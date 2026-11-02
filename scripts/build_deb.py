#!/usr/bin/env python3
"""Build a Debian package from this source tree without root privileges."""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent


def main():
    if not shutil.which('dpkg-deb'):
        raise SystemExit('dpkg-deb not found. Install the Debian dpkg package.')
    version = (ROOT / 'VERSION').read_text().strip()
    if not re.fullmatch(r'\d+\.\d+\.\d+(?:[+~.-][A-Za-z0-9.+~]+)?', version):
        raise SystemExit('VERSION must contain a valid numeric release version.')
    output = ROOT / 'dist'
    output.mkdir(exist_ok=True)
    package = output / f'node-desk_{version}_all.deb'
    with tempfile.TemporaryDirectory(prefix='node-desk-build-') as folder:
        stage = Path(folder)
        stage.chmod(0o755)
        for target in ('DEBIAN', 'usr/bin', 'usr/lib/node-desk',
                       'usr/share/applications', 'usr/share/doc/node-desk'):
            (stage / target).mkdir(parents=True, exist_ok=True)
            (stage / target).chmod(0o755)
        control = (ROOT / 'packaging/control.in').read_text().replace('@VERSION@', version)
        (stage / 'DEBIAN/control').write_text(control)
        for source, destination, mode in (
            ('node-desk.py', 'usr/bin/node-desk', 0o755),
            ('ssh_client.py', 'usr/lib/node-desk/ssh_client.py', 0o755),
            ('ssh_helper.py', 'usr/lib/node-desk/ssh_helper.py', 0o755),
            ('platform_support.py', 'usr/lib/node-desk/platform_support.py', 0o644),
            ('packaging/node-desk.desktop', 'usr/share/applications/node-desk.desktop', 0o644),
            ('README.md', 'usr/share/doc/node-desk/README.md', 0o644),
        ):
            target = stage / destination
            shutil.copyfile(ROOT / source, target)
            target.chmod(mode)
        (stage / 'usr/bin/tailscale-exit-ui').symlink_to('node-desk')
        subprocess.run(['dpkg-deb', '--root-owner-group', '--build', str(stage), str(package)], check=True)
    print(package)


if __name__ == '__main__':
    main()
