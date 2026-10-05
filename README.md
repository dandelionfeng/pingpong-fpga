# FPGA AI 乒乓球发球测量项目

2026 FPGA 创新设计赛道团队仓库，按**自主命题**准备。当前方案采用 AFH03（RK3576J + PH1A90SEG324）与 USB 同步双 OV9281；先在电脑上完成算法闭环，再接入相机和板卡。

## 从哪里开始

先看[当前方案索引](plans/current/README.md)。完整技术路线提供 [Markdown](plans/current/usb-stereo/技术路线_AFH03与USB同步双目测量方案.md)、[Word](plans/current/usb-stereo/技术路线_AFH03与USB同步双目测量方案.docx)和 [PDF](plans/current/usb-stereo/技术路线_AFH03与USB同步双目测量方案.pdf)。[三人总分工](项目规划/AFH03_USB同步双目方案一个月分工/00_三人分工与一个月实施安排.md)及同目录四份 Word 是最新职责说明：前半段讲工作与工具，后半段讲具体实现；三份个人文件最后附有可复制的 agent 提示词。

| 人员 | 当前主责 | 个人说明 |
| --- | --- | --- |
| A（蒲公英） | 文件输入与原图缓存、共用 C++ 核心、CPU 整数参考与 FPGA 前三级、USB/PCIe/DDR 适配及系统集成 | [Markdown](项目规划/AFH03_USB同步双目方案一个月分工/01_A_USB采集与FPGA链路职责说明.md) · [Word](项目规划/AFH03_USB同步双目方案一个月分工/01_A_USB采集与FPGA链路职责说明.docx) |
| B | FPGA 后四级与掩膜打包、CPU 球心、标定、三维、跟踪和事件 | [Markdown](项目规划/AFH03_USB同步双目方案一个月分工/02_B_FPGA视觉与三维测量职责说明.md) · [Word](项目规划/AFH03_USB同步双目方案一个月分工/02_B_FPGA视觉与三维测量职责说明.docx) |
| C | 数据与三类模型、PC 实际推理、导出与 RKNN 部署准备、独立评分 | [Markdown](项目规划/AFH03_USB同步双目方案一个月分工/03_C_AI模型训练与部署职责说明.md) · [Word](项目规划/AFH03_USB同步双目方案一个月分工/03_C_AI模型训练与部署职责说明.docx) |

## 当前路线与完成状态

正式目标采用 72°、3.6 mm 手动调焦双 OV9281 USB3 模组，YUY2 左右拼接 2560×720@60 fps，每眼 1280×720，安装基线 150～200 mm。相机由 RK3576J 的 J4 USB3 OTG0 采集；RK 保存原始 Y 和 8 对原图，每眼生成 640×360 搜索图，经 PCIe1 交给 FPGA。FPGA 的七级运动前端返回两张 1 bit Mask；CPU 在同帧原图的 256×256 ROI 内求球心、三维轨迹和离手/最高点/触拍事件，NPU 异步识别 ball、hand、racket。

暂无实物时，文件输入、CPU 整数运动前端和 PC 三类模型替代相应硬件后端，后续测量核心共用。工作目标分为 10 月 4～8 日模块交付、9～12 日 PC 集成与部署材料、13～28 日按实际到货逐层联调。详细任务见[PC 算法闭环与部署验收](docs/PC算法闭环与部署验收.md)。这些是实施目标，当前完整 PC 闭环、七级运动 RTL 和实机部署尚待实现与验证。

旧 TD 调试工程、基础图像内核、测试脚本和验证记录已集中到[调试归档](archive/fpga-debug/v2026-10-05_td_experiments/README.md)，保留原文件与 SHA-256。当前 FPGA 开发从 [fpga/README.md](fpga/README.md)进入；参考旧行缓存或流控代码时，按新任务明确选取并重新验证。[相机选型核对](docs/OV9281_USB双目模组选型核对.md)区分当前 72° 方案与此前 100° 商详；最终 SKU、YUY2 模式、同步、手动曝光及完整帧率以所购实物确认。帧率、精度、延迟、功耗和板端资源均待实测。竞赛提交期限沿用项目记录 2026-11-04。

## 协作与资料入口

- [GitHub 使用指南](docs/协作使用指南.md)、[AI agent 协作指南](docs/AI_agent协作指南.md)、[项目规则](AGENTS.md)和[贡献流程](CONTRIBUTING.md)说明怎样领取任务、提交、评审和交接。
- [实施规划](项目规划/项目实施规划.md)、[接口与验收契约](项目规划/接口与验收契约.md)和[实施前待确认项](docs/实施前待确认项.md)是现行入口；二进制布局、模型输入与判罚阈值继续按负责人评审草案管理。
- [历史归档](archive/README.md)保留旧路线、旧分工、旧协作指南及原始校验和。归档正文按当时背景阅读，现行开发从 `plans/current/` 进入。
- [板卡资料清单](data/manifests/afh03-vendor-package.md)、[相机资料清单](data/manifests/ov9281-usb-module.md)和[大文件管理](artifacts/README.md)记录本地资料、来源与哈希。厂商 SDK、原始视频、模型权重和生成工程留在本地。
- [交接索引](handoffs/README.md)定位当前任务和历史执行记录；[报告索引](reports/README.md)区分文档核查、历史模块测试与之后的完整系统结果。

`fpga/`、`vision/` 和 `contracts/` 目前保留开发入口，现行七级运动 RTL 尚待实现。方案建议的 `software/pc_pipeline/`、`tools/fixtures/`、`tests/pc_pipeline/` 尚待具体任务创建，目录名不代表功能已实现。新任务从最新已评审的 `origin/main` 开始；若依赖尚未合并的工作，明确基准提交和依赖 PR。
