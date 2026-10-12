#!/usr/bin/env python3
"""Prepare a fresh pinned build tree; never execute the repository's x86 custom.sh."""
import argparse
import gzip
import hashlib
import json
import pathlib
import shutil
import struct
import subprocess
import urllib.request

REPO = pathlib.Path(__file__).resolve().parents[2]
LOCK = REPO / 'configs/am6bplus/sources.lock.json'


def run(*args, cwd=None):
    subprocess.run(args, cwd=cwd, check=True)


def checkout(spec, path):
    if path.exists():
        raise ValueError(f'Refusing existing checkout: {path}')
    run('git', 'init', str(path))
    run('git', 'remote', 'add', 'origin', spec['url'], cwd=path)
    run('git', 'fetch', '--depth', '1', 'origin', spec['commit'], cwd=path)
    run('git', 'checkout', '--detach', 'FETCH_HEAD', cwd=path)
    actual = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=path, text=True).strip()
    if actual != spec['commit']:
        raise ValueError(f'Checkout identity mismatch: {actual}')


def install_core(spec, output):
    with urllib.request.urlopen(spec['url'], timeout=120) as response:
        data = response.read(100_000_001)
    if len(data) > 100_000_000 or hashlib.sha256(data).hexdigest() != spec['sha256']:
        raise ValueError('Mihomo download size/hash mismatch')
    binary = gzip.decompress(data)
    # ELF64 little-endian, e_machine == EM_AARCH64. Do not execute target code.
    if binary[:6] != b'\x7fELF\x02\x01' or struct.unpack_from('<H', binary, 18)[0] != 183:
        raise ValueError('Mihomo is not an AArch64 ELF64 binary')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(binary)
    output.chmod(0o755)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('build_dir', type=pathlib.Path)
    args = parser.parse_args()
    lock = json.loads(LOCK.read_text())
    build = args.build_dir.resolve()
    checkout(lock['openwrt'], build)
    # defconfig runs host prerequisites non-interactively; repeat after feeds install.
    shutil.copyfile(REPO / 'configs/am6bplus/seed.config', build / '.config')
    run('make', 'defconfig', cwd=build)
    (build / 'feeds.conf').write_text(''.join(
        f"src-git {name} {spec['url']}^{spec['commit']}\n" for name, spec in lock['feeds'].items()))
    run('./scripts/feeds', 'update', '-a', cwd=build)
    for name, spec in lock['feeds'].items():
        actual = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=build / 'feeds' / name, text=True).strip()
        if actual != spec['commit']:
            raise ValueError(f'Feed {name} drift: {actual}')
    run('./scripts/feeds', 'install', '-a', cwd=build)
    for name, spec in lock['plugins'].items():
        checkout(spec, build / 'package' / 'am6bplus' / name)
    shutil.copyfile(REPO / 'configs/am6bplus/seed.config', build / '.config')
    # Dedicated overlay. No inherited credentials, disk formatting or x86 core.
    overlay = build / 'files'
    install_core(lock['mihomo'], overlay / 'etc/openclash/core/clash_meta')
    defaults = overlay / 'etc/uci-defaults/99-am6bplus-safe-firstboot'
    defaults.parent.mkdir(parents=True, exist_ok=True)
    defaults.write_text('''#!/bin/sh
# Services are installed but require deliberate configuration before use.
for service in openclash mosdns ddns-go adguardhome miniupnpd banip containerd dockerd samba4 ttyd; do
    [ ! -x "/etc/init.d/$service" ] || "/etc/init.d/$service" disable
done
uci -q set openclash.config.enable='0'
uci -q commit openclash
exit 0
''')
    defaults.chmod(0o755)
    run('make', 'defconfig', cwd=build)
    run('python3', str(REPO / 'scripts/am6bplus/verify-config.py'), str(build / '.config'))
    manifest = {'sources': lock, 'nft_qos_policy': 'omitted-by-user-decision-2026-10-12',
                'nft_qos_included': False, 'hardware_validation': 'NOT_RUN',
                'phase': 'source-preparation-before-firmware-build'}
    (build / 'am6bplus-source-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')


if __name__ == '__main__':
    main()
