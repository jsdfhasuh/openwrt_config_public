#!/bin/bash
architecture=$0
echo "Architecture: $architecture"
build_root=$1
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