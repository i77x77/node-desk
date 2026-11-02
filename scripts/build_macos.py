#!/usr/bin/env python3
"""Build and smoke-test a macOS app/DMG on the current native architecture."""
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent


def run(command, **kwargs):
    subprocess.run([str(item) for item in command], check=True, **kwargs)


def main():
    if sys.platform != 'darwin':
        raise SystemExit('macOS build requires a Mac. Use the GitHub Actions macOS job.')
    version = (ROOT / 'VERSION').read_text().strip()
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise SystemExit('VERSION must contain a numeric major.minor.patch version.')
    architecture = platform.machine()
    if architecture not in ('arm64', 'x86_64'):
        raise SystemExit('Unsupported macOS architecture: ' + architecture)
    dist = ROOT / 'dist'
    dist.mkdir(exist_ok=True)
    work = ROOT / 'build' / 'macos'
    work.mkdir(parents=True, exist_ok=True)
    identity = os.environ.get('MACOS_SIGN_IDENTITY', '-')
    common = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir',
              '--hidden-import', 'keyring.backends.macOS', '--copy-metadata', 'keyring',
              '--specpath', str(work), '--codesign-identity', identity]
    run(common + ['--console', '--name', 'node-desk-helper', '--distpath', work / 'helper-dist',
                  '--workpath', work / 'helper-work', ROOT / 'ssh_helper.py'])
    run(common + ['--windowed', '--name', 'Node Desk', '--osx-bundle-identifier', 'io.github.i77x77.node-desk',
                  '--distpath', dist, '--workpath', work / 'gui-work', ROOT / 'node-desk.py'])
    app = dist / 'Node Desk.app'
    helper_dir = app / 'Contents' / 'Helpers' / 'node-desk-helper'
    shutil.copytree(work / 'helper-dist' / 'node-desk-helper', helper_dir, symlinks=True, dirs_exist_ok=True)
    plist_path = app / 'Contents' / 'Info.plist'
    with plist_path.open('rb') as handle:
        info = plistlib.load(handle)
    info.update(CFBundleShortVersionString=version, CFBundleVersion=version,
                LSMinimumSystemVersion='15.0', NSHighResolutionCapable=True,
                NSAppleEventsUsageDescription='Node Desk opens SSH sessions in Terminal when you connect to a server.')
    with plist_path.open('wb') as handle:
        plistlib.dump(info, handle)
    run(['/usr/bin/codesign', '--force', '--deep', '--sign', identity, app])
    run(['/usr/bin/codesign', '--verify', '--deep', '--strict', app])
    # Exercise the frozen helper without accessing a real server or the keychain.
    helper = helper_dir / 'node-desk-helper'
    run([helper, '--self-test'])
    with tempfile.TemporaryDirectory(prefix='node-desk-smoke-') as folder:
        result = Path(folder) / 'result.json'
        env = {**os.environ, 'NODE_DESK_CONFIG_DIR': str(Path(folder) / 'config')}
        run([app / 'Contents' / 'MacOS' / 'Node Desk', '--smoke-test', result], env=env, timeout=60)
        report = json.loads(result.read_text())
        if report.get('tabs') != 2 or not report.get('ok'):
            raise SystemExit('GUI smoke test failed: ' + str(report))
    with tempfile.TemporaryDirectory(prefix='node-desk-dmg-') as folder:
        content = Path(folder)
        content.chmod(0o755)
        shutil.copytree(app, content / app.name, symlinks=True)
        (content / 'Applications').symlink_to('/Applications')
        dmg = dist / f'node-desk_{version}_macos_{architecture}.dmg'
        run(['/usr/bin/hdiutil', 'create', '-ov', '-format', 'UDZO', '-volname', 'Node Desk',
             '-srcfolder', content, dmg])
    print(dmg)


if __name__ == '__main__':
    main()
