import threading
import unittest
from types import SimpleNamespace

import cv2
import numpy as np

from automation import Stopped
from nte_auction import AuctionBackend, AuctionController, AuctionReader, AuctionScene, Box, USE_LABELS, BID_AMOUNT


def word(text, x, y, w=160, h=30, confidence=0.99):
    return ([[x, y], [x+w, y], [x+w, y+h], [x, y+h]], text, confidence)


class ReaderTests(unittest.TestCase):
    def setUp(self):
        self.reader = AuctionReader(SimpleNamespace(cv=cv2))
        self.frame = np.zeros((1439, 2559, 3), np.uint8)

    def dialog(self, label='使用', target=True):
        rows = [word('仪器组合', 745, 220, h=40), word('内含下列仪器', 1170, 320),
                word('初级泛用仪器组', 745, 370), word(label, 1260, 1020)]
        if target:
            rows.append(word('至尊仪器组', 745, 800))
        return rows

    def game(self, value='3,626'):
        return [word('仪器', 490, 1320, w=75), word('出价', 2310, 1320, w=75),
                word('竞拍第1回合', 1140, 240, w=260), word('00:08', 1240, 80, w=90),
                word('ESC', 40, 105, w=45, h=20), word('九格均价仪器', 1040, 650, w=250),
                word('本局内九格藏品的平均价值为' + value + '。', 1040, 720, w=580),
                word('我的资产', 1920, 70), word('27,304,476', 2260, 70), word('当前估价：516,441', 2000, 200)]

    def game_list(self):
        return [word('仪器列表', 865, 150, h=40), word('至尊鉴定仪器', 1030, 310),
                word('九格均价仪器', 1030, 990, w=250), word('使用', 1240, 1200, w=90)]

    def keypad(self, amount=None):
        rows = self.game() + [word('请输入你愿意出的价格', 1600, 840, w=300),
                             word('确认出价', 1650, 1280, w=200), word('清空', 1250, 1280, w=100, h=40),
                             word('推荐出价参考：800,000', 1600, 885, w=300),
                             word('可输入范围0~27,304,476', 1560, 1040, w=390)]
        for digit in range(1, 10):
            rows.append(word(str(digit), 580 + ((digit-1) % 3) * 220, 770 + ((digit-1) // 3) * 170, w=60, h=40))
        for i, label in enumerate(('0', '00', '0000')):
            rows.append(word(label, 580 + i * 220, 1280, w=60, h=40))
        if amount is not None:
            rows.append(word(str(amount), 1620, 1010, w=240, h=40))
        return rows

    def test_game_requires_round_instrument_and_bid_anchors(self):
        scene = self.reader.from_rows(self.game(), self.frame)
        self.assertEqual((scene.page, scene.round_number, scene.countdown, scene.average), ('game', 1, 8, 3626))
        self.assertIsNotNone(scene.exit)
        self.assertEqual(self.reader.from_rows(self.game()[1:], self.frame).page, 'unknown')

    def test_average_does_not_use_assets_estimate_or_malformed_numbers(self):
        for value in ('350,001', '350000', '0', '123,456,789'):
            self.assertEqual(self.reader.from_rows(self.game(value), self.frame).average, int(value.replace(',', '')))
        for value in ('', '-3626', '3,62', '3,626.5', 'O,626'):
            with self.subTest(value=value):
                self.assertIsNone(self.reader.from_rows(self.game(value), self.frame).average)
        self.assertIsNone(self.reader.from_rows(self.game()[:-4], self.frame).average)

    def test_average_split_ocr_value_is_joined_on_the_same_line_only(self):
        rows = self.game()[:6] + [word('本局内九格藏品的平均价值为', 1040, 720, w=390), word('3,626。', 1440, 720, w=120)]
        self.assertEqual(self.reader.from_rows(rows, self.frame).average, 3626)
        rows[-1] = word('3,626。', 1440, 805, w=120)
        self.assertIsNone(self.reader.from_rows(rows, self.frame).average)

    def test_in_game_instrument_list_is_distinct_from_preparation(self):
        cv2.rectangle(self.frame, (890, 965), (1650, 1125), (140, 60, 245), 5)
        scene = self.reader.from_rows(self.game_list(), self.frame)
        self.assertEqual(scene.page, 'instrument_list')
        self.assertTrue(scene.selected)
        self.assertEqual(scene.use_label, '使用')
        duplicate = self.game_list() + [word('九格均价仪器', 1030, 670, w=250)]
        self.assertIsNone(self.reader.from_rows(duplicate, self.frame).target)

    def test_keypad_geometry_and_current_amount_are_required(self):
        scene = self.reader.from_rows(self.keypad('5,000,000'), self.frame)
        self.assertEqual((scene.page, scene.bid_amount), ('bid_input', BID_AMOUNT))
        self.assertEqual(set(scene.keys), {'5', '00', '0000', 'clear'})
        self.assertIsNone(self.reader.from_rows(self.keypad(), self.frame).bid_amount)
        missing = [row for row in self.keypad() if row[1] != '0000']
        self.assertEqual(self.reader.from_rows(missing, self.frame).page, 'unknown')
        needed = [row for row in self.keypad('5,000,000') if row[1] not in tuple('123467890')]
        self.assertEqual(self.reader.from_rows(needed, self.frame).bid_amount, BID_AMOUNT)

    def test_bid_confirmation_reads_actual_amount_separately_from_entry(self):
        rows = [word('提示', 1150, 300), word('检测到当前出价5,000,000疑似异常过高，是否确认出价？', 730, 520, w=1150),
                word('取消', 900, 750), word('确认', 1450, 750)]
        scene = self.reader.from_rows(rows, self.frame)
        self.assertEqual((scene.page, scene.bid_amount), ('bid_confirm', BID_AMOUNT))
        rows[1] = word('检测到当前出价6,666,666疑似异常过高，是否确认出价？', 730, 520, w=1150)
        self.assertEqual(self.reader.from_rows(rows, self.frame).bid_amount, 6666666)

    def test_unknown_dialog_over_game_does_not_allow_underlying_buttons(self):
        rows = self.game() + [word('提示', 1150, 300), word('确认', 1450, 750), word('取消', 900, 750)]
        self.assertEqual(self.reader.from_rows(rows, self.frame).page, 'unknown')

    def test_home_requires_both_auction_title_and_start_button(self):
        rows = [word('即刻落槌', 150, 60), word('至尊仪器组', 1680, 1050), word('开始匹配', 1950, 1320)]
        scene = self.reader.from_rows(rows, self.frame)
        self.assertEqual(scene.page, 'home')
        self.assertEqual(scene.group.center, (1760, 1065))
        self.assertEqual(self.reader.from_rows(rows[1:], self.frame).page, 'unknown')
        rows[-1] = word('开始拍卖', 1950, 1320)
        self.assertEqual(self.reader.from_rows(rows, self.frame).page, 'home')

    def test_list_bounds_stay_left_of_instrument_details(self):
        scene = self.reader.from_rows(self.dialog(), self.frame)
        self.assertEqual(scene.page, 'instruments')
        self.assertLess(scene.listing.center[0], 1170)
        self.assertTrue(scene.listing.contains(scene.target.center))

    def test_right_column_supreme_description_is_not_a_target(self):
        rows = self.dialog(target=False) + [word('至尊仪器组', 1250, 500)]
        scene = self.reader.from_rows(rows, self.frame)
        self.assertIsNone(scene.target)

    def test_all_footer_labels_use_one_operation(self):
        for label in USE_LABELS:
            with self.subTest(label=label):
                scene = self.reader.from_rows(self.dialog(label), self.frame)
                self.assertEqual(scene.use_label, label)
                self.assertIsNotNone(scene.use)

    def test_used_tags_and_ambiguous_buttons_do_not_authorize_use(self):
        rows = self.dialog('已使用')
        self.assertIsNone(self.reader.from_rows(rows, self.frame).use)
        rows = self.dialog() + [word('购买并使用', 1290, 1090)]
        self.assertIsNone(self.reader.from_rows(rows, self.frame).use)

    def test_duplicate_or_low_confidence_target_is_not_clicked(self):
        rows = self.dialog() + [word('至尊仪器组', 745, 600)]
        self.assertIsNone(self.reader.from_rows(rows, self.frame).target)
        rows = self.dialog(target=False) + [word('至尊仪器组', 745, 800, confidence=0.4)]
        self.assertIsNone(self.reader.from_rows(rows, self.frame).target)

    def test_selection_requires_pink_border_enclosing_the_target_card(self):
        self.assertFalse(self.reader.from_rows(self.dialog(), self.frame).selected)
        cv2.rectangle(self.frame, (720, 780), (1060, 957), (140, 60, 245), 5)
        self.assertTrue(self.reader.from_rows(self.dialog(), self.frame).selected)
        self.frame[:] = 0
        cv2.rectangle(self.frame, (720, 340), (1060, 517), (140, 60, 245), 5)
        self.assertFalse(self.reader.from_rows(self.dialog(), self.frame).selected)

    def test_merged_target_and_remaining_count_still_confirm_selection(self):
        rows = self.dialog(target=False) + [word('至尊仪器组 剩余：1', 740, 800, w=315)]
        cv2.rectangle(self.frame, (720, 780), (1060, 957), (140, 60, 245), 5)
        self.assertTrue(self.reader.from_rows(rows, self.frame).selected)

    def test_confirm_is_specific_to_matching_entry_fee_dialog(self):
        rows = [word('提示', 1150, 300), word('匹配成功后将扣除入场费20,000，是否继续？', 750, 520, w=950),
                word('取消', 900, 750), word('确认', 1450, 750)]
        self.assertEqual(self.reader.from_rows(rows, self.frame).page, 'entry_confirm')
        rows[1] = word('是否删除藏品？', 750, 520)
        self.assertEqual(self.reader.from_rows(rows, self.frame).page, 'unknown')

    def test_loading_requires_bottom_right_percent_and_gray_graphic(self):
        rows = [word('100%', 2380, 1340, w=120, h=40)]
        self.assertEqual(self.reader.from_rows(rows, self.frame).page, 'unknown')
        cv2.ellipse(self.frame, (2225, 1350), (105, 40), 0, 0, 360, (125, 125, 125), -1)
        scene = self.reader.from_rows(rows, self.frame)
        self.assertEqual((scene.page, scene.progress), ('loading', 100))
        rows[0] = word('37%', 2380, 1340, w=120, h=40)
        self.assertEqual(self.reader.from_rows(rows, self.frame).progress, 37)
        rows[0] = word('101%', 2380, 1340, w=120, h=40)
        self.assertEqual(self.reader.from_rows(rows, self.frame).page, 'unknown')

    def test_other_percentages_and_bright_background_are_not_loading(self):
        cv2.ellipse(self.frame, (2225, 1350), (105, 40), 0, 0, 360, (125, 125, 125), -1)
        self.assertEqual(self.reader.from_rows([word('100%', 2380, 700, h=40)], self.frame).page, 'unknown')
        self.frame[:] = 180
        self.assertEqual(self.reader.from_rows([word('100%', 2380, 1340, h=40)], self.frame).page, 'unknown')


class FakeAuction:
    def __init__(self, label='使用'):
        self.actions = []
        self.page = 'home'
        self.target = False
        self.selected = False
        self.label = label
        self.point = Box(750, 800, 160, 30)
        self.loading_reads = 0
        self.average = 3626
        self.average_used = False
        self.bid_amount = None
        self.confirm_amount = BID_AMOUNT

    def observe(self):
        if self.page == 'home':
            return AuctionScene('home', group=self.point, start=self.point)
        if self.page == 'entry_confirm':
            return AuctionScene('entry_confirm', confirm=self.point)
        if self.page == 'loading':
            self.loading_reads += 1
            if self.loading_reads <= 3:
                return AuctionScene('loading', progress=100)
            return AuctionScene('game', instrument=self.point, exit=self.point, bid=self.point,
                                average=self.average if self.average_used else None)
        if self.page == 'game':
            return AuctionScene('game', instrument=self.point, exit=self.point, bid=self.point,
                                average=self.average if self.average_used else None)
        if self.page == 'instrument_list':
            return AuctionScene('instrument_list', target=self.point, selected=True, use=self.point, use_label='使用')
        if self.page == 'bid_input':
            return AuctionScene('bid_input', bid_amount=self.bid_amount, bid_submit=self.point)
        if self.page == 'bid_confirm':
            return AuctionScene('bid_confirm', bid_amount=self.confirm_amount, confirm=self.point)
        if self.page == 'unknown':
            return AuctionScene('unknown')
        return AuctionScene('instruments', listing=Box(720, 300, 350, 680), target=self.point if self.target else None,
                            selected=self.selected, use=self.point if self.label else None, use_label=self.label)

    def find_cursor(self):
        return True

    def click_checked(self, scene, action='select'):
        self.actions.append(action)
        if action == 'open':
            self.page = 'instruments'
        elif action == 'select':
            self.selected = True
        elif action == 'use':
            self.page = 'home'
        elif action == 'start':
            self.page = 'entry_confirm'
        elif action == 'confirm':
            self.page = 'loading'
        elif action == 'game_open':
            self.page = 'instrument_list'
        elif action == 'average_use':
            self.average_used = True
            self.page = 'game'
        elif action == 'exit':
            self.page = 'home'
        elif action == 'bid_open':
            self.page = 'bid_input'
        elif action == 'bid_submit':
            self.page = 'bid_confirm'
        elif action == 'bid_confirm':
            self.page = 'game'

    def fill_bid(self):
        self.actions.append('fill_bid')
        self.bid_amount = BID_AMOUNT

    def scroll_groups(self, scene):
        self.actions.append('scroll')
        self.target = True
        return True


class FlowTests(unittest.TestCase):
    def controller(self, backend):
        now = [0.0]
        stop = threading.Event()
        def sleep(seconds):
            now[0] += seconds
            if now[0] > 12:
                stop.set()
        return AuctionController({'scan_interval': 0.05, 'confirm_frames': 2}, backend, stop,
                                 clock=lambda: now[0], sleep=sleep, log=lambda _: None)

    def test_three_footer_variants_return_then_start_and_confirm_once(self):
        for label in USE_LABELS:
            with self.subTest(label=label):
                backend = FakeAuction(label)
                controller = self.controller(backend)
                reports = []
                controller.report = reports.append
                controller.run()
                self.assertEqual(backend.actions, ['open', 'scroll', 'select', 'use', 'start', 'confirm', 'game_open', 'average_select', 'average_use', 'exit'])
                self.assertEqual((reports[-1]['phase'], reports[-1]['state']), ('已退出本局', 'stopped'))
                self.assertEqual(reports[-1]['auction_average'], 3626)
                self.assertEqual(controller.completed, 1)

    def test_wrong_initial_screen_never_sends_input(self):
        backend = FakeAuction()
        backend.page = 'instruments'
        with self.assertRaisesRegex(Stopped, '界面错误'):
            self.controller(backend).run()
        self.assertEqual(backend.actions, [])

    def test_missing_cursor_never_opens_groups(self):
        backend = FakeAuction()
        backend.find_cursor = lambda: False
        with self.assertRaisesRegex(Stopped, 'F8'):
            self.controller(backend).run()
        self.assertEqual(backend.actions, [])

    def test_target_already_visible_never_scrolls(self):
        backend = FakeAuction()
        backend.target = True
        self.controller(backend).run()
        self.assertNotIn('scroll', backend.actions)

    def test_failed_selection_does_not_click_purchase(self):
        backend = FakeAuction()
        original = backend.click_checked
        def click(scene, action='select'):
            original(scene, action)
            if action == 'select':
                backend.selected = False
        backend.click_checked = click
        with self.assertRaisesRegex(Stopped, 'F8'):
            self.controller(backend).run()
        self.assertEqual(backend.actions, ['open', 'scroll', 'select'])

    def test_use_without_return_does_not_repeat_purchase_or_start(self):
        backend = FakeAuction()
        original = backend.click_checked
        def click(scene, action='select'):
            original(scene, action)
            if action == 'use':
                backend.page = 'instruments'
        backend.click_checked = click
        with self.assertRaisesRegex(Stopped, 'F8'):
            self.controller(backend).run()
        self.assertEqual(backend.actions, ['open', 'scroll', 'select', 'use'])

    def test_cancel_after_use_prevents_start_and_confirmation(self):
        backend = FakeAuction()
        controller = self.controller(backend)
        original = backend.click_checked
        def click(scene, action='select'):
            original(scene, action)
            if action == 'use':
                controller.stop.set()
        backend.click_checked = click
        with self.assertRaisesRegex(Stopped, 'F8'):
            controller.run()
        self.assertEqual(backend.actions, ['open', 'scroll', 'select', 'use'])

    def test_missing_entry_prompt_prevents_confirmation(self):
        backend = FakeAuction()
        original = backend.click_checked
        def click(scene, action='select'):
            original(scene, action)
            if action == 'start':
                backend.page = 'unknown'
        backend.click_checked = click
        with self.assertRaisesRegex(Stopped, 'F8'):
            self.controller(backend).run()
        self.assertNotIn('confirm', backend.actions)

    def test_loading_at_100_percent_keeps_waiting_without_any_input(self):
        backend = FakeAuction()
        original = backend.observe
        backend.observe = lambda: AuctionScene('loading', progress=100) if backend.page == 'loading' else original()
        controller = self.controller(backend)
        reports = []
        controller.report = reports.append
        with self.assertRaisesRegex(Stopped, 'F8'):
            controller.run()
        self.assertEqual(backend.actions, ['open', 'scroll', 'select', 'use', 'start', 'confirm'])
        self.assertEqual(reports[-1]['phase'], '加载中 100%')
        self.assertEqual(controller.completed, 0)

    def test_after_confirmation_unknown_scene_waits_for_loading_without_input(self):
        backend = FakeAuction()
        original = backend.observe
        backend.observe = lambda: AuctionScene('unknown') if backend.page == 'loading' else original()
        controller = self.controller(backend)
        reports = []
        controller.report = reports.append
        with self.assertRaisesRegex(Stopped, 'F8'):
            controller.run()
        self.assertEqual(backend.actions, ['open', 'scroll', 'select', 'use', 'start', 'confirm'])
        self.assertEqual(reports[-1]['phase'], '等待匹配成功 / 加载画面')
        self.assertEqual(controller.completed, 0)

    def test_one_missing_loading_frame_does_not_finish_observation(self):
        backend = FakeAuction()
        original = backend.observe
        game = AuctionScene('game', instrument=backend.point, exit=backend.point, bid=backend.point)
        frames = iter([AuctionScene('loading', progress=90), AuctionScene('unknown'),
                       AuctionScene('loading', progress=100), game, game])
        backend.observe = lambda: next(frames) if backend.page == 'loading' else original()
        controller = self.controller(backend)
        controller.run()
        self.assertEqual(controller.completed, 1)

    def test_loading_disappearance_without_game_anchors_never_opens_instruments(self):
        backend = FakeAuction()
        original = backend.observe
        reads = [0]
        def observe():
            if backend.page == 'loading':
                reads[0] += 1
                return AuctionScene('loading', progress=100) if reads[0] == 1 else AuctionScene('unknown')
            return original()
        backend.observe = observe
        with self.assertRaisesRegex(Stopped, 'F8'):
            self.controller(backend).run()
        self.assertNotIn('game_open', backend.actions)

    def test_stationary_list_pauses_after_two_batches(self):
        backend = FakeAuction()
        batches = []
        def scroll(scene):
            batches.append(scene)
            return len(batches) < 2
        backend.scroll_groups = scroll
        with self.assertRaisesRegex(Stopped, 'F8'):
            self.controller(backend).run()
        self.assertEqual(len(batches), 2)
        self.assertEqual(backend.actions, ['open'])

    def test_strict_threshold_equal_or_lower_exits_without_bidding(self):
        for value in (0, 3626, 349999, 350000):
            with self.subTest(value=value):
                backend = FakeAuction()
                backend.average = value
                controller = self.controller(backend)
                controller.run()
                self.assertEqual(controller.average, value)
                self.assertEqual(backend.actions.count('exit'), 1)
                self.assertNotIn('bid_open', backend.actions)

    def test_above_threshold_bids_exactly_once_then_waits_until_cancel(self):
        backend = FakeAuction()
        backend.average = 350001
        controller = self.controller(backend)
        reports = []
        controller.report = reports.append
        with self.assertRaisesRegex(Stopped, 'F8'):
            controller.run()
        self.assertEqual(backend.actions[-4:], ['bid_open', 'fill_bid', 'bid_submit', 'bid_confirm'])
        self.assertEqual(backend.actions.count('bid_submit'), 1)
        self.assertEqual(backend.actions.count('bid_confirm'), 1)
        self.assertNotIn('exit', backend.actions)
        self.assertEqual((reports[-1]['phase'], reports[-1]['auction_average']), ('等待竞拍结果', 350001))

    def test_wrong_secondary_confirmation_amount_is_never_approved(self):
        backend = FakeAuction()
        backend.average = 500000
        backend.confirm_amount = 6666666
        with self.assertRaisesRegex(Stopped, 'F8'):
            self.controller(backend).run()
        self.assertIn('bid_submit', backend.actions)
        self.assertNotIn('bid_confirm', backend.actions)

    def test_no_warning_returns_to_game_without_repeating_bid(self):
        backend = FakeAuction()
        backend.average = 500000
        original = backend.click_checked
        def click(scene, action='select'):
            original(scene, action)
            if action == 'bid_submit':
                backend.page = 'game'
        backend.click_checked = click
        with self.assertRaisesRegex(Stopped, 'F8'):
            self.controller(backend).run()
        self.assertEqual(backend.actions.count('bid_submit'), 1)
        self.assertNotIn('bid_confirm', backend.actions)

    def test_wrong_keypad_amount_prevents_submit(self):
        backend = FakeAuction()
        backend.average = 500000
        def fill():
            backend.actions.append('fill_bid')
            backend.bid_amount = 50000000
        backend.fill_bid = fill
        with self.assertRaisesRegex(Stopped, 'F8'):
            self.controller(backend).run()
        self.assertNotIn('bid_submit', backend.actions)

    def test_unreadable_average_does_not_bid_exit_or_reuse_instrument(self):
        backend = FakeAuction()
        backend.average = None
        with self.assertRaisesRegex(Stopped, 'F8'):
            self.controller(backend).run()
        self.assertEqual(backend.actions.count('average_use'), 1)
        self.assertNotIn('bid_open', backend.actions)
        self.assertNotIn('exit', backend.actions)

    def test_fluctuating_average_never_authorizes_a_decision(self):
        backend = FakeAuction()
        original = backend.observe
        readings = [0]
        def observe():
            scene = original()
            if scene.page == 'game' and backend.average_used:
                readings[0] += 1
                scene.average = 100000 if readings[0] % 2 else 500000
            return scene
        backend.observe = observe
        with self.assertRaisesRegex(Stopped, 'F8'):
            self.controller(backend).run()
        self.assertNotIn('bid_open', backend.actions)
        self.assertNotIn('exit', backend.actions)

    def test_cancel_after_instrument_selection_prevents_use_and_bidding(self):
        backend = FakeAuction()
        controller = self.controller(backend)
        original = backend.click_checked
        def click(scene, action='select'):
            original(scene, action)
            if action == 'average_select':
                controller.stop.set()
        backend.click_checked = click
        with self.assertRaisesRegex(Stopped, 'F8'):
            controller.run()
        self.assertNotIn('average_use', backend.actions)
        self.assertNotIn('bid_open', backend.actions)


class ClickTests(unittest.TestCase):
    def test_warning_amount_change_after_moving_prevents_confirmation(self):
        backend = AuctionBackend.__new__(AuctionBackend)
        clicks = []
        box = Box(1450, 750, 150, 30)
        backend.move_verified = lambda *args: None
        backend.observe = lambda: AuctionScene('bid_confirm', confirm=box, bid_amount=6666666)
        backend.guard = lambda: None
        backend.mouse = SimpleNamespace(click=lambda: clicks.append('click'))
        with self.assertRaisesRegex(ValueError, '金额未确认'):
            backend.click_checked(AuctionScene('bid_confirm', confirm=box, bid_amount=BID_AMOUNT), 'bid_confirm')
        self.assertEqual(clicks, [])

    def keypad_backend(self, wrong_feedback=False, cancel_after_key=False):
        backend = AuctionBackend.__new__(AuctionBackend)
        labels = ('clear', '5', '00', '0000')
        keys = {label: Box(100 + i * 90, 600, 50, 30) for i, label in enumerate(labels)}
        state = {'amount': 888888, 'point': None, 'clicks': [], 'stopped': False}
        backend.point = lambda x, y: (x, y)
        backend.move_verified = lambda x, y, _: state.update(point=(x, y))
        backend.cursor_position = lambda: SimpleNamespace(point=state['point'])
        def guard():
            if state['stopped']:
                raise Stopped('F8')
        backend.guard = guard
        backend.observe = lambda: AuctionScene('bid_input', keys=keys, bid_amount=state['amount'])
        def click():
            label = next(label for label, box in keys.items() if box.center == state['point'])
            state['clicks'].append(label)
            state['amount'] = None if label == 'clear' else (6 if wrong_feedback else int(str(state['amount'] or '') + label))
            state['stopped'] = cancel_after_key
        backend.mouse = SimpleNamespace(click=click, wait=lambda _: None)
        return backend, state

    def test_virtual_keypad_clears_then_builds_verified_five_million(self):
        backend, state = self.keypad_backend()
        backend.fill_bid()
        self.assertEqual(state['clicks'], ['clear', '5', '00', '0000'])
        self.assertEqual(state['amount'], BID_AMOUNT)

    def test_wrong_key_feedback_stops_remaining_digits(self):
        backend, state = self.keypad_backend(wrong_feedback=True)
        with self.assertRaisesRegex(ValueError, '反馈不符合'):
            backend.fill_bid()
        self.assertEqual(state['clicks'], ['clear', '5'])

    def test_cancel_during_keypad_entry_stops_remaining_digits(self):
        backend, state = self.keypad_backend(cancel_after_key=True)
        with self.assertRaisesRegex(Stopped, 'F8'):
            backend.fill_bid()
        self.assertEqual(state['clicks'], ['clear'])

    def test_verified_cursor_and_fresh_scene_send_actual_click(self):
        backend = AuctionBackend.__new__(AuctionBackend)
        clicks = []
        backend.move_verified = lambda *args: None
        backend.guard = lambda: None
        backend.mouse = SimpleNamespace(click=lambda: clicks.append('click'))
        box = Box(1100, 950, 150, 30)
        scene = AuctionScene('home', start=box)
        backend.observe = lambda: scene
        backend.point = lambda x, y: (x, y)
        backend.cursor_position = lambda: SimpleNamespace(point=box.center)
        backend.click_checked(scene, 'start')
        self.assertEqual(clicks, ['click'])

    def test_pointer_moved_during_ocr_prevents_click(self):
        backend = AuctionBackend.__new__(AuctionBackend)
        clicks = []
        backend.move_verified = lambda *args: None
        backend.guard = lambda: None
        backend.mouse = SimpleNamespace(click=lambda: clicks.append('click'))
        box = Box(1100, 950, 150, 30)
        scene = AuctionScene('home', start=box)
        backend.observe = lambda: scene
        backend.point = lambda x, y: (x, y)
        backend.cursor_position = lambda: SimpleNamespace(point=(10, 10))
        with self.assertRaisesRegex(ValueError, '光标已离开'):
            backend.click_checked(scene, 'start')
        self.assertEqual(clicks, [])

    def test_changed_page_after_pointer_move_prevents_click(self):
        backend = AuctionBackend.__new__(AuctionBackend)
        clicks = []
        backend.move_verified = lambda *args: None
        backend.observe = lambda: AuctionScene('home')
        backend.guard = lambda: None
        backend.mouse = SimpleNamespace(click=lambda: clicks.append('click'))
        scene = AuctionScene('instruments', target=Box(700, 400, 150, 25))
        with self.assertRaisesRegex(ValueError, '界面或位置变化'):
            backend.click_checked(scene)
        self.assertEqual(clicks, [])

    def test_use_requires_fresh_selected_target_and_same_footer(self):
        backend = AuctionBackend.__new__(AuctionBackend)
        clicks = []
        backend.move_verified = lambda *args: None
        backend.guard = lambda: None
        backend.mouse = SimpleNamespace(click=lambda: clicks.append('click'))
        box = Box(1100, 950, 150, 30)
        scene = AuctionScene('instruments', target=box, selected=True, use=box, use_label='使用')
        backend.observe = lambda: AuctionScene('instruments', target=box, selected=False, use=box, use_label='使用')
        with self.assertRaisesRegex(ValueError, '未确认'):
            backend.click_checked(scene, 'use')
        self.assertEqual(clicks, [])


if __name__ == '__main__':
    unittest.main()
