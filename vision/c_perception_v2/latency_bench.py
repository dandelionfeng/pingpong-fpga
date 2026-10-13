"""RTX GPU 上的延迟与吞吐测量（AH）。

测量对象（batch = 1，单张 1920x1080 BNDSTT 彩色帧）::

    1. YOLO ball+racket
    2. YOLOv8n-Pose
    3. combined（两者串行，即真实流水线单帧耗时）

口径：warmup 20 帧后测量 100 次迭代；每次迭代用 CUDA event 记录 GPU 时间，
同时用 ``perf_counter`` 记录端到端墙钟时间（含 letterbox / NMS / 后处理）。
报告 mean / median / P95 与理论 FPS。本轮**不测 RK3576**。
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
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
from .ball_racket import detect_ball_racket, load_detector
from .config import (
    BNDSTT_BENCHMARK_NAME,
    INFER_CONF_REPORT,
    INFER_IMGSZ,
    INFER_IOU,
    PATHS,
)
from .dataset_qa import read_image_robust
from .wrist_pose import infer_pose, load_pose_model

WARMUP_FRAMES = 20
MEASURE_ITERATIONS = 100


@dataclass
class TimingStats:
    label: str
    device: str
    iterations: int
    wall_ms: list[float] = field(default_factory=list)
    gpu_ms: list[float] = field(default_factory=list)

    def to_dict(self) -> dict:
        wall = sorted(self.wall_ms)
        gpu = sorted(self.gpu_ms)
        payload = {
            "label": self.label,
            "device": self.device,
            "iterations": self.iterations,
            "wall_mean_ms": _mean(wall),
            "wall_median_ms": _median(wall),
            "wall_p95_ms": _percentile(wall, 0.95),
            "wall_min_ms": wall[0] if wall else None,
            "wall_max_ms": wall[-1] if wall else None,
            "fps_theoretical": (1000.0 / _median(wall)) if wall and _median(wall) else None,
        }
        if gpu:
            payload.update(
                {
                    "gpu_mean_ms": _mean(gpu),
                    "gpu_median_ms": _median(gpu),
                    "gpu_p95_ms": _percentile(gpu, 0.95),
                    "gpu_fps_theoretical": (1000.0 / _median(gpu)) if _median(gpu) else None,
                }
            )
        return payload


def _mean(values: list[float]) -> float | None:
    return round(statistics.fmean(values), 4) if values else None


def _median(values: list[float]) -> float | None:
    return round(statistics.median(values), 4) if values else None


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    index = min(len(values) - 1, max(0, int(round(fraction * (len(values) - 1)))))
    return round(values[index], 4)


class _CudaTimer:
    """CUDA event 计时；没有 CUDA 时退化为墙钟计时。"""

    def __init__(self, device: str | int | None):
        import torch

        self.torch = torch
        self.enabled = bool(torch.cuda.is_available()) and str(device) != "cpu"
        self.start = self.end = None

    def __enter__(self):
        if self.enabled:
            self.start = self.torch.cuda.Event(enable_timing=True)
            self.end = self.torch.cuda.Event(enable_timing=True)
            self.torch.cuda.synchronize()
            self.start.record()
        return self

    def __exit__(self, *exc):
        if self.enabled:
            self.end.record()
            self.torch.cuda.synchronize()
        return False

    def elapsed_ms(self) -> float | None:
        if not self.enabled:
            return None
        return float(self.start.elapsed_time(self.end))


def pick_frames(count: int = 4, source_dir: Path | None = None) -> list[Path]:
    """挑几张 BNDSTT 彩色帧做基准输入（跨 session）。"""
    import cv2

    base = Path(source_dir) if source_dir is not None else PATHS.bndstt_mvp_dir / "images_color"
    candidates: list[Path] = []
    for split in ("train", "val"):
        directory = base / split
        if directory.is_dir():
            candidates.extend(sorted(directory.glob("*.jpg")))
    if not candidates:
        raise FileNotFoundError(f"no BNDSTT frames under {base}")
    step = max(1, len(candidates) // count)
    picked = candidates[::step][:count]
    frames = []
    for path in picked:
        image = read_image_robust(path)
        if image is not None:
            frames.append(path)
    return frames


def measure(
    weights: str | Path | None = None,
    pose_weights: str | Path | None = None,
    device: str | int = 0,
    imgsz: int = INFER_IMGSZ,
    warmup: int = WARMUP_FRAMES,
    iterations: int = MEASURE_ITERATIONS,
    frame_paths: list[Path] | None = None,
) -> dict:
    """执行完整测量并返回报告字典。"""
    import cv2
    import torch

    frames = frame_paths if frame_paths else pick_frames()
    images = []
    for path in frames:
        image = read_image_robust(path)
        if image is None:
            raise ValueError(f"cannot read frame: {path}")
        images.append(image)
    height, width = images[0].shape[:2]

    detector = load_detector(weights, device=device)
    pose_model = load_pose_model(pose_weights, device=device)

    cuda_available = bool(torch.cuda.is_available())
    gpu_name = torch.cuda.get_device_name(0) if cuda_available else None
    total_vram_gb = (
        round(torch.cuda.get_device_properties(0).total_memory / (1024 ** 3), 2)
        if cuda_available
        else None
    )

    stats = {
        "yolo_ball_racket": TimingStats("YOLO ball+racket", str(device), iterations),
        "pose": TimingStats("YOLOv8n-Pose", str(device), iterations),
        "combined": TimingStats("combined (A then B, serial)", str(device), iterations),
    }

    def run_once(image):
        import time

        wall_start = time.perf_counter()
        with _CudaTimer(device) as timer_br:
            detect_ball_racket(
                detector, image, conf=INFER_CONF_REPORT, iou=INFER_IOU, imgsz=imgsz, device=device
            )
        br_gpu = timer_br.elapsed_ms()
        br_wall = (time.perf_counter() - wall_start) * 1000.0

        wall_start = time.perf_counter()
        with _CudaTimer(device) as timer_pose:
            infer_pose(pose_model, image, conf=0.25, imgsz=imgsz, device=device)
        pose_gpu = timer_pose.elapsed_ms()
        pose_wall = (time.perf_counter() - wall_start) * 1000.0

        return (br_wall, br_gpu), (pose_wall, pose_gpu), (br_wall + pose_wall, None)

    for index in range(warmup):
        run_once(images[index % len(images)])

    for index in range(iterations):
        (br_wall, br_gpu), (pose_wall, pose_gpu), (sum_wall, _) = run_once(
            images[index % len(images)]
        )
        stats["yolo_ball_racket"].wall_ms.append(br_wall)
        if br_gpu is not None:
            stats["yolo_ball_racket"].gpu_ms.append(br_gpu)
        stats["pose"].wall_ms.append(pose_wall)
        if pose_gpu is not None:
            stats["pose"].gpu_ms.append(pose_gpu)
        stats["combined"].wall_ms.append(sum_wall)

    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "device_requested": str(device),
        "cuda_available": cuda_available,
        "gpu_name": gpu_name,
        "gpu_total_vram_gb": total_vram_gb,
        "torch_version": torch.__version__,
        "imgsz": imgsz,
        "input_size": [width, height],
        "warmup": warmup,
        "iterations": iterations,
        "frames_used": [str(p) for p in frames],
        "weights": str(weights) if weights else str(PATHS.model_out_dir / "best.pt"),
        "pose_weights": str(pose_weights) if pose_weights else str(PATHS.pose_weights_path),
        "benchmark_name": BNDSTT_BENCHMARK_NAME,
        "results": {key: value.to_dict() for key, value in stats.items()},
    }


def _print_report(report: dict) -> None:
    print("=" * 78)
    print(
        f"device={report['device_requested']} gpu={report['gpu_name']} "
        f"cuda={report['cuda_available']} torch={report['torch_version']}"
    )
    print(
        f"input={report['input_size']} imgsz={report['imgsz']} "
        f"warmup={report['warmup']} iters={report['iterations']}"
    )
    print("-" * 78)
    print(f"{'stage':<32}{'mean':>10}{'median':>10}{'P95':>10}{'FPS':>9}")
    for key in ("yolo_ball_racket", "pose", "combined"):
        entry = report["results"][key]
        print(
            f"{entry['label']:<32}{entry['wall_mean_ms']:>10.2f}"
            f"{entry['wall_median_ms']:>10.2f}{entry['wall_p95_ms']:>10.2f}"
            f"{entry['fps_theoretical']:>9.1f}"
        )
    print("=" * 78)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="GPU 延迟基准（ball+racket / pose / combined）")
    parser.add_argument("--weights", type=Path, default=None)
    parser.add_argument("--pose-weights", type=Path, default=None)
    parser.add_argument("--device", default="0")
    parser.add_argument("--imgsz", type=int, default=INFER_IMGSZ)
    parser.add_argument("--warmup", type=int, default=WARMUP_FRAMES)
    parser.add_argument("--iterations", type=int, default=MEASURE_ITERATIONS)
    parser.add_argument("--also-cpu", action="store_true", help="额外测一次 CPU")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    out_dir = Path(args.out) if args.out else PATHS.latency_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    report = measure(
        weights=args.weights,
        pose_weights=args.pose_weights,
        device=args.device,
        imgsz=args.imgsz,
        warmup=args.warmup,
        iterations=args.iterations,
    )
    target = out_dir / "latency_gpu.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _print_report(report)
    print(f"saved: {target}")

    if args.also_cpu:
        cpu_report = measure(
            weights=args.weights,
            pose_weights=args.pose_weights,
            device="cpu",
            imgsz=args.imgsz,
            warmup=max(3, args.warmup // 4),
            iterations=max(10, args.iterations // 5),
        )
        cpu_target = out_dir / "latency_cpu.json"
        cpu_target.write_text(
            json.dumps(cpu_report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print("[CPU]")
        _print_report(cpu_report)
        print(f"saved: {cpu_target}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys

    sys.exit(main())
