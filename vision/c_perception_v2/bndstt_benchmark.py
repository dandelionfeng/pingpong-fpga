"""BNDSTT 30 帧固定 benchmark 的确定性构建（Z 段）。

要求
----
* 从现有 280 张域内彩色帧中**确定性**选 30 张（同一次运行、同一份清单）；
* 跨多个 session / 多个 source video，覆盖 7 个发球阶段；
* **不**从 quick_test 抽取（本文件会断言零 session 重叠）；
* 生成后 ``benchmark_manifest.csv`` 即冻结：默认拒绝覆盖，需显式 ``--force``。

选择算法（可复现）
------------------
1. 固定 ``SEED``；对每张图计算稳定 key = ``sha256(f"{SEED}:{image_id}")``；
2. 按 7 个 stage_hint 分组（每组 40 张），组内按稳定 key 升序 = 固定顺序；
3. 轮转各阶段依次取帧；每轮优先选 **未使用过的 session 与 source** 的帧；
4. 取满 30 张为止，并校验最少 session / source / contact 阶段数量。
"""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# 同时支持两种用法：作为包导入与直接运行脚本（python vision/c_perception_v2/xxx.py）
import sys

if __package__ in (None, ""):
    _PACKAGE_DIR = str(Path(__file__).resolve().parent)
    _VISION_DIR = str(Path(__file__).resolve().parents[1])
    if _VISION_DIR not in sys.path:
        sys.path.insert(0, _VISION_DIR)
    if _PACKAGE_DIR not in sys.path:
        sys.path.insert(0, _PACKAGE_DIR)
    __package__ = "c_perception_v2"

from .config import (
    BNDSTT_BENCHMARK_NAME,
    BNDSTT_BENCHMARK_SIZE,
    BNDSTT_MIN_NEAR_CONTACT,
    BNDSTT_MIN_SESSIONS,
    BNDSTT_MIN_SOURCES,
    PATHS,
)

SEED = 20261012

# 发球阶段顺序（轮转用），与 frames_manifest.csv 的 stage_hint 对应
STAGE_ORDER: tuple[str, ...] = (
    "ready_or_hold_candidate",
    "toss_start_candidate",
    "rising_candidate",
    "mid_high_candidate",
    "apex_candidate",
    "descending_or_racket_approach_candidate",
    "contact_or_followthrough_candidate",
)
STAGE_LABELS = {
    "ready_or_hold_candidate": "发球准备",
    "toss_start_candidate": "抛球",
    "rising_candidate": "球上升",
    "mid_high_candidate": "中高位",
    "apex_candidate": "最高点附近",
    "descending_or_racket_approach_candidate": "下降/球拍接近",
    "contact_or_followthrough_candidate": "击球附近/随挥",
}
NEAR_CONTACT_STAGES = {
    "apex_candidate",
    "descending_or_racket_approach_candidate",
    "contact_or_followthrough_candidate",
}


class BenchmarkError(RuntimeError):
    pass


def stable_key(image_id: str, seed: int = SEED) -> str:
    return hashlib.sha256(f"{seed}:{image_id}".encode("utf-8")).hexdigest()


def _clean_row(row: dict) -> dict:
    return {(key or "").lstrip("\ufeff").strip(): (value or "").strip() for key, value in row.items()}


def read_csv_rows(path: Path) -> list[dict]:
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        return [_clean_row(row) for row in csv.DictReader(handle)]


@dataclass
class BenchmarkEntry:
    image_id: str
    image_path: Path
    split: str
    session_id: str
    source_id: str
    stage_hint: str
    frame_index: str
    fraction: str
    source_video_path: str
    width: str
    height: str
    selection_reason: str = ""

    def to_row(self) -> dict:
        return {
            "image_id": self.image_id,
            "image_path": str(self.image_path),
            "rel_image_path": self.image_path.name,
            "split": self.split,
            "session_id": self.session_id,
            "source_id": self.source_id,
            "stage_hint": self.stage_hint,
            "stage_label": STAGE_LABELS.get(self.stage_hint, self.stage_hint),
            "frame_index": self.frame_index,
            "fraction": self.fraction,
            "source_video_path": self.source_video_path,
            "width": self.width,
            "height": self.height,
            "is_quick_test": "0",
            "selection_reason": self.selection_reason,
        }


@dataclass
class BenchmarkResult:
    entries: list[BenchmarkEntry] = field(default_factory=list)
    manifest: Path | None = None
    report: dict = field(default_factory=dict)


def check_quick_test_isolation(frames_rows: list[dict], split_rows: list[dict]) -> dict:
    """断言 benchmark 候选帧与 quick_test 视频零 session 重叠。"""
    quick_sessions = {
        row.get("session_id", "") for row in split_rows if row.get("split") == "quick_test"
    }
    frame_sessions = {row.get("session_id", "") for row in frames_rows}
    overlap = sorted(s for s in quick_sessions & frame_sessions if s)
    return {
        "quick_test_sessions": len({s for s in quick_sessions if s}),
        "frame_sessions": len({s for s in frame_sessions if s}),
        "overlap": overlap,
        "isolated": not overlap,
    }


def load_candidates(mvp_dir: Path | None = None) -> tuple[list[dict], list[dict]]:
    base = Path(mvp_dir) if mvp_dir is not None else PATHS.bndstt_mvp_dir
    frames = read_csv_rows(base / "frames_manifest.csv")
    splits_path = base / "split_manifest.csv"
    splits = read_csv_rows(splits_path) if splits_path.is_file() else []
    return frames, splits


def _to_entry(
    row: dict, mvp_dir: Path, prefer_new: bool = True, reason: str = "stage-robin"
) -> BenchmarkEntry:
    relative = row.get("original_image_path") or row.get("derived_gray3_path") or ""
    image_path = Path(mvp_dir) / relative if relative else Path(mvp_dir) / "images_color"
    # frames_manifest.csv 没有 image_id 列，image_id 以图片文件名派生（稳定且唯一）
    image_id = row.get("image_id", "").strip() or image_path.stem
    return BenchmarkEntry(
        image_id=image_id,
        image_path=image_path,
        split=row.get("split", ""),
        session_id=row.get("session_id", ""),
        source_id=row.get("source_id", ""),
        stage_hint=row.get("stage_hint", ""),
        frame_index=row.get("frame_index", ""),
        fraction=row.get("fraction", ""),
        source_video_path=row.get("source_video_path", ""),
        width=row.get("width", "1920"),
        height=row.get("height", "1080"),
        selection_reason=(
            reason + (";new-source-first" if prefer_new else ";filled") + f";seed={SEED}"
        ),
    )


def select_frames(
    frames_rows: list[dict],
    mvp_dir: Path,
    count: int = BNDSTT_BENCHMARK_SIZE,
) -> list[BenchmarkEntry]:
    """确定性选择：先铺满未使用过的 source（每源一次），再按阶段轮转逐帧补齐。

    数据事实：40 个 source，每个 source 恰好贡献 7 个阶段各一帧。因此本函数保证

    1. 第一轮：每个阶段各取一帧，且尽量来自**未使用的 source**（跨 7 个阶段共 7 帧）。
       7 帧 == 7 个阶段，所以第一轮就拿到 7 个不同 source；
    2. 第二轮：同样的规则（此时只剩未使用 source）→ 又 7 帧；
    3. 第三、四轮：source 用尽后按阶段轮转补齐，优先选择尚未使用的 session；
    4. session / source 都尽量不重复，超出池子时允许复用（数据上确有限制）。
    """
    grouped: dict[str, list[dict]] = {stage: [] for stage in STAGE_ORDER}
    for row in frames_rows:
        stage = row.get("stage_hint", "")
        if stage in grouped:
            grouped[stage].append(row)
    for stage in grouped:
        grouped[stage].sort(key=lambda row: stable_key(row.get("image_id", "")))

    chosen: list[BenchmarkEntry] = []
    chosen_ids: set[str] = set()
    used_sessions: set[str] = set()
    used_sources: set[str] = set()

    def first_index(stage: str, predicate) -> int:
        for index, row in enumerate(grouped[stage]):
            if row.get("image_id") in chosen_ids:
                continue
            if predicate(row):
                return index
        return -1

    def take_at(stage: str, index: int, reason: str) -> bool:
        row = grouped[stage][index]
        chosen.append(_to_entry(row, mvp_dir, prefer_new=True, reason=reason))
        chosen_ids.add(row.get("image_id", ""))
        used_sessions.add(row.get("session_id", ""))
        used_sources.add(row.get("source_id", ""))
        return True

    # 轮次 A：每次尝试取一个未使用过的 source（每源只在这一轮出现一次）
    for _ in range(4):
        for stage in STAGE_ORDER:
            if len(chosen) >= count:
                break
            index = first_index(stage, lambda row: row.get("source_id") not in used_sources)
            if index >= 0:
                take_at(stage, index, "stage-robin-new-source")

    # 轮次 B：source 用尽后补齐，优先未使用的 session
    while len(chosen) < count:
        progressed = False
        for stage in STAGE_ORDER:
            if len(chosen) >= count:
                break
            index = first_index(stage, lambda row: row.get("session_id") not in used_sessions)
            if index < 0:
                index = first_index(stage, lambda row: True)
            if index >= 0:
                progressed = take_at(stage, index, "stage-robin-fill") or progressed
        if not progressed:
            break

    return chosen


def summarize_selection(entries: list[BenchmarkEntry]) -> dict:
    sessions = sorted({e.session_id for e in entries})
    sources = sorted({e.source_id for e in entries})
    stages: dict[str, int] = {}
    for entry in entries:
        stages[entry.stage_hint] = stages.get(entry.stage_hint, 0) + 1
    near_contact = sum(stages.get(stage, 0) for stage in NEAR_CONTACT_STAGES)
    missing_files = [e.image_id for e in entries if not e.image_path.is_file()]
    return {
        "count": len(entries),
        "sessions": len(sessions),
        "session_ids": sessions,
        "sources": len(sources),
        "source_ids": sources,
        "stages": stages,
        "near_contact_frames": near_contact,
        "missing_image_files": missing_files,
    }


def validate_selection(summary: dict) -> list[str]:
    problems: list[str] = []
    if summary["count"] != BNDSTT_BENCHMARK_SIZE:
        problems.append(f"expected {BNDSTT_BENCHMARK_SIZE} frames, got {summary['count']}")
    if summary["sessions"] < BNDSTT_MIN_SESSIONS:
        problems.append(f"sessions {summary['sessions']} < required {BNDSTT_MIN_SESSIONS}")
    if summary["sources"] < BNDSTT_MIN_SOURCES:
        problems.append(f"sources {summary['sources']} < required {BNDSTT_MIN_SOURCES}")
    if summary["near_contact_frames"] < BNDSTT_MIN_NEAR_CONTACT:
        problems.append(
            f"near-contact frames {summary['near_contact_frames']} < "
            f"required {BNDSTT_MIN_NEAR_CONTACT}"
        )
    if summary["missing_image_files"]:
        problems.append(f"missing image files: {summary['missing_image_files'][:5]}")
    return problems


def write_benchmark(
    entries: list[BenchmarkEntry],
    out_dir: Path | None = None,
    isolation: dict | None = None,
    force: bool = False,
) -> Path:
    out = Path(out_dir) if out_dir is not None else PATHS.benchmark_dir
    out.mkdir(parents=True, exist_ok=True)
    manifest = out / "benchmark_manifest.csv"
    if manifest.exists() and not force:
        raise BenchmarkError(
            f"benchmark manifest already exists (frozen): {manifest}. "
            "不要换图：所有模型必须用同一批 30 张。需要重建请显式 --force。"
        )
    rows = [entry.to_row() for entry in entries]
    columns = [
        "image_id", "image_path", "rel_image_path", "split", "session_id", "source_id",
        "stage_hint", "stage_label", "frame_index", "fraction", "source_video_path",
        "width", "height", "is_quick_test", "selection_reason",
    ]
    with open(manifest, "w", encoding="utf-8", newline="\n") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    summary = summarize_selection(entries)
    digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
    report = {
        "benchmark": BNDSTT_BENCHMARK_NAME,
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "seed": SEED,
        "stage_labels": STAGE_LABELS,
        "selection": summary,
        "quick_test_isolation": isolation or {},
        "manifest_sha256": digest,
        "image_ids": [entry.image_id for entry in entries],
    }
    (out / "benchmark_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _write_readme(out, summary, isolation or {}, digest)
    return manifest


def _write_readme(out: Path, summary: dict, isolation: dict, digest: str) -> None:
    lines = [
        f"# {BNDSTT_BENCHMARK_NAME}",
        "",
        "BNDSTT 域内固定 30 帧 benchmark。**冻结**：所有模型（YOLO / Pose / 后续版本）",
        "必须使用同一批 30 张，不得因为结果不好而换图。",
        "",
        f"- 图片数量：{summary['count']}",
        f"- 覆盖 session：{summary['sessions']}",
        f"- 覆盖 source video：{summary['sources']}",
        f"- 覆盖发球阶段：{len(summary['stages'])} / {len(STAGE_ORDER)}",
        f"- 近击球阶段帧数：{summary['near_contact_frames']}",
        f"- manifest SHA256：`{digest}`",
        f"- quick_test 隔离：{isolation.get('isolated', 'unknown')}"
        f"（quick_test sessions={isolation.get('quick_test_sessions', '?')}）",
        "",
        "## 阶段分布",
        "",
        "| stage_hint | 中文 | 帧数 |",
        "| --- | --- | --- |",
    ]
    for stage in STAGE_ORDER:
        lines.append(
            f"| `{stage}` | {STAGE_LABELS[stage]} | {summary['stages'].get(stage, 0)} |"
        )
    lines += [
        "",
        "## 重建方式",
        "",
        "```powershell",
        r".\.venv\c-detector\Scripts\python.exe vision\c_perception_v2\bndstt_benchmark.py build",
        "```",
        "",
        "默认拒绝覆盖已有 manifest（防止换图）。需要重建必须显式加 `--force`，",
        "但那会让历史结果不可比，除非有充分理由否则不要这么做。",
    ]
    (out / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_benchmark(force: bool = False, out_dir: Path | None = None) -> BenchmarkResult:
    frames, splits = load_candidates()
    isolation = check_quick_test_isolation(frames, splits)
    if not isolation["isolated"]:
        raise BenchmarkError(
            f"quick_test sessions leaked into benchmark candidates: {isolation['overlap']}"
        )
    entries = select_frames(frames, PATHS.bndstt_mvp_dir)
    summary = summarize_selection(entries)
    problems = validate_selection(summary)
    if problems:
        raise BenchmarkError("benchmark selection invalid: " + "; ".join(problems))
    manifest = write_benchmark(entries, out_dir, isolation=isolation, force=force)
    return BenchmarkResult(
        entries=entries,
        manifest=manifest,
        report={"selection": summary, "quick_test_isolation": isolation},
    )


def load_benchmark(manifest: Path | None = None) -> list[dict]:
    path = Path(manifest) if manifest is not None else PATHS.benchmark_manifest
    if not path.is_file():
        raise BenchmarkError(
            f"benchmark manifest not found: {path}. 先运行 bndstt_benchmark.py build"
        )
    return read_csv_rows(path)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=f"构建 {BNDSTT_BENCHMARK_NAME}")
    parser.add_argument("command", choices=["build", "verify"], nargs="?", default="build")
    parser.add_argument("--force", action="store_true", help="允许覆盖已有冻结 manifest")
    parser.add_argument("--out-dir", type=Path, default=None)
    args = parser.parse_args(argv)

    if args.command == "verify":
        rows = load_benchmark()
        entries = [
            BenchmarkEntry(
                image_id=row["image_id"],
                image_path=Path(row["image_path"]),
                split=row["split"],
                session_id=row["session_id"],
                source_id=row["source_id"],
                stage_hint=row["stage_hint"],
                frame_index=row["frame_index"],
                fraction=row["fraction"],
                source_video_path=row["source_video_path"],
                width=row["width"],
                height=row["height"],
            )
            for row in rows
        ]
        summary = summarize_selection(entries)
        problems = validate_selection(summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        if problems:
            print("VERIFY FAILED:", problems)
            return 1
        print("VERIFY PASS")
        return 0

    result = build_benchmark(force=args.force, out_dir=args.out_dir)
    for entry in result.entries:
        print(f"{entry.image_id:<58} {entry.stage_hint:<42} {entry.session_id}")
    print("-" * 100)
    print(json.dumps(result.report, ensure_ascii=False, indent=2))
    print(f"manifest: {result.manifest}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys

    sys.exit(main())
