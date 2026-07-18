from __future__ import annotations

import json
import os
import re
from pathlib import Path

import cv2
from PIL import Image

from .schemas import AIFeedback, AnalysisSummary


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
