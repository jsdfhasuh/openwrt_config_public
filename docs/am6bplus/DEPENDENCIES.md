# 两阶段依赖契约

## Rootfs 编译主机

OpenWrt 官方构建工具：编译器、make、ncurses、rsync、gawk、Python 等。安装在 GitHub runner，不是选择一个目标 CONFIG_PACKAGE 就能满足。

## 上游 packit 主机

本次实际入口使用 btrfs-progs、dosfstools、e2fsprogs、fdisk、util-linux、parted、gawk、uuid-runtime、kmod、xz/zstd/gzip/tar、Python、curl、git、rsync、bc 等。
创建普通镜像文件后，使用本次专属 loop/mount 执行真实上游流程。只清理本次资源，不运行全局 losetup -D，不接触用户 SD/eMMC。

## 目标 rootfs

| 配置 | 用途 |
| --- | --- |
| CONFIG_PACKAGE_block-mount=y | /sbin/block 与 fstab 服务；实际启动 UCI /boot 挂载 |
| CONFIG_PACKAGE_bash=y | 保留应用脚本需要 |
| CONFIG_PACKAGE_btrfs-progs=y | 上游 Btrfs 根文件系统维护；内核还须具备对应能力 |
| CONFIG_PACKAGE_e2fsprogs=y | 用户现选维护工具，不宣称所有 SD 根分区必需 |
| CONFIG_PACKAGE_blkid=y、CONFIG_PACKAGE_lsblk=y | 磁盘识别与诊断，不等同于内核 root 挂载必需 |
| CONFIG_PACKAGE_zlib=y | 固定 AArch64 kmod 工具的 libz.so.1 依赖 |
| 官方 base-files/fstools/BusyBox、APK、musl | 基础系统和用户态身份，实际根文件检查 |

mkfs/parted/losetup 等宿主工具与上述目标包严格区分。原版 packit 的 first_run、eMMC 安装、在线升级依赖没有因为 README 就全部强加，本 SD-only 适配不提供这些功能。

对外部内核，安装用户态包无法弥补模块缺项。保留的 APK 数据库不是模块 ABI 证明，详细升级风险见 README。
