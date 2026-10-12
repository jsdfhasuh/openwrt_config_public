#!/bin/sh
# Fresh experimental AM6 image only. Connect directly to an isolated PC first.
# Never replace an existing network configuration.
[ ! -s /etc/config/network ] || exit 0
. /lib/functions/uci-defaults.sh
board_config_update
ucidef_set_interface_lan 'eth0' 'static'
board_config_flush
exit 0
