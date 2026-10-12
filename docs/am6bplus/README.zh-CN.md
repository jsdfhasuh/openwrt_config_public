# AM6B Plus：OpenWrt 25.12.5 两阶段 Actions

## 两条工作流

1. `AM6B Plus - Build ARM64 rootfs 25.12.5`：从锁定的官方源码和 feeds 构建 `armsr/armv8` 用户态 rootfs。
2. `AM6B Plus - Package SD with pinned unifreq packit`：下载第一条的指定成功运行产物，真正执行固定版本 unifreq/openwrt_packit 的 S922X 入口，经可审计的 AM6/SD-only 安全适配后生成镜像。

第二条不是使用早期自制 ext4 组装器冒充上游；当前保留上游 FAT + Btrfs 的磁盘格式、rootfs/boot 解包和快照路径。上游源码固定在 `a46b4f5d201ab99eba0ddc7c2e7cd67412fc3d5c`，不是每次拉取浮动 master。

## 以后怎样自己构建

- Actions 页面选第一条 → Run workflow → 选择并行任务数（建议 2）→ 运行。
- 第一条在同仓库 main 分支成功后，第二条自动接续打包。PR/fork 的产物不会进入这条自动路径。
- 若仅需重新打包，在第二条 Run workflow 填入成功 rootfs 的数字 run ID。不能填 artifact ID，也不会模糊选择“最新”产物。
- 手动入口需要工作流存在于默认分支。普通提交不会自动编译；仅 main 上影响列出的 ARM 文件、且提交信息含 `[build-am6bplus]` 时，第一条会自动运行。本次首次触发使用这一方式。
- 第一条 artifact 名为 `am6bplus-rootfs-运行ID-尝试次数`；第二条为 `am6bplus-packit-运行ID-尝试次数`。镜像、日志、完整配置、来源、补丁和 SHA256 都随产物保留 14 天，不自动发 Release。
- 失败不自动重编到绿，日志会尽可能保留。云 runner 空间不足会停止，不清空其他目录。

第二条校验 source workflow、仓库、main、事件、成功终态、run ID、attempt、head SHA、artifact ID、rootfs/config/锁文件摘要。打包脚本检出本次工作流的可信 main 提交；rootfs 原提交与打包提交分别记录，源锁文件必须一致，避免把其他运行或版本的产物混用。

## 配置以当前 x86 应用需求为准

参考用户仓库 `a475f7a2214da748ca229fcd4bb9fb6a81a32964` 的 x86.config。全部 472 个选中条目的迁移处理见 `x86-package-migration.csv`。

显式选择 88 个包配置：Argon 配置及主题、banIP、commands、ddns-go、firewall、mosdns、OpenClash、APK 软件包管理、Samba4、ttyd、UPnP，以及 AdGuard Home、Python3、pip3 及现选子模块、WireGuard 工具、SFTP、诊断/磁盘工具、containerd/runc 等。

- nft-qos 已按用户决定舍弃；官方因多个未修问题将其删除，不盲搬旧版。
- 当前 x86 未选的旧 ARM dockerman/mwan3/wol 页面/OpenWrt2020 主题不默认加入；etherwake 工具按当前 x86 保留。
- 当前 x86 没选 Docker daemon/UI，不擅自新增；containerd/runc 不等于完整 Docker 产品。
- attendedsysupgrade 不适用于这种外部内核 SD 适配，排除其页面和通用升级入口。
- x86 驱动、GRUB 和固件不迁移；库和依赖由 ARM64 Kconfig 重算。
- 新 mosdns 依赖 geo2txt，不伪称旧 v2dat 已安装。
- 不复制原 custom.sh 的自动格式化盘逻辑、固定 AdGuard Home 凭据或 x86 核心。

2024 年找回的 ARM 配置只作历史参考，不能证明现卡内核/启动参数。每个显式配置项在 make defconfig 后核对；缺包或依赖丢失会直接失败。

## 上游 packit 的必要适配

- 固定源码、boot/kernel/modules/DTB/firmware，摘要不符停止，不拉浮动内核。
- 将默认 GT-King Pro DTB 改为 AM6 对应 `/dtb/amlogic/meson-g12b-ugoos-am6.dtb`，不用原错误 `/dev` 注释路径。
- 调用上游实际镜像、分区、文件系统、解包、fstab/快照函数；构建机 loop 和挂载只管理本次创建的资源，禁止全局 losetup -D。
- 不注入原 first_run 自动分区/格式化、不提供 eMMC 安装/在线升级/备份命令，不写 raw FIP。
- 跳过固定密码、应用强制改写以及依赖旧 opkg 数据库的非必要注入，不伪建 opkg 数据库；以实际 APK/rootfs 文件检查作为准入。
- 完整局部补丁和上游原文件/修改后摘要进入 artifact，源文件不符合精确预期就停止。

原 README 的长依赖清单主要为 eMMC 安装和在线升级服务，不全部等于 SD 启动必需。本流程单列 runner 主机工具、目标系统包和选用应用，见 DEPENDENCIES.md。block-mount 必须存在，不能只写 UCI fstab 就声称会挂载 /boot。

## 必须理解的实验限制

这不是 OpenWrt 官方 AM6B Plus 整机移植，AM6 Plus 上游映射不是每个 AM6B Plus 硬件修订的实机保证。
先用备用 SD 卡，保留现卡；首次电脑直连隔离网络（默认 eth0 / 192.168.1.1，可能提供 DHCP），不要接生产网络。设置管理员密码后再配置应用。

随上游资产附带的 Amlogic 启动脚本含 saveenv，SD 启动也可能更改持久 bootloader 环境。没有写 eMMC 镜像不等于绝对不改启动环境。

外置内核与官方 armsr APK 的内核 ABI 不一致。保留原 APK 数据库并不使其与替换后的模块文件一致。不得对 kernel/kmod 做 install/upgrade/fix/reinstall，不做 blanket apk upgrade；普通应用也可能间接拉入 kmod，须审查依赖。禁用某些 kmod 源不等于彻底隔离这一风险。用户态 APK 操作仍需设备验证，更新优先重建整镜像。

OpenClash、mosdns、DDNS、AdGuard Home、UPnP、banIP、containerd、Samba、ttyd 初始禁止自启动，先配置后启用。不自动迁移旧密码、订阅、网络或防火墙。

构建成功只证明产物生成；不能代替真实盒子的启动、网络、温控、Wi-Fi、容器、应用和恢复测试。硬件测试目前 NOT_RUN。构建/打包真实结果以本次 GitHub Actions 与产物 STATUS/manifest 为准，不能把早期静态测试当作完整编译通过。


### 只修复打包而复用成功 rootfs

打包 Action 使用本次可信 main 工作流提交中的打包代码，源 rootfs 仍固定到输入的
成功 run/attempt/artifact/原配置 SHA；两个提交号分别记录，源锁文件必须一致。
手动运行打包 Action 并输入成功 rootfs 的 run ID，无需重编所有软件。
也支持 main 上涉及打包脚本的提交中显式写入 `[pack-am6bplus:数字runID]`，
触发一次只打包运行。普通 push 不打包；失败、PR、外部仓库或非 main rootfs 拒绝。


2026-10-12 按用户要求新增 `python3-pip`，其他包和固定源不变。
构建完成后用最终包清单与 rootfs 中的 pip3 文件核对；旧版不含 pip 的 artifact 保留。

手动扩容工具随新版根分区预装：`/usr/sbin/am6bplus-grow-sd`。
说明：`/usr/share/doc/am6bplus-grow-sd/README.zh-CN.md`。没有开机自动执行钩子。
先只读预览并备份，再按两阶段步骤操作；真实 SD 扩容未测试（NOT_RUN）。
