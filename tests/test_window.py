import unittest

from nte_window import ClientArea, GameWindow, choose_window


class API:
    def __init__(self):
        self.client = ClientArea(108, 139, 1000, 600)
        self.rect = (100, 100, 1016, 639)
        self.focused = True
        self.iconic = False
        self.exists = True
        self.has_border = True
        self.calls = []

    def valid(self, hwnd): return self.exists
    def windowed(self, hwnd): return self.has_border
    def minimized(self, hwnd): return self.iconic
    def foreground(self, hwnd): return self.focused
    def restore(self, hwnd): self.iconic = False
    def geometry(self, hwnd): return self.client
    def outer(self, hwnd): return self.rect
    def windows(self): return [(2**40, '异环'), (22, '异环助手 · 店长特供')]
    def resize(self, hwnd, x, y, w, h):
        self.calls.append((hwnd, x, y, w, h))
        self.rect = (x, y, w, h)
        self.client = ClientArea(x+8, y+39, w-16, h-39)


class WindowTests(unittest.TestCase):
    def test_client_size_excludes_title_and_border(self):
        api = API()
        window = GameWindow(api, 99, (2560, 1440))
        window.resize()
        self.assertEqual(api.calls, [(99, 100, 100, 1936, 1119)])
        self.assertEqual(window.area().region(), (108, 139, 1920, 1080))

    def test_coordinates_follow_moved_window(self):
        api = API()
        window = GameWindow(api, 99, (2560, 1440))
        window.resize()
        first = window.area().point(1279.5, 719.5, (2559, 1439))
        api.client = ClientArea(308, 239, 1920, 1080)
        second = window.area().point(1279.5, 719.5, (2559, 1439))
        self.assertEqual((second[0]-first[0], second[1]-first[1]), (200, 100))

    def test_insufficient_desktop_space_does_not_resize(self):
        api = API()
        with self.assertRaisesRegex(ValueError, '桌面空间不足'):
            GameWindow(api, 99, (1920, 1080)).resize()
        self.assertEqual(api.calls, [])

    def test_focus_loss_minimized_and_wrong_size_block_access(self):
        api = API()
        window = GameWindow(api, 99, (2560, 1440))
        window.resize()
        api.focused = False
        with self.assertRaisesRegex(ValueError, '不在前台'):
            window.area()
        api.focused = True
        api.iconic = True
        with self.assertRaisesRegex(ValueError, '最小化'):
            window.area()
        api.iconic = False
        api.client = ClientArea(108, 139, 1280, 720)
        with self.assertRaisesRegex(ValueError, '1920×1080'):
            window.area()

    def test_fullscreen_is_rejected(self):
        api = API()
        api.has_border = False
        with self.assertRaisesRegex(ValueError, '普通窗口模式'):
            GameWindow(api, 99, (2560, 1440)).resize()

    def test_auto_selection_preserves_64bit_handle(self):
        self.assertEqual(choose_window(API()), 2**40)
        self.assertEqual(choose_window(API(), hwnd=2**40), 2**40)

    def test_closed_selected_window_is_not_replaced(self):
        with self.assertRaisesRegex(ValueError, '已关闭'):
            choose_window(API(), hwnd=15)
