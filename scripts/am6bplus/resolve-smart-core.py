#!/usr/bin/env python3
"""Resolve the official ARM64 Smart core to an immutable, checksum-verified spec."""
import argparse
import hashlib
import json
import re
import subprocess


REPOSITORY = 'https://github.com/vernesong/OpenClash.git'
CORE_REF = 'refs/heads/core'
RAW_BASE = 'https://raw.githubusercontent.com/vernesong/OpenClash'
FILENAME = 'clash-linux-arm64.tar.gz'


def resolve(commit_override=''):
    if commit_override and not re.fullmatch(r'[0-9a-f]{40}', commit_override):
        raise ValueError('Smart core override must be a full lowercase 40-character commit SHA')
    commit = commit_override
    if not commit:
        refs = subprocess.check_output(
            ['git', 'ls-remote', '--exit-code', REPOSITORY, CORE_REF],
            timeout=60, text=True)
        matches = [line.split() for line in refs.splitlines() if line.strip()]
        if (len(matches) != 1 or len(matches[0]) != 2
                or matches[0][1] != CORE_REF
                or not re.fullmatch(r'[0-9a-f]{40}', matches[0][0])):
            raise ValueError('Expected exactly one full commit SHA for the official core branch')
        commit = matches[0][0]
    base = f'{RAW_BASE}/{commit}/dev/smart'
    checksums_url = f'{base}/checksums.txt'
    data = subprocess.check_output(
        ['curl', '--fail', '--location', '--proto', '=https', '--proto-redir', '=https',
         '--tlsv1.2', '--silent', '--show-error', '--connect-timeout', '20',
         '--max-time', '60', checksums_url], timeout=70)
    checksums = []
    for line in data.decode('utf-8').splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[-1] in (FILENAME, f'./{FILENAME}', f'*{FILENAME}', f'*./{FILENAME}'):
            if len(fields) != 2 or not re.fullmatch(r'[0-9a-fA-F]{64}', fields[0]):
                raise ValueError('Malformed ARM64 Smart core checksum entry')
            checksums.append(fields[0].lower())
    if len(checksums) != 1:
        raise ValueError('Expected exactly one ARM64 Smart core checksum entry')
    return {
        'schema': 1,
        'type': 'Smart',
        'architecture': 'arm64',
        'commit': commit,
        'format': 'tar.gz',
        'url': f'{base}/{FILENAME}',
        'sha256': checksums[0],
        'checksums_url': checksums_url,
        'checksums_sha256': hashlib.sha256(data).hexdigest(),
        'resolution_mode': 'pinned' if commit_override else 'latest',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--commit', default='', help='Optional full core-branch commit SHA for rollback')
    args = parser.parse_args()
    print(json.dumps(resolve(args.commit), indent=2))


if __name__ == '__main__':
    main()
