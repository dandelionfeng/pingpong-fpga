# 当前 AFH03 USB 同步双目技术路线

更新：2026-09-29。当前按自主命题准备。入口是[技术路线 Markdown](usb-stereo/技术路线_AFH03与USB同步双目测量方案.md)、[Word](usb-stereo/技术路线_AFH03与USB同步双目测量方案.docx)、[PDF](usb-stereo/技术路线_AFH03与USB同步双目测量方案.pdf)；[三人一个月分工](../../项目规划/AFH03_USB同步双目方案一个月分工/00_三人分工与一个月实施安排.md)另有[Word 版](../../项目规划/AFH03_USB同步双目方案一个月分工/00_三人分工与一个月实施安排.docx)，A/B/C 的个人说明见同目录。

双目模组经 RK3576J Type-C SuperSpeed USB 输入，目标为左右各 1080p60、基线 15～20 cm。RK 留存左右原图，FPGA 经板内 PCIe 接收双路搜索图和同帧双 ROI，完成候选与左右球心硬件测量；RK CPU 做双目标定、三角测量、轨迹与事件；NPU 识别球、手、球拍。采购以模组的同时帧率、硬件同曝光、全局快门、USB 格式、ARM64 支持和供电资料为依据。

本版的 60 fps、带宽、资源和延迟先按理论设计；完整链路以选定模组和 AFH03 实测为准。赛事选题三列有 FPGA MIPI CSI 采集及硬件压缩必做项，因此本版按自主命题申报。[历史 FPGA 直采 MIPI 方案](../../archive/routes/v2026-09-28_afh03_sc130gs_fpga_mipi/技术路线_AFH03与SC130GS单目测量方案.docx)、[历史 RK 直采 MIPI 方案](../../archive/routes/v2026-09-28_afh03_sc130gs_rk_mipi/技术路线_AFH03与SC130GS单目神经网络测距方案.docx)和[旧分工](../../archive/routes/v2026-09-28_afh03_sc130gs_mipi_team/00_三人分工与一个月实施安排.docx)保留原内容以便回查。

现有 FPGA 图像模块和[验证记录](../../reports/AFH03图像处理验证.md)可作为新双路搜索流水线的基础；将 640×512 单路输入改成左右 960×540 的接口、时序和资源仍需重新验证。模型输入、ROI 坐标、量化与阈值由 A/B/C 根据黄金样例联合评审。
