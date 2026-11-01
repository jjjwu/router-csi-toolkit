#!/bin/sh
# CSI watchdog for OpenWrt / GL-MT6000.
#
# Runs from cron every minute. It checks:
#   1. mt76-csi-daemon is running;
#   2. the dedicated csi0 interface exists;
#   3. debugfs csi_stats still reports CSI enable: 1.
#
# It does not restart just because no stations are associated: CSI only
# produces frames when a client is active, so an idle network is normal.
#
# It also re-applies the Wi-Fi throughput tuning: the MediaTek firmware
# "VoW ATF" (airtime fairness) keeps a station's downlink rate pinned at
# MCS0 after the client goes idle, so it is disabled. See:
# https://okwujun.pw/en/openwrt-wifi-slow-after-idle/

DAEMON_NAME="mt76-csi-daemon"
INIT_SCRIPT="/etc/init.d/mt76-csi"
CSI_IFACE="csi0"
LOG_TAG="csi-watchdog"

log() {
	logger -t "$LOG_TAG" "$*"
}

if ! pgrep -f "$DAEMON_NAME" >/dev/null 2>&1; then
	log "daemon missing; restarting"
	"$INIT_SCRIPT" restart
	exit 0
fi

if ! ip link show "$CSI_IFACE" >/dev/null 2>&1; then
	log "$CSI_IFACE missing; reloading wifi"
	wifi reload
	sleep 5
fi

STATS=$(find /sys/kernel/debug/ieee80211 -name csi_stats 2>/dev/null | head -n 1)
if [ -n "$STATS" ]; then
	enable=$(sed -n 's/^CSI enable: //p' "$STATS" | head -n 1)
	if [ "$enable" != "1" ]; then
		log "CSI enable=$enable; restarting daemon"
		"$INIT_SCRIPT" restart
	fi
fi

# --- Wi-Fi throughput tuning -------------------------------------------
# vow_atf=1 (firmware default) prevents the rate adaptation from
# recovering after an idle client's downlink collapses to MCS0.
for f in /sys/kernel/debug/ieee80211/phy*/mt76/vow_atf; do
	[ -w "$f" ] || continue
	cur=$(cat "$f" 2>/dev/null)
	if [ "$cur" != "0" ]; then
		if echo 0 > "$f" 2>/dev/null; then
			log "vow_atf: $cur -> 0 ($f)"
		fi
	fi
done

