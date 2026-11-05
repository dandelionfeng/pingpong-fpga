发球测量系统 1.2.1 竞赛代码包
================================

一、运行环境

1. 查看已有样例（仅需 PC）
   - Windows 10 / 11，64 位。
   - Microsoft Edge（Windows 10/11 自带）。工作台以 Edge 应用窗口打开；未找到 Edge 时使用系统默认浏览器。
   - 无需安装 Python 或其他软件。PC 端 Python 3.13、OpenCV、NumPy、pySerial、FFmpeg 均已随包放在 runtime 与 app\tools 中。
   - 解压时保持目录结构完整，发球测量系统.exe 与 app、runtime、data 文件夹须位于同一目录。

2. 现场采集
   - AFH03 开发板（RK3576J + PH1A90 FPGA）、USB 双目 OV9281 相机。板端系统需带 Python 3.11 与 RKNN 运行时。
   - PC 端驱动：J3 调试串口的 USB 转串口驱动（按设备管理器识别的芯片安装，如 WCH CH34x 或 FTDI）；J4 的 Android ADB USB 驱动。
   - FPGA 位流 app\fpga\afh03_sgdma_motion7.bit 使用安路 TD 软件中的 BitWriter 下载。工作台中的 BitWriter 按钮调用 C:\Anlogic\TD_Release_2026.1_SP2.200.067\bin\bw.exe。
   - 板端部署直接使用 app\dist 内的离线部署包，不要求先还原外层 wheels。根目录“准备板端部署文件.cmd”用于需要单独取出三个板端依赖文件时离线还原并核对哈希。
   - 部署位流，TDbitwriter不接受含中文路径的文件。从RK取回结果同样路径不能有中文

二、查看已有样例

1. 双击 发球测量系统.exe，等待工作台窗口打开。
2. 点击左侧“测试记录”，列表中列出 serve_01、serve_02 两份已录制样例，显示双目帧数、测量状态、高度 H 与角度 θ。
3. 点击某一行的“查看回放 ↗”，打开轨迹回放：左右目录像及标注、拟合轨迹、离手点与最高点、球的空间轨迹，以及抛球高度 H、抛球角度 θ 等测量结果。
   首页的“查看最新回放”直接打开 serve_02。
4. 使用完毕点击“退出工作台”，再关闭窗口。查看样例不需要连接开发板。



