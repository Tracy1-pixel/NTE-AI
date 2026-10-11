"""Windows F8 cancellation independent of keyboard hooks and OCR work."""
from __future__ import annotations

import ctypes as ct
import sys
import threading

VK_F8 = 0x77
WM_HOTKEY = 0x0312
HOTKEY_ID = 0x4E54


class WindowsF8:
    def __init__(self):
        if sys.platform != 'win32':
            raise RuntimeError('全局 F8 停止需要 Windows')
        from ctypes import wintypes as wt
        self.u = ct.WinDLL('user32', use_last_error=True)
        self.message = wt.MSG()
        for name, args, result in (
            ('RegisterHotKey', [wt.HWND, ct.c_int, wt.UINT, wt.UINT], wt.BOOL),
            ('UnregisterHotKey', [wt.HWND, ct.c_int], wt.BOOL),
            ('PeekMessageW', [ct.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT, wt.UINT], wt.BOOL),
            ('GetAsyncKeyState', [ct.c_int], ct.c_short),
        ):
            function = getattr(self.u, name)
            function.argtypes, function.restype = args, result
        self.registration_error = 0

    def register(self):
        # Registration and message pumping belong to this monitor's thread.
        ct.set_last_error(0)
        accepted = bool(self.u.RegisterHotKey(None, HOTKEY_ID, 0x4000, VK_F8))
        self.registration_error = 0 if accepted else ct.get_last_error()
        return accepted

    def message_pressed(self):
        while self.u.PeekMessageW(ct.byref(self.message), None, WM_HOTKEY, WM_HOTKEY, 1):
            if self.message.wParam == HOTKEY_ID:
                return True
        return False

    def key_pressed(self):
        # The high bit is current key-down state, unlike the shared low bit.
        return bool(self.u.GetAsyncKeyState(VK_F8) & 0x8000)

    def unregister(self):
        self.u.UnregisterHotKey(None, HOTKEY_ID)


class F8StopMonitor:
    def __init__(self, stop, on_stop=lambda reason: None, log=lambda text: None,
                 api_factory=WindowsF8, interval=0.02):
        self.stop_event, self.on_stop, self.log = stop, on_stop, log
        self.api_factory, self.interval = api_factory, interval
        self.shutdown = threading.Event()
        self.ready = threading.Event()
        self.thread = None
        self.registered = False
        self.error = None
        self.reason = ''

    def cancel(self, reason):
        self.reason = reason
        self.stop_event.set()
        self.on_stop(reason)

    def run(self):
        api = None
        try:
            api = self.api_factory()
            self.registered = api.register()
            # Probe polling before allowing the automation to start. An absent
            # global registration still has a working independent stop path.
            held = api.key_pressed()
            if self.registered:
                self.log('F8 停止已就绪：Windows 全局热键 + 独立按键检测')
            else:
                self.log(f'F8 全局热键未注册（错误 {getattr(api, "registration_error", 0)}），已启用独立按键检测；停止按钮仍可用')
            self.ready.set()
            if held and not self.stop_event.is_set():
                self.cancel('已收到 F8，正在停止自动操作')
            while not self.shutdown.is_set() and not self.stop_event.is_set():
                if (self.registered and api.message_pressed()) or api.key_pressed():
                    self.cancel('已收到 F8，正在停止自动操作')
                    break
                self.shutdown.wait(self.interval)
        except Exception as error:
            self.error = error
            self.cancel(f'F8 停止监听异常，已终止自动操作：{error}')
        finally:
            self.ready.set()
            if api is not None and self.registered:
                api.unregister()

    def start(self):
        if self.thread is not None:
            raise RuntimeError('F8 停止监听不能重复启动')
        self.thread = threading.Thread(target=self.run, name='NTE-F8-stop', daemon=True)
        self.thread.start()
        if not self.ready.wait(2):
            self.close()
            raise RuntimeError('F8 停止监听未就绪，不开始自动操作')
        if self.error is not None:
            self.close()
            raise RuntimeError(f'F8 停止监听不可用：{self.error}') from self.error
        return self

    def close(self):
        self.shutdown.set()
        if self.thread is not None:
            self.thread.join(timeout=1)

    def __enter__(self):
        return self.start()

    def __exit__(self, *args):
        self.close()
