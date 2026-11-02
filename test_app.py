import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('app', Path(__file__).with_name('node-desk.py'))
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)

class StatusTests(unittest.TestCase):
    def test_running_without_exit_is_disconnected(self):
        self.assertEqual(app.describe_status({'BackendState': 'Running'})[0], 'Не подключён')

    def test_online_exit(self):
        status = app.describe_status({'BackendState': 'Running', 'ExitNodeStatus': {
            'Online': True, 'TailscaleIPs': ['100.114.10.75/32']}})
        self.assertEqual(status[0], 'Подключён')
        self.assertIn('100.114.10.75', status[1])
        self.assertNotIn('/32', status[1])

    def test_offline_selected_exit(self):
        self.assertEqual(app.describe_status({'BackendState': 'Running', 'ExitNodeStatus': {
            'Online': False}})[0], 'Узел недоступен')

    def test_logged_out_is_never_connected(self):
        self.assertEqual(app.describe_status({'BackendState': 'NeedsLogin', 'ExitNodeStatus': {
            'Online': True}})[0], 'Нужен вход в Tailscale')

    def test_legacy_peer(self):
        self.assertEqual(app.describe_status({'BackendState': 'Running', 'Peer': {
            'key': {'ExitNode': True, 'Online': True}}})[0], 'Подключён')

    def test_reject_command_injection(self):
        for value in ['100.114.10.75; reboot', '--help', '', 'host.example', 'fe80::1%eth0']:
            with self.assertRaises(ValueError):
                app.validate_ip(value)

    def test_command_uses_argv_without_password_prompt(self):
        with patch.object(app.shutil, 'which', side_effect=lambda name: '/usr/bin/' + name), \
             patch.object(app.os, 'geteuid', return_value=1000), \
             patch.object(app.subprocess, 'run') as run:
            run.return_value.returncode = 0
            run.return_value.stdout = ''
            app.run_cli(['set', '--exit-node='], privileged=True)
            self.assertEqual(run.call_args.args[0], ['/usr/bin/tailscale', 'set', '--exit-node='])
            self.assertNotIn('shell', run.call_args.kwargs)

class PersistenceTests(unittest.TestCase):
    def test_close_saves_entered_ip_without_connecting(self):
        import tempfile
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as folder:
            instance = app.App.__new__(app.App)
            instance.config = Path(folder) / 'config.json'
            instance.ip = Mock()
            instance.ip.get.return_value = '100.114.10.76'
            instance.root = Mock()
            instance.close()
            self.assertEqual(app.json.loads(instance.config.read_text())['ip'], '100.114.10.76')
            instance.root.destroy.assert_called_once()

    def test_invalid_input_preserves_saved_ip(self):
        import tempfile
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as folder:
            instance = app.App.__new__(app.App)
            instance.config = Path(folder) / 'config.json'
            instance.config.write_text('{"ip":"100.114.10.75"}')
            instance.ip = Mock()
            instance.ip.get.return_value = 'invalid'
            instance.root = Mock()
            instance.close()
            self.assertEqual(app.json.loads(instance.config.read_text())['ip'], '100.114.10.75')

class InterfaceTests(unittest.TestCase):
    def test_save_button_persists_without_connection(self):
        import tempfile
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as folder:
            instance = app.App.__new__(app.App)
            instance.config = Path(folder) / 'nested' / 'config.json'
            instance.ip = Mock()
            instance.ip.get.return_value = ' 100.114.10.77 '
            instance.note = Mock()
            instance.save_ip()
            self.assertEqual(app.json.loads(instance.config.read_text())['ip'], '100.114.10.77')
            instance.ip.set.assert_called_once_with('100.114.10.77')

    def test_toggle_disconnects_selected_node(self):
        from unittest.mock import Mock
        instance = app.App.__new__(app.App)
        instance.known, instance.busy, instance.selected = True, False, True
        instance.change = Mock()
        instance.toggle_connection()
        instance.change.assert_called_once_with(False)

    def test_toggle_connects_when_no_node_selected(self):
        from unittest.mock import Mock
        instance = app.App.__new__(app.App)
        instance.known, instance.busy, instance.selected = True, False, False
        instance.change = Mock()
        instance.toggle_connection()
        instance.change.assert_called_once_with(True)

    def test_unknown_status_blocks_toggle(self):
        from unittest.mock import Mock
        instance = app.App.__new__(app.App)
        instance.known, instance.busy = False, False
        instance.change = Mock()
        instance.toggle_connection()
        instance.change.assert_not_called()

if __name__ == '__main__':
    unittest.main()
