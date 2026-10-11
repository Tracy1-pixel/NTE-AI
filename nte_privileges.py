"""Request Windows administrator consent before starting the assistant."""
import ctypes as ct
import os
import subprocess
import sys
from pathlib import Path


class WindowsElevation:
    def __init__(self):
        from ctypes import wintypes as wt
        self.shell = ct.WinDLL('shell32', use_last_error=True)
        self.user = ct.WinDLL('user32', use_last_error=True)
        self.shell.ShellExecuteW.argtypes = [wt.HWND, wt.LPCWSTR, wt.LPCWSTR, wt.LPCWSTR, wt.LPCWSTR, ct.c_int]
        self.shell.ShellExecuteW.restype = ct.c_ssize_t
        self.user.MessageBoxW.argtypes = [wt.HWND, wt.LPCWSTR, wt.LPCWSTR, wt.UINT]
        self.user.MessageBoxW.restype = ct.c_int

    def status(self):
        from nte_input import process_elevated
        return process_elevated(os.getpid())

    def relaunch(self, executable, arguments, directory):
        # ShellExecute's runas verb displays the normal Windows UAC prompt.
        # Arguments go to Python/the EXE directly, without a command shell.
        return self.shell.ShellExecuteW(None, 'runas', executable, arguments, directory, 1)

    def message(self, text):
        self.user.MessageBoxW(None, text, '异环助手 · 管理员权限', 0x30)


def ensure_administrator(api=None):
    """Return True only when this process may continue running the application."""
    if sys.platform != 'win32':
        return True
    api = api if api is not None else WindowsElevation()
    status = api.status()
    if status == '是':
        return True
    if status != '否':
        api.message('无法确认当前管理员权限，助手未启动。请关闭后重新打开。')
        return False
    arguments = list(sys.argv[1:])
    if not getattr(sys, 'frozen', False):
        arguments.insert(0, str(Path(sys.argv[0]).resolve()))
    try:
        result = api.relaunch(sys.executable, subprocess.list2cmdline(arguments), os.getcwd())
    except OSError:
        api.message('无法请求管理员授权，助手未启动。请右键选择“以管理员身份运行”。')
        return False
    if result <= 32:
        api.message('未获得管理员权限，助手未启动。请重新打开，并在 Windows 授权提示中选择“是”。')
    # The original process must exit after either relaunch or cancellation.
    # An elevated child verifies its own token before opening the GUI.
    return False
