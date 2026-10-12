import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts/am6bplus' / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestConfiguration(unittest.TestCase):
    def test_all_sources_are_pinned(self):
        lock = json.loads((ROOT / 'configs/am6bplus/sources.lock.json').read_text())
        specs = [lock['openwrt'], *lock['feeds'].values(), *lock['plugins'].values()]
        for spec in specs:
            self.assertRegex(spec['commit'], r'^[a-f0-9]{40}$')
            self.assertTrue(spec['url'].startswith('https://github.com/'))

    def test_config_rejects_silently_dropped_package(self):
        module = load('verify-config')
        seed = (ROOT / 'configs/am6bplus/seed.config').read_text() + '\nCONFIG_USE_APK=y\n'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '.config'
            path.write_text(seed)
            module.verify(path)
            path.write_text(seed.replace('CONFIG_PACKAGE_block-mount=y', '# CONFIG_PACKAGE_block-mount is not set'))
            with self.assertRaisesRegex(ValueError, 'block-mount'):
                module.verify(path)

    def test_core_rejects_wrong_hash(self):
        module = load('prepare-source')
        data = gzip.compress(b'bad')
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'core.gz'
            source.write_bytes(data)
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                module.install_core({'url': source.as_uri(), 'sha256': '0' * 64}, Path(directory) / 'core')

    def test_core_rejects_x86_and_accepts_aarch64_header_without_execution(self):
        module = load('prepare-source')
        for machine in (62, 183):
            header = bytearray(64)
            header[:6] = b'\x7fELF\x02\x01'
            struct.pack_into('<H', header, 18, machine)
            data = gzip.compress(header)
            with tempfile.TemporaryDirectory() as directory:
                source, output = Path(directory) / 'core.gz', Path(directory) / 'core'
                source.write_bytes(data)
                spec = {'url': source.as_uri(), 'sha256': hashlib.sha256(data).hexdigest()}
                if machine == 62:
                    with self.assertRaisesRegex(ValueError, 'AArch64'):
                        module.install_core(spec, output)
                else:
                    module.install_core(spec, output)
                    self.assertEqual(output.read_bytes(), header)

    def test_existing_checkout_is_never_overwritten(self):
        module = load('prepare-source')
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, 'existing checkout'):
                module.checkout({}, Path(directory))


if __name__ == '__main__':
    unittest.main()

class TestArtifactIdentity(unittest.TestCase):
    def test_wrong_repository_is_rejected(self):
        module = load('build-artifact')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path/'build-manifest.json').write_text('{}')
            (path/'run.json').write_text(json.dumps({'repository': {'full_name': 'someone/fork'}}))
            with patch.dict('os.environ', {'GITHUB_REPOSITORY':'jsdfhasuh/openwrt_config_public'}):
                with self.assertRaisesRegex(ValueError, 'Foreign/fork'):
                    module.verify(path, path/'run.json')

    def test_source_pr_is_rejected(self):
        module = load('build-artifact')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path/'build-manifest.json').write_text('{}')
            repo = {'full_name':'jsdfhasuh/openwrt_config_public'}
            (path/'run.json').write_text(json.dumps({'repository':repo, 'head_repository':repo, 'event':'pull_request', 'head_branch':'main'}))
            with patch.dict('os.environ', {'GITHUB_REPOSITORY':repo['full_name']}):
                with self.assertRaisesRegex(ValueError, 'main push/manual'):
                    module.verify(path, path/'run.json')
