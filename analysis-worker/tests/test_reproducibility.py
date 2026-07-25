from types import SimpleNamespace
import unittest

from app.reproducibility import (
    canonical_sha256,
    court_influence_percent,
    position_score,
    validate_calibration,
)

class ReproducibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.positions = [
            {"t": index / 8, "x": 2 + (index % 16) / 8, "y": 14 + (index % 8) / 8, "source": "detected"}
            for index in range(160)
        ]
        self.summary = SimpleNamespace(
            quality_status="reliable",
            recovery_within_two_seconds_percent=63.4,
            net_zone_percent=24.2,
        )

    def test_same_inputs_produce_identical_score_and_fingerprint(self) -> None:
        first = position_score(self.summary, self.positions)
        second = position_score(self.summary, [dict(point) for point in self.positions])
        self.assertEqual(first, second)
        self.assertEqual(
            canonical_sha256({"positions": self.positions, "score": first}),
            canonical_sha256({"score": second, "positions": self.positions}),
        )

    def test_influence_does_not_depend_on_position_order(self) -> None:
        self.assertEqual(court_influence_percent(self.positions), court_influence_percent(list(reversed(self.positions))))

    def test_valid_calibration_passes_and_crossed_markers_fail(self) -> None:
        valid = [
            SimpleNamespace(x=180, y=90),
            SimpleNamespace(x=1100, y=100),
            SimpleNamespace(x=1240, y=680),
            SimpleNamespace(x=40, y=690),
        ]
        self.assertGreater(validate_calibration(valid, 1280, 720)["quality_score"], 50)
        crossed = [valid[0], valid[2], valid[1], valid[3]]
        with self.assertRaisesRegex(ValueError, "crossed|valid"):
            validate_calibration(crossed, 1280, 720)


if __name__ == "__main__":
    unittest.main()
