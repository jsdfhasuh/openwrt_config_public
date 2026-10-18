import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('finish_packit', ROOT / 'scripts/am6bplus/finish-packit-rootfs.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class TestPackitModules(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.kernel = '6.6.124-flippy-94+'
        self.modules = self.root / 'lib/modules' / self.kernel
        self.modules.mkdir(parents=True)
        for name in module.MODULES:
            if name != 'tun':
                (self.modules / f'{name}.ko').touch()
        (self.modules / 'modules.builtin').write_text('kernel/drivers/net/tun.ko\n')
        self.firmware = self.root / 'lib/firmware/rtl_nic/rtl8153b-2.fw'
        self.firmware.parent.mkdir(parents=True)
        self.firmware.write_bytes(b'firmware-fixture')
        for name in ['modules.d', 'modules-boot.d']:
            directory = self.root / 'etc' / name
            directory.mkdir(parents=True)
            (directory / 'old-armsr').write_text('old_driver\n')
        patcher = patch.object(module.subprocess, 'run')
        self.depmod = patcher.start()
        self.addCleanup(patcher.stop)

    def test_r8152_is_in_generated_boot_list(self):
        module.configure_modules(self.root, self.kernel)
        lines = (self.root / 'etc/modules.d/20-am6bplus').read_text().splitlines()
        self.assertEqual(lines.count('r8152'), 1)
        self.assertIn('tun', lines)
        self.assertIn('USB_RTL8152', module.REQUIRED)
        for name in ['modules.d', 'modules-boot.d']:
            self.assertEqual((self.root / 'etc' / f'{name}.armsr-disabled/old-armsr').read_text(),
                             'old_driver\n')
            self.assertFalse((self.root / 'etc' / name / 'old-armsr').exists())
        self.depmod.assert_called_once_with(['depmod', '-b', str(self.root), self.kernel], check=True)

    def test_missing_driver_fails_before_replacing_autoload(self):
        (self.modules / 'r8152.ko').unlink()
        with self.assertRaisesRegex(SystemExit, 'Missing selected modules:.*r8152'):
            module.configure_modules(self.root, self.kernel)
        self.assert_original_autoload()

    def test_missing_firmware_fails_before_replacing_autoload(self):
        self.firmware.unlink()
        with self.assertRaisesRegex(SystemExit, 'RTL8153B firmware missing'):
            module.configure_modules(self.root, self.kernel)
        self.assert_original_autoload()

    def test_builtin_r8152_is_supported(self):
        (self.modules / 'r8152.ko').unlink()
        (self.modules / 'modules.builtin').write_text('kernel/drivers/net/tun.ko\nkernel/drivers/net/usb/r8152.ko\n')
        module.configure_modules(self.root, self.kernel)
        self.assertIn('r8152', (self.root / 'etc/modules.d/20-am6bplus').read_text().splitlines())

    def test_repeated_adaptation_is_rejected(self):
        module.configure_modules(self.root, self.kernel)
        with self.assertRaisesRegex(SystemExit, 'Duplicate adaptation'):
            module.configure_modules(self.root, self.kernel)

    def assert_original_autoload(self):
        for name in ['modules.d', 'modules-boot.d']:
            self.assertEqual((self.root / 'etc' / name / 'old-armsr').read_text(), 'old_driver\n')
            self.assertFalse((self.root / 'etc' / f'{name}.armsr-disabled').exists())
        self.depmod.assert_not_called()


if __name__ == '__main__':
    unittest.main()
