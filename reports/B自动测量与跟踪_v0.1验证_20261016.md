# B 自动测量与跟踪初版验证

日期：2026-10-16  
范围：相机坐标系下自动球心候选、双眼同帧配对、三角测量、短时预测与逐帧结果导出。

## 输入与来源

- 输入清单：`output/full-serve-20261015/manifest.json`，共 329 对帧。
- C 检测缓存：`evidence/c-20261015/full-video-detections.jsonl`，仅作为候选提示，不作为 truth。
- 双目标定：`data/calibration/ov9281-20261014/calibration_results.json`，实际 SHA-256：`e0a51683b2907d73436058d668097cf02dac2e72a2a2774262e48c323f45e616`。
- 输出坐标系：`left_camera`，单位 `m`。

## 本轮完成

- 每个输入 pair_id 均有一条 `results.jsonl` 记录。
- 使用左右眼同 pair_id、同采样时间的候选，检查极线误差、视差、深度和重投影误差后再三角测量。
- 使用真实采样时间计算 dt；连续短缺测保留 `predicted`，长缺测复位；观测、预测和无效状态分开。
- 同时导出 JSONL、CSV 和统计摘要。

## 实际统计

```json
{
  "total": 329,
  "observed_2d_pair": 29,
  "observed_3d": 29,
  "predicted": 41,
  "invalid": 26,
  "ambiguous": 0,
  "no_candidate": 274
}
```

这些是处理计数，不是准确率。当前包没有逐帧运动 Mask，因此 C 缓存候选是主要输入，正式接入 A 的 Mask 后应在同一入口替换候选来源。

## 复现命令

```powershell
& '.\.venv\Scripts\python.exe' tools/b_tracking_replay.py `
  --input output/full-serve-20261015/manifest.json `
  --calibration data/calibration/ov9281-20261014/calibration_results.json `
  --detections-jsonl evidence/c-20261015/full-video-detections.jsonl `
  --output _deliveries/b_tracking_replay_20261016
```

C++ 轨迹/球心回归：MSVC 19.43.34808.0、OpenCV 4.10.0，8/8 CTest 通过。OpenCV 4.13 环境未取得，因此不能声称已用 4.13 编译。

## 未完成与下一步

- 未接入真实 A 运动 Mask；当前没有可用 Mask 文件。
- 未完成 pipeline_b_module 公共注册适配；需要 A 的最新共用接口在实际 Git 基准上继续接入。
- 未完成正式球台世界坐标、事件判罚、RKNN、FPGA 上板、Linux/ARM 和传感器同步精度验证。
- 未有独立人工三维 truth，因此不宣称真实米制精度达标。
