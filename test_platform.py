import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import platform_support as platform
import ssh_client as ssh

spec = importlib.util.spec_from_file_location('main_app', Path(__file__).with_name('node-desk.py'))
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)


class PlatformTests(unittest.TestCase):
    def test_mac_config_location(self):
        with patch.object(platform.sys, 'platform', 'darwin'), patch.dict(os.environ, {}, clear=True), patch.object(platform.Path, 'home', return_value=Path('/Users/example')):
            self.assertEqual(platform.config_dir(), Path('/Users/example/Library/Application Support/Node Desk'))

    def test_linux_config_compatibility(self):
        with patch.object(platform.sys, 'platform', 'linux'), patch.dict(os.environ, {'XDG_CONFIG_HOME': '/tmp/example'}, clear=True):
            self.assertEqual(platform.config_dir(), Path('/tmp/example/tailscale-exit-ui'))

    def test_mac_finds_gui_tailscale_without_shell_path(self):
        with patch.object(platform.sys, 'platform', 'darwin'), patch.object(platform.shutil, 'which', return_value=None), patch.object(platform.Path, 'is_file', return_value=True), patch.object(platform.os, 'access', return_value=True):
            self.assertEqual(platform.tailscale_binary(), '/Applications/Tailscale.app/Contents/MacOS/Tailscale')

    def test_mac_tailscale_forces_cli_mode(self):
        with patch.object(app.sys, 'platform', 'darwin'), patch.object(app, 'tailscale_binary', return_value='/Applications/Tailscale.app/Contents/MacOS/Tailscale'), patch.object(app.subprocess, 'run') as run:
            run.return_value.returncode = 0
            run.return_value.stdout = '{}'
            self.assertEqual(app.run_cli(['status', '--json']), '{}')
            self.assertEqual(run.call_args.kwargs['env']['TAILSCALE_BE_CLI'], '1')

    def test_mac_uses_keychain_backend(self):
        module = types.ModuleType('keyring.backends.macOS')
        module.Keyring = lambda: 'mac-keychain'
        with patch.object(ssh.sys, 'platform', 'darwin'), patch.dict(sys.modules, {'keyring.backends.macOS': module}):
            self.assertEqual(ssh.vault(), 'mac-keychain')

    def test_applescript_does_not_interpolate_connection_values(self):
        env = {'SSH_ASKPASS': "/Users/a's folder/helper", 'TEST': '$(do-not-run); "hello"'}
        command = ['/Applications/Node Desk.app/helper', '--session', '{"user":"test"}']
        result = ssh.mac_terminal_command(command, env)
        self.assertNotIn('do-not-run', result[2])
        parsed = shlex.split(result[3])
        self.assertEqual(parsed, ['env'] + [f'{k}={v}' for k, v in env.items()] + command)

    def test_mac_launch_uses_terminal_and_separate_secret_reference(self):
        server = dict(ssh.credentials('192.0.2.1', 'test', 22), secret_key='server:123', password='DO_NOT_LEAK')
        with patch.object(ssh.sys, 'platform', 'darwin'), patch.object(ssh.shutil, 'which', return_value='/usr/bin/ssh'), patch.object(ssh, 'helper_invocation', return_value=('/app/helper', ['/app/helper'])), patch.object(ssh.subprocess, 'run') as run:
            run.return_value.returncode = 0
            ssh.launch_server(server)
            argv = run.call_args.args[0]
            self.assertEqual(argv[0], '/usr/bin/osascript')
            self.assertIn('TAILSCALE_UI_SSH_SECRET_KEY=server:123', shlex.split(argv[3]))
            self.assertNotIn('DO_NOT_LEAK', repr(argv))

    def test_source_helper_preserves_argument_quoting(self):
        with tempfile.TemporaryDirectory(prefix="node desk's ") as folder:
            directory = Path(folder)
            (directory / 'ssh_helper.py').write_text('import json,sys\nprint(json.dumps(sys.argv[1:]))\n')
            with patch.object(ssh, '__file__', str(directory / 'ssh_client.py')), patch.object(ssh, 'config_dir', return_value=directory / 'config'), patch.object(ssh.sys, 'frozen', False, create=True):
                helper, _ = ssh.helper_invocation()
            value = 'argument with spaces and $(literal); apostrophe\''
            result = subprocess.run([helper, value], capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(result.stdout), [value])

    def test_frozen_helper_is_resolved_inside_app_bundle(self):
        with tempfile.TemporaryDirectory() as folder:
            contents = Path(folder) / 'Node Desk.app' / 'Contents'
            helper = contents / 'Helpers' / 'node-desk-helper' / 'node-desk-helper'
            helper.parent.mkdir(parents=True)
            helper.touch()
            with patch.object(ssh.sys, 'frozen', True, create=True), patch.object(ssh.sys, 'executable', str(contents / 'MacOS' / 'Node Desk')):
                executable, command = ssh.helper_invocation()
                self.assertEqual(executable, str(helper.resolve()))
                self.assertEqual(command, [str(helper.resolve())])

    def test_frozen_helper_through_symlinked_directory(self):
        # Reproduce macOS /var -> /private/var on every test platform.
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'real').mkdir()
            (root / 'alias').symlink_to(root / 'real', target_is_directory=True)
            contents = root / 'alias' / 'Node Desk.app' / 'Contents'
            helper = contents / 'Helpers' / 'node-desk-helper' / 'node-desk-helper'
            helper.parent.mkdir(parents=True)
            helper.touch()
            with patch.object(ssh.sys, 'frozen', True, create=True), patch.object(ssh.sys, 'executable', str(contents / 'MacOS' / 'Node Desk')):
                executable, command = ssh.helper_invocation()
                self.assertTrue(Path(executable).samefile(helper))
                self.assertEqual(executable, str(helper.resolve()))
                self.assertEqual(command, [executable])


if __name__ == '__main__':
    unittest.main()
