#!/usr/bin/env python3
"""Read-only validation of runtime tools and safe overlays in the built rootfs."""
import hashlib
import json
import struct
from pathlib import Path
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[2]
REQUIRED_TOOLS = (
    'usr/bin/pip3', 'usr/bin/python3', 'usr/bin/btrfs', 'usr/bin/docker',
    'usr/bin/dockerd', 'etc/init.d/dockerd', 'usr/bin/v2dat',
    'usr/sbin/vsftpd', 'etc/init.d/vsftpd',
    'www/luci-static/resources/view/wol.js',
)
PYTHON_MODULES = ('pip', 'requests', 'yaml')
OVERLAY = ROOT / 'files/am6bplus'


def verify(filename):
    with tarfile.open(filename, 'r:gz') as archive:
        entries = {m.name.removeprefix('./'): m for m in archive.getmembers()}
        for name in REQUIRED_TOOLS:
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
        for source in OVERLAY.rglob('*'):
            if not source.is_file():
                continue
            target = source.relative_to(OVERLAY).as_posix()
            entry = entries.get(target)
            if entry is None or not entry.isfile() or archive.extractfile(entry).read() != source.read_bytes():
                raise ValueError(f'Missing or changed runtime overlay: {target}')
        v2dat = entries['usr/bin/v2dat']
        if not v2dat.isfile() or v2dat.mode & 0o111 != 0o111:
            raise ValueError('v2dat is not a regular executable')
        header = archive.extractfile(v2dat).read(64)
        if len(header) < 64 or header[:6] != b'\x7fELF\x02\x01' or struct.unpack_from('<H', header, 18)[0] != 183:
            raise ValueError('v2dat architecture mismatch')
        core = entries.get('etc/openclash/core/clash_meta')
        if core is None or not core.isfile() or core.mode & 0o111 != 0o111:
            raise ValueError('Missing executable OpenClash core')
        binary = archive.extractfile(core).read()
        locked = json.loads((Path(filename).parent / 'resolved-core.json').read_text())
        if hashlib.sha256(binary).hexdigest() != locked['binary_sha256']:
            raise ValueError('OpenClash core hash mismatch')
        if binary[:6] != b'\x7fELF\x02\x01' or struct.unpack_from('<H', binary, 18)[0] != 183:
            raise ValueError('OpenClash core architecture mismatch')
        for module in PYTHON_MODULES:
            if not any(f'/site-packages/{module}/__init__.py' in name for name in entries):
                raise ValueError(f'Missing {module} Python module')
    print('Runtime tools, ARM64 v2dat/core, temperature overlay and SD helper verified; no execution.')

if __name__ == '__main__':
    verify(sys.argv[1])
