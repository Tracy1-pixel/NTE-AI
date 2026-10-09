import ctypes
import threading
import unittest
from types import SimpleNamespace

from automation import Stopped
from nte_input import Input, WindowsMouse
from nte_workflow import DesktopBackend


class API:
    def __init__(self, stalled=False):
        self.xy = (600, 400)
        self.calls = []
        self.stalled = stalled

    def position(self): return self.xy
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
        self.assertEqual(len(api.calls), 3)
        self.assertFalse(any(call[0] in (2, 4) for call in api.calls))

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
