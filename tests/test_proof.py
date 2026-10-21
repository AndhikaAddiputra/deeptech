from __future__ import annotations

import unittest

from savent.proof import compare_text, explain_decision, lead_text


class ProofTest(unittest.TestCase):
    def test_early_prediction_names_the_gap(self):
        text = explain_decision(
            {"quality": {"co2": "ok"}, "co2_ppm": 820, "co2_pred_10min_ppm": 1040, "outdoor_intake_ok": True},
            "air_in",
        )
        self.assertIn("1040 ppm", text)
        self.assertIn("820 ppm", text)
        self.assertIn("kipas menyala", text)

    def test_invalid_sensor_blocks_the_fan(self):
        text = explain_decision({"quality": {"co2": "fault"}, "co2_ppm": None}, "air_stay")
        self.assertIn("tidak dinyalakan", text)

    def test_live_lead_is_positive_when_model_is_first(self):
        text = lead_text(90, 570, 480)
        self.assertIn("8 menit", text)

    def test_compare_reports_both_rooms(self):
        text = compare_text(60, 300)
        self.assertIn("1 menit", text)
        self.assertIn("5 menit", text)


if __name__ == "__main__":
    unittest.main()
