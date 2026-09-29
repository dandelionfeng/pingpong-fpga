# AFH03 硬件无关图像处理内核

本目录最初对应[已归档的 AFH03 双目路线](../../archive/routes/v2026-09-24_afh03_dual/技术路线_MLK-AFH03-AFC03-2GB.docx)中的 FPGA 图像前端，目标器件为 PH1A90SEG324。它是可复用的基础像素处理内核；现行 [USB 同步双目方案](../../plans/current/README.md)计划通过 PCIe 把左右搜索图及局部图送入 FPGA。当前验证只覆盖脱离相机、DDR 控制器和 PCIe 驱动的内核；左右各 960×540、60 fps 的双路适配需要重新仿真、综合和板上验证。

这是新增的 AFH03 内核接口草案 `afh03-image-v0.1`，没有修改 v1.3 既有接口契约、模型输入、坐标约定或判罚阈值。冻结跨 FPGA/CPU 的协议前，仍需相关模块负责人评审。

## 已实现的数据流

上游将图像转换为 GRAY8，并附上帧开始、行结束、帧号和时间戳。两路图像分别进入帧检查与配置切换模块，再经过带行缓存的 3×3 去噪和可配置亮度调整，输出整帧双通道数据及可选 ROI。全部接口使用同一处理时钟下的 `valid/ready` 握手。

整帧每拍同时保留“输入灰度”和“处理后灰度”，两者的尺寸、坐标与帧信息一致。默认关闭去噪、采用单位增益和零偏置，此时两个通道相同。保留原始灰度便于后续 CPU/NPU 按任务选择输入，避免预处理把球边缘和关键细节不可逆地删掉。

ROI 保留原图绝对坐标，可从原始灰度或处理后灰度裁出矩形区域；越出图像的右、下边界自动截断。CPU 后续可根据上一帧的目标位置更新下一帧 ROI。内核不承担目标检测，也不把 ROI 改变、模型缩放和模型量化混在一起。

如果上游已经输出 RGB888，可先实例化独立的 `img_rgb888_to_gray`。它不包含 Bayer 解码；RAW8 Bayer 不能直接当作 GRAY8 接入。当前内核也不保留彩色图像，需要彩色场景识别或录像时，由上游另行保留彩色通路。

## 文件入口

- `../rtl/afh03_image/afh03_stereo_preproc.v`：真正接入板级工程的双路顶层，lane 0 位于打包总线低位。
- `../rtl/afh03_image/afh03_image_lane.v`：单路配置、帧检查、处理和输出分流。
- `../rtl/afh03_image/img_filter3x3.v`：三组行 RAM、窗口处理和四边补齐。
- `../rtl/afh03_image/img_luma_adjust.v`：带饱和限制的亮度增益/偏置。
- `../rtl/afh03_image/img_rgb888_to_gray.v`：可选 RGB888 灰度适配器。
- [INTERFACE.md](INTERFACE.md)：端口、数据位域、配置寄存器和异常处理。
- `td/`：TD 工程创建脚本、综合封装及处理时钟目标。
- `../sim/afh03_image/`：RTL 仿真 testbench；`../../tools/run_image_pipeline_tests.py`：独立逐像素参考与自动比对。

## 在 TD 中打开与综合

在项目根目录执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/build_afh03_image.ps1
```

脚本使用本机 TD `Release_2026.1_SP2`，在 `build/afh03-image-日期时间-随机后缀/` 创建原生 `afh03_image.al` 工程并运行综合。成功后控制台给出工程路径，`build/afh03-image-latest.txt` 记录最新成功目录。在 TD 中用 File → Open Project 打开该 `.al` 即可查看层级和源码。换安装目录时传入 `-TdRoot`。

工程顶层是 `afh03_image_compile_top`。它只用于把内核的宽数据/元数据接口收拢，以便通过封装 IO 数量检查；它完整实例化两路内核，并保留动态配置与输出观察通路。它不是摄像头接口、PCIe 协议，也不是最终上板顶层。后续板级工程应直接实例化 `afh03_stereo_preproc`。

每次构建复制一份当前 RTL，保存 `source-sha256.json` 以对应综合结果。日常修改仓库里的 RTL 后重新运行脚本；不要只改生成目录中的副本。`build/` 及工具生成数据库不进入版本管理。

当前 SDC 只设置 10 ns 的处理时钟目标。脚本止于综合，没有板级管脚分配、布局布线或 bitstream，也不据此承诺 100 MHz 时序收敛、图像帧率或上板可用性。

## 运行功能仿真

```powershell
python tools/run_image_pipeline_tests.py --waves
```

Python 脚本只使用标准库；HDL 仿真依赖 Icarus Verilog 的 `iverilog` 和 `vvp`。优先使用 `.tools/iverilog/app/bin`，也可通过 `--iverilog-dir` 指定本机路径，或在 PATH 中提供工具。`--waves` 仅为第一组随机种子保留 VCD。

脚本独立计算图像的边缘扩展、卷积、饱和亮度和 ROI，再对比每个输出像素、坐标、边界标记、帧号、时间戳和配置标签。测试也检查输出停顿时数据保持、两路互不阻塞、帧中改参、异常帧与复位恢复。运行目录位于 `tmp/afh03-image-tests-*`，结果以 `summary.json` 和实际仿真日志为准。

## 后续接硬件的位置

摄像头端需要确定像素格式和接口后补上解包/必要的颜色转换、跨时钟 FIFO、帧号及采集时间戳。摄像头物理端通常不能被 `ready` 暂停，必须由前端缓存吸收停顿；发生溢出时中止整帧并通知系统，不能直接丢几个像素后继续当正常图像。

DDR/PCIe 端需要把 `full_*` 和 `roi_*` 分别接入带反压的写帧/写 ROI 队列，按帧提交描述符，并将故障帧作废。两个输出都已在像素级提供坐标、时间戳和配置标签，但这里尚未规定内存布局、DMA 描述符或 PCIe 报文。

CPU 配置端需要由实际总线桥接为 `cfg_*` 写事务。CPU/NPU 的裁剪后缩放、彩色转换、模型归一化、量化和推理调度留在 RK3576J 侧实现。当前内核不做双目配对或曝光同步；两路帧时间信息原样交给软件进行后续标定和配对。

请结合 [接口草案](INTERFACE.md) 和 `../../handoffs/2026-09-24-afh03-image-pipeline.md` 接手。先保证单路无丢帧传输和元数据正确，再接第二路与软件任务。
