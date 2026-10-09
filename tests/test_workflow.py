import threading
import unittest

from automation import Stopped
from workflow import Controller, Scene, fraction, integer, settings


class Game:
    def __init__(self, city=96, outcomes=(), cost=48, initial='home'):
        self.scene = Scene(initial, city=city)
        self.city, self.cost = city, cost
        self.outcomes = list(outcomes)
        self.current = 'success'
        self.actions = []
        self.hits = 0
        self.retry_delay = 0

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
        elif name == 'retry':
            self.new_attempt()
            self.retry_delay = 4  # The failure panel stays visible during loading.

    def select_level(self):
        self.actions.append('select_level')
        self.scene.selected = True
        return True


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

    def test_home_select_ready_goal_claim_and_repeat_until_zero(self):
        game = Game()
        controller, _ = self.make(game)
        with self.assertRaisesRegex(Stopped, '都市体力为 0'):
            controller.run()
        self.assertEqual(game.actions.count('claim'), 2)
        self.assertEqual(game.actions.count('scroll_bottom'), 2)
        self.assertEqual(game.actions.count('select_level'), 2)
        self.assertEqual(game.actions.count('start'), 2)
        self.assertEqual(game.actions.count('exit'), 2)
        self.assertNotIn('retry', game.actions)

    def test_zero_cost_stops_without_claiming(self):
        game = Game(cost=0)
        controller, _ = self.make(game)
        with self.assertRaisesRegex(Stopped, '消耗为 0'):
            controller.run()
        self.assertNotIn('claim', game.actions)

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
        self.assertEqual(game.actions.count('scroll_bottom'), 1)
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


if __name__ == '__main__':
    unittest.main()
