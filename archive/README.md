# 历史方案、采购资料与调试工程

这里保存技术路线切换过程中的原始文件。目录名 `vYYYY-MM-DD_平台_主题` 是**归档版本标识**：日期取自文档版本、正文日期或文件时间，并不表示接口协议已经冻结。搬迁前后每个文件的 SHA-256 相同，逐项记录在 [校验清单](moved-files-sha256.csv)。旧文件正文和表格保持原样；其中的价格、器件选择与性能目标应按原时间背景阅读。

## 技术路线

| 归档版本 | 主要内容 | 代表文件 |
| --- | --- | --- |
| v2026-09-20_h10_rk3566 | H10-PH1A180、双 OV9281、网口连接 RK3566；实施规划 v1.4、接口契约 v0.4、早期分工与硬件核查 | [实施规划](routes/v2026-09-20_h10_rk3566/项目规划/项目实施规划_v1.4.md) · [接口契约](routes/v2026-09-20_h10_rk3566/项目规划/接口与验收契约_v0.4.md) |
| v2026-09-22_h10_zero3e | H10、双 OV9281、ZERO 3E 的项目规划和路线摘要；另存当日团队操作说明 | [规划书](routes/v2026-09-22_h10_zero3e/乒乓球发球辅助系统项目规划书.docx) · [路线摘要](routes/v2026-09-22_h10_zero3e/核心硬件及技术路线.docx) |
| v2026-09-23_h10_fpga_primary | FPGA 主通路、AI 辅助通路的架构评审 | [评审方案](routes/v2026-09-23_h10_fpga_primary/乒乓球发球系统新版架构评审方案.docx) |
| v2026-09-23_h10_full_fpga_dvp | 全 FPGA、DVP、无 FSIN 的同步备选研究 | [评审方案](routes/v2026-09-23_h10_full_fpga_dvp/全FPGA无FSIN同步方案.docx) |
| v2026-09-24_dr1m90g | MLK-F3P-DR1M90G 板卡备选管线 | [技术路线](routes/v2026-09-24_dr1m90g/技术路线_MLK-F3P-DR1M90G.docx) |
| v2026-09-24_afh03_dual | AFH03-AFC03、双目相机的早期管线 | [技术路线](routes/v2026-09-24_afh03_dual/技术路线_MLK-AFH03-AFC03-2GB.docx) |
| v2026-09-24_generic_fpga | 未指定最终板卡的双目 FPGA 管线 PDF | [技术路线](routes/v2026-09-24_generic_fpga/技术路线.pdf) |
| v2026-09-27_afh03_dual_nv1100m | AFH03、双 NV1100M 摄像头方案 | [详细方案](routes/v2026-09-27_afh03_dual_nv1100m/技术路线_AFH03与双NV1100M详细方案.docx) |
| v2026-09-28_afh03_sc130gs_fpga_mipi | SC130GS 经 FMC 转接板直入 FPGA 的单目路线 | [技术路线](routes/v2026-09-28_afh03_sc130gs_fpga_mipi/技术路线_AFH03与SC130GS单目测量方案.docx) |
| v2026-09-28_afh03_sc130gs_rk_mipi | SC130GS 经 RK3576J MIPI CSI 直入的单目路线 | [Word](routes/v2026-09-28_afh03_sc130gs_rk_mipi/技术路线_AFH03与SC130GS单目神经网络测距方案.docx) · [PDF](routes/v2026-09-28_afh03_sc130gs_rk_mipi/技术路线_AFH03与SC130GS单目神经网络测距方案.pdf) |
| v2026-09-28_afh03_sc130gs_mipi_team | 以上 RK 直入 MIPI 单目路线当时的三人分工和个人说明 | [总分工](routes/v2026-09-28_afh03_sc130gs_mipi_team/00_三人分工与一个月实施安排.docx) |

## 采购资料

| 归档版本 | 原文件的适用背景 | 代表文件 |
| --- | --- | --- |
| v2026-09-21_h10_zero3e | H10、双 OV9281、ZERO 3E；Word 与 Markdown 属同一阶段的清单 | [Word 清单](procurement/v2026-09-21_h10_zero3e/硬件选型与采购参考清单.docx) · [Markdown 参考](procurement/v2026-09-21_h10_zero3e/硬件器件选型与采购参考.md) |
| v2026-09-27_afh03_options | AFH03 搭配 DVP 双目或 SC130GS 单目的两种询价草案 | [购买物品清单](procurement/v2026-09-27_afh03_options/购买物品清单.pdf) |

当前 AFH03 USB 同步双目自主命题路线见[当前方案索引](../plans/current/README.md)。历史 `handoffs/` 是执行记录，按日期留在原目录；其中提到的旧文件名可由本页及校验清单定位。历史采购报价只供比较，采购前以现用板卡、相机实物和供应商报价重新核对。

## 2026-09-29 通用 USB 双目 1080p60 设计

[技术路线](routes/v2026-09-29_afh03_usb_stereo_1080p60/route/技术路线_AFH03与USB同步双目测量方案.md)与同目录 `team/` 保留模组选定前的路线和分工。2026-09-30 的下一历史阶段改用双 OV9281 的 720p60/800×600@100 设计，2026-10-04 现行路线已改为 72°、固定 YUY2 60fps 与 PC 算法先行安排。此处为完整副本归档，11 个文件大小与 SHA-256 记录在清单中。

## 2026-10-04 整理的历史版本

本轮额外归档 26 个文件，逐项来源、原路径、字节数和 SHA-256 见[本轮清单](sync-2026-10-04-sha256.json)。其中 11 份路线/分工从提交 `c638158281dff65ec9a7750ac85ae4b4d5f9dfcf` 读取原始 Git 字节；旧指南、相机说明和到货方案保留整理前工作区字节。空目录占位文件留存路径用于追溯。

| 归档目录 | 适用历史背景 | 入口 |
| --- | --- | --- |
| `routes/v2026-09-30_afh03_usb_stereo_720p60/` | 100°/2.1 mm 双目、FPGA 局部球心、旧四周分工 | [路线](routes/v2026-09-30_afh03_usb_stereo_720p60/route/技术路线_AFH03与USB同步双目测量方案.md) · [分工](routes/v2026-09-30_afh03_usb_stereo_720p60/team/00_三人分工与一个月实施安排.md) |
| `camera-selection/v2026-09-30_100deg_2p1mm/` | 旧 100° 商详、两模式预算与原图清单 | [选型核对](camera-selection/v2026-09-30_100deg_2p1mm/docs/OV9281_USB双目模组选型核对.md) · [清单](camera-selection/v2026-09-30_100deg_2p1mm/data/manifests/ov9281-usb-module.md) |
| `planning/v2026-10-02_afh03_delay_h10/` | 预期先拿相机和 H10 的分拆预验证与细排期，已由 PC 先行版取代 | [Markdown](planning/v2026-10-02_afh03_delay_h10/AFH03延期后的技术方案与人员安排_2026-10-02.md) · [Word](planning/v2026-10-02_afh03_delay_h10/AFH03延期后的技术方案与人员安排_2026-10-02.docx) |
| `collaboration/v2026-09-19_h10_rk3566/` | 旧 FSIN/UDP/RK3566 GitHub 分工与规则文本 | [GitHub 指南](collaboration/v2026-09-19_h10_rk3566/docs/协作使用指南.md) · [原规则](collaboration/v2026-09-19_h10_rk3566/AGENTS.md) |
| `scaffolding/v2026-09-19_h10_rk3566/` | 旧 FPGA 直采/UDP/ROI 和 RK3566 空目录占位路径 | 8 个 `.gitkeep` 的原路径及哈希见本轮清单 |

旧 [Agent 交接包](routes/v2026-09-20_h10_rk3566/项目规划/Agent协作交接包.md)继续保留原文。现行入口为[GitHub 指南](../docs/协作使用指南.md)、[AI agent 指南](../docs/AI_agent协作指南.md)和[当前方案](../plans/current/README.md)。历史相对链接及执行命令保留当时写法，定位被迁移文件时使用校验清单中的 `source_path` 与 `archive_path`；归档中的 AGENTS.md 和旧任务卡只作资料读取。

## 2026-10-05 TD 调试工程与代码归档

[调试归档入口](fpga-debug/v2026-10-05_td_experiments/README.md)保存旧 PH1A180 工具链测试和 PH1A90 基础图像实验的 24 个源码、约束、脚本与报告，按原目录布局保留字节。[源码校验清单](fpga-debug/v2026-10-05_td_experiments/files-sha256.json)记录原路径、归档路径、大小、SHA-256 与原 Git blob。

本机 20 组生成工程、仿真输出和调试辅助文件共 366 个文件，集中到被忽略的 `archive/local-debug/v2026-10-05_td_experiments/`。[本地工程摘要](fpga-debug/v2026-10-05_td_experiments/local-projects-summary.json)仅登记位置、数量和大小；完整工程、数据库、日志、波形及逐文件清单保留在本机。当前开发从 [FPGA 说明](../fpga/README.md)与[现行方案](../plans/current/README.md)进入。
