import threading
import unittest

from automation import Stopped
from nte_workflow import Controller, Scene, fraction, integer, settings
from nte_stars import StarAnchor


class Game:
    def __init__(self, city=96, outcomes=(), cost=48, initial='home'):
        self.scene = Scene(initial, city=city)
        self.city, self.cost = city, cost
        self.outcomes = list(outcomes)
        self.current = 'success'
        self.actions = []
        self.hits = 0
        self.retry_delay = 0
        self.level_visible = False

    def observe(self):
        if self.retry_delay:
            self.retry_delay -= 1
            if not self.retry_delay:
                self.scene = Scene('ready', score=0)
        return self.scene

    def new_attempt(self):
        self.current = self.outcomes.pop(0) if self.outcomes else 'success'
        self.hits = 0

    def action(self, name):
        self.actions.append(name)
        if name == 'start':
            self.new_attempt()
            self.scene = Scene('ready', score=0)
        elif name == 'hammer':
            self.hits += 1
            if self.current == 'failure':
                self.scene = Scene('failure')
            elif self.hits >= 3:
                self.scene = Scene('playing', score=1927)
            else:
                self.scene = Scene('playing', score=0)
        elif name == 'exit':
            self.scene = Scene('success', city=self.city, cost=self.cost)
        elif name == 'claim':
            self.city = max(0, self.city - self.cost)
            self.scene = Scene('home', city=self.city)
            self.level_visible = False
        elif name == 'retry':
            self.new_attempt()
            self.retry_delay = 4  # The failure panel stays visible during loading.
        elif name == 'scroll_step':
            self.level_visible = True
            return True

    def select_level(self):
        self.actions.append('select_level')
        if not self.level_visible:
            return False
        self.actions.append('click_level')
        self.scene.selected = True
        return True

    def find_cursor(self):
        self.actions.append('find_cursor')
        return True

    def find_star_anchor(self):
        self.actions.append('find_star_anchor')
        return StarAnchor(150, 500, 150, 40)

    def move_to_anchor(self, anchor):
        self.actions.append('move_to_anchor')


class WorkflowTests(unittest.TestCase):
    def make(self, game):
        now = [0.0]
        stop = threading.Event()
        self.logs = []
        def sleep(dt):
            now[0] += dt
            if now[0] > 60:
                stop.set()
        controller = Controller({'scan_interval': 0.1, 'click_interval': 0.03, 'confirm_frames': 2}, game, stop, clock=lambda: now[0], sleep=sleep, log=self.logs.append)
        return controller, stop

    def test_initial_mismatch_has_no_mouse_actions(self):
        game = Game(initial='playing')
        controller, _ = self.make(game)
        with self.assertRaisesRegex(Stopped, '界面错误'):
            controller.run()
        self.assertEqual(game.actions, [])

    def test_no_cursor_pauses_before_any_movement_scroll_or_click(self):
        class MissingCursor(Game):
            def find_cursor(self):
                self.actions.append('find_cursor')
                return False
        game = MissingCursor()
        controller, _ = self.make(game)
        reports = []
        controller.report = reports.append
        with self.assertRaisesRegex(Stopped, 'F8'):
            controller.run()
        self.assertTrue(game.actions)
        self.assertEqual(set(game.actions), {'find_cursor'})
        self.assertTrue(any(row['phase'] == '识别游戏光标' and row['state'] == 'paused' for row in reports))

    def test_cursor_confirmation_precedes_scroll_selection_and_start(self):
        class LateCursor(Game):
            reads = iter([False, True, False, True, True])
            def find_cursor(self):
                found = next(self.reads, True)
                self.actions.append('cursor_yes' if found else 'cursor_no')
                return found
        game = LateCursor(city=48)
        controller, _ = self.make(game)
        with self.assertRaisesRegex(Stopped, '都市体力为 0'):
            controller.run()
        self.assertEqual(game.actions[:5], ['cursor_no', 'cursor_yes', 'cursor_no', 'cursor_yes', 'cursor_yes'])
        self.assertEqual(game.actions[5:12], ['find_star_anchor', 'move_to_anchor', 'select_level',
                                            'scroll_step', 'select_level', 'click_level', 'start'])

    def test_failed_mouse_verification_never_reports_movement_or_click_success(self):
        class StalledMouse(Game):
            def move_to_anchor(self, anchor):
                self.actions.append('move_failed')
                raise ValueError('鼠标移动未确认：实际坐标未改变')
        game = StalledMouse()
        controller, _ = self.make(game)
        with self.assertRaisesRegex(Stopped, 'F8'):
            controller.run()
        self.assertIn('move_failed', game.actions)
        self.assertNotIn('click_level', game.actions)
        self.assertNotIn('scroll_step', game.actions)
        self.assertNotIn('start', game.actions)
        self.assertTrue(any('鼠标移动未确认' in line for line in self.logs))
        self.assertFalse(any('光标移动已核验' in line for line in self.logs))

    def test_home_select_ready_goal_claim_and_repeat_until_zero(self):
        game = Game()
        controller, _ = self.make(game)
        with self.assertRaisesRegex(Stopped, '都市体力为 0'):
            controller.run()
        self.assertEqual(game.actions.count('claim'), 2)
        self.assertEqual(game.actions.count('scroll_step'), 2)
        self.assertEqual(game.actions.count('click_level'), 2)
        self.assertEqual(game.actions.count('start'), 2)
        self.assertEqual(game.actions.count('exit'), 2)
        self.assertNotIn('retry', game.actions)

    def test_zero_cost_stops_without_claiming(self):
        game = Game(cost=0)
        controller, _ = self.make(game)
        with self.assertRaisesRegex(Stopped, '消耗为 0'):
            controller.run()
        self.assertNotIn('claim', game.actions)

    def test_each_reward_reads_changed_cost_until_zero(self):
        class VariableCostGame(Game):
            def __init__(self):
                super().__init__(city=500)
                self.costs = iter([48, 24, 7, 0])
                self.claimed_costs = []

            def action(self, name):
                if name == 'exit':
                    self.cost = next(self.costs)
                elif name == 'claim':
                    self.claimed_costs.append(self.scene.cost)
                super().action(name)

        game = VariableCostGame()
        controller, _ = self.make(game)
        with self.assertRaisesRegex(Stopped, '领取按钮下方消耗为 0'):
            controller.run()
        self.assertEqual(game.claimed_costs, [48, 24, 7])
        self.assertEqual(game.city, 421)
        self.assertEqual(game.actions.count('start'), 4)
        self.assertEqual(game.actions.count('claim'), 3)
        self.assertEqual(controller.completed, 3)

    def test_live_status_counts_final_round_before_zero_stamina_stop(self):
        controller, _ = self.make(Game())
        reports = []
        controller.report = reports.append
        with self.assertRaisesRegex(Stopped, '都市体力为 0'):
            controller.run()
        self.assertEqual(reports[-1]['completed'], 2)
        self.assertTrue(any(row['score'] == 1927 for row in reports))
        self.assertTrue(any(row['phase'] == '领取奖励' for row in reports))

    def test_live_status_reports_third_failure_before_stopping(self):
        controller, _ = self.make(Game(outcomes=['failure'] * 3))
        reports = []
        controller.report = reports.append
        with self.assertRaisesRegex(Stopped, '连续三次'):
            controller.run()
        self.assertEqual(reports[-1]['failures'], 3)

    def test_live_status_pauses_on_unknown_and_resumes_on_valid_scene(self):
        controller, _ = self.make(Game())
        reports = []
        controller.report = reports.append
        controller.publish('playing', Scene('unknown'))
        controller.publish('playing', Scene('playing', score=1200))
        self.assertEqual([row['state'] for row in reports], ['paused', 'running'])
        self.assertEqual(reports[-1]['score'], 1200)

    def test_zero_city_at_start_does_not_scroll_or_click(self):
        game = Game(city=0)
        controller, _ = self.make(game)
        with self.assertRaisesRegex(Stopped, '都市体力为 0'):
            controller.run()
        self.assertEqual(game.actions, [])

    def test_three_failures_retry_twice_without_returning_home(self):
        game = Game(outcomes=['failure'] * 3)
        controller, _ = self.make(game)
        with self.assertRaisesRegex(Stopped, '连续三次'):
            controller.run()
        self.assertEqual(game.actions.count('retry'), 2)
        self.assertEqual(game.actions.count('start'), 1)
        self.assertEqual(game.actions.count('scroll_step'), 1)
        self.assertNotIn('claim', game.actions)

    def test_successful_claim_resets_failure_streak(self):
        game = Game(city=200, outcomes=['failure', 'success', 'failure', 'failure', 'failure'])
        controller, _ = self.make(game)
        with self.assertRaisesRegex(Stopped, '连续三次'):
            controller.run()
        self.assertEqual(game.actions.count('claim'), 1)
        self.assertEqual(game.actions.count('retry'), 3)

    def test_f8_event_prevents_all_actions(self):
        game = Game()
        controller, stop = self.make(game)
        stop.set()
        with self.assertRaisesRegex(Stopped, 'F8'):
            controller.run()
        self.assertEqual(game.actions, [])

    def test_unknown_screen_pauses_and_does_not_terminate(self):
        class UnknownAfterHammer(Game):
            seen_unknown = False
            unsafe_clicks = 0
            def observe(self):
                scene = super().observe()
                if scene.page == 'unknown':
                    self.seen_unknown = True
                return scene
            def action(self, name):
                if name == 'hammer' and self.seen_unknown:
                    self.unsafe_clicks += 1
                super().action(name)
                if name == 'hammer':
                    self.scene = Scene('unknown')
        game = UnknownAfterHammer()
        controller, _ = self.make(game)
        with self.assertRaisesRegex(Stopped, 'F8'):
            controller.run()
        self.assertEqual(game.unsafe_clicks, 0)
        self.assertTrue(any('界面错误' in line for line in self.logs))

    def test_old_round_and_time_limits_do_not_apply(self):
        self.assertNotIn('max_rounds', settings({'max_rounds': 1, 'max_minutes': 1}))
        self.assertNotIn('max_minutes', settings({'max_rounds': 1, 'max_minutes': 1}))

    def test_numeric_reads_require_complete_values(self):
        self.assertEqual(fraction('0/700'), 0)
        self.assertEqual(fraction('652 / 700'), 652)
        self.assertIsNone(fraction('0'))
        self.assertIsNone(fraction('652/0'))
        self.assertEqual(integer('48'), 48)
        self.assertEqual(integer('0'), 0)
        self.assertIsNone(integer('领取48'))

    def test_missing_triplet_waits_without_moving_or_scrolling(self):
        class NoAnchor(Game):
            def find_star_anchor(self):
                self.actions.append('find_star_anchor')
                return None
        game = NoAnchor()
        controller, _ = self.make(game)
        reports = []
        controller.report = reports.append
        with self.assertRaisesRegex(Stopped, 'F8'):
            controller.run()
        self.assertEqual(set(game.actions), {'find_cursor', 'find_star_anchor'})
        self.assertTrue(any(row['phase'] == '识别三星锚点' and row['state'] == 'paused' for row in reports))

    def test_visible_target_is_clicked_without_unnecessary_scrolling(self):
        game = Game(city=48)
        game.level_visible = True
        controller, _ = self.make(game)
        with self.assertRaisesRegex(Stopped, '都市体力为 0'):
            controller.run()
        self.assertNotIn('scroll_step', game.actions)
        self.assertEqual(game.actions.count('click_level'), 1)
        self.assertLess(game.actions.index('move_to_anchor'), game.actions.index('click_level'))

    def test_unreadable_target_at_bottom_pauses_wheel_but_keeps_ocr(self):
        class BottomWithoutTarget(Game):
            def action(self, name):
                if name == 'scroll_step':
                    self.actions.append(name)
                    return False
                return super().action(name)
        game = BottomWithoutTarget()
        controller, _ = self.make(game)
        with self.assertRaisesRegex(Stopped, 'F8'):
            controller.run()
        self.assertEqual(game.actions.count('scroll_step'), 1)
        self.assertGreater(game.actions.count('select_level'), 1)
        self.assertNotIn('start', game.actions)


if __name__ == '__main__':
    unittest.main()
