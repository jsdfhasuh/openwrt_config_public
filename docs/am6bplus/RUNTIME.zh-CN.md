# AM6B Plus 实机改动与复用

本页记录 2026-10-18 已在一台 AM6B Plus / Flippy 6.6.124 上验证的通用改动。
不包含密码、SSH 密钥、订阅、WireGuard 配置、设备地址表、备份或运行日志。
公开镜像不等于现用路由器的私有配置克隆。

## 新构建会包含什么

- 独立 LuCI 概览温度模块，读取 CPU 和 DDR 温度并随概览自动刷新。
- 固定上游提交与源码压缩包 SHA256 的 `v2dat` OpenWrt 软件包，安装至 `/usr/bin/v2dat`。
- `luci-app-wol`、中文翻译和原有 `etherwake`。
- `python3-requests`、`python3-yaml`，用于已有 Python 维护脚本。
- `vsftpd`，默认关闭；Samba、SFTP、Docker、pip3、Smart ARM64 核心和手动扩容工具继续保留。
- 已合并的 Flippy `r8152` 自动加载修复。

温度、软件包和依赖属于 rootfs 改动，必须重新运行第一阶段 rootfs 构建。
仅将旧 rootfs 重新 packit 打包不会获得这些功能。源锁已更新，旧锁不匹配的产物会被拒绝。
普通提交不触发完整固件构建；合并后可从 Actions 手动运行两阶段流程。

## 已刷机设备：只安装温度组件

在 Windows 仓库根目录执行。以自己的 `Host openwrt` 配置为准；新旧设备更换时先核实主机密钥。
上传目录必须是此前不存在的新目录，避免 `scp -r` 将目录重复嵌套。

```powershell
ssh openwrt "test ! -e /tmp/am6bplus-temperature-overlay"
# 仅在上一条命令成功后继续。
scp -O -r .\files\am6bplus openwrt:/tmp/am6bplus-temperature-overlay
scp -O .\scripts\am6bplus\install-temperature.sh openwrt:/tmp/install-temperature.sh
ssh openwrt "sed -i 's/\r$//' /tmp/install-temperature.sh && chmod +x /tmp/install-temperature.sh && /tmp/install-temperature.sh /tmp/am6bplus-temperature-overlay"
```

安装器校验 AArch64、`thermal_zone0=cpu-thermal`、`thermal_zone1=ddr-thermal`，
然后仅安装以下两个文件，保留替换前文件或“原先不存在”的标记：

- `/www/luci-static/resources/view/status/include/15_temperature.js`
- `/usr/share/rpcd/acl.d/luci-am6bplus-temperature.json`

备份位于输出的 `/root/am6bplus-temperature-backups/install.*`。
已有管理会话可能直接生效；如果显示不可用，请退出 LuCI 后重新登录，再刷新概览。
不自动重启 rpcd、uhttpd 或任何网络服务。ACL 仅增加两个温度文件的读取权限，不开放文件写入或命令执行。
传感器不可用或读数异常时显示不可用，不阻止其他概览模块刷新。

回退时仅处理上面两个新增文件：若对应备份有原文件则恢复；若有 `.absent` 标记则删除对应新增文件。
不要删除整个 `acl.d` 或 `status/include` 目录。

## 已刷机设备：独立 ARM64 v2dat

官方 25.12.5 软件源没有此包，旧维护脚本仍需要它；新 mosdns 的 `geo2txt` 不能直接冒充其命令行。
新固件通过本仓库的包配方构建 APK；现有设备可在 Windows 本地构建独立静态程序：

```powershell
powershell.exe -NoProfile -File .\scripts\am6bplus\build-v2dat.ps1 -WorkDir C:\Temp\v2dat-arm64-build
```

需要 Git、curl 和约 1 GiB 临时空间。目录必须不存在。
脚本下载并校验固定 Go 工具链、检出锁定源码、验证 Go 模块，设置 `GOOS=linux`、`GOARCH=arm64`、`CGO_ENABLED=0`。
不把构建工具链加入永久 PATH；输出二进制和 SHA256。不要把产物、缓存或整个工具链提交到 Git。

```powershell
scp -O C:\Temp\v2dat-arm64-build\v2dat openwrt:/tmp/v2dat-arm64
scp -O .\scripts\am6bplus\install-v2dat.sh openwrt:/tmp/install-v2dat.sh
# 将 VERIFIED_SHA256 替换为本地可信构建输出的完整小写 SHA256。
ssh openwrt "sed -i 's/\r$//' /tmp/install-v2dat.sh && chmod +x /tmp/install-v2dat.sh && /tmp/install-v2dat.sh /tmp/v2dat-arm64 VERIFIED_SHA256"
```

独立版本安装在 `/usr/local/bin/v2dat`，不属于 APK 数据库；不覆盖已有版本。
调用它的 cron PATH 应包含 `/usr/local/bin`，或使用完整路径。
已有设备上的 GeoIP `cn`（两份数据）及 GeoSite `cn`、`china-list`、`geolocation-!cn`、`category-ads-all`
共六项解包已在 `/tmp` 验证成功，没有覆盖现用规则。

## 私有配置迁移清单

- 保留新机 SSH 服务端主机密钥；仅从私有备份恢复授权公钥，不发布任何密钥。
- Samba/FTP 账号、共享目录、监听地址和访问权限从私有备份恢复，并限制在 LAN。
  不默认开放匿名访问、根目录共享或 WAN 管理端口；FTP 明文凭据只适合受信任 LAN。
- LAN/WAN、DHCP、DNS、WireGuard、OpenClash 订阅、mosdns 自定义规则和 cron 从私有备份按项迁移。
  修改网络前准备回滚，不直接覆盖整套 x86 网络配置。
- 普通 NAT 使用 fw4/nft；实机采用软件流量卸载，未启用 FullCone 或硬件卸载。
  该偏好不自动覆盖新机的防火墙区域和转发规则。
- Flippy 内核不与官方 armsr kmod ABI 兼容，不安装/升级/重装 kernel 或 kmod；不要 `apk upgrade`。
- SD 扩容仍需手动运行辅助工具。该设备已扩至约 118.7 GiB；不代表新刷卡会自动扩容。

## 定时任务复核与未解决项

新版 OpenClash 的旧资源更新命令对应关系：

| 旧命令 | 新命令 |
| --- | --- |
| `openclash_ipdb.sh` | `openclash_geo.sh ipdb` |
| `openclash_geosite.sh` | `openclash_geo.sh geosite` |
| `openclash_geoip.sh` | `openclash_geo.sh geoip` |

都位于 `/usr/share/openclash/`。迁移前备份 `/etc/crontabs/root`，只替换失效命令，不改变执行时间。
不要把本设备的 cron 原文或带凭据的脚本提交到公开仓库。

- 每分钟在线检测已从实机日志确认运行；备份上传尚未完成端到端验证。
- 两个原有 07:00 任务会同时操作 mosdns，其中 Cloudflare 优选还会停止/恢复 OpenClash。
  本次没有改动时间或执行逻辑；并发和短暂断网风险仍需另行处理。
- uhttpd 曾无响应，只重启网页服务后恢复；触发根因尚未确认，不能据此加入自动重启任务。
- 新增包配方的完整 OpenWrt 编译、重刷后的验收、长期稳定性仍需新构建验证。

## 验证入口

```sh
python3 -m unittest discover -s tests/am6bplus -v
node tests/am6bplus/test_temperature.cjs
sh -n scripts/am6bplus/install-temperature.sh
sh -n scripts/am6bplus/install-v2dat.sh
```

完整 Python 测试集应在 Linux 执行，包含 `fcntl` 和 POSIX 文件权限测试。
PR 会运行独立 Ubuntu CI。固件构建后的 rootfs 检查还会校验实际 v2dat ELF 架构、温度扩展内容、WoL 和 Python 依赖是否存在。
