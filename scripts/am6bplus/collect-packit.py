#!/usr/bin/env python3
"""Verify upstream-produced disk structure and bind its identity to the rootfs run."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main(packit, output):
    images = list((packit / 'output').glob('*.img'))
    if len(images) != 1:
        raise ValueError(f'Expected one upstream .img, found {len(images)}')
    image = images[0]
    if image.is_symlink() or image.stat().st_size < 1024**3:
        raise ValueError('Invalid/incomplete upstream image')
    table = json.loads(subprocess.check_output(['sfdisk', '--json', str(image)], text=True))
    partitions = table['partitiontable']['partitions']
    if len(partitions) != 2 or partitions[0]['start'] != 8192:
        raise ValueError('Unexpected upstream SD partition layout')
    postflight = json.loads((packit / 'output/packaging-manifest.json').read_text())
    with image.open('rb') as stream:
        stream.seek(partitions[0]['start'] * 512)
        fat = stream.read(512)
        if b'FAT' not in fat[54:90] or fat[510:512] != b'\x55\xaa':
            raise ValueError('Missing FAT boot filesystem signature')
        stream.seek(partitions[1]['start'] * 512 + 0x10000)
        superblock = stream.read(4096)
        if superblock[0x40:0x48] != b'_BHRfS_M':
            raise ValueError('Missing upstream Btrfs root filesystem signature')
        if str(uuid.UUID(bytes=superblock[0x20:0x30])) != postflight['root_uuid']:
            raise ValueError('Actual Btrfs UUID differs from postflight/uEnv/fstab identity')
    output.mkdir(parents=True, exist_ok=True)
    target = output / (image.name + '.gz')
    if target.exists():
        raise ValueError('Refusing to overwrite an existing output image')
    with image.open('rb') as source, target.open('wb') as destination:
        with gzip.GzipFile(filename='', mode='wb', fileobj=destination, compresslevel=1, mtime=0) as compressed:
            shutil.copyfileobj(source, compressed)
    patch_manifest = json.loads((packit / 'am6bplus-patch-manifest.json').read_text())
    source_run = json.loads((output / 'source-run.json').read_text())
    source_artifact = json.loads((output / 'source-artifact.json').read_text())
    manifest = {'schema': 1, 'kind': 'am6bplus-upstream-packit-sd',
                'configuration_sha': os.environ['EXPECTED_CONFIGURATION_SHA'],
                'packaging_sha': os.environ['PACKAGING_SHA'],
                'parent_run_id': source_run['id'], 'parent_run_attempt': source_run['run_attempt'],
                'parent_artifact_id': source_artifact['id'], 'parent_artifact_digest': source_artifact.get('digest'),
                'pack_run_id': int(os.environ['GITHUB_RUN_ID']), 'pack_run_attempt': int(os.environ['GITHUB_RUN_ATTEMPT']),
                'image_built': True, 'upstream': patch_manifest, 'rootfs_postflight': postflight, 'image': {'name': target.name, 'sha256': digest(target),
                                                    'raw_sha256': digest(image), 'raw_size': image.stat().st_size},
                'partitions': table, 'hardware_validation': 'NOT_RUN',
                'warning': 'Experimental external-kernel APK rootfs; not official AM6B Plus support. SD boot can modify bootloader environment.'}
    (output / 'packaging-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(f'Upstream image structure verified and compressed: {target.name}')


if __name__ == '__main__':
    main(Path(sys.argv[1]), Path(sys.argv[2]))
