#!/usr/bin/env python3
"""Unprivileged tests for pinned packit adaptation; never builds or mounts images."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
UPSTREAM = Path(sys.argv.pop(1)).resolve() if len(sys.argv) > 1 and not sys.argv[1].startswith('-') else None
spec = importlib.util.spec_from_file_location('prepare_packit', HERE / 'prepare-packit.py')
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)


class ExactPatchTests(unittest.TestCase):
    def test_context_must_exist(self):
        with self.assertRaises(ValueError):
            prepare.exact('actual', 'missing', 'replacement')

    def test_duplicate_context_rejected(self):
        with self.assertRaises(ValueError):
            prepare.exact('same same', 'same', 'replacement')

    def test_runtime_refuses_non_runner(self):
        env = os.environ.copy()
        env['AM6BPLUS_GITHUB_RUNNER'] = '0'
        result = subprocess.run(['bash', '-c', 'source "$1"; am6_require_runner',
                                 'test', str(HERE / 'packit-runtime.sh')],
                                env=env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('GitHub-hosted', result.stderr)

    def test_cleanup_only_registered_loop_and_mounts(self):
        script = r'''
source "$1"
AM6_OWNED_LOOP=/dev/loop987
AM6_OWNED_IMAGE=/tmp/mock-image.img
AM6_OWNED_MOUNTS=(/tmp/mock-boot /tmp/mock-root)
mountpoint() { return 0; }
findmnt() { case "$*" in *mock-boot*) echo /dev/loop987p1;; *) echo /dev/loop987p2;; esac; }
am6_assert_device() { return 0; }
umount() { printf 'UNMOUNT %s\n' "$*"; }
losetup() { printf 'LOOP %s\n' "$*"; }
am6_cleanup_owned || exit 1
[[ -z $AM6_OWNED_LOOP && ${#AM6_OWNED_MOUNTS[@]} == 0 ]]
'''
        result = subprocess.run(['bash', '-c', script, 'test', str(HERE / 'packit-runtime.sh')],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ['UNMOUNT -- /tmp/mock-root',
                         'UNMOUNT -- /tmp/mock-boot', 'LOOP --detach /dev/loop987'])

    def test_cleanup_refuses_unexpected_mount(self):
        script = r'''
source "$1"
AM6_OWNED_LOOP=/dev/loop987
AM6_OWNED_MOUNTS=(/tmp/mock-root)
mountpoint() { return 0; }
findmnt() { echo /dev/unrelated; }
umount() { echo SHOULD_NOT_UNMOUNT; }
losetup() { echo SHOULD_NOT_DETACH; }
am6_cleanup_owned
'''
        result = subprocess.run(['bash', '-c', script, 'test', str(HERE / 'packit-runtime.sh')],
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('SHOULD_NOT_', result.stdout)


@unittest.skipUnless(UPSTREAM is not None, 'Pass pinned packit checkout path for upstream adaptation tests')
class PinnedUpstreamTests(unittest.TestCase):
    def setUp(self):
        for name, digest in prepare.ORIGINAL_SHA256.items():
            self.assertEqual(prepare.sha256(UPSTREAM / name), digest)
        self.original = (UPSTREAM / 'public_funcs').read_text()
        self.functions = prepare.adapt_functions(self.original)
        self.entry = prepare.adapt_entry((UPSTREAM / 'mk_s922x_gtking.sh').read_text())

    def test_pinned_original_core_is_really_retained(self):
        for name in ['create_partition', 'make_filesystem', 'extract_rootfs_files',
                     'extract_amlogic_boot_files', 'create_fstab_config']:
            self.assertEqual(prepare.function_body(self.original, name),
                             prepare.function_body(self.functions, name))
            self.assertIn(name, self.entry)

    def test_transformed_shell_syntax(self):
        for text in [self.functions, self.entry]:
            result = subprocess.run(['bash', '-n'], input=text, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_no_global_device_cleanup(self):
        self.assertNotIn('losetup -D', self.functions)
        self.assertNotIn('umount -f *', self.functions)
        self.assertIn('AM6_OWNED_LOOP=$(losetup --find --show --partscan', self.functions)
        self.assertIn('AM6_OWNED_MOUNTS+=("$mount_point")', self.functions)

    def test_guard_precedes_image_write(self):
        body = prepare.function_body(self.functions, 'create_image')
        self.assertLess(body.index('! -e "$img_name"'), body.index('dd if=/dev/zero'))

    def test_board_boot_and_native_btrfs_layout(self):
        self.assertIn('SKIP_MB=4\nBOOT_MB=384\nROOTFS_MB=3072', self.entry)
        self.assertIn('\nFDT=/dtb/amlogic/meson-g12b-ugoos-am6.dtb\n', self.entry)
        self.assertNotIn('\nFDT=/dtb/amlogic/meson-g12b-gtking-pro.dtb\n', self.entry)
        self.assertIn('rootfstype=btrfs', self.entry)
        self.assertIn('btrfs subvolume create "$TGT_ROOT/etc" || exit 1', self.entry)
        self.assertIn('UBOOT_WITHOUT_FIP="u-boot-gtkingpro.bin"', self.entry)

    def test_invasive_calls_not_executed(self):
        forbidden = {'copy_supplement_files', 'extract_glibc_programs', 'config_first_run',
                     'copy_uboot_to_fs', 'write_uboot_to_disk', 'adjust_openssh_config',
                     'adjust_ntfs_config', 'adjust_kernel_env', 'adjust_samba_config'}
        self.assertFalse(forbidden & set(self.entry.splitlines()))
        self.assertIn('finish-packit-rootfs.py', self.entry)

    def test_already_adapted_source_fails_closed(self):
        with self.assertRaises(ValueError):
            prepare.adapt_functions(self.functions)
        with self.assertRaises(ValueError):
            prepare.adapt_entry(self.entry)


if __name__ == '__main__':
    unittest.main(verbosity=2)
