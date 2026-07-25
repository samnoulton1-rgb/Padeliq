from __future__ import annotations

import hashlib
import json
import math
import random
from typing import Any

SERVICE_VERSION = "0.8.0"
POSITIONING_METHOD_VERSION = "positioning-2.0"
SCORING_METHOD_VERSION = "position-score-2.0"
ANALYSIS_CONFIG_ID = "rtdetr-r50vd-8fps-deterministic-v1"
SAMPLE_RATE_FPS = 8.0
DETERMINISTIC_SEED = 20260725


def configure_determinism() -> None:
    """Use fixed inference settings so identical inputs follow the same path."""
    import cv2
    import numpy as np
    import torch

    random.seed(DETERMINISTIC_SEED)
    np.random.seed(DETERMINISTIC_SEED)
    torch.manual_seed(DETERMINISTIC_SEED)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(DETERMINISTIC_SEED)
    torch.use_deterministic_algorithms(True, warn_only=True)
    if hasattr(torch.backends, "cudnn"):
        torch.backends.cudnn.benchmark = False
        torch.backends.cudnn.deterministic = True
    cv2.setNumThreads(1)


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(payload).hexdigest()


def stable_band(value: float) -> int:
    return round(max(0.0, min(100.0, float(value))) / 5) * 5


def court_influence_percent(positions: list[dict[str, Any]]) -> int | None:
    if not positions:
        return None
    direct = [point for point in positions if point.get("source") != "interpolated"]
    samples = direct if len(direct) >= 20 else positions
    cell_size, columns, rows, influence_radius = 0.5, 20, 20, 0.75
    covered: set[tuple[int, int]] = set()
    for point in samples:
        px = max(0.0, min(10.0, float(point["x"])))
        raw_y = max(0.0, min(20.0, float(point["y"])))
        py = raw_y if raw_y <= 10 else 20 - raw_y
        min_x = max(0, math.floor((px - influence_radius) / cell_size))
        max_x = min(columns - 1, math.floor((px + influence_radius) / cell_size))
        min_y = max(0, math.floor((py - influence_radius) / cell_size))
        max_y = min(rows - 1, math.floor((py + influence_radius) / cell_size))
        for gx in range(min_x, max_x + 1):
            for gy in range(min_y, max_y + 1):
                centre_x, centre_y = (gx + 0.5) * cell_size, (gy + 0.5) * cell_size
                if math.hypot(centre_x - px, centre_y - py) <= influence_radius:
                    covered.add((gx, gy))
    return round(len(covered) / (columns * rows) * 100)


def position_score(summary: Any, positions: list[dict[str, Any]]) -> int | None:
    if summary.quality_status != "reliable":
        return None
    influence = court_influence_percent(positions)
    recovery = summary.recovery_within_two_seconds_percent
    return round(
        stable_band(50 if recovery is None else recovery) * 0.45
        + stable_band(min(100, summary.net_zone_percent * 2)) * 0.30
        + stable_band(min(100, (influence or 0) * 2)) * 0.25
    )


def validate_calibration(corners: list[Any], width: int, height: int) -> dict[str, float]:
    points = [(float(point.x), float(point.y)) for point in corners]
    if not all(math.isfinite(value) for point in points for value in point):
        raise ValueError("Court markers must contain valid coordinates")
    if any(x < 0 or x > width or y < 0 or y > height for x, y in points):
        raise ValueError("A court marker is outside the video frame")
    cross_products = []
    for index in range(4):
        x1, y1 = points[index]
        x2, y2 = points[(index + 1) % 4]
        x3, y3 = points[(index + 2) % 4]
        cross_products.append((x2 - x1) * (y3 - y2) - (y2 - y1) * (x3 - x2))
    if min(abs(value) for value in cross_products) < width * height * 0.002 or not (
        all(value > 0 for value in cross_products) or all(value < 0 for value in cross_products)
    ):
        raise ValueError("Court markers are crossed or do not form a valid four-corner court")
    area = abs(sum(points[index][0] * points[(index + 1) % 4][1] - points[(index + 1) % 4][0] * points[index][1] for index in range(4))) / 2
    area_ratio = area / max(1, width * height)
    distance = lambda left, right: math.hypot(right[0] - left[0], right[1] - left[1])
    top_width = distance(points[0], points[1]) / width
    bottom_width = distance(points[3], points[2]) / width
    left_height = distance(points[0], points[3]) / height
    right_height = distance(points[1], points[2]) / height
    if area_ratio < 0.06 or min(top_width, bottom_width) < 0.08 or min(left_height, right_height) < 0.12:
        raise ValueError("The marked court is too small or distorted. Mark the four outer playing-surface corners again")
    if ((points[0][1] + points[1][1]) / 2 >= (points[2][1] + points[3][1]) / 2) or (
        (points[0][0] + points[3][0]) / 2 >= (points[1][0] + points[2][0]) / 2
    ):
        raise ValueError("Court markers must be ordered top-left, top-right, bottom-right, bottom-left")
    quality = round(min(100.0, area_ratio / 0.30 * 100))
    return {"area_ratio": round(area_ratio, 4), "quality_score": quality}
