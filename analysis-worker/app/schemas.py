from pydantic import BaseModel, Field


class Point(BaseModel):
    x: float
    y: float


class CourtCalibration(BaseModel):
    """Image points ordered: top-left, top-right, bottom-right, bottom-left."""

    corners: list[Point] = Field(min_length=4, max_length=4)
    player: Point


class AnalysisSummary(BaseModel):
    duration_seconds: float
    analysed_frames: int
    tracked_frames: int
    tracking_coverage_percent: float
    distance_metres: float
    average_speed_kmh: float
    maximum_speed_kmh: float
    net_zone_percent: float
    transition_zone_percent: float
    back_court_percent: float
    recovery_events: int
    median_recovery_seconds: float | None
    recovery_within_two_seconds_percent: float | None


class AnalysisResult(BaseModel):
    version: str = "0.1"
    summary: AnalysisSummary
    positions: list[dict[str, float]]
    heatmap: list[list[float]]
    warnings: list[str]


class JobState(BaseModel):
    id: str
    status: str
    progress: int = 0
    message: str = "Queued"
    result: AnalysisResult | None = None
    error: str | None = None

