# CSI 抓包质量预检

`scripts/check_csi_capture.py` 使用 Python 标准库，在 NumPy/Matplotlib 分析之前检查本项目
`csi_capture*.sh` 生成的抓包容器。

浏览器本地版本：<https://okwujun.pw/zh/csi-capture-checker/>。

## 快速使用

```bash
python3 scripts/check_csi_capture.py capture.bin \
  --format markdown \
  --output capture-quality.md

python3 scripts/check_csi_capture.py capture.bin \
  --format json \
  --output capture-quality.json
```

退出码：

| 退出码 | 判定 | 含义 |
| ---: | :--- | :--- |
| 0 | pass | 快速结构检查通过，可进入下一层分析 |
| 1 | warn | 文件可解析，但有截断、缺链、混用、倒序或长空档 |
| 2 | fail | 没有完整组、payload 头损坏、没有非零 I/Q 或格式不匹配 |

## 检查内容

- 外层 `<float64 timestamp><uint16 length>` 分帧；
- 24 字节 CSI payload 头；
- `chain_info` bit 15 闭合的测量组；
- 每组 Tx/Rx 链记录数与众数；
- `data_num` 子载波分布；
- 相邻闭合组的时间间隔、p50、p95、最大空档；
- I/Q 字节数和是否全零；
- 时间倒序、重复链和非标准尾部记录。

默认快速筛查基线：

- 至少 10 个闭合测量组；
- 链组和子载波覆盖达到 98%；
- 最大闭合组间隔不超过 5 秒；
- 至少一条记录包含非零 I/Q。

阈值可通过 `--min-groups`、`--min-coverage` 和 `--max-gap` 修改。它们是工程筛查参数，
不是 IEEE 一致性测试，也不证明人体检测模型有效。

## 重要边界

时间空档不等于网络丢包。它可能来自 UDP 丢包、接收端落盘延迟、CSI 触发条件未命中、
目标客户端没有流量，或 daemon 已经停止。要区分原因，必须同时保存 daemon 日志、接口计数和
接收端丢包计数。

未闭合尾组通常是停止采集时截断，应隔离而不是补零。`chain_info` bit 15 能判断组边界，
但不能证明每条物理链都携带了可用、非零的 CSI。

## 已验证样本

对公开 60 秒脱敏样本的预期结果：

| 字段 | 值 |
| :--- | ---: |
| 外层记录 | 2,777 |
| 闭合测量组 | 347 |
| 尾部未闭合链记录 | 1 |
| 每完整组链记录众数 | 8 |
| 子载波众数 | 256 |
| 最大闭合组间隔 | 1.005951 s |
| 判定 | pass |

样本下载与 SHA-256：<https://okwujun.pw/zh/datasets/>。

## 隐私

脚本只统计发送端数量，不输出 MAC。JSON 报告包含输入文件名、大小、SHA-256 和结构统计；
发布报告前仍应确认文件名和所在路径没有包含个人信息。
