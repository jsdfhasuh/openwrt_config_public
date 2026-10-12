# 验证记录

## 状态

- 开发与隔离测试完成；未在用户 SD、eMMC 或实机上执行。
- 36 项 unittest 通过；Python 语法编译检查通过。
- 稀疏普通文件模拟 128,000,000,000 字节 SD，验证 MBR 字段变化、已有数据哨兵不变、幂等。
- 两阶段运行测试 mock 掉 sysfs、挂载信息、Btrfs 命令和硬件身份，仅在测试创建的普通文件上写入。
- 没有真实 loop 挂载、真实 Btrfs resize 或 AM6B Plus 硬件测试。模拟成功不代表硬件已通过。

## 镜像依据

[成功打包任务 38238567698](https://github.com/jsdfhasuh/openwrt_config_public/actions/runs/38238567698) 的 packaging-manifest.json 与实际 img.gz 经只读校验：

- MBR p1：start=8192，size=786432，type=0x0c。
- MBR p2：start=794624，size=6291456，type=0x83。
- p3/p4 全零；FAT32 和 Btrfs 头签名符合。
- 实际 Btrfs UUID：0ce70fdb-78c5-4fb9-8639-92ed5ddc7694。
- 假设实际卡容量正好 128000000000 字节，p2 新长度 249204736 扇区，127592824832 字节。
- 只读提取的头部保留在 actual-mbr.bin、actual-fat.bin、actual-superblock.bin，计划结果在 actual-image-plan.json。

注意：上面 UUID 来自构建镜像，用来记录验证依据，不作为用户实际 SD 的硬编码标识；运行时读取并确认实际 UUID/CID/容量。

## 依赖核实

成功 rootfs 压缩包中已确认含 fcntl 的 aarch64 musl 扩展、argparse、hashlib、json、pathlib、subprocess、struct、uuid 和 /usr/bin/btrfs。新 pip3 版配置仅追加 python3-pip，当前仍应等待最终产物清单核实。

## 独立审阅与修正

- 文件系统增长后不再用整盘 buffered raw superblock 读回判定结果，避免分区/整盘缓存别名造成假失败；改用 Btrfs 实时设备信息。
- SD 的设备节点 major:minor 必须对应已检查的 sysfs type=SD 节点，避免误标节点指向 eMMC。
- p1、p2 内核起始/长度均检查；只允许既有两分区布局。
- 已挂载的 Btrfs 设备按 major:minor 校验，支持合法 /dev/root 别名。
- 只接受原始单设备 devid=1；不盲目对其他设备号执行 max。
- 文档明确 Btrfs 已扩大后不能直接恢复旧分区前缀；重启后须再次停业务服务。

[Btrfs 官方说明](https://btrfs.readthedocs.io/en/stable/btrfs-filesystem.html) 说明 filesystem show 与 resize 的行为；resize 不自动调整分区表，bare max 针对默认 devid=1。

## 重跑

```sh
python3 -m py_compile am6bplus-grow-sd.py test_grow_sd.py
python3 test_grow_sd.py
```

这是开发机的无硬件测试命令。不要为了测试而把真实设备传给脚本的 --apply。

独立复核额外进行了 3 种隔离故障注入：pwrite 返回短写 256、pwrite 抛 OSError、fsync 抛 OSError；均停止且未调用 resize。此检查同样只作用于临时普通稀疏文件。

第二阶段强制读取第一阶段原始 JSON，校验 CID、容量、根 UUID、p2 起始扇区和目标长度；新增缺失/损坏/换卡/字段不匹配拒绝测试。最终身份和原始前缀复查移动至 os.sync 之后，缩短写前检查窗口。协作锁不阻止其他不守锁的 root 工具，指南要求禁止并行改盘/换卡/重挂载。
