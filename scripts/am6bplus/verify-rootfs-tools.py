#!/usr/bin/env python3
"""Read-only validation of requested pip3 and manual SD helper in built rootfs."""
import hashlib
from pathlib import Path
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[2]

def verify(filename):
    with tarfile.open(filename, 'r:gz') as archive:
        entries = {m.name.removeprefix('./'): m for m in archive.getmembers()}
        for name in ('usr/bin/pip3', 'usr/bin/python3', 'usr/bin/btrfs'):
            if name not in entries or not (entries[name].isfile() or entries[name].issym()):
                raise ValueError(f'Missing required tool: {name}')
        for target, source in (
            ('usr/sbin/am6bplus-grow-sd', 'scripts/am6bplus/am6bplus-grow-sd.py'),
            ('usr/share/doc/am6bplus-grow-sd/README.zh-CN.md', 'docs/am6bplus/grow-sd/README.zh-CN.md'),
        ):
            entry = entries.get(target)
            if entry is None or not entry.isfile():
                raise ValueError(f'Missing regular rootfs file: {target}')
            content = archive.extractfile(entry).read()
            if hashlib.sha256(content).digest() != hashlib.sha256((ROOT / source).read_bytes()).digest():
                raise ValueError(f'Rootfs content mismatch: {target}')
            if target.startswith('usr/sbin/') and entry.mode & 0o111 != 0o111:
                raise ValueError(f'Rootfs helper is not executable: {target}')
        if not any('/site-packages/pip/__init__.py' in name for name in entries):
            raise ValueError('Missing pip Python module')
    print('Actual rootfs pip3, Python, btrfs and manual helper content/permissions verified; no execution.')

if __name__ == '__main__':
    verify(sys.argv[1])
