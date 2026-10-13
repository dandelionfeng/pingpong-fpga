# RKNN 部署指南（target = rk3576）

## 当前状态

**RKNN_PREPARED_NOT_EXECUTED**

原因：本机未安装 `rknn-toolkit2`，且配置的 PyPI 镜像（清华源）没有该包 —— Rockchip 只在官方 index 发布。按任务要求不擅自安装来源不明确的软件，因此本轮只交付脚本与说明。

同时：**没有 AFH03 真机**，所以无论后续是否转换成功，以下说法一律**禁止**：

- ~~BOARD VERIFIED~~
- ~~RK3576 REAL-TIME VERIFIED~~

最多只能写 **RKNN CONVERSION VERIFIED ON HOST**（主机侧转换验证）。

## 前置条件

```bash
# 建议在 Linux + Python 3.8~3.10 环境（rknn-toolkit2 对 Windows 支持有限）
pip install rknn-toolkit2 -i https://pypi.org/simple
# 或从 Rockchip 官方仓库取对应版本 wheel：
#   https://github.com/airockchip/rknn-toolkit2
```

版本需记录到转换日志里（`rknn-toolkit2 --version`）。

## 要转换的模型

| 模型 | ONNX | 输入 | 输出 | 建议精度 |
| --- | --- | --- | --- | --- |
| YOLO ball+racket | `ball_racket_yolov8n_v1.onnx` | `[1,3,640,640]` | `[1,6,8400]` | FP16 → INT8 |
| Pose | `yolov8n_pose.onnx` | `[1,3,640,640]` | `[1,56,8400]` | FP16 → INT8 |
| BallTrack | `balltrack_tracknetv3.onnx` | `[1,15,288,512]` | `[1,1,288,512]` | **建议只 FP16** |

### 为什么 BallTrack 建议只做 FP16

- 输入 15 通道（median + 4 帧），通道间动态范围差异大；
- 输出是 sigmoid 热图，后续要用 **阈值 0.5 + 轮廓解码** 得到球心；
- 热图峰值附近的量化误差会直接平移球心，进而放大到双目匹配与三维误差；
- 球在画面里只占几十像素，热图响应本身就不高（实测未检出帧的 heatmap max 仅 0.05~0.34）。

若一定要 INT8，必须**先量化后逐帧比对球心误差**，而不是只看输出 tensor 的数值差。

## 执行步骤

```bash
# FP16（先做这个）
python vision/c_perception_v2/export_rknn.py --model yolo --precision fp16
python vision/c_perception_v2/export_rknn.py --model pose --precision fp16
python vision/c_perception_v2/export_rknn.py --model balltrack --precision fp16

# INT8（需要校准集）
python vision/c_perception_v2/export_rknn.py --model yolo --precision int8
python vision/c_perception_v2/export_rknn.py --model pose --precision int8
```

## 校准集

见 `calibration_manifest.txt`。要点：

- **校准不是训练**：不更新权重、不算梯度、不改标签；
- 共 128 张，来自公开 v2 train/val（确定性等距抽样）+ BNDSTT 域内帧（**只读图像，不用标签**）；
- **不使用 quick_test**。

### 特别注意：YOLO 的坐标输出不要量化

YOLOv8 的输出 `[1,6,8400]` 前 4 个通道是**像素坐标**（cx, cy, w, h），数值范围 0~640。
如果把这 4 个通道也做 INT8 量化，球心坐标会有可达数像素的系统误差。
建议用 `hybrid_quantization`，把输出层保持 FP16：

```python
rknn.config(..., quantized_dtype='w8a8', quantized_algorithm='normal')
rknn.hybrid_quantization_step1(dataset='dataset.txt')
# 编辑生成的 .quantization.cfg，把输出节点设为 float
rknn.hybrid_quantization_step2(model_input='...', data='...', model_quantized='...')
```

## 主机侧验证（允许声称的范围）

转换完成后在主机上用 RKNN simulator 或 onnxruntime 做对比，记录：

1. 每个模型输出 tensor 的 max/mean abs diff；
2. **球心误差**（不是 tensor 误差）——用公开 test 图比对 YOLO 的 ball center；
3. **手腕关键点误差**（px）——比对 pose 的 17 个关键点；
4. BallTrack 热图解码后的球心误差分布；
5. 转换日志、`rknn-toolkit2` 版本、目标平台字符串。

允许的结论措辞：**RKNN CONVERSION VERIFIED ON HOST**。

禁止的措辞（没有真机时，以下全部禁止）：

- ~~BOARD VERIFIED~~
- ~~RK3576 REAL-TIME VERIFIED~~
- ~~RKNN RUNS ON BOARD~~
- ~~上板通过~~
- ~~AFH03 实测通过~~

## 板端待办（需要 A 同学 / 真机）

- [ ] 在 RK3576 上跑 RKNN runtime，确认真实 NPU 延迟（当前 PC 参考：YOLO 39 ms、pose 45 ms）；
- [ ] 确认三模型是否可共享 NPU 而不互相阻塞，核对 60 FPS 目标；
- [ ] 确认 BallTrack 的 15 通道输入在板端的零拷贝组装方式；
- [ ] 确认 INT8 后球心误差是否满足双目匹配要求（这是本项目的关键指标）。

## 模型文件是否入库

`.onnx` 与 `.rknn` **都不提交 Git**，继续走 `.gitignore` + `artifacts/README.md` 清单引用。
