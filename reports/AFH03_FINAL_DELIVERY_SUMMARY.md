# AFH03 最终交付包（V3 Unified YOLOv8n · FP16 RKNN）

日期：2026-10-30　分支：`codex/c-pc-detector`

## 1. 交付物

| 项 | 值 |
| --- | --- |
| ZIP | `artifacts/handoff/AFH03_FINAL_V3_FP16_FOR_CAPTAIN.zip` |
| 大小 | **16,584,628 B（15.82 MB）** |
| SHA256 | `a9cef00ce356ef47cc0210632d92229ba40fcf2509814cb602237c5e0aa9114f` |
| 内含文件 | 13 个（12 个内容文件 + SHA256SUMS.txt） |
| 解压验证 | ✅ 解压后逐文件重算 SHA256，**12/12 匹配，0 失败** |

## 2. 包内清单

| 文件 | 大小 | SHA256 |
| --- | ---: | --- |
| `v3_960_fp16_dfl_layout.rknn` | 13,038,908 | `1bcff6ff23f1a26428742e6a8e7c9acaf5b130171dbf2072cbaace6c62bcad0b` |
| `pingpong_yolov8n_gray_3cls_v3_960_960.onnx` | 12,161,114 | `b779c88e08f8bd15275e301c00bcbfb9c737fc22fa4ef1c358008f0b932254ba` |
| `README_CAPTAIN.md` | 6,671 | `ada81949c37ce577ee3a66bd1d302f1fd61d4e6b3d0f03127beda75b3049e28c` |
| `MODEL_CARD.md` | 3,153 | `80cd56c507b3a6e0d91f7ec31aa3838ce50efdee23f91574343c492d43f4b5ec` |
| `EVALUATION_REPORT.md` | 3,001 | `49164f1e0732950dd22ba12379fda15e02346b14e827dea0a92c3633dd3e4ffc` |
| `DEPLOYMENT_GUIDE.md` | 4,263 | `0ad64000a280427aafc4909df8720c531b8fe0a1f056025dad6b5bc5823a1b05` |
| `STATUS.md` | 2,585 | `384a2ea8ffcfa804513eca67e96a04db99fb20d48078e708d1d47444de1f074d` |
| `cpp/rknn_v3_detect_dfl.cpp` | 17,745 | `df0f1f333d5170ec47451864b1304cd3fdc8f7e7eaae66d9c2fe6bf11ba38d01` |
| `cpp/CMakeLists_dfl.txt` | 1,397 | `3a282c7e1cd578bb3c0ba26c2d1219b8b3ceeeb4bf6f408f90e9c8e31f280ea6` |
| `cpp/build.sh` | 266 | `c19c3fe8bdada7a2820625976712835d683b969e78197cdacb85b9ca2a662a90` |
| `cpp/configs/fp16_960.yaml` | 816 | `a34a01ab7d1ae91b4812ebef0727c64f82d020bffed56ba25d339bdd86494948` |
| `accuracy_fp16_509.json` | 737 | `e1cbbefec5d101699b04e5674184509e32797fdbdfe0452ee6a7e40e05cae32d` |
| `SHA256SUMS.txt` | — | 上述 12 个文件的校验和 |

## 3. 精度（509 张固定 val，PC/模拟器，非板端）

| 类别 | P | R | F1 | AP50 |
| --- | ---: | ---: | ---: | ---: |
| Ball | 0.810 | 0.510 | 0.626 | 0.487 |
| Hand | 0.692 | 0.559 | 0.618 | 0.507 |
| Racket | 0.764 | 0.756 | 0.760 | 0.691 |

阈值 ball 0.20 / hand 0.25 / racket 0.25。FP16 与 FP32 差异 ≤1.3 点。

## 4. 状态

**已完成**：FP16 RKNN 转换（真文件、真哈希）、输出布局修复、509 张精度评测、C++ DFL 解码源码、
算法级数值核验、完整打包与解压校验。

**未验证（BLOCKED）**：AFH03 板端加载、板端精度、NPU FPS（单/双核）、C++ 真实编译、
OV9281 接入、RGA/FPGA 预处理、与 BallTrack 联调。

**INT8 未作为默认交付**：Ball Recall 0.470 < 0.49 门槛（Hand/Racket 达标），
模型与修复报告在 `artifacts/rknn_deployment/v3_960_int8_v2/`。

## 5. 保护核对

- V3 权重/ONNX 未改动（`b779c88e…` 一致）
- 旧 FP16 RKNN（`f6354f2e…`）与 V2/V3 交付 ZIP 未覆盖
- 未修改 main、未 force push、未改动任何 C++ 正式判罚模块
