#!/usr/bin/env bash
# Host-only guards for the pinned packit entry. Never sourced in the target image.
am6_require_runner() {
  [[ ${AM6BPLUS_GITHUB_RUNNER:-} == 1 && ${GITHUB_ACTIONS:-} == true && ${RUNNER_ENVIRONMENT:-} == github-hosted && $EUID == 0 ]] || {
    echo 'Packaging is restricted to an explicitly enabled GitHub-hosted disposable runner, as root.' >&2
    exit 1
  }
  [[ -n ${GITHUB_WORKSPACE:-} && $PWD == "$GITHUB_WORKSPACE"/* ]] || {
    echo 'Packit must be in a fresh subdirectory of GITHUB_WORKSPACE.' >&2
    exit 1
  }
  for path in tmp output src1 src2; do
    [[ ! -e $PWD/$path && ! -L $PWD/$path ]] || {
      echo "Expected fresh checkout without $path; refusing to reuse previous state." >&2
      exit 1
    }
  done
  AM6_OWNED_LOOP=''
  AM6_OWNED_IMAGE=''
  AM6_OWNED_MOUNTS=()
  trap 'am6_exit_cleanup $?' EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
}

am6_exit_cleanup() {
  local status=$1
  trap - EXIT
  am6_cleanup_owned || status=1
  exit "$status"
}

am6_assert_device() {
  [[ -n ${AM6_OWNED_LOOP:-} && -n ${AM6_OWNED_IMAGE:-} ]] || return 1
  case "$1" in
    "$AM6_OWNED_LOOP"|"${AM6_OWNED_LOOP}p1"|"${AM6_OWNED_LOOP}p2") ;;
    *) echo "Refusing non-owned device: $1" >&2; return 1 ;;
  esac
  [[ -b $1 ]] || return 1
  [[ $(losetup --noheadings --output BACK-FILE "$AM6_OWNED_LOOP") == "$AM6_OWNED_IMAGE" ]] || {
    echo 'Loop backing-file mismatch; stopping.' >&2
    return 1
  }
}

am6_cleanup_owned() {
  local i point source failed=0
  for ((i=${#AM6_OWNED_MOUNTS[@]}-1; i>=0; i--)); do
    point=${AM6_OWNED_MOUNTS[$i]}
    if mountpoint -q "$point"; then
      source=$(findmnt --noheadings --raw --mountpoint "$point" --output SOURCE) || return 1
      source=${source%%\[*}
      case "$source" in
        "${AM6_OWNED_LOOP}p1"|"${AM6_OWNED_LOOP}p2")
          am6_assert_device "$source" || return 1
          umount -- "$point" || failed=1 ;;
        *) echo "Refusing cleanup of unexpected mount: $point ($source)" >&2; failed=1 ;;
      esac
    fi
  done
  (( failed == 0 )) || return 1
  AM6_OWNED_MOUNTS=()
  if [[ -n ${AM6_OWNED_LOOP:-} ]]; then
    am6_assert_device "$AM6_OWNED_LOOP" || return 1
    losetup --detach "$AM6_OWNED_LOOP" || return 1
    AM6_OWNED_LOOP=''
  fi
  if [[ -n ${TEMP_DIR:-} && -d $TEMP_DIR && $TEMP_DIR == "$WORK_DIR"/tmp.* ]]; then
    cd "$WORK_DIR" || return 1
    rm -rf -- "$TEMP_DIR"
  fi
}
