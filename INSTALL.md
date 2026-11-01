# 安装与使用

## 0. 前置条件

- 路由器：支持 CSI 的 MT7986/MT7915 设备，已刷 OpenWrt（含 CSI 补丁与 `mt76-csi-daemon`）；
- 分析机：macOS 或 Linux，Python 3.8+（`numpy`、`matplotlib`）；
- 网络：路由器与分析机在同一 LAN，UDP 端口可达（默认 8888）。

数据格式见 [`docs/DATA-FORMAT.md`](docs/DATA-FORMAT.md)。

## 1. 路由器侧

```bash
# 复制脚本
scp scripts/csi-watchdog.sh scripts/mt76-wifi-tune scripts/wifi-htmode.sh root@<router>:/tmp/

ssh root@<router>
cp /tmp/csi-watchdog.sh /usr/bin/csi-watchdog
cp /tmp/mt76-wifi-tune  /etc/init.d/mt76-wifi-tune
cp /tmp/wifi-htmode.sh  /usr/bin/wifi-htmode
chmod +x /usr/bin/csi-watchdog /etc/init.d/mt76-wifi-tune /usr/bin/wifi-htmode

# 开机自动关闭会拖垮速率恢复的固件 ATF
/etc/init.d/mt76-wifi-tune enable

# 每分钟守护（daemon / 接口 / CSI 状态 / 调优重放）
grep -q csi-watchdog /etc/crontabs/root || \
  echo "* * * * * /usr/bin/csi-watchdog >/dev/null 2>&1" >> /etc/crontabs/root
/etc/init.d/cron restart
```

验证：

```bash
cat /sys/kernel/debug/ieee80211/phy*/mt76/vow_atf      # 期望 0
cat /sys/kernel/debug/ieee80211/phy1/mt76/csi_stats    # 期望 CSI enable: 1
iw dev csi0 station dump | grep -E "Station|tx bitrate"
```

## 2. 分析机侧

```bash
pip3 install numpy matplotlib

# 抓 60 秒（自动生成 bin + 热图 + 运动曲线 + 摘要）
scripts/csi_capture_session.sh 60

# 或者只抓包（Linux；参数依次为秒数、UDP 端口、输出目录）
scripts/csi_capture_linux.sh 60 8888 ./captures

# 先用标准库预检；不需要 NumPy/Matplotlib
python3 scripts/check_csi_capture.py captures/csi_udp_*.bin \
  --format json --output captures/quality.json

# 已有数据重新分析
python3 scripts/analyze_csi_capture.py out.bin --outdir ./analysis
```

`check_csi_capture.py` 返回 `0` 表示结构通过，`1` 表示有需要复核的警告，`2` 表示不应直接进入分析。
它不会输出发送端 MAC。浏览器本地版本：
<https://okwujun.pw/en/csi-capture-checker/>。

## 3. 常见问题

| 现象 | 处理 |
| :--- | :--- |
| 抓不到任何数据 | 检查 frame-type 过滤与 MAC 过滤是否设置；见教程第 5 章 |
| CSI 有数据但帧率极低 | 客户端没有持续流量（CSI 只在有包时上报） |
| Wi-Fi 突然变慢 | 见 [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md)：关闭 ATF、检查客户端带宽 |
| daemon 重启后帧计数归零 | 计数是进程内的，正常 |
