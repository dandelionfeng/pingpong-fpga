# B 第二部分：局部球心测量 v2

更新：2026-10-06。依据当前 AFH03 USB 双目路线 2.5 及 B 职责“从运动区域到原图球心”。使用 C++17/OpenCV，在 PC 上复现，沿用 640×360 Mask、1280×720 原图、256×256 ROI、64×64 局部窗口和搜索坐标 `2u+0.5`。

## 本版行为

搜索图进行 8 邻域连通域分析，结合面积、宽高比、尺寸与可用预测位置排序，最多保留 8 个候选。原图 ROI 先做 3×3 Gaussian 平滑，仅真实有效像素参与 Otsu 直方图。亮球、暗球两种分割分别进行 3×3 闭运算和局部连通域分析；使用候选距离、形状、面积、背景对比度、可用历史尺寸选择一个区域，只对该区域做 moments。均匀背景、低对比度、过大/细长区域和无法区分的候选明确拒收。

ROI 使用 replicate 补齐为固定 256×256，保留原图原点、实际图像范围及 ROI/局部窗口内有效范围。填充像素不计入分割统计。完整球在需补齐的 ROI 中仍可测量；球轮廓被图像或局部窗口截断时拒收，并保留选中区域和边界证据。

输出面积、宽高比、圆度、亮度对比、Sobel 轮廓强度、24 方位边缘支持比例、径向不对称和凸包充实度。形状异常标为可能遮挡/形状失真，不将其当作语义真值。轻度形变可输出 reduced 质量观测；严重形变和边缘截断拒收。

## 构建与 C++ 测试

Windows 已安装 Visual Studio C++、Windows SDK 与 OpenCV 4.10.0 时，在仓库根目录执行：

```powershell
& '.\software\pc_pipeline\ball_measurement\build_and_test.bat'
```

脚本定位 Visual Studio 并使用 CMake/Ninja/x64 MSVC。默认 OpenCV 路径为仓库根 `.tools/opencv-4.10.0/opencv/build/x64/vc16/lib`，也可传 `-OpenCVDir`。仅当前进程导入编译器环境。中文 MSVC 头文件依赖输出在本机存在解码差异，因此该小模块采用 `--clean-first` 防止修改头文件后复用陈旧对象；不会删除源码。匹配的 OpenCV DLL 复制到被忽略的构建目录，直接运行不依赖全局 PATH。

默认构建目录 `build-ninja-release/`；configure/build/test 日志及工具版本也存放在此处。`CPP_BUILD_AND_TEST_PASS` 表示 3 组 CTest 全部通过。本版包括 42 个断言场景。

Linux 构建入口（本轮未执行）：

```bash
cmake -S software/pc_pipeline/ball_measurement -B software/pc_pipeline/ball_measurement/build-linux -DCMAKE_BUILD_TYPE=Release
cmake --build software/pc_pipeline/ball_measurement/build-linux
ctest --test-dir software/pc_pipeline/ball_measurement/build-linux --output-on-failure
```

## 文件复现与真值隔离

Python 用于生成输入与评分，依赖 `numpy`、`opencv-python`，本机使用项目 `.venv`。生成器将输入 manifest/图片放在 `inputs/`，真值放在 `truth/`。C++ CLI 只读取 inputs。运行：

```powershell
& '.\.venv\Scripts\python.exe' tools/fixtures/ball_measurement_v2_fixture.py --output _deliveries/part2_v2_validation
& '.\software\pc_pipeline\ball_measurement\build-ninja-release\ball_measurement_cli.exe' _deliveries/part2_v2_validation/inputs/manifest.json _deliveries/part2_v2_validation/results
& '.\.venv\Scripts\python.exe' tools/fixtures/ball_measurement_v2_score.py --truth _deliveries/part2_v2_validation/truth/expected.json --results _deliveries/part2_v2_validation/results --report _deliveries/part2_v2_validation/score.json
```

另外一台机器可先建立 Python 环境并 `python -m pip install -r tools/fixtures/ball_measurement_v2_requirements.txt`，将命令中的解释器路径替换为该环境的 Python。实际本机版本见交付中的 `tool-versions.txt`。

CLI 输出逐场景 JSON、原图叠加、64×64 局部图与选中区域。拒收和 predicted-only 不输出 observation 字段；拒收 Measurement 内部的 `image_center` 为 NaN，不能当作原图测量点。独立评分器读取 truth 后核对来源、理由、球心误差及质量标记。本版 54 个固定场景通过，35 个清晰场景 P95 约 0.073 px；不代表真实相机精度。

## C++ 调用与接口影响

正式入口见 `include/ball_measurement.hpp`：

```cpp
GrayFrame image{gray_mat, image_stamp};
MotionFrame motion;
motion.mask = decoded_mask_mat;
motion.stamp = image_stamp;
motion.reference_valid = true;
motion.reference_id = previous_pair_id;
EyeResult result = measure_eye(image, motion, config, optional_prediction);
```

每个 `FrameStamp` 包含 pair_id、眼别、ns 采样时间、mode_id、配置与标定版本；图像和 Mask 必须完全一致，配置版本也必须与正在运行的 Config 相符。检测完成时间与算法采样时间分开，由 A 的调度层管理。cv::Mat 行步幅可非连续，现有测试覆盖该输入。

初帧 reference_valid=false 时必须提供零 Mask 和无 reference_id；有参考时 ID 必须存在且早于当前 pair_id。失败 Mask/错帧/错眼/尺寸或版本错误拒绝进入测量。`measure_pair` 先核对两眼及各自 Mask，再调用两个单眼核心，返回左右结果；极线校正与配对仍由后续几何模块提供，不把两个 observed 点直接当作已验证的同一球。

`PredictionHint` 由后续跟踪模块提供已经投影到当前眼的原图像素位置，绑定目标帧身份和采样时间，同时保留源帧号、源采样时间、预测器版本和可选先前球直径。目标失配或超过 0.25 秒的预测拒收。零 Mask 时仍可在预测附近的当前原图测量；找到真实区域后为 observed，搜索来源为 prediction，原预测保持单独字段。无真实区域时只返回 predicted，observation 为空。与预测相距超过配置门限的候选拒收，避免切到远处其他圆形对象。本模块不计算 Kalman、世界坐标或三维投影。

像素级旧函数 `measure_ball(gray,candidate,cfg)` 仍保留用于兼容，其结果 identity_validated=false；实际集成须用 `measure_eye` 或 `measure_pair`。Config 和返回结构已新增字段，接手人需重编译；新增内容仍是 `b-measure-v2-draft` C++ 草案，未冻结 PCIe 描述符/Mask 位序，没有改动 A/C 源码。

## 默认配置与质量限制

Config 中的可调阈值属于受控 PC 样例起点，最终根据真实输入评审。主要数值：Mask 面积 8～1600、尺寸 4～48、宽高比≤3、最多 8 候选；局部区域面积 50～1800、尺寸 8～44、宽高比≤1.8、圆度≥0.60、有效局部灰度分位跨度≥12、对比度≥15、前景比例≤0.50、候选/预测距离门限 24 px、歧义分数间隔 0.08。源码当前固定的质量提示分界采用圆度 0.85、宽高比 1.15、径向不对称 0.10、凸包充实度 0.90；Sobel 24 方位支持低于 0.75 降低质量，低于 0.50 拒收。

这些指标不能证明目标类别，也无法保证完全遮挡的真实球心。轻度遮挡的 moments 仍可能有偏差，调用方须保留 reduced 质量和原观测，不当作干净测量。多个近似球状物体缺少明确预测时可为 invalid/ambiguous；后续 C 语义、标定极线配对和跟踪用于进一步消歧。

## 尚待验证

A 的正式文件/缓存输入联调、C 的独立复核、真实许可图像与真实相机、Linux 构建、更多模糊/复杂遮挡/背景场景及板端速度尚未执行；完整 P4 验收不能只由这批合成结果宣布。原初版 ZIP 与旧 Python reference/cases 为历史草稿，本版以 C++ CLI、v2 生成器和 v2 评分器为现行入口。最新结果见[验证报告](../../../reports/第二部分_球心测量_v2验证_2026-10-06.md)，提交包内的工具版本、实际配置和评分见[文本证据](../../../reports/ball_measurement_v2/2026-10-06/README.md)，正式接手见[任务交接](../../../handoffs/2026-10-06-b-ball-measurement-v2.md)。

