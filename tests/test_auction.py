import threading
import unittest
from types import SimpleNamespace

import cv2
import numpy as np

from automation import Stopped
from nte_auction import AuctionBackend, AuctionController, AuctionReader, AuctionScene, Box, USE_LABELS


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

    def observe(self):
        if self.page == 'home':
            return AuctionScene('home', group=self.point, start=self.point)
        if self.page == 'entry_confirm':
            return AuctionScene('entry_confirm', confirm=self.point)
        if self.page == 'loading':
            self.loading_reads += 1
            if self.loading_reads <= 3:
                return AuctionScene('loading', progress=100)
            return AuctionScene('unknown')
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
                self.assertEqual(backend.actions, ['open', 'scroll', 'select', 'use', 'start', 'confirm'])
                self.assertEqual((reports[-1]['phase'], reports[-1]['state']), ('等待后续流程', 'stopped'))
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
        frames = iter([AuctionScene('loading', progress=90), AuctionScene('unknown'),
                       AuctionScene('loading', progress=100), AuctionScene('unknown'), AuctionScene('unknown')])
        backend.observe = lambda: next(frames) if backend.page == 'loading' else original()
        controller = self.controller(backend)
        controller.run()
        self.assertEqual(controller.completed, 1)

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


class ClickTests(unittest.TestCase):
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
