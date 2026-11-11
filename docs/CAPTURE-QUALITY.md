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

# JSON 与 Markdown 一次生成；stdout 静默，适合批处理
python3 scripts/check_csi_capture.py capture.bin \
  --format none \
  --json-output capture-quality.json \
  --markdown-output capture-quality.md
```

`--json-output` 和 `--markdown-output` 可单独或同时使用。所有已请求的输出路径必须互不相同，
也不能与原始抓包指向同一文件；否则脚本在写入前退出 `2`。身份检查包含符号链接和硬链接，
同时保守拒绝大小写别名和父子路径。报告先写入目标目录内的临时文件，再通过已打开的目录句柄
执行原子替换；因此审计期间新建的输出符号链接也只会被替换，不能把写入重定向到抓包。
所有临时文件创建后，还会用实际父目录的 `(st_dev, st_ino)` 与规范化 basename 再次检查，
阻止两个符号链接父目录指向同一目录项。每个文件单独原子发布；JSON 与 Markdown 之间不是
跨文件事务，极端发布失败可能留下其中一份完整报告，但进程会返回 `2`。
目录创建、权限、磁盘或其他输出 I/O 失败统一返回 `2`，不会被误判为质量警告。

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

对公开 10 分钟脱敏数据，同一检查器返回 `warn/1`：

| 字段 | 值 |
| :--- | ---: |
| 外层记录 | 57,293 |
| 闭合测量组 | 7,609 |
| 8 链组 / 4 链组 | 6,714 / 895 |
| 链覆盖 | 约 0.882 |
| 记录率 / 测量率 | 95.500 / 12.683 Hz |
| 最大闭合组间隔 | 2.372654 s |
| 判定 | warn |

该警告来自 4 链与 8 链测量组混合，低于默认 98% 链覆盖阈值；文件仍可解析并进入下一层分析。

## 隐私

脚本只统计发送端数量，不输出 MAC。JSON 报告包含输入文件名、大小、SHA-256 和结构统计；
发布报告前仍应确认文件名和所在路径没有包含个人信息。
