#!/usr/bin/env python3
"""Opt-in, two-stage growth for this project's two-partition AM6B Plus SD image.
No automatic boot hook. No format, partition deletion, reread, reboot or data migration.
Only native MMC SD media are supported; eMMC, USB and regular files are rejected.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import struct
import subprocess
import sys
import uuid

SECTOR = 512
PREFIX = 4 * 1024 * 1024
ROOT_START = 794624
ROOT_MIN = 6291456
SIZE_OFFSET = 446 + 16 + 12


def require(ok, message):
    if not ok:
        raise ValueError(message)


def read_at(fd, offset, length):
    value = os.pread(fd, length, offset)
    require(len(value) == length, 'Short read; stop without writing.')
    return value


def layout(mbr, capacity, fat, superblock, gpt_primary=b'', gpt_backup=b''):
    """Pure validation/planning, independently testable without a block device."""
    require(len(mbr) == 512 and mbr[510:] == b'\x55\xaa', 'Not a valid MBR.')
    require(gpt_primary[:8] != b'EFI PART' and gpt_backup[:8] != b'EFI PART',
            'GPT/stale GPT detected; unsupported. Do not erase it automatically.')
    entries = [mbr[446 + 16*i:462 + 16*i] for i in range(4)]
    require(not any(entries[2]) and not any(entries[3]), 'Extra partitions: refusing growth.')
    parts = [(e[0], e[4], *struct.unpack_from('<II', e, 8)) for e in entries[:2]]
    require(parts[0] == (0, 0x0c, 8192, 786432), 'Boot partition differs from the supported image.')
    flags, kind, start, count = parts[1]
    require(flags == 0 and kind == 0x83 and start == ROOT_START and count >= ROOT_MIN,
            'Root partition differs from the supported image.')
    require(capacity % SECTOR == 0 and capacity // SECTOR <= 0xffffffff,
            'Unsupported disk capacity / MBR geometry.')
    require((start + count) * SECTOR <= capacity, 'Partition extends beyond media.')
    require(len(fat) == 512 and fat[510:] == b'\x55\xaa' and fat[82:90] == b'FAT32   ',
            'Missing FAT32 boot signature.')
    require(len(superblock) == 4096 and superblock[0x40:0x48] == b'_BHRfS_M',
            'Missing Btrfs root signature.')
    total, used, _, devices = struct.unpack_from('<QQQQ', superblock, 0x70)
    require(devices == 1, 'Multi-device Btrfs is unsupported.')
    require(0 < used <= total <= count * SECTOR, 'Invalid Btrfs filesystem geometry.')
    root_uuid = str(uuid.UUID(bytes=bytes(superblock[0x20:0x30])))
    # Leave <1MiB at the end if required for MiB alignment. Never shrink.
    new_count = (capacity // SECTOR // 2048) * 2048 - start
    require(new_count >= count, 'Growth would shrink the partition; refusing.')
    changed = bytearray(mbr)
    struct.pack_into('<I', changed, SIZE_OFFSET, new_count)
    return dict(root_uuid=root_uuid, root_start=ROOT_START, old_sectors=count, new_sectors=new_count,
                filesystem_bytes=total, target_bytes=new_count * SECTOR), bytes(changed)


def sd_identity(device):
    device = Path(device).resolve(strict=True)
    require(re.fullmatch(r'mmcblk[0-9]+', device.name) is not None,
            'Only a whole native SD device /dev/mmcblkN is supported. No USB/eMMC/partition/image.')
    st = device.stat()
    require(stat.S_ISBLK(st.st_mode), 'Not a block device.')
    node = Path('/sys/class/block') / device.name
    major, minor = map(int, (node / 'dev').read_text().strip().split(':'))
    require(st.st_rdev == os.makedev(major, minor), 'Device node does not match its SD sysfs identity.')
    require((node / 'device/type').read_text().strip() == 'SD', 'Media is not SD: eMMC is forbidden.')
    require((node / 'queue/logical_block_size').read_text().strip() == '512', '512-byte sectors required.')
    require((node / 'ro').read_text().strip() == '0', 'SD is read-only.')
    cid = (node / 'device/cid').read_text().strip()
    require(re.fullmatch(r'[0-9a-fA-F]{32}', cid) is not None, 'Missing reliable SD CID.')
    capacity = int((node / 'size').read_text()) * SECTOR
    identity = dict(device=str(device), cid=cid.lower(), capacity_bytes=capacity,
                    name=(node / 'device/name').read_text().strip())
    return device, node, st, identity


def kernel_geometry(node):
    p1 = node / (node.name + 'p1')
    require(int((p1 / 'start').read_text()) == 8192 and
            int((p1 / 'size').read_text()) == 786432, 'Kernel boot geometry differs from image.')
    p2 = node / (node.name + 'p2')
    require(int((p2 / 'start').read_text()) == ROOT_START, 'Kernel p2 start differs from MBR.')
    # Refuse hidden/extra kernel partitions left over from another layout.
    children = sorted(p.name for p in node.iterdir() if (p / 'partition').is_file())
    require(children == [node.name + 'p1', node.name + 'p2'], 'Unexpected kernel partitions.')
    return int((p2 / 'size').read_text())


def mounted_btrfs(mountpoint, device, root_uuid):
    mountpoint = str(Path(mountpoint).resolve(strict=True))
    require(mountpoint in ('/', '/rom'), 'Online flow supports only the current system / or /rom.')
    rows = []
    for line in Path('/proc/self/mountinfo').read_text().splitlines():
        left, right = line.split(' - ', 1)
        fields, tail = left.split(), right.split()
        if fields[4] == mountpoint and tail[0] == 'btrfs':
            rows.append((fields, tail))
    require(len(rows) == 1, 'Select a directly mounted Btrfs / or /rom, not an overlay mount.')
    require('rw' in rows[0][0][5].split(','), 'Selected Btrfs mount is not writable.')
    result = subprocess.run(['btrfs', 'filesystem', 'show', '--raw', mountpoint],
                            check=True, text=True, capture_output=True,
                            env={**os.environ, 'LC_ALL': 'C'})
    output = result.stdout
    require(re.search(r'uuid:\s*' + re.escape(root_uuid) + r'\b', output), 'Mounted Btrfs UUID mismatch.')
    require(re.search(r'Total devices\s+1\b', output), 'Mounted Btrfs is not single-device.')
    devices = re.findall(r'^\s*devid\s+(\d+)\s+size\s+(\d+)\s+used\s+\d+\s+path\s+(\S+)\s*$', output, re.M)
    require(len(devices) == 1 and devices[0][0] == '1',
            'Supported original single-device Btrfs devid=1 required.')
    partition = Path(str(device) + 'p2')
    part_stat = partition.stat()
    actual_stat = Path(devices[0][2]).stat()
    node = Path('/sys/class/block') / device.name / partition.name
    major, minor = map(int, (node / 'dev').read_text().strip().split(':'))
    expected_rdev = os.makedev(major, minor)
    require(stat.S_ISBLK(part_stat.st_mode) and stat.S_ISBLK(actual_stat.st_mode) and
            part_stat.st_rdev == actual_stat.st_rdev == expected_rdev,
            'Mounted Btrfs does not use this SD p2 exclusively.')
    return mountpoint, int(devices[0][1])


def check_consumers(node):
    for p in [node] + [x for x in node.iterdir() if (x / 'partition').is_file()]:
        require(not list((p / 'holders').iterdir()), 'Device-mapper/RAID holder detected; refusing.')
    for line in Path('/proc/swaps').read_text().splitlines()[1:]:
        # Swap files on the root filesystem are unsafe too. Stop swap before growth.
        require(False, 'Active swap detected. Disable swap before applying; no automatic swapoff.')


def confirmation(identity, plan, phase):
    payload = {**identity, 'uuid': plan['root_uuid'], 'target': plan['new_sectors'], 'phase': phase}
    return 'GROW-' + hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:20]


def verify_identity_record(path, identity, plan):
    require(path, 'Filesystem phase requires original --identity-file backup JSON.')
    record = json.loads(Path(path).read_text())
    require(isinstance(record, dict), 'Identity JSON must be an object.')
    expected = {key: identity[key] for key in ('cid', 'capacity_bytes')}
    expected.update({key: plan[key] for key in ('root_uuid', 'root_start', 'new_sectors')})
    require(record.get('schema') == 1, 'Unsupported/missing identity JSON schema.')
    require(all(type(record.get(key)) is type(value) and record.get(key) == value
                for key, value in expected.items()),
            'Original backup identity does not match this SD/CID/capacity/UUID/start/target.')


def save_backup(path, prefix, identity, plan):
    path = Path(path)
    require(not path.exists(), 'Backup exists. Refusing to overwrite it.')
    with path.open('xb') as out:
        os.chmod(path, 0o600)
        out.write(prefix)
        out.flush()
        os.fsync(out.fileno())
    metadata = {'schema': 1, **identity, **plan, 'sha256': hashlib.sha256(prefix).hexdigest(),
                'warning': 'Prefix only, not a complete data backup. Export both files off this SD.'}
    with Path(str(path) + '.json').open('x') as out:
        json.dump(metadata, out, indent=2)
        out.write('\n')
        out.flush()
        os.fsync(out.fileno())
    directory = os.open(str(path.parent), os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--device', required=True, help='Explicit whole SD path, never assumed from numbering')
    parser.add_argument('--phase', choices=['partition', 'filesystem'], default='partition')
    parser.add_argument('--mountpoint', default='/', help='Direct writable Btrfs system mount: / or /rom')
    parser.add_argument('--apply', action='store_true', help='Mutate only after all explicit confirmations')
    parser.add_argument('--confirm', help='Exact phase-specific token printed by preview')
    parser.add_argument('--identity-file', help='Original backup JSON required for filesystem phase')
    parser.add_argument('--backup-file', help='Existing verified 4MiB prefix backup for partition apply')
    parser.add_argument('--save-backup', help='Create prefix + JSON backup only; does not change partition table')
    parser.add_argument('--backup-exported', action='store_true', help='I copied backup off SD and made a data backup')
    parser.add_argument('--services-stopped', action='store_true', help='I stopped Docker, HA and other writing services')
    args = parser.parse_args()
    require(not (args.save_backup and args.apply), 'Backup creation and apply must be separate invocations.')
    device, node, st, identity = sd_identity(args.device)
    fd = os.open(device, os.O_RDWR if args.apply else os.O_RDONLY)
    try:
        require(os.fstat(fd).st_rdev == st.st_rdev, 'Device identity changed.')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        capacity = identity['capacity_bytes']
        prefix = read_at(fd, 0, PREFIX)
        superblock = read_at(fd, ROOT_START * SECTOR + 0x10000, 4096)
        plan, changed = layout(prefix[:512], capacity, read_at(fd, 8192 * SECTOR, 512), superblock,
                               read_at(fd, 512, 8), read_at(fd, capacity - 512, 8))
        kernel_sectors = kernel_geometry(node)
        require(ROOT_MIN <= kernel_sectors <= plan['old_sectors'],
                'Kernel/table disagree unexpectedly; reboot and inspect, no writes.')
        if changed != prefix[:512]:
            require(kernel_sectors == plan['old_sectors'],
                    'Pending partition change detected; reboot before any further change.')
        mountpoint, live_bytes = mounted_btrfs(args.mountpoint, device, plan['root_uuid'])
        require(0 < live_bytes <= kernel_sectors * SECTOR, 'Invalid live Btrfs device size.')
        plan['filesystem_bytes'] = live_bytes
        check_consumers(node)
        token = confirmation(identity, plan, args.phase)
        print(json.dumps({**identity, **plan, 'kernel_sectors': kernel_sectors,
                          'capacity_GiB': round(capacity / 1024**3, 3),
                          'phase': args.phase, 'confirm_token': token}, indent=2))
        if args.save_backup:
            require(args.phase == 'partition' and plan['old_sectors'] < plan['new_sectors'],
                    'Create the original backup before partition growth only.')
            save_backup(args.save_backup, prefix, identity, plan)
            print('Backup saved. Export .bin and .json to Windows; separately back up important data.')
            return
        if args.phase == 'partition' and changed == prefix[:512]:
            print('Partition already fills aligned SD space. No table write. Reboot if kernel size differs; then preview filesystem phase.')
            return
        if args.phase == 'filesystem':
            verify_identity_record(args.identity_file, identity, plan)
            require(plan['old_sectors'] == plan['new_sectors'], 'Run partition phase first.')
            require(kernel_sectors == plan['new_sectors'],
                    'REBOOT REQUIRED. Kernel still sees the old p2 size; filesystem growth refused.')
            if plan['target_bytes'] - plan['filesystem_bytes'] < 4096:
                print('Btrfs already fills partition. No action required.')
                return
        if not args.apply:
            print('PREVIEW ONLY. No writes. Review CID, capacity, UUID and phase before applying.')
            return
        require(os.geteuid() == 0, 'Root required for apply.')
        require(args.confirm == token, 'Missing/wrong confirmation token; preview again.')
        require(args.services_stopped, 'Explicit --services-stopped is required.')
        os.sync()
        # Revalidate all observable identity/layout inputs after sync, immediately before writing.
        require(sd_identity(device)[3] == identity, 'SD identity changed.')
        require(read_at(fd, 0, PREFIX) == prefix, 'Prefix changed during validation.')
        require(kernel_geometry(node) == kernel_sectors, 'Kernel partition changed during validation.')
        mounted_btrfs(mountpoint, device, plan['root_uuid'])
        check_consumers(node)
        if args.phase == 'partition':
            require(args.backup_exported and args.backup_file,
                    'Existing --backup-file and explicit --backup-exported required.')
            require(Path(args.backup_file).read_bytes() == prefix, 'Backup differs from current original prefix.')
            # Kernel retains old safe geometry. Never BLKRRPART/partprobe/partx here.
            # Aligned full-sector write; only p2 LBA length bytes differ. CHS stays unchanged.
            require(os.pwrite(fd, changed, 0) == SECTOR, 'Short MBR write: stop and recover from backup.')
            os.fsync(fd)
            require(read_at(fd, 0, SECTOR) == changed, 'MBR readback failed: do not continue.')
            print('MBR p2 length updated and read back. No filesystem change, no reread, no reboot performed.')
            print('Keep services stopped. Reboot normally now, then preview --phase filesystem.')
        else:
            subprocess.run(['btrfs', 'filesystem', 'resize', 'max', mountpoint], check=True)
            os.sync()
            # Query the mounted filesystem through btrfs ioctls. Do not trust the
            # whole-disk raw cache after writes through the partition device.
            _, grown = mounted_btrfs(mountpoint, device, plan['root_uuid'])
            require(0 <= plan['target_bytes'] - grown < 4096, 'Growth not verified; inspect btrfs filesystem usage.')
            print('Btrfs growth verified. UUID and p2 start preserved. No formatting or data migration.')
    finally:
        os.close(fd)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print('STOP: ' + str(error), file=sys.stderr)
        sys.exit(1)
