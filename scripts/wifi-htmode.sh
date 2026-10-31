#!/bin/sh
# Switch the GL-MT6000 5GHz radio (radio1) channel width / HT mode.
#
#   HE80 / VHT80 : 80MHz - CSI experiment mode (256 subcarriers).
#                  A 40MHz-only client (e.g. older Mac) collapses to
#                  MCS0 on this BSS; see
#                  https://csi.okwujun.pw/en/wifi-slow-troubleshooting/
#   HE40 / VHT40 : 40MHz - daily-use mode. The 40MHz client is stable
#                  (~400 Mbps), CSI still streams but with half the
#                  bandwidth (fewer subcarriers).
#
# Usage:  wifi-htmode.sh HE80 | HE40 | VHT80 | VHT40

MODE="$1"
case "$MODE" in
	HE80|HE40|VHT80|VHT40) ;;
	*)
		echo "usage: $0 <HE80|HE40|VHT80|VHT40>" >&2
		exit 1
		;;
esac

uci set wireless.radio1.htmode="$MODE"
uci commit wireless

# Keep the CSI daemon metadata consistent with the radio width.
case "$MODE" in
	*80) BW=80 ;;
	*40) BW=40 ;;
esac
if [ -f /etc/mt76-csi.conf ] && grep -q '^bandwidth' /etc/mt76-csi.conf; then
	sed -i "s/^bandwidth.*/bandwidth = $BW/" /etc/mt76-csi.conf
	/etc/init.d/mt76-csi restart >/dev/null 2>&1
fi

wifi reload
sleep 5
echo "radio1 htmode=$MODE (CSI bandwidth=$BW)"
iw dev csi0 info 2>/dev/null | grep -E "channel"
