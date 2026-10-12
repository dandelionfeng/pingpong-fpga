# A MJPEG输入适配与1.0.1发布交接

- 任务编号/负责人：A-MJPEG-20261012 / Codex，最终授权人蒲公英。
- 基准提交号/工作分支：`fe7af549464b290b2573199a1cf5a00ebf4432a5` / `codex/a-mjpeg-input-20261012`。
- 当前目标与不包含的范围：新增MJPEG文件/截图包、Linux V4L2协商/解码，替换旧软件发布；不修改现有尺寸、60fps请求、曝光、算法、GUI、B/C数据结构或RTL，不合入其他任务分支。
- 允许修改的文件：`software/pc_pipeline`输入/构建/版本/契约与测试，`tools/a_pipeline`生成/像素复核/打包；当前README、下载说明、报告及本交接。
- 输入输出/依赖的接口版本：清单schema 1新增MJPG/MJPEG格式，压缩数据只在A输入边界存在；输出仍为原`FramePair`/`Meta`与`a-motion-v1-draft`。OpenCV4.13.0、Qt6.8.3保持固定。
- 环境与复现命令：Windows运行`tools/a_pipeline/build_windows.ps1 -DependenciesRoot 'C:\FPGA competition'`；Linux运行`build_linux.sh`；用`generate_mjpeg_fixture.py --output output/mjpeg-new --pairs 125`生成人工输入，CLI/GUI按[验证报告](../reports/MJPEG适配验证_20261012.md)运行。
- 已执行检查及真实结果：Windows/Linux各2/2 CTest；125对JPEG独立核对；Windows Qt实际操作、导入/播放/ROI/导出与CLI一致；CPU/mock、慢处理替换、身份门禁通过；旧125对YUY2及8对人工混合输入Mask哈希保持相同；便携Windows及Linux CLI样例通过；5个仓库测试通过。细节见[JSON](../reports/MJPEG适配验证_20261012.json)。
- 未执行检查、阻塞与所需硬件：真实相机60fps/同步/JPEG质量、RK部署、设备DMA/DDR与整机；本轮未重验RTL/TD及10,000对压力。Windows没有新增实时相机入口，Linux便携GUI交互未重验。
- 修改文件与设计理由：`mjpeg.cpp`检查单帧JPEG并直接灰度解码；`io.cpp`扩展清单/截图包；`v4l2.cpp`按原模式优先协商并处理可变长度；`mjpeg_tests.cpp`独立覆盖输入错误与采集边界；样例生成器使用Pillow，避免只以OpenCV自编码自验证；打包器只收Git跟踪源码。
- 发布/旧版处理：当前[A 1.0.1 Release](https://github.com/fengfengkang/pingpong-fpga/releases/tag/a-pipeline-pc-20261012)，Windows包、完整源码、Linux包和验证证据分别提供。用户已明确授权上传新版及删除旧版，检查通过后按CONTRIBUTING采用PR/squash；新版核验后移除旧1.0.0软件附件和本地活动dist目录，保留本地`C:\FPGA competition-backups\20261012-before-mjpeg`副本与历史Git/报告/人工输入。
- 下一步及验收条件：B/C继续用原GRAY8/Mask/ROI接口；接相机后确认协商MJPG2560×720@60、实测帧率/采样时间/同步、坏帧恢复与长稳，再评估压缩对球心/模型影响。确需调整阈值、模型预处理或协议时另行提交兼容影响，交蒲公英审批。

原主工作区未切分支或覆盖他人修改；实现位于已附加的独立worktree。接手先阅读AGENTS.md与当前路线，再以最新已评审main建立分支。
