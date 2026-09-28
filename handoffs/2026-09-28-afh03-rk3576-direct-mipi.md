# 任务交接

- 任务编号/负责人：2026-09-28 AFH03 单目方案 RK3576 MIPI 直入改版 / Codex
- 基准提交号/工作分支：`8f94786` / `codex/afh03-rk3576-direct-mipi-20260928`
- 当前目标与不包含的范围：更新既有技术路线 DOCX/PDF 与三人一月分工 DOCX，设计相机直入 RK3576 的处理闭环；2026-09-28 续改以用户确认的 24 脚相机定义和 RK 侧仅使用 2 条 MIPI 数据 lane 为准。本次仅核验公开规格和理论计算，未做上板采集、驱动移植、RTL 综合或模型测速。
- 允许修改的文件：`技术路线_AFH03与SC130GS单目神经网络测距方案.docx/.pdf`、`项目规划/AFH03单目方案一个月分工/00_三人分工与一个月实施安排.docx`、`项目规划/AFH03单目方案一个月分工/01_A_FPGA采集缓存与传输职责说明.docx`、本交接文档；`tmp/afh03-direct-rk-mipi/`仅为本次草稿与渲染检查。B/C 职责文档和工作区其余已有修改未触及。
- 输入输出/依赖的接口版本：第一周联合评审的单目新接口待冻结。原始 RAW10 帧、640×512 GRAY8 搜索图、320×256 搜索网格、候选与原图 ROI 以同一 `frame_id` 关联；候选框到原图需完成 4 倍网格坐标映射并核对块中心和扩边。模型输入是 RK 本地原图固定尺度 192×192 ROI，深度 `Zc` 单位为米。现有 v0.4 双目契约只作历史对照。
- 环境与复现命令：Windows PowerShell、Microsoft Word COM、bundled Python；DOCX 用 `python-docx` 做定点修改，PDF 用 `tmp/afh03-direct-rk-mipi/export.ps1` 从 Word 导出；`render_docx.py` 因环境无 `soffice.exe` 失败，采用 Word COM 导出后用 `pypdf`/`pypdfium2` 做文本与逐页视觉检查。
- 已执行检查及真实结果：原版 5 个 DOCX 均可由 `python-docx` 重新打开；路线 PDF 11 页，总分工 4 页，A/B/C 说明最终均 4 页。路线保留原有 6 张表及无图结构；所有 DOCX 引用和外部链接仍在，PDF 可提取全文。检查了 `不能`、`不作为`、`不得`、`禁止`，五份文档均为 0 处。与 Word PDF 对照检查页面，没有空白页或文字裁切。理论负载：240 fps RAW10 有效像素 393.216 MB/s，2 lane 平均 1.573 Gb/s/lane；120 fps 为 0.786 Gb/s/lane，均另计 CSI 开销。若以 16 位容器写内存为 629.146 MB/s；640×512 GRAY8 搜索流 78.643 MB/s；FPGA 前帧读加新帧写约 157.287 MB/s；192×192×16 bit×240 本地 ROI 为 17.695 MB/s。PCIe 2.x x1 每方向编码后理论上限 500 MB/s，搜索流占 15.7%。8 帧原图按 16 位容器为 20.97 MB、仅约 33.3 ms，实际环深按最慢往返和裁剪队列调整。续改后的 DOCX/PDF 页数及版式另见本交接后续验证记录。
- 未执行检查、阻塞与所需硬件：相机按用户确认的 24 脚定义；仍需核对实物间距、触点方向、相机 D0/D1 与 RK 接收端差分对映射、AFH03 底板 CSI 引脚和电源、相机 2-lane mode 表及 RK3576 驱动来源、板内 PCIe RC/EP/双向 DMA 样例；随后以真实板核对 120/240 fps 完整帧、V4L2 stride/RAW10 位序、CSI 错误计数、PCIe 吞吐与往返、TD 时序、CPU/RGA 预处理占用、候选召回及 NPU 延迟。公开资料未证明该模组已在 AFH03/RK3576 完成 2-lane RAW10 240 fps 驱动适配，也未证明板级 H2C/C2H 性能。240 fps 是目标模式，120 fps 是先验收的稳定链路。
- 修改文件与设计理由：相机到 RK CSI，RK 原图环与低成本灰度缩图；灰度搜索流送 FPGA 做 3×3 滤波、帧差、形态学、候选网格；返回候选直接决定同帧原图裁剪和模型调度，RK NPU/CPU 完成身份、深度、几何与轨迹。FPGA 启用/软件旁路对比候选召回、CPU、P95 和功耗，答辩用实测展示硬件价值。赛事指南物理第 25 页另列 FPGA MIPI 采集及 JPEG/LZ77 硬件压缩评分项，本直入方案按申报类别核对权重。
- 下一步及验收条件：A 先核对已确认的相机 24 脚定义、板端 2-lane 差分对、2-lane 驱动/mode 表和 PCIe 双向例程；三人批准新接口黄金样例。A 实机保存连续 RAW10 与搜索图，B 逐像素对照 FPGA 候选，C 完成两个 RKNN 试转换。第二周形成 120 fps 同帧闭环，第三周依据模组发送端 lane 速率、CSI 完整帧率、PCIe 和软件耗时评估 240 fps，第四周用独立场次与持续运行报告验收。

## 资料入口与边界

- 本地《全国大学生嵌入式芯片与系统设计竞赛'2026FPGA赛道选题指南-安路科技.pdf》物理第 9–11 页：AFH03/RK3576J/FPGA 资源、底板标称 2 路四 lane CSI、板内 PCIe2.0×1；本方案按用户确认的实际连线使用其中 2 条数据 lane；物理第 25 页：赛题评分项。指南内部部分页眉写 2025，按文件实物页码引用。
- [SC130GS 官方产品资料](https://smartsens.oss-cn-beijing.aliyuncs.com/web/products/SC130GS_V4.0.pdf)：1280×1024 @ 240 fps、RAW/Mono、1/2/4 lane MIPI；产品 flyer 未给出 2-lane RAW10 240 fps 的联合 mode 或发送端每 lane 速率，具体模组模式和 RK 驱动另核。
- [RK3576 官方产品页](https://www.rock-chips.com/a/en/products/RK35_Series/2024/1212/2033.html)与[Rockchip RK3576 Datasheet V1.5 的公开镜像](https://rockchip.fr/RK3576%20datasheet%20V1.5.pdf)：CSI、RGA、NPU/PCIe；datasheet 的 Video Input Interface 节给出 D-PHY v1.2 每 lane 2.5 Gb/s，此处按两条数据 lane 计算。
- [PCI-SIG 对 PCIe 2.0 速率说明](https://pcisig.com/how-does-pcie-30-8gts-double-pcie-20-5gts-bit-rate)：5 GT/s、8b/10b 后 x1 单方向 500 MB/s 理论上限。
- [Firefly RK3576 摄像头配置示例](https://github.com/Firefly-docs/products-docs/blob/master/zh/%E4%B8%BB%E6%9D%BF/ROC-RK3576-PC/usage_camera.md)：DPHY → CSI → RKCIF → V4L2 链路的同芯片示例，不能当作 AFH03/SC130GS 现成驱动。
- [Rockchip RKNN Model Zoo](https://github.com/airockchip/rknn_model_zoo)与[RKNN Toolkit2](https://github.com/airockchip/rknn-toolkit2)：支持 RK3576 及 YOLOv8 示例；项目专用测距回归需实际转换和校验。
- [librga 官方 FAQ](https://github.com/airockchip/librga/blob/main/docs/Rockchip_FAQ_RGA_CN.md)：具体格式和缩放支持需对板端版本查询；首版搜索图按固定 RAW10 解包、隔点取样与取高 8 位规则实现。

## 2026-09-28 两条 MIPI 数据 lane 续改验证

- 实际改动：主路线 DOCX/PDF、总分工 DOCX、A 职责说明 DOCX；B/C 职责和现有 FPGA/PCIe 处理链保持原样。相机按用户确认的 24 脚定义，RK 侧只接 D0/D1 与时钟差分对；240 fps RAW10 两条数据 lane 平均纯像素负载 1.573 Gb/s/lane，120 fps 为 0.786 Gb/s/lane。240 fps RAW8 的纯像素备选为 1.258 Gb/s/lane。
- 文档检查：bundled Python `python-docx` 可重新打开 3 个修改后的 DOCX，主路线保留 6 张表、11 页；总分工 4 张表、4 页；A 说明 3 张表、4 页。三份文档正文均无过时的“30P”或“四条 CSI lane 平均 0.786 Gb/s/lane”说法；`不能`、`不作为`、`不得`、`禁止` 均为 0 处。Word COM 导出 PDF，再用 `pypdf` 检查文字与页数、`pypdfium2` 渲染逐页检查；修正了 A 说明中表头与表体跨页的问题。B/C 文件未修改。
- 环境记录：原批量 `export.ps1` 在 Windows PowerShell 5.1 首次运行时遇到中文路径编码问题；补 UTF-8 BOM 后主路线成功导出，后续单独用 Word COM 导出总分工及 A 说明。未执行板级抓帧、传感器 mode 写入、PCIe DMA、RTL 综合和模型测速。
