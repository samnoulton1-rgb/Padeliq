from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Callable

import cv2
import numpy as np
from PIL import Image

from .schemas import AIFeedback, AnalysisSummary, PositionPoint, RallyOutcome


class VideoFeedbackAnalyzer:
    """Produces cautious coaching notes from sampled frames plus measured CV metrics."""

    def __init__(self) -> None:
        self.model_id = os.getenv("VLM_MODEL_ID", "Qwen/Qwen3-VL-2B-Instruct")
        self.model = None
        self.processor = None

    def _load(self) -> None:
        if self.model is not None:
            return
        import torch
        from transformers import AutoModelForMultimodalLM, AutoProcessor

        self.processor = AutoProcessor.from_pretrained(self.model_id)
        self.model = AutoModelForMultimodalLM.from_pretrained(
            self.model_id,
            torch_dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32,
            device_map="auto",
            low_cpu_mem_usage=True,
        )

    @staticmethod
    def _frames(video_path: Path, count: int = 8) -> list[Image.Image]:
        capture = cv2.VideoCapture(str(video_path))
        total = max(1, int(capture.get(cv2.CAP_PROP_FRAME_COUNT)))
        images: list[Image.Image] = []
        for index in range(count):
            capture.set(cv2.CAP_PROP_POS_FRAMES, round((index + 0.5) * total / count))
            ok, frame = capture.read()
            if not ok:
                continue
            height, width = frame.shape[:2]
            scale = min(1.0, 768 / max(height, width))
            if scale < 1:
                frame = cv2.resize(frame, (round(width * scale), round(height * scale)))
            images.append(Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)))
        capture.release()
        return images

    @staticmethod
    def _json(text: str) -> dict:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise ValueError("The video model did not return structured feedback")
        return json.loads(match.group(0))

    @staticmethod
    def _rally_windows(video_path: Path) -> list[tuple[float, float]]:
        capture = cv2.VideoCapture(str(video_path))
        fps = capture.get(cv2.CAP_PROP_FPS) or 8.0
        total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = total / fps if total else 0
        sample_every = max(1, round(fps / 4))
        previous = None
        samples: list[tuple[float, float]] = []
        frame_index = 0
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            if frame_index % sample_every:
                frame_index += 1
                continue
            gray = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (192, 108))
            score = 0.0 if previous is None else float(np.mean(cv2.absdiff(gray, previous)))
            samples.append((frame_index / fps, score))
            previous = gray
            frame_index += 1
        capture.release()
        if len(samples) < 12:
            return [(0.0, duration)] if duration >= 3 else []
        scores = np.asarray([score for _, score in samples], dtype=float)
        smoothed = np.convolve(scores, np.ones(5) / 5, mode="same")
        threshold = max(2.0, float(np.percentile(smoothed, 52)))
        active = smoothed >= threshold
        windows: list[tuple[float, float]] = []
        start: float | None = None
        quiet = 0
        for (timestamp, _), is_active in zip(samples, active):
            if is_active and start is None:
                start = max(0.0, timestamp - 0.75)
            if start is None:
                continue
            quiet = 0 if is_active else quiet + 1
            if quiet >= 6:
                end = timestamp - quiet / 4 + 0.75
                if end - start >= 3:
                    windows.append((start, min(duration, end)))
                start, quiet = None, 0
        if start is not None and duration - start >= 3:
            windows.append((start, duration))
        merged: list[tuple[float, float]] = []
        for window in windows:
            if merged and window[0] - merged[-1][1] < 1.5:
                merged[-1] = (merged[-1][0], window[1])
            else:
                merged.append(window)
        return merged[: max(1, int(os.getenv("MAX_RALLY_CANDIDATES", "16")))]

    @staticmethod
    def _window_frames(video_path: Path, start: float, end: float, count: int = 3) -> list[Image.Image]:
        capture = cv2.VideoCapture(str(video_path))
        images: list[Image.Image] = []
        window_start = max(start, end - 4.5)
        for timestamp in np.linspace(window_start, end, count):
            capture.set(cv2.CAP_PROP_POS_MSEC, float(timestamp) * 1000)
            ok, frame = capture.read()
            if not ok:
                continue
            height, width = frame.shape[:2]
            scale = min(1.0, 640 / max(height, width))
            if scale < 1:
                frame = cv2.resize(frame, (round(width * scale), round(height * scale)))
            images.append(Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)))
        capture.release()
        return images

    def analyze_rallies(
        self,
        marked_video_path: Path,
        positions: list[PositionPoint],
        partner_positions: list[PositionPoint] | None = None,
        progress_callback: Callable[[int, str], None] | None = None,
    ) -> list[RallyOutcome]:
        self._load()
        windows = self._rally_windows(marked_video_path)
        outcomes: list[RallyOutcome] = []
        for batch_start in range(0, len(windows), 4):
            batch = windows[batch_start : batch_start + 4]
            content: list[dict] = []
            for local_index, (start, end) in enumerate(batch):
                rally_index = batch_start + local_index + 1
                content.append({"type": "text", "text": f"Candidate rally {rally_index}, ending near {end:.1f} seconds. The selected player is enclosed by the GREEN tracking box."})
                content.extend({"type": "image", "image": image} for image in self._window_frames(marked_video_path, start, end))
            prompt = f"""You are reviewing the final seconds of {len(batch)} candidate padel rallies.
The selected player is marked by a GREEN tracking box. For each candidate, decide whether it visibly ends a rally
and, only when the evidence is reasonably clear, whether the selected player's team WON or LOST the point.
Use the ball outcome, final player contact, all four players' reactions and preparation for the next point.
Never infer an outcome merely from where the selected player stands. If the ball or reactions do not make the
outcome clear, return unknown. Confidence must reflect visible evidence, not guesswork.

Return ONLY JSON with this exact shape:
{{"rallies":[{{"index":{batch_start + 1},"is_rally_end":true,"outcome":"won|lost|unknown","confidence":0.0,"reason":"brief visible evidence"}}]}}
Return one item for every candidate index from {batch_start + 1} to {batch_start + len(batch)}."""
            content.append({"type": "text", "text": prompt})
            inputs = self.processor.apply_chat_template(
                [{"role": "user", "content": content}], tokenize=True, add_generation_prompt=True,
                return_dict=True, return_tensors="pt"
            ).to(self.model.device)
            generated = self.model.generate(**inputs, max_new_tokens=300, do_sample=False)
            new_tokens = generated[0][inputs["input_ids"].shape[1] :]
            data = self._json(self.processor.decode(new_tokens, skip_special_tokens=True))
            by_index = {int(item.get("index", -1)): item for item in data.get("rallies", [])}
            for local_index, (start, end) in enumerate(batch):
                rally_index = batch_start + local_index + 1
                item = by_index.get(rally_index, {})
                raw_outcome = str(item.get("outcome", "unknown")).lower()
                confidence = max(0.0, min(1.0, float(item.get("confidence", 0))))
                outcome = raw_outcome if raw_outcome in {"won", "lost"} and item.get("is_rally_end") and confidence >= 0.72 else "unknown"
                nearest = min(positions, key=lambda point: abs(point.t - end)) if positions else None
                nearest_partner = min(partner_positions, key=lambda point: abs(point.t - end)) if partner_positions else None
                zone = "unknown"
                if nearest is not None:
                    zone = "net" if 8 <= nearest.y <= 12 else "back" if nearest.y <= 6 or nearest.y >= 14 else "transition"
                outcomes.append(
                    RallyOutcome(
                        id=f"rally-{rally_index}", start_seconds=round(start, 2), end_seconds=round(end, 2),
                        outcome=outcome, confidence=round(confidence, 3), x=nearest.x if nearest else None,
                        y=nearest.y if nearest else None,
                        partner_x=nearest_partner.x if nearest_partner else None,
                        partner_y=nearest_partner.y if nearest_partner else None, zone=zone,
                        reason=str(item.get("reason", "Insufficient visible evidence"))[:240], model=self.model_id,
                    )
                )
            if progress_callback:
                completed = min(len(windows), batch_start + len(batch))
                progress_callback(completed, f"Reviewed {completed} of {len(windows)} likely rally endings")
        return outcomes

    def analyze(self, video_path: Path, summary: AnalysisSummary) -> AIFeedback:
        self._load()
        images = self._frames(video_path)
        if not images:
            raise ValueError("No video frames were available for coaching feedback")
        metrics = summary.model_dump_json()
        prompt = f"""You are assisting a padel coach. These ordered frames are sparse samples from one match,
and the selected player's measured tracking metrics are: {metrics}

Only describe behaviour that is visible in multiple frames or supported by the metrics. Do not identify
shot types, winners, errors, reaction time, or ball contact unless clearly observable. Be concise and useful.
Return ONLY valid JSON with this exact shape:
{{"summary":"2 sentences", "strengths":["..."], "improvements":["..."],
"observations":["..."], "confidence":"low|medium|high"}}
Use at most 3 items in each list and make improvements practical for the next training session."""
        content = [{"type": "image", "image": image} for image in images]
        content.append({"type": "text", "text": prompt})
        messages = [{"role": "user", "content": content}]
        inputs = self.processor.apply_chat_template(
            messages, tokenize=True, add_generation_prompt=True, return_dict=True, return_tensors="pt"
        ).to(self.model.device)
        generated = self.model.generate(**inputs, max_new_tokens=500, do_sample=False)
        new_tokens = generated[0][inputs["input_ids"].shape[1] :]
        data = self._json(self.processor.decode(new_tokens, skip_special_tokens=True))
        return AIFeedback(**data, model=self.model_id)
