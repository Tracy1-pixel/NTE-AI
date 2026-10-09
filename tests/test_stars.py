import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

from automation import Stopped
from nte_stars import StarAnchorDetector
from nte_window import ClientArea
from nte_workflow import DesktopBackend, REFERENCE, ScreenReader


class StarTests(unittest.TestCase):
    def setUp(self):
        self.detector = StarAnchorDetector()
        self.sample = cv2.imread(str(Path(__file__).resolve().parents[1] / 'assets/pianist/star_triplet.png'))
        self.assertIsNotNone(self.sample)

    def frame(self):
        frame = np.zeros((1439, 2559, 3), np.uint8)
        frame[650:716, 140:320] = self.sample
        return frame

    def backend(self, frames):
        backend = DesktopBackend.__new__(DesktopBackend)
        backend.star_detector = self.detector
        backend.reader = SimpleNamespace(cv=cv2)
        backend.stop = threading.Event()
        backend.scroll_stable = 0
        backend.guard = lambda: None
        backend.point = lambda x, y: ClientArea(100, 200, 1920, 1080).point(x, y, REFERENCE)
        frames = iter(frames)
        backend.frame = lambda: next(frames)
        backend.calls = []
        backend.pg = SimpleNamespace(
            moveTo=lambda *point, **kwargs: backend.calls.append(('move', point)),
            scroll=lambda ticks: backend.calls.append(('wheel', ticks)),
            click=lambda *point: backend.calls.append(('click', point)))
        return backend

    def test_real_sample_is_one_anchor_covering_all_three_stars(self):
        groups = self.detector.groups(self.sample)
        self.assertEqual(len(groups), 1)
        self.assertEqual((groups[0].x, groups[0].y, groups[0].width, groups[0].height), (13, 11, 152, 43))
        self.assertEqual(groups[0].center, (89, 32.5))

    def test_two_stars_are_not_a_triplet(self):
        image = self.sample.copy()
        image[:, 120:] = 100
        self.assertEqual(self.detector.groups(image), [])

    def test_differently_colored_stars_and_three_gold_circles_are_rejected(self):
        hsv = cv2.cvtColor(self.sample, cv2.COLOR_BGR2HSV)
        hsv[:, :, 0] = 110
        self.assertEqual(self.detector.groups(cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)), [])
        image = np.zeros_like(self.sample)
        for x in (30, 85, 140):
            cv2.circle(image, (x, 33), 20, (40, 200, 255), -1)
        self.assertEqual(self.detector.groups(image), [])

    def test_right_panel_and_header_stars_are_not_level_list_anchors(self):
        frame = np.zeros((1439, 2559, 3), np.uint8)
        frame[20:86, 140:320] = self.sample
        frame[650:716, 700:880] = self.sample
        self.assertIsNone(self.detector.find(frame))

    def test_anchor_tracks_position_and_survives_actual_client_scaling(self):
        frame = self.frame()
        group = self.detector.find(frame)
        self.assertEqual(group.center, (229, 682.5))
        for size in ((1280, 720), (1600, 900), (1920, 1080)):
            with self.subTest(size=size):
                normalized = cv2.resize(cv2.resize(frame, size), REFERENCE)
                resized = self.detector.find(normalized)
                self.assertIsNotNone(resized)
                self.assertAlmostEqual(resized.center[0], group.center[0], delta=2)
                self.assertAlmostEqual(resized.center[1], group.center[1], delta=2)

    def test_each_wheel_batch_moves_to_detected_triplet_and_detects_bottom(self):
        frame = self.frame()
        backend = self.backend([frame] * 6)
        self.assertTrue(backend.scroll_step())
        self.assertFalse(backend.scroll_step())
        point = backend.point(229, 682.5)
        self.assertEqual(backend.calls, [('move', point), ('wheel', -3), ('move', point), ('wheel', -3)])

    def test_missing_anchor_has_no_mouse_or_wheel_actions(self):
        backend = self.backend([np.zeros((1439, 2559, 3), np.uint8)])
        with self.assertRaisesRegex(ValueError, '连续三颗星'):
            backend.scroll_step()
        self.assertEqual(backend.calls, [])

    def test_wheel_progress_resets_bottom_confirmation(self):
        frame = self.frame()
        after = cv2.add(frame, np.full_like(frame, 25))
        backend = self.backend([frame, frame, after])
        backend.scroll_stable = 1
        self.assertTrue(backend.scroll_step())
        self.assertEqual(backend.scroll_stable, 0)

    def test_stop_after_wheel_prevents_followup_capture_and_clicks(self):
        frame = self.frame()
        backend = self.backend([frame, frame])
        def wheel(ticks):
            backend.calls.append(('wheel', ticks))
            backend.stop.set()
        backend.pg.scroll = wheel
        with self.assertRaisesRegex(Stopped, 'F8'):
            backend.scroll_step()
        self.assertEqual(len(backend.calls), 2)

    def test_ocr_identifier_alone_selects_target_but_not_similar_numbers(self):
        for text in ('3-10', '3–10', '３－１０', '3-10 钢！琴！家！'):
            self.assertTrue(ScreenReader.is_level(text))
        for text in ('13-10', '3-100', '3-9', '2310'):
            self.assertFalse(ScreenReader.is_level(text))
        frame = self.frame()
        backend = self.backend([frame, frame])
        box = [[50, 200], [150, 200], [150, 230], [50, 230]]
        backend.reader.is_level = ScreenReader.is_level
        backend.reader.ocr = lambda image: ([[box, '13-10', 0.99], [box, '3-10', 0.5]], None)
        self.assertFalse(backend.select_level())
        self.assertEqual(backend.calls, [])
        backend.reader.ocr = lambda image: ([[box, '3-10', 0.99]], None)
        self.assertTrue(backend.select_level())
        point = backend.point(100, 355)
        self.assertEqual(backend.calls, [('move', point), ('click', point)])


if __name__ == '__main__':
    unittest.main()
