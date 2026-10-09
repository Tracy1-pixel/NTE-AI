import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from nte_window import ClientArea, GameWindow, choose_window


class API:
    def __init__(self):
        self.client = ClientArea(108, 139, 1000, 600)
        self.focused = True
        self.iconic = False
        self.exists = True
        self.calls = []

    def valid(self, hwnd): return self.exists
    def minimized(self, hwnd): return self.iconic
    def foreground(self, hwnd): return self.focused
    def geometry(self, hwnd): return self.client
    def windows(self): return [(2**40, '异环'), (22, '异环助手 · 店长特供')]
    def activate(self, hwnd): self.calls.append(('activate', hwnd))

    # Any attempt to change the selected game window is a regression.
    def resize(self, *args): raise AssertionError('must not resize the game')
    def restore(self, *args): raise AssertionError('must not restore the game')
    def windowed(self, *args): raise AssertionError('must not require a window border')


class WindowTests(unittest.TestCase):
    def test_current_client_area_is_read_without_changing_window(self):
        api = API()
        window = GameWindow(api, 99, (1920, 1080))
        self.assertEqual(window.area().region(), (108, 139, 1000, 600))
        self.assertEqual(api.calls, [])

    def test_coordinates_follow_moved_and_resized_window(self):
        api = API()
        window = GameWindow(api, 99, (2560, 1440))
        self.assertEqual(window.area().point(1279.5, 719.5, (2559, 1439)), (608, 439))
        api.client = ClientArea(308, 239, 1280, 720)
        self.assertEqual(window.area().point(1279.5, 719.5, (2559, 1439)), (948, 599))
        self.assertEqual(api.calls, [])

    def test_backend_start_only_focuses_game_and_preserves_geometry(self):
        import nte_workflow as workflow
        api = API()
        original = api.client
        pg = SimpleNamespace(size=lambda: (1920, 1080))
        for prepare in (True, False):
            with self.subTest(prepare=prepare), patch.dict(sys.modules, {'pyautogui': pg}), \
                    patch.object(workflow, 'Win32', return_value=api), \
                    patch.object(workflow, 'ScreenReader'), patch('nte_input.WindowsMouse'), \
                    patch('nte_cursor.CursorDetector'), patch('nte_stars.StarAnchorDetector'), \
                    patch.object(workflow.time, 'sleep'):
                api.calls.clear()
                backend = workflow.DesktopBackend(hwnd=2**40, prepare=prepare, log=lambda text: None)
                self.assertEqual(api.client, original)
                self.assertEqual(api.calls, [('activate', 2**40)] if prepare else [])
                self.assertEqual(backend.point(1279.5, 719.5), (608, 439))

    def test_focus_loss_minimized_closed_and_invalid_size_block_access(self):
        api = API()
        window = GameWindow(api, 99, (1920, 1080))
        for attribute, value, message in [('focused', False, '不在前台'),
                                           ('iconic', True, '最小化'),
                                           ('exists', False, '已关闭')]:
            with self.subTest(attribute=attribute):
                old = getattr(api, attribute)
                setattr(api, attribute, value)
                with self.assertRaisesRegex(ValueError, message):
                    window.area()
                setattr(api, attribute, old)
        for width, height in [(0, 720), (1280, 0), (-1, 720)]:
            api.client = ClientArea(108, 139, width, height)
            with self.assertRaisesRegex(ValueError, '有效'):
                window.area()

    def test_offscreen_content_pauses_without_moving_game(self):
        api = API()
        for area in [ClientArea(-10, 0, 1280, 720), ClientArea(0, -1, 1280, 720),
                     ClientArea(1000, 0, 1280, 720), ClientArea(0, 500, 1280, 720)]:
            with self.subTest(area=area):
                api.client = area
                with self.assertRaisesRegex(ValueError, '主屏幕'):
                    GameWindow(api, 99, (1920, 1080)).area()
                self.assertEqual(api.calls, [])

    def test_auto_selection_preserves_64bit_handle(self):
        self.assertEqual(choose_window(API()), 2**40)
        self.assertEqual(choose_window(API(), hwnd=2**40), 2**40)

    def test_closed_selected_window_is_not_replaced(self):
        with self.assertRaisesRegex(ValueError, '已关闭'):
            choose_window(API(), hwnd=15)
