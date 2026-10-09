import unittest
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np

from nte_cursor import CursorDetector
from nte_workflow import DesktopBackend
from nte_window import ClientArea


def arrow(size=40, background=0):
    image = np.full((128, 128, 3), background, np.uint8)
    # A slightly different shoulder / tail from the reference tests tolerance.
    outline = np.array([(0, 0), (90, 60), (94, 65), (49, 71),
                        (25, 105), (9, 105), (4, 96)], np.float32)
    outline = (outline * size / 105).astype(np.int32) + (20, 20)
    cv2.fillPoly(image, [outline], (15, 20, 35))
    inner = ((outline - (20, 20)) * 0.9).astype(np.int32) + (22, 22)
    cv2.fillPoly(image, [inner], (230, 240, 250))
    return image


class CursorTests(unittest.TestCase):
    def setUp(self):
        self.detector = CursorDetector()

    def test_arrow_at_different_sizes_and_backgrounds(self):
        for size in (24, 36, 52, 76):
            for background in (0, 80, 205):
                with self.subTest(size=size, background=background):
                    self.assertTrue(self.detector.matches(arrow(size, background)))

    def test_rectangles_triangles_and_standard_windows_pointer_are_rejected(self):
        for points in ([(20, 20), (85, 20), (85, 90), (20, 90)],
                       [(20, 20), (85, 55), (27, 90)],
                       [(20, 20), (20, 80), (34, 68), (44, 88),
                        (56, 82), (46, 62), (64, 62)]):
            image = np.zeros((128, 128, 3), np.uint8)
            cv2.fillPoly(image, [np.array(points, np.int32)], (255, 255, 255))
            self.assertFalse(self.detector.matches(image))

    def test_unrelated_arrow_elsewhere_does_not_count_as_mouse_cursor(self):
        frame = np.zeros((400, 500, 3), np.uint8)
        frame[200:328, 300:428] = arrow()
        self.assertFalse(self.detector.near_pointer(frame, 20, 20))
        self.assertTrue(self.detector.near_pointer(frame, 320, 220))
        self.assertFalse(self.detector.near_pointer(frame, -10, 200))

    def test_hardware_cursor_fallback_only_accepts_cursor_inside_game(self):
        backend = DesktopBackend.__new__(DesktopBackend)
        backend.cursor_detector = self.detector
        backend.pg = SimpleNamespace(position=lambda: (120, 220))
        backend.window = SimpleNamespace(area=lambda: ClientArea(100, 200, 1920, 1080))
        backend.frame = lambda: np.zeros((1080, 1920, 3), np.uint8)
        with patch('nte_cursor.windows_cursor_bitmap', return_value=(arrow(), (120, 220))):
            self.assertTrue(backend.find_cursor())
        with patch('nte_cursor.windows_cursor_bitmap', return_value=(arrow(), (10, 10))):
            self.assertFalse(backend.find_cursor())

if __name__ == '__main__':
    unittest.main()
