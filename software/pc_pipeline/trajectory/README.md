# B 第三部分：双目三维、轨迹与发球事件

交付更新：2026-10-10。负责人：B / cluepiggie。依据 AFH03 USB 同步双目路线 2.1、2.7、2.8 和 B 个人职责。接口为 `b-trajectory-v2-draft`，标定为 `b-calibration-v1-draft`，共同接口和判罚阈值仍待技术复核与 FengFengKang 最终审批。

## 构建与完整 v2 复现

本模块依赖最新 main 已合入的 `software/pc_pipeline/ball_measurement/`，两者必须同级。没有第二部分目录时明确失败，不携带 `BPart2/` 副本。基准为 `fe7af549464b290b2573199a1cf5a00ebf4432a5`。

安装 Visual Studio C++/Windows SDK、CMake/Ninja、OpenCV C++ 和 Python 后，从仓库根执行：

```powershell
python -m pip install -r tools/fixtures/trajectory_v2_requirements.txt
& '.\software\pc_pipeline\trajectory\run_validation_v2.ps1' `
  -Python 'C:\path\to\python.exe' `
  -OpenCVDir 'C:\path\to\opencv\build\x64\vc16\lib' `
  -BuildDirectory '.\build\b-trajectory-release' `
  -OutputDirectory '.\output\b-trajectory-v2-new'
```

路径示例需替换为本机实际路径。默认 Python 为仓库 `.venv/Scripts/python.exe`；默认 OpenCV_DIR 可由环境变量指定，否则使用 `.tools/opencv-4.10.0/opencv/build/x64/vc16/lib`。可用 `-VisualStudioPath` 指定 VS 安装。构建目录由脚本生成，不上传。

`build_and_test.bat` 调用同目录 `build_and_test.ps1`，配置、clean-first 编译并运行 CTest；`run_validation_v2.ps1` 先调用 builder，再从同一个 BuildDirectory 检查 CLI，依次生成独立双目输入、两组棋盘标定和留出评分、文件链路评分、校正预览、事件证据与图表。成功输出 `PART3_V2_VALIDATION_PASS`。输入、truth 与结果分目录，C++ CLI 不读取 truth。用新的 OutputDirectory 保存每轮证据。

Linux 构建入口（本轮未执行）：

```sh
cmake -S software/pc_pipeline/trajectory -B build/b-trajectory-linux -DCMAKE_BUILD_TYPE=Release
cmake --build build/b-trajectory-linux
ctest --test-dir build/b-trajectory-linux --output-on-failure
```

## 实现与接口

- `calibrate_chessboards`：成对 1280×720 GRAY8 棋盘，经 findChessboardCornersSB、calibrateCamera、stereoCalibrate(CALIB_FIX_INTRINSIC)、stereoRectify，保存/加载参数。`set_world_pose` 用 solvePnP。未知方格尺寸只用 `unit=square`，正式三维入口要求 `unit=m` 与有效世界变换。
- `triangulate`：undistortPoints(R1/R2/P1/P2)、triangulatePoints、齐次归一化、R1ᵀ 回左相机、Rcwᵀ(Xc−tcw) 回世界。世界 X 横向、Y 球台纵向、Z 向上，单位米。检查帧/眼/时间/版本、正深度、视差、极线和重投影，输出质量/拒收原因及协方差。额外标定/同步预算由调用者声明，不能视为实测精度。
- `observation_candidates` 与 `match_stereo`：每眼最多8个实际测量候选；几何、尺寸和可用预测帮助配对，歧义拒收。几何不能证明目标语义身份；来源正确且已到达的 ball 框可用于筛选。
- `Tracker`：6维位置/速度 Kalman，真实采样 dt，自由飞行重力、Mahalanobis 门控、Joseph 更新；处理缺帧、离群、时间/配置跳变与重捕获。`roi_hint` 反投影预测位置，调用第二部分测量当前原图；真实区域被找到才产生观测。确认触拍后仅用最近两次实际三维观测 `reset_after_contact`。
- `OnlineEvents`：持球、上抛、顶点、下降、触拍；语义按来源帧关联，按实际到达时间 push，不能预载未来框。输出事件ID、修订版本、发布时间、来源区间，取消/缺证据保留 cancelled/unknown。最多256帧、2048检测、32待来源检测、64待取修订，调用方及时 take_updates。
- `fit_flight`：只用实际有效且跟踪接受的观测，水平线性/竖直二次，8次 Huber 重加权；至少6点、0.08秒跨度，顶点须由实际观测包围。离手交点受观测区间和声明误差预算约束。高度包络不是统计校准的置信区间，不自动判罚。

头文件入口 `include/trajectory.hpp`。调用顺序：预测并生成 ROI hint → 在同帧两眼原图测量 → 同帧配对/三角测量 → 更新跟踪和事件；不要先更新当前帧再预测回当前帧。FrameStamp 保留 pair_id、眼别、采样时间、mode/config/calibration 与 reference_id。`processing_time_ns`/检测 `arrival_time_ns` 与采样时间分开。

CLI manifest 可选 `left_pixel/right_pixel`（显式像素观测回放）或 `images`（实际调用 B2 图像测量），图像模式要求显式 reference_valid/reference_id。JSON/CSV 分栏保存原始观测、滤波、预测、拒收原因和事件区间。hand/racket 为显式 synthetic replay，本模块不运行 YOLO/RKNN。

## 验证、证据与接手

2026-10-09 本地 v2 已执行：8/8 CTest（B3 62项、B2 42项）、84/84文件场景、两组棋盘留出4/4与6/6、88事件证据窗口、12图表。所有输入属于 B 开发合成回归，C 尚未独立复核；通过包含按预期 unknown/cancelled 的场景。

`trajectory_event_evidence.py` 不读取 truth，导出邻近左右原图/哈希、手拍框、256/64窗口及原点/有效范围、三维片段和事件版本；像素回放缺原图时明确登记。结果目录的 index.html/events.html 为本地查看入口。此次仅提交源码与小型文本证据，不上传图片结果 ZIP。

新基准复现与原始日志见[当前报告](../../../reports/trajectory_v2/2026-10-10/README.md)，接手见[交接](../../../handoffs/2026-10-10-b-trajectory-v2-path-fix.md)。main 中 A/B2 源码保持原样；本独立库还没有 `pipeline_b_module` 适配，A系统联调、C真实模型及独立评分、公开棋盘练习、真实相机标定/同步/尺度、Linux/ARM和硬件验收均另行登记。合成 Mask 是搜索提示，不能当成 A 七级前端已接通。

实物锁焦后按路线采集25～40对覆盖视场/距离/姿态的米制棋盘，重新标定并用 solvePnP 建世界系，以独立已知位置核验。不能缩放图片后沿用旧内参或把方格单位解释为米。
