from typing import Literal

from pydantic import BaseModel, Field


class Point(BaseModel):
    x: float
    y: float


class PlayerReference(Point):
    t: float = Field(default=0, ge=0)


class CourtCalibration(BaseModel):
    """Image points ordered: top-left, top-right, bottom-right, bottom-left."""

    corners: list[Point] = Field(min_length=4, max_length=4)
    player: Point | None = None
    player_references: list[PlayerReference] = Field(default_factory=list, max_length=5)
    partner_references: list[PlayerReference] = Field(default_factory=list, max_length=5)

    def references(self) -> list[PlayerReference]:
        if self.player_references:
            return sorted(self.player_references, key=lambda point: point.t)
        if self.player is not None:
            return [PlayerReference(x=self.player.x, y=self.player.y, t=0)]
        raise ValueError("At least one player reference is required")


class AnalysisSummary(BaseModel):
    duration_seconds: float
    analysed_frames: int
    tracked_frames: int
    tracking_coverage_percent: float
    direct_tracking_coverage_percent: float = 0
    interpolated_frames: int = 0
    identity_reacquisitions: int = 0
    quality_status: str = "unreliable"
    distance_metres: float
    average_speed_kmh: float
    maximum_speed_kmh: float
    net_zone_percent: float
    transition_zone_percent: float
    back_court_percent: float
    recovery_events: int
    median_recovery_seconds: float | None
    recovery_within_two_seconds_percent: float | None


class AIFeedback(BaseModel):
    summary: str
    strengths: list[str] = []
    improvements: list[str] = []
    observations: list[str] = []
    confidence: str = "medium"
    model: str
    disclaimer: str = "AI coaching is an estimate from sampled video frames and tracking data; review important decisions with a qualified coach."


class PositionPoint(BaseModel):
    t: float
    x: float
    y: float
    source: Literal["detected", "interpolated"] = "detected"


class RallyOutcome(BaseModel):
    id: str
    start_seconds: float
    end_seconds: float
    outcome: Literal["won", "lost", "unknown"]
    confidence: float = Field(ge=0, le=1)
    x: float | None = None
    y: float | None = None
    zone: Literal["net", "transition", "back", "unknown"] = "unknown"
    reason: str
    model: str


class PairEvent(BaseModel):
    t: float
    type: Literal["middle_gap", "left_space", "right_space", "depth_split"]
    label: str
    gap_metres: float
    me_x: float
    me_y: float
    partner_x: float
    partner_y: float


class PairAnalysis(BaseModel):
    quality_status: Literal["reliable", "unreliable"] = "unreliable"
    pair_tracking_coverage_percent: float
    partner_direct_tracking_coverage_percent: float
    partner_positions: list[PositionPoint]
    alignment_percent: float
    healthy_spacing_percent: float
    coordinated_transition_percent: float | None
    middle_protection_percent: float
    average_partner_gap_metres: float
    largest_partner_gap_metres: float
    pair_movement_score: int | None = None
    open_space_events: list[PairEvent] = []


class AnalysisResult(BaseModel):
    version: str = "0.6.3"
    summary: AnalysisSummary
    positions: list[PositionPoint]
    rallies: list[RallyOutcome] = []
    pair_analysis: PairAnalysis | None = None
    heatmap: list[list[float]]
    warnings: list[str]
    ai_feedback: AIFeedback | None = None
    diagnostic_available_until: str | None = None
    diagnostic_token: str | None = None


class JobState(BaseModel):
    id: str
    status: str
    progress: int = 0
    message: str = "Queued"
    result: AnalysisResult | None = None
    error: str | None = None


class OutcomeJobState(BaseModel):
    token: str
    status: str
    progress: int = 0
    message: str = "Queued"
    rallies: list[RallyOutcome] = []
    error: str | None = None
