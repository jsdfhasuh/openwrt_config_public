#!/bin/sh
set -eu
umask 077

source_root=${1:?Usage: install-temperature.sh OVERLAY_ROOT}
[ "$(uname -m)" = aarch64 ] || { echo 'This sensor mapping is for AM6B Plus ARM64.' >&2; exit 1; }
[ "$(cat /sys/class/thermal/thermal_zone0/type)" = cpu-thermal ]
[ "$(cat /sys/class/thermal/thermal_zone1/type)" = ddr-thermal ]
view=www/luci-static/resources/view/status/include/15_temperature.js
acl=usr/share/rpcd/acl.d/luci-am6bplus-temperature.json
for relative in "$view" "$acl"; do
    [ -f "$source_root/$relative" ]
    [ ! -L "/$relative" ] || { echo "Refusing destination symlink: /$relative" >&2; exit 1; }
done
python3 -m json.tool "$source_root/$acl" >/dev/null

mkdir -p /root/am6bplus-temperature-backups
backup=$(mktemp -d /root/am6bplus-temperature-backups/install.XXXXXX)
for relative in "$view" "$acl"; do
    mkdir -p "$backup/$(dirname "$relative")"
    if [ -e "/$relative" ]; then
        cp -p "/$relative" "$backup/$relative"
    else
        touch "$backup/$relative.absent"
    fi
done
sha256sum /etc/config/network /etc/config/firewall /etc/config/dhcp \
    /etc/config/openclash /etc/config/mosdns /etc/crontabs/root > "$backup/protected.sha256"

rollback() {
    status=$?
    if [ "$status" -ne 0 ]; then
        for relative in "$view" "$acl"; do
            if [ -f "$backup/$relative.absent" ]; then
                rm -f "/$relative"
            else
                cp -p "$backup/$relative" "/$relative"
            fi
        done
        echo "Installation rolled back; backup: $backup" >&2
    fi
    exit "$status"
}
trap rollback EXIT
trap 'exit 130' INT
trap 'exit 143' HUP TERM
for relative in "$view" "$acl"; do
    mkdir -p "/$(dirname "$relative")"
    cp "$source_root/$relative" "/$relative"
    chmod 644 "/$relative"
done
sha256sum -c "$backup/protected.sha256"
printf 'Temperature extension installed. Backup: %s\n' "$backup"
echo 'Log out of LuCI and log in again to load the new read-only ACL.'
echo 'No services were restarted; networking and DNS were not changed.'
