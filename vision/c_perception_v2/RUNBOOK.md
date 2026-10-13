# C 端感知 V2 运行手册

按阶段推进：**download -> audit -> conversion -> 1-batch smoke -> short training smoke
-> full training -> test -> pose -> BNDSTT30 -> fusion**。每阶段 PASS 后再进入下一阶段。

解释器固定为：

```powershell
$python = ".\.venv\c-detector\Scripts\python.exe"
```

## Stage 1 数据获取

优先自动：设置环境变量 `ROBOFLOW_API_KEY` 后运行

```powershell
& $python vision\c_perception_v2\prepare_tabletennis_br.py --auto
```

没有 key（或 SDK 下载失败、网络受限）时，程序输出 `WAITING_FOR_TABLETENNIS_V2_ZIP`
并给出精确人工步骤。把 ZIP 放到：

```text
artifacts/files/datasets/downloads/tabletennis_nbcdc_v2_yolov8.zip
```

再运行同一条命令即可自动解压并继续。**不要**换数据集、不要用 v1。

## Stage 2 只审计不转换

```powershell
& $python vision\c_perception_v2\prepare_tabletennis_br.py --audit-only
```

输出真实的 `class_id -> class_name`、`ball`/`racket` 的实际 id、每个 split 的实例统计。
若总数不是 1480，脚本直接 FAIL（防止误用 v1 或被自动 augmentation 的版本）。

## Stage 3 转换 + QA

`--auto` 已包含转换与 QA。产物：

```text
artifacts/files/datasets/tabletennis_ball_racket_v1/{images,labels}/{train,val,test}
artifacts/files/datasets/tabletennis_ball_racket_v1/{data.yaml,SOURCE.md,manifest.csv,dataset_card.json}
artifacts/files/reports/tabletennis_br_dataset_qa/{train_random_50,val_random_30,test_random_30}.jpg
```

## Stage 4 GPU smoke（不训练）

```powershell
& $python vision\c_perception_v2\train_ball_racket.py --env-only
```

打印 python / torch / CUDA / GPU / 显存，并对 `yolov8n.pt` 与 `yolov8n-pose.pt` 各做一次
真实 predict。**两者都成功才允许训练**。

## Stage 5 训练

```powershell
# 只做 smoke（3 epochs, fraction 0.05）
& $python vision\c_perception_v2\train_ball_racket.py --smoke-only

# 正式训练：imgsz 640 / epochs 120 / patience 25 / seed 42 / workers 4 / amp True
& $python vision\c_perception_v2\train_ball_racket.py
```

batch 从 16 开始，CUDA OOM 时自动降 16 -> 8 -> 4（**不改 imgsz**）。产物整理到
`artifacts/files/models/ball_racket_yolov8n_v1/`（best.pt / last.pt / args.yaml /
results.csv / results.png / confusion_matrix.png / PR_curve.png / F1_curve.png）。

## Stage 6 test 评估

```powershell
& $python vision\c_perception_v2\eval_ball_racket.py
```

输出 overall 与 ball / racket 各自的 P、R、AP50、AP50-95，并生成
`artifacts/files/reports/test_ball_failures/`（FN / 低置信 / 误检 / 小球 contact sheet）。

## Stage 7 BNDSTT 30 域内验证

```powershell
& $python vision\c_perception_v2\bndstt_benchmark.py verify
& $python vision\c_perception_v2\fusion_demo.py --weights artifacts\files\models\ball_racket_yolov8n_v1\best.pt
```

产出 `artifacts/files/reports/BNDSTT_30_FUSION_V1/`：每张 fusion 图 + 三张 contact sheet
（fusion / ball_racket_only / pose_only）+ `fusion_results.json`。

## Stage 8 延迟

```powershell
& $python vision\c_perception_v2\latency_bench.py --also-cpu
```

## 故障排查

| 现象 | 处理 |
| --- | --- |
| `WAITING_FOR_TABLETENNIS_V2_ZIP` | 按提示人工下载 ZIP 放入 downloads/ |
| RAW 图片数不是 1480 | 停止训练，检查是否 v1 或自动 augmentation |
| CUDA OOM | 脚本自动降 batch；不要改 imgsz 躲 OOM |
| `images not found` | 检查 `data.yaml` 的 `path` 是否为绝对路径 |
| git 自检失败 | 数据/权重目录必须保持 git ignored，不要改 .gitignore |

## Stage 9 BNDSTT DOMAIN FINE-TUNE V1（域内微调）

```powershell
$python = ".\.venv\c-detector\Scripts\python.exe"

# 1) 已自动完成：80 帧确定性选池（排除 frozen benchmark 与 quick_test）
& $python vision\c_perception_v2\finetune_domain.py pool

# 2) 已自动完成：复制到 workspace 并用 baseline best.pt 预标（conf=0.10）
& $python vision\c_perception_v2\finetune_domain.py proposals

# 3) 人工确认（必须由人完成，见 ANNOTATION_GUIDE.md）
& $python vision\c_perception_v2\annotator_br.py --port 8899   # 打开 http://127.0.0.1:8899/
& $python vision\c_perception_v2\finetune_domain.py status      # 查看 0/80 进度

# 4) 80 张全部 HUMAN_VERIFIED 后：构建数据集（未确认会直接拒绝）
& $python vision\c_perception_v2\finetune_domain.py build

# 5) 训练两个变体：A BNDSTT-only / B mixed replay（公开数据占 30%）
& $python vision\c_perception_v2\train_finetune.py --variant both

# 6) 三模型三处对比 + 阈值扫描 + contact sheet
& $python vision\c_perception_v2\eval_finetune.py
```

产物：

- 数据：`artifacts/files/datasets/BNDSTT_BR_FINETUNE_V1/`
- 模型：`artifacts/files/models/ball_racket_yolov8n_v2_domain_a/`、`..._b/`
- 对比报告：`artifacts/files/reports/FINETUNE_COMPARE_V1/comparison.md`

硬约束：本阶段 **不做** ONNX / RKNN / RK3576 / AFH03；不覆盖 v1 baseline；
不使用 quick_test；不修改 frozen `BNDSTT_30_V1`。
