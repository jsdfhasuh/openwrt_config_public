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
