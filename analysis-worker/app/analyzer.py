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

from .schemas import AnalysisResult, AnalysisSummary, CourtCalibration

COURT_WIDTH_METRES = 10.0
COURT_LENGTH_METRES = 20.0
MAX_PLAUSIBLE_SPEED_MPS = 9.0


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
        result = self.processor.post_process_object_detection(
            outputs, target_sizes=target, threshold=0.42
        )[0]
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
    def _closest_track(detections: sv.Detections, point: tuple[float, float]) -> int | None:
        if detections.tracker_id is None or len(detections) == 0:
            return None
        feet = np.column_stack(((detections.xyxy[:, 0] + detections.xyxy[:, 2]) / 2, detections.xyxy[:, 3]))
        distances = np.linalg.norm(feet - np.asarray(point), axis=1)
        index = int(np.argmin(distances))
        return int(detections.tracker_id[index])

    @staticmethod
    def _recovery_metrics(positions: list[dict[str, float]]) -> tuple[int, float | None, float | None]:
        """Estimate returns after large positional excursions; not shot-linked recovery."""
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

    def analyze(
        self,
        video_path: Path,
        calibration: CourtCalibration,
        progress: Callable[[int, str], None],
    ) -> AnalysisResult:
        capture = cv2.VideoCapture(str(video_path))
        if not capture.isOpened():
            raise ValueError("The uploaded video could not be opened")
        fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = total_frames / fps if total_frames else 0.0
        sample_every = max(1, round(fps / 8.0))
        expected_samples = max(1, total_frames // sample_every)
        matrix = self._homography(calibration)
        tracker = sv.ByteTrack(frame_rate=max(1, round(fps / sample_every)))
        selected_id: int | None = None
        selected_image_point = (calibration.player.x, calibration.player.y)
        positions: list[dict[str, float]] = []
        analysed = tracked = frame_index = 0

        while True:
            ok, frame = capture.read()
            if not ok:
                break
            if frame_index % sample_every:
                frame_index += 1
                continue
            detections = tracker.update_with_detections(self._detect_people(frame))
            analysed += 1
            if selected_id is None:
                selected_id = self._closest_track(detections, selected_image_point)
            if selected_id is not None and detections.tracker_id is not None:
                matches = np.where(detections.tracker_id == selected_id)[0]
                if len(matches):
                    box = detections.xyxy[int(matches[0])]
                    court_x, court_y = self._to_court(matrix, ((box[0] + box[2]) / 2, box[3]))
                    if -1 <= court_x <= 11 and -1 <= court_y <= 21:
                        positions.append({"t": frame_index / fps, "x": court_x, "y": court_y})
                        tracked += 1
            if analysed % 10 == 0:
                progress(min(94, 5 + round(analysed / expected_samples * 89)), "Tracking selected player")
            frame_index += 1
        capture.release()

        if len(positions) < 2:
            raise ValueError("The selected player could not be tracked reliably")

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
        ]
        if tracked / analysed < 0.75:
            warnings.append("Tracking coverage is below 75%; review the player identity and camera angle.")
        summary = AnalysisSummary(
            duration_seconds=round(duration, 2),
            analysed_frames=analysed,
            tracked_frames=tracked,
            tracking_coverage_percent=round(tracked / max(1, analysed) * 100, 1),
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
        return AnalysisResult(summary=summary, positions=positions[::4], heatmap=heatmap.round(4).tolist(), warnings=warnings)

