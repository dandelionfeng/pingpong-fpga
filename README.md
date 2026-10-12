# FPGA AI 乒乓球发球测量项目

正式目标为 AFH03（RK3576J + PH1A90SEG324）与 72°/3.6 mm 双 OV9281 USB3。当前先完成 PC 算法闭环：每眼 1280×720 原图保留在 CPU，640×360 搜索图经七级运动前端生成 Mask，B 测量球心、三维和事件，C 提供 ball/hand/racket 语义与独立评分。

## 当前入口

| 要做什么 | 从这里开始 |
| --- | --- |
| 理解技术路线与分工 | [当前方案](plans/current/README.md)、[总分工](项目规划/AFH03_USB同步双目方案一个月分工/00_三人分工与一个月实施安排.md) |
| 了解真实完成状态 | [PC阶段交付状态](docs/当前PC阶段交付状态.md)、[本轮PR复核](reports/PR审查_20261008.md) |
| 理解三人怎样接入、Qt做什么 | [系统架构与接口图](docs/architecture/README.md) |
| 运行A的Qt/CLI、构建共用核心 | [software/pc_pipeline](software/pc_pipeline/README.md)、[B接入A材料](docs/B接入A交付材料.md) |
| 使用B的球心模块 | [ball_measurement](software/pc_pipeline/ball_measurement/README.md) |
| 开发与测试FPGA | [fpga](fpga/README.md) |
| 准备C的模型与评分 | [vision](vision/README.md)、[C个人分工](项目规划/AFH03_USB同步双目方案一个月分工/03_C_AI模型训练与部署职责说明.md) |
| 接手任务、查看证据 | [handoffs](handoffs/README.md)、[reports](reports/README.md) |

截至 2026-10-08，A共用软件/CPU整数参考/前三段RTL已合入；B局部球心模块和后四级帧缓存功能参考的协议修复已合入。B三维/事件修订PR仍需处理依赖和重复目录。实际C模型、A/B/C共用适配与完整GUI叠加、正式设备链路仍待验证。独立模块通过不等于完整系统通过。

Qt是长期保留的显示、回放和证据复查层。当前程序已能查看左右图、各级图、Mask和ROI；最终目标包括AFH03 HDMI实时显示球心、识别框、轨迹和事件。后续算法沿用共用C++核心，文件输入/CPU运动/PC推理逐层换为相机/FPGA/NPU后端。

## 仓库保留什么

`plans/current/`和当前三人职责保留现行Markdown、Word/PDF；`software/`、`fpga/`、`tools/`保留现用实现、验证与构建入口；`data/manifests/`记录输入、版本和本地产物；`handoffs/`、`reports/`保留当前接手材料及实际算法证据。

旧路线、旧TD调试实验、旧文档核查和被替代的交接已移出当前文件树。原始文件及Git字节备份保存在本机，入口为[本地历史资料](archive/README.md)和[清单](data/manifests/local-history-20261008.json)。原始视频、模型权重、厂商SDK、授权和生成工程继续按[产物说明](artifacts/README.md)保存在本地；A 1.0.1 MJPEG兼容运行包及源码从[当前私人Release](https://github.com/fengfengkang/pingpong-fpga/releases/tag/a-pipeline-pc-20261012)取得，原A/B人工输入与历史证据仍在[2026-10-06 Release](https://github.com/fengfengkang/pingpong-fpga/releases/tag/a-pipeline-pc-20261006)。[本轮验证](reports/MJPEG适配验证_20261012.md)单独记录输入适配，原配置、算法和B/C接口保持原样。

协作前阅读[AGENTS.md](AGENTS.md)、[CONTRIBUTING.md](CONTRIBUTING.md)、[协作指南](docs/AI_agent协作指南.md)和[接口契约入口](项目规划/接口与验收契约.md)。新任务基于最新已评审的`origin/main`建立任务分支；性能、准确率、综合与上板各按实际证据记录。
