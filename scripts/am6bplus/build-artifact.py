#!/usr/bin/env python3
"""Bind build artifacts to one trusted repository/run/attempt/configuration."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parents[2]
ROOTFS_NAME = 'openwrt-armsr-armv8-generic-rootfs.tar.gz'
WORKFLOW = 'AM6B Plus - Build ARM64 rootfs 25.12.5'


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def validate_resolved_core(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError('Missing or invalid resolved-core.json')
    core = json.loads(path.read_text())
    if not isinstance(core, dict):
        raise ValueError('Invalid resolved core: expected an object')
    for key, expected in [('schema', 1), ('type', 'Smart'), ('architecture', 'arm64'),
                          ('format', 'tar.gz')]:
        if core.get(key) != expected:
            raise ValueError(f'Invalid resolved core: {key}')
    commit = core.get('commit', '')
    if not isinstance(commit, str) or not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise ValueError('Invalid resolved core: commit')
    base = f'https://raw.githubusercontent.com/vernesong/OpenClash/{commit}/dev/smart/'
    for key, filename in [('url', 'clash-linux-arm64.tar.gz'), ('checksums_url', 'checksums.txt')]:
        if core.get(key) != base + filename:
            raise ValueError(f'Invalid resolved core: {key}')
    for key in ['sha256', 'binary_sha256', 'checksums_sha256']:
        value = core.get(key, '')
        if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{64}', value):
            raise ValueError(f'Invalid resolved core: {key}')
    if core.get('resolution_mode') not in ['latest', 'pinned']:
        raise ValueError('Invalid resolved core: resolution_mode')


def create(build, output):
    # OpenWrt also emits generic-targz-rootfs.tar.gz. Select the canonical
    # rootfs explicitly; a broad glob rejects a successful two-output build.
    rootfs = build / 'bin/targets/armsr/armv8' / ROOTFS_NAME
    if rootfs.is_symlink() or not rootfs.is_file():
        raise ValueError(f'Missing canonical ARM64 rootfs: {rootfs}')
    validate_resolved_core(build / 'resolved-core.json')
    output.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(rootfs, output / ROOTFS_NAME)
    shutil.copyfile(build / '.config', output / 'openwrt.config')
    shutil.copyfile(ROOT / 'configs/am6bplus/sources.lock.json', output / 'sources.lock.json')
    shutil.copyfile(build / 'resolved-core.json', output / 'resolved-core.json')
    names = [ROOTFS_NAME, 'openwrt.config', 'sources.lock.json', 'resolved-core.json']
    for path in (build / 'bin/targets/armsr/armv8').glob('*.manifest'):
        if path.is_symlink() or not path.is_file():
            raise ValueError(f'Invalid package manifest: {path.name}')
        shutil.copyfile(path, output / path.name)
        names.append(path.name)
    manifest = {'schema': 2, 'kind': 'am6bplus-rootfs', 'repository': os.environ['GITHUB_REPOSITORY'],
                'configuration_sha': os.environ['GITHUB_SHA'], 'workflow': os.environ['GITHUB_WORKFLOW'],
                'run_id': int(os.environ['GITHUB_RUN_ID']), 'run_attempt': int(os.environ['GITHUB_RUN_ATTEMPT']),
                'openwrt': json.loads((output / 'sources.lock.json').read_text())['openwrt'],
                'files': {name: {'sha256': digest(output / name), 'size': (output / name).stat().st_size}
                          for name in names},
                'firmware_packaging': 'NOT_RUN', 'hardware_validation': 'NOT_RUN'}
    (output / 'build-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')


def verify(directory, run_file, allow_legacy_schema1=False):
    run = json.loads(run_file.read_text())
    manifest = json.loads((directory / 'build-manifest.json').read_text())
    expected_repo = os.environ['GITHUB_REPOSITORY']
    if run['repository']['full_name'] != expected_repo or run['head_repository']['full_name'] != expected_repo:
        raise ValueError('Foreign/fork source repository rejected')
    if run['event'] not in ['push', 'workflow_dispatch'] or run['head_branch'] != 'main':
        raise ValueError('Only same-repository main push/manual builds are trusted')
    if run['name'] != WORKFLOW or run['path'] != '.github/workflows/openwrt_am6bplus_25_12.yml':
        raise ValueError('Unexpected source workflow')
    if run['status'] != 'completed' or run['conclusion'] != 'success':
        raise ValueError('Source build is not successful/completed')
    schema = manifest.get('schema')
    if schema != 2 and not (schema == 1 and allow_legacy_schema1):
        raise ValueError('Unsupported artifact schema; legacy schema 1 requires explicit approval')
    for key, expected in [('kind', 'am6bplus-rootfs'), ('repository', expected_repo),
                          ('configuration_sha', run['head_sha']), ('workflow', WORKFLOW),
                          ('run_id', run['id']), ('run_attempt', run['run_attempt'])]:
        if manifest.get(key) != expected:
            raise ValueError(f'Artifact identity mismatch: {key}')
    required = {ROOTFS_NAME, 'openwrt.config', 'sources.lock.json'}
    if schema == 2:
        required.add('resolved-core.json')
    files = manifest.get('files', {})
    if not isinstance(files, dict) or not required.issubset(files):
        raise ValueError('Artifact manifest is missing required files')
    for name, expected in files.items():
        if not isinstance(name, str) or Path(name).name != name or name in ['.', '..']:
            raise ValueError('Invalid artifact filename')
        path = directory / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f'Invalid artifact file: {name}')
        if digest(path) != expected['sha256'] or path.stat().st_size != expected['size']:
            raise ValueError(f'Artifact integrity mismatch: {name}')
    if schema == 2:
        validate_resolved_core(directory / 'resolved-core.json')
    if digest(directory / 'sources.lock.json') != digest(ROOT / 'configs/am6bplus/sources.lock.json'):
        raise ValueError('Artifact source lock differs from checked-out build commit')
    if manifest['configuration_sha'] != os.environ['EXPECTED_CONFIGURATION_SHA']:
        raise ValueError('Checked-out configuration identity mismatch')
    print('Trusted exact-run rootfs artifact and source lock verified.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['create', 'verify'])
    parser.add_argument('first', type=Path)
    parser.add_argument('second', type=Path)
    parser.add_argument('--allow-legacy-schema1', action='store_true',
                        help='Allow verification of legacy artifacts without resolved core provenance')
    args = parser.parse_args()
    if args.mode == 'create':
        if args.allow_legacy_schema1:
            parser.error('--allow-legacy-schema1 is only supported with verify')
        create(args.first, args.second)
    else:
        verify(args.first, args.second, allow_legacy_schema1=args.allow_legacy_schema1)
