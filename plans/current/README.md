# 当前 AFH03 USB 同步双目技术路线

技术方案正文版本为2026-10-04 PC算法闭环版；本索引于2026-10-08整理。路线：[Markdown](usb-stereo/技术路线_AFH03与USB同步双目测量方案.md)、[Word](usb-stereo/技术路线_AFH03与USB同步双目测量方案.docx)、[PDF](usb-stereo/技术路线_AFH03与USB同步双目测量方案.pdf)。分工：[总分工](../../项目规划/AFH03_USB同步双目方案一个月分工/00_三人分工与一个月实施安排.md)，同目录保留四份Word和A/B/C个人说明。正文和Word/PDF本轮保持原字节。

正式目标采用AFH03 RK3576J + PH1A90SEG324、72°/3.6 mm双OV9281 USB3、拼接2560×720@60 YUY2，每眼1280×720、安装基线150～200 mm。CPU保留8对原图，每眼生成640×360搜索图，经PCIe送FPGA；七级运动前端返回双眼1 bit Mask。CPU在同帧原图ROI内测量球心、三维和事件，NPU异步提供球/手/拍三类语义。模型、坐标与协议仍按草案评审管理。

[当前PC交付状态](../../docs/当前PC阶段交付状态.md)区分已合入模块、待联调和实物边界；[架构与接口](../../docs/architecture/README.md)解释A/B/C和Qt的关系；[验收清单](../../docs/PC算法闭环与部署验收.md)规定检查方法。60fps、同步、精度、时延和功耗是实机目标，不能用文件回放或合成评分代替。

按自主命题准备；AFH03实机验收按实际到货日另行推进。H10 CK203 PH1A180已到货，最近排查记录尚未解决JTAG识别，其DDR3/RTL预验证与AFH03 DDR3L/PCIe/RK/NPU整机分别记录。旧路线与TD调试实验已转为[本地历史资料](../../archive/README.md)，当前FPGA入口为[fpga/README.md](../../fpga/README.md)。

接手先读[协作规则](../../AGENTS.md)、[贡献流程](../../CONTRIBUTING.md)、对应个人说明第二部分及[最新交接](../../handoffs/README.md)。本次只整理入口与证据，不改技术路线、共同参数或判罚阈值。
