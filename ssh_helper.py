#!/usr/bin/env python3
"""Console-enabled entry point, also bundled separately inside the macOS app."""
import json
import sys
from ssh_client import askpass, credentials, run_session


def main():
    if len(sys.argv) > 1 and sys.argv[1] == '--self-test':
        from ssh_client import vault, ssh_command
        backend = vault()
        assert backend is not None
        assert ssh_command(credentials('192.0.2.1', 'test', 22))[-1] == '192.0.2.1'
        print('SSH helper ready')
        return 0
    if len(sys.argv) > 2 and sys.argv[1] == '--session':
        return run_session(credentials(**json.loads(sys.argv[2])))
    try:
        return askpass(sys.argv[1] if len(sys.argv) > 1 else 'Password:')
    except Exception:
        return 1


if __name__ == '__main__':
    sys.exit(main())
