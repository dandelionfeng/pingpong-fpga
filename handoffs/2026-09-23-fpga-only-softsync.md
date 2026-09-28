# 任务交接

- 任务编号/负责人：2026-09-23 全 FPGA 与无 FSIN 同步方案 / Codex。
- 基准提交号/工作分支：8f94786 / codex/fpga-only-softsync-20260923。
- 当前目标与不包含的范围：根据用户新要求取消外接 NPU，优先软件同步，并纳入后续提出的 OV5640/DVP 候选。只交付架构与验证方案，不实施 RTL 或改写既有契约。
- 允许修改的文件：项目规划/全FPGA无FSIN同步方案.docx、本交接；构建及 QA 文件在忽略目录 tmp/fpga-only-softsync/。
- 输入输出/依赖的接口版本：读取现行规划及上一版独立评审；用户明确相机模组未确定，最好用软件同步，随后提出可能采用 OV5640 与 DVP。DVP 接口与全局/滚动快门分开评估；旧 FSIN pair_id 语义不能沿用。
- 环境与复现命令：C:/Users/20743/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe 执行 tmp/fpga-only-softsync/build.py；PowerShell 执行 tmp/fpga-only-softsync/export.ps1；相同 Python 执行 tmp/fpga-only-softsync/qa.py。layout.py 为本任务的独立排版辅助文件。
- 已执行检查及真实结果：官方资料核查了软件同步的帧长调节机制及帧率余量、OV5640 滚动快门/模式帧率/FREX、H10 HDMI、PH1A 资源。解析预算脚本得到每候选 663648 MAC、5928 字节 INT8 权重、16 候选在 32 MAC/100MHz 理想运算约 3.318ms；均为预算非板测。Word 6页、5表格、7超链接，Word COM 导出 PDF 后逐页渲染检查，结构断言通过。
- 未执行检查、阻塞与所需硬件：标准 render_docx.py 因无 soffice.exe 失败，使用 Word COM 与 pypdfium2 完成替代 QA。尚无实际相机同步、曝光时间映射、模型训练、RTL 仿真/综合/时序或整机测试。摄像头模组未定，不能承诺无 FSIN 的 10μs 目标，也不能保证 OV5640 等效替换双 OV9281。
- 修改文件与设计理由：新增一份独立方案，不覆盖既有 Word。推荐全 FPGA 后端和双 DVP 接收，曝光相位采用寄存器闭环控制；OV5640 普通视频有滚动快门与分辨率/帧率取舍，保留为验证候选。如果保持原高速动态精度，优先验证全局快门 DVP 模组。FREX 不写成现成高速全局快门功能。
- 下一步及验收条件：先做 3～5 天模组小样验证，核对 DVP 电平/时钟/引脚、工作模式、帧长更新粒度及生效延迟；使用已知时刻光脉冲测曝光而非只比较 VSYNC。同步和动态几何误差通过后，A/B/C 再冻结新时间、有效性、定点及模型接口。
