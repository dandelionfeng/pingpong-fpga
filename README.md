# FPGA competition 2026

发球测量系统 1.2.1，基于 AFH03 RK3576J、PH1A90 FPGA 与双 OV9281。处理链路为双目采集、FPGA 运动 Mask、NPU 球与手拍识别、CPU 双目几何与运动学、数据回传和本地回放。

## 下载与运行

**[下载最终发布包：源码包.rar](https://github.com/dandelionfeng/pingpong-fpga/releases/download/fpga-competition-2026-final/FPGA-competition-2026-final.rar)**（195,836,989 字节，195.84 MB）。GitHub 附件名为 FPGA-competition-2026-final.rar，与本地“源码包.rar”内容及哈希一致。这是完整离线竞赛包；解压后双击“发球测量系统.exe”，保留同目录的 app、runtime、data。支持 Windows 10/11 64 位，PC 查看样例无需安装 Python。

GitHub 自动生成的 Source code.zip/tar.gz 用于阅读与开发源码。运行展示使用上面的 RAR 附件，其中包含 PC 离线环境、板端部署包、模型、bit 流、FPGA 工程和 serve_01、serve_02 两份回放。

```powershell
.\发球测量系统.exe --self-test --report 检查结果.json
```

SHA-256：`f918ff1d5f11fea70a886c2f2c20d694467ae3a461f4c054073b3bc873d5368c`。完整目录、安装条件及现场步骤见 [随包说明](README.txt)；发布身份见 [final-release.json](manifests/final-release.json)。

## 现场展示

使用原已配置好的 AFH03 Linux 系统，板端需 Python 3.11、RKNN 运行库及原生 OpenCV 动态库。电脑需 J3 串口/J4 ADB 驱动，重新下载 FPGA 位流需匹配版本的安路 TD/BitWriter。录制按钮默认使用 `/dev/video73`；节点变化时按随包说明手动指定。

流程：J4 部署检查 → J3 短录制 → 等待 `RECORDING_SAVED` → J4 取回 → 查看新记录。只有两份历史回放随包保留，共 642 对帧元数据；历史输入 JPEG 已省略。接板后的新记录会严格校验实际输入和 SHA-256。

本次发布执行离线自检与缓存/取回逻辑回归；真实相机、FPGA/NPU 和 USB 数据回传的接板验收另行记录。详见 [发布与离线审核](docs/发布与离线审核.md)。

## 源码导航

| 目录 | 内容与入口 |
| --- | --- |
| app | PC 工作台、算法、RK 脚本、UI、冻结配置及硬件来源记录 |
| source/native | C++ 原生处理链路与 CMake 构建配置 |
| hardware/rtl | FPGA 七级运动 Mask 自研 RTL |
| data | 历史六组编号索引；最终 RAR 实际保留两组回放 |
| docs | 系统、操作、重建、验证和最终技术报告 |
| manifests | 模型、完整发布包与发布附件的校验清单 |
| tools | 启动器、EXE 构建、源码检查和离线依赖恢复工具 |
| tests | 9 项 PC 路径、取回缓存与回放指针回归 |
| licenses | 随源码发布的第三方许可 |

每个源码目录的 README 提供用途、入口和文件索引。完整运行依赖保存在本地工作目录和 Release 附件中；生成物与历史材料存入外部归档，Git 只跟踪明确的源码与文档范围。

## 开发与验证

```powershell
python tools/check_repo.py
python -m unittest discover -s tests -v
```

EXE 构建需要 Windows Python 3.13 和 `tools/requirements-build.txt` 中的依赖：`python tools/build_windows.py`。`app/version.json` 管理冻结模型、标定、坐标与阈值；发布整理保持其原字节。

仓库：[dandelionfeng/pingpong-fpga](https://github.com/dandelionfeng/pingpong-fpga)。本次通过 `codex/final-release-20261103` 的 PR 合入 main，提交标题统一为 `FPGA competition 2026`，保留既有历史与旧版本标签。
