"""Windows GUI entry point for the installed application."""
from __future__ import annotations

import argparse
import json
import queue
import sys
import threading
import time
from pathlib import Path

import automation as engine
import nte_workflow as workflow
import nte_window
from nte_status import RuntimeStatus


def enable_dpi_awareness():
    if sys.platform == 'win32':
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except (AttributeError, OSError):
            ctypes.windll.user32.SetProcessDPIAware()


def self_test(report):
    """Exercise bundled OCR models and runtime libraries without clicking."""
    try:
        import cv2
        import numpy as np
        import pyautogui
        from PIL import Image
        from rapidocr_onnxruntime import RapidOCR
        if sys.platform == 'win32':
            from pynput import keyboard
            import os
            from nte_input import process_elevated
            if process_elevated(os.getpid()) != '是':
                raise RuntimeError('助手实际进程未以管理员身份运行')
            import ctypes as ct
            from ctypes import wintypes as wt
            from nte_cursor import windows_cursor_bitmap
            user32 = ct.WinDLL('user32')
            user32.LoadCursorW.argtypes = [wt.HINSTANCE, ct.c_void_p]
            user32.LoadCursorW.restype = wt.HANDLE
            handle = user32.LoadCursorW(None, ct.c_void_p(32512))
            rendered = windows_cursor_bitmap(handle)
            if not handle or rendered is None or not rendered[0].any():
                raise RuntimeError('Windows 光标图形读取自检失败')
        image = np.zeros((100, 420, 3), dtype=np.uint8)
        cv2.putText(image, '1900/1900', (10, 65), cv2.FONT_HERSHEY_SIMPLEX, 1.8, (255, 255, 255), 3)
        result, _ = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=2)(image)
        text = ''.join(item[1] for item in sorted(result or [], key=lambda row: min(p[0] for p in row[0])))
        if engine.parse_score(text) != 1900:
            raise RuntimeError(f'OCR 自检失败：{text}')
        reader = workflow.ScreenReader()
        from nte_stars import StarAnchorDetector
        stars = cv2.imread(str(workflow.ASSETS / 'star_triplet.png'))
        if len(StarAnchorDetector().groups(stars)) != 1:
            raise RuntimeError('真实三星整体锚点自检失败')
        level = cv2.imread(str(workflow.ASSETS / 'level_sample.png'))
        if not reader.is_level(reader.text(level)):
            raise RuntimeError('真实截图 3-10 OCR 自检失败')
        level = cv2.imread(str(workflow.ASSETS / 'level_first_sample.png'))
        if level is None or not reader.is_level(reader.text(level), '1-1'):
            raise RuntimeError('真实截图 1-1 OCR 自检失败')
        for name, expected, parser in (('score_zero', 0, engine.parse_score), ('score_goal', 1927, engine.parse_score), ('city_sample', 652, workflow.fraction), ('cost_sample', 48, workflow.integer)):
            image = cv2.imread(str(workflow.ASSETS / (name + '.png')))
            actual = reader.number(image, parser)
            if actual != expected:
                raise RuntimeError(f'真实截图 OCR 自检失败：{name}={actual}')
        import tkinter as tk
        root = tk.Tk()
        app = App(root)
        root.update()
        if tuple(app.level_list['values']) != workflow.LEVELS:
            raise RuntimeError('GUI 30 关下拉列表测试失败')
        app.mode_choice.set(workflow.MODES['progression'])
        app.start_level.set('2-7')
        app.update_mode()
        root.update()
        if str(app.level_list['state']) != 'readonly' or '2-7' not in app.subtitle.get():
            raise RuntimeError('GUI 闯关模式 / 开始关卡测试失败')
        app.mode_choice.set(workflow.MODES['loop'])
        app.update_mode()
        if str(app.level_list['state']) != 'disabled':
            raise RuntimeError('GUI 循环模式测试失败')
        app.mode_choice.set(workflow.MODES['progression'])
        app.update_mode()
        app.busy = True
        app.update_mode()
        if str(app.level_list['state']) != 'disabled':
            raise RuntimeError('GUI 运行期间锁定开始关卡测试失败')
        app.stop_button.configure(state='normal')
        app.stop_button.invoke()
        if not app.stop.is_set() or app.runtime.phase != '正在停止':
            raise RuntimeError('GUI 停止按钮测试失败')
        app.busy = False
        app.stop.clear()
        app.stop_button.configure(state='disabled')
        app.runtime = RuntimeStatus(mode='progression', level='2-7', goal=None)
        app.update_mode()
        app.paint_status()
        root.update()
        if sys.platform == 'win32':
            probe = tk.Toplevel(root)
            probe.title('NTE Window Smoke')
            probe.geometry('640x360+100+100')
            root.update()
            api = nte_window.Win32()
            hwnd = int(api.u.GetAncestor(probe.winfo_id(), 2))
            window = nte_window.GameWindow(api, hwnd, tuple(pyautogui.size()))
            original = api.geometry(hwnd)
            area = window.area(require_foreground=False)
            if (area.width, area.height) != (640, 360) or api.geometry(hwnd) != original:
                raise RuntimeError('Windows 当前窗口内容区只读测试失败')
            # Resize only this test-owned Tk window to verify tracking.
            probe.geometry('800x450+120+110')
            root.update()
            area = window.area(require_foreground=False)
            if (area.width, area.height) != (800, 450) or area.point(1279.5, 719.5, workflow.REFERENCE) != (area.x + 400, area.y + 225):
                raise RuntimeError('Windows 窗口变化后的坐标换算测试失败')
            if nte_window.choose_window(api, hwnd=hwnd) != hwnd:
                raise RuntimeError('Windows 窗口选择测试失败')
            from nte_status import overlay_position
            app.overlay.attach(hwnd)
            api.activate(hwnd)
            probe.lift()
            probe.focus_force()
            root.update()
            from nte_input import WindowsMouse
            received = []
            probe.bind('<Button-1>', lambda event: received.append('click'))
            probe.bind('<MouseWheel>', lambda event: received.append(('wheel', event.delta)))
            def input_guard():
                root.update()
                window.area()
            mouse = WindowsMouse(input_guard)
            diagnostic = mouse.api.diagnostics(hwnd)
            if '助手管理员=未知' in diagnostic or '游戏进程管理员=未知' in diagnostic:
                raise RuntimeError(f'Windows 当前进程权限诊断失败：{diagnostic}')
            # Real input goes only to this test-owned window, never to a game.
            mouse.move(*area.point(1279.5, 719.5, workflow.REFERENCE))
            mouse.click()
            mouse.scroll(-3)
            root.update()
            if 'click' not in received or not any(isinstance(event, tuple) and event[0] == 'wheel' and event[1] < 0 for event in received):
                raise RuntimeError(f'Windows 实际鼠标移动 / 点击 / 滚轮事件未确认：{received}')
            for method, target in ((mouse.api.move_absolute, (area.x + 250, area.y + 150)),
                                   (mouse.api.set_position, (area.x + 400, area.y + 225))):
                input_guard()
                method(*target)
                time.sleep(0.05)
                input_guard()
                actual = mouse.api.position()
                if max(abs(actual[0] - target[0]), abs(actual[1] - target[1])) > 4:
                    raise RuntimeError(f'Windows 鼠标坐标定位回退自检失败：目标 {target}，实际 {actual}')
            foreground = api.u.GetForegroundWindow()
            area = api.geometry(hwnd)
            app.overlay.refresh(RuntimeStatus(phase='连点锤子', state='running', score=1927))
            app.overlay.shield.show(*overlay_position(area))
            root.update_idletasks()
            styles = api.u.GetWindowLongPtrW(app.overlay.hwnd, -20)
            if styles & (0x20 | 0x08000000) != (0x20 | 0x08000000):
                raise RuntimeError('状态栏点击穿透 / 不抢焦点测试失败')
            if api.u.GetForegroundWindow() != foreground:
                raise RuntimeError('状态栏抢占了前台焦点')
            if api.outer(app.overlay.hwnd)[:2] != overlay_position(area):
                raise RuntimeError('状态栏未跟随游戏左下角')
            app.overlay.hide()
            probe.destroy()
            # Save a preview of the actual packaged GUI for the build artifacts.
            root.deiconify()
            root.update()
            area = api.geometry(int(api.u.GetAncestor(root.winfo_id(), 2)))
            pyautogui.screenshot(region=area.region()).save(str(Path(report).with_suffix('.png')))
        app.close()
        data = {'status': 'passed', 'score': 1900, 'gui': 'passed', 'progression_controls': 'passed', 'level_ocr': 'passed', 'star_anchors': 'passed', 'cursor_capture': 'passed', 'mouse_input': 'passed', 'stop_button': 'passed', 'overlay': 'passed', 'window_geometry': 'passed', 'frozen': bool(getattr(sys, 'frozen', False))}
        code = 0
    except Exception as error:
        data, code = {'status': 'failed', 'error': str(error)}, 1
    Path(report).write_text(json.dumps(data, ensure_ascii=False), 'utf-8')
    return code


class App:
    def __init__(self, root):
        import tkinter as tk
        from tkinter import ttk
        self.root, self.tk, self.ttk = root, tk, ttk
        self.events = queue.Queue()
        self.stop = threading.Event()
        self.busy = False
        self.runtime = RuntimeStatus()
        self.overlay = None
        root.title('异环助手 · 店长特供 1.1.13')
        root.geometry('980x820')
        root.minsize(920, 760)
        root.configure(bg='#0b1220')
        root.protocol('WM_DELETE_WINDOW', self.close)
        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('.', font=('Microsoft YaHei UI', 9))
        style.configure('TFrame', background='#0b1220')
        style.configure('TLabel', background='#0b1220', foreground='#bbcee6')
        style.configure('Title.TLabel', font=('Microsoft YaHei UI', 24, 'bold'), foreground='#eef5ff')
        style.configure('Muted.TLabel', foreground='#8fa1bc')
        style.configure('Card.TFrame', background='#142139')
        style.configure('Card.TLabel', background='#142139', foreground='#8fa1bc')
        style.configure('Value.TLabel', background='#142139', foreground='#eef5ff', font=('Microsoft YaHei UI', 13, 'bold'))
        style.configure('TButton', background='#24364f', foreground='#eef5ff', borderwidth=0, padding=(13, 9))
        style.map('TButton', background=[('active', '#314967'), ('disabled', '#18243a')], foreground=[('disabled', '#61738d')])
        style.configure('Accent.TButton', background='#42ddbc', foreground='#09261f', font=('Microsoft YaHei UI', 10, 'bold'))
        style.map('Accent.TButton', background=[('active', '#6ceacd'), ('disabled', '#254740')])
        style.configure('Stop.TButton', background='#66303e', foreground='#ffc5cd')
        style.map('Stop.TButton', background=[('active', '#824051'), ('disabled', '#241f2b')])
        style.configure('TEntry', fieldbackground='#142139', foreground='#eef5ff', insertcolor='#eef5ff', bordercolor='#24364f', padding=6)
        style.configure('TCombobox', fieldbackground='#142139', background='#24364f', foreground='#eef5ff', arrowcolor='#42ddbc', padding=6)
        style.map('TCombobox', fieldbackground=[('readonly', '#142139')], foreground=[('readonly', '#eef5ff'), ('disabled', '#61738d')])
        style.configure('TLabelframe', background='#0b1220', bordercolor='#24364f')
        style.configure('TLabelframe.Label', background='#0b1220', foreground='#8fa1bc')
        root.option_add('*TCombobox*Listbox.background', '#142139')
        root.option_add('*TCombobox*Listbox.foreground', '#eef5ff')

        sidebar = tk.Frame(root, bg='#101b31', width=184, padx=18, pady=26)
        sidebar.pack(side='left', fill='y')
        sidebar.pack_propagate(False)
        tk.Label(sidebar, text='NTE', bg='#101b31', fg='#42ddbc', font=('Segoe UI', 30, 'bold'), anchor='w').pack(fill='x')
        tk.Label(sidebar, text='异环助手', bg='#101b31', fg='#eef5ff', font=('Microsoft YaHei UI', 17, 'bold'), anchor='w').pack(fill='x', pady=(4, 30))
        ttk.Button(sidebar, text='店长特供', style='Accent.TButton', command=lambda: root.deiconify()).pack(fill='x', pady=5)
        tk.Label(sidebar, text='当前游戏窗口\n自动读取尺寸\n\nv1.1.13', bg='#101b31', fg='#61738d', justify='left', font=('Segoe UI', 10), anchor='sw').pack(side='bottom', fill='x')

        outer = ttk.Frame(root, padding=(24, 22))
        outer.pack(fill='both', expand=True)
        header = ttk.Frame(outer)
        header.pack(fill='x')
        ttk.Label(header, text='店长特供', style='Title.TLabel').pack(side='left')
        self.badge = ttk.Label(header, text='● 就绪', foreground='#42ddbc')
        self.badge.pack(side='right', pady=10)
        self.subtitle = tk.StringVar(value='钢琴家自动循环  /  从初始界面开始')
        ttk.Label(outer, textvariable=self.subtitle, style='Muted.TLabel').pack(anchor='w', pady=(6, 16))

        self.metric_size = tk.StringVar(value='未绑定')
        self.metric_phase = tk.StringVar(value='就绪')
        self.metric_score = tk.StringVar(value='— / 1,900')
        self.metric_runs = tk.StringVar(value='0 轮 · 0/3 失败')
        metrics = ttk.Frame(outer)
        metrics.pack(fill='x', pady=(0, 14))
        for column, (title, value) in enumerate((('游戏内容区', self.metric_size), ('运行阶段', self.metric_phase), ('营业额', self.metric_score), ('本次进度', self.metric_runs))):
            metrics.columnconfigure(column, weight=1)
            card = ttk.Frame(metrics, style='Card.TFrame', padding=(10, 12))
            card.grid(row=0, column=column, sticky='nsew', padx=(0, 6 if column < 3 else 0))
            ttk.Label(card, text=title, style='Card.TLabel').pack(anchor='w')
            ttk.Label(card, textvariable=value, style='Value.TLabel').pack(anchor='w', pady=(7, 0))

        target = ttk.LabelFrame(outer, text='绑定游戏窗口', padding=12)
        target.pack(fill='x', pady=(0, 10))
        target_row = ttk.Frame(target)
        target_row.pack(fill='x')
        self.window_choice = tk.StringVar()
        self.window_list = ttk.Combobox(target_row, textvariable=self.window_choice, state='readonly', width=40)
        self.window_list.pack(side='left', fill='x', expand=True, padx=(0, 8))
        self.window_refresh = ttk.Button(target_row, text='刷新', command=self.refresh_windows)
        self.window_refresh.pack(side='right')
        self.window_choices = {}
        ttk.Label(target, text='沿用当前游戏窗口尺寸和位置，识别与点击坐标自动换算。', style='Muted.TLabel', wraplength=650).pack(anchor='w', pady=(8, 0))

        options = ttk.LabelFrame(outer, text='运行参数', padding=12)
        options.pack(fill='x', pady=(0, 10))
        self.mode_choice = tk.StringVar(value=workflow.MODES['loop'])
        self.start_level = tk.StringVar(value='1-1')
        ttk.Label(options, text='运行模式').grid(row=0, column=0, padx=(0, 10), pady=3, sticky='w')
        self.mode_list = ttk.Combobox(options, textvariable=self.mode_choice, values=list(workflow.MODES.values()), state='readonly', width=18)
        self.mode_list.grid(row=0, column=1, padx=(0, 18), pady=3, sticky='w')
        ttk.Label(options, text='请选择开始关卡：').grid(row=0, column=2, padx=(0, 10), pady=3, sticky='w')
        self.level_list = ttk.Combobox(options, textvariable=self.start_level, values=workflow.LEVELS, state='disabled', width=10, height=12)
        self.level_list.grid(row=0, column=3, padx=(0, 18), pady=3, sticky='w')
        self.mode_list.bind('<<ComboboxSelected>>', lambda event: self.update_mode())
        self.level_list.bind('<<ComboboxSelected>>', lambda event: self.update_mode())
        self.fields = {}
        for index, (name, label) in enumerate((('click_interval', '点击间隔 / 秒'), ('scan_interval', '识别间隔 / 秒'), ('scroll_interval', '滚动间隔 / 秒'))):
            row, column = divmod(index, 2)
            row += 1
            ttk.Label(options, text=label).grid(row=row, column=column*2, padx=(0, 10), pady=3, sticky='w')
            variable = tk.StringVar()
            self.fields[name] = variable
            ttk.Entry(options, textvariable=variable, width=10).grid(row=row, column=column*2+1, padx=(0, 18), pady=3)
        ttk.Label(options, text='默认 0.1；越小滚动越快，至少 0.05。', style='Muted.TLabel').grid(row=2, column=2, columnspan=2, sticky='w')

        actions = ttk.Frame(outer)
        actions.pack(fill='x', pady=(3, 8))
        self.start_button = ttk.Button(actions, text='开始运行', style='Accent.TButton', command=lambda: self.launch('run'))
        self.start_button.pack(side='left', padx=(0, 8))
        self.stop_button = ttk.Button(actions, text='停止', style='Stop.TButton', command=self.request_stop, state='disabled')
        self.stop_button.pack(side='left', padx=(0, 8))
        self.check_button = ttk.Button(actions, text='检查画面', command=lambda: self.launch('check'))
        self.check_button.pack(side='left', padx=(0, 8))
        self.diagnose_button = ttk.Button(actions, text='鼠标诊断', command=lambda: self.launch('diagnose'))
        self.diagnose_button.pack(side='left')
        ttk.Label(actions, text='F8  快捷停止', style='Muted.TLabel').pack(side='right')
        self.status = tk.StringVar(value='准备就绪，请打开店长特供选关界面。')
        ttk.Label(outer, textvariable=self.status, wraplength=680).pack(anchor='w', pady=(3, 7))
        self.summary = tk.StringVar()
        ttk.Label(outer, textvariable=self.summary, wraplength=680, style='Muted.TLabel').pack(anchor='w')
        ttk.Label(outer, text='运行记录', foreground='#eef5ff').pack(anchor='w', pady=(14, 5))
        log_frame = ttk.Frame(outer)
        log_frame.pack(fill='both', expand=True)
        self.logs = tk.Text(log_frame, height=6, state='disabled', wrap='word', bg='#101b31', fg='#bbcee6', insertbackground='#eef5ff', relief='flat', padx=12, pady=8, font=('Microsoft YaHei UI', 9))
        self.logs.pack(side='left', fill='both', expand=True)
        scrollbar = ttk.Scrollbar(log_frame, command=self.logs.yview)
        scrollbar.pack(side='right', fill='y')
        self.logs.configure(yscrollcommand=scrollbar.set)
        if sys.platform == 'win32':
            from nte_overlay import Overlay
            self.overlay = Overlay(root, nte_window.Win32())
        self.refresh()
        self.refresh_windows()
        root.after(100, self.poll)

    def request_stop(self):
        if self.busy:
            self.stop.set()
            self.runtime.apply({'phase': '正在停止', 'state': 'paused', 'details': '等待当前识别结束'})
            self.paint_status()

    def paint_status(self):
        self.badge.configure(text='● ' + self.runtime.phase, foreground=self.runtime.color)
        self.metric_phase.set(self.runtime.phase)
        self.metric_score.set(self.runtime.score_text)
        self.metric_runs.set(f'{self.runtime.completed} {self.runtime.progress_unit} · {self.runtime.failures}/3 失败')
        self.status.set(self.runtime.details)
        if self.busy:
            self.subtitle.set(f'{self.runtime.mode_text}  /  当前关卡 {self.runtime.level}')

    def update_mode(self):
        progression = self.mode_choice.get() == workflow.MODES['progression']
        self.level_list.configure(state='readonly' if progression and not self.busy else 'disabled')
        if not self.busy:
            self.subtitle.set(f'闯关模式  /  从 {self.start_level.get()} 依次闯关至 3-10' if progression else '钢琴家自动循环  /  从初始界面开始')
        self.summary.set('成功领取并返回后进入下一关，完成 3-10 后停止；体力耗尽或连续失败三次也会停止。' if progression else '请在店长特供选关界面开始；体力耗尽或连续失败三次时自动停止。')

    def refresh_windows(self):
        try:
            windows = [(handle, title) for handle, title in nte_window.Win32().windows()
                       if '异环助手' not in title and 'NTE-AI' not in title]
            self.window_choices = {f'{title} [{handle}]': (handle, title) for handle, title in windows}
            self.window_list['values'] = list(self.window_choices)
            saved = engine.load_config().get('window_title', '')
            if self.window_choice.get() not in self.window_choices:
                selected = next((label for label, (_, title) in self.window_choices.items() if saved and title == saved), '')
                if not selected:
                    try:
                        handle = nte_window.choose_window(nte_window.Win32())
                        selected = next(label for label, (candidate, _) in self.window_choices.items() if candidate == handle)
                    except ValueError:
                        pass
                self.window_choice.set(selected)
        except Exception as error:
            self.log(f'窗口列表不可用：{error}')

    def refresh(self):
        try:
            c = workflow.settings(engine.load_config())
            for name, variable in self.fields.items():
                variable.set(str(c[name]))
            self.mode_choice.set(workflow.MODES[c['mode']])
            self.start_level.set(c['start_level'])
            self.update_mode()
        except Exception as error:
            self.log(f'读取配置失败：{error}')

    def log(self, text):
        self.logs.configure(state='normal')
        self.logs.insert('end', time.strftime('%H:%M:%S ') + str(text) + '\n')
        self.logs.see('end')
        self.logs.configure(state='disabled')

    def launch(self, mode):
        from tkinter import messagebox
        if self.busy:
            return
        try:
            c = workflow.settings(engine.load_config())
            for name, variable in self.fields.items():
                c[name] = float(variable.get())
            c['mode'] = next(key for key, label in workflow.MODES.items() if label == self.mode_choice.get())
            c['start_level'] = workflow.normalize_level(self.start_level.get())
            selected = self.window_choices.get(self.window_choice.get())
            if not selected:
                raise ValueError('请刷新并选择《异环》游戏窗口')
            handle, c['window_title'] = selected
            workflow.settings(c)
            engine.save_config(c)
        except Exception as error:
            messagebox.showerror('请完成配置', str(error), parent=self.root)
            return
        self.busy = True
        self.window_list.configure(state='disabled')
        self.mode_list.configure(state='disabled')
        self.level_list.configure(state='disabled')
        self.stop.clear()
        self.runtime = RuntimeStatus(phase='准备运行' if mode == 'run' else ('鼠标诊断' if mode == 'diagnose' else '检查画面'), state='starting', details='5 秒后处理游戏窗口，请切回游戏', mode=c['mode'], level=c['start_level'] if c['mode'] == 'progression' else '3-10', goal=None if c['mode'] == 'progression' else 1900)
        self.paint_status()
        self.stop_button.configure(state='normal')
        if self.overlay:
            self.overlay.attach(handle)
        for button in (self.check_button, self.diagnose_button, self.start_button, self.window_refresh):
            button.configure(state='disabled')
        self.log('窗口最小化，5 秒后处理游戏画面，请切回游戏。')
        self.root.iconify()
        threading.Thread(target=self.worker, args=(mode, c, handle), daemon=True).start()

    def worker(self, mode, config, handle):
        listener = None
        emit = lambda text: self.events.put(('log', text))
        try:
            from pynput import keyboard
            def on_press(key):
                if key == keyboard.Key.f8:
                    self.stop.set()
            listener = keyboard.Listener(on_press=on_press)
            listener.start()
            if self.stop.wait(5):
                raise engine.Stopped('已取消')
            if mode == 'diagnose':
                from nte_input import MouseAPI
                api = nte_window.Win32()
                if not api.valid(handle):
                    raise ValueError('所选游戏窗口已关闭，请刷新后重新选择')
                emit('鼠标诊断（只读）：' + MouseAPI().diagnostics(handle))
                area = api.geometry(handle)
                emit(f'游戏内容区 {area.region()}；当前是否前台={api.foreground(handle)}。诊断未移动、点击、滚动或修改鼠标限制。')
                if api.foreground(handle) and not api.minimized(handle):
                    try:
                        import cv2
                        import numpy as np
                        import pyautogui
                        from nte_cursor import CursorDetector, windows_cursor_bitmap
                        detector = CursorDetector()
                        frame = cv2.cvtColor(np.asarray(pyautogui.screenshot(region=area.region())), cv2.COLOR_RGB2BGR)
                        hits = detector.candidates(frame, oriented=True)
                        points = [(area.x + hit.x, area.y + hit.y) for hit in hits[:5]]
                        hardware = windows_cursor_bitmap()
                        hardware_matches = bool(hardware and detector.matches(hardware[0]))
                        emit(f'光标定位诊断：画面候选数={len(hits)}，候选位置={points}；Windows 光标轮廓符合目标={hardware_matches}。画面光标按图像位置反馈，系统光标按系统坐标反馈。')
                    except Exception as error:
                        emit(f'光标图形诊断未完成：{error}；上方坐标 / 权限诊断仍可使用。')
                self.events.put(('runtime', {'phase': '诊断完成', 'state': 'stopped', 'details': '鼠标诊断完成，请复制运行记录中的诊断信息'}))
                return
            desktop = workflow.DesktopBackend(self.stop, config['window_title'], handle, prepare=(mode == 'run'), capture_shield=self.overlay.shield if self.overlay else None, log=emit, scroll_interval=config['scroll_interval'])
            if self.stop.is_set():
                raise engine.Stopped('已停止')
            if mode == 'check':
                level = config['start_level'] if config['mode'] == 'progression' else '3-10'
                scene = desktop.observe(target_level=level)
                emit(f'当前界面：{scene.page}；目标关卡：{level}；营业额：{scene.score} / {scene.goal}；都市体力：{scene.city}；领取消耗：{scene.cost}')
                emit('检查不会点击或改变窗口尺寸。使用当前内容区；开始运行必须是图一。')
            else:
                emit(f'版本 1.1.13：{workflow.MODES[config["mode"]]}；开始关卡 {config["start_level"] if config["mode"] == "progression" else "3-10"}；滚动间隔 {config["scroll_interval"]} 秒。')
                workflow.Controller(config, desktop, self.stop, log=emit, report=lambda data: self.events.put(('runtime', data))).run()
        except engine.Stopped as error:
            emit(str(error))
            self.events.put(('runtime', {'phase': '已停止', 'state': 'stopped', 'details': str(error)}))
        except Exception as error:
            emit(f'已停止：{error}')
            self.events.put(('runtime', {'phase': '运行失败', 'state': 'error', 'details': str(error)}))
        finally:
            if listener:
                listener.stop()
            self.events.put(('done', None))

    def poll(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == 'log':
                    self.log(payload)
                elif kind == 'runtime':
                    self.runtime.apply(payload)
                    self.paint_status()
                else:
                    self.busy = False
                    self.stop_button.configure(state='disabled')
                    if self.runtime.state in ('running', 'starting'):
                        self.runtime.apply({'phase': '已结束', 'state': 'stopped', 'details': '当前任务已结束，请查看运行记录'})
                    self.paint_status()
                    if self.overlay:
                        self.overlay.hide()
                    self.window_list.configure(state='readonly')
                    self.mode_list.configure(state='readonly')
                    self.update_mode()
                    for button in (self.check_button, self.diagnose_button, self.start_button, self.window_refresh):
                        button.configure(state='normal')
                    self.root.deiconify()
        except queue.Empty:
            pass
        if self.busy and self.overlay:
            try:
                area = self.overlay.refresh(self.runtime)
                if area:
                    self.metric_size.set(f'{area.width} × {area.height}')
            except Exception as error:
                self.overlay.hide()
                self.log(f'状态栏显示异常：{error}')
        self.root.after(100, self.poll)

    def close(self):
        if self.busy:
            from tkinter import messagebox
            messagebox.showinfo('正在运行', '请先点击停止或按 F8，再关闭窗口。', parent=self.root)
            return
        if self.overlay:
            self.overlay.close()
        self.root.destroy()


def main():
    from nte_privileges import ensure_administrator
    if not ensure_administrator():
        return 0
    enable_dpi_awareness()
    parser = argparse.ArgumentParser()
    parser.add_argument('--self-test', metavar='REPORT')
    args = parser.parse_args()
    if args.self_test:
        return self_test(args.self_test)
    import tkinter as tk
    root = tk.Tk()
    App(root)
    root.mainloop()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
