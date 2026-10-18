import importlib.util
import io
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import hashlib

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('tools_verify', ROOT / 'scripts/am6bplus/verify-rootfs-tools.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class TestRootfsTools(unittest.TestCase):
    def fixture(self, filename, bad_mode=False, bad_content=False, missing_pip=False,
                bad_v2dat=False, missing_temperature=False):
        with tarfile.open(filename, 'w:gz') as archive:
            tools = [name for name in module.REQUIRED_TOOLS if name != 'usr/bin/v2dat'
                     and not (missing_pip and name == 'usr/bin/pip3')]
            tools += [f'usr/lib/python3.13/site-packages/{name}/__init__.py'
                      for name in module.PYTHON_MODULES if not (missing_pip and name == 'pip')]
            for name in tools:
                info = tarfile.TarInfo('./' + name)
                info.mode = 0o755
                archive.addfile(info, io.BytesIO(b''))
            data = bytearray(64)
            data[:6] = b'\x7fELF\x02\x01'
            data[18:20] = bytes([183, 0])
            info = tarfile.TarInfo('./etc/openclash/core/clash_meta')
            info.size = len(data)
            info.mode = 0o755
            archive.addfile(info, io.BytesIO(data))
            v2dat = bytearray(data)
            if bad_v2dat:
                v2dat[18:20] = bytes([62, 0])
            info = tarfile.TarInfo('./usr/bin/v2dat')
            info.mode = 0o755
            info.size = len(v2dat)
            archive.addfile(info, io.BytesIO(v2dat))
            for path in module.OVERLAY.rglob('*'):
                if not path.is_file() or (missing_temperature and path.suffix == '.js'):
                    continue
                content = path.read_bytes()
                info = tarfile.TarInfo('./' + path.relative_to(module.OVERLAY).as_posix())
                info.size = len(content)
                info.mode = 0o644
                archive.addfile(info, io.BytesIO(content))
            for target, source in [('usr/sbin/am6bplus-grow-sd', 'scripts/am6bplus/am6bplus-grow-sd.py'), ('usr/share/doc/am6bplus-grow-sd/README.zh-CN.md', 'docs/am6bplus/grow-sd/README.zh-CN.md')]:
                data = (ROOT / source).read_bytes()
                if bad_content: data += b'changed'
                info = tarfile.TarInfo('./' + target)
                info.size = len(data)
                info.mode = 0o644 if bad_mode else 0o755
                archive.addfile(info, io.BytesIO(data))

    def test_actual_archive_checks(self):
        for failure in [None, 'bad_mode', 'bad_content', 'missing_pip', 'bad_v2dat', 'missing_temperature']:
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                filename = Path(directory) / 'rootfs.tar.gz'
                self.fixture(filename, **({failure:True} if failure else {}))
                binary = bytearray(64)
                binary[:6] = b'\x7fELF\x02\x01'
                binary[18:20] = bytes([183, 0])
                expected = {'binary_sha256': hashlib.sha256(binary).hexdigest()}
                (filename.parent / 'resolved-core.json').write_text('{}')
                with patch.object(module.json, 'loads', return_value=expected):
                    if failure:
                        with self.assertRaises(ValueError): module.verify(filename)
                    else:
                        module.verify(filename)
