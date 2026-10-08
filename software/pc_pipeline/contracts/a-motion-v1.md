# A 共用接口 v1 草案

状态：按蒲公英本次实施计划实现的软件/RTL 内部契约。厂商 DMA 二进制协议尚未绑定；取得 SDK 后由相关负责人技术复核，蒲公英批准实际绑定。当前 `a-motion-v1-draft` 与历史图像内核接口分别管理。

## 接口变化与接入影响

| 接入方 | 当前新增入口 | 影响与复核内容 |
| --- | --- | --- |
| B CPU 测量 | `Registry.measurement` → `MeasurementModule` | 接收来源帧、两眼 Mask/参考身份；同帧框传入 `process`，迟到框走 `acceptDetections`；按需要请求右眼检测 |
| C 推理 | `Registry.detector` → `DetectorBackend` | 接收独立复制的原眼 GRAY8；自行预处理；框返回原眼像素坐标；必须保留模型版本并响应停止/期限 |
| B RTL 后四级 | `motion_front3` 的 valid/ready 输出 | threshold 为 1 bit；Gaussian/diff 为核对旁带；坐标、眼别、pair/time/config/ref 身份同步传递 |
| 厂商 SDK | `Registry.motion` → `PcieMotionBackend` / `DmaTransport` / `DmaBinding` | 绑定实际描述符、完成队列、缓存一致性、复位和 DDR 银行；软件 AM01 草案没有被直接当作硬件协议 |

各库包含 `pipeline/pipeline.hpp`，链接 `pipeline_module_api`。B/C 使用的回放与测试版本均在输出中保留后端标记；`--full` 要求实际 B 和声明 `actual-model` 的 C。接口测试库返回空测量，`model` 门禁拒绝测试后端。

## 帧及时间

`Meta`：`pair_id:uint64`、`timestamp_ns:int64`、`eye_timestamp_ns[2]`、`camera_frame_id[2]`、配置/标定/模型版本、时间来源与输入来源。pair 编号和两眼时间分别递增；坏输入会记录证据并拒收。算法按采样时间计算；wall-clock/完成时间不替代采样时间。

`FramePair`：两张 1280×720 原眼 GRAY8 与两张 640×360 搜索图。消费者持有 `FramePtr` 即可保持原图寿命；不得通过 Mat 数据指针改写共用输入。缓存只持有最新 8 对，检测上下文独立复制所需图像及身份，避免长任务依赖环形槽位。

来源请求时间明确为 `video_requested_time_not_device_capture`；人工样例为 `synthetic_16ms_fixture`。本次包的几何标记是 `duplicated_monocular_not_calibrated_stereo`。重复图像内容保留，编号/时间错误则拒绝。

## 运动结果及 ROI

`MotionResult` 包含帧身份、有效性/错误原因、task/generation/completion、后端及两眼 `EyeMotion`。CPU 的七级矩阵按 Gaussian、difference、threshold、erode1、dilate1、dilate2、erode2 排列；最终 Mask 为 0/255。设备仅返回 Mask 时其他阶段可为空，输出记录 `stages_available`。

每眼保留 `reference_valid`、`reference_id`、`reference_timestamp_ns`。首帧有效处理完成，但参考尚未建立：Mask 零、`invalid_uninitialized_reference`。失败保留原参考；复位/配置变更/运动超时清空参考并更新任务代际。

搜索中心 `(u,v)` 映射到原图 `(2u+0.5,2v+0.5)`。框边界与宽高乘 2。`cropRoi` 提供原图同帧 ROI，默认 256×256；原点 `floor(center)-128`；记录有效区域、padding、pair_id、eye。填充不会被解释成观测像素。

## C 检测及 B 测量

检测上下文含原图眼别、采样时间、参考身份、原眼尺寸、ROI 原点、task/generation。当前提交整眼，`origin=(0,0)`。C 如选择 ROI 推理，负责把框映射回原眼。

检测框为 `{"class":"ball|hand|racket","confidence":0..1,"bbox":[x,y,width,height]}`，原眼 1280×720 像素坐标，边界在眼图内部。非法或过期结果不带可用框。默认一条推理线程，左右共用 25 次/秒；同一输入先左后右。实时队列替换最旧尚未开始的检测任务，并记录其来源身份。

检测完成队列中结果永远属于 `source_pair_id`，迟到结果送 `acceptDetections()` 和 JSONL 档案。显示和 `process()` 只使用来源帧匹配且状态 `ok` 的框。B 的测量结果必须返回相同 pair_id，三维单位为米，各观察量明确为 observed、predicted 或 invalid。A 没有构造虚假球心或三维坐标。

## 软件序列化与黄金向量

AM01 帧头是显式字节序列，数值采用 little-endian：

| 偏移 | 字节数 | 内容 |
| --- | --- | --- |
| 0 | 4 | ASCII `AM01` |
| 4 | 2 | 版本 1 |
| 6 | 2 | 搜索宽 640 |
| 8 | 2 | 搜索高 360 |
| 10 | 2 | UTF-8 JSON 元数据字节数 |
| 12 | 4 | 图像 payload 字节数 460800 |
| 16 | 可变 | 元数据 JSON，随后左眼再右眼连续 GRAY8 |

固定头黄金向量在 [descriptor-header-golden-v1.json](descriptor-header-golden-v1.json)。不存在原生 struct 内存拷贝、编译器 padding 或隐式主机字节序。

Mask 暂定行优先，每行宽度须为 8 的倍数；像素 x 对应字节 `x/8` 的 bit `x%8`。640×360 每眼 28800 字节。[mask-golden-v1.json](mask-golden-v1.json) 给出独立两行期望字节 `81 02 04 40`。软件模拟 DMA 实际编码/解码输入并打包/解包最终 Mask，完成通知可延迟、乱序、超时或复位；参考处理按提交顺序。

## RTL 外部存储

`motion_front3` 参数默认 W=640、H=360、FIFO=32；宽高至少 2，FIFO 深度为 2 的幂。每眼独立活动银行与暂存银行，每银行 N=230400 字节的 Gaussian。地址为 `eye*2*N+bank*N+y*W+x`；4 银行共 921600 字节。

启动头：eye、pair_id64、timestamp64、config_tag32、threshold8。开始仅在 start_ready 时接收。处理完最后一个输出后 `done=1`，`commit` 才切换本眼参考；`abort_frame` 放弃暂存并保留旧参考。配置 tag 改变清空两眼参考。运动超时由系统适配层复位核心及存储事务，清除两眼参考。

读/写各有独立 valid/ready；停顿时 valid、地址、数据、epoch 保持，已完成的单侧请求只发送一次，双侧要求满足后才释放当前 Gaussian 像素。读响应在 epoch 内有序；旧 epoch 的响应被排空。硬件复位需连同 DDR/DMA 请求队列复位或排空，避免旧响应进入新任务；epoch16 使用范围要求旧请求在复用之前已排空。

目前只实现前三段 RTL。后四级及 LSB0 打包交 B；测试中存储模型只在 testbench。TD 的寄存器封装用于综合观察，不是 AFH03 PCIe IP 或最终引脚工程。

## 数据隔离

输入清单、配置、结果、框回放各有 schema_version。原始图像、工具、模型和输入内容通过 SHA-256 留证。算法不读取评分 truth；C 的回放框作为明确标记的检测后端输入，独立评分须另设入口。PC、RTL、综合、真实模型和实物各自记录验证范围。
