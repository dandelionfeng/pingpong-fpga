# C 模型、数据与独立评分入口

职责依据为[C个人说明](../项目规划/AFH03_USB同步双目方案一个月分工/03_C_AI模型训练与部署职责说明.md)。截至2026-10-08，仓库尚无可接入A的实际三类推理库、冻结独立测试集或RKNN板端验收；原空目录占位已移出。

C交付`pipeline_c_module`及`register_c_module(Registry&)`，实现[DetectorBackend](../software/pc_pipeline/include/pipeline/pipeline.hpp)，输出ball/hand/racket框、置信度、模型版本和来源帧。模型输入、预处理、坐标还原和异步约束见[软件接口](../software/pc_pipeline/contracts/a-motion-v1.md)及[架构图](../docs/architecture/README.md)。

训练/校准/测试按场次隔离。真值仅由独立评分器读取，用于核对实际PC模型、B球心/三维/事件与整条回放。B自有合成回归不等于C独立评分。代码进入具体任务目录；原图、权重和RKNN二进制通过[data/manifests](../data/manifests/ov9281-usb-module.md)记录版本与有权限的本地引用，按[产物说明](../artifacts/README.md)管理。
