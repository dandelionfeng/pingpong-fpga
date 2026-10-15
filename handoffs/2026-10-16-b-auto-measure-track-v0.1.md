# B 自动测量与跟踪交接

负责人：B / cluepiggie。

## 交付

- `tools/b_tracking_replay.py`：读取 manifest、标定和 C 检测缓存，逐 pair 输出双眼候选、相机系三维、跟踪状态。
- `_deliveries/b_tracking_replay_20261016/`：329 对帧的 JSONL、CSV 和摘要。
- `reports/B自动测量与跟踪_v0.1验证_20261016.md`：复现命令、统计和限制。

## 给 A 的接入口

A 提供同 pair_id、eye、sample_time_ns、reference_id 的 640x360 decoded Mask 与 1280x720 gray；替换 C 候选输入后，继续调用现有 `ball_measurement::measure_pair` 和 B trajectory `triangulate`/`Tracker`。输出保留 `coordinate_frame=left_camera`、`unit=m`、`observed/predicted/invalid`。

## 当前限制

本轮没有逐帧 Mask，C 缓存不是人工真值；公共 `pipeline_b_module` 注册及 A/C 联调尚未完成。世界坐标、事件判罚、RKNN、FPGA 和正式上板不在本轮范围。
