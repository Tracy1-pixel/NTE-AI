"""Auction preparation and passive observation of the matching/loading phase."""
from dataclasses import dataclass
import re
import unicodedata

from automation import Stopped
from nte_workflow import Controller, DesktopBackend, REFERENCE

TARGET = '至尊仪器组'
USE_LABELS = ('购买并使用', '使用', '一键补齐', '一键补全')
START_LABELS = ('开始匹配', '开始拍卖')


def compact(text):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', text))


@dataclass(frozen=True)
class Box:
    x: float
    y: float
    width: float
    height: float

    @property
    def center(self):
        return self.x + self.width / 2, self.y + self.height / 2

    def contains(self, point):
        return self.x <= point[0] <= self.x + self.width and self.y <= point[1] <= self.y + self.height


@dataclass
class AuctionScene:
    page: str
    group: Box | None = None
    listing: Box | None = None
    target: Box | None = None
    selected: bool = False
    frame: object = None
    use: Box | None = None
    use_label: str = ''
    start: Box | None = None
    confirm: Box | None = None
    progress: int | None = None


class AuctionReader:
    def __init__(self, reader):
        self.reader, self.cv = reader, reader.cv

    def inspect(self, frame):
        frame = self.cv.resize(frame, REFERENCE)
        rows, _ = self.reader.ocr(frame)
        return self.from_rows(rows or [], frame)

    def from_rows(self, rows, frame):
        words = []
        for points, text, confidence in rows:
            if confidence < 0.65:
                continue
            x, y = min(p[0] for p in points), min(p[1] for p in points)
            words.append((compact(text), Box(x, y, max(p[0] for p in points) - x, max(p[1] for p in points) - y)))
        width, height = REFERENCE
        loading = [(int(match.group(1)), box) for text, box in words
                   if (match := re.fullmatch(r'(\d{1,3})%', text)) and int(match.group(1)) <= 100
                   and box.center[0] > width * 0.75 and box.center[1] > height * 0.85]
        if len(loading) == 1 and self.loading_graphic(frame, loading[0][1]):
            return AuctionScene('loading', frame=frame, progress=loading[0][0])
        fees = [box for text, box in words if '入场费' in text]
        confirms = [box for text, box in words if text == '确认']
        cancels = [box for text, box in words if text == '取消']
        combined = ''.join(text for text, _ in words)
        if fees and '匹配成功后' in combined and '扣除' in combined and '是否继续' in combined:
            if len(confirms) == len(cancels) == 1:
                confirm, cancel = confirms[0], cancels[0]
                body_bottom = max(box.y + box.height for box in fees)
                if confirm.y > body_bottom and cancel.y > body_bottom and confirm.x > cancel.x and abs(confirm.center[1] - cancel.center[1]) < max(confirm.height, cancel.height):
                    return AuctionScene('entry_confirm', confirm=confirm, frame=frame)
            return AuctionScene('unknown')
        titles = [box for text, box in words if text == '仪器组合']
        contents = [box for text, box in words if text == '内含下列仪器']
        if len(titles) == len(contents) == 1:
            title, content = titles[0], contents[0]
            scale = max(1, title.height)
            left = max(0, title.x - scale * 0.7)
            right = content.x - scale * 2.5
            top = content.y - scale * 0.5
            buttons = [(text, box) for text, box in words if text in USE_LABELS and box.y > content.y + scale * 10 and title.x + (content.x - title.x) * 0.9 < box.center[0] < content.x + scale * 13]
            bottom = min(box.y for _, box in buttons) - scale if buttons else min(height, top + scale * 23)
            if right - left < scale * 5 or bottom - top < scale * 5 or top <= title.y:
                return AuctionScene('unknown')
            listing = Box(left, top, right - left, bottom - top)
            targets = [box for text, box in words if re.fullmatch(TARGET + r'(?:剩余[:：]?\d+)?', text) and listing.contains(box.center)]
            # Ambiguous OCR never authorizes a click on one arbitrary row.
            target = targets[0] if len(targets) == 1 else None
            selected = target is not None and self.selected_border(frame, listing, target)
            use_label, use = buttons[0] if len(buttons) == 1 else ('', None)
            return AuctionScene('instruments', listing=listing, target=target, selected=selected, frame=frame, use=use, use_label=use_label)
        if titles or contents:
            return AuctionScene('unknown')
        home_title = any(text == '即刻落槌' and box.center[0] < width * 0.3 and box.center[1] < height * 0.2 for text, box in words)
        start = [box for text, box in words if text in START_LABELS and box.center[0] > width * 0.55 and box.center[1] > height * 0.65]
        groups = [box for text, box in words if re.fullmatch(r'(?:初级|中级|高级|至尊)\S{0,8}仪器组', text) and box.center[0] > width * 0.55 and height * 0.60 < box.center[1] < height * 0.88]
        if home_title and len(start) == 1 and len(groups) == 1 and groups[0].y < start[0].y:
            return AuctionScene('home', group=groups[0], frame=frame, start=start[0])
        return AuctionScene('unknown')

    def loading_graphic(self, frame, percent):
        # A percentage alone is insufficient: require the broad gray silhouette
        # immediately to its left, on the dark lower-right loading background.
        # This is a visual structure check, not a template of the supplied animal.
        if frame is None:
            return False
        h = max(1, percent.height)
        left, top = max(0, int(percent.x - h * 7)), max(0, int(percent.y - h * 1.5))
        right, bottom = int(percent.x), min(frame.shape[0], int(percent.y + h * 2))
        crop = frame[top:bottom, left:right]
        if not crop.size:
            return False
        hsv = self.cv.cvtColor(crop, self.cv.COLOR_BGR2HSV)
        if (hsv[:, :, 2] < 65).mean() < 0.55:
            return False
        mask = self.cv.inRange(hsv, (0, 0, 65), (179, 55, 210))
        contours, _ = self.cv.findContours(mask, self.cv.RETR_EXTERNAL, self.cv.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            x, y, w, ch = self.cv.boundingRect(contour)
            if h * 2 < w < h * 7 and h * 0.7 < ch < h * 3 and 1.4 < w / ch < 5:
                if self.cv.contourArea(contour) > w * ch * 0.2 and abs(top + y + ch / 2 - percent.center[1]) < h:
                    return True
        return False

    def selected_border(self, frame, listing, target):
        if frame is None:
            return False
        # The supplied third image uses a pink outline for the selected card.
        # Require an enclosing outline, rather than a pink icon elsewhere.
        x = max(0, int(listing.x - target.height))
        y = max(0, int(listing.y - target.height))
        right = min(frame.shape[1], int(listing.x + listing.width + target.height))
        bottom = min(frame.shape[0], int(listing.y + listing.height))
        crop = frame[y:bottom, x:right]
        if not crop.size:
            return False
        hsv = self.cv.cvtColor(crop, self.cv.COLOR_BGR2HSV)
        mask = self.cv.inRange(hsv, (140, 110, 110), (179, 255, 255))
        contours, _ = self.cv.findContours(mask, self.cv.RETR_EXTERNAL, self.cv.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            bx, by, w, h = self.cv.boundingRect(contour)
            card = Box(x + bx, y + by, w, h)
            if h >= target.height * 2.5 and w > h * 1.4 and card.contains((target.x, target.y)) and card.contains((target.x + target.width, target.y + target.height)):
                area = abs(self.cv.contourArea(contour))
                if area >= w * h * 0.6:
                    return True
        return False


class AuctionBackend(DesktopBackend):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.auction_reader = AuctionReader(self.reader)
        self.list_stable = 0

    def observe(self):
        return self.auction_reader.inspect(self.frame())

    def confirm_pointer(self, point):
        target = self.point(*point)
        cursor = self.cursor_position()
        if cursor is None or max(abs(a-b) for a, b in zip(cursor.point, target)) > 8:
            raise ValueError('识别后光标已离开目标，暂停输入并重新定位')

    def click_checked(self, scene, action='select'):
        targets = {'open': 'group', 'select': 'target', 'use': 'use', 'start': 'start', 'confirm': 'confirm'}
        labels = {'open': '仪器组方框', 'select': TARGET, 'use': scene.use_label, 'start': '开始拍卖按钮', 'confirm': '入场确认按钮'}
        target = getattr(scene, targets[action])
        if target is None:
            raise ValueError('没有唯一操作按钮位置，暂停点击')
        self.move_verified(*target.center, '移动到' + labels[action])
        fresh = self.observe()
        current = getattr(fresh, targets[action])
        expected = 'entry_confirm' if action == 'confirm' else ('home' if action in ('open', 'start') else 'instruments')
        if fresh.page != expected or current is None or max(abs(a-b) for a, b in zip(current.center, target.center)) > 16:
            raise ValueError('移动后仪器组界面或位置变化，重新识别后再点击')
        if action == 'use' and (not fresh.selected or fresh.target is None or fresh.use_label != scene.use_label):
            raise ValueError('未确认至尊仪器组仍被选中或底部按钮已变化，暂停使用')
        self.confirm_pointer(current.center)
        self.guard()
        self.mouse.click()

    def scroll_groups(self, scene):
        if scene.page != 'instruments' or scene.listing is None:
            raise ValueError('未定位左侧仪器组列表，暂停滚动')
        self.move_verified(*scene.listing.center, '移动到左侧仪器组列表')
        fresh = self.observe()
        if fresh.page != 'instruments' or fresh.listing is None or max(abs(a-b) for a, b in zip(fresh.listing.center, scene.listing.center)) > 16:
            raise ValueError('左侧仪器组列表位置变化，暂停滚动')
        box = fresh.listing
        self.confirm_pointer(box.center)
        x, y, right, bottom = map(int, (box.x, box.y, box.x + box.width, box.y + box.height))
        before = fresh.frame[y:bottom, x:right]
        self.guard()
        self.mouse.scroll(-3)
        self.mouse.wait(self.scroll_interval)
        after = self.reader.cv.resize(self.frame(), REFERENCE)[y:bottom, x:right]
        difference = float(self.reader.cv.absdiff(before, after).mean())
        self.list_stable = self.list_stable + 1 if difference < 1 else 0
        return self.list_stable < 2


class AuctionController(Controller):
    def publish(self, phase, reason='', completed=False):
        if self.report:
            self.report({'mode': 'auction', 'level': TARGET, 'goal': None, 'score': None,
                         'phase': '已暂停' if reason else phase,
                         'state': 'paused' if reason else ('stopped' if completed else 'running'),
                         'details': reason or phase, 'completed': int(completed), 'failures': 0})

    def run(self):
        self.publish('确认即刻落槌初始界面')
        for _ in range(self.c['confirm_frames']):
            self.check()
            if self.b.observe().page != 'home':
                raise Stopped('界面错误：请从即刻落槌初始界面开始')
            self.wait(self.c['scan_interval'])
        state = 'cursor'
        cursor_frames = dialog_frames = selected_frames = 0
        edge = False
        while True:
            self.check()
            try:
                scene = self.b.observe()
                self.check()
                if state in ('await_loading', 'loading'):
                    # These states intentionally never send mouse input, even
                    # when the percentage reaches 100 or a previous page returns.
                    if scene.page == 'loading':
                        dialog_frames = 0
                        if state != 'loading':
                            self.message('已识别右下角加载标识，仅观察状态，不进行鼠标操作')
                        state = 'loading'
                        self.publish(f'加载中 {scene.progress}%' if scene.progress is not None else '加载中')
                    elif state == 'loading':
                        dialog_frames += 1
                        self.publish('等待加载画面切换')
                        if dialog_frames >= self.c['confirm_frames']:
                            self.completed = 1
                            self.message('加载标识已连续消失；后续游戏画面与操作等待补充')
                            self.publish('等待后续流程', completed=True)
                            return
                    else:
                        self.publish('等待匹配成功 / 加载画面')
                elif scene.page == 'unknown':
                    cursor_frames = dialog_frames = selected_frames = 0
                    self.publish('等待识别', '即刻落槌界面未确认，暂停操作并等待恢复；F8 停止')
                elif state == 'cursor' and scene.page == 'home':
                    self.publish('识别游戏光标')
                    cursor_frames = cursor_frames + 1 if self.b.find_cursor() else 0
                    if cursor_frames >= self.c['confirm_frames']:
                        self.b.click_checked(scene, 'open')
                        self.message('已发送仪器组方框点击，等待仪器组合弹窗确认')
                        state = 'opening'
                    else:
                        self.message('等待确认游戏光标，请将鼠标置于游戏内容区；F8 停止')
                elif state == 'opening':
                    self.publish('等待仪器组合弹窗')
                    dialog_frames = dialog_frames + 1 if scene.page == 'instruments' else 0
                    if dialog_frames >= self.c['confirm_frames']:
                        state = 'search'
                        self.message('已确认仪器组合弹窗，在左侧列表寻找至尊仪器组')
                elif state == 'search' and scene.page == 'instruments':
                    self.publish('左侧列表寻找至尊仪器组')
                    if scene.target is not None:
                        self.b.click_checked(scene)
                        state = 'confirm'
                        self.message('已发送至尊仪器组点击，等待选中边框确认')
                    elif not edge:
                        edge = self.b.scroll_groups(scene) is False
                    else:
                        self.publish('等待识别', '两批滚动后列表未变化，暂停滚轮并等待识别至尊仪器组；F8 停止')
                elif state == 'confirm' and scene.page == 'instruments':
                    self.publish('确认至尊仪器组选中')
                    selected_frames = selected_frames + 1 if scene.target is not None and scene.selected else 0
                    if selected_frames >= self.c['confirm_frames']:
                        if scene.use is None:
                            self.publish('等待底部按钮', '已选中至尊仪器组，但底部使用按钮未能唯一识别，等待恢复；F8 停止')
                        else:
                            self.b.click_checked(scene, 'use')
                            self.message(f'已发送“{scene.use_label}”点击，等待返回即刻落槌初始界面')
                            state = 'returning'
                            dialog_frames = 0
                elif state == 'returning':
                    self.publish('等待返回初始界面')
                    dialog_frames = dialog_frames + 1 if scene.page == 'home' else 0
                    if dialog_frames >= self.c['confirm_frames']:
                        self.b.click_checked(scene, 'start')
                        self.message('已确认返回初始界面并发送开始拍卖点击，等待入场费确认')
                        state = 'matching'
                        dialog_frames = 0
                elif state == 'matching':
                    self.publish('等待入场费确认')
                    dialog_frames = dialog_frames + 1 if scene.page == 'entry_confirm' else 0
                    if dialog_frames >= self.c['confirm_frames']:
                        self.b.click_checked(scene, 'confirm')
                        self.message('已发送入场确认点击，等待匹配成功与加载画面')
                        state = 'await_loading'
                        dialog_frames = 0
                else:
                    cursor_frames = dialog_frames = selected_frames = 0
                    self.publish('等待识别', '界面切换未完成，暂停操作等待恢复；F8 停止')
            except Stopped:
                raise
            except Exception as error:
                cursor_frames = dialog_frames = selected_frames = 0
                self.message(f'即刻落槌操作暂停：{error}；F8 停止')
                self.publish('等待恢复', str(error))
            self.wait(self.c['scan_interval'])
