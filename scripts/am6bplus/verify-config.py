#!/usr/bin/env python3
"""Reject dropped requested symbols after Kconfig dependency resolution."""
import pathlib
import sys


def verify(path):
    actual = dict(line.strip().split('=', 1) for line in pathlib.Path(path).read_text().splitlines()
                  if line.startswith('CONFIG_') and '=' in line)
    seed = pathlib.Path(__file__).resolve().parents[2] / 'configs/am6bplus/seed.config'
    required = dict(line.split('=', 1) for line in seed.read_text().splitlines() if line.startswith('CONFIG_'))
    missing = [f'{key}: wanted {value}, got {actual.get(key, "absent")}'
               for key, value in required.items() if actual.get(key) != value]
    if actual.get('CONFIG_USE_APK') != 'y':
        missing.append('CONFIG_USE_APK must be y for OpenWrt 25.12')
    if missing:
        raise ValueError('Configuration dependency loss:\n' + '\n'.join(missing))
    print('Configuration matches every explicit requested symbol; APK enabled.')


if __name__ == '__main__':
    verify(sys.argv[1])
