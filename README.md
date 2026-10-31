# Router CSI Toolkit

Scripts and tooling extracted from a real GL-MT6000 (MT7986) Wi-Fi CSI lab:
**256 subcarriers @ 80 MHz, 2 Tx x 4 Rx chain records, 95.5 chain records/s for 10 minutes** on OpenWrt + mt76.
Those records group into 7,609 measurements, or about **12.64 independent snapshots/s**.

> 本仓库是「路由器 Wi-Fi CSI」项目的脚本部分。配套教程与完整手册见站点
> **https://csi.okwujun.pw**（中文 `/zh/`，English `/en/`）。

Canonical repository: <https://github.com/jjjwu/router-csi-toolkit>

Public dataset: <https://doi.org/10.5281/zenodo.23434789>

## What is included

| 文件 | 运行位置 | 用途 |
| :--- | :--- | :--- |
| `scripts/csi_capture_session.sh` | 分析机（macOS/Linux） | 一键定时抓包 + 自动分析 + 摘要 |
| `scripts/csi_capture_linux.sh` | 分析机（Linux） | 纯标准库接收 + 落盘 |
| `scripts/csi_capture.py` | 分析机 | UDP 原始流接收器，由两个 capture 脚本调用 |
| `scripts/analyze_csi_capture.py` | 分析机 | 幅度热图 + 1 秒滚动运动指标 |
| `scripts/csi-watchdog.sh` | 路由器（cron 每分钟） | 守护 daemon / 接口 / CSI 状态，并重放性能调优 |
| `scripts/wifi-htmode.sh` | 路由器 | HE80（CSI 高精度）↔ HE40（客户端稳定）切换 |
| `scripts/mt76-wifi-tune` | 路由器（开机） | 关闭会拖垮速率恢复的固件 VoW ATF |

## What is NOT included

- **首启整机配置脚本**：不同设备的接口名、上游网段和 Wi-Fi 策略不同，本公开工具包不包含环境特定脚本。
- **Wi-Fi 固件**（`mt7986_wm.bin` 等）：版权属于 MediaTek，请从官方渠道获取
  （linux-firmware / openwrt/mt76）。需要的版本与 MD5 见 `docs/TROUBLESHOOTING.md`。
- **内核 CSI 补丁**：属于上游 GPL 工程（ossiemarks/openwrt 的 mt76 分支），
  请从上游获取；本仓库只提供“怎么用”的脚本与文档。
- 实测原始数据集（58MB）：见站点下载页。

## Quick start

```bash
# 1) 分析机：接收 CSI（默认 UDP 8888）
scripts/csi_capture_session.sh 60          # 抓 60 秒并自动出图

# 2) 路由器：守护与调优（复制到路由器后执行一次）
scp scripts/csi-watchdog.sh      root@<router>:/usr/bin/csi-watchdog
scp scripts/mt76-wifi-tune       root@<router>:/etc/init.d/mt76-wifi-tune
scp scripts/wifi-htmode.sh       root@<router>:/usr/bin/wifi-htmode
ssh root@<router> 'chmod +x /usr/bin/csi-watchdog /etc/init.d/mt76-wifi-tune /usr/bin/wifi-htmode;
                   /etc/init.d/mt76-wifi-tune enable;
                   echo "* * * * * /usr/bin/csi-watchdog >/dev/null 2>&1" >> /etc/crontabs/root'
```

## Verified environment

| 项目 | 值 |
| :--- | :--- |
| 路由器 | GL.iNet GL-MT6000（MT7986A + MT7976） |
| 系统 | OpenWrt SNAPSHOT / Linux 6.18 |
| Wi-Fi 固件 | 20260515（MD5 `3ce21edabe201608e7bec0dd16898019`） |
| CSI 栈 | ossiemarks CSI 补丁 + `mt76-vendor` + `mt76-csi-daemon` |
| 实测 | 10 分钟 57,293 条链记录 / 95.5 条每秒 / 7,609 个测量组 / 约 12.64Hz / 无 >5 秒断流 / daemon RSS ≈5.2MB |

## License

- 脚本：MIT（见 `LICENSE`）
- 文档：CC BY 4.0（署名即可转载）

## Disclaimer

刷机与修改固件有风险；请先备份并演练回退。本项目仅用于个人技术研究，
不得用于未经同意的监控。
