"""Click-through status overlay; Tk operations stay on the GUI thread."""
import threading

from nte_status import overlay_position

WIDTH, HEIGHT = 430, 112


class CaptureShield:
    """Exclude the overlay from OCR screenshots, with a native hide fallback."""
    def __init__(self, api, hwnd, excluded):
        self.api, self.hwnd, self.excluded = api, hwnd, excluded
        self.lock = threading.RLock()
        self.visible = False
        self.position = (0, 0)

    def show(self, x, y):
        with self.lock:
            self.position = (x, y)
            self.api.position_overlay(self.hwnd, x, y, WIDTH, HEIGHT)
            self.visible = True

    def hide(self):
        with self.lock:
            self.api.hide(self.hwnd)
            self.visible = False

    def capture(self, screenshot):
        with self.lock:
            hidden = self.visible and not self.excluded
            if hidden:
                self.api.hide(self.hwnd)
                self.api.flush_compositor()
            try:
                return screenshot()
            finally:
                if hidden:
                    self.api.position_overlay(self.hwnd, *self.position, WIDTH, HEIGHT)


class Overlay:
    def __init__(self, root, api):
        import tkinter as tk
        self.api = api
        self.target = None
        self.window = tk.Toplevel(root)
        self.window.withdraw()
        self.window.title('异环助手 · 游戏状态')
        self.window.overrideredirect(True)
        self.window.configure(bg='#101b31')
        self.window.geometry(f'{WIDTH}x{HEIGHT}')
        self.window.attributes('-alpha', 0.95)
        self.accent = tk.Frame(self.window, bg='#42ddbc', width=4)
        self.accent.pack(side='left', fill='y')
        body = tk.Frame(self.window, bg='#101b31', padx=14, pady=10)
        body.pack(fill='both', expand=True)
        self.headline = tk.Label(body, text='异环助手', fg='#eef5ff', bg='#101b31', font=('Microsoft YaHei UI', 11, 'bold'), anchor='w')
        self.headline.pack(fill='x')
        self.metrics = tk.Label(body, text='准备运行', fg='#bbcee6', bg='#101b31', font=('Microsoft YaHei UI', 9), anchor='w')
        self.metrics.pack(fill='x', pady=(4, 0))
        self.detail = tk.Label(body, text='F8 停止', fg='#8fa1bc', bg='#101b31', font=('Microsoft YaHei UI', 8), anchor='w')
        self.detail.pack(fill='x', pady=(3, 0))
        self.window.update_idletasks()
        self.hwnd = int(api.u.GetAncestor(self.window.winfo_id(), 2))
        api.configure_overlay(self.hwnd)
        self.window.deiconify()
        self.window.update_idletasks()
        api.hide(self.hwnd)
        excluded = api.exclude_from_capture(self.hwnd)
        self.shield = CaptureShield(api, self.hwnd, excluded)

    def attach(self, hwnd):
        self.target = hwnd
        # Detach Tk's owner so minimizing the dashboard does not hide the HUD.
        # Owning it by the game would destroy it when that game window closes.
        self.api.overlay_owner(self.hwnd, 0)

    def refresh(self, status, active=True):
        if not active or not self.target or not self.api.valid(self.target) or self.api.minimized(self.target):
            self.shield.hide()
            return None
        area = self.api.geometry(self.target)
        self.headline.configure(text=f'{area.width} × {area.height}   ·   {status.phase}')
        self.metrics.configure(text=f'营业额 {status.score_text}   ·   完成 {status.completed} 轮   ·   失败 {status.failures}/3')
        text = status.details if status.state in ('paused', 'error') else '异环助手正在监控当前游戏窗口'
        self.detail.configure(text=f'{text[:34]}   |   F8 停止')
        self.accent.configure(bg=status.color)
        if self.api.foreground(self.target):
            self.shield.show(*overlay_position(area, WIDTH, HEIGHT))
        else:
            self.shield.hide()
        return area

    def hide(self):
        self.shield.hide()

    def close(self):
        self.hide()
        self.window.destroy()
