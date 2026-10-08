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
        ttk.Label(outer, text='连点锤子 → 分数达到 1900 → Esc / 退出 / 领取 → 再开始').pack(anchor='w', pady=8)
        self.summary = tk.StringVar()
        ttk.Label(outer, textvariable=self.summary, wraplength=700).pack(anchor='w', pady=8)
        self.config_button = ttk.Button(outer, text='① 配置截图区域与操作步骤', command=self.configure)
        self.config_button.pack(fill='x', pady=5)

        options = ttk.LabelFrame(outer, text='运行设置', padding=12)
        options.pack(fill='x', pady=10)
        self.fields = {}
        for i, (name, label) in enumerate((('click_interval', '点击间隔（秒）'), ('max_rounds', '最多轮数'), ('max_minutes', '最多运行（分钟）'), ('round_timeout', '单轮超时（秒）'))):
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
        self.stop_button = ttk.Button(actions, text='停止（F8）', command=self.stop.set, state='disabled')
        self.stop_button.pack(side='right', padx=4)
        self.status = tk.StringVar(value='就绪：首次使用请先配置，建议先试运行 2 轮。')
        ttk.Label(outer, textvariable=self.status, wraplength=700).pack(anchor='w', pady=6)
        ttk.Label(outer, text='检查或启动后窗口会最小化，请切回游戏。F8 或将鼠标移到屏幕角落可停止。', wraplength=700).pack(anchor='w', pady=4)
        self.preview_frame = ttk.Frame(outer)
        self.preview_frame.pack(fill='x', pady=8)
        self.preview_images = []
        self.logs = tk.Text(outer, height=9, state='disabled', wrap='word')
        self.logs.pack(fill='both', expand=True, pady=6)
        self.refresh()
        root.after(100, self.poll)

    def refresh(self):
        try:
            c = engine.load_config()
            for name, variable in self.fields.items():
                variable.set(str(c[name]))
            try:
                engine.validate(c)
                self.summary.set('配置齐全。先检查分数识别，再进入新一轮点击阶段并开始。')
            except (ValueError, KeyError) as error:
                self.summary.set(f'配置尚未完成：{error}')
            for child in self.preview_frame.winfo_children():
                child.destroy()
            self.preview_images.clear()
            from PIL import Image, ImageTk
            for name, label in (('goal', '分数区域'), ('stamina', '体力不足模板')):
                path = engine.ROOT / c.get(name, {}).get('image', f'captures/{name}.png')
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
        try:
            engine.configure(self.root, self.refresh)
        except Exception as error:
            self.root.deiconify()
            messagebox.showerror('配置失败', str(error), parent=self.root)

    def launch(self, mode):
        from tkinter import messagebox
        if self.busy:
            return
        try:
            c = engine.load_config()
            for name, variable in self.fields.items():
                c[name] = int(variable.get()) if name == 'max_rounds' else float(variable.get())
            engine.validate(c)
            engine.save_config(c)
        except Exception as error:
            messagebox.showerror('请完成配置', str(error), parent=self.root)
            return
        self.busy = True
        self.stop.clear()
        for button in (self.config_button, self.check_button, self.start_button):
            button.configure(state='disabled')
        self.stop_button.configure(state='normal')
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
            desktop = engine.Desktop(config)
            if self.stop.is_set():
                raise engine.Stopped('已停止')
            if mode == 'check':
                goal = desktop.match('goal')
                stamina = desktop.match('stamina')
                emit(f'当前分数：{getattr(desktop, "last_score", None)}；达到目标：{goal}；体力不足：{stamina}')
                emit('读不到分数或结果与游戏不符时，请重新框选区域。检查操作不会点击。')
            else:
                engine.Runner(config, desktop, self.stop, log=emit).run()
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
                    self.stop_button.configure(state='disabled')
                    self.status.set('已结束，请查看日志。')
                    self.root.deiconify()
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def close(self):
        self.stop.set()
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
