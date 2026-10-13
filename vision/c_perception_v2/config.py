"""路径、常量与公开数据源元数据。

设计原则
--------
1. 全部路径从仓库根推导，不依赖当前工作目录。
2. ``dataset.yaml`` 的 ``path`` 必须写绝对路径（Ultralytics 的相对 path 会拼到
   它自己的全局 ``datasets_dir``，这是旧方案踩过的坑）。
3. 公开数据源信息集中在这里，便于写入 ``SOURCE.md`` 与比赛报告引用。
4. 任何图片 / 标签 / 权重 / 缓存都必须落在被 Git 忽略的目录里；本模块提供
   :func:`assert_gitignored` 在运行前自检。
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from datetime import date
from pathlib import Path

# ---------------------------------------------------------------- 公开数据源
ROBOFLOW_WORKSPACE = "yolo-class-delww"
ROBOFLOW_PROJECT = "tabletennis-nbcdc"
ROBOFLOW_VERSION = 2
ROBOFLOW_AUTHOR = "yolo class"
ROBOFLOW_LICENSE = "CC BY 4.0"
ROBOFLOW_UNIVERSE_URL = (
    "https://universe.roboflow.com/yolo-class-delww/tabletennis-nbcdc"
)
ROBOFLOW_DATASET_URL = (
    "https://universe.roboflow.com/yolo-class-delww/tabletennis-nbcdc/dataset/2"
)
ROBOFLOW_DOWNLOAD_URL = (
    "https://universe.roboflow.com/yolo-class-delww/tabletennis-nbcdc/dataset/2/download/yolov8"
)
ROBOFLOW_MODEL_ID = "tabletennis-nbcdc/2"
ROBOFLOW_FORMAT = "yolov8"

# v2 公开页面公布的固定统计（用于下载后一致性断言，不是我们的模型指标）
EXPECTED_V2_SPLITS = {"train": 1036, "valid": 291, "test": 153}
EXPECTED_V2_TOTAL = 1480
EXPECTED_V2_CLASSES = (
    "ball",
    "table",
    "player",
    "net",
    "racket",
    "scoreboard",
    "umpire",
)

# 人工 fallback：用户把 ZIP 放到 downloads/ 后，程序自动接手
DOWNLOAD_ZIP_BASENAMES = (
    "tabletennis_nbcdc_v2_yolov8.zip",
    "tabletennis-nbcdc.v2-yolov8.zip",
    "tabletennis_nbcdc_v2.zip",
)

WAITING_FOR_ZIP_TOKEN = "WAITING_FOR_TABLETENNIS_V2_ZIP"

# ---------------------------------------------------------------- 数据集布局
RAW_DIRNAME = "tabletennis_nbcdc_v2_raw"
BR_DIRNAME = "tabletennis_ball_racket_v1"

BALL_RACKET_NAMES = {0: "ball", 1: "racket"}

# 训练 / 评估默认参数（本轮固定，不做超参搜索）
TRAIN_IMGSZ = 640
TRAIN_EPOCHS = 120
TRAIN_PATIENCE = 25
TRAIN_SEED = 42
TRAIN_WORKERS = 4
TRAIN_BATCH_CANDIDATES = (16, 8, 4)

MODEL_NAME_TAG = "ball_racket_yolov8n_v1"
BASE_WEIGHTS_NAME = "yolov8n.pt"
POSE_WEIGHTS_NAME = "yolov8n-pose.pt"

# BNDSTT 域内固定 benchmark
BNDSTT_BENCHMARK_NAME = "BNDSTT_30_V1"
BNDSTT_BENCHMARK_SIZE = 30
BNDSTT_MIN_SESSIONS = 8
BNDSTT_MIN_SOURCES = 12
BNDSTT_MIN_NEAR_CONTACT = 3

INFER_IMGSZ = 640
INFER_CONF_REPORT = 0.15
INFER_CONF_DISPLAY = 0.25
INFER_IOU = 0.70
WRIST_CONF_MIN = 0.30


# ---------------------------------------------------------------- 仓库定位
def find_repo_root(start: Path | None = None) -> Path:
    """向上查找含 ``AGENTS.md`` 与 ``vision`` 的仓库根。"""
    here = Path(start) if start is not None else Path(__file__).resolve()
    for candidate in [here, *here.parents]:
        if (candidate / "AGENTS.md").is_file() and (candidate / "vision").is_dir():
            return candidate
    raise RuntimeError(f"cannot locate repo root from {here}")


@dataclass(frozen=True)
class Paths:
    """仓库内所有与本方案相关的绝对路径。"""

    repo_root: Path

    # --- 输入 -------------------------------------------------------------
    @property
    def downloads_dir(self) -> Path:
        return self.repo_root / "artifacts" / "files" / "datasets" / "downloads"

    @property
    def datasets_dir(self) -> Path:
        return self.repo_root / "artifacts" / "files" / "datasets"

    @property
    def raw_dir(self) -> Path:
        return self.datasets_dir / RAW_DIRNAME

    @property
    def br_dir(self) -> Path:
        return self.datasets_dir / BR_DIRNAME

    @property
    def br_data_yaml(self) -> Path:
        return self.br_dir / "data.yaml"

    @property
    def bndstt_mvp_dir(self) -> Path:
        return self.datasets_dir / "BNDSTT_MVP_v1"

    @property
    def bndstt_frames_manifest(self) -> Path:
        return self.bndstt_mvp_dir / "frames_manifest.csv"

    @property
    def bndstt_manual_gt_dir(self) -> Path:
        """只读引用（domain test images），本轮绝不写入、绝不用于训练。"""
        return self.datasets_dir / "BNDSTT_MANUAL_GT_V1"

    # --- 权重 -------------------------------------------------------------
    @property
    def weights_dir(self) -> Path:
        return self.repo_root / "artifacts" / "files" / "models"

    @property
    def base_weights_path(self) -> Path:
        """yolov8n.pt：优先 artifacts 副本，其次仓库根，最后交给 Ultralytics 下载。"""
        for candidate in (
            self.weights_dir / "ultralytics" / BASE_WEIGHTS_NAME,
            self.repo_root / BASE_WEIGHTS_NAME,
        ):
            if candidate.is_file():
                return candidate
        return Path(BASE_WEIGHTS_NAME)

    @property
    def pose_weights_path(self) -> Path:
        for candidate in (
            self.weights_dir / "ultralytics" / POSE_WEIGHTS_NAME,
            self.repo_root / POSE_WEIGHTS_NAME,
        ):
            if candidate.is_file():
                return candidate
        return Path(POSE_WEIGHTS_NAME)

    # --- 输出 -------------------------------------------------------------
    @property
    def project_dir(self) -> Path:
        return self.repo_root / "artifacts" / "runs" / MODEL_NAME_TAG

    @property
    def model_out_dir(self) -> Path:
        return self.repo_root / "artifacts" / "files" / "models" / MODEL_NAME_TAG

    @property
    def reports_dir(self) -> Path:
        return self.repo_root / "artifacts" / "files" / "reports"

    @property
    def qa_dir(self) -> Path:
        return self.reports_dir / "tabletennis_br_dataset_qa"

    @property
    def failures_dir(self) -> Path:
        return self.reports_dir / "test_ball_failures"

    @property
    def benchmark_dir(self) -> Path:
        return self.repo_root / "artifacts" / "files" / "benchmarks" / BNDSTT_BENCHMARK_NAME

    @property
    def benchmark_manifest(self) -> Path:
        return self.benchmark_dir / "benchmark_manifest.csv"

    @property
    def fusion_dir(self) -> Path:
        return self.reports_dir / "BNDSTT_30_FUSION_V1"

    @property
    def latency_dir(self) -> Path:
        return self.reports_dir / "latency_bench"


PATHS = Paths(repo_root=find_repo_root())


def roboflow_api_key() -> str | None:
    """只从环境变量 ``ROBOFLOW_API_KEY`` 读取，绝不落盘、绝不打印。"""
    value = os.environ.get("ROBOFLOW_API_KEY", "").strip()
    return value or None


def mask_secret(value: str | None) -> str:
    """给日志用的掩码：永不回显任何 key 内容。"""
    if not value:
        return "<unset>"
    return f"<set,len={len(value)}>"


def find_source_zip(downloads_dir: Path | None = None) -> Path | None:
    """在 downloads/ 中定位待用 ZIP。

    先按约定文件名匹配，再退化为“任意包含 tabletennis 的 .zip”，按修改时间取最新。
    找不到返回 ``None``，调用方据此输出 ``WAITING_FOR_TABLETENNIS_V2_ZIP``。
    """
    root = Path(downloads_dir) if downloads_dir is not None else PATHS.downloads_dir
    if not root.is_dir():
        return None
    for name in DOWNLOAD_ZIP_BASENAMES:
        candidate = root / name
        if candidate.is_file() and candidate.stat().st_size > 0:
            return candidate
    loose = sorted(
        (p for p in root.glob("*.zip") if "tabletennis" in p.name.lower()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for candidate in loose:
        if candidate.stat().st_size > 0:
            return candidate
    return None


# ---------------------------------------------------------------- Git 安全
def is_gitignored(path: Path, repo_root: Path | None = None) -> bool:
    """用 ``git check-ignore`` 判定路径是否被忽略（不依赖 .gitignore 文本解析）。"""
    root = Path(repo_root) if repo_root is not None else PATHS.repo_root
    try:
        target = Path(path).resolve()
    except OSError:  # pragma: no cover - 极端路径
        return False
    proc = subprocess.run(
        ["git", "check-ignore", "-q", "--", str(target)],
        cwd=str(root),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if proc.returncode == 0:
        return True
    # 目录不存在或为空时 git 仍应能判定；返回 1 表示未被忽略。
    # 兜底：git 不可用时用文本规则近似判断，避免误判为“安全”。
    if proc.returncode not in (0, 1):
        return False
    return False


def assert_gitignored(paths: list[Path], repo_root: Path | None = None) -> None:
    """运行前自检：这些目录必须被 Git 忽略，否则直接抛错。"""
    leaks = [p for p in paths if not is_gitignored(p, repo_root)]
    if leaks:
        joined = ", ".join(str(p) for p in leaks)
        raise RuntimeError(
            f"these paths are NOT git-ignored: {joined}. "
            "Images/labels/weights/caches must never be committable."
        )


def download_date() -> str:
    """SOURCE.md 记录用日期（ISO）。"""
    return date.today().isoformat()
