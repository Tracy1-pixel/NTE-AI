import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import automation
from test_runner import config


class SettingsTests(unittest.TestCase):
    def test_partial_configuration_survives_reopen(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(automation, 'ROOT', Path(folder)):
                automation.save_config({'click_region': [10, 10, 20, 20]})
                restored = automation.load_config()
                self.assertEqual(restored['click_region'], [10, 10, 20, 20])
                self.assertEqual(restored['enter_steps'], [])
                self.assertEqual(restored['target_score'], 1900)
                self.assertFalse((Path(folder) / 'config.json.tmp').exists())

    def test_refresh_preserves_captured_regions_and_steps(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(automation, 'ROOT', Path(folder)):
                initial = config()
                automation.save_config(initial)
                restored = automation.load_config()
                restored['max_rounds'] = 2
                automation.save_config(restored)
                saved = automation.load_config()
                self.assertEqual(saved['exit_steps'], initial['exit_steps'])
                self.assertEqual(saved['stamina'], initial['stamina'])
                self.assertEqual(saved['max_rounds'], 2)

    def test_nonfinite_runtime_limits_are_rejected(self):
        for value in (float('nan'), float('inf')):
            c = config()
            c['max_minutes'] = value
            with self.assertRaises(ValueError):
                automation.validate(c)
