from __future__ import annotations

import math
from pathlib import Path
from typing import Callable

import cv2
import numpy as np
import supervision as sv
import torch
from scipy.ndimage import gaussian_filter
from transformers import RTDetrForObjectDetection, RTDetrImageProcessor

from .schemas import AnalysisResult, AnalysisSummary, CourtCalibration, PairAnalysis, PairEvent, PlayerReference

COURT_WIDTH_METRES = 10.0
COURT_LENGTH_METRES = 20.0
MAX_PLAUSIBLE_SPEED_MPS = 9.0
MIN_RELIABLE_COVERAGE = 70.0
MAX_INTERPOLATION_SECONDS = 1.0


class PadelAnalyzer:
    def __init__(self, model_id: str = "PekingU/rtdetr_r50vd") -> None:
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.processor = RTDetrImageProcessor.from_pretrained(model_id)
        self.model = RTDetrForObjectDetection.from_pretrained(model_id).to(self.device)
        self.model.eval()

    def _detect_people(self, frame: np.ndarray) -> sv.Detections:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        inputs = self.processor(images=rgb, return_tensors="pt").to(self.device)
        with torch.inference_mode():
            outputs = self.model(**inputs)
        target = torch.tensor([rgb.shape[:2]], device=self.device)
        result = self.processor.post_process_object_detection(outputs, target_sizes=target, threshold=0.24)[0]
        boxes, scores = [], []
        for score, label, box in zip(result["scores"], result["labels"], result["boxes"]):
            if self.model.config.id2label[int(label)].lower() == "person":
                boxes.append(box.detach().cpu().numpy())
                scores.append(float(score))
        if not boxes:
            return sv.Detections.empty()
        return sv.Detections(xyxy=np.asarray(boxes), confidence=np.asarray(scores))

    @staticmethod
    def _homography(calibration: CourtCalibration) -> np.ndarray:
        source = np.float32([[point.x, point.y] for point in calibration.corners])
        destination = np.float32(
            [[0, 0], [COURT_WIDTH_METRES, 0], [COURT_WIDTH_METRES, COURT_LENGTH_METRES], [0, COURT_LENGTH_METRES]]
        )
        matrix = cv2.getPerspectiveTransform(source, destination)
        if abs(np.linalg.det(matrix)) < 1e-9:
            raise ValueError("Court calibration points do not form a valid court polygon")
        return matrix

    @staticmethod
    def _to_court(matrix: np.ndarray, image_point: tuple[float, float]) -> tuple[float, float]:
        point = np.asarray([[[image_point[0], image_point[1]]]], dtype=np.float32)
        mapped = cv2.perspectiveTransform(point, matrix)[0, 0]
        return float(mapped[0]), float(mapped[1])

    @staticmethod
    def _feet(box: np.ndarray) -> tuple[float, float]:
        return float((box[0] + box[2]) / 2), float(box[3])

    @staticmethod
    def _appearance(frame: np.ndarray, box: np.ndarray) -> np.ndarray | None:
        height, width = frame.shape[:2]
        x1, y1, x2, y2 = box.astype(int)
        x1, x2 = max(0, x1), min(width, x2)
        y1, y2 = max(0, y1), min(height, y2)
        body_bottom = y1 + max(1, round((y2 - y1) * 0.72))
        crop = frame[y1:body_bottom, x1:x2]
        if crop.size < 100:
            return None
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        histogram = cv2.calcHist([hsv], [0, 1], None, [24, 16], [0, 180, 0, 256])
        return cv2.normalize(histogram, histogram).flatten()

    @staticmethod
    def _appearance_distance(left: np.ndarray | None, right: np.ndarray | None) -> float:
        if left is None or right is None:
            return 0.45
        return float(cv2.compareHist(left.astype(np.float32), right.astype(np.float32), cv2.HISTCMP_BHATTACHARYYA))

    @staticmethod
    def _near_reference(references: list[PlayerReference], timestamp: float, tolerance: float = 1.25) -> PlayerReference | None:
        reference = min(references, key=lambda item: abs(item.t - timestamp))
        return reference if abs(reference.t - timestamp) <= tolerance else None

    @staticmethod
    def _interpolate(positions: list[dict[str, float]], sample_rate: float) -> tuple[list[dict[str, float]], int]:
        if len(positions) < 2:
            return positions, 0
        output: list[dict[str, float]] = [positions[0]]
        interpolated = 0
        max_steps = max(1, round(MAX_INTERPOLATION_SECONDS * sample_rate))
        for previous, current in zip(positions, positions[1:]):
            missing = int(current["sample"] - previous["sample"] - 1)
            if 0 < missing <= max_steps:
                for step in range(1, missing + 1):
                    ratio = step / (missing + 1)
                    output.append(
                        {
                            "t": previous["t"] + (current["t"] - previous["t"]) * ratio,
                            "x": previous["x"] + (current["x"] - previous["x"]) * ratio,
                            "y": previous["y"] + (current["y"] - previous["y"]) * ratio,
                            "sample": previous["sample"] + step,
                            "source": "interpolated",
                        }
                    )
                    interpolated += 1
            output.append(current)
        return output, interpolated

    @staticmethod
    def _recovery_metrics(positions: list[dict[str, float]]) -> tuple[int, float | None, float | None]:
        if len(positions) < 20:
            return 0, None, None
        coords = np.asarray([[p["x"], p["y"]] for p in positions])
        base = np.median(coords, axis=0)
        radius = np.linalg.norm(coords - base, axis=1)
        times = np.asarray([p["t"] for p in positions])
        durations: list[float] = []
        outside = False
        start = 0.0
        for distance, timestamp in zip(radius, times):
            if not outside and distance >= 3.0:
                outside, start = True, timestamp
            elif outside and distance <= 1.5:
                durations.append(float(timestamp - start))
                outside = False
        if not durations:
            return 0, None, None
        within_two = sum(duration <= 2.0 for duration in durations) / len(durations) * 100
        return len(durations), float(np.median(durations)), float(within_two)

    def _choose_target(
        self,
        frame: np.ndarray,
        detections: sv.Detections,
        matrix: np.ndarray,
        current_id: int | None,
        last_position: dict[str, float] | None,
        appearance: np.ndarray | None,
        reference: PlayerReference | None,
        preferred_half: int | None,
        timestamp: float,
        excluded_tracker_ids: set[int] | None = None,
    ) -> tuple[int | None, int | None, tuple[float, float] | None, np.ndarray | None]:
        if detections.tracker_id is None:
            return None, None, None, appearance
        diagonal = math.hypot(frame.shape[1], frame.shape[0])
        best: tuple[float, int, int, tuple[float, float], np.ndarray | None] | None = None
        for index, (box, tracker_id) in enumerate(zip(detections.xyxy, detections.tracker_id)):
            if excluded_tracker_ids and int(tracker_id) in excluded_tracker_ids:
                continue
            feet = self._feet(box)
            court = self._to_court(matrix, feet)
            if not (-0.75 <= court[0] <= 10.75 and -0.75 <= court[1] <= 20.75):
                continue
            candidate_appearance = self._appearance(frame, box)
            score = self._appearance_distance(appearance, candidate_appearance) * 3.5
            if last_position is not None:
                elapsed = max(0.125, timestamp - last_position["t"])
                distance = math.hypot(court[0] - last_position["x"], court[1] - last_position["y"])
                score += distance / max(1.5, min(7.0, MAX_PLAUSIBLE_SPEED_MPS * elapsed)) * 2.5
            if reference is not None:
                score += math.hypot(feet[0] - reference.x, feet[1] - reference.y) / max(1, diagonal) * 12
            if preferred_half is not None and (0 if court[1] < 10 else 1) != preferred_half:
                score += 2.5
            if current_id is not None and int(tracker_id) == current_id:
                score -= 1.2
            confidence = float(detections.confidence[index]) if detections.confidence is not None else 0.5
            score += max(0, 0.55 - confidence)
            candidate = (score, index, int(tracker_id), court, candidate_appearance)
            if best is None or candidate[0] < best[0]:
                best = candidate
        if best is None or best[0] > (7.0 if reference is not None else 4.8):
            return None, None, None, appearance
        _, index, tracker_id, court, candidate_appearance = best
        return index, tracker_id, court, candidate_appearance

    @staticmethod
    def _pair_analysis(
        positions: list[dict[str, float]],
        partner_positions: list[dict[str, float]],
        analysed: int,
        partner_direct_tracked: int,
        self_quality: str,
    ) -> PairAnalysis:
        me_by_sample = {int(point["sample"]): point for point in positions}
        partner_by_sample = {int(point["sample"]): point for point in partner_positions}
        joined = [(me_by_sample[key], partner_by_sample[key]) for key in sorted(me_by_sample.keys() & partner_by_sample.keys())]
        pair_coverage = len(joined) / max(1, analysed) * 100
        partner_direct_coverage = partner_direct_tracked / max(1, analysed) * 100
        reliable = self_quality == "reliable" and pair_coverage >= 60 and partner_direct_coverage >= 50

        def depth(point: dict[str, float]) -> float:
            return point["y"] if point["y"] <= 10 else 20 - point["y"]

        aligned = healthy = middle_protected = 0
        gaps: list[float] = []
        events: list[PairEvent] = []
        last_event_at = -10.0
        for me, partner in joined:
            me_depth, partner_depth = depth(me), depth(partner)
            depth_gap = abs(me_depth - partner_depth)
            left_x, right_x = sorted((me["x"], partner["x"]))
            middle_gap = right_x - left_x
            pair_gap = math.hypot(me["x"] - partner["x"], me_depth - partner_depth)
            gaps.append(pair_gap)
            aligned += depth_gap <= 2.5
            healthy += 2.0 <= pair_gap <= 6.0
            middle_protected += middle_gap <= 5.0
            candidates = [
                (depth_gap, "depth_split", "Different court depths left one player isolated", depth_gap),
                (middle_gap, "middle_gap", "A large central gap opened between the pair", middle_gap),
                (left_x, "left_space", "Potential open space appeared in the left channel", left_x),
                (10 - right_x, "right_space", "Potential open space appeared in the right channel", 10 - right_x),
            ]
            severity, event_type, label, gap = max(candidates, key=lambda item: item[0])
            threshold = 4.0 if event_type == "depth_split" else 4.5
            if severity >= threshold and me["t"] - last_event_at >= 3.0:
                events.append(PairEvent(t=round(me["t"], 2), type=event_type, label=label, gap_metres=round(gap, 1), me_x=round(me["x"], 2), me_y=round(me["y"], 2), partner_x=round(partner["x"], 2), partner_y=round(partner["y"], 2)))
                last_event_at = me["t"]

        coordinated = opportunities = 0
        for (previous_me, previous_partner), (me, partner) in zip(joined, joined[1:]):
            me_change = depth(me) - depth(previous_me)
            partner_change = depth(partner) - depth(previous_partner)
            if max(abs(me_change), abs(partner_change)) < 0.35:
                continue
            opportunities += 1
            coordinated += abs(me_change) >= 0.15 and abs(partner_change) >= 0.15 and me_change * partner_change > 0
        transition_percent = coordinated / opportunities * 100 if opportunities else None
        count = max(1, len(joined))
        alignment_percent = aligned / count * 100
        spacing_percent = healthy / count * 100
        middle_percent = middle_protected / count * 100
        transition_for_score = transition_percent if transition_percent is not None else 60.0
        score = round(alignment_percent * .30 + spacing_percent * .25 + transition_for_score * .20 + middle_percent * .25) if reliable else None
        public_partner = [{key: value for key, value in point.items() if key != "sample"} for point in partner_positions[::4]]
        return PairAnalysis(
            quality_status="reliable" if reliable else "unreliable",
            pair_tracking_coverage_percent=round(pair_coverage, 1),
            partner_direct_tracking_coverage_percent=round(partner_direct_coverage, 1),
            partner_positions=public_partner,
            alignment_percent=round(alignment_percent, 1),
            healthy_spacing_percent=round(spacing_percent, 1),
            coordinated_transition_percent=round(transition_percent, 1) if transition_percent is not None else None,
            middle_protection_percent=round(middle_percent, 1),
            average_partner_gap_metres=round(float(np.mean(gaps)), 1) if gaps else 0,
            largest_partner_gap_metres=round(max(gaps), 1) if gaps else 0,
            pair_movement_score=score,
            open_space_events=events[:16],
        )

    def analyze(
        self,
        video_path: Path,
        calibration: CourtCalibration,
        progress: Callable[[int, str], None],
        diagnostic_path: Path | None = None,
    ) -> AnalysisResult:
        capture = cv2.VideoCapture(str(video_path))
        if not capture.isOpened():
            raise ValueError("The uploaded video could not be opened")
        fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = total_frames / fps if total_frames else 0.0
        sample_rate = 8.0
        sample_every = max(1, round(fps / sample_rate))
        expected_samples = max(1, total_frames // sample_every)
        matrix = self._homography(calibration)
        references = calibration.references()
        partner_references = sorted(calibration.partner_references, key=lambda point: point.t)
        initial_court = self._to_court(matrix, (references[0].x, references[0].y))
        preferred_half = 0 if initial_court[1] < 10 else 1
        tracker = sv.ByteTrack(frame_rate=max(1, round(fps / sample_every)), lost_track_buffer=60)
        selected_id: int | None = None
        partner_id: int | None = None
        target_appearance: np.ndarray | None = None
        partner_appearance: np.ndarray | None = None
        positions: list[dict[str, float]] = []
        partner_positions: list[dict[str, float]] = []
        analysed = direct_tracked = partner_direct_tracked = frame_index = sample_index = 0
        missing_samples = partner_missing_samples = reacquisitions = partner_reacquisitions = 0
        writer: cv2.VideoWriter | None = None

        while True:
            ok, frame = capture.read()
            if not ok:
                break
            if frame_index % sample_every:
                frame_index += 1
                continue
            if diagnostic_path is not None and writer is None:
                height, width = frame.shape[:2]
                writer = cv2.VideoWriter(str(diagnostic_path), cv2.VideoWriter_fourcc(*"mp4v"), sample_rate, (width, height))
            detections = tracker.update_with_detections(self._detect_people(frame))
            analysed += 1
            timestamp = frame_index / fps
            reference = self._near_reference(references, timestamp)
            side_reference = min(references, key=lambda item: abs(item.t - timestamp))
            side_court = self._to_court(matrix, (side_reference.x, side_reference.y))
            current_preferred_half = 0 if side_court[1] < 10 else 1
            previous_id = selected_id
            index, candidate_id, court, candidate_appearance = self._choose_target(
                frame,
                detections,
                matrix,
                selected_id,
                positions[-1] if positions else None,
                target_appearance,
                reference,
                current_preferred_half,
                timestamp,
                {partner_id} if partner_id is not None else None,
            )
            if index is not None and court is not None:
                if previous_id is not None and candidate_id != previous_id and missing_samples:
                    reacquisitions += 1
                selected_id = candidate_id
                missing_samples = 0
                if target_appearance is None:
                    target_appearance = candidate_appearance
                elif candidate_appearance is not None:
                    target_appearance = target_appearance * 0.88 + candidate_appearance * 0.12
                positions.append(
                    {"t": timestamp, "x": court[0], "y": court[1], "sample": sample_index, "source": "detected"}
                )
                direct_tracked += 1
            else:
                missing_samples += 1
                if missing_samples > round(sample_rate * 1.5):
                    selected_id = None

            partner_index = None
            if partner_references:
                partner_reference = self._near_reference(partner_references, timestamp)
                partner_side_reference = min(partner_references, key=lambda item: abs(item.t - timestamp))
                partner_side_court = self._to_court(matrix, (partner_side_reference.x, partner_side_reference.y))
                partner_preferred_half = 0 if partner_side_court[1] < 10 else 1
                previous_partner_id = partner_id
                partner_index, partner_candidate_id, partner_court, partner_candidate_appearance = self._choose_target(
                    frame, detections, matrix, partner_id,
                    partner_positions[-1] if partner_positions else None,
                    partner_appearance, partner_reference, partner_preferred_half, timestamp,
                    {selected_id} if selected_id is not None else None,
                )
                if partner_index is not None and partner_court is not None:
                    if previous_partner_id is not None and partner_candidate_id != previous_partner_id and partner_missing_samples:
                        partner_reacquisitions += 1
                    partner_id = partner_candidate_id
                    partner_missing_samples = 0
                    if partner_appearance is None:
                        partner_appearance = partner_candidate_appearance
                    elif partner_candidate_appearance is not None:
                        partner_appearance = partner_appearance * .88 + partner_candidate_appearance * .12
                    partner_positions.append({"t": timestamp, "x": partner_court[0], "y": partner_court[1], "sample": sample_index, "source": "detected"})
                    partner_direct_tracked += 1
                else:
                    partner_missing_samples += 1
                    if partner_missing_samples > round(sample_rate * 1.5):
                        partner_id = None

            if writer is not None:
                for detection_index, box in enumerate(detections.xyxy):
                    track_id = int(detections.tracker_id[detection_index]) if detections.tracker_id is not None else -1
                    colour = (62, 211, 89) if index == detection_index else (220, 120, 70) if partner_index == detection_index else (120, 160, 185)
                    x1, y1, x2, y2 = box.astype(int)
                    cv2.rectangle(frame, (x1, y1), (x2, y2), colour, 3 if detection_index in {index, partner_index} else 1)
                    identity = "ME" if index == detection_index else "PARTNER" if partner_index == detection_index else f"ID {track_id}"
                    cv2.putText(frame, identity, (x1, max(20, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, colour, 2)
                polygon = np.asarray([[[round(point.x), round(point.y)] for point in calibration.corners]], dtype=np.int32)
                cv2.polylines(frame, polygon, True, (255, 200, 60), 2)
                cv2.putText(frame, f"Tracked {direct_tracked}/{analysed}", (20, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
                writer.write(frame)
            if analysed % 10 == 0:
                progress(min(94, 5 + round(analysed / expected_samples * 89)), "Tracking selected player and partner" if partner_references else "Tracking and re-identifying selected player")
            frame_index += 1
            sample_index += 1
        capture.release()
        if writer is not None:
            writer.release()

        if len(positions) < 2:
            raise ValueError("The selected player could not be tracked reliably")
        positions, interpolated = self._interpolate(positions, sample_rate)
        partner_interpolated = 0
        if partner_positions:
            partner_positions, partner_interpolated = self._interpolate(partner_positions, sample_rate)
        usable_coverage = min(100.0, len(positions) / max(1, analysed) * 100)
        direct_coverage = direct_tracked / max(1, analysed) * 100
        quality_status = "reliable" if usable_coverage >= MIN_RELIABLE_COVERAGE and direct_coverage >= 55 else "unreliable"

        distance = 0.0
        valid_speeds: list[float] = []
        for previous, current in zip(positions, positions[1:]):
            elapsed = current["t"] - previous["t"]
            segment = math.hypot(current["x"] - previous["x"], current["y"] - previous["y"])
            speed = segment / elapsed if elapsed else 0.0
            if speed <= MAX_PLAUSIBLE_SPEED_MPS:
                distance += segment
                valid_speeds.append(speed)

        heatmap, _, _ = np.histogram2d(
            [p["y"] for p in positions], [p["x"] for p in positions], bins=(40, 20), range=((0, 20), (0, 10))
        )
        heatmap = gaussian_filter(heatmap, sigma=1.35)
        if heatmap.max():
            heatmap /= heatmap.max()
        back = sum(p["y"] >= 14 or p["y"] <= 6 for p in positions)
        net = sum(8 <= p["y"] <= 12 for p in positions)
        transition = len(positions) - back - net
        recoveries, median_recovery, within_two = self._recovery_metrics(positions)
        warnings = [
            "Recovery is an excursion-to-base proxy until shot contact events are available.",
            "Distance is filtered to remove implausible tracking jumps.",
            f"{interpolated} short-gap positions were interpolated and are identified separately from detections.",
        ]
        if quality_status == "unreliable":
            warnings.append("Quality gate failed; performance scores are withheld until usable coverage reaches 70% with at least 55% direct detections.")
        pair_analysis = None
        if partner_references and partner_positions:
            pair_analysis = self._pair_analysis(positions, partner_positions, analysed, partner_direct_tracked, quality_status)
            warnings.append(f"Partner tracking used {partner_direct_tracked} direct detections and {partner_interpolated} short-gap estimates.")
            if pair_analysis.quality_status == "unreliable":
                warnings.append("Pair scores are withheld because both-player tracking did not meet the pair reliability gate.")
        summary = AnalysisSummary(
            duration_seconds=round(duration, 2),
            analysed_frames=analysed,
            tracked_frames=len(positions),
            tracking_coverage_percent=round(usable_coverage, 1),
            direct_tracking_coverage_percent=round(direct_coverage, 1),
            interpolated_frames=interpolated,
            identity_reacquisitions=reacquisitions,
            quality_status=quality_status,
            distance_metres=round(distance, 1),
            average_speed_kmh=round((np.mean(valid_speeds) if valid_speeds else 0) * 3.6, 1),
            maximum_speed_kmh=round((max(valid_speeds) if valid_speeds else 0) * 3.6, 1),
            net_zone_percent=round(net / len(positions) * 100, 1),
            transition_zone_percent=round(transition / len(positions) * 100, 1),
            back_court_percent=round(back / len(positions) * 100, 1),
            recovery_events=recoveries,
            median_recovery_seconds=round(median_recovery, 2) if median_recovery is not None else None,
            recovery_within_two_seconds_percent=round(within_two, 1) if within_two is not None else None,
        )
        progress(98, "Creating report")
        public_positions = [{key: value for key, value in point.items() if key != "sample"} for point in positions[::4]]
        return AnalysisResult(summary=summary, positions=public_positions, pair_analysis=pair_analysis, heatmap=heatmap.round(4).tolist(), warnings=warnings)
