#!/usr/bin/env python3
"""Download checksum-pinned AM6 packaging inputs; never execute downloaded code."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('cache', type=Path)
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    args.cache.mkdir(parents=True, exist_ok=True)
    lock = json.loads(Path(__file__).with_name('assets.lock.json').read_text())
    for asset in lock['assets']:
        target = args.cache / asset['name']
        if not target.is_file() or digest(target) != asset['sha256']:
            if args.verify_only:
                raise SystemExit(f'Missing or changed asset: {target}')
            temporary = target.with_suffix(target.suffix + '.download')
            subprocess.run(['curl', '--fail', '--location', '--retry', '3',
                            '--proto', '=https', '--tlsv1.2', '--output',
                            str(temporary), asset['url']], check=True)
            if digest(temporary) != asset['sha256']:
                temporary.unlink()
                raise SystemExit(f'Checksum mismatch: {asset["name"]}')
            temporary.replace(target)
    with tarfile.open(args.cache / 'kernel.tar.gz', 'r:gz') as bundle:
        for asset in lock['kernel_members']:
            target = args.cache / asset['name']
            if not target.is_file() or digest(target) != asset['sha256']:
                if args.verify_only:
                    raise SystemExit(f'Missing or changed kernel member: {target}')
                member = bundle.getmember(asset['member'])
                if not member.isfile():
                    raise SystemExit(f'Not a regular archive member: {member.name}')
                with bundle.extractfile(member) as source, target.open('wb') as output:
                    shutil.copyfileobj(source, output)
            if digest(target) != asset['sha256']:
                raise SystemExit(f'Checksum mismatch: {asset["name"]}')
    print(f'All AM6 packaging inputs verified in {args.cache}')


if __name__ == '__main__':
    main()
