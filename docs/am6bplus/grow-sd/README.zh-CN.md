# AM6B Plus SD 扩容脚本（实验性、默认只预览）

## 为什么 128GB 卡只有 3GiB 根分区？

当前镜像按固定大小生成：磁盘前 4MiB 是保留/引导区域，p1 是 384MiB FAT32 启动分区，p2 是 3GiB Btrfs 根分区，后面没有 p3/p4。把镜像写入更大的 SD 卡不会自动改变分区表。为避免首次启动误格式化/误改 eMMC，构建中已禁用上游 first_run 自动分区逻辑。

这里核实的是成功打包任务 38238567698 的实际产物，而不是根据设备型号猜布局：

- p1：起始扇区 8192，长度 786432 扇区
- p2：起始扇区 794624，长度 6291456 扇区
- 每扇区 512 字节，分区表为 MBR
- 根目录采用 Btrfs，/etc 是子卷，/.snapshots/etc-000 是只读快照；/rom 的 fstab 也指向相同根 UUID

128GB 是厂商十进制标称，约为 119.21GiB。扣除前面的引导区和启动分区，若实际容量正好 128,000,000,000 字节，扩容后的 p2 约为 118.83GiB（127,592,824,832 字节）。Btrfs 元数据、系统文件及快照还会占空间；df 的可用数不会等于标称容量。脚本以实际读取的卡容量计算，末尾可能留不足 1MiB 对齐余量。

## 方案与风险

脚本实现两阶段、人工确认的在线扩容，适合只有 Windows 和一张 SD 卡的情况：

1. 在 OpenWrt 上，校验 SD 身份和原始分区布局；只增大 MBR 中 p2 的长度。整扇区写回，但只有长度字段的 4 字节可能改变。保留 MBR 引导代码、磁盘签名、所有分区起始位置和其他分区表字段。
2. 不强行重读在用分区表，不自动重启，不在这一阶段扩文件系统。你正常重启设备后，内核才使用新 p2 大小。
3. 再运行第二阶段，核对内核 p2 大小、当前 SD 身份、Btrfs UUID 和挂载设备；单独确认后调用 btrfs filesystem resize max。

脚本不格式化、不删除/新建分区、不移动数据、不改 UUID、不改 fstab、不删快照、不安装/启动 Docker。它也不会把自己加入首次启动或 rc.local。扩容现有 Btrfs 不需要格式化，现有子卷/快照仍属同一文件系统。

任何写分区表都有风险，尤其是断电、劣质/故障 SD、并发分区操作、内核或硬件异常。512 字节写入和 fsync 不能保证 SD 控制器在突然掉电时原子完成。请用稳定电源，先把重要数据备份到 Windows，再把下面生成的原始前缀备份复制到 Windows。仅把备份留在同一张 SD 上没有灾难恢复保障。

离线使用另一台 Linux 机器扩分区，能避免当前系统仍运行带来的并发风险，通常更稳；但仍存在写卡断电风险，也需要可靠识别读卡器。本脚本刻意只支持当前系统里的原生 SD（sysfs type=SD、可读 CID），不支持 USB 读卡器、eMMC、GPT、第三分区、RAID、device-mapper、多设备 Btrfs 或普通镜像文件。没有通过检查时请停下来，不要删掉检查强行运行。

## 使用前

本脚本仅完成源码检查、实际镜像只读校验，以及自己创建的稀疏文件/模拟运行测试。尚未在 AM6B Plus 实机、真实 SD 或挂载的 Btrfs 上验证；不能称为实机验证完成。

请先进行预览，把输出留存。如果有报错或布局与说明不同，先人工复核。建议先在可丢弃数据的测试卡上验证。

依赖：python3（包括标准库 fcntl、argparse、hashlib、json、pathlib、subprocess、struct、uuid 等）和 btrfs-progs。已成功的 rootfs 配置/包清单含 python3、python3-light、python3-uuid 和 btrfs-progs，并已只读检查 rootfs 压缩包中上述模块和 /usr/bin/btrfs 确实存在；pip3 版仍在编译，最终以新产物清单为准。此前未安装 pip3 的成功版本也已有这些 Python 运行依赖，不需要等待 pip3 才能运行脚本。无需 parted、growpart 或 sfdisk；不尝试联网安装依赖。

## 1. 上传并确认 SD

新版固件已预装 /usr/sbin/am6bplus-grow-sd；此工具只在用户手动调用时运行。以下命令在 OpenWrt 的 SSH 终端里运行，不能直接粘贴到 Windows PowerShell 当作 Linux 命令。

先只读查看：

```sh
lsblk -o NAME,SIZE,FSTYPE,MOUNTPOINTS
for d in /sys/class/block/mmcblk*; do
  [ -f "$d/device/type" ] || continue
  echo "$d"
  cat "$d/device/type" "$d/device/name" "$d/device/cid" "$d/size"
done
btrfs filesystem show --raw /
```

type=SD 才是候选 SD；type=MMC 通常是 eMMC，脚本会拒绝。不要因为名字是 mmcblk0 就认定它是 SD。确认容量、CID、当前 Btrfs 挂载使用的 p2 相符。

下列 SD 值必须手动改成刚刚核实的真实设备路径，MOUNTPOINT 也必须是直接、可写的 Btrfs 挂载点 / 或 /rom。如果 / 是 overlay，不要硬套 /：核实 /rom 是否是直接可写 Btrfs；只读 /rom 也会被脚本拒绝。

```sh
SD=/dev/请填已核实的整张SD设备名
MOUNTPOINT=/
/usr/sbin/am6bplus-grow-sd --device "$SD" --mountpoint "$MOUNTPOINT"
```

默认只读预览。显示 CID、容量、根 UUID、当前/目标扇区数、内核当前大小以及本阶段 confirm_token。令牌绑定设备路径、CID、容量、UUID、目标大小和阶段，重启后设备路径改变时必须重新预览，不能套用旧令牌。

## 2. 生成备份，下载到 Windows

先备份业务数据。然后在 OpenWrt 生成前 4MiB 备份和身份信息：

```sh
/usr/sbin/am6bplus-grow-sd --device "$SD" --mountpoint "$MOUNTPOINT" \
  --save-backup /root/am6-sd-prefix.bin
```

将 /root/am6-sd-prefix.bin 和 /root/am6-sd-prefix.bin.json 下载到 Windows 并检查文件大小。bin 应为 4,194,304 字节。JSON 内有 SHA256，可在 Windows 用 Get-FileHash 核对。前缀包含原始分区表和引导保留区，不含完整 p1/p2，也不是业务数据备份。不要公开这些身份信息文件。

脚本不覆盖同名备份。扩容后不要重新生成“原始备份”，请保留扩容前的版本。

## 3. 明确执行分区阶段

停止 Docker、Home Assistant 等写入服务，关闭 swap；脚本不会擅自替你停止它们。有 swap 或复杂存储层时脚本拒绝运行。确保没有其他分区工具在操作这张卡。flock 是协作锁，不能阻止不遵守锁的 parted、dd 或其他 root 操作；全过程禁止换卡、重挂载以及并行使用分区管理工具。

再次运行预览，然后填入它实际输出的令牌。两个确认开关表示你已经完成对应事项，不能拿来跳过备份或停服务：

```sh
/usr/sbin/am6bplus-grow-sd --device "$SD" --mountpoint "$MOUNTPOINT" \
  --apply --confirm '填入本次partition预览的GROW令牌' \
  --backup-file /root/am6-sd-prefix.bin --backup-exported --services-stopped
```

仅在看到“MBR p2 length updated and read back”后，保持业务服务停止，正常重启 OpenWrt（例如用 LuCI 重启或 reboot）。脚本不会自动重启，也不会运行 partprobe、partx、BLKRRPART 或 grow 文件系统。

若命令失败或断电，不要盲目重复写分区表，不要立即格式化。先核实分区表和系统能否启动；需要恢复时使用外部备份、已确认设备身份的离线工具人工处理。本交付物没有自动恢复脚本。

特别注意：一旦第二阶段已扩大 Btrfs，不能直接恢复旧的 4MiB 前缀！这样会把 p2 可见长度改回 3GiB，截断已扩大的文件系统。旧前缀只能作为尚未 grow 文件系统时的恢复参考；任何恢复都应先核实当前真实状态，不能盲目写回。

## 4. 重启后扩 Btrfs

重新 SSH 登录，重新核实 SD 路径并设置 SD/MOUNTPOINT。必须将本次预览中的 CID、capacity_bytes 和 root_uuid 与保存在 Windows 的原始备份 JSON 逐项比较，三者完全一致才继续。第二阶段必须提供第一阶段生成的原始 JSON，脚本会自动核对 CID、实际容量、根 UUID、p2 起始扇区和目标长度；缺失、损坏或不匹配都会拒绝。设备路径可能在重启后变化，所以不能仅比较路径。不要编辑 JSON 来绕过不匹配。若服务自动启动，请先再停止 Docker/HA 等写入服务。

```sh
/usr/sbin/am6bplus-grow-sd --device "$SD" --mountpoint "$MOUNTPOINT" --phase filesystem --identity-file /root/am6-sd-prefix.bin.json
```

脚本必须看到内核的新 p2 大小，才会允许后续操作。若提示 REBOOT REQUIRED，不要强制重读当前根分区表；先确认是否真的重启并核实状态。

确认新输出的 filesystem 令牌后：

```sh
/usr/sbin/am6bplus-grow-sd --device "$SD" --mountpoint "$MOUNTPOINT" --phase filesystem --identity-file /root/am6-sd-prefix.bin.json \
  --apply --confirm '填入本次filesystem预览的GROW令牌' --services-stopped
btrfs filesystem show --raw "$MOUNTPOINT"
btrfs filesystem usage "$MOUNTPOINT"
df -h "$MOUNTPOINT"
```

脚本通过已挂载 Btrfs 的实时设备信息校验扩容结果，避免把整盘原始读取缓存误当成最新文件系统状态。成功后可以手动恢复业务服务。

重跑已完成的阶段会报告无需操作。完成分区阶段但尚未重启时，重跑分区阶段不会再次写表；文件系统阶段会拒绝使用旧内核分区大小。断在两阶段之间不会要求重新格式化。

## Docker / Home Assistant 数据规划

此次扩容增加的是现有 Btrfs 根文件系统的空间。之后可以把业务数据放在合适的目录或单独 Btrfs 子卷，再明确设置 Docker data-root / Home Assistant 挂载。脚本不自动迁移数据，也不承诺已有 Docker 数据路径会自动改变。

保留独立数据分区的好处是系统重装时可以更清楚地区分数据，但这需要新增并格式化 p3、配置挂载和迁移，风险及操作更多。当前镜像的 p2 本来就是最后一个分区，扩大它更直接；若希望独立数据分区，请先确定方案，不要先把 p2 扩满再计划缩小它。

重刷整张 SD 镜像会破坏卡上系统和数据，扩容不是备份。仅有 /etc 快照也不等于 Docker/HA 全量备份。长期大量写入优先考虑可靠外接 SSD 和独立备份计划。

## 开发验证与集成建议

- 本目录独立于构建仓库；未修改主构建、未推送、未执行用户设备上的写入。
- test_grow_sd.py 验证分区边界、额外分区拒绝、GPT残留拒绝、MBR字段不变、幂等、确认令牌、错误备份、重启前禁止grow以及模拟两阶段流程。
- 所有写入测试仅作用于临时创建的普通稀疏文件。模拟 Btrfs grow 不等于真实 btrfs 命令测试。生产脚本拒绝普通文件。
- 实际成功镜像的 MBR/FAT/Btrfs superblock 已被只读提取并通过计划校验；结果见 actual-image-plan.json。
- 本次已将脚本安装到 /usr/sbin/am6bplus-grow-sd（保留 Python shebang）；务必先审阅并进行实机只读预览。不要加入 uci-defaults、first_run、rc.local 或任何自动执行钩子。
