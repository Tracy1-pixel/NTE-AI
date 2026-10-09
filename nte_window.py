"""Windows client-area geometry for a fixed 1920×1080 game window."""
from __future__ import annotations

import sys
import re
from dataclasses import dataclass

CLIENT_SIZE = (1920, 1080)


@dataclass(frozen=True)
class ClientArea:
    x: int
    y: int
    width: int
    height: int

    def region(self):
        return self.x, self.y, self.width, self.height

    def point(self, x, y, reference):
        return self.x + round(x * self.width / reference[0]), self.y + round(y * self.height / reference[1])


class Win32:
    def __init__(self):
        if sys.platform != 'win32':
            raise RuntimeError('窗口模式需要 Windows')
        import ctypes
        from ctypes import wintypes
        self.ct, self.types = ctypes, wintypes
        self.u = ctypes.WinDLL('user32', use_last_error=True)
        self.callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        signatures = {
            'EnumWindows': ([self.callback, wintypes.LPARAM], wintypes.BOOL),
            'GetWindowTextLengthW': ([wintypes.HWND], ctypes.c_int),
            'GetWindowTextW': ([wintypes.HWND, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int),
            'IsWindow': ([wintypes.HWND], wintypes.BOOL),
            'IsWindowVisible': ([wintypes.HWND], wintypes.BOOL),
            'IsIconic': ([wintypes.HWND], wintypes.BOOL),
            'IsZoomed': ([wintypes.HWND], wintypes.BOOL),
            'GetWindowRect': ([wintypes.HWND, ctypes.POINTER(wintypes.RECT)], wintypes.BOOL),
            'GetClientRect': ([wintypes.HWND, ctypes.POINTER(wintypes.RECT)], wintypes.BOOL),
            'ClientToScreen': ([wintypes.HWND, ctypes.POINTER(wintypes.POINT)], wintypes.BOOL),
            'GetWindowLongPtrW': ([wintypes.HWND, ctypes.c_int], ctypes.c_ssize_t),
            'SetWindowLongPtrW': ([wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t], ctypes.c_ssize_t),
            'SetWindowDisplayAffinity': ([wintypes.HWND, wintypes.DWORD], wintypes.BOOL),
            'GetForegroundWindow': ([], wintypes.HWND),
            'GetAncestor': ([wintypes.HWND, wintypes.UINT], wintypes.HWND),
            'ShowWindow': ([wintypes.HWND, ctypes.c_int], wintypes.BOOL),
            'SetForegroundWindow': ([wintypes.HWND], wintypes.BOOL),
            'SetWindowPos': ([wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT], wintypes.BOOL),
        }
        for name, (args, result) in signatures.items():
            function = getattr(self.u, name)
            function.argtypes, function.restype = args, result

    def title(self, hwnd):
        buffer = self.ct.create_unicode_buffer(self.u.GetWindowTextLengthW(hwnd) + 1)
        self.u.GetWindowTextW(hwnd, buffer, len(buffer))
        return buffer.value

    def windows(self):
        result = []
        @self.callback
        def visit(hwnd, _):
            title = self.title(hwnd)
            if self.u.IsWindowVisible(hwnd) and title:
                result.append((int(hwnd), title))
            return True
        self.u.EnumWindows(visit, 0)
        return result

    def valid(self, hwnd):
        return bool(self.u.IsWindow(hwnd))

    def minimized(self, hwnd):
        return bool(self.u.IsIconic(hwnd))

    def foreground(self, hwnd):
        return self.u.GetForegroundWindow() == hwnd

    def geometry(self, hwnd):
        rect, origin = self.types.RECT(), self.types.POINT(0, 0)
        if not self.u.GetClientRect(hwnd, self.ct.byref(rect)) or not self.u.ClientToScreen(hwnd, self.ct.byref(origin)):
            raise ValueError('无法读取游戏窗口尺寸或位置')
        return ClientArea(origin.x, origin.y, rect.right - rect.left, rect.bottom - rect.top)

    def outer(self, hwnd):
        rect = self.types.RECT()
        if not self.u.GetWindowRect(hwnd, self.ct.byref(rect)):
            raise ValueError('无法读取游戏窗口边框')
        return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top

    def windowed(self, hwnd):
        style = self.u.GetWindowLongPtrW(hwnd, -16)
        return bool(style & 0x00C00000)

    def restore(self, hwnd):
        if self.u.IsIconic(hwnd) or self.u.IsZoomed(hwnd):
            self.u.ShowWindow(hwnd, 9)

    def resize(self, hwnd, x, y, width, height):
        if not self.u.SetWindowPos(hwnd, None, x, y, width, height, 0x0004 | 0x0010):
            raise ValueError('无法调整游戏窗口，请检查游戏是否处于普通窗口模式')

    def activate(self, hwnd):
        self.u.SetForegroundWindow(hwnd)

    def configure_overlay(self, hwnd):
        flags = self.u.GetWindowLongPtrW(hwnd, -20)
        self.u.SetWindowLongPtrW(hwnd, -20, flags | 0x80000 | 0x20 | 0x08000000 | 0x80)
        actual = self.u.GetWindowLongPtrW(hwnd, -20)
        if actual & (0x20 | 0x08000000) != (0x20 | 0x08000000):
            raise RuntimeError('无法启用状态栏点击穿透')

    def overlay_owner(self, hwnd, owner):
        self.u.SetWindowLongPtrW(hwnd, -8, owner)

    def exclude_from_capture(self, hwnd):
        if sys.getwindowsversion().build < 19041:
            return False
        return bool(self.u.SetWindowDisplayAffinity(hwnd, 0x11))

    def position_overlay(self, hwnd, x, y, width, height):
        if not self.u.SetWindowPos(hwnd, -1, x, y, width, height, 0x0010 | 0x0040):
            raise RuntimeError('无法显示状态栏')

    def hide(self, hwnd):
        self.u.ShowWindow(hwnd, 0)

    def flush_compositor(self):
        try:
            self.ct.WinDLL('dwmapi').DwmFlush()
        except OSError:
            pass


class GameWindow:
    def __init__(self, api, hwnd, screen_size):
        self.api, self.hwnd, self.screen_size = api, hwnd, screen_size

    def resize(self):
        if not self.api.valid(self.hwnd):
            raise ValueError('游戏窗口已关闭，请重新选择')
        if not self.api.windowed(self.hwnd):
            raise ValueError('请先在游戏设置中切换为普通窗口模式（非全屏/无边框）')
        self.api.restore(self.hwnd)
        client = self.api.geometry(self.hwnd)
        x, y, w, h = self.api.outer(self.hwnd)
        width, height = CLIENT_SIZE[0] + w - client.width, CLIENT_SIZE[1] + h - client.height
        if width > self.screen_size[0] or height > self.screen_size[1]:
            raise ValueError('桌面空间不足以完整显示 1920×1080 游戏内容区及标题栏/边框；请使用更大的桌面分辨率')
        x = max(0, min(x, self.screen_size[0] - width))
        y = max(0, min(y, self.screen_size[1] - height))
        self.api.resize(self.hwnd, x, y, width, height)

    def area(self, require_foreground=True):
        if not self.api.valid(self.hwnd) or self.api.minimized(self.hwnd):
            raise ValueError('游戏窗口已关闭或最小化，暂停操作')
        area = self.api.geometry(self.hwnd)
        if (area.width, area.height) != CLIENT_SIZE:
            raise ValueError('游戏内容区必须为 1920×1080；请恢复尺寸后继续，或 F8 停止重新启动')
        if area.x < 0 or area.y < 0 or area.x + area.width > self.screen_size[0] or area.y + area.height > self.screen_size[1]:
            raise ValueError('请将整个游戏内容区移回主屏幕可见范围')
        if require_foreground and not self.api.foreground(self.hwnd):
            raise ValueError('游戏不在前台，暂停操作；切回游戏即可继续')
        return area


def choose_window(api, title='', hwnd=None):
    candidates = [(handle, name) for handle, name in api.windows()
                  if '异环助手' not in name and 'NTE-AI' not in name]
    if hwnd is not None:
        for handle, _ in candidates:
            if handle == hwnd:
                return handle
        raise ValueError('选择的游戏窗口已关闭，请刷新窗口列表')
    if title:
        matches = [handle for handle, name in candidates if name == title]
    else:
        matches = [handle for handle, name in candidates if '异环' in name or 'neverness' in name.lower() or re.search(r'\bNTE\b', name, re.IGNORECASE)]
    if len(matches) != 1:
        raise ValueError('请在助手中选择唯一的《异环》游戏窗口')
    return matches[0]
