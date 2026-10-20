from __future__ import annotations

import unittest

from savent.logic import Node, OutdoorSample, Sample, correct_co2
from savent.model import fit, replay_metrics


def room(**overrides) -> Sample:
    base = dict(co2_raw=800, t_c=27.4, rh_pct=62.0, p_hpa=932.0, gas_ohm=180_000, pm25=18, pm10=24)
    base.update(overrides)
    return Sample(**base)


def warmed(node: Node, sample: Sample | None = None, ticks: int = 6) -> dict:
    record = {}
    for _ in range(ticks):
        record = node.advance(30, sample or room())
    return record


class CorrectionTest(unittest.TestCase):
    def test_bandung_pressure_raises_reading(self):
        corrected = correct_co2(800, 930)
        self.assertAlmostEqual(corrected, 871.6, delta=0.2)
        self.assertGreater(corrected, 800)

    def test_published_value_uses_corrected_co2(self):
        node = Node()
        record = warmed(node, room(co2_raw=800, p_hpa=930))
        self.assertEqual(record["co2_raw_ppm"], 800)
        self.assertEqual(record["co2_ppm"], 872)
        self.assertEqual(record["quality"]["co2"], "ok")


class QualityTest(unittest.TestCase):
    def test_warmup_blocks_decision(self):
        node = Node(mode=3)
        record = node.advance(30, room(co2_raw=2000))
        self.assertEqual(record["quality"]["co2"], "warming")
        self.assertFalse(record["fan_on"])
        self.assertEqual(record["vent_request"], "off")

    def test_missing_sensor_and_out_of_range(self):
        node = Node(mode=3)
        warmed(node)
        dead = node.advance(30, room(co2_raw=None))
        self.assertEqual(dead["quality"]["co2"], "fault")
        self.assertFalse(dead["fan_on"])
        high = node.advance(30, room(co2_raw=6000))
        self.assertEqual(high["quality"]["co2"], "out_of_range")
        self.assertFalse(high["fan_on"])

    def test_stuck_at_baseline_sentinel(self):
        node = Node(mode=3)
        warmed(node, room(co2_raw=400))
        record = {}
        for _ in range(30):
            record = node.advance(30, room(co2_raw=400))
        self.assertEqual(record["quality"]["co2"], "stuck")
        self.assertFalse(record["fan_on"])

    def test_humid_pm_is_flagged_and_still_shown(self):
        node = Node()
        warmed(node)
        record = node.advance(30, room(rh_pct=80))
        self.assertEqual(record["quality"]["pm"], "rh_high")
        self.assertEqual(record["pm25_ugm3"], 18)


class DecisionTest(unittest.TestCase):
    def test_mode_one_recommends_without_spinning_fan(self):
        node = Node(mode=1)
        record = warmed(node, room(co2_raw=2000))
        self.assertEqual(record["vent_request"], "recommend_on")
        self.assertFalse(record["fan_on"])

    def test_mode_three_runs_fan_and_force_off_wins(self):
        node = Node(mode=3)
        record = warmed(node, room(co2_raw=2000))
        self.assertTrue(record["fan_on"])
        self.assertEqual(record["vent_request"], "on")
        node.command({"cmd": "force_off", "source": "dashboard"})
        self.assertFalse(node.fan_on)
        self.assertTrue(any(event["detail"] == "force_off" for event in node.events))

    def test_invalid_co2_stops_fan_without_waiting_minimum_on(self):
        node = Node(mode=3)
        warmed(node, room(co2_raw=2000))
        self.assertTrue(node.fan_on)
        record = node.advance(30, room(co2_raw=None))
        self.assertFalse(record["fan_on"])
        self.assertEqual(record["vent_request"], "off")

    def test_minimum_off_blocks_chatter(self):
        node = Node(mode=3)
        warmed(node, room(co2_raw=2000))
        self.assertTrue(node.fan_on)
        node.command({"cmd": "force_off", "source": "dashboard"})
        node.command({"cmd": "force_off_release", "source": "dashboard"})
        record = node.advance(30, room(co2_raw=2000))
        self.assertFalse(record["fan_on"])
        self.assertEqual(record["vent_request"], "recommend_on")
        for _ in range(4):
            record = node.advance(30, room(co2_raw=2000))
        self.assertTrue(record["fan_on"])

    def test_confirm_window_on_mode_two(self):
        node = Node(mode=2)
        warmed(node, room(co2_raw=2000))
        self.assertFalse(node.fan_on)
        node.command({"cmd": "confirm", "source": "dashboard"})
        self.assertTrue(node.fan_on)
        node.advance(30, room(co2_raw=2000))
        node.advance(60, room(co2_raw=2000))
        self.assertFalse(node.fan_on)

    def test_command_without_source_is_rejected(self):
        node = Node()
        event = node.command({"cmd": "set_mode", "mode": 3})
        self.assertEqual(event["type"], "command_rejected")
        self.assertEqual(node.mode, 1)

    def test_outdoor_pm_rejects_intake_only(self):
        node = Node(mode=1)
        warmed(node, room(pm25=20))
        dirty = node.advance(30, room(pm25=20), OutdoorSample(pm25=40, pm_quality="ok"))
        self.assertFalse(dirty["outdoor_intake_ok"])
        humid = node.advance(30, room(pm25=20), OutdoorSample(pm25=40, pm_quality="rh_high"))
        self.assertTrue(humid["outdoor_intake_ok"])


class BufferTest(unittest.TestCase):
    def test_outage_keeps_seq_without_duplicates(self):
        node = Node()
        warmed(node)
        first = node.seq
        held = [node.advance(30, room(), broker_up=False) for _ in range(3)]
        self.assertEqual([record["seq"] for record in held], [first + 1, first + 2, first + 3])
        self.assertEqual(len(node.buffer), 3)
        restored = node.advance(30, room(), broker_up=True)
        flushed = [record["seq"] for record in restored["_flush"]]
        self.assertEqual(flushed, [first + 1, first + 2, first + 3])
        self.assertEqual(restored["seq"], first + 4)
        self.assertEqual(len(node.buffer), 0)


class ModelTest(unittest.TestCase):
    def test_model_beats_persistence_and_warns_early(self):
        metrics = replay_metrics(fit())
        self.assertIsNotNone(metrics["mae_model_ppm"])
        self.assertLess(metrics["mae_model_ppm"], metrics["mae_persistence_ppm"])
        self.assertGreater(metrics["lead_time_s"], 0)


if __name__ == "__main__":
    unittest.main()
