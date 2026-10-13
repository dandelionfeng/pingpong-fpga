"""fine-tune 对比评估：baseline vs A(BNDSTT-only) vs B(mixed replay)。

对每个模型在三处同时评估（方案第 12/13 条）：
1. ``BNDSTT_30_V1`` 固定 benchmark（ball/racket/both 帧级检出）；
2. fine-tune 的域内 val（只对 A/B 有意义，baseline 也一并测）；
3. 公开 test split + duplicate-excluded 公开 test（第 16 条）。

并输出：
* 三套 contact sheet（每个模型一套，含 ball/racket/both 视图）；
* 最佳模型的 conf 阈值扫描（第 15 条）。

**不修改** frozen benchmark，**不使用** quick_test。
"""

from __future__ import annotations

import json
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
from .config import INFER_IMGSZ, PATHS
from .dataset_qa import contact_sheet, read_image_robust, write_image_robust
from .finetune_domain import (
    VAL_SIZE,
    baseline_weights,
    finetune_dir,
    model_dir,
    read_csv_rows,
)
from .finetune_eval import (
    CONF_GRID,
    DEFAULT_CONF,
    bndstt_frame_metrics,
    build_duplicate_excluded_test,
    predict_boxes,
    public_test_metrics,
    review_out_of_bounds,
    scan_conf_thresholds,
)
from .yolo_io import (
    COLOR_BALL,
    COLOR_RACKET,
    draw_box,
    draw_label,
    draw_legend,
)

REPORT_DIRNAME = "FINETUNE_COMPARE_V1"
TARGETS = {"ball_frames_min": 24, "racket_frames_min": 26, "both_frames_min": 22}


def report_dir() -> Path:
    return PATHS.reports_dir / REPORT_DIRNAME


def model_candidates() -> dict[str, Path]:
    """三个待比较模型：baseline 与两个 fine-tune 变体。"""
    candidates = {"baseline_v1": baseline_weights()}
    for variant in ("a_bndstt_only", "b_mixed_replay"):
        candidates[variant] = model_dir("ball_racket_yolov8n_v2_domain_" + variant) / "best.pt"
    return candidates


def render_panels(weights: Path, conf: float, limit: int | None = None) -> list:
    """在 BNDSTT_30 上生成 ball+racket 叠加面板（用于三套 contact sheet）。"""
    from ultralytics import YOLO

    rows = read_csv_rows(PATHS.benchmark_manifest)
    if limit:
        rows = rows[:limit]
    model = YOLO(str(weights))
    panels = []
    for index, row in enumerate(rows, start=1):
        image = read_image_robust(Path(row["image_path"]))
        if image is None:
            continue
        boxes = predict_boxes(model, image, conf=conf, imgsz=INFER_IMGSZ, device=0)
        balls = [b for b in boxes if b.class_id == 0]
        rackets = [b for b in boxes if b.class_id == 1]
        canvas = image.copy()
        for box in balls:
            draw_box(canvas, box, label="ball " + format(box.confidence, ".2f"),
                     color=COLOR_BALL, thickness=2)
        for box in rackets:
            draw_box(canvas, box, label="racket " + format(box.confidence, ".2f"),
                     color=COLOR_RACKET, thickness=2)
        draw_legend(canvas, [
            ("ball x" + str(len(balls)), COLOR_BALL),
            ("racket x" + str(len(rackets)), COLOR_RACKET),
        ])
        draw_label(canvas, "#" + str(index) + " " + row["image_id"][-30:],
                   (8, canvas.shape[0] - 26), (40, 40, 40), scale=0.5)
        panels.append(canvas)
    return panels


def evaluate_model(name: str, weights: Path, conf: float = DEFAULT_CONF,
                   domain_val_yaml: Path | None = None) -> dict:
    """单个模型的三处评估（不含 contact sheet）。"""
    import cv2

    result: dict = {"name": name, "weights": str(weights), "exists": weights.is_file()}
    if not weights.is_file():
        result["note"] = "weights missing"
        return result

    result["bndstt30"] = bndstt_frame_metrics(weights, conf=conf, imgsz=INFER_IMGSZ, device=0)
    result["bndstt30"].pop("per_frame", None)

    try:
        result["public_test"] = {
            key: value for key, value in public_test_metrics(weights).items()
            if key in ("overall", "per_class", "speed_ms_per_image")
        }
    except Exception as exc:  # noqa: BLE001
        result["public_test_error"] = type(exc).__name__ + ": " + str(exc)

    if domain_val_yaml is not None and domain_val_yaml.is_file():
        try:
            result["domain_val"] = {
                key: value for key, value in
                public_test_metrics(weights, data_yaml=domain_val_yaml, split="val").items()
                if key in ("overall", "per_class")
            }
        except Exception as exc:  # noqa: BLE001
            result["domain_val_error"] = type(exc).__name__ + ": " + str(exc)

    # contact sheet 三套（BNDSTT_30）
    panels = render_panels(weights, conf)
    if panels:
        out = report_dir()
        out.mkdir(parents=True, exist_ok=True)
        target = out / ("bndstt30_" + name + ".jpg")
        ok = write_image_robust(target, contact_sheet(panels, columns=6))
        result["contact_sheet"] = str(target) if ok else None
        result["contact_sheet_ok"] = bool(ok)
    _ = cv2
    return result


def gate_check(best: dict) -> dict:
    """门槛判定（第 14 条）。"""
    m = best.get("bndstt30", {})
    ball = m.get("ball_detected_frames", 0)
    racket = m.get("racket_detected_frames", 0)
    both = m.get("both_detected_frames", 0)
    return {
        "ball": {"value": ball, "target": TARGETS["ball_frames_min"],
                 "pass": ball >= TARGETS["ball_frames_min"]},
        "racket": {"value": racket, "target": TARGETS["racket_frames_min"],
                   "pass": racket >= TARGETS["racket_frames_min"]},
        "both": {"value": both, "target": TARGETS["both_frames_min"],
                 "pass": both >= TARGETS["both_frames_min"]},
        "all_pass": (ball >= TARGETS["ball_frames_min"]
                     and racket >= TARGETS["racket_frames_min"]
                     and both >= TARGETS["both_frames_min"]),
    }


def run_comparison(conf: float = DEFAULT_CONF, scan: bool = True) -> dict:
    domain_yaml = finetune_dir() / "replay_0" / "data.yaml"
    if not domain_yaml.is_file():
        domain_yaml = finetune_dir() / "data.yaml"

    models = model_candidates()
    results = [evaluate_model(name, weights, conf=conf, domain_val_yaml=domain_yaml)
               for name, weights in models.items()]

    # duplicate-excluded 公开 test（第 16 条）
    dup_excluded = build_duplicate_excluded_test()
    if dup_excluded.get("data_yaml"):
        for entry in results:
            if not entry.get("exists"):
                continue
            from pathlib import Path as _Path

            try:
                dedup = public_test_metrics(_Path(entry["weights"]),
                                            data_yaml=_Path(dup_excluded["data_yaml"]))
                entry["public_test_duplicate_excluded"] = {
                    key: value for key, value in dedup.items()
                    if key in ("overall", "per_class")
                }
            except Exception as exc:  # noqa: BLE001
                entry["public_test_duplicate_excluded_error"] = (
                    type(exc).__name__ + ": " + str(exc)
                )

    # 最佳模型：优先 fine-tune 变体中 both 帧数最高者，否则 baseline
    finetuned = [e for e in results if e["name"] != "baseline_v1" and e.get("exists")]
    pool = finetuned if finetuned else results
    best = max(pool, key=lambda e: (
        e.get("bndstt30", {}).get("both_detected_frames", 0),
        e.get("bndstt30", {}).get("ball_detected_frames", 0),
    ))

    scan_result = None
    if scan and best.get("exists"):
        scan_result = scan_conf_thresholds(best["weights"], confs=CONF_GRID)

    oob = review_out_of_bounds()

    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "conf": conf,
        "targets": TARGETS,
        "results": results,
        "best_model": {"name": best["name"], "weights": best["weights"]},
        "gate": gate_check(best),
        "threshold_scan": scan_result,
        "duplicate_excluded": {k: v for k, v in dup_excluded.items() if k != "excluded_rows"},
        "out_of_bounds_review": {k: v for k, v in oob.items() if k != "records"},
        "domain_val_size": VAL_SIZE,
    }
    out = report_dir()
    out.mkdir(parents=True, exist_ok=True)
    (out / "comparison.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _write_markdown(report, out / "comparison.md")
    return report


def _fmt(value, digits: int = 4) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return format(value, "." + str(digits) + "f")
    return str(value)


def _write_markdown(report: dict, path: Path) -> None:
    lines = [
        "# BNDSTT DOMAIN FINE-TUNE V1 对比",
        "",
        "生成时间：" + report["generated_at_utc"],
        "评估 conf：" + str(report["conf"]),
        "",
        "## BNDSTT_30_V1（帧级检出，/30）",
        "",
        "| model | ball | racket | both | ball recall | racket recall |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for entry in report["results"]:
        m = entry.get("bndstt30") or {}
        lines.append(
            "| " + entry["name"] + " | " + str(m.get("ball_detected_frames", "n/a"))
            + " | " + str(m.get("racket_detected_frames", "n/a"))
            + " | " + str(m.get("both_detected_frames", "n/a"))
            + " | " + _fmt(m.get("ball_frame_recall"))
            + " | " + _fmt(m.get("racket_frame_recall")) + " |"
        )
    lines += ["", "## 公开 test（原始 / duplicate-excluded）", "",
              "| model | P | R | mAP50 | mAP50-95 | ball AP50 | racket AP50 | dup-excl mAP50 |",
              "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for entry in report["results"]:
        pub = entry.get("public_test") or {}
        overall = pub.get("overall") or {}
        per = pub.get("per_class") or {}
        dedup = ((entry.get("public_test_duplicate_excluded") or {}).get("overall") or {})
        lines.append(
            "| " + entry["name"]
            + " | " + _fmt(overall.get("precision"))
            + " | " + _fmt(overall.get("recall"))
            + " | " + _fmt(overall.get("map50"))
            + " | " + _fmt(overall.get("map50_95"))
            + " | " + _fmt((per.get("ball") or {}).get("ap50"))
            + " | " + _fmt((per.get("racket") or {}).get("ap50"))
            + " | " + _fmt(dedup.get("map50")) + " |"
        )
    gate = report["gate"]
    lines += ["", "## 门槛判定", "",
              "| 项 | 实测 | 目标 | 是否达标 |", "| --- | --- | --- | --- |"]
    for key in ("ball", "racket", "both"):
        g = gate[key]
        lines.append("| " + key + " | " + str(g["value"]) + " | " + str(g["target"])
                     + " | " + ("YES" if g["pass"] else "NO") + " |")
    lines += ["", "**all_pass: " + ("YES" if gate["all_pass"] else "NO") + "**", ""]
    scan = report.get("threshold_scan")
    if scan:
        lines += ["## 阈值扫描（最佳模型）", "",
                  "| conf | ball /30 | racket /30 | both /30 | ball 多余框 | racket 多余框 |",
                  "| --- | --- | --- | --- | --- | --- |"]
        for row in scan["table"]:
            lines.append(
                "| " + format(row["conf"], ".2f")
                + " | " + str(row["ball_frames"]) + " | " + str(row["racket_frames"])
                + " | " + str(row["both_frames"]) + " | " + str(row["ball_extra_boxes"])
                + " | " + str(row["racket_extra_boxes"]) + " |"
            )
        lines += ["", "推荐 conf：" + str(scan["recommended_conf"]), ""]
    oob = report.get("out_of_bounds_review") or {}
    if oob.get("available"):
        lines += ["## out-of-bounds 复核", "",
                  "- 轻微越界建议 clip：" + str(oob["clipped"]),
                  "- 明显错误建议 drop：" + str(oob["dropped"]),
                  "- 明细 CSV：" + str(oob["csv"]), ""]
    path.write_text(chr(10).join(lines) + chr(10), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="fine-tune 三模型三处对比")
    parser.add_argument("--conf", type=float, default=DEFAULT_CONF)
    parser.add_argument("--no-scan", action="store_true")
    args = parser.parse_args(argv)
    report = run_comparison(conf=args.conf, scan=not args.no_scan)
    printable = {
        "best_model": report["best_model"],
        "gate": report["gate"],
        "results": [
            {
                "name": e["name"],
                "exists": e.get("exists"),
                "bndstt30": {
                    k: (e.get("bndstt30") or {}).get(k)
                    for k in ("ball_detected_frames", "racket_detected_frames", "both_detected_frames")
                },
            }
            for e in report["results"]
        ],
    }
    print(json.dumps(printable, ensure_ascii=False, indent=2))
    print("report: " + str(report_dir() / "comparison.md"))
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys

    sys.exit(main())
