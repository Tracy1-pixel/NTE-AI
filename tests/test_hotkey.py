import threading
import unittest

from nte_hotkey import F8StopMonitor


class FakeKeys:
    def __init__(self, registered=True):
        self.registered = registered
        self.registration_error = 1409
        self.message = threading.Event()
        self.down = threading.Event()
        self.closed = threading.Event()
        self.owner = None
        self.poll_failed = False

    def register(self):
        self.owner = threading.get_ident()
        return self.registered

    def message_pressed(self):
        if threading.get_ident() != self.owner:
            raise RuntimeError('wrong message thread')
        return self.message.is_set()

    def key_pressed(self):
        if self.poll_failed:
            raise OSError('poll failed')
        return self.down.is_set()

    def unregister(self):
        if threading.get_ident() != self.owner:
            raise RuntimeError('wrong unregister thread')
        self.closed.set()


class HotkeyTests(unittest.TestCase):
    def monitor(self, api, reasons=None):
        stop = threading.Event()
        reasons = reasons if reasons is not None else []
        return F8StopMonitor(stop, on_stop=reasons.append, api_factory=lambda: api, interval=0.001), stop

    def test_short_press_message_stops_while_worker_is_busy(self):
        api = FakeKeys()
        reasons = []
        monitor, stop = self.monitor(api, reasons)
        with monitor:
            api.message.set()  # Already released: current key state is false.
            self.assertTrue(stop.wait(1))
        self.assertEqual(reasons, ['已收到 F8，正在停止自动操作'])
        self.assertTrue(api.closed.is_set())
        self.assertFalse(monitor.thread.is_alive())

    def test_current_key_state_is_an_independent_backup(self):
        api = FakeKeys()
        monitor, stop = self.monitor(api)
        with monitor:
            api.down.set()  # No WM_HOTKEY callback or keyboard hook.
            self.assertTrue(stop.wait(1))
        self.assertTrue(api.closed.is_set())

    def test_registration_conflict_still_has_a_working_stop(self):
        api = FakeKeys(registered=False)
        monitor, stop = self.monitor(api)
        logs = []
        monitor.log = logs.append
        with monitor:
            api.down.set()
            self.assertTrue(stop.wait(1))
        self.assertIn('独立按键检测', logs[0])
        self.assertFalse(api.closed.is_set())

    def test_f8_already_held_at_start_cancels_before_operation(self):
        api = FakeKeys()
        api.down.set()
        monitor, stop = self.monitor(api)
        with monitor:
            self.assertTrue(stop.wait(1))

    def test_close_releases_hotkey_without_cancelling_idle_user(self):
        api = FakeKeys()
        monitor, stop = self.monitor(api)
        with monitor:
            pass
        self.assertFalse(stop.is_set())
        self.assertTrue(api.closed.is_set())

    def test_stop_button_and_repeated_runs_do_not_leave_listeners(self):
        for _ in range(3):
            api = FakeKeys()
            monitor, stop = self.monitor(api)
            with monitor:
                stop.set()
            self.assertFalse(monitor.thread.is_alive())
            self.assertTrue(api.closed.is_set())

    def test_unavailable_keyboard_api_prevents_start(self):
        api = FakeKeys()
        api.poll_failed = True
        monitor, stop = self.monitor(api)
        with self.assertRaisesRegex(RuntimeError, '监听不可用'):
            monitor.start()
        self.assertTrue(stop.is_set())
        self.assertTrue(api.closed.is_set())

    def test_keyboard_failure_during_run_cancels_instead_of_losing_f8(self):
        api = FakeKeys()
        monitor, stop = self.monitor(api)
        with monitor:
            api.poll_failed = True
            self.assertTrue(stop.wait(1))
        self.assertIn('监听异常', monitor.reason)


if __name__ == '__main__':
    unittest.main()
