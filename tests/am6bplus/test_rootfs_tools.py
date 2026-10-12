import importlib.util
import io
from pathlib import Path
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('tools_verify', ROOT / 'scripts/am6bplus/verify-rootfs-tools.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class TestRootfsTools(unittest.TestCase):
    def fixture(self, filename, bad_mode=False, bad_content=False, missing_pip=False):
        with tarfile.open(filename, 'w:gz') as archive:
            for name in ['usr/bin/python3', 'usr/bin/btrfs', 'usr/bin/docker', 'usr/bin/dockerd', 'etc/init.d/dockerd'] + ([] if missing_pip else ['usr/bin/pip3', 'usr/lib/python3.13/site-packages/pip/__init__.py']):
                info = tarfile.TarInfo('./' + name)
                info.mode = 0o755
                archive.addfile(info, io.BytesIO(b''))
            for target, source in [('usr/sbin/am6bplus-grow-sd', 'scripts/am6bplus/am6bplus-grow-sd.py'), ('usr/share/doc/am6bplus-grow-sd/README.zh-CN.md', 'docs/am6bplus/grow-sd/README.zh-CN.md')]:
                data = (ROOT / source).read_bytes()
                if bad_content: data += b'changed'
                info = tarfile.TarInfo('./' + target)
                info.size = len(data)
                info.mode = 0o644 if bad_mode else 0o755
                archive.addfile(info, io.BytesIO(data))

    def test_actual_archive_checks(self):
        for failure in [None, 'bad_mode', 'bad_content', 'missing_pip']:
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                filename = Path(directory) / 'rootfs.tar.gz'
                self.fixture(filename, **({failure:True} if failure else {}))
                if failure:
                    with self.assertRaises(ValueError): module.verify(filename)
                else: module.verify(filename)
