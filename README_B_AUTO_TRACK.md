# B 自动测量与跟踪

本交付使用相机坐标系完成双目自动测量与短时跟踪。入口为 `tools/b_tracking_replay.py`，它读取 329 对帧清单、双目标定和 C 实际推理缓存；缓存中的球框只作为候选提示，经过左右同帧配对、极线/视差/正深度/重投影检查后才输出三维点。

## 运行

```powershell
& '.\\.venv\\Scripts\\python.exe' tools/b_tracking_replay.py `
  --input output/full-serve-20261015/manifest.json `
  --calibration data/calibration/ov9281-20261014/calibration_results.json `
  --detections-jsonl evidence/c-20261015/full-video-detections.jsonl `
  --output _deliveries/b_tracking_replay_20261016
```

结果：`results.jsonl`、`results.csv`、`summary.json` 和 `representative_frames.json`。三维字段固定为 `coordinate_frame=left_camera`、`unit=m`；`track_state` 区分 `observed`、`predicted` 和 `invalid`。

没有逐帧 Mask 的帧会被清楚记录为无候选或无效。A 接入真实 Mask 后，应在同一帧身份接口中替换候选来源并继续复用球心、三角测量和跟踪代码。
