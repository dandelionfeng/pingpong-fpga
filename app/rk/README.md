# FPGA competition 2026 · app/rk

RK3576J 板端 Python/Shell 源码与冻结配置。run_capture.sh 为现场采集入口；preflight.py 检查原已配置 Linux 系统。完整部署载荷在 RAR 的 app/dist 中。

| 文件或目录 | 类型 |
| --- | --- |
| [algorithms/](algorithms/) | 目录 |
| [board_case.py](board_case.py) | 文件 |
| [calibration.json](calibration.json) | 文件 |
| [camera.sh](camera.sh) | 文件 |
| [capture_session.py](capture_session.py) | 文件 |
| [diagnostic_recorded.sh](diagnostic_recorded.sh) | 文件 |
| [field_logging.sh](field_logging.sh) | 文件 |
| [field_parameters.sh](field_parameters.sh) | 文件 |
| [field_workflow.py](field_workflow.py) | 文件 |
| [finish_measurement.py](finish_measurement.py) | 文件 |
| [model-config-int8.json](model-config-int8.json) | 文件 |
| [online_kinematics.py](online_kinematics.py) | 文件 |
| [payload-sha256.json](payload-sha256.json) | 文件 |
| [pc/](pc/) | 目录 |
| [preflight.py](preflight.py) | 文件 |
| [provision.py](provision.py) | 文件 |
| [rebind_pcie.sh](rebind_pcie.sh) | 文件 |
| [run_capture.sh](run_capture.sh) | 文件 |
| [run_recorded.sh](run_recorded.sh) | 文件 |
| [save_case_input.py](save_case_input.py) | 文件 |
| [stop_capture.py](stop_capture.py) | 文件 |
| [update_runtime.py](update_runtime.py) | 文件 |
| [version.json](version.json) | 文件 |

运行、发布包和验证范围见[仓库说明](..\..\README.md)。
