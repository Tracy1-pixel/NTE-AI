import unittest

from nte_overlay import CaptureShield
from nte_status import RuntimeStatus, overlay_position
from nte_window import ClientArea


class Native:
    def __init__(self):
        self.events = []

    def position_overlay(self, *args):
        self.events.append(('show', args))

    def hide(self, hwnd):
        self.events.append(('hide', hwnd))

    def flush_compositor(self):
        self.events.append(('flush',))


class OverlayTests(unittest.TestCase):
    def test_capture_excluded_overlay_does_not_interrupt_rendering(self):
        api = Native()
        shield = CaptureShield(api, 7, True)
        shield.show(12, 34)
        api.events.clear()
        self.assertEqual(shield.capture(lambda: 'frame'), 'frame')
        self.assertEqual(api.events, [])

    def test_fallback_hides_during_capture_and_restores_same_position(self):
        api = Native()
        shield = CaptureShield(api, 7, False)
        shield.show(12, 34)
        api.events.clear()
        def capture():
            self.assertEqual(api.events, [('hide', 7), ('flush',)])
            return 'frame'
        self.assertEqual(shield.capture(capture), 'frame')
        self.assertEqual(api.events[-1], ('show', (7, 12, 34, 430, 112)))

    def test_fallback_restores_after_screenshot_error(self):
        api = Native()
        shield = CaptureShield(api, 7, False)
        shield.show(12, 34)
        def capture():
            raise OSError('capture failed')
        with self.assertRaisesRegex(OSError, 'capture failed'):
            shield.capture(capture)
        self.assertEqual(api.events[-1], ('show', (7, 12, 34, 430, 112)))

    def test_capture_does_not_show_inactive_overlay(self):
        api = Native()
        shield = CaptureShield(api, 7, False)
        shield.hide()
        api.events.clear()
        shield.capture(lambda: 'frame')
        self.assertEqual(api.events, [])

    def test_position_follows_moving_and_resizing_game_client(self):
        self.assertEqual(overlay_position(ClientArea(100, 200, 1920, 1080)), (116, 1152))
        self.assertEqual(overlay_position(ClientArea(300, 100, 1280, 720)), (316, 692))

    def test_status_distinguishes_unknown_score_and_zero_when_paused(self):
        status = RuntimeStatus(completed=2, failures=1)
        self.assertEqual(status.score_text, '— / 1,900')
        status.apply({'score': 0, 'state': 'paused', 'details': '窗口尺寸错误'})
        self.assertEqual(status.score_text, '0 / 1,900')
        self.assertEqual(status.color, '#ffc267')
        self.assertEqual((status.completed, status.failures), (2, 1))


if __name__ == '__main__':
    unittest.main()
