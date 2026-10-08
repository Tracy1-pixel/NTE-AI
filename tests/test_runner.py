import threading
import unittest

from automation import Runner, Stopped, validate, parse_score


def config():
    return {
        'click_region': [10, 10, 10, 10],
        'goal': {'region': [100, 0, 50, 20]},
        'stamina': {'region': [100, 100, 50, 20]},
        'exit_steps': [{'x': 1, 'y': 1, 'delay': 0.1}],
        'enter_steps': [{'x': 2, 'y': 2, 'delay': 0.1}],
        'click_interval': 0.05, 'scan_interval': 0.1,
        'round_timeout': 2, 'transition_timeout': 1,
        'max_rounds': 3, 'max_minutes': 1, 'confirm_frames': 2,
    }


class FakeDesktop:
    def __init__(self, empty_after=2, stuck_banner=False, never_win=False):
        self.clicks = []
        self.round = 1
        self.hits = 0
        self.empty_after = empty_after
        self.stuck_banner = stuck_banner
        self.never_win = never_win
        self.keys = []

    def press(self, key):
        self.keys.append(key)

    def check_screen(self):
        pass

    def match(self, name):
        if name == 'stamina':
            return self.round > self.empty_after
        return self.hits >= 3 and not self.never_win

    def click(self, x, y):
        self.clicks.append((x, y))
        if (x, y) == (2, 2):
            self.round += 1
            if not self.stuck_banner:
                self.hits = 0
        elif (x, y) != (1, 1):
            self.hits += 1


class RunnerTests(unittest.TestCase):
    def make(self, backend, c=None):
        self.now = 0.0
        def sleep(dt):
            self.now += dt
        return Runner(c or config(), backend, threading.Event(), clock=lambda: self.now, sleep=sleep, log=lambda _: None)

    def test_repeated_rounds_stop_on_empty_stamina(self):
        desktop = FakeDesktop(empty_after=2)
        runner = self.make(desktop)
        with self.assertRaisesRegex(Stopped, '体力不足'):
            runner.run()
        self.assertEqual(desktop.clicks.count((1, 1)), 2)
        self.assertEqual(desktop.clicks.count((2, 2)), 2)
        # Detection is periodic; additional hits before the next scan are expected.
        self.assertGreaterEqual(sum(x >= 10 for x, y in desktop.clicks), 6)
        self.assertLessEqual(sum(x >= 10 for x, y in desktop.clicks), 12)

    def test_empty_stamina_prevents_all_clicks(self):
        desktop = FakeDesktop(empty_after=0)
        with self.assertRaisesRegex(Stopped, '体力不足'):
            self.make(desktop).run()
        self.assertEqual(desktop.clicks, [])

    def test_no_goal_times_out_without_reentering(self):
        desktop = FakeDesktop(never_win=True)
        with self.assertRaisesRegex(Stopped, '单轮超时'):
            self.make(desktop).run()
        self.assertNotIn((1, 1), desktop.clicks)
        self.assertNotIn((2, 2), desktop.clicks)

    def test_old_goal_banner_does_not_complete_next_round(self):
        desktop = FakeDesktop(empty_after=10, stuck_banner=True)
        with self.assertRaisesRegex(Stopped, '提示未消失'):
            self.make(desktop).run()
        self.assertEqual(desktop.clicks.count((1, 1)), 1)

    def test_emergency_stop_prevents_clicks(self):
        desktop = FakeDesktop()
        runner = self.make(desktop)
        runner.stop.set()
        with self.assertRaisesRegex(Stopped, '紧急停止'):
            runner.run()
        self.assertEqual(desktop.clicks, [])

    def test_round_limit_exits_without_starting_extra_round(self):
        desktop = FakeDesktop(empty_after=10)
        c = config()
        c['max_rounds'] = 1
        with self.assertRaisesRegex(Stopped, '轮数上限'):
            self.make(desktop, c).run()
        self.assertEqual(desktop.clicks.count((1, 1)), 1)
        self.assertNotIn((2, 2), desktop.clicks)

    def test_missing_stamina_detection_is_rejected(self):
        c = config()
        del c['stamina']
        with self.assertRaisesRegex(ValueError, 'stamina'):
            validate(c)

    def test_score_requires_numerator_and_correct_denominator(self):
        self.assertEqual(parse_score('1,901 / 1900'), 1901)
        self.assertEqual(parse_score('1899／1900'), 1899)
        self.assertEqual(parse_score('1900/1900'), 1900)
        self.assertEqual(parse_score('1900//1900'), 1900)
        self.assertIsNone(parse_score('1900'))
        self.assertIsNone(parse_score('1900/2000'))
        self.assertIsNone(parse_score('99999/1900'))

    def test_exit_sequence_sends_escape_before_menu_clicks(self):
        desktop = FakeDesktop(empty_after=10)
        c = config()
        c['max_rounds'] = 1
        c['exit_steps'].insert(0, {'key': 'esc', 'delay': 0.1})
        with self.assertRaisesRegex(Stopped, '轮数上限'):
            self.make(desktop, c).run()
        self.assertEqual(desktop.keys, ['esc'])
        self.assertEqual(desktop.clicks[-1], (1, 1))

    def test_unreadable_start_score_prevents_clicks(self):
        desktop = FakeDesktop()
        desktop.last_score = None
        with self.assertRaisesRegex(Stopped, '无法读取分数'):
            self.make(desktop).run()
        self.assertEqual(desktop.clicks, [])

    def test_unreadable_round_score_pauses_until_timeout(self):
        desktop = FakeDesktop()
        desktop.last_score = None
        with self.assertRaisesRegex(Stopped, '单轮超时'):
            self.make(desktop).play_round()
        self.assertEqual(desktop.clicks, [])


if __name__ == '__main__':
    unittest.main()
