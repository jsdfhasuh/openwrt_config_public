# Validation before the first published run

- OpenWrt 25.12.5 and its release-feed commits verified locally; five third-party plugin commits locked.
- Actual ARM64 make defconfig passed for all 87 explicitly requested packages plus APK. The current x86 intent is preserved through the documented migration table.
- Actual kernel/boot/DTB/modules/firmware downloads matched their hashes; ARM64 Mihomo hash/ELF header verified.
- Both workflows passed actionlint 1.7.7. Own host runtime passed shellcheck 0.10.0. Python compilation and configuration/artifact identity unit tests passed.
- Twelve pinned-upstream adaptation tests passed: exact context and original hashes, retained core functions, transformed bash syntax, cleanup simulation, foreign-mount refusal, runner and pre-write gates.
- Rootfs compilation and actual upstream image assembly have not run locally. GitHub Actions is the requested execution environment for those stages; see the exact published commit/run and artifact STATUS for real outcomes.
- A clean source preparation attempt encountered a cloud CONNECT tunnel 403; that was not counted as success. Local final configuration validation used previously downloaded SHA-verified checkouts.
- No hardware boot, network, thermal, Wi-Fi, service/container or recovery validation has occurred. Build/pack success must never be described as AM6B Plus hardware acceptance.

The earlier local prototype used a self-contained ext4 image writer. It was retired before publication when the user requested two workflows with a real upstream packit call. Its toy filesystem tests are not claimed as testing this upstream Btrfs assembly. Current scripts invoke the pinned upstream core via an exact SD-only adapter.


## 首次 GitHub 构建与收集修复（2026-10-12）

运行 38193861104 / 提交 e23a89468c0b1a1acb6972e648987b6232008421
在约四小时后正常结束 `make world`，日志记录生成标准
`openwrt-armsr-armv8-generic-rootfs.tar.gz` 和额外的
`openwrt-armsr-armv8-generic-targz-rootfs.tar.gz`。87 项显式包配置复核通过。
本仓库收集脚本的 `*rootfs.tar.gz` 匹配了两个文件，违反其错误的唯一性假设，
导致整个工作流失败，未上传可打包 rootfs。首败保留，不能把该 run 写成通过。

首败日志 artifact ID：11729323376；ZIP SHA256：
`70dd5a6239fc49d07c3faf05faa11e8181174a796dbfa278163e3ff3bb9c8cf6`。

修复为精确选择标准文件名，拒绝缺失或符号链接，不以另一个名称静默代替；
新增两产物并存与标准产物缺失的回归测试。配置/收集动作日志另行保留。
失败时单独上传这两个已知生成文件到 diagnostic-rootfs artifact，
不包含源码缓存、凭据或整个构建目录；打包 Action 仍只接受成功运行的正式 artifact。
本次修改没有更改 OpenWrt 源码、包集合、固定版本、打包安全限制或超时。
修复后的全量构建及实际打包须以新 run 终态为准。
