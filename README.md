# 发球测量系统 1.2.0

基于 AFH03 RK3576J、PH1A90 FPGA 与双 OV9281 的乒乓球发球测量软件。系统采集双目视频，通过 FPGA 运动 Mask、NPU 球与手拍识别、CPU 双目几何和运动学处理生成离手与轨迹测量结果。

## 运行

完整提交包解压后，双击 **发球测量系统.exe**。保留同目录的 `app`、`runtime` 和 `data` 文件夹。软件自动启动本地服务并打开图形工作台。

- 现场采集：J3 串口连接 PC，相机连接 RK，节点 `/dev/video73`，自动曝光，默认录制 30 秒。
- 部署和结果取回：J4 连接 PC。录制与分析完成并显示 `RECORDING_SAVED` 后取回。
- 本地回放：在“测试记录”中选择记录。三维演示支持拖拽旋转、空闲自动旋转和缩放。
- 安装检查：运行 `发球测量系统.exe --self-test --report 检查结果.json`。

详细步骤见 [操作说明](docs/操作说明.md)，系统组成见 [系统说明](docs/系统说明.md)，编号对应关系见 [实测记录](docs/实测记录.md)。

## 目录

| 目录或文件 | 内容 |
| --- | --- |
| 发球测量系统.exe | Windows 图形工作台入口 |
| app/pc、app/algorithms、app/ui | PC 程序、运动学代码和界面 |
| app/rk | RK 程序、固定运行配置及两份 INT8 RKNN 模型 |
| app/fpga | 已验证 bit 流及其来源记录 |
| runtime | PC Python 与板端离线依赖 |
| source/native | RK 原生链路源代码及构建配置 |
| hardware | FPGA RTL 与当前工程 |
| data | 六组重编号实测记录和回放 |
| docs、manifests、licenses | 说明、校验清单和第三方许可 |
| tools | EXE 构建与源码检查工具 |

## GitHub 源码与完整运行包

仓库保存本版源代码、配置、说明、校验值及 EXE 入口。权重、原视频、私有 SDK、厂商 IP、离线依赖和生成工程由完整本地提交包提供。对应文件可按 `manifests/model-sha256.json` 和运行清单核验。

仓库：[fengfengkang/pingpong-fpga](https://github.com/fengfengkang/pingpong-fpga)。开发基于 `codex/` 分支，通过 PR 合入 `main`。

## 构建 EXE

在 Windows Python 3.13 环境安装 `tools/requirements-build.txt` 中的构建依赖，再执行：

```powershell
python tools/build_windows.py
```

EXE 使用自身所在目录定位运行环境，启动过程直接调用 Python 服务。运行模型及测量阈值见 `app/version.json`。
