# 历史方案和采购资料

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

## 采购资料

| 归档版本 | 原文件的适用背景 | 代表文件 |
| --- | --- | --- |
| v2026-09-21_h10_zero3e | H10、双 OV9281、ZERO 3E；Word 与 Markdown 属同一阶段的清单 | [Word 清单](procurement/v2026-09-21_h10_zero3e/硬件选型与采购参考清单.docx) · [Markdown 参考](procurement/v2026-09-21_h10_zero3e/硬件器件选型与采购参考.md) |
| v2026-09-27_afh03_options | AFH03 搭配 DVP 双目或 SC130GS 单目的两种询价草案 | [购买物品清单](procurement/v2026-09-27_afh03_options/购买物品清单.pdf) |

当前两条 AFH03 单目路线见[当前方案索引](../plans/current/README.md)。历史 `handoffs/` 是执行记录，按日期留在原目录；其中提到的旧文件名可由本页及校验清单定位。历史采购报价只供比较，采购前以现用板卡、相机实物和供应商报价重新核对。
