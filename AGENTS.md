# AGENTS.md
## Scope
- Applies to the whole repository.
- This is an OpenWrt build configuration repo, not a general application repo.
- Main work happens in GitHub Actions and shell scripts.
- Prefer minimal, targeted changes over broad cleanup.

## Repository Layout
- `.github/workflows/openwrt_x86.yml` - main OpenWrt build workflow.
- `.github/workflows/openwrt_x86_24_10.yml` - OpenWrt 24.10 workflow.
- `.github/workflows/test.yml` - lightweight script smoke workflow.
- `custom.sh` - prepares custom files and patches OpenWrt sources during CI.
- `feeds.conf` - feed definitions copied into the OpenWrt tree before `feeds update`.
- `x86.config` - OpenWrt config seed used to generate `.config`.
- `root/` - files copied into the firmware image.
- `rc.local` and `adguardhome.yaml` - custom image files moved by `custom.sh`.

## Agent Rule Sources
- No repository-local Cursor rules were found.
- No `.cursorrules` file was found.
- No `.cursor/rules/` directory was found.
- No `.github/copilot-instructions.md` file was found.
- This file is the repository-local instruction source for coding agents.

## Working Rules To Preserve
- Read related files before editing.
- Ask only when a missing fact materially changes the result.
- Make the smallest necessary change.
- Prefer readable code over clever code.
- Do not silence problems with bypasses like `eslint-disable` or `@ts-ignore`.
- Remove dead code instead of commenting it out.
- Reuse existing scripts and patterns before introducing new ones.
- Run validation after changes whenever practical.

## Build Commands
- Full OpenWrt build flow is defined in `.github/workflows/openwrt_x86.yml`.
- Main source checkout currently uses `git clone https://github.com/openwrt/openwrt.git "$BUILD_OPENWRT"`.
- 24.10 build uses `git clone --branch "$REPO_BRANCH" --single-branch "$REPO_URL" "$BUILD_OPENWRT"`.
- Feed update: `./scripts/feeds update -a`
- Feed install: `./scripts/feeds install -a`
- Seed config: `cat "$BUILD_ROOT/x86.config" > .config`
- Expand config: `make oldconfig`
- Download sources: `make download -j8 V=s`
- Normal build: `make -j$(($(nproc)+1)) world V=s`
- Debug build: `make -j1 world V=s`

## Test And Verification Commands
- There is no conventional unit test suite in this repository.
- There is no `pytest`, `bats`, `go test`, `npm test`, or similar local harness checked in.
- There is no dedicated lint workflow or pre-commit config checked in.
- Current `test` workflow only smoke-runs `custom.sh`.
- Smoke command: `bash custom.sh "$ARCHITECTURE" "$BUILD_ROOT"`
- Full custom-script invocation in build workflow: `bash custom.sh "$ARCHITECTURE" "$BUILD_ROOT" "$BUILD_OPENWRT"`
- Shell syntax validation: `bash -n custom.sh`
- Workflow YAML validation can be done by loading it with Python YAML locally.

## Single Test Guidance
- There is currently no true single-test command because the repo has no test framework.
- The smallest meaningful targeted verification is a single package build inside OpenWrt.
- Example package-only verification used by the 24.10 workflow:
- `make package/feeds/packages/python-pip/clean V=sc`
- `make package/feeds/packages/python-pip/compile V=sc`
- Use package-only builds to isolate failures before running `make world`.
- If a future test framework is added, update this file with exact single-test commands.

## Workflow Notes
- `openwrt_x86.yml` tracks upstream default branch behavior and is more exposed to upstream breakage.
- `openwrt_x86_24_10.yml` is intended to be more stable and pins OpenWrt to `openwrt-24.10`.
- The 24.10 workflow rewrites official feed branches in `feeds.conf` at runtime.
- Both workflows rely on GitHub-hosted Ubuntu runners.
- CI behavior matters more than local workstation assumptions.

## Style Guidelines
- Primary languages here are shell and GitHub Actions YAML.
- Follow existing file style unless there is a strong reason not to.
- Use 2-space indentation in YAML.
- Keep shell scripts simple and linear.
- Prefer ASCII in new files unless an existing file clearly uses non-ASCII content.
- Comments should be sparse and only explain non-obvious logic.
- Keep comments in English.

## Shell Conventions
- Match syntax to the shebang.
- Do not write Bash-only syntax into a `#!/bin/sh` script.
- Use `snake_case` for local variables and function names.
- Use uppercase for exported or workflow-provided environment variables.
- Quote paths and variable expansions by default: `"$path"`, `"$BUILD_OPENWRT"`.
- Avoid unnecessary subshells and pipelines.
- Prefer explicit checks over silent failure.
- When editing scripts that mutate files or disks, add guard conditions instead of broad refactors.

## Naming Conventions
- Shell functions should use verb-first names when possible, such as `check_unformatted_disk`.
- Variables should be descriptive and use `snake_case`.
- Environment variables should stay uppercase, for example `BUILD_ROOT`, `BUILD_OPENWRT`, `ARCHITECTURE`.
- Workflow names should clearly indicate target branch or purpose.
- New workflow files should use descriptive names like `openwrt_x86_24_10.yml`.

## Imports, Dependencies, Formatting, Types
- There are no language-level import style rules like Python or TypeScript imports here.
- Dependency management is mainly external package installation in GitHub Actions and OpenWrt feeds.
- Reuse existing apt dependency lists unless a change is necessary.
- If adding dependencies, add the smallest required package set.
- Preserve the existing ordering and grouping in workflow files where practical.
- Keep one logical operation per workflow step when possible.
- Do not mass-reformat `x86.config`.
- Treat `x86.config` as a generated-style config seed and change only required symbols.
- Avoid unrelated whitespace churn.
- This repo does not currently contain typed application code.
- If typed code is introduced later, use explicit types and avoid `any`.

## Error Handling
- Existing scripts do not consistently use strict mode.
- Do not blindly add `set -euo pipefail` to existing scripts without checking behavior impact.
- For existing scripts, prefer local defensive checks and clear logging.
- For new Bash scripts, consider strict mode only if the entire script is designed for it.
- Fail early around destructive commands such as `mv`, `rm`, `mkfs.ext4`, and `mount`.
- Validate source and destination paths before moving or deleting files.

## Known Hazards
- `custom.sh` is a critical part of the image assembly flow.
- `custom.sh` moves files out of the repo workspace during CI, so call order matters.
- `root/check_and_format_disk.sh` uses `#!/bin/sh` but contains array-like Bash syntax; treat it as compatibility-sensitive.
- The OpenClash core download URL in `custom.sh` is sensitive to architecture value and upstream URL behavior.
- Upstream OpenWrt and feed changes can break builds without any repo-local code changes.
- `python3-pip` is currently enabled in `x86.config` and has been a known build-risk area.
- A known failure mode is `BackendUnavailable: Cannot import 'setuptools.build_meta'` during package builds.

## Python-Pip Guidance
- If `python-pip` fails, first determine whether the failure is in host build or target build.
- Prefer package-only compile checks before retrying full firmware builds.
- Do not assume Ubuntu runner packages will fix hostpkg Python problems inside OpenWrt.
- If `python3-pip` must stay enabled, prefer stable branches and isolated package verification.
- Investigate `feeds/packages/lang/python/python-pip` and related host dependencies before changing unrelated files.

## Change Strategy
- Prefer extending the existing workflows over replacing them.
- Keep `main` and `24.10` workflows separate unless a change clearly belongs in both.
- Reuse `feeds.conf`, `custom.sh`, and `x86.config` patterns before adding new files.
- If a workflow-specific difference is needed, isolate it in the workflow rather than forking many config files.
- Avoid broad cleanup of unrelated quoting, naming, or formatting while fixing a targeted issue.

## Validation Checklist
- Read the touched workflow or script from top to bottom before editing.
- Confirm argument order for any shell script you invoke or modify.
- Validate shell syntax with `bash -n` for changed Bash scripts.
- Validate changed workflow YAML before finishing.
- If changing package selection, confirm the relevant `CONFIG_PACKAGE_*` symbol in `x86.config`.
- If changing build flow, verify whether both `debug` and non-debug paths still make sense.

## Commit And Review Guidance
- Keep commits focused on one concern.
- Mention the affected workflow, package, or build failure in commit messages.
- When a change is a workaround for upstream instability, say so explicitly.
- Do not commit generated OpenWrt source trees or build artifacts.
- Do not commit secrets, SSH keys, or tokens.

## When Unsure
- Prefer the 24.10 workflow for stability-sensitive work.
- Prefer evidence from repo files and CI logs over assumptions.
- Call out facts versus guesses in analysis.
- If a behavior depends on upstream OpenWrt internals, verify it before making broad changes.
