# 任务交接

- 任务编号/负责人：2026-09-29 AFH03 USB 同步双目技术路线与三人分工 / Codex。
- 基准提交号/工作分支：`3e6a226` / `codex/usb-stereo-route-20260929`。
- 当前目标与不包含的范围：按用户决定将现行路线改为 USB 接入的成品同步双目模组，并按自主命题准备；设计目标为左右各 1920×1080、同时 60 fps、15～20 cm 基线。更新技术路线、四周分工及 A/B/C 个人说明；旧 MIPI 单目版本完整归档。摄像头型号尚待选定，本任务提供理论预算和验证入口，未进行模组采购或板级实测。
- 允许修改的文件：`plans/current/usb-stereo/` 新路线、`项目规划/AFH03_USB同步双目方案一个月分工/` 新分工，`README.md`、`plans/current/README.md`、`项目规划/项目实施规划.md`、`项目规划/接口与验收契约.md`、`docs/实施前待确认项.md`、`archive/README.md`、`archive/moved-files-sha256.csv`、`data/manifests/afh03-vendor-package.md`、`fpga/afh03_image/README.md` 及本交接文档；原两份 MIPI 路线和旧分工只移动到 `archive/routes/v2026-09-28_*`，未改原文。
- 输入输出/依赖的接口版本：`pair_id`、左右原图、960×540 GRAY8 双路搜索图、256×256 GRAY8 双 ROI、候选与球心质量为语义草案。USB 左右同步证明、USB3 Type-C 主机模式、板内 PCIe 与模组格式须由 A/B/C 首周核对；二进制协议、世界坐标、量化与阈值按 `项目规划/接口与验收契约.md` 联合评审后确定。旧 H10 UDP v0.4 属归档资料。
- 环境与复现命令：Windows PowerShell；bundled Python `C:\Users\20743\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`；Word COM。`python -m unittest discover -s tests -v`、`python tools/run_image_pipeline_tests.py`、`python tools/check_repo.py --staged`。文档生成与 QA 的任务临时脚本在被忽略的 `tmp/` 中，原始文字留在同名 Markdown，Word/PDF 本次同步生成，之后需人工审校修改。
- 已执行检查及真实结果：USB 3 5 Gb/s、PCIe 2.0×1 与 RKNN 资料使用 USB-IF、PCI-SIG、Rockchip 官方资料核对；AFH03 Type-C USB3 信号、两路 USB2 Host 与板内 PCIe 见本地厂商硬件手册，竞赛选题三和自主命题条款见本地指南。理论计算：双目 1080p60 GRAY8 248.832 MB/s，YUYV 497.664 MB/s，左右搜索图 62.208 MB/s，双 ROI 7.86432 MB/s，合计 PCIe H2C 纯载荷 70.07232 MB/s；8 对紧凑 GRAY8 原图 33.1776 MB。7 个移动文件的 SHA-256 与大小逐项相同，追加于归档 CSV。5 份 DOCX 均可打开；Word COM 导出主 PDF 5 页、分工与个人说明各 2 页；Poppler 渲染全部页面并完成视觉检查。`tmp/validate_usb_docs.py` 通过 DOCX/PDF 内容、本地链接和归档哈希核对。`python -m unittest discover -s tests -v` 为 5/5 通过；`python tools/run_image_pipeline_tests.py` 三组随机停顿种子与灰度模块测试通过。现有 FPGA 测试仅证明旧基础内核，尚非 USB 双目新链路验证。
- 未执行检查、阻塞与所需硬件：真实模组尚未选定，未执行 USB3 5000M 枚举、同时 1080p60、同曝光时间误差、PCIe DMA 并发、双路 FPGA 时序/NPU/三维误差、板级功耗与持续运行。`render_docx.py` 因本机没有 `soffice.exe` 报错；采用 Word COM 导出 PDF、Poppler 逐页渲染进行替代视觉 QA。需要最终模组的 UVC/ARM64 SDK、模式表、同步和基线证明，以及 AFH03 板卡与量具。
- 修改文件与设计理由：USB 摄像头直接到 RK3576J，FPGA 处理每帧双路运动候选和同帧左右 ROI 球心，使三角化依赖 FPGA 的像素观测；CPU 负责标定和三维轨迹，NPU 负责球手拍身份。独立的 MIPI 路线保留为可追溯历史，README 入口只指向新路线。新文档尽量采用正向、通俗表述，并把理论值与未来实测分开。
- 下一步及验收条件：A 先取得模组同时模式、硬件曝光同步、USB3 与 ARM64 资料，核对 AFH03 Type-C 主机与 PCIe 并发；B 准备双目黄金图、标定与 FPGA 双路参考；C 固定数据和模型输入草案。三人共同评审 `pair_id`、图像格式、坐标、ROI 和版本后再实现二进制协议。第一阶段以同一对图经 FPGA 返回双候选与球心、RK 产生可复核静态三维球心为验收出口。

本交接的资料链接及具体技术依据见 `plans/current/usb-stereo/技术路线_AFH03与USB同步双目测量方案.md`。受限厂商文件留在本地 `vendor/`，GitHub 保存定位与校验清单。
