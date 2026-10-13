"""Stage 4-5 入口：GPU smoke test → 训练 smoke → 正式训练（含 OOM 自动降 batch）。

流程
----
1. **环境与 GPU smoke test**：torch.cuda 可用性、GPU 名称 / CUDA / 显存，然后
   YOLO(yolov8n.pt) 与 YOLO(yolov8n-pose.pt) 各对一张图 predict 成功；
2. **训练 smoke**：3 epochs + fraction 0.05 的一小步，确认数据管道与标签没问题；
3. **正式训练**：yolov8n.pt / imgsz 640 / epochs 120 / patience 25 / seed 42 /
   workers 4 / amp True；batch 从 16 开始，CUDA OOM 自动降 16 -> 8 -> 4；
4. 产物整理到 artifacts/files/models/ball_racket_yolov8n_v1/。

增强策略（P）：使用 Ultralytics 稳健默认值，不叠加激进 perspective / rotation / crop，
避免小球被裁掉或糊掉；只额外设置 close_mosaic=10 与 cos_lr。
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

# 同时支持两种用法：作为包导入（vision.c_perception_v2.xxx）与直接运行脚本。
# 直接运行时先把 仓库根/vision/包目录 放进 sys.path，再走绝对导入，
# 不替换 sys.modules、不改 __name__，因此文件末尾的 __main__ 守卫照常生效。
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

from . import CLASS_BALL, CLASS_NAMES, CLASS_RACKET  # noqa: E402,F401
from .dataset_qa import read_image_robust
from .config import (  # noqa: E402
    BASE_WEIGHTS_NAME,
    MODEL_NAME_TAG,
    PATHS,
    TRAIN_BATCH_CANDIDATES,
    TRAIN_EPOCHS,
    TRAIN_IMGSZ,
    TRAIN_PATIENCE,
    TRAIN_SEED,
    TRAIN_WORKERS,
    assert_gitignored,
)

KEEP_ARTIFACTS = (
    "results.csv",
    "results.png",
    "args.yaml",
    "confusion_matrix.png",
    "confusion_matrix_normalized.png",
    "PR_curve.png",
    "P_curve.png",
    "R_curve.png",
    "F1_curve.png",
    "labels.jpg",
    "labels_correlogram.jpg",
    "train_batch0.jpg",
    "val_batch0_labels.jpg",
    "val_batch0_pred.jpg",
)

OOM_MARKERS = (
    "out of memory",
    "cuda error: out of memory",
    "cublas_status_alloc_failed",
    "cudnn_status_alloc_failed",
)


def is_oom(error: BaseException) -> bool:
    text = (type(error).__name__ + ": " + str(error)).lower()
    return any(marker in text for marker in OOM_MARKERS)


def _safe_version(module_name: str):
    try:
        module = __import__(module_name)
        return getattr(module, "__version__", None)
    except Exception:
        return None


def disable_analytics() -> bool:
    """关闭 Ultralytics 的匿名使用统计（sync）。

    sync=True 时每次训练/预测都会向 ultralytics.com 发请求；在受限网络下会长时间
    阻塞启动，表现为“训练卡住不动”。本轮不需要任何联网遥测。
    """
    try:
        from ultralytics.utils import SETTINGS

        if SETTINGS.get("sync"):
            SETTINGS.update({"sync": False})
        return bool(SETTINGS.get("sync"))
    except Exception:
        return True


def environment_report() -> dict:
    """打印并返回 python / torch / CUDA / GPU / ultralytics 版本信息。"""
    import torch
    import ultralytics

    report = {
        "python": sys.version.split()[0],
        "torch": torch.__version__,
        "torchvision": _safe_version("torchvision"),
        "cuda_available": bool(torch.cuda.is_available()),
        "cuda_version": getattr(torch.version, "cuda", None),
        "ultralytics": ultralytics.__version__,
        "gpu_count": torch.cuda.device_count() if torch.cuda.is_available() else 0,
    }
    if report["cuda_available"]:
        properties = torch.cuda.get_device_properties(0)
        report["gpu_name"] = torch.cuda.get_device_name(0)
        report["gpu_total_vram_gb"] = round(properties.total_memory / (1024 ** 3), 2)
        report["gpu_compute_capability"] = str(properties.major) + "." + str(properties.minor)
    print("=" * 78)
    print("ENVIRONMENT")
    for key, value in report.items():
        print("  " + str(key).ljust(22) + ": " + str(value))
    print("=" * 78)
    return report


def _first_benchmark_image() -> Path:
    from .bndstt_benchmark import load_benchmark

    rows = load_benchmark()
    return Path(rows[0]["image_path"])


def gpu_smoke_test(sample_image: Path | None = None) -> dict:
    """检测器 A 与 Pose 各真实 predict 一次，两者都成功才允许训练。"""
    import cv2
    import torch
    from ultralytics import YOLO

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is not available; 本阶段要求 GPU 训练/推理")

    image_path = Path(sample_image) if sample_image else _first_benchmark_image()
    image = read_image_robust(image_path)
    if image is None:
        raise FileNotFoundError("cannot read smoke-test image: " + str(image_path))
    height, width = image.shape[:2]
    print("[smoke] image = " + str(image_path) + " (" + str(width) + "x" + str(height) + ")")

    detector = YOLO(str(PATHS.base_weights_path))
    detection = detector.predict(image, imgsz=640, conf=0.15, verbose=False)[0]
    det_count = int(len(detection.boxes)) if detection.boxes is not None else 0
    print("[smoke] YOLO(" + BASE_WEIGHTS_NAME + ") predict OK, boxes=" + str(det_count))

    pose = YOLO(str(PATHS.pose_weights_path))
    pose_result = pose.predict(image, imgsz=640, conf=0.25, verbose=False)[0]
    person_count = int(len(pose_result.boxes)) if pose_result.boxes is not None else 0
    keypoints = getattr(pose_result, "keypoints", None)
    if keypoints is None:
        raise RuntimeError("pose predict returned no keypoints object")
    shape = tuple(keypoints.xy.shape)
    print(
        "[smoke] YOLO(yolov8n-pose.pt) predict OK, persons="
        + str(person_count) + ", kp_shape=" + str(shape)
    )
    # keypoints.xy 形状为 (n, 17, 2) 或 (17, 2)；只有关键点维度不是 17 才算异常
    if 17 not in shape[1:]:
        raise RuntimeError("unexpected keypoint count: " + str(shape) + " (expected 17)")
    print("[smoke] PASS")
    return {
        "image": str(image_path),
        "image_size": [width, height],
        "detector_boxes": det_count,
        "pose_persons": person_count,
        "pose_keypoint_shape": list(shape),
    }


def train_once(
    data_yaml: Path,
    batch: int,
    epochs: int,
    name: str,
    fraction: float = 1.0,
    imgsz: int = TRAIN_IMGSZ,
    device: str | int = 0,
    patience: int = TRAIN_PATIENCE,
    seed: int = TRAIN_SEED,
    workers: int = TRAIN_WORKERS,
    weights: Path | None = None,
):
    """一次训练调用；fraction < 1 用于 smoke。"""
    disable_analytics()
    from ultralytics import YOLO

    model = YOLO(str(weights if weights is not None else PATHS.base_weights_path))
    results = model.train(
        data=str(Path(data_yaml).resolve()),
        epochs=int(epochs),
        imgsz=int(imgsz),
        batch=int(batch),
        device=device,
        patience=int(patience),
        seed=int(seed),
        workers=int(workers),
        amp=True,
        fraction=float(fraction),
        project=str(PATHS.project_dir.parent),
        name=name,
        exist_ok=False,
        pretrained=True,
        optimizer="auto",
        cos_lr=True,
        close_mosaic=10,
        plots=True,
        val=True,
        cache=False,
        deterministic=True,
        verbose=True,
    )
    return model, results


def _cleanup_failed_run(run_name: str) -> None:
    """OOM 失败留下的 run 目录改名，避免 Ultralytics 因重名自增序号。"""
    run_dir = PATHS.project_dir.parent / run_name
    if run_dir.is_dir():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        target = run_dir.with_name(run_name + "_oom_" + stamp)
        try:
            run_dir.rename(target)
            print("[train] moved failed run to " + target.name)
        except OSError:
            pass


def copy_or_link(source: Path, target: Path) -> str:
    """优先硬链接（省空间），失败则复制；返回实际使用的方式。"""
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    try:
        os.link(source, target)
        return "hardlink"
    except OSError:
        shutil.copy2(source, target)
        return "copy"


def organize_outputs(run_dir: Path, model_out_dir: Path) -> dict:
    """把 best.pt / last.pt / 曲线图整理到统一目录，并返回真实路径映射。"""
    run_dir = Path(run_dir)
    out = Path(model_out_dir)
    out.mkdir(parents=True, exist_ok=True)
    mapping: dict[str, str] = {}

    weights = {
        "best.pt": run_dir / "weights" / "best.pt",
        "last.pt": run_dir / "weights" / "last.pt",
    }
    for name, source in weights.items():
        if source.is_file():
            method = copy_or_link(source, out / name)
            mapping[name] = str(out / name) + " (" + method + ")"

    for name in KEEP_ARTIFACTS:
        source = run_dir / name
        if source.is_file():
            method = copy_or_link(source, out / name)
            mapping[name] = str(out / name) + " (" + method + ")"

    mapping["run_dir"] = str(run_dir)
    mapping["model_out_dir"] = str(out)
    (out / "output_paths.json").write_text(
        json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return mapping


def run_training(
    data_yaml: Path | None = None,
    epochs: int = TRAIN_EPOCHS,
    imgsz: int = TRAIN_IMGSZ,
    device: str | int = 0,
    smoke: bool = True,
    smoke_epochs: int = 3,
    smoke_fraction: float = 0.05,
    force_batch: int | None = None,
    run_name: str = MODEL_NAME_TAG,
) -> dict:
    """完整训练流程，返回报告字典。"""
    assert_gitignored([PATHS.project_dir, PATHS.raw_dir, PATHS.br_dir])
    disable_analytics()
    env = environment_report()
    smoke_report = gpu_smoke_test() if smoke else {}

    data_yaml = Path(data_yaml) if data_yaml else PATHS.br_data_yaml
    if not data_yaml.is_file():
        raise FileNotFoundError(
            "dataset yaml not found: " + str(data_yaml) + ". 先运行 prepare_tabletennis_br.py --auto"
        )

    if smoke:
        print(
            "[smoke] training smoke: epochs=" + str(smoke_epochs)
            + " fraction=" + str(smoke_fraction) + " batch=4"
        )
        train_once(
            data_yaml,
            batch=4,
            epochs=smoke_epochs,
            name=run_name + "_smoke",
            fraction=smoke_fraction,
            imgsz=imgsz,
            device=device,
            patience=max(1, smoke_epochs),
            workers=min(2, TRAIN_WORKERS),
        )
        print("[smoke] training smoke PASS")

    candidates = [force_batch] if force_batch else list(TRAIN_BATCH_CANDIDATES)
    last_error: BaseException | None = None
    used_batch: int | None = None
    for batch in candidates:
        print("[train] trying batch=" + str(batch) + " epochs=" + str(epochs) + " imgsz=" + str(imgsz))
        try:
            train_once(
                data_yaml,
                batch=batch,
                epochs=epochs,
                name=run_name,
                imgsz=imgsz,
                device=device,
            )
            used_batch = batch
            break
        except RuntimeError as error:
            if is_oom(error):
                print("[train] CUDA OOM at batch=" + str(batch) + "; 降 batch 重试（不改 imgsz）")
                last_error = error
                _cleanup_failed_run(run_name)
                continue
            raise
    if used_batch is None:
        raise RuntimeError("training failed for all batch candidates: " + str(last_error))

    final_dir = PATHS.project_dir.parent / run_name
    organized = organize_outputs(final_dir, PATHS.model_out_dir)
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "environment": env,
        "smoke": smoke_report,
        "data_yaml": str(data_yaml),
        "base_weights": str(PATHS.base_weights_path),
        "imgsz": imgsz,
        "epochs_requested": epochs,
        "batch": used_batch,
        "device": str(device),
        "run_dir": str(final_dir),
        "organized": organized,
        "class_names": list(CLASS_NAMES),
    }
    PATHS.reports_dir.mkdir(parents=True, exist_ok=True)
    (PATHS.reports_dir / "ball_racket_train_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("[train] DONE")
    printable = {k: v for k, v in report.items() if k != "environment"}
    print(json.dumps(printable, ensure_ascii=False, indent=2))
    return report


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="训练 ball+racket YOLOv8n（2 类）")
    parser.add_argument("--data", type=Path, default=None)
    parser.add_argument("--epochs", type=int, default=TRAIN_EPOCHS)
    parser.add_argument("--imgsz", type=int, default=TRAIN_IMGSZ)
    parser.add_argument("--device", default="0")
    parser.add_argument("--batch", type=int, default=None, help="强制 batch（跳过 16->8->4 自动降级）")
    parser.add_argument("--no-smoke", action="store_true")
    parser.add_argument("--smoke-only", action="store_true", help="只做 GPU + 训练 smoke")
    parser.add_argument("--env-only", action="store_true", help="只打印环境与 smoke 结果")
    args = parser.parse_args(argv)

    if args.env_only:
        environment_report()
        gpu_smoke_test()
        return 0
    if args.smoke_only:
        environment_report()
        gpu_smoke_test()
        train_once(
            Path(args.data) if args.data else PATHS.br_data_yaml,
            batch=4,
            epochs=3,
            name=MODEL_NAME_TAG + "_smoke",
            fraction=0.05,
            imgsz=args.imgsz,
            device=args.device,
            patience=3,
            workers=2,
        )
        print("[smoke-only] PASS")
        return 0

    run_training(
        data_yaml=args.data,
        epochs=args.epochs,
        imgsz=args.imgsz,
        device=args.device,
        smoke=not args.no_smoke,
        force_batch=args.batch,
    )
    return 0


if __name__ == "__main__" or getattr(globals().get("_entry_module"), "__name__", "") == "__main__":
    sys.exit(main())
