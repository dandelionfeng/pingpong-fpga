"""C 端感知 V2：ball + racket 检测（YOLOv8n）+ Pose 手腕（YOLOv8n-Pose）。

本包是 C 模块视觉路线的新方案（2026-10）。与旧 ``vision/bndstt_mvp`` 的
ball/hand/racket 三类方案并存，不替换、不修改旧模块的 DetectionResult API。

模块划分::

    config.py             路径、常量、Roboflow v2 来源元数据、Git 忽略自检
    roboflow_v2.py        v2 ZIP 获取（环境变量 API key）与解压到 RAW
    data_prep.py          RAW 审计 + ball/racket 二分类转换 + dataset.yaml
    dataset_qa.py         GT 可视化与 QA contact sheet
    ball_racket.py        检测器 A：ball + racket，PerceptionResultV2
    wrist_pose.py         检测器 B：COCO 17 关键点中的 left/right wrist
    fusion.py             HEURISTIC 候选关联（server / racket wrist / toss wrist）
    fusion_demo.py        BNDSTT 30 帧上的联合可视化与 contact sheet
    latency_bench.py      GPU 延迟与吞吐测量
    train_ball_racket.py  正式训练（含 OOM 自动降 batch）
    eval_ball_racket.py   test split 正式评估 + tiny-ball 失败分析

所有输出写入被 Git 忽略的 ``artifacts/files/`` 与 ``artifacts/runs/``。
"""

from __future__ import annotations

SCHEMA_VERSION = "c_perception_v2/1"

# 最终二分类类别顺序（固定，不可调换）
CLASS_NAMES = ("ball", "racket")
CLASS_BALL = 0
CLASS_RACKET = 1
NUM_CLASSES = 2

__all__ = [
    "SCHEMA_VERSION",
    "CLASS_NAMES",
    "CLASS_BALL",
    "CLASS_RACKET",
    "NUM_CLASSES",
]
