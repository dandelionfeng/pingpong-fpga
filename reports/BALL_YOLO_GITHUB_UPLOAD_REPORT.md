# 四个 Ball YOLO ONNX 上传 GitHub · 结果

日期：2026-10-21　分支：`codex/c-pc-detector`　提交：`554cbc076ecefbaa5b339dac60d91382e6542b3e`

## 0. 结论：**已真实上传并远程核验通过**

四个 ONNX 二进制已进入 GitHub 目标分支，远程克隆后逐字节校验哈希**全部一致**，
且四个文件在远端都能被 onnxruntime 正常加载。

| 项 | 值 |
| --- | --- |
| 仓库 | `https://github.com/fengfengkang/pingpong-fpga`（**私有仓库**，`private=true`） |
| 分支 | `codex/c-pc-detector` |
| 提交 | `554cbc076ecefbaa5b339dac60d91382e6542b3e`（短 SHA `554cbc0`） |
| 推送 | `95eda5f..554cbc0  codex/c-pc-detector -> codex/c-pc-detector`（fast-forward，无 force） |
| 远程当前头 | `554cbc0`（`git ls-remote` 与 GitHub API 一致） |
| `main` | `4ba0939b1da393cfeee103784f91378e2caa7bd6`，**未改动** |
| PR | 未创建、未合并 |

## 1. 四个模型在仓库中的路径

```text
artifacts/handoff/BALL_YOLO_FOUR_MODELS_FOR_CAPTAIN/models/
├── ball_yolo_v1_1280.onnx
├── ball_roboflow_960.onnx
├── ball_roboflow_1280.onnx
└── ball_v6_round2.onnx
```

| 文件 | 输入 | 大小 | 本机 SHA256 | 远程克隆后 SHA256 | 结果 |
| --- | --- | --- | --- | --- | --- |
| `ball_yolo_v1_1280.onnx` | 1280×1280 | 12,218,920 B | `185a337e…3a1f4a17b` | `185a337e…3a1f4a17b` | **一致** |
| `ball_roboflow_960.onnx` | 960×960 | 12,159,554 B | `7d2da4eb…38e85e3e36` | `7d2da4eb…38e85e3e36` | **一致** |
| `ball_roboflow_1280.onnx` | 1280×1280 | 12,218,920 B | `f5ec1e7a…5b2971802d9d` | `f5ec1e7a…5b2971802d9d` | **一致** |
| `ball_v6_round2.onnx` | 960×960 | 12,159,554 B | `d32b98d6…f49dd685383` | `d32b98d6…f49dd685383` | **一致** |

完整哈希：

```text
185a337ec9ed6c52e867c3748e889ef8fac56c855ce5cceb478a7213a1f4a17b  ball_yolo_v1_1280.onnx
7d2da4eb27b07a515551e141fafaa7c3e34253a4498812d2e3da5138e85e3e36  ball_roboflow_960.onnx
f5ec1e7a19deada33486ab65bee2f7e251c1594cb9d777eae0d55b2971802d9d  ball_roboflow_1280.onnx
d32b98d6a5a986b527654a7a34656a96d6d79a2702440bfffb36cf49dd685383  ball_v6_round2.onnx
```

## 2. 远程核验做了什么（可复查）

1. `git ls-remote origin codex/c-pc-detector` → `554cbc076ece…`，与本地 HEAD 相同。
2. **浅克隆整个仓库**到 `C:\pp_models\ball4_remote_verify`，克隆 HEAD = `554cbc076ece…`；
   对克隆出来的四个文件重新算 SHA256 → 与上表逐个相同（证明是真实字节，不是清单）。
3. 用 onnxruntime 加载克隆出来的四个文件，形状全部正确：

   | 文件 | 输入 | 输出 |
   | --- | --- | --- |
   | `ball_yolo_v1_1280.onnx` | `[1,3,1280,1280]` | `[1,5,33600]` |
   | `ball_roboflow_960.onnx` | `[1,3,960,960]` | `[1,5,18900]` |
   | `ball_roboflow_1280.onnx` | `[1,3,1280,1280]` | `[1,5,33600]` |
   | `ball_v6_round2.onnx` | `[1,3,960,960]` | `[1,5,18900]` |

4. GitHub API（带 token）：`GET /repos/fengfengkang/pingpong-fpga/contents/...?ref=554cbc0`
   返回四个 `type=file` 条目，`size` 分别为 12218920 / 12159554 / 12218920 / 12159554，与本地一致。
5. `GET /commits/554cbc0` → 该提交在远端存在，含 **11 个文件**。

## 3. 这次提交包含什么

| 文件 | 说明 |
| --- | --- |
| 4 × `models/*.onnx` | 真实二进制，逐字节与原始模型相同 |
| `config/model_manifest.json` | 形状/类别/来源/哈希/一致性/限制 |
| `MODEL_SHA256.txt` | 逐文件哈希清单 |
| `README_CAPTAIN.md` | 队长使用说明（含命令） |
| `THIRD_PARTY_NOTICES.md` | AGPL-3.0（YOLOv8n）/ CC BY 4.0（Roboflow）声明 |
| `tools/eval_ball_models.py`、`tools/score_ball_models.py` | README 里引用的推理与评分脚本（各 ~8 KB） |
| `.gitattributes`（新增一行 `*.onnx binary`） | 防止仓库已有的 `* text=auto eol=lf` 规则改写 ONNX 二进制 |

**刻意未提交**：67.7 MB 的交付 ZIP、42 张测试图（25.6 MB）、`gt/`、任何 `.pt`、任何数据集、
任何 `artifacts/` 下的其他内容。`artifacts/handoff/` 本来被 `.gitignore` 忽略，
本次只用 `git add -f` 精确添加上述指定路径，**没有把整个 `artifacts/` 纳入 Git**。

## 4. Git / 二进制策略

- 检查结果：`.gitignore:66` 忽略 `artifacts/handoff/`；无 LFS 规则（`git-lfs 3.7.1` 已安装但仓库未配置 LFS）。
- 依"优先沿用仓库现有规范"：仓库既有的二进制（如 `*.png`、`*.zip`）都是**普通 Git 文件**，
  因此四个 ONNX 也按普通 Git 文件提交，**未使用 Git LFS**。
- 单文件 12.2 MB，远低于 GitHub 100 MiB 上限。仓库体积因此增加约 **48.5 MB**（`size_KB` 现为 9,632 KB 的 API 口径，实际 `.git` 增长见下）。
- 无需 `git lfs` 推送，因此不存在 LFS 对象状态需要核对。

## 5. 队长怎么下载

仓库是**私有**的（`private=true`），队长需要先有该仓库的访问权限（collaborator 或被加到组织）。

方式 A —— 网页：

```text
https://github.com/fengfengkang/pingpong-fpga/tree/codex/c-pc-detector/artifacts/handoff/BALL_YOLO_FOUR_MODELS_FOR_CAPTAIN/models
```

进入文件页后点右上角 **Download raw file**，四个文件分别下载。

方式 B —— 命令行（有权限即可）：

```powershell
git clone -b codex/c-pc-detector https://github.com/fengfengkang/pingpong-fpga.git
cd pingpong-fpga\artifacts\handoff\BALL_YOLO_FOUR_MODELS_FOR_CAPTAIN
python tools/eval_ball_models.py --model ball_yolo_v1_1280 --source path\to\image_or_folder --out out\v1
```

下载后建议先自检：

```powershell
Get-FileHash models\*.onnx -Algorithm SHA256   # 与 MODEL_SHA256.txt 比对
```

## 6. 注意事项与限制

1. **仓库私有**：如果队长没有权限，网页会 404。需要蒲公英把队长加为 collaborator，
   或把交付内容挂到 **Release** 让有权限的人下载（本次未做 Release）。
2. `ball_roboflow_960.onnx` 与 `ball_roboflow_1280.onnx` 是**同一组权重的两种导出尺寸**，
   不是两个独立训练的模型。README 与 manifest 都已明确写下这一点。
3. 许可：权重基于 Ultralytics YOLOv8n（**AGPL-3.0**）；训练数据含 Roboflow v3（**CC BY 4.0**，需署名）。
   仓库私有 + 校内竞赛用途下风险可控；**对外分发前需确认 AGPL 义务**。
4. 未做：不训练、不重新导出、不改权重、不改 C++、不动 V2.4/V2.3 包、不推 `main`、不建 PR、不 force push。
5. 远程哈希核验方式是**浅克隆后本地重算 SHA256**（等价于读取远程字节），不是从网页复制哈希。

## 7. 可复查命令

```powershell
git ls-remote origin codex/c-pc-detector
git -C C:\pp_models\ball4_remote_verify rev-parse HEAD
Get-FileHash C:\pp_models\ball4_remote_verify\artifacts\handoff\BALL_YOLO_FOUR_MODELS_FOR_CAPTAIN\models\*.onnx -Algorithm SHA256
```
