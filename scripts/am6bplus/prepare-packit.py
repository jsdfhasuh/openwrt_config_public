#!/usr/bin/env python3
"""Prepare an exact, auditable SD-only adapter for pinned upstream openwrt_packit.

This prepares files only. Image assembly is performed by upstream public_funcs
on a fresh GitHub-hosted runner through mk_s922x_am6bplus.sh.
"""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import shutil
import shlex
import subprocess
import sys
import tarfile

sys.dont_write_bytecode = True
import importlib.util

HERE = Path(__file__).resolve().parent
PIN = 'a46b4f5d201ab99eba0ddc7c2e7cd67412fc3d5c'
ORIGINAL_SHA256 = {
    'public_funcs': '9637786105f18452b0c38fdf3bc71c9e24c48fac9e85c1fafbc6015748df4ac5',
    'mk_s922x_gtking.sh': '9c58103ecf32be6fcc8955f07c42ab2bfe3dbc523a69e122c77f2db284f7c23b',
    'make.env': '547d3e15c7eaac335f5b39bd784335bd186b83beec0f6372daf5dbc548bb07cf',
}


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def exact(text, before, after, count=1):
    actual = text.count(before)
    if actual != count:
        raise ValueError(f'Patch context count {actual}, expected {count}: {before[:100]!r}')
    return text.replace(before, after)


def function_body(text, name):
    prefix = f'function {name}() {{\n'
    if text.count(prefix) != 1:
        raise ValueError(f'Expected exactly one function {name}')
    start = text.index(prefix)
    end = text.index('\n}\n', start) + 3
    return text[start:end]


def adapt_functions(original):
    text = original
    old = function_body(text, 'check_block_dev')
    text = exact(text, old, '''function check_block_dev() {
    am6_assert_device "$1" || { echo "Non-owned block device refused: $1" >&2; exit 1; }
}
''')
    text = exact(text, '    losetup -D\n    echo \n}',
                 '    # No global detach: runtime owns only its newly allocated loop.\n    echo\n}')
    old = function_body(text, 'detach_loopdev')
    text = exact(text, old, '''function detach_loopdev() {
    am6_cleanup_owned
}
''')
    text = exact(text, '    dd if=/dev/zero of="$img_name" bs=1M count=$size_mb conv=fsync && sync',
                 '    [[ "$img_name" == "$WORK_DIR"/*.img && ! -e "$img_name" && ! -L "$img_name" ]] || exit 1\n'
                 '    dd if=/dev/zero of="$img_name" bs=1M count=$size_mb conv=fsync && sync')
    text = exact(text, '    losetup -f -P "$img_name"', '''    [[ "$img_name" == "$WORK_DIR"/*.img && ! -b "$img_name" && ! -L "$img_name" ]] || exit 1
    AM6_OWNED_IMAGE=$(realpath -- "$img_name")
    AM6_OWNED_LOOP=$(losetup --find --show --partscan "$img_name")''')
    text = exact(text, '''        TGT_DEV=$(losetup | grep "$img_name" | gawk '{print $1}')''',
                 '        TGT_DEV=$AM6_OWNED_LOOP\n        am6_assert_device "$TGT_DEV" || exit 1')
    old = function_body(text, 'mount_fs')
    new = exact(old, '         echo "成功"\n    fi',
                '         AM6_OWNED_MOUNTS+=("$mount_point")\n         echo "成功"\n    fi')
    text = exact(text, old, new)
    old = function_body(text, 'clean_work_env')
    text = exact(text, old, exact(old, '    detach_loopdev\n', '    detach_loopdev || return 1\n'))
    text = exact(text, '1>/dev/nul 2>&1', '1>/dev/null 2>&1')
    text = exact(text, 'btrfs subvolume snapshot -r etc .snapshots/${snapshot_name}',
                 'btrfs subvolume snapshot -r etc .snapshots/${snapshot_name} || exit 1')
    if 'losetup -D' in text or 'umount -f *' in text:
        raise ValueError('Global device cleanup remains after adaptation.')
    return text


SKIPPED_CALLS = '''copy_supplement_files
extract_glibc_programs
adjust_docker_config
adjust_openssl_config
adjust_qbittorrent_config
adjust_getty_config
adjust_samba_config
adjust_nfs_config "mmcblk2p4"
adjust_openssh_config
adjust_openclash_config
use_xrayplug_replace_v2rayplug
create_fstab_config
adjust_turboacc_config
adjust_ntfs_config
adjust_mosdns_config
patch_admin_status_index_html
adjust_kernel_env
copy_uboot_to_fs
write_release_info
write_banner
config_first_run
create_snapshot "etc-000"
write_uboot_to_disk
clean_work_env'''


def adapt_entry(original):
    text = exact(original, 'source make.env\nsource public_funcs\ninit_work_env', '''source ./am6bplus/packit-runtime.sh
am6_require_runner
AM6_HELPER=$PWD/am6bplus
export AM6_HELPER
source make.env
source public_funcs
init_work_env
[[ -d "$TEMP_DIR" && -d "$TGT_BOOT" && -d "$TGT_ROOT" ]] || exit 1''')
    text = exact(text, 'BOARD=gtking', 'BOARD=am6bplus')
    text = exact(text, 'ROOTFS_MB=1280', 'ROOTFS_MB=3072')
    text = exact(text, 'btrfs subvolume create $TGT_ROOT/etc', 'btrfs subvolume create "$TGT_ROOT/etc" || exit 1')
    text = exact(text, 'cd $TGT_BOOT\n', 'cd "$TGT_BOOT" || exit 1\n')
    text = exact(text, 'cd $TGT_ROOT\n', 'cd "$TGT_ROOT" || exit 1\n')
    text = exact(text, '\nFDT=/dtb/amlogic/meson-g12b-gtking-pro.dtb\n',
                 '\n#FDT=/dtb/amlogic/meson-g12b-gtking-pro.dtb\n')
    text = exact(text, '#FDT=/dev/amlogic/meson-g12b-ugoos-am6.dtb',
                 'FDT=/dtb/amlogic/meson-g12b-ugoos-am6.dtb')
    text = exact(text, SKIPPED_CALLS, '''# Keep upstream layout/extraction/fstab/snapshots. Omit legacy application,
# opkg, fixed-password, first-run partitioning and internal-storage tooling.
create_fstab_config
write_release_info
python3 "$AM6_HELPER/finish-packit-rootfs.py" "$TGT_ROOT" "$TGT_BOOT" "$KERNEL_VERSION" "$ROOTFS_UUID" || exit 1
create_snapshot "etc-000" || exit 1
[[ -d "$TGT_ROOT/.snapshots/etc-000" ]] || exit 1
clean_work_env || exit 1
[[ -z "$AM6_OWNED_LOOP" ]] || exit 1''')
    text = exact(text, 'mv ${TGT_IMG} ${OUTPUT_DIR} && sync', 'mv -- "$TGT_IMG" "$OUTPUT_DIR" || exit 1\nsync')
    return text


def require(condition, message):
    if not condition:
        raise SystemExit(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('checkout', type=Path)
    parser.add_argument('rootfs', type=Path)
    parser.add_argument('assets', type=Path)
    args = parser.parse_args()
    checkout, rootfs, assets = (p.resolve() for p in (args.checkout, args.rootfs, args.assets))
    require(all(not any(c.isspace() for c in str(p)) for p in (checkout, rootfs, assets)),
            'Upstream packit requires paths without whitespace.')
    require(rootfs.is_file() and rootfs.stat().st_size >= 10 * 1024 * 1024,
            'Rootfs missing or below 10 MiB. Never pad an incomplete rootfs.')
    revision = subprocess.check_output(['git', '-C', str(checkout), 'rev-parse', 'HEAD'], text=True).strip()
    require(revision == PIN, f'Packit must be checked out at {PIN}, not a moving branch.')
    subprocess.run(['git', '-C', str(checkout), 'diff', '--exit-code', 'HEAD', '--'], check=True)
    require(not (checkout / 'whoami').exists() and not (checkout / 'am6bplus').exists(),
            'Use a fresh packit checkout without whoami or previous adaptation.')
    for name, expected in ORIGINAL_SHA256.items():
        require(sha256(checkout / name) == expected, f'Upstream source checksum changed: {name}')
    spec = importlib.util.spec_from_file_location('validate_rootfs', HERE / 'validate-rootfs.py')
    validator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validator)
    validator.validate(rootfs)
    with tarfile.open(rootfs, 'r:gz') as archive:
        candidates = [m for m in archive if m.name.lstrip('./') == 'etc/openwrt_release']
        require(len(candidates) == 1 and candidates[0].isfile(), 'Missing or invalid OpenWrt release metadata.')
        release = archive.extractfile(candidates[0]).read().decode()
    require("DISTRIB_RELEASE='25.12.5'" in release and "DISTRIB_TARGET='armsr/armv8'" in release,
            'Expected OpenWrt 25.12.5 armsr/armv8 rootfs.')
    subprocess.run([sys.executable, str(HERE / 'download-assets.py'), str(assets), '--verify-only'], check=True)
    lock = json.loads((HERE / 'assets.lock.json').read_text())
    require(lock['packit_commit'] == PIN, 'Asset lock and packit source commit differ.')
    originals = {name: (checkout / name).read_text() for name in ['public_funcs', 'mk_s922x_gtking.sh']}
    adapted = {'public_funcs': adapt_functions(originals['public_funcs']),
               'mk_s922x_am6bplus.sh': adapt_entry(originals['mk_s922x_gtking.sh'])}
    # Validate all modified shell before writing the checkout.
    for content in adapted.values():
        subprocess.run(['bash', '-n'], input=content, text=True, check=True)
    helper = checkout / 'am6bplus'
    helper.mkdir()
    for name in ['packit-runtime.sh', 'finish-packit-rootfs.py', 'board-network.sh', 'assets.lock.json']:
        shutil.copyfile(HERE / name, helper / name)
    shutil.copyfile(assets / 'kmod', helper / 'kmod')
    for name, content in adapted.items():
        (checkout / name).write_text(content)
    (checkout / 'mk_s922x_am6bplus.sh').chmod(0o755)
    destination = checkout / 'openwrt-armsr-armv8-generic-rootfs.tar.gz'
    require(not destination.exists(), 'Rootfs already exists in checkout.')
    shutil.copyfile(rootfs, destination)
    (checkout / 'whoami').write_text(
        f'WHOAMI=AM6BPlus-experimental\nOPENWRT_VER=25.12.5\n'
        f'KERNEL_VERSION={shlex.quote(lock["kernel_release"])}\nKERNEL_PKG_HOME={shlex.quote(str(assets))}\n')
    patch = ''.join(difflib.unified_diff(originals['public_funcs'].splitlines(True),
                                        adapted['public_funcs'].splitlines(True),
                                        'a/public_funcs', 'b/public_funcs'))
    patch += ''.join(difflib.unified_diff(originals['mk_s922x_gtking.sh'].splitlines(True),
                                         adapted['mk_s922x_am6bplus.sh'].splitlines(True),
                                         'a/mk_s922x_gtking.sh', 'b/mk_s922x_am6bplus.sh'))
    (helper / 'upstream-adaptation.patch').write_text(patch)
    manifest = {'packit_commit': PIN, 'rootfs_sha256': sha256(rootfs),
                'original_sources': ORIGINAL_SHA256,
                'adapted_sources': {name: sha256(checkout / name) for name in adapted},
                'adaptation_patch_sha256': sha256(helper / 'upstream-adaptation.patch'),
                'assembly': 'Pinned upstream public_funcs, SD-only adapter of mk_s922x_gtking.sh',
                'image_built': False, 'hardware_tested': False,
                'bootloader_environment_may_change': True}
    manifest['assets'] = lock
    (helper / 'adaptation.json').write_text(json.dumps(manifest, indent=2) + '\n')
    (checkout / 'am6bplus-patch-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print('Prepared pinned upstream mk_s922x_am6bplus.sh (not executed).')
    print('Run only on a fresh GitHub-hosted runner; outputs: packit/output/*.img')


if __name__ == '__main__':
    main()
