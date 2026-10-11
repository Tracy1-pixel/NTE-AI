import os
import runpy
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from nte_privileges import ensure_administrator


class ElevationTests(unittest.TestCase):
    def api(self, status='否', result=33):
        return SimpleNamespace(status=Mock(return_value=status), relaunch=Mock(return_value=result), message=Mock())

    def test_non_windows_does_not_request_elevation(self):
        api = self.api()
        with patch('nte_privileges.sys.platform', 'linux'):
            self.assertTrue(ensure_administrator(api))
        api.status.assert_not_called()
        api.relaunch.assert_not_called()

    def test_already_elevated_process_continues_without_relaunch(self):
        api = self.api(status='是')
        with patch('nte_privileges.sys.platform', 'win32'):
            self.assertTrue(ensure_administrator(api))
        api.relaunch.assert_not_called()

    def test_frozen_child_preserves_arguments_and_working_directory(self):
        api = self.api()
        args = ['NTE-AI.exe', '--self-test', 'a report.json']
        with patch('nte_privileges.sys.platform', 'win32'), \
                patch('nte_privileges.sys.frozen', True, create=True), \
                patch('nte_privileges.sys.argv', args), \
                patch('nte_privileges.sys.executable', 'C:\\助手目录\\NTE-AI.exe'):
            self.assertFalse(ensure_administrator(api))
        api.relaunch.assert_called_once_with('C:\\助手目录\\NTE-AI.exe', subprocess.list2cmdline(args[1:]), os.getcwd())
        api.message.assert_not_called()

    def test_source_child_preserves_script_path_with_spaces_and_unicode(self):
        api = self.api()
        script = str(Path('异环 source/app.py').resolve())
        with patch('nte_privileges.sys.platform', 'win32'), \
                patch('nte_privileges.sys.frozen', False, create=True), \
                patch('nte_privileges.sys.argv', [script, '--self-test', 'result.json']), \
                patch('nte_privileges.sys.executable', 'C:\\Python 环境\\pythonw.exe'):
            self.assertFalse(ensure_administrator(api))
        api.relaunch.assert_called_once_with('C:\\Python 环境\\pythonw.exe', subprocess.list2cmdline([script, '--self-test', 'result.json']), os.getcwd())

    def test_cancel_or_denial_exits_without_repeated_requests(self):
        for result in (0, 5, 32):
            api = self.api(result=result)
            with self.subTest(result=result), patch('nte_privileges.sys.platform', 'win32'):
                self.assertFalse(ensure_administrator(api))
            api.relaunch.assert_called_once()
            api.message.assert_called_once()

    def test_unknown_token_does_not_loop_relaunching(self):
        api = self.api(status='未知')
        with patch('nte_privileges.sys.platform', 'win32'):
            self.assertFalse(ensure_administrator(api))
        api.relaunch.assert_not_called()
        api.message.assert_called_once()

    def test_failed_launch_exits_with_an_explanation(self):
        api = self.api()
        api.relaunch.side_effect = OSError('launch failed')
        with patch('nte_privileges.sys.platform', 'win32'):
            self.assertFalse(ensure_administrator(api))
        api.message.assert_called_once()

    def test_parent_never_opens_gui_after_relaunch_or_cancel(self):
        import app
        with patch('nte_privileges.ensure_administrator', return_value=False), \
                patch.object(app, 'enable_dpi_awareness') as dpi:
            self.assertEqual(app.main(), 0)
        dpi.assert_not_called()


class ManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.check = staticmethod(runpy.run_path(str(Path(__file__).resolve().parents[1] / 'packaging/check_admin_manifest.py'))['check_manifest'])

    def manifest(self, level='requireAdministrator', access='false'):
        return f'<assembly xmlns="urn:schemas-microsoft-com:asm.v1"><trustInfo><requestedExecutionLevel level="{level}" uiAccess="{access}"/></trustInfo></assembly>'

    def test_administrator_manifest_is_accepted(self):
        self.check(self.manifest().encode())

    def test_unprivileged_or_uiaccess_manifest_is_rejected(self):
        for level, access in (('asInvoker', 'false'), ('highestAvailable', 'false'), ('requireAdministrator', 'true')):
            with self.subTest(level=level, access=access), self.assertRaises(ValueError):
                self.check(self.manifest(level, access))

    def test_missing_or_ambiguous_execution_level_is_rejected(self):
        for xml in ('<assembly/>', '<assembly><requestedExecutionLevel level="requireAdministrator" uiAccess="false"/><requestedExecutionLevel level="asInvoker"/></assembly>'):
            with self.subTest(xml=xml), self.assertRaises(ValueError):
                self.check(xml)


if __name__ == '__main__':
    unittest.main()
