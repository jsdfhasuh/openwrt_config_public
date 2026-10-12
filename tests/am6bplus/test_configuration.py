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


def resolved_core():
    core = json.loads((ROOT / 'configs/am6bplus/sources.lock.json').read_text())['openclash_core'].copy()
    core.update(schema=1, resolution_mode='latest', checksums_sha256='b' * 64,
                checksums_url=f"https://raw.githubusercontent.com/vernesong/OpenClash/{core['commit']}/dev/smart/checksums.txt")
    return core


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


class TestArtifactCollection(unittest.TestCase):
    def test_two_real_openwrt_output_names_select_canonical(self):
        module = load('build-artifact')
        with tempfile.TemporaryDirectory() as directory:
            build = Path(directory) / 'build'
            target = build / 'bin/targets/armsr/armv8'
            target.mkdir(parents=True)
            (target / module.ROOTFS_NAME).write_bytes(b'canonical-rootfs')
            (target / 'openwrt-armsr-armv8-generic-targz-rootfs.tar.gz').write_bytes(b'device-image')
            (build / '.config').write_text('CONFIG_USE_APK=y\n')
            (build / 'resolved-core.json').write_text(json.dumps(resolved_core()))
            output = Path(directory) / 'output'
            env = {'GITHUB_REPOSITORY': 'jsdfhasuh/openwrt_config_public',
                   'GITHUB_SHA': 'a' * 40, 'GITHUB_WORKFLOW': module.WORKFLOW,
                   'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1'}
            with patch.dict('os.environ', env):
                module.create(build, output)
            self.assertEqual((output / module.ROOTFS_NAME).read_bytes(), b'canonical-rootfs')
            manifest = json.loads((output / 'build-manifest.json').read_text())
            self.assertEqual(manifest['run_id'], 123)
            self.assertEqual(manifest['schema'], 2)
            self.assertEqual(json.loads((output / 'resolved-core.json').read_text()), resolved_core())
            self.assertEqual(manifest['files']['resolved-core.json']['sha256'],
                             module.digest(output / 'resolved-core.json'))
            self.assertEqual(manifest['files'][module.ROOTFS_NAME]['sha256'],
                             hashlib.sha256(b'canonical-rootfs').hexdigest())

    def test_alternate_name_does_not_substitute_for_missing_canonical(self):
        module = load('build-artifact')
        with tempfile.TemporaryDirectory() as directory:
            build = Path(directory) / 'build'
            target = build / 'bin/targets/armsr/armv8'
            target.mkdir(parents=True)
            (target / 'openwrt-armsr-armv8-generic-targz-rootfs.tar.gz').write_bytes(b'other')
            with self.assertRaisesRegex(ValueError, 'Missing canonical'):
                module.create(build, Path(directory) / 'output')


class TestResolvedCoreArtifact(unittest.TestCase):
    def setUp(self):
        self.module = load('build-artifact')
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name)
        self.build = self.path / 'build'
        target = self.build / 'bin/targets/armsr/armv8'
        target.mkdir(parents=True)
        (target / self.module.ROOTFS_NAME).write_bytes(b'rootfs')
        (target / 'packages.manifest').write_text('package - 1.0\n')
        (self.build / '.config').write_text('CONFIG_USE_APK=y\n')
        (self.build / 'resolved-core.json').write_text(json.dumps(resolved_core()))
        self.output = self.path / 'output'
        repo = {'full_name': 'jsdfhasuh/openwrt_config_public'}
        self.run_file = self.path / 'run.json'
        self.run_file.write_text(json.dumps({
            'repository': repo, 'head_repository': repo, 'event': 'push', 'head_branch': 'main',
            'name': self.module.WORKFLOW, 'path': '.github/workflows/openwrt_am6bplus_25_12.yml',
            'status': 'completed', 'conclusion': 'success', 'head_sha': 'a' * 40,
            'id': 123, 'run_attempt': 1}))
        patcher = patch.dict('os.environ', {
            'GITHUB_REPOSITORY': repo['full_name'], 'GITHUB_SHA': 'a' * 40,
            'GITHUB_WORKFLOW': self.module.WORKFLOW, 'GITHUB_RUN_ID': '123',
            'GITHUB_RUN_ATTEMPT': '1', 'EXPECTED_CONFIGURATION_SHA': 'a' * 40})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_schema2_round_trip(self):
        self.module.create(self.build, self.output)
        self.module.verify(self.output, self.run_file)
        manifest = json.loads((self.output / 'build-manifest.json').read_text())
        self.assertIn('packages.manifest', manifest['files'])

    def test_create_requires_resolved_core(self):
        (self.build / 'resolved-core.json').unlink()
        with self.assertRaisesRegex(ValueError, 'resolved-core'):
            self.module.create(self.build, self.output)

    def test_malformed_resolved_provenance_is_rejected(self):
        for key, value in [('commit', 'master'), ('commit', 'c' * 40),
                           ('url', 'https://example.com/core.tar.gz'),
                           ('url', resolved_core()['url'].replace('clash-linux-arm64', 'clash-linux-amd64')),
                           ('checksums_url', resolved_core()['checksums_url'].replace(resolved_core()['commit'], 'c' * 40)),
                           ('architecture', 'amd64'), ('sha256', 'bad'),
                           ('binary_sha256', 'bad'), ('checksums_sha256', 'bad'),
                           ('resolution_mode', 'unknown')]:
            with self.subTest(key=key, value=value):
                core = resolved_core()
                core[key] = value
                (self.build / 'resolved-core.json').write_text(json.dumps(core))
                with self.assertRaisesRegex(ValueError, 'Invalid resolved core'):
                    self.module.create(self.build, self.output)

    def test_verify_rejects_missing_or_tampered_resolved(self):
        self.module.create(self.build, self.output)
        path = self.output / 'resolved-core.json'
        path.write_text(path.read_text() + ' ')
        with self.assertRaisesRegex(ValueError, 'integrity mismatch: resolved-core'):
            self.module.verify(self.output, self.run_file)
        path.unlink()
        with self.assertRaisesRegex(ValueError, 'Invalid artifact file: resolved-core'):
            self.module.verify(self.output, self.run_file)

    def test_verify_checks_provenance_even_if_hash_is_consistent(self):
        self.module.create(self.build, self.output)
        core = resolved_core()
        core['url'] = core['url'].replace(core['commit'], 'c' * 40)
        path = self.output / 'resolved-core.json'
        path.write_text(json.dumps(core))
        manifest_path = self.output / 'build-manifest.json'
        manifest = json.loads(manifest_path.read_text())
        manifest['files'][path.name] = {'sha256': self.module.digest(path), 'size': path.stat().st_size}
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'Invalid resolved core: url'):
            self.module.verify(self.output, self.run_file)

    def test_schema2_manifest_cannot_omit_resolved_core(self):
        self.module.create(self.build, self.output)
        manifest_path = self.output / 'build-manifest.json'
        manifest = json.loads(manifest_path.read_text())
        del manifest['files']['resolved-core.json']
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'missing required files'):
            self.module.verify(self.output, self.run_file)

    def test_legacy_schema1_requires_explicit_option(self):
        self.module.create(self.build, self.output)
        manifest_path = self.output / 'build-manifest.json'
        manifest = json.loads(manifest_path.read_text())
        manifest['schema'] = 1
        del manifest['files']['resolved-core.json']
        manifest_path.write_text(json.dumps(manifest))
        (self.output / 'resolved-core.json').unlink()
        with self.assertRaisesRegex(ValueError, 'legacy schema 1 requires explicit approval'):
            self.module.verify(self.output, self.run_file)
        self.module.verify(self.output, self.run_file, allow_legacy_schema1=True)


if __name__ == '__main__':
    unittest.main()
