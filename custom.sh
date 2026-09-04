#!/bin/bash
architecture=$1
echo "Custom script started"
echo "Architecture: $architecture"
build_root=$2
BUILD_OPENWRT=$3
echo "Build root: $build_root"
echo "Build openwrt: $BUILD_OPENWRT"

# Enable VMware VMDK and bootable ISO images for both OpenWrt workflows.
CONFIG_FILE="$build_root/x86.config"
if [ ! -f "$CONFIG_FILE" ]; then
    echo "ERROR: OpenWrt config not found: $CONFIG_FILE" >&2
    exit 1
fi

for option in ISO_IMAGES VMDK_IMAGES; do
    sed -i \
        -e "/^CONFIG_${option}=.*/d" \
        -e "/^# CONFIG_${option} is not set$/d" \
        "$CONFIG_FILE"
    echo "CONFIG_${option}=y" >> "$CONFIG_FILE"
done

echo "Enabled image formats:"
grep -E '^CONFIG_(ISO_IMAGES|VMDK_IMAGES)=y$' "$CONFIG_FILE"

# EFI ISO generation needs mkfs.fat, mmd and mcopy on the GitHub runner.
sudo DEBIAN_FRONTEND=noninteractive apt-get -qq install -y dosfstools mtools

# openwrt_files
openwrt_files=$build_root/openwrt_files
mkdir -p "$openwrt_files"
# download clash core
clash_core_url="https://raw.githubusercontent.com/vernesong/OpenClash/blob/core/master/meta/clash-linux-$architecture.tar.gz"
clash_core_dir=$openwrt_files/etc/openclash/core
echo "Clash core dir: $clash_core_dir"
mkdir -p "$clash_core_dir"
echo "Downloading clash core from $clash_core_url"
curl -L -o $clash_core_dir/clash_meta $clash_core_url
ls -l $clash_core_dir
# add adguardhome.yaml
mv $build_root/adguardhome.yaml $openwrt_files/etc/adguardhome.yaml
ls -l $openwrt_files/etc/adguardhome.yaml
# mv root
mv $build_root/root $openwrt_files/root
# mv rc.local
mv $build_root/rc.local $openwrt_files/etc/rc.local

# fixed rust host build download llvm in ci error
cat $BUILD_OPENWRT/feeds/packages/lang/rust/Makefile | grep -q -- 'llvm.download-ci-llvm' || echo "llvm.download-ci-llvm not found"
sed -i 's/--set=llvm\.download-ci-llvm=true/--set=llvm.download-ci-llvm=false/' $BUILD_OPENWRT/feeds/packages/lang/rust/Makefile
grep -q -- '--ci false \\' $BUILD_OPENWRT/feeds/packages/lang/rust/Makefile || sed -i '/x\.py \\/a \        --ci false \\' $BUILD_OPENWRT/feeds/packages/lang/rust/Makefile

echo "custom is complete!"
