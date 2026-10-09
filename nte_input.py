"""Checked Windows SendInput mouse events, including relative motion for games."""
import ctypes as ct
import sys
import time
from dataclasses import dataclass

from automation import Stopped

# Fixed-width Win32 fields keep INPUT layouts testable on non-Windows hosts.
class MouseInput(ct.Structure):
    _fields_ = [('dx', ct.c_int32), ('dy', ct.c_int32), ('mouseData', ct.c_uint32),
                ('dwFlags', ct.c_uint32), ('time', ct.c_uint32), ('dwExtraInfo', ct.c_size_t)]

class KeyboardInput(ct.Structure):
    _fields_ = [('wVk', ct.c_uint16), ('wScan', ct.c_uint16),
                ('dwFlags', ct.c_uint32), ('time', ct.c_uint32), ('dwExtraInfo', ct.c_size_t)]

class HardwareInput(ct.Structure):
    _fields_ = [('uMsg', ct.c_uint32), ('wParamL', ct.c_uint16), ('wParamH', ct.c_uint16)]

class InputData(ct.Union):
    _fields_ = [('mi', MouseInput), ('ki', KeyboardInput), ('hi', HardwareInput)]

class Input(ct.Structure):
    _fields_ = [('type', ct.c_uint32), ('data', InputData)]

@dataclass(frozen=True)
class MoveResult:
    before: tuple
    after: tuple
    target: tuple

class MouseAPI:
    def __init__(self):
        if sys.platform != 'win32':
            raise RuntimeError('鼠标输入需要 Windows')
        self.u = ct.WinDLL('user32', use_last_error=True)
        self.u.SendInput.argtypes = [ct.c_uint32, ct.POINTER(Input), ct.c_int]
        self.u.SendInput.restype = ct.c_uint32
        from ctypes import wintypes as wt
        self.point = wt.POINT
        self.u.GetCursorPos.argtypes = [ct.POINTER(wt.POINT)]
        self.u.GetCursorPos.restype = wt.BOOL

    def position(self):
        point = self.point()
        if not self.u.GetCursorPos(ct.byref(point)):
            raise OSError('无法读取系统光标实际坐标')
        return point.x, point.y

    def send(self, flags, dx=0, dy=0, data=0):
        packet = Input(0, InputData(mi=MouseInput(dx, dy, data & 0xffffffff, flags, 0, 0)))
        ct.set_last_error(0)
        if self.u.SendInput(1, ct.byref(packet), ct.sizeof(Input)) != 1:
            error = ct.get_last_error()
            raise OSError(f'Windows 未接收鼠标输入（错误 {error}）；如果游戏以管理员身份运行，请以管理员身份运行助手')

class WindowsMouse:
    def __init__(self, guard, stop=None, api=None, sleep=time.sleep):
        self.api = api if api is not None else MouseAPI()
        self.guard, self.stop, self.sleep = guard, stop, sleep

    def wait(self, seconds):
        if self.stop is not None:
            if self.stop.wait(seconds):
                raise Stopped('已停止（停止按钮 / F8）')
        else:
            self.sleep(seconds)

    def move(self, x, y):
        self.guard()
        target = (round(x), round(y))
        before = self.api.position()
        unchanged = 0
        for _ in range(48):
            self.guard()
            actual = self.api.position()
            dx, dy = target[0] - actual[0], target[1] - actual[1]
            if max(abs(dx), abs(dy)) <= 4:
                return MoveResult(before, actual, target)
            # Relative events reach games that maintain their own UI cursor.
            # Read feedback rather than assuming acceleration is disabled.
            step = lambda d: max(-120, min(120, round(d / 2))) if abs(d) > 4 else 0
            self.api.send(0x0001, step(dx), step(dy))
            self.wait(0.02)
            after = self.api.position()
            unchanged = unchanged + 1 if after == actual else 0
            if unchanged >= 3:
                break
        actual = self.api.position()
        raise ValueError(f'鼠标移动未确认：原位置 {before}，目标 {target}，实际 {actual}；暂停点击。请检查助手与游戏权限、游戏是否锁定鼠标或是否接收模拟输入')

    def click(self):
        self.guard()
        self.api.send(0x0002)  # left down
        try:
            self.wait(0.02)
        finally:
            self.api.send(0x0004)  # always release, including F8 while held

    def scroll(self, ticks):
        self.guard()
        self.api.send(0x0800, data=round(ticks * 120))
