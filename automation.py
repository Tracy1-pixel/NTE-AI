"""Screen-only automation. No game memory, network, or process injection."""
from __future__ import annotations

import argparse
import json
import random
import re
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class Stopped(Exception):
    pass


def parse_score(text, target=1900):
    """Require the complete fraction so the denominator cannot count as progress."""
    text = text.replace('／', '/').replace('，', ',')
    compact = re.sub(r'[\s,]', '', text)
    match = re.search(r'(?<!\d)(\d{1,5})/' + str(target) + r'(?!\d)', compact)
    if not match:
        return None
    value = int(match.group(1))
    return value if value <= target * 3 else None


def validate(config):
    for name in ('click_region', 'goal', 'stamina', 'enter_steps', 'exit_steps'):
        if not config.get(name):
            raise ValueError(f'请先配置 {name}')
    for region in (config['click_region'], config['goal']['region'], config['stamina']['region']):
        if len(region) != 4 or any(not isinstance(v, int) for v in region) or min(region[:2]) < 0 or min(region[2:]) <= 0:
            raise ValueError('截图或点击区域无效')
    for name in ('goal', 'stamina'):
        if not 0.5 <= config[name].get('threshold', 0.88) <= 1:
            raise ValueError('识别阈值必须在 0.5 到 1 之间')
    for name in ('enter_steps', 'exit_steps'):
        for step in config[name]:
            if step.get('key'):
                if step['key'] != 'esc' or step['delay'] < 0:
                    raise ValueError('键盘步骤只支持 esc，等待不能为负数')
            elif min(step['x'], step['y'], step['delay']) < 0:
                raise ValueError('点击坐标和等待时间不能为负数')
    for name, default in (('click_interval', 0.08), ('scan_interval', 0.25), ('round_timeout', 180), ('transition_timeout', 30), ('max_rounds', 100), ('max_minutes', 60)):
        if config.get(name, default) <= 0:
            raise ValueError(f'{name} 必须大于零')
    if config.get('confirm_frames', 3) < 2:
        raise ValueError('连续确认帧数至少为 2')


class Runner:
    def __init__(self, config, backend, stop, clock=time.monotonic, sleep=time.sleep, log=print):
        validate(config)
        self.c, self.b, self.stop = config, backend, stop
        self.clock, self.sleep, self.log = clock, sleep, log
        self.deadline = clock() + config.get('max_minutes', 60) * 60

    def check(self):
        if self.stop.is_set():
            raise Stopped('已紧急停止')
        if self.clock() >= self.deadline:
            raise Stopped('达到总运行时间上限，已停止')
        self.b.check_screen()

    def wait(self, seconds):
        end = self.clock() + seconds
        while self.clock() < end:
            self.check()
            self.sleep(min(0.05, end - self.clock()))

    def stamina_empty(self):
        # Confirm multiple fresh screenshots before making a final decision.
        for i in range(self.c.get('confirm_frames', 3)):
            self.check()
            if not self.b.match('stamina'):
                return False
            if i + 1 < self.c.get('confirm_frames', 3):
                self.wait(self.c.get('scan_interval', 0.25))
        return True

    def steps(self, name):
        for step in self.c[name]:
            self.check()
            if self.stamina_empty():
                raise Stopped('识别到都市体力不足，已停止')
            if step.get('key'):
                self.b.press(step['key'])
            else:
                self.b.click(step['x'], step['y'])
            self.wait(step['delay'])

    def wait_goal_clear(self):
        end = self.clock() + self.c.get('transition_timeout', 30)
        clear_frames = 0
        while self.clock() < end:
            self.check()
            if self.stamina_empty():
                raise Stopped('识别到都市体力不足，已停止')
            achieved = self.b.match('goal')
            readable = not hasattr(self.b, 'last_score') or self.b.last_score is not None
            clear_frames = clear_frames + 1 if readable and not achieved else 0
            if clear_frames >= self.c.get('confirm_frames', 3):
                return
            self.wait(self.c.get('scan_interval', 0.25))
        raise Stopped('退出/重进后目标达成提示未消失，请检查操作步骤')

    def play_round(self):
        end = self.clock() + self.c.get('round_timeout', 180)
        next_scan, frames, readable = self.clock(), 0, True
        while self.clock() < end:
            self.check()
            if self.clock() >= next_scan:
                if self.stamina_empty():
                    raise Stopped('识别到都市体力不足，已停止')
                frames = frames + 1 if self.b.match('goal') else 0
                readable = not hasattr(self.b, 'last_score') or self.b.last_score is not None
                if frames >= self.c.get('confirm_frames', 3):
                    return
                next_scan = self.clock() + self.c.get('scan_interval', 0.25)
            # Pause clicking as soon as a possible success banner appears.
            if not frames and readable:
                x, y, w, h = self.c['click_region']
                self.b.click(random.randint(x, x + w - 1), random.randint(y, y + h - 1))
            self.wait(self.c.get('click_interval', 0.08))
        raise Stopped('单轮超时，未识别到目标达成；请检查界面和截图')

    def run(self):
        if self.stamina_empty():
            raise Stopped('识别到都市体力不足，已停止')
        # Start with the game already inside 店长特供, before the clicking stage.
        if self.b.match('goal'):
            raise Stopped('启动时已显示目标达成，请先进入新一轮')
        if hasattr(self.b, 'last_score') and self.b.last_score is None:
            raise Stopped('启动时无法读取分数，请先用 check 校准分数区域')
        for i in range(int(self.c.get('max_rounds', 100))):
            self.log(f'开始第 {i + 1} 轮')
            self.play_round()
            self.log('目标达成，执行退出步骤')
            self.steps('exit_steps')
            if self.stamina_empty():
                raise Stopped('识别到都市体力不足，已停止')
            if i + 1 >= int(self.c.get('max_rounds', 100)):
                raise Stopped('达到轮数上限，已停止')
            self.steps('enter_steps')
            self.wait_goal_clear()


class Desktop:
    def __init__(self, config):
        import cv2
        import numpy as np
        import pyautogui as pg
        self.cv, self.np, self.pg, self.c = cv2, np, pg, config
        pg.FAILSAFE = True
        pg.PAUSE = 0
        self.templates = {}
        self.ocr = None
        if config.get('goal_mode', 'score') == 'score':
            from rapidocr_onnxruntime import RapidOCR
            self.ocr = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=2)
        for name in ('goal', 'stamina'):
            if name == 'goal' and self.ocr is not None:
                continue
            path = ROOT / config[name]['image']
            raw = np.fromfile(path, dtype=np.uint8)
            template = cv2.imdecode(raw, cv2.IMREAD_GRAYSCALE)
            if template is None or template.std() < 2:
                raise ValueError(f'{name} 图片无法读取或缺乏可识别内容，请重新截取文字/图标')
            self.templates[name] = template
        self.check_screen()

    def check_screen(self):
        size = list(self.pg.size())
        if size != self.c['screen_size']:
            raise Stopped('屏幕分辨率已改变，请重新配置')
        for region in (self.c['click_region'], self.c['goal']['region'], self.c['stamina']['region']):
            x, y, w, h = region
            if x + w > size[0] or y + h > size[1]:
                raise Stopped('配置区域超出主屏幕')

    def click(self, x, y):
        self.pg.click(x, y)

    def press(self, key):
        self.pg.press(key)

    def match(self, name):
        rule = self.c[name]
        rgb = self.np.array(self.pg.screenshot(region=tuple(rule['region'])))
        if name == 'goal' and self.ocr is not None:
            enlarged = self.cv.resize(rgb, None, fx=3, fy=3, interpolation=self.cv.INTER_CUBIC)
            result, _ = self.ocr(self.cv.cvtColor(enlarged, self.cv.COLOR_RGB2BGR))
            pieces = sorted(result or [], key=lambda item: min(p[0] for p in item[0]))
            text = ''.join(item[1] for item in pieces if item[2] >= 0.7)
            score = parse_score(text, self.c.get('target_score', 1900))
            self.last_score = score
            return score is not None and score >= self.c.get('target_score', 1900)
        gray = self.cv.cvtColor(rgb, self.cv.COLOR_RGB2GRAY)
        template = self.templates[name]
        if any(a > b for a, b in zip(template.shape, gray.shape)):
            raise ValueError(f'{name} 模板大于搜索区域')
        scores = self.cv.matchTemplate(gray, template, self.cv.TM_CCOEFF_NORMED)
        return float(scores.max()) >= rule.get('threshold', 0.88)


def configure():
    import tkinter as tk
    from tkinter import messagebox
    import pyautogui as pg
    from PIL import ImageTk

    path = ROOT / 'config.json'
    c = json.loads(path.read_text('utf-8')) if path.exists() else {
        'click_interval': 0.08, 'scan_interval': 0.25, 'confirm_frames': 3,
        'round_timeout': 180, 'transition_timeout': 30, 'max_rounds': 100,
        'max_minutes': 60, 'enter_steps': [], 'exit_steps': [],
    }
    c['goal_mode'] = 'score'
    c['target_score'] = 1900
    root = tk.Tk()
    root.title('异环 · 店长特供配置')
    status = tk.StringVar(value='游戏放在主屏幕；保持窗口位置、分辨率和 UI 缩放固定。')
    tk.Label(root, textvariable=status, wraplength=580).pack(padx=15, pady=10)

    def capture(name):
        root.iconify()

        def select():
            shot = pg.screenshot()
            window = tk.Toplevel(root)
            window.attributes('-fullscreen', True)
            window.attributes('-topmost', True)
            canvas = tk.Canvas(window, highlightthickness=0, cursor='crosshair')
            canvas.pack(fill='both', expand=True)
            photo = ImageTk.PhotoImage(shot)
            canvas.create_image(0, 0, image=photo, anchor='nw')
            canvas.image = photo
            canvas.create_text(20, 20, text='拖动框选区域；Esc 取消', fill='red', anchor='nw', font=('', 20))
            selection = {}

            def down(event):
                selection['start'] = (event.x, event.y)
                if 'rect' in selection:
                    canvas.delete(selection['rect'])
                selection['rect'] = canvas.create_rectangle(event.x, event.y, event.x, event.y, outline='red', width=2)

            def move(event):
                if 'start' in selection:
                    canvas.coords(selection['rect'], *selection['start'], event.x, event.y)

            def up(event):
                if 'start' not in selection:
                    return
                sx, sy = selection['start']
                x, y = min(sx, event.x), min(sy, event.y)
                w, h = abs(event.x - sx), abs(event.y - sy)
                if w < 5 or h < 5:
                    return
                c['screen_size'] = list(shot.size)
                if name == 'click_region':
                    c[name] = [x, y, w, h]
                else:
                    folder = ROOT / 'captures'
                    folder.mkdir(exist_ok=True)
                    shot.crop((x, y, x + w, y + h)).save(folder / f'{name}.png')
                    # Search near the capture to tolerate minor banner movement.
                    left, top = max(0, x - 30), max(0, y - 30)
                    c[name] = {'image': f'captures/{name}.png', 'region': [left, top, min(shot.width, x + w + 30) - left, min(shot.height, y + h + 30) - top], 'threshold': 0.88}
                    if name == 'goal':
                        c[name]['region'] = [x, y, w, h]
                window.destroy()
                root.deiconify()
                status.set(f'{name} 已录入；配置尚未保存。')

            canvas.bind('<ButtonPress-1>', down)
            canvas.bind('<B1-Motion>', move)
            canvas.bind('<ButtonRelease-1>', up)
            window.bind('<Escape>', lambda _: (window.destroy(), root.deiconify()))

        root.after(700, select)

    for label, name in (('框选锤子快速点击区域', 'click_region'), ('框选右上角完整「当前分数/1900」', 'goal'), ('截取「都市体力不足」提示文字/图标', 'stamina')):
        tk.Button(root, text=label, command=lambda n=name: capture(n)).pack(fill='x', padx=15, pady=3)
    tk.Label(root, text='录入步骤：点击按钮后，将鼠标移到游戏按钮上，3 秒后记录位置。\n按实际顺序添加；每步等待时间用于页面切换。').pack(pady=8)
    delay = tk.StringVar(value='2.0')
    tk.Label(root, text='每步点击后等待（秒）').pack()
    tk.Entry(root, textvariable=delay).pack()

    def record(name):
        try:
            seconds = float(delay.get())
            if not 0 <= seconds <= 60:
                raise ValueError()
        except ValueError:
            messagebox.showerror('无效等待时间', '请输入 0 到 60 秒')
            return
        root.iconify()

        def finish():
            pos = pg.position()
            c.setdefault(name, []).append({'x': pos.x, 'y': pos.y, 'delay': seconds})
            root.deiconify()
            status.set(f'{name} 已录入 {len(c[name])} 步，最新位置 {pos.x}, {pos.y}')

        root.after(3000, finish)

    for label, name in (('退出', 'exit_steps'), ('重新进入', 'enter_steps')):
        row = tk.Frame(root)
        row.pack(fill='x', padx=15, pady=3)
        tk.Button(row, text=f'添加{label}点击步骤（3 秒）', command=lambda n=name: record(n)).pack(side='left')
        def clear(n=name):
            c[n] = []
            status.set(f'{n} 已清空')
        tk.Button(row, text=f'清空{label}步骤', command=clear).pack(side='right')

    def add_escape():
        c['exit_steps'].insert(0, {'key': 'esc', 'delay': 2.0})
        status.set('已在退出步骤开头加入 Esc；随后录入退出和确认领取按钮。')
    tk.Button(root, text='在退出步骤开头加入 Esc（只加一次）', command=add_escape).pack(pady=3)

    def save():
        try:
            validate(c)
            path.write_text(json.dumps(c, ensure_ascii=False, indent=2), 'utf-8')
            status.set('已保存 config.json。请关闭配置窗口，在新一轮点击阶段启动 run。')
        except ValueError as error:
            messagebox.showerror('配置未完成', str(error))

    tk.Button(root, text='保存配置', command=save).pack(pady=12)
    root.mainloop()


def main():
    parser = argparse.ArgumentParser(description='异环店长特供：截图识别 + 区域连点')
    parser.add_argument('command', choices=('configure', 'check', 'run'))
    args = parser.parse_args()
    if args.command == 'configure':
        configure()
        return
    config = json.loads((ROOT / 'config.json').read_text('utf-8'))
    validate(config)
    desktop = Desktop(config)
    if args.command == 'check':
        print('当前画面识别：', {name: desktop.match(name) for name in ('goal', 'stamina')})
        print('OCR 当前分数：', getattr(desktop, 'last_score', None))
        return
    from pynput import keyboard
    stop = threading.Event()
    def on_press(key):
        # Esc is also sent by the script to open the game exit menu.
        if key == keyboard.Key.f8:
            stop.set()
    with keyboard.Listener(on_press=on_press):
        print('5 秒后开始。将游戏置于前台的新一轮点击阶段。F8 或鼠标移到屏幕角落停止。')
        runner = Runner(config, desktop, stop)
        try:
            runner.wait(5)
            runner.run()
        except Stopped as error:
            print(error)
        except desktop.pg.FailSafeException:
            print('鼠标移至角落，已紧急停止')


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('已停止')
    except Exception as error:
        print(f'已停止：{error}')
        raise SystemExit(1)
