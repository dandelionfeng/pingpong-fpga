# B 第三部分深化版交接

- 负责人/角色：B（cluepiggie），2026-10-06。
- 目标：按现行路线补候选联合配对、棋盘估计配置下图像链路、在线多次发球与迟到语义、触拍重估速度、取消/稀疏检测、事件证据及扩展PC测试。
- 基准/分支/依赖：本地无Git元数据，基准提交未取得；建议codex/b-trajectory-events-v2。依赖修复后的第二部分 PR（目录必须是 `software/pc_pipeline/ball_measurement/`，不能有 `BPart2/` 外层）；源码哈希与先前提交包一致。第三部分v2替换初版对应文件；若初版未合入，在PR注明真实依赖PR/基准，不覆盖队友后续修改。
- 允许修改：software/pc_pipeline/trajectory/、tools/fixtures/trajectory*及本轮报告/交接。第一部分、第二部分、A/C代码、路线Word/PDF保持未改。
- 接口：b-trajectory-v2-draft；标定仍b-calibration-v1-draft。FrameStamp/PredictionHint复用第二部分；单位米，X台宽/Y台长/Z向上；观测、滤波、预测分栏。图像manifest要求显式reference_valid/reference_id；处理、完成、到达、采样时间分开。兼容影响是第三部分CLI输出版本与新增在线调用，接手者需重编译；旧图像manifest须补真实参考元数据，不自动推断pair_id-1。
- 输入来源：B合成双目分别投影、小数圆形/棋盘；Mask合成提示，语义显式回放。已知参数与棋盘估计配置分开，后者实际跑图像闭环。truth不传入C++程序。
- 验证：62现行第三部分C++检查＋42第二部分回归，8/8CTest；84文件场景；旧棋盘4/4留出、扩展棋盘6/6留出；9图像场景54～55/56测量，顶点补测及触拍后连续测量通过。实际命令与误差见v2报告，不将生成场景精度当真实相机。
- 复现入口：`software/pc_pipeline/trajectory/build_and_test.bat` 和 `run_validation_v2.ps1`；可传 `Python/OpenCVDir/BuildDirectory/VisualStudioPath/OutputDirectory`。脚本先构建并检查 `trajectory_cli.exe`，再运行完整 v2 链路。index.html看总览，events.html看事件原图、区域和三维证据。
- 在线接入：A逐帧push_frame，再按真实arrival调用push_detection/advance；及时take_updates保存修订和最终结果，禁止加载未来框。B预测先搜索当前图，再update；只有确认触拍与两次实际点才reset_after_contact；C提供来源帧/眼别/采样、完成/到达、模型版本和可见性。ball框仅在已到达且来源匹配时用于消歧。
- 未执行：A系统联调、C实际模型和独立冻结/评分、实物标定/精度、Linux/ARM、目标板性能、根仓库提交检查。公开棋盘下载被自动批准服务故障阻止，未执行；WSL未安装。无GitHub写操作。正式 v2 入口已在本地以修复后的同级第二部分目录跑通，PR 仍需在合并修复后的第二部分后从干净 checkout 重跑。
- 证据边界：高度误差预算未统计校准；调用者声明的标定/同步噪声不得称实测。复杂同极线球状干扰仍需C身份。完整未知/失败与旧整数图像误差在包内保留，未宣布全面验收。
- 后续入口：A/C提供实际交接包后逐层替换输入/检测，不改几何核心；FengFengKang最终评审共同接口与阈值。源码包带未变第二部分依赖便于复现；已合入时无需重新上传依赖目录。
