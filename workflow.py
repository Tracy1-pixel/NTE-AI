"""Figure 1–7 state machine and screenshot-driven desktop backend."""
from __future__ import annotations

import math
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from automation import Stopped, parse_score

REFERENCE = (2559, 1439)
ASSETS = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent)) / 'assets' / 'pianist'


def settings(saved=None):
    c = {'click_interval': 0.08, 'scan_interval': 0.25, 'confirm_frames': 3,
         'transition_timeout': 30.0, 'workflow_version': 2}
    for key in c:
        if key != 'workflow_version' and key in (saved or {}):
            c[key] = saved[key]
    for key in ('click_interval', 'scan_interval', 'transition_timeout'):
        if not math.isfinite(c[key]) or c[key] <= 0:
            raise ValueError(f'{key} 必须是大于零的有限数值')
    if not isinstance(c['confirm_frames'], int) or c['confirm_frames'] < 2:
        raise ValueError('连续确认帧数至少为 2')
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
    def __init__(self, config, backend, stop, clock=time.monotonic, sleep=time.sleep, log=print):
        self.c, self.b, self.stop = settings(config), backend, stop
        self.clock, self.sleep, self.log = clock, sleep, log
        self.failures = 0
        self.completed = 0
        self.last_message = None

    def check(self):
        if self.stop.is_set():
            raise Stopped('F8：已停止')

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
        self.b.action(name)
        if name != 'hammer':
            self.wait(0.3)

    def initial(self):
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
        scrolls = 0
        next_observe, scene = 0, None
        while True:
            self.check()
            try:
                if self.clock() < next_observe:
                    if state == 'playing' and scene.page in ('ready', 'playing') and not score_frames:
                        self.action('hammer')
                    self.wait(self.c['click_interval'])
                    continue
                scene = self.b.observe()
                next_observe = self.clock() + self.c['scan_interval']
                for page in ('home', 'success', 'failure'):
                    page_frames[page] = page_frames.get(page, 0) + 1 if scene.page == page else 0
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
                    scrolls = 0
                    self.action('scroll_bottom')
                    state, since = 'select', self.clock()
                    self.message('图一：已滚动关卡栏，寻找 3-10 钢！琴！家！')
                elif state == 'select' and scene.page == 'home':
                    if self.b.select_level():
                        state, since = 'selected', self.clock()
                    elif scrolls < 20:
                        self.action('scroll_bottom')
                        scrolls += 1
                    else:
                        self.message('界面错误：关卡栏未找到钢琴家；暂停操作，F8 停止')
                elif state == 'selected' and scene.page == 'home' and scene.selected:
                    self.action('start')
                    state, since = 'starting', self.clock()
                    score_frames = 0
                    self.message('已点击开始营业，等待图三；倒计时出现后即开始点击锤子')
                elif state in ('starting', 'retrying', 'playing') and scene.page in ('ready', 'playing'):
                    state, since = 'playing', self.clock()
                    score_frames = score_frames + 1 if scene.score is not None and scene.score >= 1900 else 0
                    if score_frames >= self.c['confirm_frames']:
                        self.action('exit')
                        state, since = 'exiting', self.clock()
                        self.message(f'图六：营业额 {scene.score} 达标，已点击左上退出图标')
                    elif not score_frames:
                        self.action('hammer')
                elif state in ('starting', 'retrying', 'playing', 'exiting') and page_frames['failure'] >= self.c['confirm_frames']:
                    self.failures += 1
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
                    else:
                        self.action('claim')
                        state, since = 'claiming', self.clock()
                        self.message(f'图七：消耗 {scene.cost}，已点击领取奖励')
                elif state == 'claiming' and page_frames['home'] >= self.c['confirm_frames']:
                    self.completed += 1
                    self.failures = 0
                    self.message(f'领取完成，已完成 {self.completed} 轮，返回图一继续')
                    state, since = 'home', self.clock()
                elif scene.page == 'unknown' or self.clock() - since > self.c['transition_timeout']:
                    self.message('界面错误或页面切换未完成：暂停操作，等待正确界面；F8 停止')
            except Stopped:
                raise
            except Exception as error:
                self.message(f'运行错误，暂停本次操作并等待恢复：{error}；F8 停止')
            self.wait(self.c['click_interval'] if state == 'playing' else self.c['scan_interval'])


class ScreenReader:
    """Normalize a full-screen 16:9 game to the supplied screenshots."""
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
        normalized = re.sub(r'\s', '', text).replace('—', '-').replace('一', '-')
        return bool(re.search(r'3[-–]?10', normalized) and any(c in text for c in '钢琴家'))


class DesktopBackend:
    def __init__(self, stop=None):
        import pyautogui as pg
        self.pg = pg
        self.stop = stop
        pg.PAUSE = 0
        # F8 is the manual stop requested by the user; corners are not stop triggers.
        pg.FAILSAFE = False
        self.reader = ScreenReader()
        self.size = tuple(pg.size())
        if abs(self.size[0] / self.size[1] - REFERENCE[0] / REFERENCE[1]) > 0.04:
            raise ValueError('请使用主屏幕 16:9 全屏或无边框游戏画面')

    def frame(self):
        if tuple(self.pg.size()) != self.size:
            raise ValueError('屏幕分辨率已改变，请按 F8 后重新启动')
        return self.reader.cv.cvtColor(self.reader.np.array(self.pg.screenshot()), self.reader.cv.COLOR_RGB2BGR)

    def observe(self):
        return self.reader.inspect(self.frame())

    def point(self, x, y):
        return round(x * self.size[0] / REFERENCE[0]), round(y * self.size[1] / REFERENCE[1])

    def action(self, name):
        self.guard()
        points = {'start': (2290, 1340), 'hammer': (125, 610), 'exit': (65, 64),
                  'claim': (1545, 1115), 'retry': (1545, 1115)}
        if name == 'scroll_bottom':
            self.pg.moveTo(*self.point(230, 1060))
            self.pg.scroll(-15)
        else:
            self.pg.click(*self.point(*points[name]))

    def select_level(self):
        frame = self.reader.cv.resize(self.frame(), REFERENCE)
        rows, _ = self.reader.ocr(frame[140:1390, :455])
        for box, text, confidence in rows or []:
            if confidence >= 0.65 and self.reader.is_level(text):
                x = sum(p[0] for p in box) / 4
                y = sum(p[1] for p in box) / 4 + 140
                self.guard()
                self.pg.click(*self.point(x, y))
                return True
        return False

    def guard(self):
        if self.stop is not None and self.stop.is_set():
            raise Stopped('F8：已停止')
