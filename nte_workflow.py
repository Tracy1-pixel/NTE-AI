"""Figure 1–7 state machine and screenshot-driven desktop backend."""
from __future__ import annotations

import math
import re
import sys
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from automation import Stopped, parse_score
from nte_window import GameWindow, Win32, choose_window
from nte_status import PHASES

REFERENCE = (2559, 1439)
ASSETS = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent)) / 'assets' / 'pianist'


def settings(saved=None):
    c = {'click_interval': 0.08, 'scan_interval': 0.25, 'confirm_frames': 3,
         'transition_timeout': 30.0, 'workflow_version': 5, 'window_title': ''}
    for key in c:
        if key != 'workflow_version' and key in (saved or {}):
            c[key] = saved[key]
    for key in ('click_interval', 'scan_interval', 'transition_timeout'):
        if not math.isfinite(c[key]) or c[key] <= 0:
            raise ValueError(f'{key} 必须是大于零的有限数值')
    if not isinstance(c['confirm_frames'], int) or c['confirm_frames'] < 2:
        raise ValueError('连续确认帧数至少为 2')
    if not isinstance(c['window_title'], str):
        raise ValueError('游戏窗口标题必须为文字')
    return c


def fraction(text):
    compact = re.sub(r'[\s,，]', '', text).replace('／', '/')
    match = re.fullmatch(r'(\d{1,5})/+(\d{1,5})', compact)
    if not match:
        return None
    numerator, denominator = map(int, match.groups())
    return numerator if denominator > 0 and numerator <= denominator else None


def integer(text):
    compact = re.sub(r'[\s,，]', '', text)
    return int(compact) if re.fullmatch(r'\d{1,4}', compact) else None


@dataclass
class Scene:
    page: str
    score: int | None = None
    city: int | None = None
    cost: int | None = None
    selected: bool = False


class Controller:
    def __init__(self, config, backend, stop, clock=time.monotonic, sleep=time.sleep, log=print, report=None):
        self.c, self.b, self.stop = settings(config), backend, stop
        self.clock, self.sleep, self.log = clock, sleep, log
        self.failures = 0
        self.completed = 0
        self.last_message = None
        self.report = report

    def publish(self, state, scene=None, reason=''):
        if self.report:
            paused = bool(reason) or (scene is not None and scene.page == 'unknown')
            phase = '已暂停' if paused else PHASES.get(state, state)
            if state in ('cursor', 'anchor') and scene is not None and scene.page == 'home':
                phase = PHASES[state]
            if scene is not None and scene.page == 'ready' and state == 'playing':
                phase = '倒计时连点'
            self.report({'phase': phase, 'state': 'paused' if paused else 'running',
                         'details': reason or ('界面错误，等待识别恢复' if paused else phase),
                         'score': scene.score if scene else None,
                         'completed': self.completed, 'failures': self.failures})

    def check(self):
        if self.stop.is_set():
            raise Stopped('已停止（停止按钮 / F8）')

    def wait(self, seconds):
        end = self.clock() + seconds
        while self.clock() < end:
            self.check()
            self.sleep(min(0.05, end - self.clock()))

    def message(self, text):
        if self.last_message != text:
            self.log(text)
            self.last_message = text

    def action(self, name):
        self.check()
        result = self.b.action(name)
        if name != 'hammer':
            self.wait(0.3)
        return result

    def initial(self):
        self.publish('home')
        # Require several fresh observations of Figure 1 before any mouse action.
        for _ in range(self.c['confirm_frames']):
            self.check()
            if self.b.observe().page != 'home':
                raise Stopped('界面错误：请停留在图一的店长特供关卡选择页面再开始')
            self.wait(self.c['scan_interval'])

    def run(self):
        self.initial()
        state, since = 'home', self.clock()
        page_frames, zero_city, zero_cost, score_frames = {}, 0, 0, 0
        at_bottom, cursor_frames = False, 0
        next_observe, scene = 0, None
        while True:
            self.check()
            try:
                paused_reason = ''
                if self.clock() < next_observe:
                    if state == 'playing' and scene.page in ('ready', 'playing') and not score_frames:
                        self.action('hammer')
                    self.wait(self.c['click_interval'])
                    continue
                scene = self.b.observe()
                if state == 'cursor' and scene.page != 'home':
                    cursor_frames = 0
                self.publish(state, scene)
                next_observe = self.clock() + self.c['scan_interval']
                for page in ('home', 'success', 'failure'):
                    page_frames[page] = page_frames.get(page, 0) + 1 if scene.page == page else 0
                # Count the final claimed round before its zero-stamina stop.
                if state == 'claiming' and page_frames['home'] >= self.c['confirm_frames']:
                    self.completed += 1
                    self.failures = 0
                    self.message(f'领取完成，已完成 {self.completed} 轮，返回图一继续')
                    state, since = 'home', self.clock()
                    self.publish(state, scene)
                city_visible = scene.page in ('home', 'success')
                zero_city = zero_city + 1 if city_visible and scene.city == 0 else 0
                zero_cost = zero_cost + 1 if scene.page == 'success' and scene.cost == 0 else 0
                if zero_city >= self.c['confirm_frames']:
                    raise Stopped('右上角都市体力为 0，已停止')
                if zero_cost >= self.c['confirm_frames']:
                    raise Stopped('领取按钮下方消耗为 0，已停止')

                # Any uncertain zero reading pauses actions until it is confirmed or disproved.
                if zero_city or zero_cost:
                    self.wait(self.c['scan_interval'])
                    continue

                if state == 'home' and scene.page == 'home' and page_frames['home'] >= self.c['confirm_frames']:
                    state, since = 'cursor', self.clock()
                    cursor_frames = 0
                    self.message('图一已确认，先识别游戏光标；确认后才移动和滚动')
                elif state == 'cursor' and scene.page == 'home':
                    cursor_frames = cursor_frames + 1 if self.b.find_cursor() else 0
                    if cursor_frames >= self.c['confirm_frames']:
                        state, since = 'anchor', self.clock()
                        self.message('已识别游戏光标，寻找左侧连续三颗星的整体锚点')
                    else:
                        paused_reason = '等待确认游戏光标，请将鼠标置于游戏内容区'
                        self.message(paused_reason + '；停止按钮 / F8 可停止')
                elif state == 'anchor' and scene.page == 'home':
                    anchor = self.b.find_star_anchor()
                    if anchor is None:
                        paused_reason = '左侧未识别到连续三颗星的完整锚点，等待恢复'
                        self.message(paused_reason + '；停止按钮 / F8 可停止')
                    else:
                        self.check()
                        self.b.move_to_anchor(anchor)
                        at_bottom = False
                        state, since = 'select', self.clock()
                        self.message('光标移动已核验，逐批滚动并 OCR 寻找 3-10')
                elif state == 'select' and scene.page == 'home':
                    if self.b.select_level():
                        state, since = 'selected', self.clock()
                        self.message('OCR 识别到 3-10，已发送点击输入；等待右侧标题确认选中')
                    elif not at_bottom:
                        self.publish('scrolling', scene)
                        at_bottom = self.action('scroll_step') is False
                    else:
                        paused_reason = '两批滚动后列表未变化，无法确认是否到底或游戏未接收输入；暂停滚动，继续 OCR 等待 3-10'
                        self.message(paused_reason + '；停止按钮 / F8 可停止')
                elif state == 'selected' and scene.page == 'home' and scene.selected:
                    self.message('右侧标题已确认选中 3-10')
                    self.action('start')
                    state, since = 'starting', self.clock()
                    score_frames = 0
                    self.message('已发送开始营业点击输入，等待图三确认；倒计时出现后才开始锤子连点')
                elif state in ('starting', 'retrying', 'playing') and scene.page in ('ready', 'playing'):
                    if state != 'playing':
                        self.message('已识别倒计时 / 营业画面，确认开始营业成功')
                    state, since = 'playing', self.clock()
                    score_frames = score_frames + 1 if scene.score is not None and scene.score >= 1900 else 0
                    if score_frames >= self.c['confirm_frames']:
                        self.action('exit')
                        state, since = 'exiting', self.clock()
                        self.message(f'图六：营业额 {scene.score} 达标，已发送左上退出点击输入，等待结算画面')
                    elif not score_frames:
                        self.action('hammer')
                elif state in ('starting', 'retrying', 'playing', 'exiting') and page_frames['failure'] >= self.c['confirm_frames']:
                    self.failures += 1
                    self.publish('retrying', scene)
                    self.message(f'图五：连续失败 {self.failures}/3')
                    if self.failures >= 3:
                        raise Stopped('连续三次挑战失败，已停止')
                    self.action('retry')
                    state, since = 'retrying', self.clock()
                    score_frames = 0
                    # Do not count the same failure panel again while retry is loading.
                    state = 'retry_loading'
                elif state == 'retry_loading' and scene.page in ('ready', 'playing'):
                    state, since = 'retrying', self.clock()
                elif state in ('playing', 'exiting') and page_frames['success'] >= self.c['confirm_frames']:
                    # A missing cost is not treated as zero. Wait for readable reward data.
                    if scene.cost is None:
                        self.message('图七：消耗数字未识别，等待；F8 停止')
                        paused_reason = '领取消耗未识别，等待恢复'
                    else:
                        self.action('claim')
                        state, since = 'claiming', self.clock()
                        self.message(f'图七：消耗 {scene.cost}，已发送领取点击输入，等待返回图一确认')
                elif scene.page == 'unknown' or self.clock() - since > self.c['transition_timeout']:
                    cursor_frames = 0
                    self.message('界面错误或页面切换未完成：暂停操作，等待正确界面；F8 停止')
                    paused_reason = '界面错误或页面切换未完成'
                self.publish(state, scene, paused_reason)
            except Stopped:
                raise
            except Exception as error:
                self.message(f'运行错误，暂停本次操作并等待恢复：{error}；F8 停止')
                self.publish(state, reason=str(error))
            self.wait(self.c['click_interval'] if state == 'playing' else self.c['scan_interval'])


class ScreenReader:
    """Normalize the game client image to the supplied screenshots."""
    def __init__(self):
        import cv2
        import numpy as np
        from rapidocr_onnxruntime import RapidOCR
        self.cv, self.np = cv2, np
        self.ocr = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=2)
        self.templates = {}
        for name in ('home_title', 'home_start', 'game_title', 'hammer', 'ready', 'success', 'failure'):
            data = np.fromfile(ASSETS / f'{name}.png', np.uint8)
            self.templates[name] = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)
            if self.templates[name] is None:
                raise ValueError(f'缺少识别模板：{name}')

    def text(self, image):
        enlarged = self.cv.resize(image, None, fx=2, fy=2, interpolation=self.cv.INTER_CUBIC)
        rows, _ = self.ocr(enlarged)
        return ''.join(row[1] for row in sorted(rows or [], key=lambda r: min(p[0] for p in r[0])) if row[2] >= 0.65)

    def matches(self, frame, name, box, threshold=0.82):
        x, y, w, h = box
        gray = self.cv.cvtColor(frame[y:y+h, x:x+w], self.cv.COLOR_BGR2GRAY)
        template = self.templates[name]
        return float(self.cv.matchTemplate(gray, template, self.cv.TM_CCOEFF_NORMED).max()) >= threshold

    def inspect(self, frame):
        frame = self.cv.resize(frame, REFERENCE)
        if self.matches(frame, 'success', (1050, 210, 470, 150)):
            return Scene('success', city=fraction(self.text(frame[35:95, 2110:2300])), cost=integer(self.text(frame[1173:1225, 1590:1660])))
        if self.matches(frame, 'failure', (1050, 210, 470, 150)):
            return Scene('failure')
        if self.matches(frame, 'home_title', (10, 15, 380, 115)) and self.matches(frame, 'home_start', (2110, 1270, 400, 140)):
            title = self.text(frame[175:270, 495:1400])
            return Scene('home', city=fraction(self.text(frame[35:95, 2110:2300])), selected=self.is_level(title))
        if self.matches(frame, 'game_title', (2020, 20, 500, 120)) and self.matches(frame, 'hammer', (30, 520, 220, 180), 0.7):
            page = 'ready' if self.matches(frame, 'ready', (1030, 260, 500, 220), 0.78) else 'playing'
            return Scene(page, score=parse_score(self.text(frame[125:185, 2275:2490])))
        return Scene('unknown')

    @staticmethod
    def is_level(text):
        normalized = unicodedata.normalize('NFKC', text)
        normalized = re.sub(r'\s', '', normalized).replace('—', '-').replace('一', '-')
        return bool(re.search(r'(?<!\d)3[-–]?10(?!\d)', normalized))


class DesktopBackend:
    def __init__(self, stop=None, title='', hwnd=None, prepare=True, capture_shield=None, log=print):
        import pyautogui as pg
        self.pg = pg
        self.stop = stop
        self.capture_shield = capture_shield
        self.log = log
        pg.PAUSE = 0
        # F8 is the manual stop requested by the user; corners are not stop triggers.
        pg.FAILSAFE = False
        api = Win32()
        handle = choose_window(api, title, hwnd)
        self.window = GameWindow(api, handle, tuple(pg.size()))
        if prepare:
            self.guard(stop_only=True)
            api.activate(handle)
            time.sleep(0.3)
        self.window.area()
        from nte_input import WindowsMouse
        self.mouse = WindowsMouse(self.guard, self.stop)
        self.reader = ScreenReader()
        from nte_cursor import CursorDetector
        from nte_stars import StarAnchorDetector
        self.cursor_detector = CursorDetector()
        self.star_detector = StarAnchorDetector()
        self.scroll_stable = 0

    def frame(self):
        self.guard()
        area = self.window.area()
        capture = lambda: self.pg.screenshot(region=area.region())
        image = self.capture_shield.capture(capture) if self.capture_shield else capture()
        return self.reader.cv.cvtColor(self.reader.np.array(image), self.reader.cv.COLOR_RGB2BGR)

    def observe(self):
        return self.reader.inspect(self.frame())

    def point(self, x, y):
        return self.window.area().point(x, y, REFERENCE)

    def find_cursor(self):
        from nte_cursor import windows_cursor_bitmap
        frame = self.frame()
        area = self.window.area()
        x, y = self.pg.position()
        if self.cursor_detector.near_pointer(frame, x - area.x, y - area.y):
            return True
        cursor = windows_cursor_bitmap()
        if cursor:
            bitmap, (x, y) = cursor
            if area.x <= x < area.x + area.width and area.y <= y < area.y + area.height:
                return self.cursor_detector.matches(bitmap)
        return False

    def find_star_anchor(self):
        frame = self.reader.cv.resize(self.frame(), REFERENCE)
        self.scroll_stable = 0
        return self.star_detector.find(frame)

    def move_verified(self, x, y, label):
        result = self.mouse.move(*self.point(x, y))
        self.guard()
        # OS coordinates alone do not prove that a software-rendered game
        # cursor followed the event. Require the photographed arrow near target.
        for _ in range(3):
            if self.find_cursor():
                self.log(f'{label}：系统光标 {result.before} → {result.after}，目标 {result.target}；目标附近游戏光标已确认')
                return result
            self.mouse.wait(0.1)
            self.guard()
        raise ValueError(f'{label}：系统光标 {result.before} → {result.after}，但目标附近未确认游戏光标；暂停点击，请检查游戏是否接收输入')

    def move_to_anchor(self, anchor):
        return self.move_verified(*anchor.center, '移动到三星锚点')

    def scroll_step(self):
        cv = self.reader.cv
        frame = cv.resize(self.frame(), REFERENCE)
        anchor = self.star_detector.find(frame)
        if anchor is None:
            raise ValueError('左侧未识别到连续三颗星的完整锚点，暂停滚动')
        self.move_to_anchor(anchor)
        if self.stop is not None:
            if self.stop.wait(0.1):
                raise Stopped('已停止（停止按钮 / F8）')
        else:
            time.sleep(0.1)
        # Compare after repositioning the cursor; its movement/hover must not
        # be mistaken for the level list continuing to scroll at the bottom.
        before = cv.resize(self.frame(), REFERENCE)
        self.guard()
        self.mouse.scroll(-3)
        if self.stop is not None:
            if self.stop.wait(0.25):
                raise Stopped('已停止（停止按钮 / F8）')
        else:
            time.sleep(0.25)
        after = cv.resize(self.frame(), REFERENCE)
        before = cv.cvtColor(before[140:1390, :455], cv.COLOR_BGR2GRAY)
        after = cv.cvtColor(after[140:1390, :455], cv.COLOR_BGR2GRAY)
        self.scroll_stable = self.scroll_stable + 1 if float(cv.absdiff(before, after).mean()) < 1.0 else 0
        return self.scroll_stable < 2

    def action(self, name):
        self.guard()
        points = {'start': (2290, 1340), 'hammer': (125, 610), 'exit': (65, 64),
                  'claim': (1545, 1115), 'retry': (1545, 1115)}
        if name == 'scroll_step':
            return self.scroll_step()
        else:
            if name != 'hammer':
                labels = {'start': '开始营业', 'exit': '退出', 'claim': '领取奖励', 'retry': '重新挑战'}
                self.move_verified(*points[name], f'移动到{labels[name]}按钮')
            else:
                self.mouse.move(*self.point(*points[name]))
            self.guard()
            self.mouse.click()

    def select_level(self):
        frame = self.reader.cv.resize(self.frame(), REFERENCE)
        rows, _ = self.reader.ocr(frame[140:1390, :455])
        for box, text, confidence in rows or []:
            if confidence >= 0.65 and self.reader.is_level(text):
                x = sum(p[0] for p in box) / 4
                y = sum(p[1] for p in box) / 4 + 140
                self.move_verified(x, y, '移动到 OCR 3-10 关卡')
                self.guard()
                self.mouse.click()
                return True
        return False

    def guard(self, stop_only=False):
        if self.stop is not None and self.stop.is_set():
            raise Stopped('F8：已停止')
        if not stop_only:
            self.window.screen_size = tuple(self.pg.size())
            self.window.area()
