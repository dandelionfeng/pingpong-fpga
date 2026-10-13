"""fusion_demo 入口：联合可视化（AE/AF）。

实现集中在 :mod:`vision.c_perception_v2.fusion`（判定 + 可视化同一模块），本文件只做
别名导出，保证方案要求的两个模块名都可用：``fusion`` 与 ``fusion_demo``。
"""

from __future__ import annotations

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
from .fusion import (  # noqa: F401
    DECISION_ASSOCIATED,
    DECISION_UNKNOWN,
    FrameResult,
    main as _main,
    render_ball_racket_panel,
    render_fusion_panel,
    render_pose_panel,
    run_fusion_demo,
    summarize_frames,
)


def main(argv: list[str] | None = None) -> int:
    """转调 :func:`vision.c_perception_v2.fusion.main`。"""
    return _main(argv)


__all__ = [
    "DECISION_ASSOCIATED",
    "DECISION_UNKNOWN",
    "FrameResult",
    "main",
    "render_ball_racket_panel",
    "render_fusion_panel",
    "render_pose_panel",
    "run_fusion_demo",
    "summarize_frames",
]


if __name__ == "__main__":  # pragma: no cover
    import sys

    sys.exit(main())
