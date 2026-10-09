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
import workflow


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
        app.close()
        data = {'status': 'passed', 'score': 1900, 'gui': 'passed', 'frozen': bool(getattr(sys, 'frozen', False))}
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
        root.title('异环助手 · 店长特供')
        root.geometry('760x700')
        root.minsize(720, 650)
        root.protocol('WM_DELETE_WINDOW', self.close)
        style = ttk.Style(root)
        if 'vista' in style.theme_names():
            style.theme_use('vista')
        outer = ttk.Frame(root, padding=20)
        outer.pack(fill='both', expand=True)
        ttk.Label(outer, text='店长特供 · 都市体力助手', font=('Microsoft YaHei UI', 20, 'bold')).pack(anchor='w')
        ttk.Label(outer, text='初始界面 → 钢琴家 → 锤子连点 → 点击退出图标 / 领取 → 循环').pack(anchor='w', pady=8)
        self.summary = tk.StringVar()
        ttk.Label(outer, textvariable=self.summary, wraplength=700).pack(anchor='w', pady=8)
        self.config_button = ttk.Button(outer, text='① 查看七图预设 / 使用预设', command=self.configure)
        self.config_button.pack(fill='x', pady=5)

        options = ttk.LabelFrame(outer, text='运行设置', padding=12)
        options.pack(fill='x', pady=10)
        self.fields = {}
        for i, (name, label) in enumerate((('click_interval', '点击间隔（秒）'), ('scan_interval', '识别间隔（秒）'))):
            ttk.Label(options, text=label).grid(row=i // 2, column=(i % 2) * 2, padx=8, pady=6, sticky='w')
            variable = tk.StringVar()
            self.fields[name] = variable
            ttk.Entry(options, textvariable=variable, width=12).grid(row=i // 2, column=(i % 2) * 2 + 1, padx=8, pady=6)
        actions = ttk.Frame(outer)
        actions.pack(fill='x', pady=8)
        self.check_button = ttk.Button(actions, text='② 检查当前画面', command=lambda: self.launch('check'))
        self.check_button.pack(side='left', padx=4)
        self.start_button = ttk.Button(actions, text='③ 保存设置并开始', command=lambda: self.launch('run'))
        self.start_button.pack(side='left', padx=4)
        ttk.Label(actions, text='运行中按 F8 停止').pack(side='right', padx=4)
        self.status = tk.StringVar(value='就绪：请打开图一的店长特供关卡选择页面。')
        ttk.Label(outer, textvariable=self.status, wraplength=700).pack(anchor='w', pady=6)
        ttk.Label(outer, text='游戏需在主屏幕 16:9 全屏或无边框运行。检查或启动后切回游戏，F8 停止。', wraplength=700).pack(anchor='w', pady=4)
        self.preview_frame = ttk.Frame(outer)
        self.preview_frame.pack(fill='x', pady=8)
        self.preview_images = []
        self.logs = tk.Text(outer, height=9, state='disabled', wrap='word')
        self.logs.pack(fill='both', expand=True, pady=6)
        self.refresh()
        root.after(100, self.poll)

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
                '运行中 F8 手动停止，没有总时长和轮数上限。\n'
                '未知界面或运行错误时暂停操作，等待恢复；F8 停止。\n'
                '预设来自你提供的截图，需要主屏幕 16:9 全屏或无边框画面。')
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
            workflow.settings(c)
            engine.save_config(c)
        except Exception as error:
            messagebox.showerror('请完成配置', str(error), parent=self.root)
            return
        self.busy = True
        self.stop.clear()
        for button in (self.config_button, self.check_button, self.start_button):
            button.configure(state='disabled')
        self.status.set('正在运行；F8 停止。' if mode == 'run' else '正在检查画面。')
        self.log('窗口最小化，5 秒后处理游戏画面，请切回游戏。')
        self.root.iconify()
        threading.Thread(target=self.worker, args=(mode, c), daemon=True).start()

    def worker(self, mode, config):
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
            desktop = workflow.DesktopBackend(self.stop)
            if self.stop.is_set():
                raise engine.Stopped('已停止')
            if mode == 'check':
                scene = desktop.observe()
                emit(f'当前界面：{scene.page}；营业额：{scene.score}；都市体力：{scene.city}；领取消耗：{scene.cost}')
                emit('检查不会点击。开始运行必须是图一，未知界面会显示界面错误。')
            else:
                workflow.Controller(config, desktop, self.stop, log=emit).run()
        except engine.Stopped as error:
            emit(str(error))
        except Exception as error:
            emit(f'已停止：{error}')
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
                else:
                    self.busy = False
                    for button in (self.config_button, self.check_button, self.start_button):
                        button.configure(state='normal')
                    self.status.set('已结束，请查看日志。')
                    self.root.deiconify()
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def close(self):
        if self.busy:
            from tkinter import messagebox
            messagebox.showinfo('正在运行', '请先按 F8 停止，再关闭窗口。', parent=self.root)
            return
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
