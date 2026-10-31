# CSI 数据格式（UDP payload 与抓包文件）

## 0. 两种容器，别搞混

| 容器 | 结构 | 出现位置 |
| :--- | :--- | :--- |
| **UDP payload** | `24 字节头 + int16 I/Q` | `mt76-csi-daemon` 发到 UDP 8888 的每个包 |
| **抓包文件记录** | `double ts(8) + uint16 len(2) + payload` | `csi_capture*.sh` 落盘文件（len 通常 1048） |

解析抓包文件时先读 10 字节记录头，再按下面的 payload 结构解析。

字节序：目标机小端（little endian）。每条记录 = 24 字节头 + 交错 int16 I/Q。

| 偏移 | 字段 | 类型 | 说明 |
| ---: | :--- | :--- | :--- |
| 0 | `ts` | uint32 | **微秒**时间戳（实测每秒 ≈1,000,000） |
| 4 | `ta[6]` | uint8[6] | 发送端 MAC |
| 10 | `rssi` | int8 | dBm |
| 11 | `snr` | uint8 | dB |
| 12 | `data_bw` | uint8 | 带宽编码 |
| 13 | `pri_ch_idx` | uint8 | 主信道索引 |
| 14 | `rx_mode` | uint8 | 接收模式 |
| 15 | `pad` | uint8 | 对齐 |
| 16 | `data_num` | uint16 | 子载波数（本项目 = 256） |
| 18 | `tx_idx` | uint16 | 发送链 |
| 20 | `rx_idx` | uint16 | 接收链 |
| 22 | `chain_info` | uint16 | **bit15 = 本次测量最后一条链** |
| 24… | I/Q | int16 × `data_num` × 2 | 每子载波 4 字节（I、Q） |

## 解析示例（Python）

```python
import struct

HDR = struct.Struct("<I6sbBBBBBHHHH")   # ts, ta, rssi, snr, bw, ch, mode, pad, num, tx, rx, chain
REC = struct.Struct("<dH")              # 仅抓包文件：double ts + payload len

def parse_payload(buf: bytes):
    ts, ta, rssi, snr, bw, ch, mode, _pad, n, tx, rx, chain = HDR.unpack_from(buf, 0)
    iq = struct.unpack_from(f"<{n * 2}h", buf, HDR.size)
    i = iq[0::2]
    q = iq[1::2]
    last = bool(chain & 0x8000)   # 本次测量的最后一条链
    return dict(ts=ts, rssi=rssi, snr=snr, subcarriers=n, tx=tx, rx=rx, i=i, q=q, last=last)

def iter_capture(path: str):
    """遍历抓包文件：先解 10 字节记录头，再解 payload。"""
    with open(path, "rb") as f:
        while True:
            head = f.read(REC.size)
            if len(head) < REC.size:
                return
            _file_ts, length = REC.unpack(head)
            payload = f.read(length)
            if len(payload) < HDR.size:
                return
            yield parse_payload(payload)
```

一次完整测量由 4 条（2×2）或 8 条（2×4）链记录组成，用 `(ts, ta)` 分组、`chain_info` bit15 判断结束。

## 速率与存储估算

| 测量率 | 数据率（8 链 × 1KB） | 存储 |
| ---: | ---: | ---: |
| 100 次/秒 | ≈0.8 MB/s（6 Mbps） | ≈2.9 GB/小时 |
| 1000 次/秒 | ≈8 MB/s（64 Mbps） | ≈29 GB/小时 |
| 3000 次/秒 | ≈24 MB/s（190 Mbps） | ≈86 GB/小时 |
