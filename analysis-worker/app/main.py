from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import uuid
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from .analyzer import PadelAnalyzer
from .schemas import CourtCalibration, JobState
from .video_feedback import VideoFeedbackAnalyzer

app = FastAPI(title="PadelIQ Analysis Worker", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv("ALLOWED_ORIGINS", "http://localhost:8000").split(",")],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

jobs: dict[str, JobState] = {}
jobs_lock = threading.Lock()
analyzer: PadelAnalyzer | None = None
feedback_analyzer: VideoFeedbackAnalyzer | None = None


def update_job(job_id: str, **values) -> None:
    with jobs_lock:
        job = jobs[job_id]
        jobs[job_id] = job.model_copy(update=values)


def run_job(job_id: str, video_path: Path, calibration: CourtCalibration) -> None:
    global analyzer, feedback_analyzer
    try:
        update_job(job_id, status="processing", progress=2, message="Loading analysis model")
        if analyzer is None:
            analyzer = PadelAnalyzer(os.getenv("MODEL_ID", "PekingU/rtdetr_r50vd"))
        result = analyzer.analyze(
            video_path,
            calibration,
            lambda progress, message: update_job(job_id, progress=progress, message=message),
        )
        if os.getenv("ENABLE_VIDEO_LLM", "true").lower() == "true":
            try:
                update_job(job_id, progress=98, message="Creating AI coaching feedback")
                if feedback_analyzer is None:
                    feedback_analyzer = VideoFeedbackAnalyzer()
                result.ai_feedback = feedback_analyzer.analyze(video_path, result.summary)
            except Exception as exc:
                result.warnings.append(f"AI coaching feedback was unavailable: {exc}")
        update_job(job_id, status="complete", progress=100, message="Complete", result=result)
    except Exception as exc:
        update_job(job_id, status="failed", message="Analysis failed", error=str(exc))
    finally:
        shutil.rmtree(video_path.parent, ignore_errors=True)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "padeliq-analysis", "version": "0.2.0"}


@app.post("/jobs", response_model=JobState, status_code=202)
async def create_job(
    background_tasks: BackgroundTasks,
    video: UploadFile = File(...),
    calibration: str = Form(...),
) -> JobState:
    if video.content_type and not video.content_type.startswith("video/"):
        raise HTTPException(415, "A video file is required")
    try:
        parsed_calibration = CourtCalibration.model_validate(json.loads(calibration))
    except Exception as exc:
        raise HTTPException(422, f"Invalid court calibration: {exc}") from exc
    job_id = str(uuid.uuid4())
    directory = Path(tempfile.mkdtemp(prefix="padeliq-"))
    suffix = Path(video.filename or "match.mp4").suffix or ".mp4"
    video_path = directory / f"match{suffix}"
    with video_path.open("wb") as target:
        while chunk := await video.read(1024 * 1024):
            target.write(chunk)
    state = JobState(id=job_id, status="queued")
    jobs[job_id] = state
    background_tasks.add_task(run_job, job_id, video_path, parsed_calibration)
    return state


@app.get("/jobs/{job_id}", response_model=JobState)
def get_job(job_id: str) -> JobState:
    if job_id not in jobs:
        raise HTTPException(404, "Analysis job not found")
    return jobs[job_id]
