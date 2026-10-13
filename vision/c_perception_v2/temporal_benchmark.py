"""连续视频 temporal diagnostic 数据集构建（BNDSTT_TEMPORAL_DIAGNOSTIC_V1）。

方法学要点（务必遵守）
----------------------
* 本数据集是 **UNLABELED DIAGNOSTIC SET**，不是 accuracy benchmark：
  BNDSTT 没有逐帧 ball+racket bbox GT，因此这里**不允许**报告 precision / recall / AP。
* 只使用**真正相邻**的帧：每个 clip 从单个 mp4 内**连续抽帧**，不隔帧抽取。
* **不拼接**同 session 的其它 clip —— 实测相邻 clip 间隔 3.9~54 秒，拼接会破坏帧邻接前提。
* 隔离：排除 quick_test session、排除 BNDSTT_30 已占用的 source；两者都写入报告并在构建时断言。
* 构建后 manifest 冻结（SHA256 记录），默认拒绝覆盖，需显式 force。
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# 同时支持两种用法：作为包导入与直接运行脚本（相对导入在两种情况下都成立）。
import sys as _sys
from pathlib import Path as _Path

if __package__ in (None, ""):
    _PACKAGE_DIR = _Path(__file__).resolve().parent
    _VISION_DIR = _PACKAGE_DIR.parent
    _REPO_ROOT = _VISION_DIR.parent
    for _entry in (str(_REPO_ROOT), str(_VISION_DIR), str(_PACKAGE_DIR)):
        if _entry not in _sys.path:
            _sys.path.insert(0, _entry)
    __package__ = "c_perception_v2"

from .config import PATHS
from .finetune_domain import read_csv_rows, stable_key

TEMPORAL_SEED = 20261013
CLIP_COUNT = 8
MIN_CONSECUTIVE_FRAMES = 30
TARGET_FRAMES_PER_CLIP = 110
BENCHMARK_NAME = "BNDSTT_TEMPORAL_DIAGNOSTIC_V1"

_TIMESTAMP = re.compile(r"_(\d{2})_(\d{2})_(\d{2})\.(\d{3})-(\d{2})_(\d{2})_(\d{2})\.(\d{3})")


class TemporalError(RuntimeError):
    """temporal 数据集阶段的硬失败。"""


def benchmark_dir() -> Path:
    return PATHS.repo_root / "artifacts" / "files" / "benchmarks" / BENCHMARK_NAME


def manifest_path() -> Path:
    return benchmark_dir() / "manifest.csv"


def frames_dir() -> Path:
    return benchmark_dir() / "frames"


def video_root() -> Path:
    return PATHS.bndstt_mvp_dir.parent / "BNDSTT" / "videos" / "origin"


# ================================================================ 隔离
def _benchmark_source_ids() -> set[str]:
    rows = read_csv_rows(PATHS.benchmark_manifest)
    return {row["source_id"] for row in rows}


def _benchmark_origin_tokens() -> set[str]:
    tokens = set()
    for source_id in _benchmark_source_ids():
        if "::" in source_id:
            tokens.add(source_id.split("::", 1)[1].split("__")[0])
    return tokens


def _quick_test_sessions() -> set[str]:
    path = PATHS.bndstt_mvp_dir / "split_manifest.csv"
    rows = read_csv_rows(path) if path.is_file() else []
    return {row["session_id"] for row in rows if row.get("split") == "quick_test"}


def _metadata_by_session() -> dict[str, dict]:
    path = PATHS.bndstt_mvp_dir / "split_manifest.csv"
    rows = read_csv_rows(path) if path.is_file() else []
    out: dict[str, dict] = {}
    for row in rows:
        out.setdefault(row["session_id"], row)
    return out


def parse_timestamp_range(name: str) -> tuple[float, float] | None:
    match = _TIMESTAMP.search(name)
    if not match:
        return None
    a = [int(match.group(i)) for i in range(1, 5)]
    b = [int(match.group(i)) for i in range(5, 9)]
    start = a[0] * 3600 + a[1] * 60 + a[2] + a[3] / 1000.0
    end = b[0] * 3600 + b[1] * 60 + b[2] + b[3] / 1000.0
    return start, end


# ================================================================ 选择
@dataclass
class ClipCandidate:
    session_id: str
    source_id: str
    video_path: Path
    video_name: str
    start_seconds: float
    end_seconds: float
    fps: float
    num_frames: int
    width: int
    height: int
    spin_code: str = ""
    landing_code: str = ""

    @property
    def duration(self) -> float:
        return self.end_seconds - self.start_seconds


def collect_candidates() -> tuple[list[ClipCandidate], dict]:
    """枚举 origin 视频并应用隔离过滤。"""
    import cv2

    root = video_root()
    if not root.is_dir():
        raise TemporalError("BNDSTT origin videos not found: " + str(root))
    quick_sessions = _quick_test_sessions()
    bench_tokens = _benchmark_origin_tokens()
    meta = _metadata_by_session()

    candidates: list[ClipCandidate] = []
    skipped_quick = 0
    skipped_bench = 0
    unreadable = 0
    for session_dir in sorted(root.iterdir()):
        if not session_dir.is_dir():
            continue
        session_id = session_dir.name
        is_quick = session_id in quick_sessions
        for mp4 in sorted(session_dir.glob("*.mp4")):
            if is_quick:
                skipped_quick += 1
                continue
            if any(token in mp4.name for token in bench_tokens):
                skipped_bench += 1
                continue
            rng = parse_timestamp_range(mp4.name)
            cap = cv2.VideoCapture(str(mp4))
            if not cap.isOpened():
                unreadable += 1
                cap.release()
                continue
            fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
            num = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            cap.release()
            if num < MIN_CONSECUTIVE_FRAMES or fps <= 0:
                continue
            row = meta.get(session_id, {})
            candidates.append(
                ClipCandidate(
                    session_id=session_id,
                    source_id=session_id + "::" + mp4.stem,
                    video_path=mp4,
                    video_name=mp4.name,
                    start_seconds=rng[0] if rng else 0.0,
                    end_seconds=rng[1] if rng else 0.0,
                    fps=fps,
                    num_frames=num,
                    width=width,
                    height=height,
                    spin_code=row.get("spin_code", ""),
                    landing_code=row.get("landing_code", ""),
                )
            )
    stats = {
        "origin_root": str(root),
        "skipped_quick_test_clips": skipped_quick,
        "skipped_benchmark_clips": skipped_bench,
        "unreadable_clips": unreadable,
        "usable_clips": len(candidates),
        "usable_sessions": len({c.session_id for c in candidates}),
    }
    return candidates, stats


def select_clips(candidates: list[ClipCandidate], count: int = CLIP_COUNT) -> list[ClipCandidate]:
    """确定性选择：优先不同 session，其次不同 source，再按稳定 hash 排序。"""
    by_session: dict[str, list[ClipCandidate]] = {}
    for candidate in candidates:
        by_session.setdefault(candidate.session_id, []).append(candidate)
    for session_id in by_session:
        by_session[session_id].sort(
            key=lambda c: (stable_key(c.source_id, TEMPORAL_SEED), c.video_name)
        )

    session_order = sorted(
        by_session,
        key=lambda sid: (stable_key("session:" + sid, TEMPORAL_SEED), sid),
    )
    chosen: list[ClipCandidate] = []
    used_videos: set[str] = set()
    for session_id in session_order:
        if len(chosen) >= count:
            break
        for candidate in by_session[session_id]:
            if candidate.source_id in used_videos:
                continue
            chosen.append(candidate)
            used_videos.add(candidate.source_id)
            break
    return chosen


# ================================================================ 抽帧
def extract_clip_frames(candidate: ClipCandidate, out_dir: Path) -> dict:
    """从单个 mp4 内**连续**抽取帧并落盘为 jpg。返回抽帧统计。"""
    import cv2

    from .dataset_qa import write_image_robust

    out_dir.mkdir(parents=True, exist_ok=True)
    target = min(TARGET_FRAMES_PER_CLIP, candidate.num_frames)
    cap = cv2.VideoCapture(str(candidate.video_path))
    if not cap.isOpened():
        raise TemporalError("cannot open video: " + str(candidate.video_path))
    saved = 0
    frame_index = 0
    while saved < target:
        ok, frame = cap.read()
        if not ok:
            break
        path = out_dir / ("f" + str(frame_index).zfill(4) + ".jpg")
        if not write_image_robust(path, frame, jpeg_quality=92):
            cap.release()
            raise TemporalError("failed to write frame: " + str(path))
        saved += 1
        frame_index += 1
    cap.release()
    return {
        "frames_written": saved,
        "source_frame_count": candidate.num_frames,
        "requested": target,
    }


# ================================================================ 构建
@dataclass
class TemporalResult:
    clips: list[dict] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    manifest: Path | None = None
    report: dict = field(default_factory=dict)


def build_temporal_set(force: bool = False, count: int = CLIP_COUNT) -> TemporalResult:
    target = manifest_path()
    if target.exists() and not force:
        raise TemporalError(
            "temporal manifest already exists (frozen): " + str(target)
            + "；本轮禁止 force-rebuild"
        )
    candidates, stats = collect_candidates()
    if len(candidates) < 6:
        raise TemporalError(
            "not enough isolated candidate clips: " + str(len(candidates)) + " (need >=6)"
        )
    chosen = select_clips(candidates, count=count)
    if len({c.source_id for c in chosen}) != len(chosen):
        raise TemporalError("source duplication in temporal selection")

    bench_sources = _benchmark_source_ids()
    quick_sessions = _quick_test_sessions()
    overlap_bench = sorted({c.source_id for c in chosen} & bench_sources)
    overlap_quick = sorted({c.session_id for c in chosen} & quick_sessions)
    if overlap_bench:
        raise TemporalError("temporal set overlaps BNDSTT_30 sources: " + str(overlap_bench))
    if overlap_quick:
        raise TemporalError("temporal set overlaps quick_test sessions: " + str(overlap_quick))

    clips: list[dict] = []
    for index, candidate in enumerate(chosen, start=1):
        clip_id = "clip" + str(index).zfill(2)
        clip_dir = frames_dir() / clip_id
        info = extract_clip_frames(candidate, clip_dir)
        digest = hashlib.sha256(candidate.video_path.read_bytes()).hexdigest()
        clips.append(
            {
                "clip_id": clip_id,
                "session_id": candidate.session_id,
                "source_id": candidate.source_id,
                "video_path": str(candidate.video_path),
                "video_name": candidate.video_name,
                "fps": round(candidate.fps, 4),
                "start_frame": 0,
                "end_frame": info["frames_written"] - 1,
                "num_frames": info["frames_written"],
                "width": candidate.width,
                "height": candidate.height,
                "duration_seconds": round(candidate.duration, 4),
                "sha256": digest,
                "spin_code": candidate.spin_code,
                "landing_code": candidate.landing_code,
                "frames_dir": str(clip_dir),
            }
        )

    benchmark_dir().mkdir(parents=True, exist_ok=True)
    columns = list(clips[0].keys())
    with open(target, "w", encoding="utf-8", newline="\n") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for clip in clips:
            writer.writerow(clip)
    manifest_digest = hashlib.sha256(target.read_bytes()).hexdigest()

    report = {
        "benchmark": BENCHMARK_NAME,
        "role": "UNLABELED_CONTINUOUS_VIDEO_TEMPORAL_DIAGNOSTIC",
        "not_a_metric_benchmark": True,
        "no_ground_truth": True,
        "forbidden_metrics": ["precision", "recall", "AP", "mAP", "accuracy", "TP", "FP"],
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "seed": TEMPORAL_SEED,
        "clips": len(clips),
        "sessions": len({c["session_id"] for c in clips}),
        "sources": len({c["source_id"] for c in clips}),
        "total_consecutive_frames": sum(c["num_frames"] for c in clips),
        "fps_range": [
            min(c["fps"] for c in clips),
            max(c["fps"] for c in clips),
        ],
        "frames_per_clip": [c["num_frames"] for c in clips],
        "benchmark_source_overlap": overlap_bench,
        "quick_test_overlap": overlap_quick,
        "frame_adjacency": "CONSECUTIVE_WITHIN_CLIP",
        "clips_are_not_concatenated": True,
        "candidate_stats": stats,
        "manifest": str(target),
        "manifest_sha256": manifest_digest,
    }
    (benchmark_dir() / "dataset_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _write_readme(report)
    return TemporalResult(clips=clips, stats=stats, manifest=target, report=report)


def load_manifest() -> list[dict]:
    path = manifest_path()
    if not path.is_file():
        raise TemporalError("temporal manifest missing: " + str(path))
    return read_csv_rows(path)


def manifest_digest() -> str:
    path = manifest_path()
    if not path.is_file():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_readme(report: dict) -> None:
    lines = [
        "# " + BENCHMARK_NAME,
        "",
        "**角色：无标注的连续视频 temporal 诊断集（UNLABELED DIAGNOSTIC）。**",
        "",
        "它不是 accuracy benchmark。BNDSTT 没有逐帧 ball+racket bbox GT，因此本数据集上",
        "**禁止**报告 precision / recall / AP / mAP / accuracy / TP / FP。只能报告",
        "candidate coverage、dropout、continuity 一类的**结构性指标**。",
        "",
        "## 与 BNDSTT_30_V1 的角色区别",
        "",
        "| 数据集 | 帧结构 | 用途 |",
        "| --- | --- | --- |",
        "| `BNDSTT_30_V1` | 30 帧来自 30 个不同 source，**不是连续序列** | 单帧 domain detection **coverage** |",
        "| " + BENCHMARK_NAME + " | " + str(report["clips"]) + " 段**段内真正相邻**的连续帧 | temporal candidate association **diagnostic** |",
        "",
        "因此：**禁止**在 BNDSTT_30 上做 3/5 帧平滑、max-vote、Kalman 等 temporal 评测（方法学错误）。",
        "",
        "## 规模",
        "",
        "- clips: " + str(report["clips"]),
        "- sessions: " + str(report["sessions"]),
        "- sources: " + str(report["sources"]),
        "- 连续帧总数: " + str(report["total_consecutive_frames"]),
        "- 每段帧数: " + str(report["frames_per_clip"]),
        "- fps 范围: " + str(report["fps_range"]),
        "- BNDSTT_30 source 重叠: " + str(report["benchmark_source_overlap"]),
        "- quick_test 重叠: " + str(report["quick_test_overlap"]),
        "- manifest SHA256: `" + report["manifest_sha256"] + "`",
        "",
        "## 抽帧约定",
        "",
        "每段从**单个 mp4 内部连续抽取**（frame t, t+1, t+2 …），不隔帧。",
        "**不拼接**同 session 的其它 clip —— 实测相邻 clip 间隔 3.9~54 秒，",
        "拼接会产生时间跳变，破坏 temporal 诊断的帧邻接前提。",
        "",
        "因此每段长度受原始发球片段长度限制（原始片段仅 0.6~0.8 秒）。",
        "",
        "## 复现",
        "",
        "```powershell",
        ".\\.venv\\c-detector\\Scripts\\python.exe vision\\c_perception_v2\\temporal_benchmark.py build",
        "```",
        "",
        "manifest 首次生成后即冻结（SHA256 记录在 `dataset_report.json`），",
        "默认拒绝覆盖；本轮禁止 `--force-rebuild`。",
    ]
    (benchmark_dir() / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="构建 " + BENCHMARK_NAME)
    parser.add_argument("command", choices=["build", "verify", "probe"], nargs="?", default="build")
    parser.add_argument("--force-rebuild", action="store_true")
    parser.add_argument("--clips", type=int, default=CLIP_COUNT)
    args = parser.parse_args(argv)

    if args.command == "probe":
        candidates, stats = collect_candidates()
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        chosen = select_clips(candidates, count=args.clips)
        for c in chosen:
            print("  " + c.session_id.ljust(30) + " " + c.video_name[:56]
                  + "  frames=" + str(c.num_frames))
        return 0
    if args.command == "verify":
        rows = load_manifest()
        report = json.loads((benchmark_dir() / "dataset_report.json").read_text(encoding="utf-8"))
        ok = manifest_digest() == report["manifest_sha256"]
        print("clips:", len(rows))
        print("total frames:", sum(int(r["num_frames"]) for r in rows))
        print("manifest sha256 match:", ok)
        return 0 if ok else 1

    result = build_temporal_set(force=args.force_rebuild, count=args.clips)
    print(json.dumps({k: v for k, v in result.report.items() if k != "candidate_stats"},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys

    sys.exit(main())
