import unittest

from scripts.update_club_directory import classify_region, transform


class ClubDirectoryTests(unittest.TestCase):
    def test_regions_are_limited_to_the_selected_area(self) -> None:
        self.assertEqual(classify_region(51.50, -0.12, "SW1A"), "London")
        self.assertEqual(classify_region(51.65, -0.40, "HA6"), "Outer London")
        self.assertEqual(classify_region(51.28, 1.08, "CT1"), "Kent")
        self.assertEqual(classify_region(51.73, 0.47, "CM1"), "Essex")
        self.assertIsNone(classify_region(53.48, -2.24, "M1"))

    def test_generic_individual_courts_are_not_published_as_clubs(self) -> None:
        payload = {
            "elements": [
                {
                    "type": "node",
                    "id": 10,
                    "lat": 51.50,
                    "lon": -0.12,
                    "tags": {"name": "Court 2", "sport": "padel"},
                },
                {
                    "type": "node",
                    "id": 11,
                    "lat": 51.50,
                    "lon": -0.12,
                    "tags": {
                        "name": "Example Padel Club",
                        "sport": "padel",
                        "addr:city": "London",
                        "addr:postcode": "SE1 1AA",
                        "website": "https://example.test/",
                    },
                },
            ]
        }
        rows = transform(payload)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "Example Padel Club")
        self.assertEqual(rows[0]["region"], "London")


if __name__ == "__main__":
    unittest.main()
