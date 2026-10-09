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
        image = np.zeros((100, 420, 3), dtype=np.uint8)
        cv2.putText(image, '1900/1900', (10, 65), cv2.FONT_HERSHEY_SIMPLEX, 1.8, (255, 255, 255), 3)
        result, _ = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=2)(image)
        text = ''.join(item[1] for item in sorted(result or [], key=lambda row: min(p[0] for p in row[0])))
        if engine.parse_score(text) != 1900:
            raise RuntimeError(f'OCR 自检失败：{text}')
        reader = workflow.ScreenReader()
        for name, expected, parser in (('score_zero', 0, engine.parse_score), ('score_goal', 1927, engine.parse_score), ('city_sample', 652, workflow.fraction), ('cost_sample', 48, workflow.integer)):
            image = cv2.imread(str(workflow.ASSETS / (name + '.png')))
            actual = parser(reader.text(image))
            if actual != expected:
                raise RuntimeError(f'真实截图 OCR 自检失败：{name}={actual}')
        import tkinter as tk
        root = tk.Tk()
        app = App(root)
        root.update()
        app.busy = True
        app.stop_button.configure(state='normal')
        app.stop_button.invoke()
        if not app.stop.is_set() or app.runtime.phase != '正在停止':
            raise RuntimeError('GUI 停止按钮测试失败')
        app.busy = False
        app.stop.clear()
        app.stop_button.configure(state='disabled')
        app.runtime = RuntimeStatus()
        app.paint_status()
        root.update()
        if sys.platform == 'win32':
            probe = tk.Toplevel(root)
            probe.title('NTE Window Smoke')
            probe.maxsize(4096, 2160)
            probe.geometry('320x180+100+100')
            root.update()
            api = nte_window.Win32()
            hwnd = int(api.u.GetAncestor(probe.winfo_id(), 2))
            area = api.geometry(hwnd)
            x, y, width, height = api.outer(hwnd)
            api.resize(hwnd, x, y, 1920 + width - area.width, 1080 + height - area.height)
            root.update()
            resized = api.geometry(hwnd)
            if (resized.width, resized.height) != nte_window.CLIENT_SIZE:
                raise RuntimeError('Windows 内容区 1920×1080 调整测试失败')
            if nte_window.choose_window(api, hwnd=hwnd) != hwnd:
                raise RuntimeError('Windows 窗口选择测试失败')
            from nte_status import overlay_position
            app.overlay.attach(hwnd)
            api.activate(hwnd)
            root.update()
            foreground = api.u.GetForegroundWindow()
            area = api.geometry(hwnd)
            app.overlay.refresh(RuntimeStatus(phase='连点锤子', state='running', score=1927))
            # Native tests do not require the runner desktop to fit the game window.
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
        data = {'status': 'passed', 'score': 1900, 'gui': 'passed', 'stop_button': 'passed', 'overlay': 'passed', 'window_geometry': 'passed', 'frozen': bool(getattr(sys, 'frozen', False))}
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
        root.title('异环助手 · 店长特供 1.3')
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
        ttk.Button(sidebar, text='控制台', style='Accent.TButton', command=lambda: root.deiconify()).pack(fill='x', pady=5)
        self.config_button = ttk.Button(sidebar, text='七图流程说明', command=self.configure)
        self.config_button.pack(fill='x', pady=5)
        tk.Label(sidebar, text='01  识别初始界面\n\n02  选择钢琴家\n\n03  锤子连点\n\n04  结算 / 重试', bg='#101b31', fg='#8fa1bc', justify='left', font=('Microsoft YaHei UI', 10), anchor='nw').pack(fill='x', pady=30)
        tk.Label(sidebar, text='窗口模式\n1920 × 1080\n\nv1.3.0', bg='#101b31', fg='#61738d', justify='left', font=('Segoe UI', 10), anchor='sw').pack(side='bottom', fill='x')

        outer = ttk.Frame(root, padding=(24, 22))
        outer.pack(fill='both', expand=True)
        header = ttk.Frame(outer)
        header.pack(fill='x')
        ttk.Label(header, text='店长特供', style='Title.TLabel').pack(side='left')
        self.badge = ttk.Label(header, text='● 就绪', foreground='#42ddbc')
        self.badge.pack(side='right', pady=10)
        ttk.Label(outer, text='钢琴家自动循环  /  从初始界面开始', style='Muted.TLabel').pack(anchor='w', pady=(6, 16))

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
        ttk.Label(target, text='游戏先切换普通窗口模式；开始时自动调整内容区至 1920×1080。', style='Muted.TLabel', wraplength=650).pack(anchor='w', pady=(8, 0))

        options = ttk.LabelFrame(outer, text='运行参数', padding=12)
        options.pack(fill='x', pady=(0, 10))
        self.fields = {}
        for column, (name, label) in enumerate((('click_interval', '点击间隔 / 秒'), ('scan_interval', '识别间隔 / 秒'))):
            ttk.Label(options, text=label).grid(row=0, column=column*2, padx=(0, 10), sticky='w')
            variable = tk.StringVar()
            self.fields[name] = variable
            ttk.Entry(options, textvariable=variable, width=10).grid(row=0, column=column*2+1, padx=(0, 18))

        actions = ttk.Frame(outer)
        actions.pack(fill='x', pady=(3, 8))
        self.start_button = ttk.Button(actions, text='开始运行', style='Accent.TButton', command=lambda: self.launch('run'))
        self.start_button.pack(side='left', padx=(0, 8))
        self.stop_button = ttk.Button(actions, text='停止', style='Stop.TButton', command=self.request_stop, state='disabled')
        self.stop_button.pack(side='left', padx=(0, 8))
        self.check_button = ttk.Button(actions, text='检查画面', command=lambda: self.launch('check'))
        self.check_button.pack(side='left')
        ttk.Label(actions, text='F8  快捷停止', style='Muted.TLabel').pack(side='right')
        self.status = tk.StringVar(value='准备就绪，请打开图一的店长特供界面。')
        ttk.Label(outer, textvariable=self.status, wraplength=680).pack(anchor='w', pady=(3, 7))
        self.summary = tk.StringVar()
        ttk.Label(outer, textvariable=self.summary, wraplength=680, style='Muted.TLabel').pack(anchor='w')
        self.preview_frame = ttk.Frame(outer)
        self.preview_frame.pack(fill='x', pady=10)
        self.preview_images = []
        ttk.Label(outer, text='运行记录', foreground='#eef5ff').pack(anchor='w', pady=(4, 5))
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
        self.metric_runs.set(f'{self.runtime.completed} 轮 · {self.runtime.failures}/3 失败')
        self.status.set(self.runtime.details)

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
            try:
                workflow.settings(c)
                self.summary.set('已内置七图流程；只有识别到图一才能开始，体力/消耗为 0 或连续失败三次时停止。')
            except (ValueError, KeyError) as error:
                self.summary.set(f'配置尚未完成：{error}')
            for child in self.preview_frame.winfo_children():
                child.destroy()
            self.preview_images.clear()
            from PIL import Image, ImageTk
            for name, label in (('home_start', '开始营业'), ('score_goal', '营业额'), ('cost_sample', '领取消耗')):
                path = workflow.ASSETS / f'{name}.png'
                if path.exists():
                    with Image.open(path) as source:
                        image = source.copy()
                    image.thumbnail((280, 65))
                    photo = ImageTk.PhotoImage(image)
                    self.preview_images.append(photo)
                    box = self.ttk.LabelFrame(self.preview_frame, text=label, padding=4)
                    box.pack(side='left', padx=5)
                    self.ttk.Label(box, image=photo).pack()
        except Exception as error:
            self.log(f'读取配置失败：{error}')

    def log(self, text):
        self.logs.configure(state='normal')
        self.logs.insert('end', time.strftime('%H:%M:%S ') + str(text) + '\n')
        self.logs.see('end')
        self.logs.configure(state='disabled')

    def configure(self):
        from tkinter import messagebox
        window = self.tk.Toplevel(self.root)
        window.title('七图流程预设')
        window.geometry('620x400')
        text = ('① 图一：必须是店长特供关卡选择页面。\n'
                '② 自动滚动左侧关卡栏，找到 3-10 钢！琴！家！，点击开始营业。\n'
                '③ 图三倒计时与图四营业阶段：连续点击左侧锤子。\n'
                '④ 营业额达到 1900：点击左上退出图标，等待图七。\n'
                '⑤ 图七：读取领取下方消耗，非零时领取，返回图一。\n'
                '⑥ 图五：点击重新挑战，直接等待倒计时；连续失败三次停止。\n'
                '⑦ 都市体力或领取消耗连续确认为 0 时停止。\n\n'
                '停止按钮 / F8 手动停止，没有总时长和轮数上限。\n'
                '未知界面或运行错误时暂停操作，等待恢复；F8 停止。\n'
                '游戏需先切换普通窗口模式；内容区固定为 1920×1080，位置自动跟随。')
        self.ttk.Label(window, text=text, wraplength=570, padding=20).pack()
        def use():
            try:
                engine.save_config(workflow.settings(engine.load_config()))
                self.refresh()
                window.destroy()
            except Exception as error:
                messagebox.showerror('保存失败', str(error), parent=window)
        self.ttk.Button(window, text='使用预设并返回', command=use).pack(pady=10)

    def launch(self, mode):
        from tkinter import messagebox
        if self.busy:
            return
        try:
            c = workflow.settings(engine.load_config())
            for name, variable in self.fields.items():
                c[name] = float(variable.get())
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
        self.stop.clear()
        self.runtime = RuntimeStatus(phase='准备运行' if mode == 'run' else '检查画面', state='starting', details='5 秒后处理游戏窗口，请切回游戏')
        self.paint_status()
        self.stop_button.configure(state='normal')
        if self.overlay:
            self.overlay.attach(handle)
        for button in (self.config_button, self.check_button, self.start_button, self.window_refresh):
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
            desktop = workflow.DesktopBackend(self.stop, config['window_title'], handle, prepare=(mode == 'run'), capture_shield=self.overlay.shield if self.overlay else None)
            if self.stop.is_set():
                raise engine.Stopped('已停止')
            if mode == 'check':
                scene = desktop.observe()
                emit(f'当前界面：{scene.page}；营业额：{scene.score}；都市体力：{scene.city}；领取消耗：{scene.cost}')
                emit('检查不会点击或改变窗口尺寸。内容区需为 1920×1080；开始运行必须是图一。')
            else:
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
                    for button in (self.config_button, self.check_button, self.start_button, self.window_refresh):
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
