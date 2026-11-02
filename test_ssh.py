import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('ssh_client', Path(__file__).with_name('ssh_client.py'))
ssh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ssh)

class SSHTests(unittest.TestCase):
    def test_validation(self):
        for values in [('host;shutdown', 'root', '22'), ('1.2.3.4', '-x', '22'), ('1.2.3.4', 'root', '0')]:
            with self.assertRaises(ValueError):
                ssh.credentials(*values)
        self.assertEqual(ssh.credentials('::1', 'root', '2222')['port'], 2222)

    def test_multiple_servers_survive_reload_and_edit(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'ssh.json'
            store = ssh.ServerStore(path)
            first = store.save(None, 'Production', 'Main database', ssh.credentials('1.2.3.4', 'root', 22))
            second = store.save(None, 'Staging', 'Test environment', ssh.credentials('1.2.3.5', 'deploy', 2222))
            store = ssh.ServerStore(path)
            self.assertEqual(len(store.servers), 2)
            store.save(first['id'], 'Production EU', 'New description', ssh.credentials('1.2.3.6', 'admin', 2200))
            store = ssh.ServerStore(path)
            self.assertEqual(store.servers[0]['name'], 'Production EU')
            self.assertEqual(store.servers[0]['secret_key'], first['secret_key'])
            self.assertEqual(store.servers[1], second)
            store.delete(first['id'])
            self.assertEqual(ssh.ServerStore(path).servers, [second])

    def test_separate_passwords_even_for_same_credentials(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(ssh, 'vault') as vault:
            path = Path(folder) / 'ssh.json'
            store = ssh.ServerStore(path)
            profile = ssh.credentials('1.2.3.4', 'root', 22)
            first = store.save(None, 'One', '', profile, 'secret-first')
            second = store.save(None, 'Two', '', profile, 'secret-second')
            self.assertNotEqual(first['secret_key'], second['secret_key'])
            self.assertEqual(vault.return_value.set_password.call_args_list[0].args, (ssh.SERVICE, first['secret_key'], 'secret-first'))
            self.assertNotIn('secret-first', path.read_text())
            self.assertNotIn('secret-second', path.read_text())
            store.save(first['id'], 'Renamed', 'Description', profile)
            self.assertEqual(vault.return_value.set_password.call_count, 2)
            self.assertTrue(store.servers[0]['has_password'])

    def test_legacy_server_migrates_with_password_reference(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'ssh.json'
            profile = ssh.credentials('1.2.3.4', 'root', 22)
            path.write_text(ssh.json.dumps(profile))
            store = ssh.ServerStore(path)
            self.assertEqual(len(store.servers), 1)
            self.assertEqual(store.servers[0]['secret_key'], ssh.identity(profile))
            self.assertEqual(ssh.ServerStore(path).servers, store.servers)

    def test_corrupt_config_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'ssh.json'
            path.write_text('invalid json')
            store = ssh.ServerStore(path)
            with self.assertRaises(RuntimeError):
                store.save(None, 'Server', '', ssh.credentials('1.2.3.4', 'root', 22))
            self.assertEqual(path.read_text(), 'invalid json')

    def test_vault_failure_does_not_write_config(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(ssh, 'vault', side_effect=RuntimeError('locked')):
            path = Path(folder) / 'ssh.json'
            store = ssh.ServerStore(path)
            with self.assertRaises(RuntimeError):
                store.save(None, 'Server', '', ssh.credentials('1.2.3.4', 'root', 22), 'secret-example')
            self.assertFalse(path.exists())

    def test_delete_removes_only_its_password(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(ssh, 'vault') as vault:
            store = ssh.ServerStore(Path(folder) / 'ssh.json')
            first = store.save(None, 'One', '', ssh.credentials('1.2.3.4', 'root', 22), 'first')
            second = store.save(None, 'Two', '', ssh.credentials('1.2.3.5', 'root', 22), 'second')
            store.delete(first['id'])
            vault.return_value.delete_password.assert_called_once_with(ssh.SERVICE, first['secret_key'])
            self.assertEqual(store.servers, [second])

    def test_launch_has_no_password_in_environment_or_command(self):
        server = dict(ssh.credentials('1.2.3.4', 'root', 22), secret_key='server:example', password='MUST_NOT_LEAK')
        with patch.object(ssh.shutil, 'which', return_value='/usr/bin/ssh'), patch.object(ssh, 'terminal_command', side_effect=lambda c: ['terminal', '-e', *c]), patch.object(ssh.subprocess, 'Popen') as popen:
            ssh.launch_server(server)
            command = popen.call_args.args[0]
            env = popen.call_args.kwargs['env']
            self.assertEqual(env['TAILSCALE_UI_SSH_SECRET_KEY'], 'server:example')
            self.assertEqual(env['SSH_ASKPASS_REQUIRE'], 'force')
            self.assertNotIn('shell', popen.call_args.kwargs)
            self.assertEqual(command[4], '--session')
            self.assertNotIn('MUST_NOT_LEAK', repr(command))
            self.assertNotIn('MUST_NOT_LEAK', repr(env))

    def test_ssh_preserves_host_verification(self):
        command = ssh.ssh_command(ssh.credentials('1.2.3.4', 'root', 22))
        self.assertIn('StrictHostKeyChecking=ask', command)
        self.assertEqual(command[-2:], ['--', '1.2.3.4'])

    def test_terminal_argv(self):
        with patch.object(ssh.shutil, 'which', side_effect=lambda n: '/usr/bin/gnome-terminal' if n == 'gnome-terminal' else None):
            self.assertEqual(ssh.terminal_command(['ssh', '::1']), ['/usr/bin/gnome-terminal', '--', 'ssh', '::1'])

if __name__ == '__main__':
    unittest.main()
