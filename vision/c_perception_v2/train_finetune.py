"""BNDSTT 域内 fine-tune：两个变体（A BNDSTT-only / B mixed replay）。

关键要求（对应方案第 10/11/12 条）
----------------------------------
* 初始化权重：baseline ``ball_racket_yolov8n_v1/best.pt``（**不覆盖**，不从 yolov8n.pt 重来）；
* 两变体保持相同 ``seed / imgsz / epochs / batch / base weights``；
* 学习率使用适合 fine-tune 的较小值（``lr0=0.001``，``lrf=0.05``）；
* 不改模型结构；
* mixed replay 把公开 train 子集复制成 ``images/mixed_*``，replay 占比可配置（默认 0.30）。

产物
----
``artifacts/files/models/ball_racket_yolov8n_v2_domain_a/``（BNDSTT-only）
``artifacts/files/models/ball_racket_yolov8n_v2_domain_b/``（mixed replay）
``artifacts/runs/<name>/``（Ultralytics 原始输出）
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

# 同时支持两种用法：作为包导入与直接运行脚本（相对导入在两种情况下都成立）。
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path

    _PACKAGE_DIR = _Path(__file__).resolve().parent
    _VISION_DIR = _PACKAGE_DIR.parent
    _REPO_ROOT = _VISION_DIR.parent
    for _entry in (str(_REPO_ROOT), str(_VISION_DIR), str(_PACKAGE_DIR)):
        if _entry not in _sys.path:
            _sys.path.insert(0, _entry)
    __package__ = "c_perception_v2"
from .config import PATHS, TRAIN_SEED, TRAIN_WORKERS, assert_gitignored
from .finetune_domain import (
    TRAIN_SIZE,
    VAL_SIZE,
    baseline_hash,
    baseline_weights,
    build_finetune_dataset,
    dataset_hash,
    finetune_dir,
    model_dir,
    read_csv_rows,
    review_progress,
)

# fine-tune 参数（两变体必须一致）
FINETUNE_EPOCHS = 50
FINETUNE_PATIENCE = 15
FINETUNE_BATCH = 16
FINETUNE_IMGSZ = 640
FINETUNE_LR0 = 0.001
FINETUNE_LRF = 0.05
REPLAY_RATIO = 0.30
VARIANTS = {"a_bndstt_only": 0.0, "b_mixed_replay": REPLAY_RATIO}


class FinetuneTrainError(RuntimeError):
    pass


def disabled_analytics() -> bool:
    from .train_ball_racket import disable_analytics

    return disable_analytics()


# ================================================================ replay 数据集
def stable_key(text: str, seed: int = TRAIN_SEED) -> str:
    return hashlib.sha256((str(seed) + ":" + text).encode("utf-8")).hexdigest()


def build_replay_dataset(replay_ratio: float, out_dir: Path | None = None) -> dict:
    """把 BNDSTT 人工确认集 + 公开 train 子集组成一个数据集目录。

    ``replay_ratio`` 是公开数据在**总训练图数**中的占比；0 表示纯 BNDSTT。
    """
    if not 0.0 <= replay_ratio < 0.9:
        raise FinetuneTrainError("replay_ratio must be in [0, 0.9)")

    base = finetune_dir()
    bndstt_rows = read_csv_rows(base / "manifest.csv")
    verified = [row for row in bndstt_rows
                if (base / "annotations" / (row["image_id"] + ".json")).is_file()]
    if not verified:
        raise FinetuneTrainError(
            "no HUMAN_VERIFIED annotations yet；先用 annotator_br.py 完成人工确认"
        )

    assignment_path = base / "dataset_report.json"
    if not assignment_path.is_file():
        raise FinetuneTrainError("dataset_report.json missing；先运行 finetune_domain.py build")
    assignment = json.loads(assignment_path.read_text(encoding="utf-8"))["assignment"]

    out = Path(out_dir) if out_dir is not None else base / ("replay_" + str(replay_ratio).replace(".", ""))
    if out.exists():
        shutil.rmtree(out)
    for split in ("train", "val"):
        (out / "images" / split).mkdir(parents=True, exist_ok=True)
        (out / "labels" / split).mkdir(parents=True, exist_ok=True)

    # 1) BNDSTT 人工确认数据
    bndstt_images = {"train": 0, "val": 0}
    for row in verified:
        split = assignment[row["image_id"]]
        src_img = base / "images" / split / (row["image_id"] + ".jpg")
        src_lbl = base / "labels" / split / (row["image_id"] + ".txt")
        shutil.copy2(src_img, out / "images" / split / src_img.name)
        shutil.copy2(src_lbl, out / "labels" / split / src_lbl.name)
        bndstt_images[split] += 1

    # 2) 公开 replay（只加进 train；val 保持纯域内，便于看域内 val）
    replay_images = 0
    replay_instances = 0
    if replay_ratio > 0:
        target_replay = int(round(bndstt_images["train"] * replay_ratio / (1.0 - replay_ratio)))
        public = read_csv_rows(PATHS.br_dir / "manifest.csv")
        public_train = [row for row in public if row["split"] == "train"]
        public_train.sort(key=lambda row: stable_key(row["image"]))
        for row in public_train[:target_replay]:
            name = Path(row["image"]).name
            label_name = Path(row["label"]).name
            shutil.copy2(PATHS.br_dir / row["image"], out / "images" / "train" / name)
            shutil.copy2(PATHS.br_dir / row["label"], out / "labels" / "train" / label_name)
            replay_images += 1
            replay_instances += int(row["ball"]) + int(row["racket"])

    import yaml

    data_yaml = out / "data.yaml"
    data_yaml.write_text(
        "# 自动生成：fine-tune 训练数据（BNDSTT HUMAN_VERIFIED + 可选公开 replay）" + chr(10)
        + yaml.safe_dump(
            {
                "path": out.resolve().as_posix(),
                "train": "images/train",
                "val": "images/val",
                "nc": 2,
                "names": {0: "ball", 1: "racket"},
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    total_train = bndstt_images["train"] + replay_images
    report = {
        "out_dir": str(out),
        "data_yaml": str(data_yaml),
        "replay_ratio_requested": replay_ratio,
        "replay_ratio_actual": round(replay_images / total_train, 4) if total_train else 0.0,
        "bndstt_images": bndstt_images,
        "replay_images": replay_images,
        "replay_instances": replay_instances,
        "train_images_total": total_train,
        "val_images_total": bndstt_images["val"],
    }
    (out / "replay_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


# ================================================================ 训练
def train_variant(
    variant: str,
    epochs: int = FINETUNE_EPOCHS,
    imgsz: int = FINETUNE_IMGSZ,
    batch: int = FINETUNE_BATCH,
    device: str | int = 0,
    seed: int = TRAIN_SEED,
    workers: int = TRAIN_WORKERS,
) -> dict:
    """训练一个变体，返回报告（含哈希与指标口径）。"""
    if variant not in VARIANTS:
        raise FinetuneTrainError("unknown variant: " + variant)
    disabled_analytics()
    assert_gitignored([finetune_dir(), model_dir(variant), PATHS.project_dir])

    # 1) 确保人工确认数据集已构建（未全部确认会抛错）
    dataset_report = build_finetune_dataset()
    replay = build_replay_dataset(VARIANTS[variant])
    data_yaml = Path(replay["data_yaml"])

    weights = baseline_weights()
    if not weights.is_file():
        raise FinetuneTrainError("baseline weights missing: " + str(weights))

    from ultralytics import YOLO

    model = YOLO(str(weights))
    run_name = "finetune_v2_domain_" + variant
    model.train(
        data=str(data_yaml.resolve()),
        epochs=int(epochs),
        imgsz=int(imgsz),
        batch=int(batch),
        device=device,
        patience=FINETUNE_PATIENCE,
        seed=int(seed),
        workers=int(workers),
        amp=True,
        lr0=FINETUNE_LR0,
        lrf=FINETUNE_LRF,
        warmup_epochs=1.0,
        cos_lr=True,
        close_mosaic=5,
        pretrained=True,
        optimizer="auto",
        project=str(PATHS.project_dir.parent),
        name=run_name,
        exist_ok=True,
        plots=True,
        val=True,
        cache=False,
        deterministic=True,
        verbose=True,
    )

    run_dir = PATHS.project_dir.parent / run_name
    out_dir = model_dir(variant)
    _organize(run_dir, out_dir)
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "variant": variant,
        "run_dir": str(run_dir),
        "model_dir": str(out_dir),
        "base_weights": str(weights),
        "base_weights_sha256": baseline_hash(),
        "training_manifest_sha256": _sha256(finetune_dir() / "manifest.csv"),
        "dataset_hash": dataset_hash(),
        "replay": replay,
        "dataset": {
            "train_images": dataset_report["train_images"],
            "val_images": dataset_report["val_images"],
            "instances": dataset_report["instances"],
        },
        "hyperparameters": {
            "epochs": epochs, "imgsz": imgsz, "batch": batch, "seed": seed,
            "patience": FINETUNE_PATIENCE, "lr0": FINETUNE_LR0, "lrf": FINETUNE_LRF,
            "workers": workers, "amp": True,
        },
        "versions": _versions(),
    }
    (out_dir / "finetune_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def _sha256(path: Path) -> str:
    if not path.is_file():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _versions() -> dict:
    import torch
    import ultralytics

    return {
        "ultralytics": ultralytics.__version__,
        "torch": torch.__version__,
        "cuda": getattr(torch.version, "cuda", None),
    }


KEEP = (
    "results.csv", "results.png", "args.yaml", "confusion_matrix.png",
    "confusion_matrix_normalized.png", "PR_curve.png", "P_curve.png", "R_curve.png",
    "F1_curve.png", "labels.jpg", "labels_correlogram.jpg",
    "val_batch0_labels.jpg", "val_batch0_pred.jpg",
)


def _organize(run_dir: Path, out_dir: Path) -> dict:
    """把 best.pt / last.pt / 曲线复制到统一模型目录（硬链接优先）。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    mapping: dict[str, str] = {}
    sources = {name: run_dir / "weights" / name for name in ("best.pt", "last.pt")}
    for name, source in sources.items():
        if source.is_file():
            mapping[name] = _link_or_copy(source, out_dir / name)
    for name in KEEP:
        source = run_dir / name
        if source.is_file():
            mapping[name] = _link_or_copy(source, out_dir / name)
    mapping["run_dir"] = str(run_dir)
    (out_dir / "output_paths.json").write_text(
        json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return mapping


def _link_or_copy(source: Path, target: Path) -> str:
    if target.exists():
        target.unlink()
    try:
        os.link(source, target)
        return str(target) + " (hardlink)"
    except OSError:
        shutil.copy2(source, target)
        return str(target) + " (copy)"


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="BNDSTT 域内 fine-tune（两个变体）")
    parser.add_argument("--variant", choices=list(VARIANTS) + ["both"], default="both")
    parser.add_argument("--epochs", type=int, default=FINETUNE_EPOCHS)
    parser.add_argument("--imgsz", type=int, default=FINETUNE_IMGSZ)
    parser.add_argument("--batch", type=int, default=FINETUNE_BATCH)
    parser.add_argument("--device", default="0")
    parser.add_argument("--status", action="store_true", help="只看人工确认进度")
    args = parser.parse_args(argv)

    if args.status:
        print(json.dumps(review_progress(), ensure_ascii=False, indent=2))
        return 0

    variants = list(VARIANTS) if args.variant == "both" else [args.variant]
    reports = []
    for variant in variants:
        print("=== training variant: " + variant + " ===", flush=True)
        reports.append(
            train_variant(
                variant, epochs=args.epochs, imgsz=args.imgsz, batch=args.batch,
                device=args.device,
            )
        )
    print(json.dumps(reports, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys

    sys.exit(main())
