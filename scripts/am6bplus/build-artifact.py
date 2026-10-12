#!/usr/bin/env python3
"""Bind build artifacts to one trusted repository/run/attempt/configuration."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[2]
ROOTFS_NAME = 'openwrt-armsr-armv8-generic-rootfs.tar.gz'
WORKFLOW = 'AM6B Plus - Build ARM64 rootfs 25.12.5'


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def create(build, output):
    candidates = list((build / 'bin/targets/armsr/armv8').glob('*rootfs.tar.gz'))
    if len(candidates) != 1:
        raise ValueError(f'Expected one ARM64 rootfs, found {len(candidates)}')
    output.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(candidates[0], output / ROOTFS_NAME)
    shutil.copyfile(build / '.config', output / 'openwrt.config')
    shutil.copyfile(ROOT / 'configs/am6bplus/sources.lock.json', output / 'sources.lock.json')
    for path in (build / 'bin/targets/armsr/armv8').glob('*.manifest'):
        shutil.copyfile(path, output / path.name)
    manifest = {'schema': 1, 'kind': 'am6bplus-rootfs', 'repository': os.environ['GITHUB_REPOSITORY'],
                'configuration_sha': os.environ['GITHUB_SHA'], 'workflow': os.environ['GITHUB_WORKFLOW'],
                'run_id': int(os.environ['GITHUB_RUN_ID']), 'run_attempt': int(os.environ['GITHUB_RUN_ATTEMPT']),
                'openwrt': json.loads((output / 'sources.lock.json').read_text())['openwrt'],
                'files': {name: {'sha256': digest(output / name), 'size': (output / name).stat().st_size}
                          for name in [ROOTFS_NAME, 'openwrt.config', 'sources.lock.json']},
                'firmware_packaging': 'NOT_RUN', 'hardware_validation': 'NOT_RUN'}
    (output / 'build-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')


def verify(directory, run_file):
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
    for key, expected in [('schema', 1), ('kind', 'am6bplus-rootfs'), ('repository', expected_repo),
                          ('configuration_sha', run['head_sha']), ('workflow', WORKFLOW),
                          ('run_id', run['id']), ('run_attempt', run['run_attempt'])]:
        if manifest.get(key) != expected:
            raise ValueError(f'Artifact identity mismatch: {key}')
    for name in [ROOTFS_NAME, 'openwrt.config', 'sources.lock.json']:
        path = directory / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f'Invalid artifact file: {name}')
        expected = manifest['files'][name]
        if digest(path) != expected['sha256'] or path.stat().st_size != expected['size']:
            raise ValueError(f'Artifact integrity mismatch: {name}')
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
    args = parser.parse_args()
    (create if args.mode == 'create' else verify)(args.first, args.second)
