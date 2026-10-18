#!/bin/sh
set -eu
umask 077
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

binary=${1:?Usage: install-v2dat.sh BINARY SHA256}
expected=${2:?Supply the SHA256 from the trusted build}
[ "$(uname -m)" = aarch64 ]
[ "${#expected}" -eq 64 ]
case "$expected" in *[!0-9a-f]*) echo 'Expected lowercase SHA256' >&2; exit 1 ;; esac
printf '%s  %s\n' "$expected" "$binary" | sha256sum -c -
[ "$(od -An -tx1 -N6 "$binary" | tr -d ' \n')" = 7f454c460201 ]
[ "$(od -An -tu2 -j18 -N2 "$binary" | tr -d ' \n')" = 183 ]

if command -v v2dat >/dev/null 2>&1; then
    echo 'v2dat already exists. Review it before replacing a working or APK-owned binary.' >&2
    exit 1
fi
destination=/usr/local/bin/v2dat
[ ! -e "$destination" ] && [ ! -L "$destination" ]
mkdir -p /root/am6bplus-v2dat-backups
backup=$(mktemp -d /root/am6bplus-v2dat-backups/install.XXXXXX)
cp -p /etc/apk/world "$backup/apk-world"
sha256sum /etc/config/network /etc/config/firewall /etc/config/dhcp \
    /etc/config/openclash /etc/config/mosdns /etc/crontabs/root /etc/apk/world \
    > "$backup/protected.sha256"
mkdir -p /usr/local/bin
stage=/usr/local/bin/.v2dat-install-$$
installed=0
cleanup() {
    status=$?
    rm -f "$stage"
    if [ "$status" -ne 0 ] && [ "$installed" -eq 1 ]; then
        if [ "$(sha256sum "$destination" | cut -d ' ' -f 1)" = "$expected" ]; then
            rm -f "$destination"
        fi
    fi
    exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' HUP TERM
cp "$binary" "$stage"
chmod 755 "$stage"
"$stage" --help > "$backup/help.txt"
printf '%s  %s\n' "$expected" "$stage" | sha256sum -c -
ln "$stage" "$destination"
installed=1
sha256sum -c "$backup/protected.sha256"
printf '%s  %s\n' "$expected" "$destination" > "$backup/installed.sha256"
printf 'Installed %s; backup: %s\n' "$destination" "$backup"
echo 'Standalone binary, not APK-managed. No services or update jobs were run.'
