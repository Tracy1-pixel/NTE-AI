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
    method: str = '相对输入'

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
        self.rect = wt.RECT
        self.u.GetClipCursor.argtypes = [ct.POINTER(wt.RECT)]
        self.u.GetClipCursor.restype = wt.BOOL
        self.u.SetCursorPos.argtypes = [ct.c_int, ct.c_int]
        self.u.SetCursorPos.restype = wt.BOOL
        self.u.GetSystemMetrics.argtypes = [ct.c_int]
        self.u.GetSystemMetrics.restype = ct.c_int
        self.u.GetWindowThreadProcessId.argtypes = [wt.HWND, ct.POINTER(wt.DWORD)]
        self.u.GetWindowThreadProcessId.restype = wt.DWORD

    def clip_rect(self):
        rect = self.rect()
        if not self.u.GetClipCursor(ct.byref(rect)):
            raise OSError('无法读取鼠标活动范围')
        return rect.left, rect.top, rect.right, rect.bottom

    def move_absolute(self, x, y):
        left, top, width, height = (self.u.GetSystemMetrics(i) for i in (76, 77, 78, 79))
        if width <= 1 or height <= 1:
            raise ValueError('无法读取虚拟桌面尺寸')
        dx = max(0, min(65535, round((x - left) * 65535 / (width - 1))))
        dy = max(0, min(65535, round((y - top) * 65535 / (height - 1))))
        return self.send(0x0001 | 0x8000 | 0x4000, dx, dy)

    def set_position(self, x, y):
        ct.set_last_error(0)
        if not self.u.SetCursorPos(x, y):
            raise OSError(f'SetCursorPos 失败（错误 {ct.get_last_error()}）')
        return 1

    def diagnostics(self, hwnd=None):
        from ctypes import wintypes as wt
        import os
        pid = wt.DWORD()
        if hwnd:
            self.u.GetWindowThreadProcessId(hwnd, ct.byref(pid))
        helper = process_elevated(os.getpid())
        game = process_elevated(pid.value) if pid.value else '未知'
        return f'系统坐标 {self.position()}；鼠标活动范围 {self.clip_rect()}；助手管理员={helper}，游戏进程管理员={game}'

    def position(self):
        point = self.point()
        if not self.u.GetCursorPos(ct.byref(point)):
            raise OSError('无法读取系统光标实际坐标')
        return point.x, point.y

    def send(self, flags, dx=0, dy=0, data=0):
        packet = Input(0, InputData(mi=MouseInput(dx, dy, data & 0xffffffff, flags, 0, 0)))
        ct.set_last_error(0)
        accepted = self.u.SendInput(1, ct.byref(packet), ct.sizeof(Input))
        if accepted != 1:
            error = ct.get_last_error()
            raise OSError(f'Windows 未接收鼠标输入（错误 {error}）；如果游戏以管理员身份运行，请以管理员身份运行助手')
        return int(accepted)


def process_elevated(pid):
    """Read actual process token elevation; do not infer it from how it launched."""
    from ctypes import wintypes as wt
    kernel, advapi = ct.WinDLL('kernel32', use_last_error=True), ct.WinDLL('advapi32', use_last_error=True)
    for library, name, args, result in (
        (kernel, 'OpenProcess', [wt.DWORD, wt.BOOL, wt.DWORD], wt.HANDLE),
        (kernel, 'CloseHandle', [wt.HANDLE], wt.BOOL),
        (advapi, 'OpenProcessToken', [wt.HANDLE, wt.DWORD, ct.POINTER(wt.HANDLE)], wt.BOOL),
        (advapi, 'GetTokenInformation', [wt.HANDLE, ct.c_int, ct.c_void_p, wt.DWORD, ct.POINTER(wt.DWORD)], wt.BOOL),
    ):
        function = getattr(library, name)
        function.argtypes, function.restype = args, result
    process = kernel.OpenProcess(0x1000, False, pid)
    if not process:
        return '未知'
    token = wt.HANDLE()
    try:
        if not advapi.OpenProcessToken(process, 0x0008, ct.byref(token)):
            return '未知'
        elevated, length = wt.DWORD(), wt.DWORD()
        if not advapi.GetTokenInformation(token, 20, ct.byref(elevated), ct.sizeof(elevated), ct.byref(length)):
            return '未知'
        return '是' if elevated.value else '否'
    finally:
        if token.value:
            kernel.CloseHandle(token)
        kernel.CloseHandle(process)

class WindowsMouse:
    def __init__(self, guard, stop=None, api=None, sleep=time.sleep, log=lambda text: None):
        self.api = api if api is not None else MouseAPI()
        self.guard, self.stop, self.sleep = guard, stop, sleep
        self.log = log

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
        clip = self.api.clip_rect()
        if clip and not (clip[0] <= target[0] < clip[2] and clip[1] <= target[1] < clip[3]):
            raise ValueError(f'鼠标活动范围限制 {clip} 不包含目标 {target}；原位置 / 实际 {before}。暂停点击，不修改游戏的鼠标限制')
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
        self.log(f'相对 SendInput 返回已接收，但移动未确认：原位置 {before}，目标 {target}，实际 {actual}，鼠标活动范围 {clip}；尝试标准坐标定位')
        attempts = []
        for name, action in (('绝对 SendInput', self.api.move_absolute), ('SetCursorPos', self.api.set_position)):
            self.guard()
            try:
                accepted = action(*target)
                immediate = self.api.position()
                self.wait(0.05)
                self.guard()
                actual = self.api.position()
                attempts.append(f'{name}返回={accepted}，即时={immediate}，延后={actual}')
                if max(abs(actual[0]-target[0]), abs(actual[1]-target[1])) <= 4:
                    return MoveResult(before, actual, target, name)
            except Stopped:
                raise
            except OSError as error:
                attempts.append(f'{name}失败：{error}')
        raise ValueError(f'鼠标移动未确认：原位置 {before}，目标 {target}，实际 {actual}；范围 {clip}；' + '；'.join(attempts) + '；暂停点击。若即时到达后又返回原点，可能是游戏重置光标；若始终不变，需结合鼠标诊断检查权限或输入拦截')

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
