"""Small platform adapters shared by the GUI and SSH helper."""
import os
from pathlib import Path
import shutil
import sys


def config_dir():
    override = os.environ.get('NODE_DESK_CONFIG_DIR')
    if override:
        return Path(override).expanduser()
    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Application Support' / 'Node Desk'
    return Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config') / 'tailscale-exit-ui'


def tailscale_binary():
    binary = shutil.which('tailscale')
    if binary:
        return os.path.realpath(binary)
    if sys.platform == 'darwin':
        candidates = (
            Path('/Applications/Tailscale.app/Contents/MacOS/Tailscale'),
            Path.home() / 'Applications/Tailscale.app/Contents/MacOS/Tailscale',
            Path('/opt/homebrew/bin/tailscale'),
            Path('/usr/local/bin/tailscale'),
        )
        for candidate in candidates:
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)
    return None
