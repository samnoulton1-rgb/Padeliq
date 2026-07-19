from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .analyzer import PadelAnalyzer
from .schemas import CourtCalibration, JobState, OutcomeJobState, PositionPoint
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
outcome_jobs: dict[str, OutcomeJobState] = {}
jobs_lock = threading.Lock()
model_lock = threading.Lock()
analyzer: PadelAnalyzer | None = None
feedback_analyzer: VideoFeedbackAnalyzer | None = None
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(500 * 1024 * 1024)))
MAX_ACTIVE_JOBS = int(os.getenv("MAX_ACTIVE_JOBS", "2"))
DIAGNOSTIC_RETENTION_HOURS = int(os.getenv("DIAGNOSTIC_RETENTION_HOURS", "24"))
DIAGNOSTIC_ROOT = Path(tempfile.gettempdir()) / "padeliq-diagnostics"
diagnostics: dict[str, dict[str, str | Path | datetime]] = {}


def cleanup_expired_diagnostics() -> None:
    now = datetime.now(timezone.utc)
    for token, item in list(diagnostics.items()):
        if item["expires_at"] <= now:
            shutil.rmtree(Path(item["directory"]), ignore_errors=True)
            diagnostics.pop(token, None)


def update_job(job_id: str, **values) -> None:
    with jobs_lock:
        job = jobs[job_id]
        jobs[job_id] = job.model_copy(update=values)


def run_job(job_id: str, video_path: Path, calibration: CourtCalibration, retain_diagnostic: bool) -> None:
    global analyzer, feedback_analyzer
    try:
        update_job(job_id, status="processing", progress=2, message="Loading analysis model")
        if analyzer is None:
            analyzer = PadelAnalyzer(os.getenv("MODEL_ID", "PekingU/rtdetr_r50vd"))
        # The marked overlay is also the input for selected-player rally review.
        diagnostic_path = video_path.parent / "tracking-diagnostic.mp4"
        result = analyzer.analyze(
            video_path,
            calibration,
            lambda progress, message: update_job(job_id, progress=progress, message=message),
            diagnostic_path=diagnostic_path,
        )
        # Complete the measured positioning report immediately. Video-LLM rally
        # review is launched separately by the client for retained videos, so a
        # slow model load or generation can never hold the core report at 98%.
        if result.summary.quality_status != "reliable":
            result.warnings.append("AI coaching was skipped because the tracking quality gate was not met.")
        if retain_diagnostic:
            token = uuid.uuid4().hex
            expires_at = datetime.now(timezone.utc) + timedelta(hours=DIAGNOSTIC_RETENTION_HOURS)
            DIAGNOSTIC_ROOT.mkdir(parents=True, exist_ok=True)
            retained_directory = DIAGNOSTIC_ROOT / token
            shutil.move(str(video_path.parent), retained_directory)
            diagnostics[token] = {
                "directory": retained_directory,
                "video": retained_directory / video_path.name,
                "overlay": retained_directory / "tracking-diagnostic.mp4",
                "expires_at": expires_at,
            }
            result.diagnostic_token = token
            result.diagnostic_available_until = expires_at.isoformat()
        update_job(job_id, status="complete", progress=100, message="Complete", result=result)
    except Exception as exc:
        update_job(job_id, status="failed", message="Analysis failed", error=str(exc))
    finally:
        if video_path.parent.exists():
            shutil.rmtree(video_path.parent, ignore_errors=True)


def run_outcome_job(token: str, video_path: Path, positions: list[PositionPoint], cleanup_directory: bool = True) -> None:
    global feedback_analyzer
    try:
        outcome_jobs[token] = outcome_jobs[token].model_copy(
            update={"status": "processing", "progress": 10, "message": "Finding likely rally endings"}
        )
        if feedback_analyzer is None:
            feedback_analyzer = VideoFeedbackAnalyzer()
        with model_lock:
            rallies = feedback_analyzer.analyze_rallies(video_path, positions)
        outcome_jobs[token] = outcome_jobs[token].model_copy(
            update={"status": "complete", "progress": 100, "message": "Outcome estimates ready", "rallies": rallies}
        )
    except Exception as exc:
        outcome_jobs[token] = outcome_jobs[token].model_copy(
            update={"status": "failed", "message": "Outcome analysis failed", "error": str(exc)}
        )
    finally:
        if cleanup_directory:
            shutil.rmtree(video_path.parent, ignore_errors=True)


@app.get("/health")
def health() -> dict[str, str | bool]:
    return {
        "status": "ok",
        "service": "padeliq-analysis",
        "version": "0.6.3",
        "tracking_model": os.getenv("MODEL_ID", "PekingU/rtdetr_r50vd"),
        "video_llm": os.getenv("VLM_MODEL_ID", "Qwen/Qwen3-VL-2B-Instruct"),
        "video_llm_enabled": os.getenv("ENABLE_VIDEO_LLM", "true").lower() == "true",
    }


@app.post("/outcome-jobs", response_model=OutcomeJobState, status_code=202)
async def create_outcome_job(
    background_tasks: BackgroundTasks,
    video: UploadFile = File(...),
    positions: str = Form(...),
    token: str | None = Form(None),
) -> OutcomeJobState:
    if video.content_type and not video.content_type.startswith("video/"):
        raise HTTPException(415, "A video file is required")
    try:
        parsed_positions = [PositionPoint.model_validate(item) for item in json.loads(positions)]
    except Exception as exc:
        raise HTTPException(422, f"Invalid tracked positions: {exc}") from exc
    if not parsed_positions:
        raise HTTPException(422, "Tracked positions are required")
    outcome_token = token or uuid.uuid4().hex
    existing = outcome_jobs.get(outcome_token)
    if existing and existing.status in {"queued", "processing", "complete"}:
        return existing
    directory = Path(tempfile.mkdtemp(prefix="padeliq-outcomes-"))
    video_path = directory / "marked-player.mp4"
    uploaded_bytes = 0
    with video_path.open("wb") as target:
        while chunk := await video.read(1024 * 1024):
            uploaded_bytes += len(chunk)
            if uploaded_bytes > MAX_UPLOAD_BYTES:
                shutil.rmtree(directory, ignore_errors=True)
                raise HTTPException(413, "The uploaded video is too large")
            target.write(chunk)
    state = OutcomeJobState(token=outcome_token, status="queued")
    outcome_jobs[outcome_token] = state
    background_tasks.add_task(run_outcome_job, outcome_token, video_path, parsed_positions)
    return state


@app.post("/outcomes/{token}", response_model=OutcomeJobState, status_code=202)
async def create_retained_outcome_job(
    token: str,
    background_tasks: BackgroundTasks,
    positions: str = Form(...),
) -> OutcomeJobState:
    cleanup_expired_diagnostics()
    item = diagnostics.get(token)
    if item is None:
        raise HTTPException(404, "Retained video not found or expired")
    try:
        parsed_positions = [PositionPoint.model_validate(point) for point in json.loads(positions)]
    except Exception as exc:
        raise HTTPException(422, f"Invalid tracked positions: {exc}") from exc
    if not parsed_positions:
        raise HTTPException(422, "Tracked positions are required")
    existing = outcome_jobs.get(token)
    if existing and existing.status in {"queued", "processing", "complete"}:
        return existing
    state = OutcomeJobState(token=token, status="queued", message="Queued for point-outcome review")
    outcome_jobs[token] = state
    background_tasks.add_task(run_outcome_job, token, Path(item["video"]), parsed_positions, False)
    return state


@app.get("/outcomes/{token}", response_model=OutcomeJobState)
def get_outcomes(token: str) -> OutcomeJobState:
    if token not in outcome_jobs:
        raise HTTPException(404, "Outcome analysis not found")
    return outcome_jobs[token]


@app.post("/jobs", response_model=JobState, status_code=202)
async def create_job(
    background_tasks: BackgroundTasks,
    video: UploadFile = File(...),
    calibration: str = Form(...),
    retain_diagnostic: bool = Form(False),
) -> JobState:
    cleanup_expired_diagnostics()
    if video.content_type and not video.content_type.startswith("video/"):
        raise HTTPException(415, "A video file is required")
    with jobs_lock:
        active_jobs = sum(job.status in {"queued", "processing"} for job in jobs.values())
    if active_jobs >= MAX_ACTIVE_JOBS:
        raise HTTPException(429, "The analysis service is busy. Please try again shortly.")
    try:
        parsed_calibration = CourtCalibration.model_validate(json.loads(calibration))
    except Exception as exc:
        raise HTTPException(422, f"Invalid court calibration: {exc}") from exc
    job_id = str(uuid.uuid4())
    directory = Path(tempfile.mkdtemp(prefix="padeliq-"))
    suffix = Path(video.filename or "match.mp4").suffix or ".mp4"
    video_path = directory / f"match{suffix}"
    uploaded_bytes = 0
    with video_path.open("wb") as target:
        while chunk := await video.read(1024 * 1024):
            uploaded_bytes += len(chunk)
            if uploaded_bytes > MAX_UPLOAD_BYTES:
                shutil.rmtree(directory, ignore_errors=True)
                raise HTTPException(413, "The uploaded video is too large")
            target.write(chunk)
    state = JobState(id=job_id, status="queued")
    jobs[job_id] = state
    background_tasks.add_task(run_job, job_id, video_path, parsed_calibration, retain_diagnostic)
    return state


@app.get("/jobs/{job_id}", response_model=JobState)
def get_job(job_id: str) -> JobState:
    if job_id not in jobs:
        raise HTTPException(404, "Analysis job not found")
    return jobs[job_id]


@app.get("/diagnostics/{token}/{kind}")
def get_diagnostic(token: str, kind: str) -> FileResponse:
    cleanup_expired_diagnostics()
    item = diagnostics.get(token)
    if item is None or kind not in {"video", "overlay"}:
        raise HTTPException(404, "Diagnostic file not found or expired")
    path = Path(item[kind])
    if not path.exists():
        raise HTTPException(404, "Diagnostic file not found")
    media_type = "video/mp4"
    filename = "padeliq-source-video" + path.suffix if kind == "video" else "padeliq-tracking-diagnostic.mp4"
    return FileResponse(path, media_type=media_type, filename=filename)
