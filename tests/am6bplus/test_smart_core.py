import hashlib
import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('resolve_smart_core', ROOT / 'scripts/am6bplus/resolve-smart-core.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
COMMIT = 'a' * 40
CHECKSUM = 'b' * 64
DATA = f'{CHECKSUM}  ./clash-linux-arm64.tar.gz\n'.encode()


class TestSmartCoreResolution(unittest.TestCase):
    def test_latest_resolves_full_sha_and_pins_checksum_download(self):
        with patch.object(MODULE.subprocess, 'check_output', side_effect=[f'{COMMIT}\trefs/heads/core\n', DATA]) as run:
            spec = MODULE.resolve()
        self.assertEqual(spec['commit'], COMMIT)
        self.assertEqual(spec['resolution_mode'], 'latest')
        self.assertEqual(spec['sha256'], CHECKSUM)
        self.assertEqual(spec['checksums_sha256'], hashlib.sha256(DATA).hexdigest())
        self.assertEqual((spec['schema'], spec['type'], spec['architecture'], spec['format']), (1, 'Smart', 'arm64', 'tar.gz'))
        self.assertEqual(spec['url'], f'{MODULE.RAW_BASE}/{COMMIT}/dev/smart/{MODULE.FILENAME}')
        self.assertEqual(run.call_args_list[0].args[0], ['git', 'ls-remote', '--exit-code', MODULE.REPOSITORY, MODULE.CORE_REF])
        self.assertEqual(run.call_args_list[1].args[0][-1], spec['checksums_url'])
        self.assertNotIn('binary_sha256', spec)

    def test_pinned_does_not_resolve_branch(self):
        with patch.object(MODULE.subprocess, 'check_output', return_value=DATA) as run:
            spec = MODULE.resolve(COMMIT)
        self.assertEqual(spec['resolution_mode'], 'pinned')
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[0][0], 'curl')

    def test_invalid_override_rejected_before_network(self):
        for value in ('core', 'a' * 39, 'A' * 40, 'a' * 40 + '\n', 'https://example.com/core', '--help'):
            with self.subTest(value=value), patch.object(MODULE.subprocess, 'check_output') as run:
                with self.assertRaises(ValueError):
                    MODULE.resolve(value)
                run.assert_not_called()

    def test_invalid_branch_results_rejected(self):
        for refs in ('', 'abc\trefs/heads/core\n', f'{COMMIT}\trefs/heads/main\n', f'{COMMIT}\trefs/heads/core\n' * 2):
            with self.subTest(refs=refs), patch.object(MODULE.subprocess, 'check_output', return_value=refs) as run:
                with self.assertRaises(ValueError):
                    MODULE.resolve()
                self.assertEqual(run.call_count, 1)

    def test_missing_duplicate_or_invalid_checksum_rejected(self):
        for data in (b'', DATA * 2, DATA.replace(b'./clash-linux-arm64', b'./clash-linux-amd64'), DATA.replace(CHECKSUM.encode(), b'xyz'), DATA.replace(b'./clash', b'../clash')):
            with self.subTest(data=data), patch.object(MODULE.subprocess, 'check_output', return_value=data):
                with self.assertRaises(ValueError):
                    MODULE.resolve(COMMIT)

    def test_network_errors_have_no_fallback(self):
        for override in ('', COMMIT):
            with self.subTest(override=override), patch.object(MODULE.subprocess, 'check_output', side_effect=subprocess.CalledProcessError(1, 'network')) as run:
                with self.assertRaises(subprocess.CalledProcessError):
                    MODULE.resolve(override)
                self.assertEqual(run.call_count, 1)


if __name__ == '__main__':
    unittest.main()
