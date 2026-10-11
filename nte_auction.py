"""Auction entry, loading observation, and nine-cell average instrument use."""
from dataclasses import dataclass
import re
import time
import unicodedata

import numpy as np

from automation import Stopped
from nte_workflow import Controller, DesktopBackend, REFERENCE

TARGET = '至尊仪器组'
AVERAGE_INSTRUMENT = '九格均价仪器'
BID_THRESHOLD = 500000
BID_AMOUNT = 5000000
USE_LABELS = ('购买并使用', '使用', '一键补齐', '一键补全')
START_LABELS = ('开始匹配', '开始拍卖')

# Fractions of the game content area, never desktop coordinates. Separate
# patches are packed for one OCR invocation; returned boxes map back to the
# original reference frame before scene parsing or mouse coordinate conversion.
HOME_REGIONS = ((0, 0, .30, .20),)
RETURN_REGIONS = HOME_REGIONS + ((.70, .82, 1, 1),)
PREP_REGIONS = ((.18, .04, .86, .97),)
LIST_REGIONS = ((.26, .02, .76, .97),)
GAME_REGIONS = ((.24, 0, .80, .84), (0, 0, .08, .15), (.08, .85, .35, 1), (.70, .85, 1, 1))
KEYPAD_REGIONS = ((.18, .45, .82, .97),)
DIALOG_REGIONS = ((.08, 0, .99, .85), (.05, .85, .99, 1))
RESULT_REGIONS = ((.03, .09, .42, .32), (.04, .38, .65, .60), (.67, .85, .99, 1))
OCR_REGIONS = {
    **dict.fromkeys(('home', 'cursor'), HOME_REGIONS),
    **dict.fromkeys(('returning', 'returning_home'), RETURN_REGIONS),
    **dict.fromkeys(('opening', 'search', 'confirm', 'instruments'), PREP_REGIONS),
    **dict.fromkeys(('game_opening', 'game_search', 'game_selected', 'instrument_list'), LIST_REGIONS),
    **dict.fromkeys(('await_loading', 'loading', 'read_average', 'game'), GAME_REGIONS),
    **dict.fromkeys(('bid_opening', 'bid_fill', 'bid_verify', 'bid_input'), KEYPAD_REGIONS),
    **dict.fromkeys(('matching', 'exiting', 'bid_submitted', 'entry_confirm', 'exit_confirm', 'bid_confirm'), DIALOG_REGIONS),
    **dict.fromkeys(('waiting_result', 'result_skipped', 'result'), RESULT_REGIONS),
}
REGION_PAGES = {HOME_REGIONS: ('home',), RETURN_REGIONS: ('home', 'loading'),
                PREP_REGIONS: ('instruments',), LIST_REGIONS: ('instrument_list',),
                GAME_REGIONS: ('game', 'loading'), KEYPAD_REGIONS: ('bid_input',),
                DIALOG_REGIONS: ('entry_confirm', 'exit_confirm', 'bid_confirm', 'game', 'home'),
                RESULT_REGIONS: ('result',)}


def compact(text):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', text))


def money(text):
    if re.fullmatch(r'[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+', text):
        return int(text.replace(',', ''))
    return None


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
    instrument: Box | None = None
    average: int | None = None
    round_number: int | None = None
    countdown: int | None = None
    bid: Box | None = None
    exit: Box | None = None
    keys: dict | None = None
    bid_submit: Box | None = None
    bid_amount: int | None = None
    skip: Box | None = None
    result_exit: Box | None = None


class AuctionReader:
    def __init__(self, reader):
        self.reader, self.cv = reader, reader.cv
        self.next_full_scan = {}
        self.full_scan_regions = set()

    def inspect(self, frame, stage='auto'):
        frame = self.cv.resize(frame, REFERENCE)
        regions = OCR_REGIONS.get(stage)
        if regions is None or regions in self.full_scan_regions:
            rows, _ = self.reader.ocr(frame, use_cls=False)
            return self.from_rows(rows or [], frame)
        scene = self.from_rows(self.region_rows(frame, regions), frame)
        # Home confirmation deliberately reads only the top-left title. A full
        # fresh scan locates actual buttons immediately before a home action.
        missing_value = stage == 'read_average' and scene.page == 'game' and scene.average is None
        if (scene.page != 'unknown' and not missing_value) or stage in ('home', 'cursor'):
            return scene
        now = time.monotonic()
        if now < self.next_full_scan.get(regions, 0):
            return scene
        self.next_full_scan[regions] = now + 2
        rows, _ = self.reader.ocr(frame, use_cls=False)
        recovered = self.from_rows(rows or [], frame)
        if recovered.page in REGION_PAGES[regions] and not (stage == 'read_average' and recovered.average is None):
            # A successful full scan switches this region layout to fresh full
            # scans for this run. Otherwise intervening failed crops would reset
            # consecutive confirmation counters and prevent recovery entirely.
            self.full_scan_regions.add(regions)
        return recovered

    def region_rows(self, frame, regions):
        patches, packed_height = [], 0
        for left, top, right, bottom in regions:
            x, y, r, b = int(left * frame.shape[1]), int(top * frame.shape[0]), int(right * frame.shape[1]), int(bottom * frame.shape[0])
            patch = frame[y:b, x:r]
            patches.append((patch, x, y, packed_height))
            packed_height += patch.shape[0] + 24
        canvas = np.zeros((packed_height - 24, max(p[0].shape[1] for p in patches), 3), dtype=frame.dtype)
        for patch, _, _, offset in patches:
            canvas[offset:offset + patch.shape[0], :patch.shape[1]] = patch
        # Keep the original letter size for the two dense instrument panels.
        max_side = 2000 if regions in (PREP_REGIONS, LIST_REGIONS) else 1280
        scale = min(1, max_side / max(canvas.shape[:2]))
        ocr_canvas = self.cv.resize(canvas, (round(canvas.shape[1] * scale), round(canvas.shape[0] * scale))) if scale < 1 else canvas
        scale_x, scale_y = ocr_canvas.shape[1] / canvas.shape[1], ocr_canvas.shape[0] / canvas.shape[0]
        rows, _ = self.reader.ocr(ocr_canvas, use_cls=False)
        mapped = []
        for points, text, confidence in rows or []:
            points = [[px / scale_x, py / scale_y] for px, py in points]
            for patch, x, y, offset in patches:
                # Text touching a crop edge may be a truncated number. It must
                # never become a smaller valid amount or a partial button label.
                if all(16 <= px < patch.shape[1] - 16 and offset + 16 <= py < offset + patch.shape[0] - 16 for px, py in points):
                    mapped.append(([[px + x, py - offset + y] for px, py in points], text, confidence))
                    break
        return mapped

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
        exit_bodies = [box for text, box in words if '退出当前竞拍会场' in text or '不返还本局入场费' in text]
        if any(text == '确认退出' for text, _ in words):
            if exit_bodies and all(label in combined for label in ('是否退出当前竞拍会场', '放弃竞拍', '不返还本局入场费')) and len(confirms) == len(cancels) == 1:
                confirm, cancel = confirms[0], cancels[0]
                bottom = max(box.y + box.height for box in exit_bodies)
                if min(confirm.y, cancel.y) > bottom and confirm.x > cancel.x and abs(confirm.center[1] - cancel.center[1]) < max(confirm.height, cancel.height):
                    return AuctionScene('exit_confirm', confirm=confirm, frame=frame)
            return AuctionScene('unknown')
        bid_warning = [box for text, box in words if '当前出价' in text or '是否确认出价' in text]
        warning_amounts = re.findall(r'检测到当前出价([0-9,]+)疑似异常过高[,，]?是否确认出价[?？]?', combined)
        if bid_warning and warning_amounts:
            amount = money(warning_amounts[0]) if len(warning_amounts) == 1 else None
            if amount is not None and len(confirms) == len(cancels) == 1:
                confirm, cancel = confirms[0], cancels[0]
                if confirm.y > max(box.y + box.height for box in bid_warning) and cancel.y > max(box.y + box.height for box in bid_warning) and confirm.x > cancel.x and abs(confirm.center[1] - cancel.center[1]) < max(confirm.height, cancel.height):
                    return AuctionScene('bid_confirm', confirm=confirm, bid_amount=amount, frame=frame)
            return AuctionScene('unknown')
        if fees and '匹配成功后' in combined and '扣除' in combined and '是否继续' in combined:
            if len(confirms) == len(cancels) == 1:
                confirm, cancel = confirms[0], cancels[0]
                body_bottom = max(box.y + box.height for box in fees)
                if confirm.y > body_bottom and cancel.y > body_bottom and confirm.x > cancel.x and abs(confirm.center[1] - cancel.center[1]) < max(confirm.height, cancel.height):
                    return AuctionScene('entry_confirm', confirm=confirm, frame=frame)
            return AuctionScene('unknown')
        if (confirms and cancels) or ((confirms or cancels) and any(text == '提示' for text, _ in words)):
            return AuctionScene('unknown')
        result_titles = [box for text, box in words if text == '竞拍结束' and box.center[0] < width * 0.4
                         and box.center[1] < height * 0.3]
        if result_titles:
            skips = [box for text, box in words if text == '跳过动画' and box.center[0] > width * 0.6
                     and box.center[1] > height * 0.85]
            exits = [box for text, box in words if re.fullmatch(r'退出(?:\(\d+[sS秒]\))?', text)
                     and box.center[0] > width * 0.8 and box.center[1] > height * 0.85]
            if len(result_titles) == len(exits) == 1 and len(skips) <= 1 and all(any(text == label for text, _ in words) for label in ('最终成交价', '实际价值', '收益')):
                return AuctionScene('result', skip=skips[0] if skips else None, result_exit=exits[0], frame=frame)
            return AuctionScene('unknown')
        keypad = self.bid_keypad(words, frame)
        if keypad is not None:
            return keypad
        instrument_titles = [box for text, box in words if text == '仪器列表']
        if instrument_titles:
            if len(instrument_titles) != 1:
                return AuctionScene('unknown')
            title = instrument_titles[0]
            scale = max(1, title.height)
            buttons = [box for text, box in words if text == '使用' and box.y > title.y + scale * 10
                       and title.x + scale * 3 < box.center[0] < title.x + scale * 17]
            if len(buttons) != 1:
                return AuctionScene('unknown')
            use = buttons[0]
            left = max(0, title.x - scale * 0.7)
            listing = Box(left, title.y + scale * 2, min(width, 2 * use.center[0] - left) - left,
                          use.y - scale * 1.3 - (title.y + scale * 2))
            if listing.width < scale * 5 or listing.height < scale * 5:
                return AuctionScene('unknown')
            targets = [box for text, box in words if text == AVERAGE_INSTRUMENT and listing.contains(box.center)]
            target = targets[0] if len(targets) == 1 else None
            # Several usable instruments can have pink borders simultaneously.
            # This indicates availability; the controller still explicitly clicks
            # the average instrument before authorizing the footer's use button.
            available = target is not None and self.selected_border(frame, listing, target)
            return AuctionScene('instrument_list', listing=listing, target=target, selected=available,
                                use=use, use_label='使用', frame=frame)
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
        instruments = [box for text, box in words if text == '仪器' and width * 0.08 < box.center[0] < width * 0.35
                       and box.center[1] > height * 0.85]
        bids = [box for text, box in words if text == '出价' and box.center[0] > width * 0.78
                and box.center[1] > height * 0.85]
        rounds = [(int(match.group(1)), box) for text, box in words
                  if (match := re.fullmatch(r'竞拍第(\d{1,2})回合', text)) and int(match.group(1)) > 0
                  and width * 0.35 < box.center[0] < width * 0.65 and height * 0.12 < box.center[1] < height * 0.35]
        if len(instruments) == len(bids) == len(rounds) == 1:
            timers = [int(match.group(1)) * 60 + int(match.group(2)) for text, box in words
                      if (match := re.fullmatch(r'(\d{1,2}):([0-5]\d)', text))
                      and width * 0.4 < box.center[0] < width * 0.6 and box.center[1] < height * 0.12]
            escape = [box for text, box in words if text == 'ESC' and box.center[0] < width * 0.08 and box.center[1] < height * 0.15]
            exit_icon = None
            if len(escape) == 1:
                label = escape[0]
                exit_icon = Box(label.x, max(0, label.y - label.height * 3), label.width, label.height * 2.5)
            return AuctionScene('game', instrument=instruments[0], bid=bids[0], exit=exit_icon, frame=frame, average=self.average_value(words),
                                round_number=rounds[0][0], countdown=timers[0] if len(timers) == 1 else None)
        home_title = any(text == '即刻落槌' and box.center[0] < width * 0.3 and box.center[1] < height * 0.2 for text, box in words)
        start = [box for text, box in words if text in START_LABELS and box.center[0] > width * 0.55 and box.center[1] > height * 0.65]
        groups = [box for text, box in words if re.fullmatch(r'(?:初级|中级|高级|至尊)\S{0,8}仪器组', text) and box.center[0] > width * 0.55 and height * 0.60 < box.center[1] < height * 0.88]
        if home_title:
            return AuctionScene('home', group=groups[0] if len(groups) == 1 else None,
                                frame=frame, start=start[0] if len(start) == 1 else None)
        return AuctionScene('unknown')

    def bid_keypad(self, words, frame):
        prompts = [box for text, box in words if text == '请输入你愿意出的价格']
        submits = [box for text, box in words if text == '确认出价']
        if not prompts and not submits:
            return None
        if len(prompts) != 1 or len(submits) != 1:
            return AuctionScene('unknown')
        prompt, submit = prompts[0], submits[0]
        width, height = REFERENCE
        if prompt.center[0] < width * 0.55 or submit.y <= prompt.y or submit.center[1] < height * 0.8:
            return AuctionScene('unknown')
        clears = [box for text, box in words if text == '清空' and width * 0.35 < box.center[0] < width * 0.6
                  and box.center[1] > height * 0.8]
        if len(clears) != 1:
            return AuctionScene('unknown')
        clear = clears[0]
        keys = {'clear': clear}
        for label in ('00', '0000'):
            candidates = [box for text, box in words if text == label and width * 0.15 < box.center[0] < clear.x
                          and abs(box.center[1] - clear.center[1]) < clear.height]
            if len(candidates) != 1:
                return AuctionScene('unknown')
            keys[label] = candidates[0]
        columns = [keys[label].center[0] for label in ('00', '0000')]
        if not columns[0] < columns[1] < clear.x:
            return AuctionScene('unknown')
        gaps = (columns[1] - columns[0], clear.center[0] - columns[1])
        if min(gaps) < clear.height * 1.5 or abs(gaps[0] - gaps[1]) > clear.height * 2:
            return AuctionScene('unknown')
        fives = [box for text, box in words if text == '5' and abs(box.center[0] - columns[0]) < max(clear.height, box.height)
                 and clear.y - clear.height * 12 < box.center[1] < keys['00'].y]
        if len(fives) != 1:
            return AuctionScene('unknown')
        keys['5'] = fives[0]
        step = (keys['00'].center[1] - keys['5'].center[1]) / 2
        if not clear.height * 1.5 < step < clear.height * 6:
            return AuctionScene('unknown')
        area = Box(prompt.x - prompt.height * 1.5, prompt.y + prompt.height * 2.3,
                   max(prompt.width, submit.width) * 1.6, submit.y - prompt.height - (prompt.y + prompt.height * 2.3))
        amounts = [money(text) for text, box in words if area.contains(box.center) and money(text) is not None]
        return AuctionScene('bid_input', keys=keys, bid_submit=submit,
                            bid_amount=amounts[0] if len(amounts) == 1 else None, frame=frame)

    def average_value(self, words):
        width, height = REFERENCE
        headings = [box for text, box in words if text == AVERAGE_INSTRUMENT
                    and width * 0.3 < box.center[0] < width * 0.65 and height * 0.2 < box.y < height * 0.85]
        if len(headings) != 1:
            return None
        title = headings[0]
        area = Box(title.x - title.height * 0.4, title.y + title.height * 1.1,
                   min(width * 0.38, title.width * 4), title.height * 3)
        lines = []
        for text, box in sorted(words, key=lambda item: (item[1].center[1], item[1].x)):
            if not area.contains(box.center):
                continue
            if lines and abs(lines[-1][-1][1].center[1] - box.center[1]) < max(box.height, title.height) * 0.5:
                lines[-1].append((text, box))
            else:
                lines.append([(text, box)])
        values = []
        for line in lines:
            ordered = sorted(line, key=lambda item: item[1].x)
            # Join text and number only when OCR boxes actually share this line.
            if any(right.x - (left.x + left.width) > title.height * 2
                   for (_, left), (_, right) in zip(ordered, ordered[1:])):
                continue
            text = ''.join(text for text, _ in ordered)
            match = re.fullmatch(r'(?:本局内)?九格藏品的平均价值(?:为|是)[:：]?([0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)[。.!！]?', text)
            if match:
                values.append(int(match.group(1).replace(',', '')))
        return values[0] if len(values) == 1 else None

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
        return self.auction_reader.inspect(self.frame(), getattr(self, 'ocr_stage', 'auto'))

    def confirm_pointer(self, point):
        target = self.point(*point)
        cursor = self.cursor_position()
        if cursor is None or max(abs(a-b) for a, b in zip(cursor.point, target)) > 8:
            raise ValueError('识别后光标已离开目标，暂停输入并重新定位')

    def click_checked(self, scene, action='select'):
        targets = {'open': 'group', 'select': 'target', 'use': 'use', 'start': 'start', 'confirm': 'confirm',
                   'game_open': 'instrument', 'average_select': 'target', 'average_use': 'use',
                   'bid_open': 'bid', 'exit': 'exit', 'bid_submit': 'bid_submit', 'bid_confirm': 'confirm',
                   'exit_confirm': 'confirm', 'skip': 'skip', 'result_exit': 'result_exit'}
        labels = {'open': '仪器组方框', 'select': TARGET, 'use': scene.use_label, 'start': '开始拍卖按钮',
                  'confirm': '入场确认按钮', 'game_open': '左下仪器按钮',
                  'average_select': AVERAGE_INSTRUMENT, 'average_use': '九格均价仪器使用按钮',
                  'bid_open': '出价按钮', 'exit': '左上退出图标', 'bid_submit': '确认出价按钮', 'bid_confirm': '五百万出价确认按钮',
                  'exit_confirm': '放弃本局竞拍确认按钮', 'skip': '跳过动画按钮', 'result_exit': '结算退出按钮'}
        target = getattr(scene, targets[action])
        self.ocr_stage = {'open': 'auto', 'start': 'auto', 'game_open': 'game',
                          'average_select': 'instrument_list', 'average_use': 'instrument_list',
                          'bid_open': 'game', 'exit': 'game', 'bid_submit': 'bid_input',
                          'confirm': 'entry_confirm', 'bid_confirm': 'bid_confirm',
                          'exit_confirm': 'exit_confirm', 'skip': 'result', 'result_exit': 'result'}.get(action, 'instruments')
        if target is None and action in ('open', 'start'):
            scene = self.observe()
            if scene.page != 'home':
                raise ValueError('操作前未确认初始界面，暂停点击')
            target = getattr(scene, targets[action])
        if target is None:
            raise ValueError('没有唯一操作按钮位置，暂停点击')
        self.move_verified(*target.center, '移动到' + labels[action])
        fresh = self.observe()
        current = getattr(fresh, targets[action])
        expected = {'confirm': 'entry_confirm', 'open': 'home', 'start': 'home', 'game_open': 'game',
                    'average_select': 'instrument_list', 'average_use': 'instrument_list', 'bid_open': 'game',
                    'exit': 'game', 'bid_submit': 'bid_input', 'bid_confirm': 'bid_confirm',
                    'exit_confirm': 'exit_confirm', 'skip': 'result', 'result_exit': 'result'}.get(action, 'instruments')
        if fresh.page != expected or current is None or max(abs(a-b) for a, b in zip(current.center, target.center)) > 16:
            raise ValueError('移动后仪器组界面或位置变化，重新识别后再点击')
        if action in ('use', 'average_use') and (not fresh.selected or fresh.target is None or fresh.use_label != scene.use_label):
            raise ValueError('未确认目标仪器仍可使用或底部按钮已变化，暂停使用')
        if action in ('bid_submit', 'bid_confirm') and fresh.bid_amount != BID_AMOUNT:
            raise ValueError('出价金额未确认等于 5,000,000，暂停提交')
        self.confirm_pointer(current.center)
        self.guard()
        self.mouse.click()

    def fill_bid(self):
        # Use the game's visible keypad, with a fresh amount check after each key.
        self.ocr_stage = 'bid_fill'
        for label, expected in (('clear', None), ('5', 5), ('00', 500), ('0000', BID_AMOUNT)):
            scene = self.observe()
            if scene.page != 'bid_input' or not scene.keys or label not in scene.keys:
                raise ValueError('出价数字键盘未确认，暂停输入')
            target = scene.keys[label]
            self.move_verified(*target.center, '移动到出价键 ' + label)
            fresh = self.observe()
            current = fresh.keys.get(label) if fresh.keys else None
            if fresh.page != 'bid_input' or current is None or max(abs(a-b) for a, b in zip(current.center, target.center)) > 16:
                raise ValueError('出价数字键位置变化，暂停输入')
            self.confirm_pointer(current.center)
            self.guard()
            self.mouse.click()
            self.mouse.wait(0.12)
            after = self.observe()
            self.guard()
            if after.page != 'bid_input' or (after.bid_amount not in (None, 0) if expected is None else after.bid_amount != expected):
                raise ValueError('出价数字输入反馈不符合预期，暂停提交并重新核对')

    def scroll_groups(self, scene):
        if scene.page not in ('instruments', 'instrument_list') or scene.listing is None:
            raise ValueError('未定位左侧仪器组列表，暂停滚动')
        self.ocr_stage = scene.page
        self.move_verified(*scene.listing.center, '移动到左侧仪器组列表')
        fresh = self.observe()
        if fresh.page != scene.page or fresh.listing is None or max(abs(a-b) for a, b in zip(fresh.listing.center, scene.listing.center)) > 16:
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
                         'auction_average': getattr(self, 'average', None),
                         'phase': '已暂停' if reason else phase,
                         'state': 'paused' if reason else ('stopped' if completed else 'running'),
                         'details': reason or phase, 'completed': self.completed, 'failures': 0})

    def run(self):
        self.average = None
        self.publish('确认即刻落槌初始界面')
        self.b.ocr_stage = 'home'
        self.check()
        if self.b.observe().page != 'home':
            raise Stopped('界面错误：请从即刻落槌初始界面开始')
        state = 'cursor'
        cursor_frames = dialog_frames = selected_frames = 0
        value_frames, last_value = 0, None
        previous_page = None
        edge = False
        while True:
            self.check()
            try:
                self.b.ocr_stage = state
                scene = self.b.observe()
                self.check()
                if scene.page != previous_page:
                    dialog_frames = 0
                    previous_page = scene.page
                if state in ('await_loading', 'loading'):
                    # Loading/unknown pages never authorize input. Only a stable
                    # positively identified game page advances to instrument use.
                    if scene.page == 'loading':
                        dialog_frames = 0
                        if state != 'loading':
                            self.message('已识别右下角加载标识，仅观察状态，不进行鼠标操作')
                        state = 'loading'
                        self.publish(f'加载中 {scene.progress}%' if scene.progress is not None else '加载中')
                    elif scene.page == 'game':
                        dialog_frames += 1
                        self.publish('确认竞拍界面')
                        if dialog_frames >= self.c['confirm_frames']:
                            self.b.click_checked(scene, 'game_open')
                            self.message('已确认竞拍界面并点击左下仪器，等待仪器列表')
                            state = 'game_opening'
                            dialog_frames = 0
                            edge = False
                            self.b.list_stable = 0
                    else:
                        dialog_frames = 0
                        self.publish('等待竞拍界面' if state == 'loading' else '等待匹配成功 / 加载画面')
                elif state == 'waiting_result':
                    self.publish('等待竞拍结果')
                    dialog_frames = dialog_frames + 1 if scene.page == 'result' else 0
                    if dialog_frames >= self.c['confirm_frames']:
                        if scene.skip is not None:
                            self.b.click_checked(scene, 'skip')
                            self.message('已识别竞拍结束并点击跳过动画，等待结算退出按钮')
                            state = 'result_skipped'
                        else:
                            self.b.click_checked(scene, 'result_exit')
                            self.message('结算画面无跳过动画按钮，已点击退出，等待返回初始界面')
                            state = 'returning_home'
                        dialog_frames = 0
                elif scene.page == 'unknown':
                    cursor_frames = dialog_frames = selected_frames = 0
                    value_frames, last_value = 0, None
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
                elif state == 'game_opening':
                    self.publish('等待仪器列表')
                    dialog_frames = dialog_frames + 1 if scene.page == 'instrument_list' else 0
                    if dialog_frames >= self.c['confirm_frames']:
                        state = 'game_search'
                elif state == 'game_search' and scene.page == 'instrument_list':
                    self.publish('寻找九格均价仪器')
                    if scene.target is not None:
                        self.b.click_checked(scene, 'average_select')
                        self.message('已发送九格均价仪器点击，等待使用按钮')
                        state = 'game_selected'
                    elif not edge:
                        edge = self.b.scroll_groups(scene) is False
                    else:
                        self.publish('等待仪器', '列表未变化，暂停滚轮并等待九格均价仪器；F8 停止')
                elif state == 'game_selected' and scene.page == 'instrument_list':
                    self.publish('确认九格均价仪器可用')
                    selected_frames = selected_frames + 1 if scene.target is not None and scene.selected and scene.use is not None else 0
                    if selected_frames >= self.c['confirm_frames']:
                        self.b.click_checked(scene, 'average_use')
                        self.message('已发送九格均价仪器使用点击，等待读取中央平均价值')
                        state = 'read_average'
                elif state == 'read_average' and scene.page == 'game':
                    self.publish('读取九格平均价值')
                    if scene.average is None:
                        value_frames, last_value = 0, None
                    else:
                        value_frames = value_frames + 1 if scene.average == last_value else 1
                        last_value = scene.average
                        if value_frames >= self.c['confirm_frames']:
                            self.average = scene.average
                            self.message(f'已连续确认九格藏品平均价值：{self.average:,}')
                            if self.average > BID_THRESHOLD:
                                self.b.click_checked(scene, 'bid_open')
                                self.message('均价超过 500,000，已点击右下出价，等待数字键盘')
                                state = 'bid_opening'
                            else:
                                self.b.click_checked(scene, 'exit')
                                self.message('均价未超过 500,000，已点击左上退出图标，等待退出画面')
                                state = 'exiting'
                            dialog_frames = 0
                elif state == 'bid_opening':
                    self.publish('等待出价键盘')
                    dialog_frames = dialog_frames + 1 if scene.page == 'bid_input' else 0
                    if dialog_frames >= self.c['confirm_frames']:
                        state = 'bid_fill'
                elif state == 'bid_fill' and scene.page == 'bid_input':
                    self.publish('输入出价 5,000,000')
                    self.b.fill_bid()
                    state = 'bid_verify'
                    value_frames = 0
                elif state == 'bid_verify' and scene.page == 'bid_input':
                    self.publish('核对出价 5,000,000')
                    value_frames = value_frames + 1 if scene.bid_amount == BID_AMOUNT else 0
                    if value_frames >= self.c['confirm_frames']:
                        self.b.click_checked(scene, 'bid_submit')
                        self.message('已核对 5,000,000 并点击确认出价，等待二次确认或竞拍画面')
                        state = 'bid_submitted'
                        dialog_frames = 0
                elif state == 'bid_submitted':
                    self.publish('等待出价确认')
                    if scene.page == 'bid_confirm':
                        dialog_frames = dialog_frames + 1 if scene.bid_amount == BID_AMOUNT else 0
                        if scene.bid_amount != BID_AMOUNT:
                            self.publish('核对出价', '提示金额不是 5,000,000，暂停确认；F8 停止')
                        elif dialog_frames >= self.c['confirm_frames']:
                            self.b.click_checked(scene, 'bid_confirm')
                            self.message('已确认 5,000,000 出价，等待竞拍结果，不重复出价')
                            state = 'waiting_result'
                    elif scene.page == 'game':
                        dialog_frames += 1
                        if dialog_frames >= self.c['confirm_frames']:
                            self.message('确认出价后已回到竞拍画面，等待竞拍结果，不重复出价')
                            state = 'waiting_result'
                    else:
                        dialog_frames = 0
                elif state == 'exiting':
                    self.publish('等待放弃竞拍确认')
                    dialog_frames = dialog_frames + 1 if scene.page == 'exit_confirm' else 0
                    if dialog_frames >= self.c['confirm_frames']:
                        self.b.click_checked(scene, 'exit_confirm')
                        self.message('已确认放弃本局竞拍，等待加载并返回初始界面')
                        state = 'returning_home'
                        dialog_frames = 0
                    elif scene.page == 'home':
                        state = 'returning_home'
                        dialog_frames = 0
                elif state == 'result_skipped':
                    self.publish('等待结算退出按钮')
                    dialog_frames = dialog_frames + 1 if scene.page == 'result' else 0
                    if dialog_frames >= self.c['confirm_frames']:
                        self.b.click_checked(scene, 'result_exit')
                        self.message('已点击结算退出，等待加载并返回初始界面')
                        state = 'returning_home'
                        dialog_frames = 0
                elif state == 'returning_home':
                    if scene.page == 'loading':
                        self.publish(f'返回加载中 {scene.progress}%' if scene.progress is not None else '返回加载中')
                    else:
                        self.publish('等待返回初始界面')
                    dialog_frames = dialog_frames + 1 if scene.page == 'home' else 0
                    if dialog_frames >= self.c['confirm_frames']:
                        self.completed += 1
                        self.message(f'已确认返回初始界面，本次完成 {self.completed} 局，开始下一局')
                        self.average = None
                        state = 'cursor'
                        cursor_frames = dialog_frames = selected_frames = value_frames = 0
                        last_value = None
                        edge = False
                        self.b.list_stable = 0
                        self.publish('开始下一局')
                else:
                    cursor_frames = dialog_frames = selected_frames = 0
                    value_frames, last_value = 0, None
                    self.publish('等待识别', '界面切换未完成，暂停操作等待恢复；F8 停止')
            except Stopped:
                raise
            except Exception as error:
                cursor_frames = dialog_frames = selected_frames = 0
                value_frames, last_value = 0, None
                self.message(f'即刻落槌操作暂停：{error}；F8 停止')
                self.publish('等待恢复', str(error))
            self.wait(self.c['scan_interval'])
