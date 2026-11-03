发球测量系统 1.2.1 竞赛代码包
================================

一、运行环境

1. 查看已有样例（仅需 PC）
   - Windows 10 / 11，64 位。
   - Microsoft Edge（Windows 10/11 自带）。工作台以 Edge 应用窗口打开；未找到 Edge 时使用系统默认浏览器。
   - 无需安装 Python 或其他软件。PC 端 Python 3.13、OpenCV、NumPy、pySerial、FFmpeg 均已随包放在 runtime 与 app\tools 中。
   - 解压时保持目录结构完整，发球测量系统.exe 与 app、runtime、data 文件夹须位于同一目录。

2. 现场采集（另需硬件）
   - AFH03 开发板（RK3576J + PH1A90 FPGA）、USB 双目 OV9281 相机。板端系统需带 Python 3.11 与 RKNN 运行时。
   - PC 端驱动：J3 调试串口的 USB 转串口驱动（按设备管理器识别的芯片安装，如 WCH CH34x 或 FTDI）；J4 的 Android ADB USB 驱动。
   - FPGA 位流 app\fpga\afh03_sgdma_motion7.bit 使用安路 TD 软件中的 BitWriter 下载。工作台中的 BitWriter 按钮调用 C:\Anlogic\TD_Release_2026.1_SP2.200.067\bin\bw.exe。
   - 板端部署直接使用 app\dist 内的离线部署包，不要求先还原外层 wheels。根目录“准备板端部署文件.cmd”用于需要单独取出三个板端依赖文件时离线还原并核对哈希。

二、查看已有样例

1. 双击 发球测量系统.exe，等待工作台窗口打开。
2. 点击左侧“测试记录”，列表中列出 serve_01、serve_02 两份已录制样例，显示双目帧数、测量状态、高度 H 与角度 θ。
3. 点击某一行的“查看回放 ↗”，打开轨迹回放：左右目录像及标注、拟合轨迹、离手点与最高点、球的空间轨迹，以及抛球高度 H、抛球角度 θ 等测量结果。
   首页的“查看最新回放”直接打开 serve_02。
4. 使用完毕点击“退出工作台”，再关闭窗口。查看样例不需要连接开发板。


三、2026-11-03 离线审核修复

1. EXE 自检和安装检查按实际保留样例统计；当前为2份、642对。原始输入JPEG未随包提供，自检会明确列为仅回放样例，不将它们记为原图校验通过。
2. 从板端取回与历史样例别名冲突的结果时，新记录保存为rk_原结果名，保留serve_01、serve_02。取回前核对远端完成记录、摘要和输入清单；不同的旧缓存保留在data\.history。
3. 现有样例可使用缓存视频与已有封面更新回放页面；重新编码视频、重新计算测量需要原始输入JPEG。
4. 已修正原生适配器的重排路径、VS Code相对工程路径以及release清单指向；重新编译RK原生程序仍需要对应SDK和开发环境。

四、实际现场展示的条件

1. 本包包含PC离线环境、板端程序、模型、bit流、FPGA工程以及离线部署包。使用原已配置的AFH03系统；板端仍需Python3.11、RKNN运行库及原生OpenCV动态库。既有程序期望OpenCV库位于/userdata/codex-full-project-20261017/opencv/lib。
2. 电脑需要相应的J3串口/J4 ADB驱动；FPGA重新下载需要匹配版本的TD/BitWriter，当前按钮使用本机C:\Anlogic路径。本包不包含这些Windows驱动或TD安装程序。
3. 工作台录制按钮使用/dev/video73；相机节点变化时，在J3终端用实际节点执行sh /userdata/pingpong-quick-field-3092-20261030/run_capture.sh /dev/videoN auto 5。等待RECORDING_SAVED后接J4取回结果。
4. 本轮按用户要求仅离线审核，未执行真实相机采集、FPGA/NPU运行或USB结果传输。接板后按“J4部署检查→J3短录制→RECORDING_SAVED→J4取回→查看新记录”完成现场验收。
