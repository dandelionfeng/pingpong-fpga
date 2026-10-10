# B 第三部分修正版交接

- 任务编号/负责人：B3 修订 / B / cluepiggie。
- 基准提交号/工作分支：main `fe7af549464b290b2573199a1cf5a00ebf4432a5`，新分支 `codex/b-trajectory-events-v2-path-fix`；依赖 B2 #16 已合并，不依赖旧 #13/#14/#18；本轮替代旧第三部分提交内容，未合并 main。
- 当前目标与范围：交付双目标定、三维、跟踪、预测ROI补测及发球事件的独立PC核心，修复缺builder/依赖路径/目录重复；不修改B1/B2算法、A/C源码或方案Word/PDF。
- 允许修改：`software/pc_pipeline/trajectory/`、`tools/fixtures/trajectory*`、本交接、`reports/trajectory_v2/2026-10-10/`及交接/报告索引。
- 输入输出/接口：同帧1280×720双眼灰度/640×360 decoded Mask，或明确像素观测回放；来源帧语义/到达时间、标定与配置版本；输出米制实际观测/滤波/预测、事件区间/修订及拟合依据。`b-trajectory-v2-draft`、`b-calibration-v1-draft`，共同参数未冻结。
- 环境与复现命令：见模块README和专用报告；builder两文件已提交，CLI使用同一个BuildDirectory，必须存在main提供的同级ball_measurement。软件版本/输入/源码/依赖哈希与实际结果随专用报告提交。
- 已执行检查及真实结果：2026-10-09本地v2：8/8 CTest、B3 62项＋B2 42项、84/84文件场景、棋盘留出4/4＋6/6。2026-10-10新main源码快照的复现和仓库检查以专用报告的实际记录为准。
- 未执行/依赖：实际pipeline_b_module适配与A在线/Qt联调，C真实模型/冻结真值/独立评分，公开棋盘、OV9281标定/同步/尺度，Linux/ARM、综合和上板；检测是显式回放、Mask是人工搜索提示，不能当作实际模型/运动前端证据。
- 修改文件与理由：独立B3源码/脚本置于约定目录；不重复带入BPart2，不覆盖根SOURCE_SHA256.json，不重引入已归档旧报告。新报告保留原日期和执行范围，索引登记现行入口。
- 下一步及验收条件：A以公共头文件实现/复核pipeline_b_module映射、同帧输入与来源语义到达；C用独立冻结场景评分并提供真实ball/hand/racket输出；B核查坐标/单位/质量。相关影响由负责人技术复核，FengFengKang最终审批。检查通过且获合并授权后Squash and merge。
