from __future__ import annotations

import unittest

from savent.twin import AIR_IN, AIR_OUT, AIR_STAY, ClassroomTwin, RoomSpec, recommend_air_mode


class TwinPhysicsTest(unittest.TestCase):
    def test_volume_follows_area_and_ceiling(self):
        twin = ClassroomTwin(RoomSpec(floor_area_m2=80, ceiling_m=4))
        self.assertEqual(twin.spec.volume_m3, 320)

    def test_air_stay_accumulates_faster_than_air_in(self):
        stay = ClassroomTwin()
        fresh = ClassroomTwin()
        for _ in range(20):
            stay.step(30, AIR_STAY)
            fresh.step(30, AIR_IN)
        self.assertGreater(stay.co2_ppm, 800)
        self.assertLess(fresh.co2_ppm, stay.co2_ppm)

    def test_taller_room_rises_slower_when_air_stays(self):
        low = ClassroomTwin(RoomSpec(ceiling_m=2.6))
        high = ClassroomTwin(RoomSpec(ceiling_m=8))
        for _ in range(15):
            low.step(30, AIR_STAY)
            high.step(30, AIR_STAY)
        self.assertGreater(low.co2_ppm, high.co2_ppm)

    def test_air_out_keeps_particles_lower_when_outdoor_is_dirty(self):
        dirty = RoomSpec(outdoor_pm25=90, outdoor_pm10=120)
        incoming = ClassroomTwin(dirty)
        exhausting = ClassroomTwin(dirty)
        incoming.pm25 = 20
        exhausting.pm25 = 20
        for _ in range(30):
            incoming.step(30, AIR_IN)
            exhausting.step(30, AIR_OUT)
        self.assertLess(exhausting.pm25, incoming.pm25)
        self.assertLess(exhausting.co2_ppm, ClassroomTwin(dirty).co2_ppm + 400)

    def test_recommendation_uses_outdoor_flag(self):
        self.assertEqual(recommend_air_mode(False, True), AIR_STAY)
        self.assertEqual(recommend_air_mode(True, True), AIR_IN)
        self.assertEqual(recommend_air_mode(True, False), AIR_OUT)


if __name__ == "__main__":
    unittest.main()
