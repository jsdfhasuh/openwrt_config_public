#!/bin/bash
architecture=$1
echo "Architecture: $architecture"
build_root=$2
# openwrt_files
openwrt_files=$build_root/openwrt_files
mkdir -p $openwrt_files
# download clash core
clash_core_url="https://raw.githubusercontent.com/vernesong/OpenClash/blob/core/master/meta/clash-linux-$architecture.tar.gz"
clash_core_dir=$openwrt_files/etc/openclash/core
mkdir -p $clash_core_dir
echo "Downloading clash core from $clash_core_url"
curl -L -o $clash_core_dir/clash_meta $clash_core_url
