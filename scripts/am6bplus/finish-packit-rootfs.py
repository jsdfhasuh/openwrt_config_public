#!/usr/bin/env python3
"""Host-side APK adaptation after upstream packit extraction, without target execution."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

MODULES = '''meson_gxl stmmac stmmac_platform dwmac_meson8b
phy_meson_g12a_usb2 phy_meson_g12a_usb3_pcie xhci_hcd xhci_plat_hcd dwc3 dwc3_meson_g12a r8152
br_netfilter bridge veth tun nf_tables nft_chain_nat nft_masq nft_redir nft_reject_inet
nft_fib_inet nft_ct nft_tproxy nft_socket inet_diag xt_TPROXY ip_tables iptable_filter
iptable_nat xt_MASQUERADE xt_addrtype xt_conntrack
ip6_tables ip6table_filter ip6table_nat xt_nat xt_physdev ip_vs ip_vs_rr xt_ipvs'''.split()
REQUIRED_BUILTIN = '''CGROUPS MEMCG CGROUP_PIDS CGROUP_DEVICE CGROUP_CPUACCT
CFS_BANDWIDTH USER_NS POSIX_MQUEUE NAMESPACES NET_NS PID_NS IPC_NS UTS_NS
SECCOMP SECCOMP_FILTER OVERLAY_FS BTRFS_FS
CPUSETS BLK_CGROUP CGROUP_FREEZER CGROUP_SCHED CGROUP_BPF BPF_SYSCALL'''.split()
REQUIRED = '''USB_RTL8152 VETH BRIDGE BRIDGE_NETFILTER TUN NF_CONNTRACK NF_NAT NF_TABLES
NFT_CT NFT_MASQ NFT_REDIR NFT_REJECT NFT_REJECT_INET NFT_FIB_INET NFT_LOG NFT_NAT
NFT_TPROXY NFT_SOCKET INET_DIAG NETFILTER_XT_TARGET_TPROXY IP_NF_IPTABLES
IP_NF_FILTER IP_NF_NAT IP6_NF_IPTABLES NETFILTER_XT_MATCH_ADDRTYPE
NETFILTER_XT_MATCH_CONNTRACK NETFILTER_XT_TARGET_MASQUERADE
IP6_NF_FILTER IP6_NF_NAT NETFILTER_XT_NAT NETFILTER_XT_MATCH_PHYSDEV
IP_VS IP_VS_IPV6 IP_VS_RR NETFILTER_XT_MATCH_IPVS'''.split()


def require(condition, message):
    if not condition:
        raise SystemExit(message)


def configure_modules(root, kernel):
    modules = root / 'lib/modules' / kernel
    require(modules.is_dir(), 'Matched kernel modules missing.')
    available = {p.stem.replace('-', '_') for p in modules.rglob('*.ko')}
    available |= {Path(p).stem.replace('-', '_') for p in (modules / 'modules.builtin').read_text().splitlines()}
    require(set(MODULES) <= available, 'Missing selected modules: ' + str(set(MODULES) - available))
    require((root / 'lib/firmware/rtl_nic/rtl8153b-2.fw').is_file(), 'RTL8153B firmware missing.')
    for directory in ['modules.d', 'modules-boot.d']:
        path = root / 'etc' / directory
        if path.exists():
            require(not (root / 'etc' / f'{directory}.armsr-disabled').exists(), 'Duplicate adaptation.')
            path.rename(root / 'etc' / f'{directory}.armsr-disabled')
        path.mkdir()
    # OpenWrt loads this list at boot; shipping Flippy .ko files alone is insufficient.
    (root / 'etc/modules.d/20-am6bplus').write_text('\n'.join(MODULES) + '\n')
    subprocess.run(['depmod', '-b', str(root), kernel], check=True)


def main():
    require(len(sys.argv) == 5, 'Usage: finish-packit-rootfs.py ROOT BOOT KERNEL ROOT_UUID')
    root, boot = map(Path, sys.argv[1:3])
    kernel, root_uuid = sys.argv[3:]
    helper = Path(__file__).resolve().parent
    require(os.geteuid() == 0, 'Root required to preserve image ownership.')
    require(root.is_mount() and boot.is_mount(), 'Expected upstream-owned mounted filesystems.')
    release = (root / 'etc/openwrt_release').read_text()
    require("DISTRIB_RELEASE='25.12.5'" in release and "DISTRIB_TARGET='armsr/armv8'" in release,
            'Rootfs release/target mismatch.')
    require(any((root / p).is_file() for p in ['sbin/apk', 'usr/bin/apk', 'usr/sbin/apk', 'bin/apk']),
            'Expected APK rootfs. No opkg metadata fallback is allowed.')
    require((root / 'sbin/block').is_file() and (root / 'etc/init.d/fstab').is_file(),
            'block-mount must be selected in the rootfs build.')
    require(bool(list((root / 'lib').glob('libz.so*')) + list((root / 'usr/lib').glob('libz.so*'))),
            'zlib is required by the pinned musl kmod binary.')
    for name in ['boot-emmc.cmd', 'boot-emmc.scr', 'boot-emmc.ini', 'emmc_autoscript', 'emmc_autoscript.cmd']:
        (boot / name).unlink(missing_ok=True)
    config = (boot / f'config-{kernel}').read_text()
    for option in REQUIRED_BUILTIN:
        require(f'CONFIG_{option}=y\n' in config, f'Missing built-in capability: {option}')
    for option in REQUIRED:
        require(re.search(rf'^CONFIG_{option}=[ym]$', config, re.M), f'Missing capability: {option}')
    require((boot / 'dtb/amlogic/meson-g12b-ugoos-am6.dtb').is_file(), 'AM6 DTB missing.')
    uenv = (boot / 'uEnv.txt').read_text()
    require('FDT=/dtb/amlogic/meson-g12b-ugoos-am6.dtb\n' in uenv, 'Wrong active DTB.')
    require(f'root=UUID={root_uuid} ' in uenv and 'rootfstype=btrfs' in uenv,
            'Upstream root UUID/filesystem mismatch.')
    require(root_uuid in (root / 'etc/config/fstab').read_text(), 'Upstream fstab UUID mismatch.')
    fstab = root / 'etc/config/fstab'
    fstab_text = fstab.read_text()
    for option in ['anon_mount', 'auto_mount']:
        before = f"option {option} '1'"
        require(fstab_text.count(before) == 1, f'Upstream fstab context changed: {option}')
        fstab_text = fstab_text.replace(before, f"option {option} '0'")
    fstab.write_text(fstab_text)
    configure_modules(root, kernel)
    shutil.copyfile(helper / 'kmod', root / 'sbin/kmod')
    (root / 'sbin/kmod').chmod(0o755)
    for name in ['depmod', 'insmod', 'lsmod', 'modinfo', 'modprobe', 'rmmod']:
        path = root / 'sbin' / name
        path.unlink(missing_ok=True)
        path.symlink_to('kmod')
    # Do not let Docker alter the network or fill the small root partition on boot.
    # Remove only these services' own rc.d links; users opt in after SD expansion.
    for service in ['dockerd', 'containerd']:
        for link in (root / 'etc/rc.d').glob('*' + service):
            require(link.is_symlink(), f'Unexpected non-symlink service entry: {link}')
            require(os.readlink(link) in [f'../init.d/{service}', f'/etc/init.d/{service}'],
                    f'Unexpected service link target: {link}')
            link.unlink()
    # These programs must not enter an experimental SD-only artifact.
    for relative in ['etc/first_run.sh', 'etc/part_size', 'root/install-to-emmc.sh',
                     'usr/sbin/openwrt-install-amlogic', 'usr/sbin/openwrt-update-amlogic',
                     'usr/sbin/openwrt-kernel', 'usr/sbin/openwrt-backup',
                     'usr/sbin/openwrt-ddbr', 'usr/sbin/flippy']:
        require(not (root / relative).exists() and not (root / relative).is_symlink(),
                f'Unexpected installer/updater/partitioner: {relative}')
    require('first_run.sh' not in (root / 'etc/rc.local').read_text(), 'Unexpected first-run hook.')
    for name in ['sysupgrade', 'firstboot', 'jffs2reset', 'jffs2mark']:
        path = root / 'sbin' / name
        if path.exists() or path.is_symlink():
            path.unlink()
            path.write_text("#!/bin/sh\necho 'Disabled on experimental AM6B Plus SD image; rebuild and reflash SD.' >&2\nexit 1\n")
            path.chmod(0o755)
    board = root / 'etc/board.d/03_am6bplus'
    board.parent.mkdir(exist_ok=True)
    shutil.copyfile(helper / 'board-network.sh', board)
    board.chmod(0o755)
    for path in (root / 'etc/apk/repositories.d').glob('*'):
        if path.is_file():
            path.write_text(''.join('# External kernel: ' + line if '/kmods/' in line and not line.startswith('#')
                                    else line for line in path.read_text().splitlines(keepends=True)))
    warning = '''\nEXPERIMENTAL AM6B Plus SD image, NOT an official device port. Hardware boot unverified.
Pinned upstream packit builds FAT + btrfs. APK records describe original armsr kernel
packages, not the replacement Flippy ABI. Never apk upgrade/fix/reinstall kernel or
kmod packages; applications pulling kmod dependencies also require review.
No eMMC installation, online kernel update, or first-run partitioning is supplied.
aml_autoscript executes saveenv: SD activation can alter persistent boot settings.
Back up Android/eMMC and bootloader environment. First boot: isolated PC only,
eth0 LAN 192.168.1.1 with DHCP server; never attach to a production LAN initially.
'''
    with (root / 'etc/banner').open('a') as stream:
        stream.write(warning)
    folder = root / 'etc/am6bplus'
    folder.mkdir(exist_ok=True)
    (folder / 'README').write_text(warning)
    shutil.copyfile(helper / 'assets.lock.json', folder / 'assets.lock.json')
    manifest = json.loads((helper / 'adaptation.json').read_text())
    manifest.update(kernel_release=kernel, root_uuid=root_uuid, hardware_tested=False,
                    filesystem='btrfs', package_database='Original APK metadata; external kernel ABI mismatch')
    (folder / 'packaging-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    shutil.copyfile(folder / 'packaging-manifest.json', helper.parent / 'output/packaging-manifest.json')


if __name__ == '__main__':
    main()
