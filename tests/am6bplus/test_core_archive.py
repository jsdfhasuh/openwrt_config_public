import hashlib
import importlib.util
import io
from pathlib import Path
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('core_prepare', ROOT / 'scripts/am6bplus/prepare-source.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class TestSmartArchive(unittest.TestCase):
    def test_only_single_regular_aarch64_file(self):
        for name, symlink, machine, passes in [('clash',False,183,True), ('../clash',False,183,False), ('clash',True,183,False), ('clash',False,62,False)]:
            with self.subTest(name=name,symlink=symlink,machine=machine), tempfile.TemporaryDirectory() as directory:
                archive = Path(directory)/'core.tar.gz'
                data = bytearray(64)
                data[:6] = b'\x7fELF\x02\x01'
                data[18:20] = machine.to_bytes(2,'little')
                with tarfile.open(archive,'w:gz') as t:
                    info = tarfile.TarInfo(name)
                    if symlink:
                        info.type = tarfile.SYMTYPE
                        info.linkname = '/etc/passwd'
                        t.addfile(info)
                    else:
                        info.size = len(data)
                        t.addfile(info,io.BytesIO(data))
                locked={'format':'tar.gz','url':archive.as_uri(),'sha256':hashlib.sha256(archive.read_bytes()).hexdigest()}
                output=Path(directory)/'clash_meta'
                if passes:
                    self.assertEqual(module.install_core(locked,output),hashlib.sha256(data).hexdigest())
                    self.assertEqual(output.stat().st_mode & 0o777,0o755)
                else:
                    with self.assertRaises(ValueError):module.install_core(locked,output)
                    self.assertFalse(output.exists())
