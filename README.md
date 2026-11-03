# 发球测量系统 1.2.1

基于 AFH03 RK3576J、PH1A90 FPGA 与双 OV9281 的乒乓球发球测量软件。系统采集双目视频，通过 FPGA 运动 Mask、NPU 球与手拍识别、CPU 双目几何和运动学处理生成离手与轨迹测量结果。

## 运行

完整提交包解压后，双击 **发球测量系统.exe**。保留同目录的 `app`、`runtime` 和 `data` 文件夹。软件自动启动本地服务并打开图形工作台。

竞赛源码包中的同名 EXE 带有源码审核运行时，不依赖 `runtime/python` 即可打开工作台、读取版本与冻结配置。源码包不含权重、原视频、ADB、板端离线依赖和六组完整回放；硬件操作、模型推理与实测回放应使用完整运行包。

- 源码包自检：`发球测量系统.exe --self-test --report 源码包检查.json`
- 完整包自检：`发球测量系统.exe --self-test --report 完整包检查.json`
- 自检报告中的 `mode` 分别为 `source-embedded` 与 `complete`，两者不互相替代。

详细步骤见 [操作说明](docs/操作说明.md)，系统组成见 [系统说明](docs/系统说明.md)，编号对应关系见 [实测记录](docs/实测记录.md)。

## 目录

| 目录或文件 | 内容 |
| --- | --- |
| 发球测量系统.exe | Windows 图形工作台入口；完整包优先使用外部运行时，源码包回退到内嵌审核运行时 |
| app/pc、app/algorithms、app/ui | PC 程序、运动学代码和界面 |
| app/rk | RK 程序、固定运行配置及两份 INT8 RKNN 模型 |
| app/fpga | 已验证 bit 流及其来源记录 |
| runtime | PC Python 与板端离线依赖 |
| source/native | RK 原生链路源代码及构建配置 |
| hardware | FPGA RTL 与当前工程 |
| data | 六组重编号实测记录和回放 |
| docs、manifests、licenses | 说明、校验清单和第三方许可 |
| tools | EXE 构建与源码检查工具 |

## AFH03 部署验证（2026-11-03）

`source/native/rk_runtime/c_rknn/` 已加入 8 输出 DFL 模型适配：识别 `[1,64,18900]` DFL 与首个 `[1,3,18900]` 分类 logits，统一走现有 DFL → NMS → 结果传递链路；保留 1/6 输出模式。8 输出模型要求 RKNN Runtime ≥ 2.5.0，不再用 2.3.0 硬性检查；实际板端加载和 FPS 仍需 AFH03 实测。

验证报告、509 张精度对照、诊断脚本和 SHA256 清单见 [artifacts/final_deployment](artifacts/final_deployment/)。**PC/模拟器结果不能替代 RK3576J 板端结果。**

第三阶段板端准备、官方 RKNN 2.5.0 资产核验、ARM64 构建和部署脚本见 [artifacts/board_validation](artifacts/board_validation/)。

## GitHub 源码与完整运行包

仓库保存本版源代码、配置、说明、校验值及 EXE 入口。权重、原视频、私有 SDK、厂商 IP、离线依赖和生成工程由完整本地提交包提供。对应文件可按 `manifests/model-sha256.json` 和运行清单核验。

仓库：[dandelionfeng/pingpong-fpga](https://github.com/dandelionfeng/pingpong-fpga)。开发基于 `codex/` 分支，通过 PR 合入 `main`。

## 构建 EXE

在 Windows Python 3.13 环境安装 `tools/requirements-build.txt` 中的构建依赖，再执行：

```powershell
python tools/build_windows.py
```

EXE 使用自身所在目录定位运行环境：存在 `runtime/python/python.exe` 时调用完整运行时；否则使用 EXE 内嵌解释器执行源码包中的 `app/pc/gui_server.py`。运行模型及测量阈值见 `app/version.json`，构建过程不改写该冻结配置。
