import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np

from automation import Stopped
from nte_cursor import CursorDetector, CursorPosition
from nte_input import WindowsMouse
from nte_window import ClientArea
from nte_workflow import DesktopBackend
from test_cursor import arrow


class GameMouse:
    """A raw-input UI with a fixed OS pointer and a separate rendered pointer."""
    def __init__(self, accepts=True):
        self.game = (180, 150)
        self.os = (1977, 346)
        self.accepts = accepts
        self.calls = []

    def position(self): return self.os
    def clip_rect(self): return (1977, 346, 1978, 347)
    def send(self, flags, dx=0, dy=0, data=0):
        self.calls.append((flags, dx, dy, data))
        if flags == 1 and self.accepts:
            self.game = (self.game[0] + dx, self.game[1] + dy)
        return 1
    def move_absolute(self, *args): raise AssertionError('OS absolute positioning cannot drive this UI')
    def set_position(self, *args): raise AssertionError('must not reposition or unlock the fixed OS pointer')


class VisualCursorTests(unittest.TestCase):
    def backend(self, api):
        backend = DesktopBackend.__new__(DesktopBackend)
        backend.cursor_detector = CursorDetector()
        backend.window = SimpleNamespace(area=lambda: ClientArea(100, 200, 800, 500))
        backend.guard = lambda: None
        backend.point = lambda x, y: (x, y)
        backend.logs = []
        backend.log = backend.logs.append
        backend.mouse = WindowsMouse(backend.guard, api=api, sleep=lambda seconds: None)
        def frame():
            image = np.zeros((500, 800, 3), np.uint8)
            x, y = api.game
            image[y-20:y+108, x-20:x+108] = arrow()
            return image
        backend.frame = frame
        return backend

    def test_unique_pointer_can_be_located_far_from_os_coordinates(self):
        detector = CursorDetector()
        image = np.zeros((500, 800, 3), np.uint8)
        image[150:278, 300:428] = arrow()
        hit = detector.locate(image)
        self.assertIsNotNone(hit)
        self.assertLessEqual(max(abs(hit.x-320), abs(hit.y-170)), 5)

    def test_multiple_arrows_are_not_arbitrarily_selected(self):
        detector = CursorDetector()
        image = np.zeros((500, 800, 3), np.uint8)
        image[150:278, 100:228] = arrow()
        image[150:278, 500:628] = arrow()
        self.assertIsNone(detector.locate(image))
        # Track only around an earlier, image-confirmed cursor position.
        hit = detector.locate(image, previous=(120, 170))
        self.assertIsNotNone(hit)
        self.assertLessEqual(abs(hit.x-120), 5)

    def test_real_game_furniture_is_not_a_cursor(self):
        image = cv2.imread(str(Path(__file__).parent / 'fixtures/furniture_edge.png'))
        self.assertIsNotNone(image)
        # This real furniture edge passed the old orientation-free shape test.
        detector = CursorDetector()
        self.assertTrue(detector.matches(image))
        self.assertIsNone(detector.locate(image))

    def test_rotated_arrow_is_not_the_photographed_cursor(self):
        detector = CursorDetector()
        image = cv2.rotate(arrow(), cv2.ROTATE_90_CLOCKWISE)
        self.assertIsNone(detector.locate(image))

    def test_lost_cursor_does_not_jump_to_another_distant_arrow_during_motion(self):
        detector = CursorDetector()
        image = np.zeros((500, 800, 3), np.uint8)
        image[150:278, 500:628] = arrow()
        self.assertIsNone(detector.locate(image, previous=(100, 170), reacquire=False))

    def test_rendered_cursor_moves_and_clicks_while_os_position_stays_fixed(self):
        api = GameMouse()
        backend = self.backend(api)
        with patch('nte_cursor.windows_cursor_bitmap', return_value=None):
            initial = backend.cursor_position()
            self.assertEqual(initial.source, '游戏画面')
            result = backend.move_verified(630, 460, '移动到三星锚点')
        self.assertEqual(api.position(), (1977, 346))
        self.assertEqual(api.clip_rect(), (1977, 346, 1978, 347))
        self.assertLessEqual(max(abs(result.after[0]-630), abs(result.after[1]-460)), 8)
        self.assertTrue(all(call[0] == 1 for call in api.calls))
        self.assertIn('画面光标反馈', backend.logs[-1])
        backend.mouse.click()
        self.assertEqual([call[0] for call in api.calls[-2:]], [2, 4])

    def test_stalled_rendered_cursor_never_reports_success_or_clicks(self):
        api = GameMouse(accepts=False)
        backend = self.backend(api)
        with patch('nte_cursor.windows_cursor_bitmap', return_value=None):
            with self.assertRaisesRegex(ValueError, '游戏画面中的光标移动未确认'):
                backend.move_verified(630, 460, '移动到三星锚点')
        self.assertEqual(backend.logs, [])
        self.assertEqual(len(api.calls), 3)
        self.assertTrue(all(call[0] == 1 for call in api.calls))

    def test_os_motion_does_not_count_as_rendered_cursor_motion(self):
        api = GameMouse(accepts=False)
        def send(flags, dx=0, dy=0, data=0):
            api.calls.append((flags, dx, dy, data))
            api.os = (api.os[0]+dx, api.os[1]+dy)
        api.send = send
        backend = self.backend(api)
        with self.assertRaisesRegex(ValueError, '游戏画面中的光标移动未确认'):
            backend.move_verified(630, 460, '移动到三星锚点')
        self.assertNotEqual(api.os, (1977, 346))
        self.assertEqual(backend.logs, [])

    def test_lost_game_cursor_pauses_without_any_absolute_fallback(self):
        api = GameMouse()
        positions = iter([(300, 350), None])
        mouse = WindowsMouse(lambda: None, api=api, sleep=lambda seconds: None)
        with self.assertRaisesRegex(ValueError, '光标丢失或识别有歧义'):
            mouse.move_visual(630, 460, lambda: next(positions))
        self.assertEqual(len(api.calls), 1)

    def test_f8_after_relative_event_prevents_more_input(self):
        api = GameMouse()
        stop = threading.Event()
        def send(*args):
            api.calls.append(args)
            stop.set()
        api.send = send
        mouse = WindowsMouse(lambda: None, stop=stop, api=api)
        with self.assertRaisesRegex(Stopped, 'F8'):
            mouse.move_visual(630, 460, lambda: (300, 350))
        self.assertEqual(len(api.calls), 1)

    def test_hardware_cursor_must_be_at_target_after_os_move(self):
        api = GameMouse()
        backend = self.backend(api)
        # Inject an otherwise successful OS positioning result, then report the
        # actual recognized cursor remaining elsewhere. No click is allowed.
        from nte_input import MoveResult
        backend.mouse.move = lambda x, y: MoveResult((300, 350), (x, y), (x, y))
        backend.cursor_position = lambda: CursorPosition((300, 350), 'Windows 光标')
        with self.assertRaisesRegex(ValueError, '目标附近未确认游戏光标'):
            backend.move_verified(630, 460, '移动到三星锚点')
        self.assertEqual(api.calls, [])
        self.assertEqual(backend.logs, [])

if __name__ == '__main__':
    unittest.main()
