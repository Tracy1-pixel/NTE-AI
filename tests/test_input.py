import ctypes
import threading
import unittest
from types import SimpleNamespace

from automation import Stopped
from nte_input import Input, MouseAPI, WindowsMouse
from nte_workflow import DesktopBackend


class API:
    def __init__(self, stalled=False):
        self.xy = (600, 400)
        self.calls = []
        self.stalled = stalled

    def position(self): return self.xy
    def clip_rect(self): return None
    def move_absolute(self, x, y):
        self.calls.append(('absolute', x, y))
        if not self.stalled: self.xy = (x, y)
        return 1
    def set_position(self, x, y):
        self.calls.append(('set_position', x, y))
        if not self.stalled: self.xy = (x, y)
        return 1
    def send(self, flags, dx=0, dy=0, data=0):
        self.calls.append((flags, dx, dy, data))
        if flags == 1 and not self.stalled:
            # Model pointer acceleration; the driver must use actual feedback.
            self.xy = (self.xy[0] + round(dx * 1.4), self.xy[1] + round(dy * 1.4))


class InputTests(unittest.TestCase):
    def mouse(self, api):
        return WindowsMouse(lambda: None, api=api, sleep=lambda seconds: None)

    def test_input_structure_matches_win32_abi(self):
        self.assertEqual(ctypes.sizeof(Input), 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)
        self.assertEqual(Input.data.offset, 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 4)

    def test_relative_move_verifies_actual_position_despite_acceleration(self):
        api = API()
        result = self.mouse(api).move(160, 700)
        self.assertEqual(result.before, (600, 400))
        self.assertLessEqual(max(abs(api.xy[0]-160), abs(api.xy[1]-700)), 4)
        self.assertEqual(result.after, api.xy)
        self.assertTrue(api.calls)
        self.assertTrue(all(call[0] == 1 for call in api.calls))

    def test_accepted_events_without_actual_motion_are_rejected(self):
        api = API(stalled=True)
        with self.assertRaisesRegex(ValueError, '原位置.*目标.*实际'):
            self.mouse(api).move(160, 700)
        self.assertEqual(len(api.calls), 5)
        self.assertFalse(any(call[0] in (2, 4) for call in api.calls))

    def test_absolute_input_normalizes_coordinates_on_virtual_desktop(self):
        api = MouseAPI.__new__(MouseAPI)
        metrics = {76: -1920, 77: 0, 78: 3840, 79: 1080}
        api.u = SimpleNamespace(GetSystemMetrics=metrics.__getitem__)
        packets = []
        api.send = lambda *args: packets.append(args) or 1
        self.assertEqual(api.move_absolute(-1920, 0), 1)
        self.assertEqual(api.move_absolute(1919, 1079), 1)
        self.assertEqual(packets, [(0xC001, 0, 0), (0xC001, 65535, 65535)])

    def test_stalled_relative_motion_can_recover_with_absolute_input(self):
        api = API(stalled=True)
        def absolute(x, y):
            api.xy = (x, y)
            api.calls.append(('absolute', x, y))
            return 1
        api.move_absolute = absolute
        result = self.mouse(api).move(160, 700)
        self.assertEqual(result.after, (160, 700))
        self.assertEqual(result.method, '绝对 SendInput')
        self.assertFalse(any(call[0] == 'set_position' for call in api.calls))

    def test_stalled_injection_can_recover_with_setcursorpos(self):
        api = API(stalled=True)
        def set_position(x, y):
            api.xy = (x, y)
            return 1
        api.set_position = set_position
        result = self.mouse(api).move(160, 700)
        self.assertEqual(result.after, (160, 700))
        self.assertEqual(result.method, 'SetCursorPos')

    def test_game_reset_after_immediate_motion_is_not_reported_as_success(self):
        api = API(stalled=True)
        original = api.xy
        api.move_absolute = lambda x, y: setattr(api, 'xy', (x, y)) or 1
        api.set_position = api.move_absolute
        mouse = WindowsMouse(lambda: None, api=api, sleep=lambda seconds: setattr(api, 'xy', original))
        with self.assertRaisesRegex(ValueError, '即时=\\(160, 700\\).*延后=\\(600, 400\\)'):
            mouse.move(160, 700)

    def test_clip_excluding_target_blocks_all_inputs_without_unlocking(self):
        api = API()
        api.clip_rect = lambda: (600, 400, 601, 401)
        with self.assertRaisesRegex(ValueError, '活动范围限制.*不包含目标'):
            self.mouse(api).move(160, 700)
        self.assertEqual(api.calls, [])

    def test_f8_during_relative_motion_prevents_fallback(self):
        api = API(stalled=True)
        stop = threading.Event()
        def send(*args):
            api.calls.append(args)
            stop.set()
        api.send = send
        with self.assertRaisesRegex(Stopped, 'F8'):
            WindowsMouse(lambda: None, stop=stop, api=api).move(160, 700)
        self.assertEqual(len(api.calls), 1)

    def test_injection_failure_propagates_before_click(self):
        api = API()
        def rejected(*args): raise OSError('Windows 未接收鼠标输入')
        api.send = rejected
        with self.assertRaisesRegex(OSError, '未接收'):
            self.mouse(api).move(160, 700)

    def test_f8_during_mouse_down_still_releases_button(self):
        api = API()
        stop = threading.Event()
        def send(*args):
            api.calls.append(args)
            if args[0] == 2: stop.set()
        api.send = send
        mouse = WindowsMouse(lambda: None, stop=stop, api=api)
        with self.assertRaisesRegex(Stopped, 'F8'):
            mouse.click()
        self.assertEqual(api.calls, [(2,), (4,)])

    def test_wheel_is_a_signed_relative_input(self):
        api = API()
        self.mouse(api).scroll(-3)
        self.assertEqual(api.calls, [(0x0800, 0, 0, -360)])

    def test_focus_loss_prevents_mouse_events(self):
        api = API()
        def guard(): raise ValueError('游戏不在前台')
        mouse = WindowsMouse(guard, api=api)
        for action in (lambda: mouse.move(160, 700), mouse.click, lambda: mouse.scroll(-3)):
            with self.assertRaisesRegex(ValueError, '不在前台'):
                action()
        self.assertEqual(api.calls, [])

    def test_os_movement_without_game_cursor_confirmation_blocks_click(self):
        backend = DesktopBackend.__new__(DesktopBackend)
        backend.mouse = self.mouse(API())
        backend.point = lambda x, y: (x, y)
        backend.guard = lambda: None
        backend.find_cursor = lambda: False
        logs = []
        backend.log = logs.append
        with self.assertRaisesRegex(ValueError, '未确认游戏光标'):
            backend.move_verified(160, 700, '移动到关卡')
        self.assertEqual(logs, [])
        self.assertFalse(any(call[0] in (2, 4) for call in backend.mouse.api.calls))
