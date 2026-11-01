# Changelog

## Unreleased

- Add `scripts/check_csi_capture.py`, a standard-library capture quality preflight for framing, closed groups,
  chain/subcarrier consistency, timestamp gaps and non-empty I/Q.
- Add JSON and Markdown reports without emitting transmitter MAC addresses.
- Link the equivalent browser-local checker at `https://okwujun.pw/{zh,en}/csi-capture-checker/`.

## 0.1.2 - 2026-10-31

- Make `csi_capture.py` use the documented UDP port `8888` by default.
- Add a real UDP integration test, privacy guard, CI workflow and `CITATION.cff`.

## 0.1.1

- Bundle `scripts/csi_capture.py` so the capture helpers work from a standalone download.
- Remove environment-specific paths and the internal analysis-host address.
- Clarify that 95.5 is the chain-record rate; 7,609 measurement groups give about 12.64 independent snapshots/s.

## 0.1.0 — 2026-10-11

- 首次发布：采集/分析/守护/带宽切换脚本
- 文档：UDP 数据格式、排障（ATF 与 40MHz 塌陷）
- 已验证环境：GL-MT6000（MT7986）+ OpenWrt SNAPSHOT + 20260515 固件
