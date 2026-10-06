# B 第三部分：三维、跟踪与发球事件

## 当前入口：2026-10-06 深化版 v2

当前接口为 `b-trajectory-v2-draft`，标定配置继续使用 `b-calibration-v1-draft`。技术依据沿用原 AFH03 USB 同步双目路线；第一部分 RTL、第二部分源码及 A/C 代码均未修改。本文下方初版章节保留其历史范围，深化版结果以本节、v2 报告及交接为准。

从仓库根执行（要求第二部分已经按 `software/pc_pipeline/ball_measurement/` 合入，且与本目录同级）：

```powershell
& '.\software\pc_pipeline\trajectory\run_validation_v2.ps1'
```

可传 `-OutputDirectory`、`-Python`、`-OpenCVDir`。Python 依赖见 `tools/fixtures/trajectory_v2_requirements.txt`。程序依次构建/测试、生成输入、两组棋盘标定与留出检查、使用估计参数跑图像链路、隔离真值评分、校正预览、事件证据与图表。输出目录不能复用其他任务的证据目录。Windows 本机已实际运行；Linux入口可构建，但本机 WSL 尚未安装，未验证 Linux/ARM。

`build_and_test.bat`、`build_and_test.ps1` 和 `run_validation_v2.ps1` 都是仓库源码入口，必须随本模块提交；`build-ninja-release/` 只由脚本生成，不上传。v2 脚本每次先调用 builder，再检查生成的 `trajectory_cli.exe`，不会依赖提交外的本地构建残留。也可以显式指定构建目录：

```powershell
& '.\software\pc_pipeline\trajectory\run_validation_v2.ps1' `
  -BuildDirectory '.\software\pc_pipeline\trajectory\build-ninja-release'
```

如果第二部分目录不存在，CMake 会直接报告缺少 `software/pc_pipeline/ball_measurement`；应先合并修复后的第二部分 PR，再更新本 PR 的依赖基准，不要保留 `BPart2/` 外层目录。

新增行为：

- `observation_candidates` 从第二部分已验证的测量尝试提取最多8个不同球心，保留单眼歧义后交 `match_stereo` 联合配对。预测/无效点不参与三角测量。当前来源帧且已到达的 `ball` 框可过滤候选，回放与真实模型必须标明；多目标几何无法证明语义身份。
- `rectify_images` 用 `initUndistortRectifyMap/remap` 输出校正预览；它也允许未知尺度的方格单位标定练习，不因此产生米制三维。
- `GeometryConfig` 可声明标定位置、世界平移/旋转和同步误差预算，并传播到观测协方差。默认仍只有球心噪声；额外预算来自调用者，未从本轮数据自动估计。高度包络增加观测与持球位置预算，仍不是经统计校准的置信区间。离手高度优先使用持球高度与上升拟合交点；噪声导致交点稍超区间时，只在误差预算允许且不超一段区间长度时约束到实际区间边界，否则用中点。`release_method` 保存依据。
- `OnlineEvents` 逐帧接收实际观测，检测需按实际到达时间调用 `push_detection`，不得预载未来结果。修订含事件ID、版本、发布时间和来源帧；最多256帧、2048检测、32个待来源帧检测，修订队列64项，调用方须及时 `take_updates`。持续持球重新开始、触拍后延迟收尾、时间/配置跳变、容量超限和取消分别保留记录。临时 `unknown` 与最终结果区分。
- 允许20/30Hz手拍框与60Hz球观测分开采样，离手区间来自实际帧和可用手框；无手证据不推断离手。短遮挡触拍使用缺失前后的实际点、来源帧拍框及速度差，区间不会由预测缩窄。重新接球记录取消，不伪造触拍。
- `reset_after_contact` 只接受两次最近的实际三维观测；确认触拍后重估速度。图像丢失时可重新搜索当前运动候选，所有配对仍检查歧义和几何。预测ROI补测找到真实像素才成为观测。
- 文件图像入口要求显式 `reference_valid`/`reference_id`，不再假设相邻 `pair_id-1`。`processing_time_ns` 与采样时间分开；检测可另给 `arrival_time_ns`。C++ CLI 是有限文件回放驱动；在线核心缓存有上限，CLI为导出保存的整段数据不等于 A 的设备缓存。

`trajectory_event_evidence.py` 不读取truth，按在线最终事件导出邻近左右原图、原图哈希、手拍框叠加、256/64区域及其原点/有效范围、三维片段和版本。像素回放没有原图，明确登记缺失，不制作替代图。双击结果包 `index.html` 查看总览、`events.html` 查看事件证据。

现有测试含30条参数变化发球、10条取消/缺证据、5条异步，以及遮挡、20/30Hz语义、多候选和连续两次发球。全部属于B开发回归，未由C冻结或独立复核。Mask是合成搜索提示，没有宣称七级运动前端接通。实物标定/同步、C真实模型、A系统联调、公共棋盘下载及Linux/ARM仍需另验。

公开棋盘下载入口由路线指向OpenCV官方仓库；本轮网络受限，提权调用被自动批准服务故障阻止，未下载。后续可用成对1280×720图片组织 `board_manifest`，未知方格尺寸用 `unit=square`，已知实物尺度才能用 `unit=m`，执行 `trajectory_cli calibrate <manifest> <config>`。不得缩放图片后沿用旧内参或把方格单位解释为米。真实相机锁焦后按路线重新采集25～40对覆盖视场和距离的棋盘，使用米制板与 `solvePnP` 建世界系，保留独立位置检查。

详见 [v2交接](../../../handoffs/2026-10-06-b-trajectory-v2.md) 与 [v2报告](../../../reports/第三部分_三维轨迹事件_v2验证_2026-10-06.md)。

## 初版历史范围

2026-10-06。技术依据为现行 AFH03 USB 同步双目路线 2.1、2.7、2.8 和 B 职责；接口 `b-trajectory-v1-draft`。本模块依赖同目录上一级的第二部分 `ball_measurement/`，不改它的源码。当前为 Windows PC 可运行初版，不代表完整 P5/P6/P8/P9 或实物验收。

## 已实现入口

- `calibrate_chessboards`：成对 1280×720 GRAY8、9×6 棋盘，findChessboardCornersSB → calibrateCamera → stereoCalibrate(CALIB_FIX_INTRINSIC) → stereoRectify，保存/加载配置；至少 8 对成功角点。`set_world_pose` 用 solvePnP 建立世界到左相机 Rcw/tcw，至少 6 个米制已知点。公开图片方格尺度未知时传 `unit=square`，几何正式入口拒绝把它当米制。
- `triangulate`：左右同帧实际球心，undistortPoints(R1/R2/P1/P2) → triangulatePoints → 齐次归一化 → R1ᵀ 回左相机 → Rcwᵀ(Xc−tcw) 回世界；检查眼别/帧/采样时间/版本、正深度、视差、极线、重投影及尺寸。有限差分估计球心噪声传播协方差，尚不包含标定/同步不确定度。
- `match_stereo`：最多每眼 8 个候选，按几何、尺寸和可用预测像素选择，等价候选拒收。只是几何假设，不能证明同极线上的圆形干扰物就是同一球；C 的语义身份仍需接入。
- `Tracker`：6 维位置/速度，真实采样 dt，自由飞行重力，Mahalanobis 门控、Joseph 协方差更新、时间/配置复位；上抛模式切换处理速度突变，连续三次符合速度范围的观测尝试重捕获。预测最长 0.25 秒，观测/滤波/预测独立输出。
- `roi_hint`：将预测三维位置投影到两眼，输出第二部分 PredictionHint；文件 CLI 真正调用第二部分的 measure_pair 和本模块几何，验证零 Mask 顶点附近补测。
- `analyze_events`：有限长度单次发球离线回放，准备/上抛/顶点/下降/触拍；hand/racket 框按来源帧而不是完成时刻关联，保留版本/可见性，超过 0.25 秒的框忽略。缺证据 unknown，持续持球无上抛为 cancelled。离手需连续上行与手分离，触拍需拍接近和多帧速度变化；时间区间由邻近实际观测给出。
- `fit_flight`：只用实际有效且跟踪接受的点，水平线性/竖直二次、8 次 Huber 重加权，至少 6 点和 0.08 秒跨度，顶点必须被实际观测包围。最后持球位置能与上升拟合在离手区间内相交时细化离手高度，否则保留区间中点。输出高度、顶点、两种角度及“事件时间+残差”的误差包络，该包络不是经过统计标定的置信区间，也不作自动判罚。

## Windows 复现

已安装 MSVC、SDK、CMake/Ninja、OpenCV C++ 4.10.0，Python 3.12 + `tools/fixtures/trajectory_requirements.txt` 时，仓库根执行：

```powershell
& '.\software\pc_pipeline\trajectory\run_validation.ps1'
```

可传 `-OpenCVDir <OpenCVConfig.cmake所在目录>`、`-Python <python.exe>`、`-OutputDirectory <目录>`。构建脚本默认仓库 `.tools/opencv-4.10.0/opencv/build/x64/vc16/lib`，使用安装的 Visual Studio；导入环境仅限当前进程。和第二部分一样，每次 clean-first，避免本机中文头文件依赖输出产生旧对象；build 目录保持忽略。

逐项命令：

```powershell
& '.\software\pc_pipeline\trajectory\build_and_test.bat'
& '.\.venv\Scripts\python.exe' tools/fixtures/trajectory_fixture.py --output _deliveries/part3_v1_validation
& '.\software\pc_pipeline\trajectory\build-ninja-release\trajectory_cli.exe' _deliveries/part3_v1_validation/inputs/manifest.json _deliveries/part3_v1_validation/results
& '.\.venv\Scripts\python.exe' tools/fixtures/trajectory_score.py --truth _deliveries/part3_v1_validation/truth/expected.json --results _deliveries/part3_v1_validation/results --report _deliveries/part3_v1_validation/score.json
& '.\software\pc_pipeline\trajectory\build-ninja-release\trajectory_cli.exe' calibrate _deliveries/part3_v1_validation/inputs/board_manifest.json _deliveries/part3_v1_validation/results/board_calibration.json
& '.\.venv\Scripts\python.exe' tools/fixtures/trajectory_calibration_score.py --inputs _deliveries/part3_v1_validation/inputs --calibration _deliveries/part3_v1_validation/results/board_calibration.json --report _deliveries/part3_v1_validation/calibration-score.json
```

Linux 入口未执行：`cmake -S software/pc_pipeline/trajectory -B software/pc_pipeline/trajectory/build-linux -DCMAKE_BUILD_TYPE=Release`，随后 build/ctest。第二部分目录是必要源码依赖。

## 输入与调用

头文件 `include/trajectory.hpp` 为接口入口。二维单眼结果由 `from_measurement` 转为 PixelObservation；左右 triangulate 后，Tracker::update 接收当前 FrameStamp、可选有效三维观测和调用方自由飞行阶段。调用方须在处理当前图像前调用 roi_hint，处理完成再 update，不能先更新当前帧再预测回同一帧。

文件 manifest 的帧号和 ns 时间为十进制字符串；`left_pixel/right_pixel` 是显式像素观测回放，`images` 是调用第二部分图像测量的模式。输入没有真值三维、离手/顶点/触拍时间、拟合标签或自由飞行真值。CLI 初始自由飞行切换只依赖前后实测向上速度；当前有来源帧 racket 框时可在触拍附近尝试去除预测门控的运动重搜，适用于离线回放，正式异步调用时机和身份复核由 A/C 联调。

JSON/CSV 保存原始世界观测、滤波、预测、帧号、采样时间、版本、拒收原因、预测源和事件区间；无法得到的字段省略，CSV 留空。事件拟合不使用预测或滤波。语义检测显式 synthetic replay，不运行 YOLO/RKNN。

## 初版验证与限制

第三部分 40 个 C++ 检查 + 第二部分 42 个回归，7/7 CTest 通过。20/20 文件场景包括 5 条干净发球、噪声、缺帧/遮挡、离群、错配、版本、延迟/过期框、时间跳变和一条图像补测闭环。12 对生成棋盘标定、另 4 对姿态检查通过；该标定所得参数有毫米/厘米量级误差，不能代替实物最终参数。像素观测回放使用已知合成配置，不能把理想几何误差当作棋盘估参后的系统误差。

无噪声数学几何 996 点最大误差约 7.75e-12 m；5 条干净轨迹高度误差小于 1mm。图像补测场景几何 P95 约 5.28 cm、抛高误差约 2.73 cm，远未达到真实精度目标；整数绘制球心/像素采样和视差敏感度会放大误差。需后续小数球心渲染、更多距离/基线、噪声与真实图像验证。当前门控/事件阈值为配置起点，未评审冻结。

尚未完成：公开棋盘来源/许可练习、真实标定/同步/尺度核验、实际 C 模型与独立 C 评分、在线迟到事件修订/有限队列联调、完整取消/遮挡语义、Linux/ARM 构建、硬件性能。触拍后的初版重捕获依靠连续观测，图像样例仍有丢失；离线状态机仅处理单次发球，不承担实时调度。更多运动噪声与误差传播/置信区间待深化，不自动判罚。

详见[验证报告](../../../reports/第三部分_三维轨迹事件_初版验证_2026-10-06.md)和[交接](../../../handoffs/2026-10-06-b-trajectory-v1.md)。
