r"""Stage 1-3 入口：获取 tableTennis v2 -> 审计 -> 转换 -> QA。

用法：

    .\.venv\c-detector\Scripts\python.exe vision\c_perception_v2\prepare_tabletennis_br.py --auto
    .\.venv\c-detector\Scripts\python.exe vision\c_perception_v2\prepare_tabletennis_br.py --audit-only

没有 API key 也没有 ZIP 时，输出 ``WAITING_FOR_TABLETENNIS_V2_ZIP`` 并给出精确人工步骤，
**不会**去找别的数据集，也**不会**假装成功。
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# 同时支持两种用法：作为包导入与直接运行脚本
import sys as _sys

if __package__ in (None, ""):
    _PACKAGE_DIR = str(Path(__file__).resolve().parent)
    _VISION_DIR = str(Path(__file__).resolve().parents[1])
    if _VISION_DIR not in _sys.path:
        _sys.path.insert(0, _VISION_DIR)
    if _PACKAGE_DIR not in _sys.path:
        _sys.path.insert(0, _PACKAGE_DIR)
    __package__ = "c_perception_v2"

from c_perception_v2.config import (  # noqa: E402
    PATHS,
    assert_gitignored,
    find_source_zip,
    mask_secret,
    roboflow_api_key,
)
from c_perception_v2.data_prep import (  # noqa: E402
    DataPrepError,
    WaitingForZip,
    assert_expected_v2,
    audit_raw_dataset,
    convert_to_ball_racket,
    ensure_raw_dataset,
    print_raw_audit,
    write_dataset_card,
    write_manifest_csv,
    write_source_md,
)


def _guard_git() -> None:
    """运行前自检：数据 / 标签 / QA 图必须被 Git 忽略。"""
    assert_gitignored(
        [PATHS.raw_dir, PATHS.br_dir, PATHS.qa_dir, PATHS.datasets_dir, PATHS.downloads_dir]
    )


def run(
    auto: bool = True,
    raw_data_yaml: Path | None = None,
    audit_only: bool = False,
    out_dir: Path | None = None,
    clean: bool = False,
    skip_expected_check: bool = False,
    make_qa: bool = True,
) -> dict:
    _guard_git()
    print("[env] repo_root        = " + str(PATHS.repo_root))
    print("[env] ROBOFLOW_API_KEY = " + mask_secret(roboflow_api_key()))
    zip_path = find_source_zip(PATHS.downloads_dir)
    print("[env] manual ZIP       = " + (str(zip_path) if zip_path else "<none in downloads/>"))
    print("[env] RAW dir          = " + str(PATHS.raw_dir))
    print("[env] BR dir           = " + str(PATHS.br_dir))

    if raw_data_yaml is not None:
        data_yaml = Path(raw_data_yaml)
    elif auto:
        data_yaml = ensure_raw_dataset(force=False)
    else:
        raise WaitingForZip("auto=False 且未指定 --raw-data-yaml")

    audit = audit_raw_dataset(data_yaml)
    print_raw_audit(audit)
    warnings: list[str] = []
    if not skip_expected_check:
        warnings = assert_expected_v2(audit)
        for warning in warnings:
            print("[WARN] " + warning)
        print("[check] raw size matches public v2 page (1480 images)")

    report: dict = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "data_yaml": str(data_yaml),
        "raw_audit": audit.to_dict(),
        "warnings": warnings,
    }
    PATHS.reports_dir.mkdir(parents=True, exist_ok=True)
    (PATHS.reports_dir / "tabletennis_raw_audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if audit_only:
        print("[audit-only] 跳过转换")
        return report

    stats = convert_to_ball_racket(data_yaml, out_dir, clean=clean)
    print("-" * 78)
    print("CONVERSION -> ball/racket 二分类（0 ball / 1 racket）")
    print("output   : " + str(stats.output_dir))
    print("data.yaml: " + str(stats.data_yaml))
    print("split  images    ball  racket  img_ball  img_racket  zero_tgt")
    for split in stats.splits:
        print(
            split.split.ljust(7)
            + str(split.images).rjust(7)
            + str(split.ball_instances).rjust(8)
            + str(split.racket_instances).rjust(8)
            + str(split.images_with_ball).rjust(10)
            + str(split.images_with_racket).rjust(12)
            + str(split.zero_target_images).rjust(10)
        )

    manifest = write_manifest_csv(stats, stats.output_dir / "manifest.csv")
    source_md = write_source_md(stats, audit, stats.output_dir / "SOURCE.md")
    card = write_dataset_card(stats, audit, stats.output_dir / "dataset_card.json")
    print("manifest : " + str(manifest))
    print("SOURCE.md: " + str(source_md))
    print("card     : " + str(card))

    if make_qa:
        from c_perception_v2.dataset_qa import build_dataset_qa, collect_ball_sizes

        qa_summary = build_dataset_qa(stats.output_dir, PATHS.qa_dir)
        print("-" * 78)
        print("QA contact sheets:")
        for split, entry in qa_summary.items():
            print("  " + str(split).ljust(6) + " " + json.dumps(entry, ensure_ascii=False))
        size_summary = collect_ball_sizes(stats.output_dir)
        print("ball bbox size distribution (public v2):")
        print(json.dumps(size_summary, ensure_ascii=False, indent=2))
        report["qa"] = qa_summary
        report["ball_size_distribution"] = size_summary
        (PATHS.reports_dir / "tabletennis_raw_audit.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    print("=" * 78)
    print("[PREP PASS] 数据已就绪，可以进入 GPU smoke test / 训练")
    return report


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="tableTennis v2 -> ball+racket 数据集")
    parser.add_argument(
        "--auto",
        action="store_true",
        default=True,
        help="自动发现 RAW / ZIP / API key（默认开启，显式写出便于记录命令）",
    )
    parser.add_argument("--raw-data-yaml", type=Path, default=None)
    parser.add_argument("--audit-only", action="store_true")
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--skip-expected-check", action="store_true")
    parser.add_argument("--no-qa", action="store_true")
    args = parser.parse_args(argv)

    try:
        run(
            auto=args.auto,
            raw_data_yaml=args.raw_data_yaml,
            audit_only=args.audit_only,
            out_dir=args.out_dir,
            clean=args.clean,
            skip_expected_check=args.skip_expected_check,
            make_qa=not args.no_qa,
        )
    except WaitingForZip as exc:
        print(exc)
        return 2
    except DataPrepError as exc:
        print("[FAIL] " + type(exc).__name__ + ": " + str(exc))
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
