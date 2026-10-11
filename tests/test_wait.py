import threading
import unittest
from types import SimpleNamespace

from automation import Runner, Stopped
from nte_workflow import Controller
from test_runner import config


class WaitTests(unittest.TestCase):
    def runners(self, clock, sleep, stop):
        desktop = SimpleNamespace(check_screen=lambda: None)
        return (Controller({}, desktop, stop, clock=clock, sleep=sleep),
                Runner(config(), desktop, stop, clock=clock, sleep=sleep))

    def test_deadline_passed_between_clock_reads_never_sleeps_negative(self):
        for kind in (Controller, Runner):
            with self.subTest(kind=kind.__name__):
                now = [0.0]
                def clock():
                    now[0] += 0.04
                    return now[0]
                sleeps = []
                def sleep(seconds):
                    if seconds < 0:
                        raise ValueError('sleep length must be non-negative')
                    sleeps.append(seconds)
                runner = next(item for item in self.runners(clock, sleep, threading.Event()) if type(item) is kind)
                runner.wait(0.05)
                self.assertTrue(all(0 < seconds <= 0.05 for seconds in sleeps))

    def test_regular_wait_finishes_in_small_cancellable_steps(self):
        for kind in (Controller, Runner):
            with self.subTest(kind=kind.__name__):
                now = [0.0]
                sleeps = []
                def sleep(seconds):
                    sleeps.append(seconds)
                    now[0] += seconds
                runner = next(item for item in self.runners(lambda: now[0], sleep, threading.Event()) if type(item) is kind)
                runner.wait(0.13)
                self.assertAlmostEqual(now[0], 0.13)
                self.assertTrue(all(0 < seconds <= 0.05 for seconds in sleeps))
                self.assertEqual(len(sleeps), 3)

    def test_f8_during_wait_stops_before_another_sleep(self):
        for kind in (Controller, Runner):
            with self.subTest(kind=kind.__name__):
                stop = threading.Event()
                sleeps = []
                def sleep(seconds):
                    sleeps.append(seconds)
                    stop.set()
                runner = next(item for item in self.runners(lambda: 0.0, sleep, stop) if type(item) is kind)
                with self.assertRaises(Stopped):
                    runner.wait(0.3)
                self.assertEqual(sleeps, [0.05])

    def test_zero_duration_still_checks_cancellation_without_sleeping(self):
        stop = threading.Event()
        stop.set()
        sleeps = []
        for runner in self.runners(lambda: 0.0, sleeps.append, stop):
            with self.subTest(kind=type(runner).__name__), self.assertRaises(Stopped):
                runner.wait(0)
        self.assertEqual(sleeps, [])


if __name__ == '__main__':
    unittest.main()
