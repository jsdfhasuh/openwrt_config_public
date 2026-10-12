#!/usr/bin/env python3
"""Synthetic sparse-file tests. Never opens a block device; not a hardware/loop test."""
import importlib.util
from pathlib import Path
import os
import stat
import struct
import tempfile
import unittest
import uuid
from unittest.mock import patch
from contextlib import ExitStack, redirect_stdout
import io
import json
from types import SimpleNamespace

spec = importlib.util.spec_from_file_location('grow', Path(__file__).resolve().parents[2] / 'scripts/am6bplus/am6bplus-grow-sd.py')
grow = importlib.util.module_from_spec(spec)
spec.loader.exec_module(grow)


def fixture():
    mbr = bytearray(512)
    mbr[:440] = bytes(i % 251 for i in range(440))
    mbr[440:444] = bytes.fromhex('71fc998f')
    for index, kind, start, size in [(0, 12, 8192, 786432), (1, 131, 794624, 6291456)]:
        offset = 446 + index * 16
        mbr[offset+4] = kind
        struct.pack_into('<II', mbr, offset+8, start, size)
    mbr[510:] = b'\x55\xaa'
    fat = bytearray(512)
    fat[82:90] = b'FAT32   '
    fat[510:] = b'\x55\xaa'
    sb = bytearray(4096)
    sb[0x40:0x48] = b'_BHRfS_M'
    sb[0x20:0x30] = uuid.UUID('38d05fd0-4c19-4d24-a340-c96501312a03').bytes
    struct.pack_into('<QQQQ', sb, 0x70, 3072*1024**2, 1024**3, 6, 1)
    return mbr, fat, sb


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.mbr, self.fat, self.sb = fixture()
        self.capacity = 128_000_000_000

    def plan(self, **kw):
        return grow.layout(kw.get('mbr', self.mbr), kw.get('capacity', self.capacity),
                           kw.get('fat', self.fat), kw.get('sb', self.sb),
                           kw.get('primary', b''), kw.get('backup', b''))

    def test_expected_128gb_capacity_and_only_length_changes(self):
        plan, new = self.plan()
        self.assertEqual(plan['new_sectors'], 249204736)
        self.assertEqual(plan['target_bytes'], 127592824832)
        self.assertEqual(new[:grow.SIZE_OFFSET], self.mbr[:grow.SIZE_OFFSET])
        self.assertEqual(new[grow.SIZE_OFFSET+4:], self.mbr[grow.SIZE_OFFSET+4:])
        self.assertEqual(plan['root_uuid'], '38d05fd0-4c19-4d24-a340-c96501312a03')

    def test_idempotent_partition(self):
        _, new = self.plan()
        plan2, new2 = self.plan(mbr=new)
        self.assertEqual(new, new2)
        self.assertEqual(plan2['old_sectors'], plan2['new_sectors'])

    def test_third_partition_rejected(self):
        self.mbr[478+4] = 131
        with self.assertRaises(ValueError): self.plan()

    def test_fourth_partition_residue_rejected(self):
        self.mbr[494] = 1
        with self.assertRaises(ValueError): self.plan()

    def test_wrong_start_rejected(self):
        struct.pack_into('<I', self.mbr, 470, grow.ROOT_START + 1)
        with self.assertRaises(ValueError): self.plan()

    def test_wrong_boot_size_rejected(self):
        struct.pack_into('<I', self.mbr, 458, 123)
        with self.assertRaises(ValueError): self.plan()

    def test_gpt_rejected(self):
        for field in ['primary', 'backup']:
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.plan(**{field: b'EFI PART'})

    def test_multiple_btrfs_devices_rejected(self):
        struct.pack_into('<Q', self.sb, 0x88, 2)
        with self.assertRaises(ValueError): self.plan()

    def test_filesystem_over_partition_rejected(self):
        struct.pack_into('<Q', self.sb, 0x70, 4000*1024**2)
        with self.assertRaises(ValueError): self.plan()

    def test_short_or_corrupt_signatures_rejected(self):
        for kwargs in [dict(mbr=b'x'), dict(fat=b'x'*512), dict(sb=b'x'*4096)]:
            with self.subTest(kwargs=list(kwargs)), self.assertRaises(ValueError): self.plan(**kwargs)

    def test_shrink_rejected(self):
        with self.assertRaises(ValueError): self.plan(capacity=2*1024**3)

    def test_unsupported_sector_capacity_rejected(self):
        for size in [128000000001, 3*1024**4]:
            with self.subTest(size=size), self.assertRaises(ValueError): self.plan(capacity=size)

    def test_confirmation_bound_to_card_size_uuid_phase(self):
        plan, _ = self.plan()
        ident = dict(device='/dev/mmcblk2', cid='a'*32, capacity_bytes=self.capacity)
        base = grow.confirmation(ident, plan, 'partition')
        self.assertNotEqual(base, grow.confirmation(ident, plan, 'filesystem'))
        self.assertNotEqual(base, grow.confirmation({**ident, 'cid':'b'*32}, plan, 'partition'))
        self.assertNotEqual(base, grow.confirmation(ident, {**plan, 'root_uuid':'different'}, 'partition'))

    def test_regular_file_refused_by_production_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'mmcblk0'; p.touch()
            with self.assertRaisesRegex(ValueError, 'block device'): grow.sd_identity(p)

    def test_backup_readback_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'prefix.bin'
            data = bytes(self.mbr) + bytes(grow.PREFIX-512)
            grow.save_backup(p, data, {'cid':'a'*32}, {})
            self.assertEqual(p.read_bytes(), data)
            self.assertTrue(Path(str(p)+'.json').exists())
            with self.assertRaises(ValueError): grow.save_backup(p, data, {}, {})

    def test_sparse_128gb_file_preserves_sentinels_and_idempotence(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'simulated-sd.img'
            with p.open('w+b') as f:
                f.truncate(self.capacity)
                fd = f.fileno()
                for offset, data in [(0,self.mbr), (8192*512,self.fat),
                                     (grow.ROOT_START*512+65536,self.sb),
                                     (3*1024**3,b'EXISTING USER DATA'),
                                     (self.capacity-4096,b'TAIL SENTINEL')]:
                    os.pwrite(fd, data, offset)
                before_sb = os.pread(fd, 4096, grow.ROOT_START*512+65536)
                plan, changed = self.plan()
                os.pwrite(fd, changed, 0); os.fsync(fd)
                self.assertEqual(os.pread(fd,512,0), changed)
                self.assertEqual(os.pread(fd,18,3*1024**3), b'EXISTING USER DATA')
                self.assertEqual(os.pread(fd,13,self.capacity-4096), b'TAIL SENTINEL')
                self.assertEqual(os.pread(fd,4096,grow.ROOT_START*512+65536), before_sb)
                self.assertEqual(self.plan(mbr=os.pread(fd,512,0))[1], changed)


class LifecycleTests(unittest.TestCase):
    """Mock SD/sysfs/mount checks; exercise production control flow on sparse file only."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.device = Path(self.tmp.name) / 'simulated-sd.img'
        self.backup = Path(self.tmp.name) / 'prefix.bin'
        self.mbr, self.fat, self.sb = fixture()
        with self.device.open('w+b') as f:
            f.truncate(128000000000)
            os.pwrite(f.fileno(), self.mbr, 0)
            os.pwrite(f.fileno(), self.fat, 8192*512)
            os.pwrite(f.fileno(), self.sb, grow.ROOT_START*512+65536)
        self.ident = dict(device=str(self.device), cid='a'*32, capacity_bytes=128000000000, name='TEST')
        self.plan, self.changed = grow.layout(self.mbr,128000000000,self.fat,self.sb)
        self.record=Path(self.tmp.name)/'prefix.bin.json'
        self.record.write_text(json.dumps({'schema':1,**self.ident,**self.plan}))
        with self.device.open('rb') as f: self.backup.write_bytes(f.read(grow.PREFIX))
        self.kernel = grow.ROOT_MIN
        self.live_bytes = grow.ROOT_MIN * 512
        self.stack = ExitStack()
        self.stack.enter_context(patch.object(grow, 'sd_identity', return_value=(self.device, Path('/unused'), SimpleNamespace(st_rdev=0), self.ident)))
        self.stack.enter_context(patch.object(grow, 'kernel_geometry', side_effect=lambda _:self.kernel))
        self.stack.enter_context(patch.object(grow, 'mounted_btrfs', side_effect=lambda *args: ('/', self.live_bytes)))
        self.stack.enter_context(patch.object(grow, 'check_consumers'))
        self.stack.enter_context(patch.object(grow.os, 'geteuid', return_value=0))
        self.stack.enter_context(patch.object(grow.os, 'sync'))
        self.command = self.stack.enter_context(patch.object(grow.subprocess, 'run'))

    def tearDown(self):
        self.stack.close(); self.tmp.cleanup()

    def run_main(self, *args):
        out = io.StringIO()
        with patch.object(grow.sys,'argv',['grow','--device',str(self.device),*args]), redirect_stdout(out): grow.main()
        return out.getvalue()

    def apply_partition(self):
        token = grow.confirmation(self.ident,self.plan,'partition')
        return self.run_main('--apply','--confirm',token,'--services-stopped','--backup-exported','--backup-file',str(self.backup))

    def test_preview_writes_nothing(self):
        self.assertIn('PREVIEW ONLY',self.run_main())
        with self.device.open('rb') as f: self.assertEqual(f.read(grow.PREFIX),self.backup.read_bytes())
        self.command.assert_not_called()

    def test_missing_confirmation_writes_nothing(self):
        with self.assertRaises(ValueError): self.run_main('--apply')
        with self.device.open('rb') as f: self.assertEqual(f.read(512), self.mbr)

    def test_wrong_backup_writes_nothing(self):
        self.backup.write_bytes(b'wrong')
        with self.assertRaises(ValueError): self.apply_partition()
        with self.device.open('rb') as f: self.assertEqual(f.read(512), self.mbr)

    def test_partition_apply_does_not_resize_or_reread(self):
        self.assertIn('No filesystem change',self.apply_partition())
        self.command.assert_not_called()
        with self.device.open('rb') as f:
            self.assertEqual(f.read(512),self.changed)
            f.seek(grow.ROOT_START*512+65536); self.assertEqual(f.read(4096),self.sb)
        self.assertIn('No table write',self.run_main())

    def test_filesystem_refuses_before_reboot(self):
        self.apply_partition()
        with self.assertRaisesRegex(ValueError,'REBOOT REQUIRED'): self.run_main('--phase','filesystem','--identity-file',str(self.record))
        self.command.assert_not_called()

    def test_filesystem_requires_confirmation_after_reboot(self):
        self.apply_partition(); self.kernel=self.plan['new_sectors']
        self.assertIn('PREVIEW ONLY',self.run_main('--phase','filesystem','--identity-file',str(self.record)))
        self.command.assert_not_called()
        with self.assertRaises(ValueError): self.run_main('--phase','filesystem','--identity-file',str(self.record),'--apply')
        self.command.assert_not_called()

    def test_identity_card_swap_rejected(self):
        self.apply_partition();self.kernel=self.plan['new_sectors']
        self.ident['cid']='b'*32
        with self.assertRaisesRegex(ValueError,'does not match'):
            self.run_main('--phase','filesystem','--identity-file',str(self.record))
        self.command.assert_not_called()

    def test_identity_corrupt_json_rejected(self):
        self.apply_partition();self.kernel=self.plan['new_sectors']
        self.record.write_text('{corrupt')
        with self.assertRaises(ValueError):
            self.run_main('--phase','filesystem','--identity-file',str(self.record))
        self.command.assert_not_called()

    def test_identity_missing_rejected(self):
        self.apply_partition();self.kernel=self.plan['new_sectors']
        with self.assertRaisesRegex(ValueError,'requires original'):
            self.run_main('--phase','filesystem')
        self.command.assert_not_called()

    def test_identity_each_bound_field_rejected(self):
        record=json.loads(self.record.read_text())
        for key in ['capacity_bytes','root_uuid','root_start','new_sectors']:
            bad={**record,key:'mismatch'};self.record.write_text(json.dumps(bad))
            with self.subTest(key=key),self.assertRaises(ValueError):
                grow.verify_identity_record(self.record,self.ident,self.plan)
        self.command.assert_not_called()

    def test_simulated_resize_and_repeat(self):
        self.apply_partition(); self.kernel=self.plan['new_sectors']
        def resize(*args, **kwargs):
            self.assertEqual(args[0],['btrfs','filesystem','resize','max','/'])
            self.live_bytes = self.plan['target_bytes']
            with self.device.open('r+b') as f:
                os.pwrite(f.fileno(),struct.pack('<Q',self.plan['target_bytes']),grow.ROOT_START*512+65536+0x70)
        self.command.side_effect=resize
        token=grow.confirmation(self.ident,self.plan,'filesystem')
        result=self.run_main('--phase','filesystem','--identity-file',str(self.record),'--apply','--confirm',token,'--services-stopped')
        self.assertIn('growth verified',result)
        self.command.assert_called_once()
        self.command.reset_mock()
        self.assertIn('No action required',self.run_main('--phase','filesystem','--identity-file',str(self.record)))
        self.command.assert_not_called()


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.base=Path(self.tmp.name)
        self.device=self.base/'mmcblk2';self.device.touch()
        self.part=Path(str(self.device)+'p2');self.part.touch()
        self.alias=self.base/'root';self.alias.touch()
        self.sys=self.base/'sys';self.sys.mkdir()
        self.node=self.sys/'mmcblk2';self.node.mkdir()
        for rel,value in {'dev':'179:64','device/type':'SD','device/cid':'a'*32,
                          'device/name':'TEST','queue/logical_block_size':'512',
                          'ro':'0','size':'250000000','mmcblk2p1/start':'8192',
                          'mmcblk2p1/size':'786432','mmcblk2p1/partition':'1',
                          'mmcblk2p2/start':'794624','mmcblk2p2/size':'6291456',
                          'mmcblk2p2/partition':'2','mmcblk2p2/dev':'179:66'}.items():
            path=self.node/rel;path.parent.mkdir(exist_ok=True,parents=True);path.write_text(value)
        self.mountinfo=self.base/'mountinfo';self.mountinfo.write_text('41 1 0:31 / / rw,relatime - btrfs /dev/root rw\n')
        self.uuid='38d05fd0-4c19-4d24-a340-c96501312a03'
        self.show=f"Label: 'ROOTFS'  uuid: {self.uuid}\n    Total devices 1 FS bytes used 100\n    devid    1 size 3221225472 used 100 path {self.alias}\n"
        self.rdev=os.makedev(179,64)
        self.stack=ExitStack()
        oldstat=Path.stat
        def fake_stat(path,*args,**kwargs):
            if path==self.device:return SimpleNamespace(st_mode=stat.S_IFBLK,st_rdev=self.rdev)
            if path in (self.part,self.alias):return SimpleNamespace(st_mode=stat.S_IFBLK,st_rdev=os.makedev(179,66))
            return oldstat(path,*args,**kwargs)
        self.stack.enter_context(patch.object(Path,'stat',fake_stat))
        def path_factory(value):
            if str(value)=='/sys/class/block':return self.sys
            if str(value)=='/proc/self/mountinfo':return self.mountinfo
            return Path(value)
        self.stack.enter_context(patch.object(grow,'Path',side_effect=path_factory))
        self.stack.enter_context(patch.object(grow.subprocess,'run',side_effect=lambda *a,**kw:SimpleNamespace(stdout=self.show)))

    def tearDown(self):self.stack.close();self.tmp.cleanup()

    def test_native_sd_identity(self):
        self.assertEqual(grow.sd_identity(self.device)[3]['cid'],'a'*32)

    def test_emmc_refused(self):
        (self.node/'device/type').write_text('MMC')
        with self.assertRaisesRegex(ValueError,'eMMC'):grow.sd_identity(self.device)

    def test_misnamed_block_node_refused(self):
        self.rdev=os.makedev(179,0)
        with self.assertRaisesRegex(ValueError,'sysfs identity'):grow.sd_identity(self.device)

    def test_missing_cid_refused(self):
        (self.node/'device/cid').write_text('')
        with self.assertRaisesRegex(ValueError,'CID'):grow.sd_identity(self.device)

    def test_kernel_boot_geometry_refused(self):
        (self.node/'mmcblk2p1/size').write_text('123')
        with self.assertRaisesRegex(ValueError,'boot geometry'):grow.kernel_geometry(self.node)

    def test_btrfs_root_block_alias_accepted(self):
        self.assertEqual(grow.mounted_btrfs('/',self.device,self.uuid),('/',3221225472))

    def test_btrfs_devid_other_than_one_refused(self):
        self.show=self.show.replace('devid    1','devid    2')
        with self.assertRaisesRegex(ValueError,'devid=1'):grow.mounted_btrfs('/',self.device,self.uuid)

    def test_btrfs_wrong_device_refused(self):
        (self.node/'mmcblk2p2/dev').write_text('179:2')
        with self.assertRaisesRegex(ValueError,'exclusively'):grow.mounted_btrfs('/',self.device,self.uuid)

    def test_btrfs_readonly_refused(self):
        self.mountinfo.write_text('41 1 0:31 / / ro,relatime - btrfs /dev/root ro\n')
        with self.assertRaisesRegex(ValueError,'not writable'):grow.mounted_btrfs('/',self.device,self.uuid)


if __name__ == '__main__': unittest.main(verbosity=2)
