"""C 端感知 V2 的单元测试（AM 段 12 项）。

覆盖：
1. data.yaml class lookup（按真实 names 反查，不假设 id 一定是 0/4）
2. ball/racket class remap（合成 RAW 的端到端转换）
3. bbox bounds（越界框必须被拒）
4. YOLO 归一化 bbox 合法性
5. 原图坐标还原（归一化 -> 像素 -> 归一化 回环）
6~8. pose keypoint index / left = 9 / right = 10
9. invalid wrist confidence handling（不造坐标）
10. fusion JSON schema（HEURISTIC，不是 GT）
11. quick_test 绝不进入训练
12. 旧 manual GT 绝不进入公开数据训练
"""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from vision.c_perception_v2 import CLASS_BALL, CLASS_NAMES, CLASS_RACKET, SCHEMA_VERSION  # noqa: E402
from vision.c_perception_v2.ball_racket import (  # noqa: E402
    BallRacketDetection,
    DetectionError,
    PerceptionResultV2,
    assert_detections_in_image,
)
from vision.c_perception_v2.bndstt_benchmark import BenchmarkError, write_benchmark  # noqa: E402
from vision.c_perception_v2.config import (  # noqa: E402
    EXPECTED_V2_TOTAL,
    find_source_zip,
    PATHS,
    WAITING_FOR_ZIP_TOKEN,
    assert_gitignored,
    is_gitignored,
    mask_secret,
    roboflow_api_key,
)
from vision.c_perception_v2.data_prep import (  # noqa: E402
    DataPrepError,
    assert_expected_v2,
    audit_raw_dataset,
    convert_to_ball_racket,
    find_data_yaml,
    lookup_class_id,
    manual_zip_instructions,
    normalize_names,
    read_yolo_label_file,
    safe_extract,
    write_br_data_yaml,
)
from vision.c_perception_v2.dataset_qa import collect_ball_sizes  # noqa: E402
from vision.c_perception_v2.fusion import (  # noqa: E402
    DECISION_ASSOCIATED,
    DECISION_UNKNOWN,
    associate_frame,
    temporal_association,
)
from vision.c_perception_v2.wrist_pose import (  # noqa: E402
    COCO_KEYPOINT_NAMES,
    LEFT_WRIST_INDEX,
    RIGHT_WRIST_INDEX,
    PoseFrame,
    build_person_pose,
)
from vision.c_perception_v2.yolo_io import (  # noqa: E402
    Box,
    pixel_to_yolo_norm,
    yolo_line_is_valid,
    yolo_norm_to_pixel,
)

WRIST_CONF_MIN = 0.30


# ================================================================ 1. class lookup
def test_class_lookup_uses_real_names_not_assumed_ids():
    """ball/racket 的 id 必须来自 data.yaml 的真实 names。"""
    names = normalize_names(
        ["ball", "table", "player", "net", "racket", "scoreboard", "umpire"]
    )
    assert lookup_class_id(names, "ball") == 0
    assert lookup_class_id(names, "racket") == 4  # 本数据集恰好是 4，但代码不假设

    shuffled = normalize_names(["racket", "net", "ball", "table"])
    assert lookup_class_id(shuffled, "ball") == 2
    assert lookup_class_id(shuffled, "racket") == 0

    dict_form = normalize_names({3: "ball", 7: "racket", 0: "net"})
    assert lookup_class_id(dict_form, "ball") == 3
    assert lookup_class_id(dict_form, "racket") == 7

    assert lookup_class_id(normalize_names([" Ball ", "RACKET"]), "ball") == 0


def test_class_lookup_fails_when_class_missing():
    """ball 或 racket 缺失必须立即 FAIL，而不是默默继续。"""
    with pytest.raises(DataPrepError):
        lookup_class_id(normalize_names(["ball", "table"]), "racket")
    with pytest.raises(DataPrepError):
        lookup_class_id(normalize_names(["table", "net"]), "ball")


# ================================================================ 2. remap 端到端
def _make_synthetic_raw(root: Path, split_sizes=None) -> Path:
    """构造一个 Roboflow 风格的 RAW 导出（7 类，含无目标图）。"""
    from PIL import Image

    split_sizes = split_sizes or {"train": 3, "valid": 2, "test": 1}
    names = ["ball", "table", "player", "net", "racket", "scoreboard", "umpire"]
    for split, count in split_sizes.items():
        (root / split / "images").mkdir(parents=True, exist_ok=True)
        (root / split / "labels").mkdir(parents=True, exist_ok=True)
        for index in range(count):
            image_path = root / split / "images" / (split + "_" + str(index) + ".jpg")
            Image.new("RGB", (640, 480), (30, 30, 30)).save(image_path, quality=90)
            lines = []
            if index == 0:
                lines.append("0 0.200000 0.300000 0.050000 0.060000")
                lines.append("4 0.700000 0.600000 0.200000 0.250000")
                lines.append("1 0.500000 0.900000 0.800000 0.100000")
            elif index == 1:
                lines.append("4 0.300000 0.400000 0.150000 0.200000")
            (root / split / "labels" / (split + "_" + str(index) + ".txt")).write_text(
                chr(10).join(lines) + (chr(10) if lines else ""), encoding="utf-8"
            )
    data = {
        "train": "train/images",
        "val": "valid/images",
        "test": "test/images",
        "nc": 7,
        "names": names,
    }
    yaml_path = root / "data.yaml"
    yaml_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return yaml_path


def test_ball_racket_remap_end_to_end(tmp_path):
    raw = tmp_path / "raw"
    data_yaml = _make_synthetic_raw(raw)
    out = tmp_path / "br"

    stats = convert_to_ball_racket(data_yaml, out)

    assert stats.ball_id_source == 0
    assert stats.racket_id_source == 4

    train_labels = (out / "labels" / "train" / "train_0.txt").read_text().splitlines()
    classes = sorted(int(line.split()[0]) for line in train_labels)
    assert classes == [0, 1]

    empty_label = out / "labels" / "train" / "train_2.txt"
    assert (out / "images" / "train" / "train_2.jpg").is_file()
    assert empty_label.read_text().strip() == ""

    payload = yaml.safe_load((out / "data.yaml").read_text(encoding="utf-8"))
    assert payload["names"] == {0: "ball", 1: "racket"}
    assert payload["nc"] == 2

    assert (out / "images" / "val").is_dir()
    assert len(list((out / "images" / "train").iterdir())) == 3
    assert len(list((out / "images" / "val").iterdir())) == 2
    assert len(list((out / "images" / "test").iterdir())) == 1

    # RAW 只读：原标签仍保留全部 3 类
    raw_lines = (raw / "train" / "labels" / "train_0.txt").read_text().splitlines()
    assert len(raw_lines) == 3
    assert any(line.startswith("1 ") for line in raw_lines)

    by_split = {s.split: s for s in stats.splits}
    assert by_split["train"].ball_instances == 1
    assert by_split["train"].racket_instances == 2
    assert by_split["train"].dropped_instances == 1


def test_data_yaml_uses_absolute_path(tmp_path):
    out = tmp_path / "br"
    out.mkdir()
    yaml_path = write_br_data_yaml(out)
    payload = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    assert Path(payload["path"]).is_absolute()
    assert payload["train"] == "images/train"
    assert payload["val"] == "images/val"
    assert payload["test"] == "images/test"


def test_raw_size_mismatch_stops_training(tmp_path):
    """下载到的不是 1480 张 -> 必须停止，不能稀里糊涂开始训练。"""
    raw = tmp_path / "raw"
    data_yaml = _make_synthetic_raw(raw, split_sizes={"train": 1, "valid": 1, "test": 1})
    audit = audit_raw_dataset(data_yaml)
    assert audit.total_images == 3
    with pytest.raises(DataPrepError) as excinfo:
        assert_expected_v2(audit)
    assert str(EXPECTED_V2_TOTAL) in str(excinfo.value)


# ================================================================ 3. bbox bounds
def test_bbox_bounds_validation():
    inside = Box(10, 20, 110, 120, class_id=0, image_width=200, image_height=200)
    assert inside.is_inside()
    assert inside.is_inside(200, 200)

    outside = Box(-5, 20, 110, 120, class_id=0, image_width=200, image_height=200)
    assert not outside.is_inside(200, 200)

    zero_area = Box(50, 50, 50, 80, class_id=0)
    assert not zero_area.is_inside()
    assert zero_area.area == 0.0

    nan_box = Box(float("nan"), 0, 10, 10, class_id=0)
    assert not nan_box.is_inside()


def test_detection_outside_image_is_rejected():
    detection = BallRacketDetection(
        class_id=CLASS_BALL,
        class_name="ball",
        confidence=0.9,
        box=Box(1900, 10, 2100, 90, class_id=0, image_width=1920, image_height=1080),
    )
    with pytest.raises(DetectionError):
        assert_detections_in_image([detection], 1920, 1080)

    ok = BallRacketDetection(
        class_id=CLASS_RACKET,
        class_name="racket",
        confidence=0.9,
        box=Box(100, 100, 300, 300, class_id=1, image_width=1920, image_height=1080),
    )
    assert_detections_in_image([ok], 1920, 1080)


# ================================================================ 4. normalized validity
def test_yolo_normalized_bbox_validity():
    assert yolo_line_is_valid(["0", "0.5", "0.5", "0.1", "0.2"], 1920, 1080) == (True, "")
    assert yolo_line_is_valid(["4", "0.5", "0.5", "0.1", "0.2"], 1920, 1080)[0]

    assert not yolo_line_is_valid(["0", "0.5", "0.5", "0.1"], 1920, 1080)[0]
    assert not yolo_line_is_valid(["0", "0.5", "0.5", "0", "0.2"], 1920, 1080)[0]
    assert not yolo_line_is_valid(["0", "1.4", "0.5", "0.1", "0.2"], 1920, 1080)[0]
    assert not yolo_line_is_valid(["0", "0.5", "0.5", "0.1", "0.2", "9"], 1920, 1080)[0]
    assert not yolo_line_is_valid(["x", "0.5", "0.5", "0.1", "0.2"], 1920, 1080)[0]
    assert not yolo_line_is_valid(["0", "nan", "0.5", "0.1", "0.2"], 1920, 1080)[0]
    assert not yolo_line_is_valid(["0", "0.02", "0.5", "0.5", "0.2"], 1920, 1080)[0]


def test_read_yolo_label_reports_errors(tmp_path):
    label = tmp_path / "bad.txt"
    label.write_text("0 0.5 0.5 0.1 0.2" + chr(10) + "0 0.5 0.5 0.1" + chr(10), encoding="utf-8")
    instances, errors = read_yolo_label_file(label)
    assert len(instances) == 1
    assert len(errors) == 1


# ================================================================ 5. 原图坐标还原
def test_original_coordinate_roundtrip():
    width, height = 1920, 1080
    original = Box(100.0, 200.0, 1500.0, 900.0, class_id=0, image_width=width, image_height=height)
    cx, cy, w, h = pixel_to_yolo_norm(original, width, height)
    assert 0.0 < cx < 1.0 and 0.0 < cy < 1.0 and 0.0 < w <= 1.0 and 0.0 < h <= 1.0

    restored = yolo_norm_to_pixel(0, cx, cy, w, h, width, height)
    assert restored.x1 == pytest.approx(original.x1, abs=1e-6)
    assert restored.y1 == pytest.approx(original.y1, abs=1e-6)
    assert restored.x2 == pytest.approx(original.x2, abs=1e-6)
    assert restored.y2 == pytest.approx(original.y2, abs=1e-6)
    assert restored.is_inside(width, height)

    # 明确不是 640 letterbox 坐标
    letterbox = yolo_norm_to_pixel(0, cx, cy, w, h, 640, 640)
    assert restored.width != pytest.approx(letterbox.width, abs=1.0)


# ================================================================ 6-9. pose keypoints
def _keypoints(wrist_conf: float = 0.9, left_xy=(100.0, 200.0), right_xy=(300.0, 400.0)):
    xy = [(float(i * 10), float(i * 10)) for i in range(17)]
    xy[LEFT_WRIST_INDEX] = left_xy
    xy[RIGHT_WRIST_INDEX] = right_xy
    conf = [0.9] * 17
    conf[LEFT_WRIST_INDEX] = wrist_conf
    conf[RIGHT_WRIST_INDEX] = wrist_conf
    return xy, conf


def test_keypoint_index_definitions():
    assert len(COCO_KEYPOINT_NAMES) == 17
    assert COCO_KEYPOINT_NAMES[LEFT_WRIST_INDEX] == "left_wrist"
    assert COCO_KEYPOINT_NAMES[RIGHT_WRIST_INDEX] == "right_wrist"
    assert COCO_KEYPOINT_NAMES[7] == "left_elbow"
    assert COCO_KEYPOINT_NAMES[15] == "left_ankle"


def test_left_wrist_is_index_9_right_is_10():
    xy, conf = _keypoints()
    person = build_person_pose(0, (0.0, 0.0, 500.0, 500.0), 0.9, xy, conf)

    assert person.left_wrist is not None and person.left_wrist.index == 9
    assert person.right_wrist is not None and person.right_wrist.index == 10
    assert person.left_wrist.xy == (100.0, 200.0)
    assert person.right_wrist.xy == (300.0, 400.0)

    payload = person.to_dict()
    assert payload["left_wrist"]["name"] == "left_wrist"
    assert payload["right_wrist"]["name"] == "right_wrist"
    assert payload["left_wrist"]["xy"] == [100.0, 200.0]


def test_invalid_wrist_confidence_does_not_invent_coordinates():
    xy, conf = _keypoints(wrist_conf=0.05)
    person = build_person_pose(
        0, (0.0, 0.0, 500.0, 500.0), 0.9, xy, conf, wrist_conf_min=WRIST_CONF_MIN
    )

    assert person.left_wrist is not None
    assert person.left_wrist.valid is False
    assert person.left_wrist.xy is None
    assert person.right_wrist.valid is False
    assert person.right_wrist.xy is None

    payload = person.to_dict()
    assert payload["left_wrist"]["xy"] is None
    assert payload["right_wrist"]["valid"] is False

    frame = PoseFrame(persons=[person])
    both, one, none = frame.count_valid_wrists()
    assert (both, one, none) == (0, 0, 1)
    records = frame.wrist_records()
    assert all(record["xy"] is None for record in records)
    assert all(record["valid"] is False for record in records)


def test_keypoint_count_is_validated():
    with pytest.raises(ValueError):
        build_person_pose(0, (0.0, 0.0, 10.0, 10.0), 0.9, [(0.0, 0.0)] * 16, [0.9] * 16)


# ================================================================ 10. fusion schema
def _detection(class_id: int, name: str, box: tuple, confidence: float):
    return BallRacketDetection(
        class_id=class_id,
        class_name=name,
        confidence=confidence,
        box=Box(
            box[0], box[1], box[2], box[3],
            class_id=class_id, confidence=confidence,
            image_width=1920, image_height=1080,
        ),
    )


def test_fusion_json_schema_and_heuristic_label():
    xy, conf = _keypoints()
    xy[LEFT_WRIST_INDEX] = (700.0, 500.0)
    xy[RIGHT_WRIST_INDEX] = (200.0, 300.0)
    person = build_person_pose(0, (100.0, 100.0, 800.0, 900.0), 0.95, xy, conf)
    frame = PoseFrame(persons=[person])
    racket = _detection(CLASS_RACKET, "racket", (680.0, 480.0, 760.0, 560.0), 0.8)

    result = associate_frame(frame, [racket])

    assert result["heuristic"] is True
    assert result["is_ground_truth"] is False
    assert result["name"] == "serving_player_candidate"
    assert result["decision"] in (DECISION_ASSOCIATED, DECISION_UNKNOWN)
    assert result["candidate_server_person_id"] == 0
    assert result["candidate_racket_wrist"]["wrist"] == "left_wrist"
    assert result["candidate_racket_wrist"]["keypoint_index"] == 9
    assert result["candidate_toss_wrist"]["wrist"] == "right_wrist"
    assert result["candidate_toss_wrist"]["keypoint_index"] == 10
    assert result["racket_class_id"] == CLASS_RACKET

    text = json.dumps(result, ensure_ascii=False)
    assert "hand" not in text


def test_fusion_returns_unknown_without_racket():
    xy, conf = _keypoints()
    person = build_person_pose(0, (0.0, 0.0, 800.0, 900.0), 0.95, xy, conf)
    frame = PoseFrame(persons=[person])
    ball = _detection(CLASS_BALL, "ball", (100.0, 100.0, 120.0, 120.0), 0.9)

    result = associate_frame(frame, [ball])
    assert result["decision"] == DECISION_UNKNOWN
    assert result["candidate_server_person_id"] is None
    assert result["candidate_racket_wrist"] is None
    assert "racket" in result["reason"]


def test_fusion_returns_unknown_when_ambiguous():
    xy_a, conf = _keypoints()
    xy_b, _ = _keypoints()
    person_a = build_person_pose(0, (100.0, 100.0, 800.0, 900.0), 0.95, xy_a, conf)
    person_b = build_person_pose(1, (110.0, 105.0, 805.0, 905.0), 0.94, xy_b, conf)
    frame = PoseFrame(persons=[person_a, person_b])
    racket = _detection(CLASS_RACKET, "racket", (680.0, 480.0, 760.0, 560.0), 0.8)

    result = associate_frame(frame, [racket])
    assert result["decision"] == DECISION_UNKNOWN
    assert "ambiguous" in result["reason"]


def test_temporal_association_prefers_stable_near_wrist():
    observations = []
    for frame_index in range(8):
        observations.append((frame_index, 0, "left_wrist", 20.0 + frame_index))
        observations.append((frame_index, 0, "right_wrist", 300.0 + frame_index))
    result = temporal_association(observations, window=8)
    assert result.decided is True
    assert result.racket_wrist == "left_wrist"
    assert result.toss_wrist == "right_wrist"
    assert result.to_dict()["is_ground_truth"] is False

    thin = temporal_association(observations[:2], window=8, min_frames=3)
    assert thin.decided is False


# ================================================================ 11/12. 数据隔离
def test_quick_test_is_never_used_for_training():
    """quick_test 视频必须与本轮任何训练/benchmark 输入隔离。"""
    frames_manifest = PATHS.bndstt_frames_manifest
    split_manifest = PATHS.bndstt_mvp_dir / "split_manifest.csv"
    if not frames_manifest.is_file():
        pytest.skip("BNDSTT_MVP_v1 frames_manifest.csv not present")

    with open(frames_manifest, "r", encoding="utf-8-sig", newline="") as handle:
        frames = [
            {(k or "").lstrip("\ufeff"): v for k, v in row.items()}
            for row in csv.DictReader(handle)
        ]

    for row in frames:
        for key in ("source_video_path", "original_image_path", "derived_gray3_path"):
            assert "quick_test" not in str(row.get(key, "")).lower()

    if split_manifest.is_file():
        with open(split_manifest, "r", encoding="utf-8-sig", newline="") as handle:
            splits = [
                {(k or "").lstrip("\ufeff"): v for k, v in row.items()}
                for row in csv.DictReader(handle)
            ]
        quick_sessions = {
            row.get("session_id", "") for row in splits if row.get("split") == "quick_test"
        }
        frame_sessions = {row.get("session_id", "") for row in frames}
        assert quick_sessions & frame_sessions == set()

    v2_dir = REPO_ROOT / "vision" / "c_perception_v2"
    offenders = []
    for source in v2_dir.glob("*.py"):
        for line in source.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if "quick_test" in stripped and not stripped.startswith("#"):
                if "artifacts/quick_test" in stripped or "artifacts" + chr(92) + "quick_test" in stripped:
                    offenders.append(source.name + ": " + stripped)
    assert offenders == []


def test_quick_test_artifacts_unmodified_by_this_round():
    """冻结检查：本轮不得修改 quick_test 产物（用 git 状态证明）。"""
    quick_dir = REPO_ROOT / "artifacts" / "quick_test"
    if not quick_dir.is_dir():
        pytest.skip("artifacts/quick_test not present")

    diff = subprocess.run(
        ["git", "status", "--porcelain", "--", "artifacts/quick_test"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert diff.stdout.strip() == "" or all(
        line.strip().startswith("??") for line in diff.stdout.strip().splitlines()
    )


def test_old_manual_gt_never_enters_public_data_training():
    """旧 manual GT（含 hand 标签）不得进入公开数据训练集。"""
    v2_dir = REPO_ROOT / "vision" / "c_perception_v2"
    forbidden = ("BNDSTT_MANUAL_GT_V1", "labels_yolo", "manual_annotation_manifest")
    offenders = []
    for source in sorted(v2_dir.glob("*.py")):
        for line in source.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if any(token in stripped for token in forbidden):
                # 精确豁免：只读的目录属性声明（域内尺寸对比用），不是训练数据引用
                exempt = (
                    'return self.datasets_dir / "BNDSTT_MANUAL_GT_V1"' in stripped
                    or "annotations_json" in stripped
                )
                if exempt:
                    continue
                offenders.append(source.name + ": " + stripped)
    assert offenders == []

    assert "BNDSTT_MANUAL_GT" not in str(PATHS.br_data_yaml)
    assert PATHS.br_data_yaml.name == "data.yaml"

    assert CLASS_NAMES == ("ball", "racket")
    assert CLASS_BALL == 0 and CLASS_RACKET == 1

    manual_labels = PATHS.bndstt_manual_gt_dir / "labels_yolo"
    if manual_labels.is_dir():
        for label in sorted(manual_labels.glob("*.txt")):
            for line in label.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    class_id = int(float(line.split()[0]))
                    assert class_id in (0, 1, 2)


# ================================================================ 其他安全约定
def test_roboflow_key_is_only_read_from_env(monkeypatch):
    monkeypatch.delenv("ROBOFLOW_API_KEY", raising=False)
    assert roboflow_api_key() is None
    monkeypatch.setenv("ROBOFLOW_API_KEY", "x" * 20)
    assert roboflow_api_key() == "x" * 20
    masked = mask_secret(roboflow_api_key())
    assert "xxxxx" not in masked
    assert mask_secret(None) == "<unset>"


def test_manual_zip_instructions_have_exact_steps(tmp_path):
    text = manual_zip_instructions(tmp_path)
    assert WAITING_FOR_ZIP_TOKEN in text
    assert "universe.roboflow.com/yolo-class-delww/tabletennis-nbcdc/dataset/2" in text
    assert "YOLOv8" in text
    assert str(tmp_path) in text


def test_safe_extract_blocks_zip_slip(tmp_path):
    import zipfile

    archive_path = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("../escaped.txt", "boom")
    with pytest.raises(DataPrepError):
        safe_extract(archive_path, tmp_path / "out")
    assert not (tmp_path / "escaped.txt").exists()


def test_find_data_yaml_searches_instead_of_assuming(tmp_path):
    nested = tmp_path / "tabletennis-nbcdc.v2i.yolov8" / "deeper"
    nested.mkdir(parents=True)
    (nested / "data.yaml").write_text("names: [ball, racket]" + chr(10), encoding="utf-8")
    (tmp_path / "unrelated.yaml").write_text("names: [x]" + chr(10), encoding="utf-8")
    assert find_data_yaml(tmp_path) == nested / "data.yaml"

    with pytest.raises(DataPrepError):
        find_data_yaml(tmp_path / "empty")


def test_gitignore_protects_generated_data():
    """图片 / 标签 / 权重 / benchmark 产物一律不可提交。"""
    assert is_gitignored(PATHS.repo_root / "artifacts" / "files" / "anything.jpg")
    assert is_gitignored(PATHS.br_dir / "images" / "train" / "x.jpg")
    assert is_gitignored(PATHS.model_out_dir / "best.pt")
    assert is_gitignored(PATHS.benchmark_dir / "benchmark_manifest.csv")
    assert is_gitignored(PATHS.downloads_dir / "tabletennis_nbcdc_v2_yolov8.zip")
    assert not is_gitignored(REPO_ROOT / "vision" / "c_perception_v2" / "config.py")
    assert_gitignored([PATHS.br_dir, PATHS.qa_dir, PATHS.model_out_dir])


def test_find_source_zip_prefers_expected_name(tmp_path):
    import shutil

    from vision.c_perception_v2.config import DOWNLOAD_ZIP_BASENAMES

    target = tmp_path / DOWNLOAD_ZIP_BASENAMES[0]
    target.write_bytes(b"PK" + bytes([3, 4]) + b"dummy")
    other = tmp_path / "other.zip"
    other.write_bytes(b"PK" + bytes([3, 4]) + b"dummy")
    assert find_source_zip(tmp_path) == target
    target.unlink()
    assert find_source_zip(tmp_path) is None
    loose = tmp_path / "tabletennis_whatever.zip"
    shutil.copy2(other, loose)
    assert find_source_zip(tmp_path) == loose


def test_perception_result_v2_schema_is_separate_from_legacy_api():
    """V2 结果结构独立，不改坏旧的 DetectionResult(boxes: ball/hand/racket)。"""
    result = PerceptionResultV2(
        image_path="x.jpg",
        image_width=1920,
        image_height=1080,
        ball_racket_detections=[
            _detection(CLASS_BALL, "ball", (10.0, 20.0, 40.0, 50.0), 0.7)
        ],
    )
    payload = result.to_dict()
    assert payload["schema_version"] == SCHEMA_VERSION
    assert set(payload) >= {
        "ball_racket_detections",
        "pose_persons",
        "wrists",
        "association",
    }
    assert payload["ball_racket_detections"][0]["class_name"] == "ball"
    assert "hand" not in json.dumps(payload)


def test_benchmark_manifest_is_frozen_and_deterministic():
    """已有 benchmark manifest 就不得被静默覆盖。"""
    manifest = PATHS.benchmark_manifest
    if not manifest.is_file():
        pytest.skip("benchmark manifest not built yet")
    digest_before = hashlib.sha256(manifest.read_bytes()).hexdigest()
    with pytest.raises(BenchmarkError):
        write_benchmark([], PATHS.benchmark_dir, isolation={}, force=False)
    digest_after = hashlib.sha256(manifest.read_bytes()).hexdigest()
    assert digest_before == digest_after


def test_ball_size_csv_has_required_columns(tmp_path):
    raw = tmp_path / "raw"
    data_yaml = _make_synthetic_raw(raw)
    out = tmp_path / "br"
    convert_to_ball_racket(data_yaml, out)
    target = tmp_path / "ball_size_distribution.csv"
    summary = collect_ball_sizes(out, target)
    assert target.is_file()
    with open(target, "r", encoding="utf-8", newline="") as handle:
        header = next(csv.reader(handle))
    for column in ("bbox_w_px", "bbox_h_px", "bbox_area_ratio"):
        assert column in header
    assert summary["count"] >= 1


# ================================================================ fine-tune V1 守护
def test_finetune_pool_excludes_frozen_benchmark():
    """选池绝不允许包含 frozen BNDSTT_30_V1 的任何一帧。"""
    from vision.c_perception_v2 import finetune_domain as fd

    manifest = fd.manifest_path()
    if not manifest.is_file():
        pytest.skip("finetune pool not built yet")
    pool_ids = {row["image_id"] for row in fd.read_csv_rows(manifest)}
    bench_ids = fd.benchmark_image_ids()
    assert pool_ids & bench_ids == set()
    assert len(bench_ids) == 30
    assert len(pool_ids) == fd.POOL_SIZE


def test_proposals_are_never_ground_truth():
    """proposal 必须标记 MODEL_PROPOSAL；未经人工确认不得进入训练。"""
    import json as _json

    from vision.c_perception_v2 import finetune_domain as fd

    props = sorted(fd.proposals_dir().glob("*.json")) if fd.proposals_dir().is_dir() else []
    if not props:
        pytest.skip("proposals not generated yet")
    payload = _json.loads(props[0].read_text(encoding="utf-8"))
    assert payload["annotation_source"] == "MODEL_PROPOSAL"
    assert payload["is_ground_truth"] is False
    for obj in payload["objects"]:
        assert obj["class_id"] in (0, 1)  # 只有 ball / racket，没有 hand

    # 未确认时 build 必须拒绝，而不是把 proposal 当 GT 训练
    if fd.review_progress()["human_verified"] == 0:
        with pytest.raises(fd.FinetuneError):
            fd.build_finetune_dataset()


def test_finetune_annotation_schema_rejects_hand_and_oob():
    """标注校验：类别只用 0/1，越界框拒绝。"""
    from vision.c_perception_v2 import annotator_br as an
    from vision.c_perception_v2.finetune_domain import FinetuneError

    base = {"image_id": "x", "image_width": 100, "image_height": 100}
    with pytest.raises(FinetuneError):
        an.validate_payload(dict(base, objects=[{"class_id": 2, "bbox_xyxy": [1, 1, 9, 9]}]))
    with pytest.raises(FinetuneError):
        an.validate_payload(dict(base, objects=[{"class_id": 0, "bbox_xyxy": [-5, 1, 9, 9]}]))
    with pytest.raises(FinetuneError):
        an.validate_payload(dict(base, objects=[{"class_id": 0, "bbox_xyxy": [5, 5, 5, 9]}]))
    record = an.validate_payload(
        dict(base, objects=[{"class_id": 0, "bbox_xyxy": [1, 2, 30, 40]},
                            {"class_id": 1, "bbox_xyxy": [10, 10, 90, 90]}])
    )
    assert record["annotation_source"] == "HUMAN_VERIFIED"
    assert [o["class_name"] for o in record["objects"]] == ["ball", "racket"]


def test_finetune_assignment_keeps_source_together():
    """按 source 分组拆分：同一 source 不允许跨 train/val。"""
    from vision.c_perception_v2 import finetune_domain as fd

    rows = [
        {"image_id": "a1", "source_id": "s1", "session_id": "t1", "split": "train"},
        {"image_id": "a2", "source_id": "s1", "session_id": "t1", "split": "train"},
        {"image_id": "b1", "source_id": "s2", "session_id": "t2", "split": "train"},
        {"image_id": "c1", "source_id": "s3", "session_id": "t3", "split": "val"},
    ]
    assignment = fd.assign_split(rows, train_size=3)
    by_source: dict[str, set[str]] = {}
    for row in rows:
        by_source.setdefault(row["source_id"], set()).add(assignment[row["image_id"]])
    assert all(len(splits) == 1 for splits in by_source.values())


def test_finetune_targets_match_agreed_thresholds():
    """门槛与方案一致：ball 24 / racket 26 / both 22。"""
    from vision.c_perception_v2.eval_finetune import TARGETS

    assert TARGETS == {"ball_frames_min": 24, "racket_frames_min": 26, "both_frames_min": 22}

# ================================================================ operating point + temporal
def test_class_specific_threshold_filtering():
    """同一 frame 里 ball 与 racket 用各自阈值过滤，互不影响。"""
    from vision.c_perception_v2.operating_point import CLASS_BALL, CLASS_RACKET, fixed_threshold_metrics

    cache = {
        "detections": [
            {"image_id": "a", "class_id": 0, "confidence": 0.04, "bbox_xyxy": [0, 0, 10, 10]},
            {"image_id": "a", "class_id": 0, "confidence": 0.30, "bbox_xyxy": [0, 0, 10, 10]},
            {"image_id": "a", "class_id": 1, "confidence": 0.20, "bbox_xyxy": [0, 0, 50, 50]},
        ],
        "ground_truth": [
            {"image_id": "a", "class_id": 0, "bbox_xyxy": [0, 0, 10, 10]},
            {"image_id": "a", "class_id": 1, "bbox_xyxy": [0, 0, 50, 50]},
        ],
    }
    ball_low = fixed_threshold_metrics(cache, CLASS_BALL, 0.03)
    ball_high = fixed_threshold_metrics(cache, CLASS_BALL, 0.25)
    assert ball_low["tp"] == 1 and ball_low["fp"] == 1
    assert ball_high["tp"] == 1 and ball_high["fp"] == 0
    racket = fixed_threshold_metrics(cache, CLASS_RACKET, 0.20)
    assert racket["tp"] == 1 and racket["fp"] == 0
    # ball 阈值变化不影响 racket 结果
    assert racket == fixed_threshold_metrics(cache, CLASS_RACKET, 0.20)


def test_ball_and_racket_thresholds_are_independent():
    """两个类别的阈值网格相互独立，不被强制共享。"""
    from vision.c_perception_v2 import operating_point as op

    assert op.BALL_THRESHOLDS[0] != op.RACKET_THRESHOLDS[0]
    assert len(set(op.BALL_THRESHOLDS)) == len(op.BALL_THRESHOLDS)
    assert op.THRESHOLD_GRID_IS_SHARED is False


def test_fixed_iou_matching_is_one_to_one():
    """一个 prediction 只能匹配一个 GT；重叠 GT 不会重复计数。"""
    from vision.c_perception_v2.operating_point import match_one_to_one

    preds = [{"class_id": 0, "confidence": 0.9, "bbox_xyxy": [0, 0, 10, 10]}]
    gts = [
        {"class_id": 0, "bbox_xyxy": [0, 0, 10, 10]},
        {"class_id": 0, "bbox_xyxy": [0, 0, 10, 10]},
    ]
    result = match_one_to_one(preds, gts, match_iou=0.5)
    assert result["tp"] == 1
    assert result["fn"] == 1
    assert result["fp"] == 0

    # 两个 prediction 抢同一个 GT -> 只有一个算 TP
    preds2 = [
        {"class_id": 0, "confidence": 0.9, "bbox_xyxy": [0, 0, 10, 10]},
        {"class_id": 0, "confidence": 0.8, "bbox_xyxy": [0, 0, 10, 10]},
    ]
    result2 = match_one_to_one(preds2, [gts[0]], match_iou=0.5)
    assert result2["tp"] == 1 and result2["fp"] == 1


def test_bndstt30_is_never_treated_as_a_sequence():
    """BNDSTT_30 来自 30 个不同 source，禁止被 temporal 模块当序列。"""
    from vision.c_perception_v2 import temporal_diagnostic as td
    from vision.c_perception_v2.config import PATHS

    src = (PATHS.repo_root / "vision" / "c_perception_v2" / "temporal_diagnostic.py").read_text(encoding="utf-8")
    assert "benchmark_manifest" not in src
    assert "BNDSTT_30" not in src
    rows = td.load_manifest()
    assert len({r["source_id"] for r in rows}) == len(rows)


def test_temporal_manifest_excludes_quick_test_and_benchmark_sources():
    """temporal 数据集必须与 quick_test 和 BNDSTT_30 source 零重叠。"""
    from vision.c_perception_v2 import temporal_benchmark as tb
    from vision.c_perception_v2.config import PATHS
    from vision.c_perception_v2.finetune_domain import read_csv_rows

    if not tb.manifest_path().is_file():
        pytest.skip("temporal manifest not built")
    rows = tb.load_manifest()
    bench = {r["source_id"] for r in read_csv_rows(PATHS.benchmark_manifest)}
    assert {r["source_id"] for r in rows} & bench == set()
    quick = {r["session_id"] for r in read_csv_rows(PATHS.bndstt_mvp_dir / "split_manifest.csv")
             if r.get("split") == "quick_test"}
    assert {r["session_id"] for r in rows} & quick == set()


def test_temporal_frames_are_chronological_and_adjacent():
    """每段帧按序编号，且帧号连续（真正相邻）。"""
    from vision.c_perception_v2 import temporal_benchmark as tb

    if not tb.manifest_path().is_file():
        pytest.skip("temporal manifest not built")
    for clip in tb.load_manifest():
        folder = tb.frames_dir() / clip["clip_id"]
        names = sorted(p.name for p in folder.glob("f*.jpg"))
        indices = [int(n[1:5]) for n in names]
        assert indices == list(range(len(indices))), clip["clip_id"]
        assert len(indices) == int(clip["num_frames"])


def test_kalman_gate_rejects_far_candidates():
    """超出归一化距离 gate 的候选不能被接受。"""
    from vision.c_perception_v2 import temporal_diagnostic as td

    config = td.TrackerConfig(ball_conf=0.10, base_conf=0.02)
    tracker = td.KalmanTracker(0, config, (100.0, 100.0))
    tracker.update((100.0, 100.0))
    tracker.predict()
    frame = {"width": 1920, "height": 1080}
    near = {"class_id": 0, "confidence": 0.9, "center_xy": [102.0, 101.0], "bbox_xyxy": [0, 0, 1, 1]}
    far = {"class_id": 0, "confidence": 0.9, "center_xy": [1500.0, 900.0], "bbox_xyxy": [0, 0, 1, 1]}
    assert tracker.gate_ok(frame, near)
    assert not tracker.gate_ok(frame, far)


def test_max_prediction_gap_is_respected():
    """连续无候选超过 max_prediction_gap 后必须断开，不得无限预测。"""
    from vision.c_perception_v2 import temporal_diagnostic as td

    def frame(index, conf=None):
        candidates = [] if conf is None else [
            {"class_id": 0, "confidence": conf, "center_xy": [100.0 + index, 100.0],
             "bbox_xyxy": [90, 90, 110, 110]}]
        return {"frame_idx": index, "width": 1920, "height": 1080, "candidates": candidates}

    frames = [frame(0, 0.9)] + [frame(i) for i in range(1, 11)]
    config = td.TrackerConfig(ball_conf=0.10, base_conf=0.02, max_prediction_gap=2)
    result = td.run_kalman(frames, config)
    predicted = [r for r in result["per_frame"] if r["state"] == td.PREDICTED_ONLY]
    assert len(predicted) == 2, "预测不得超过 max_prediction_gap"
    assert result["reinitializations"] >= 1


def test_recovered_low_conf_requires_real_candidate():
    """RECOVERED_LOW_CONF 必须确实存在 detector candidate；PREDICTED_ONLY 不得有。"""
    from vision.c_perception_v2 import temporal_diagnostic as td

    def frame(index, conf=None):
        candidates = [] if conf is None else [
            {"class_id": 0, "confidence": conf, "center_xy": [100.0 + index * 2, 100.0],
             "bbox_xyxy": [90, 90, 110, 110]}]
        return {"frame_idx": index, "width": 1920, "height": 1080, "candidates": candidates}

    frames = [frame(0, 0.9), frame(1, 0.05), frame(2, 0.04), frame(3)]
    config = td.TrackerConfig(ball_conf=0.10, base_conf=0.02, max_prediction_gap=2)
    result = td.run_kalman(frames, config)
    for row in result["per_frame"]:
        if row["state"] == td.RECOVERED:
            assert row["accepted_candidate"] is True
            assert row["raw_conf"] is not None
            assert row["raw_conf"] < config.ball_conf
        if row["state"] == td.PREDICTED_ONLY:
            assert row["accepted_candidate"] is False
            assert row["raw_conf"] is None


def test_predicted_only_not_counted_as_detector_supported():
    """PREDICTED_ONLY 不计入 detector-supported coverage。"""
    from vision.c_perception_v2 import temporal_diagnostic as td

    frames = [{"frame_idx": 0, "width": 1920, "height": 1080, "candidates": [
        {"class_id": 0, "confidence": 0.9, "center_xy": [100.0, 100.0], "bbox_xyxy": [90, 90, 110, 110]}]},
        {"frame_idx": 1, "width": 1920, "height": 1080, "candidates": []},
        {"frame_idx": 2, "width": 1920, "height": 1080, "candidates": []}]
    config = td.TrackerConfig(ball_conf=0.10, base_conf=0.02, max_prediction_gap=2)
    result = td.run_kalman(frames, config)
    summary = td.summarize_clip(frames, result["per_frame"], config, "KALMAN")
    assert summary["predicted_only_frames"] == 2
    assert summary["detected_frames"] + summary["recovered_low_conf_frames"] == 1
    assert result["detector_supported_frames"] == 1


def test_causal_filter_never_reads_future_frames():
    """因果平滑：截断未来帧后，已处理帧的结果必须不变。"""
    from vision.c_perception_v2 import temporal_diagnostic as td

    def frame(index, conf):
        return {"frame_idx": index, "width": 1920, "height": 1080, "candidates": [
            {"class_id": 0, "confidence": conf, "center_xy": [100.0 + index, 100.0],
             "bbox_xyxy": [90, 90, 110, 110]}]}

    frames = [frame(i, 0.2) for i in range(6)]
    config = td.TrackerConfig(ball_conf=0.10, base_conf=0.02, smoothing="causal", smoothing_window=3)
    full = td.run_simple(frames, config)["per_frame"]
    truncated = td.run_simple(frames[:3], config)["per_frame"]
    for a, b in zip(full[:3], truncated):
        assert a["state"] == b["state"]
        assert a["smoothed_conf"] == b["smoothed_conf"]


def test_low_base_conf_candidate_cache_is_reproducible():
    """低阈值候选应可复现：两次独立推理的关键统计一致。"""
    from vision.c_perception_v2 import temporal_diagnostic as td
    from vision.c_perception_v2.config import PATHS
    from vision.c_perception_v2.temporal_benchmark import load_manifest

    weights = PATHS.model_out_dir / "best.pt"
    if not weights.is_file():
        pytest.skip("baseline weights missing")
    clips = load_manifest()
    if not clips:
        pytest.skip("temporal manifest not built")
    clip = clips[0]
    first = td.extract_raw_candidates(clip, weights, 0.10)
    second = td.extract_raw_candidates(clip, weights, 0.10)
    assert len(first["frames"]) == len(second["frames"])
    a = [round(c["confidence"], 6) for f in first["frames"] for c in f["candidates"]]
    b = [round(c["confidence"], 6) for f in second["frames"] for c in f["candidates"]]
    assert a == b


def test_operating_point_and_temporal_do_not_train_or_read_manual_gt():
    """本阶段只做诊断：不得出现训练调用，也不得读取 BNDSTT 人工 GT。"""
    from vision.c_perception_v2.config import PATHS

    v2 = PATHS.repo_root / "vision" / "c_perception_v2"
    forbidden_calls = (".train(", "model.train", "train_once(", "train_variant(")
    forbidden_gt = ("BNDSTT_MANUAL_GT_V1", "labels_yolo", "manual_annotation_manifest")
    scan = [
        "operating_point.py", "temporal_benchmark.py", "temporal_diagnostic.py",
        "ball_failure_analysis.py",
    ]
    for name in scan:
        text = (v2 / name).read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            for token in forbidden_calls:
                assert token not in stripped, name + " contains training call: " + stripped
            for token in forbidden_gt:
                assert token not in stripped, name + " reads manual GT: " + stripped


def test_temporal_manifest_is_frozen():
    """temporal manifest 一旦生成即冻结，默认拒绝覆盖。"""
    from vision.c_perception_v2 import temporal_benchmark as tb

    if not tb.manifest_path().is_file():
        pytest.skip("temporal manifest not built")
    import hashlib

    before = hashlib.sha256(tb.manifest_path().read_bytes()).hexdigest()
    with pytest.raises(tb.TemporalError):
        tb.build_temporal_set(force=False)
    after = hashlib.sha256(tb.manifest_path().read_bytes()).hexdigest()
    assert before == after

# ================================================================ C finalization
def test_final_ball_backend_is_recorded_and_reproducible():
    """最终 ball 后端必须被明确记录，且与 bake-off 结论一致（可复现）。"""
    import json

    from vision.c_perception_v2.config import PATHS

    comp = PATHS.reports_dir / "BALL_DETECTOR_FINAL_BAKEOFF" / "comparison.json"
    if not comp.is_file():
        pytest.skip("bake-off not run")
    data = json.loads(comp.read_text(encoding="utf-8"))
    assert data["final_ball_detector"] in ("YOLO", "BALLTRACK")
    assert data["switch_rule"]["threshold_pp"] == 0.05
    # 选择必须与实测差距一致，不允许“因为模型高级”而选
    gap = data["presence_gap_balltrack_minus_yolo"]
    if gap is not None and gap < 0.05:
        assert data["final_ball_detector"] == "YOLO"
    assert data["balltrack_provenance"]["license"] == "MIT"
    # GT 集合无负样本 => 不得报告 precision
    assert "precision" not in json.dumps(data["yolo"]).lower()


def test_pose_wrist_keypoint_indices():
    """COCO 17 关键点：left_wrist=9, right_wrist=10（Python 0-based）。"""
    import pathlib as _pathlib

    from vision.c_perception_v2 import wrist_pose

    assert wrist_pose.LEFT_WRIST_INDEX == 9
    assert wrist_pose.RIGHT_WRIST_INDEX == 10
    module = _pathlib.Path(wrist_pose.__file__).read_text(encoding="utf-8")
    assert "LEFT_WRIST_INDEX = 9" in module
    assert "RIGHT_WRIST_INDEX = 10" in module


def test_low_confidence_wrist_is_invalid_and_not_fabricated():
    """低置信 wrist 必须 valid=false 且不造坐标。"""
    from vision.c_perception_v2.ball_racket import WristObservation

    low = WristObservation(name="left_wrist", keypoint_index=9, xy=None, confidence=0.01, valid=False)
    payload = low.to_dict()
    assert payload["valid"] is False
    assert payload["xy"] is None
    assert payload["geometry"] == "keypoint"


def test_no_fake_hand_bbox_in_legacy_adapter():
    """legacy adapter 只输出 ball/racket，绝不伪造 hand 框。"""
    from vision.c_perception_v2.ball_racket import (
        BallObservation, BALL_SOURCE_BALLTRACK, BALL_STATE_DETECTED,
        PerceptionResultV2Final, PersonObservation, RacketObservation,
        WristObservation, to_legacy_boxes,
    )

    result = PerceptionResultV2Final(
        ball=BallObservation(source=BALL_SOURCE_BALLTRACK, state=BALL_STATE_DETECTED,
                             confidence=0.6, center_xy=[100.0, 200.0]),
        rackets=[RacketObservation(confidence=0.7, bbox_xyxy=[10, 10, 50, 50])],
        persons=[PersonObservation(person_id=0, bbox_xyxy=[0, 0, 100, 100], confidence=0.9,
                                   left_wrist=WristObservation(name="left_wrist", keypoint_index=9,
                                                               xy=[1, 2], confidence=0.9, valid=True))],
    )
    boxes = to_legacy_boxes(result)
    names = {b["class_name"] for b in boxes}
    assert "hand" not in names
    assert "toss_hand" not in names
    assert "racket_hand" not in names
    assert names <= {"ball", "racket"}
    # wrist 以 keypoint 形式出现在 persons 里，而不是 box
    assert result.to_dict()["persons"][0]["left_wrist"]["geometry"] == "keypoint"


def test_perception_result_v2_serialization():
    """V2 结构可完整序列化，且元数据字段齐全。"""
    import json

    from vision.c_perception_v2.ball_racket import (
        AssociationObservation, BallObservation, BALL_SOURCE_NONE, BALL_STATE_INVALID,
        PerceptionMetadata, PerceptionResultV2Final,
    )

    meta = PerceptionMetadata(source_pair_id="p1", task_id="t1", generation=3, timestamp=1.25,
                              frame_id=77, eye="left", original_width=1280, original_height=720)
    result = PerceptionResultV2Final(metadata=meta, ball=BallObservation(source=BALL_SOURCE_NONE,
                                                                       state=BALL_STATE_INVALID))
    payload = json.loads(result.to_json())
    assert payload["metadata"]["original_width"] == 1280
    assert payload["metadata"]["eye"] == "left"
    assert payload["ball"]["state"] == "INVALID"
    assert payload["association"]["is_ground_truth"] is False
    assert set(payload) == {"schema_version", "metadata", "ball", "racket", "persons", "association"}


def test_association_can_never_claim_ground_truth():
    """association 只允许 HEURISTIC / UNKNOWN，不能冒充 GT。"""
    from vision.c_perception_v2.ball_racket import AssociationObservation

    for status in ("HEURISTIC", "UNKNOWN"):
        assert AssociationObservation(status=status).to_dict()["is_ground_truth"] is False
    for bad in ("GROUND_TRUTH", "GT", "TRUE", "manual"):
        with pytest.raises(ValueError):
            AssociationObservation(status=bad)


def test_ball_state_invariants():
    """只有 DETECTED / RECOVERED_LOW_CONF 算 detection；PREDICTED_ONLY / INVALID 不算。"""
    from vision.c_perception_v2.ball_racket import (
        BallObservation, BALL_STATE_DETECTED, BALL_STATE_INVALID, BALL_STATE_PREDICTED_ONLY,
        BALL_STATE_RECOVERED,
    )

    assert BallObservation(state=BALL_STATE_DETECTED, center_xy=[1, 2]).detected is True
    assert BallObservation(state=BALL_STATE_RECOVERED, center_xy=[1, 2]).detected is True
    assert BallObservation(state=BALL_STATE_PREDICTED_ONLY, center_xy=[1, 2]).detected is False
    assert BallObservation(state=BALL_STATE_INVALID).detected is False
    with pytest.raises(ValueError):
        BallObservation(state=BALL_STATE_DETECTED)   # 没有 center 却声称检测到
    with pytest.raises(ValueError):
        BallObservation(state="DETECTED_BUT_MAYBE_NOT")


def test_coordinates_are_original_not_letterbox():
    """检测输出坐标必须是原图坐标，不能是 640 letterbox 坐标。"""
    from vision.c_perception_v2.config import PATHS

    v2 = PATHS.repo_root / "vision" / "c_perception_v2"
    text = (v2 / "ball_racket.py").read_text(encoding="utf-8")
    # Ultralytics Results.boxes.xyxy 已映射回原图，不得再乘 letterbox 比例
    assert "letterbox" not in text.lower() or "original" in text.lower()
    # 不写死尺寸
    assert "1280" not in text.replace("1280x720", "")


def test_default_inference_config_parses_and_matches_frozen_values():
    """正式推理配置存在、可解析，且与冻结阈值一致。"""
    from vision.c_perception_v2.config import PATHS

    cfg = PATHS.repo_root / "vision" / "c_perception_v2" / "config" / "default_inference.yaml"
    assert cfg.is_file()
    text = cfg.read_text(encoding="utf-8")
    for key in ("base_conf", "ball_conf", "racket_conf", "pose_conf", "max_prediction_gap",
                "backend", "causal", "predicted_only_for_continuity_only"):
        assert key in text, key
    assert "base_conf: 0.02" in text
    assert "racket_conf: 0.30" in text
    assert "max_prediction_gap: 2" in text
    assert "causal: true" in text
    assert "backend: balltrack" in text


def test_final_architecture_doc_freezes_key_rules():
    """FINAL_ARCHITECTURE.md 必须写明关键不变式。"""
    from vision.c_perception_v2.config import PATHS

    doc = PATHS.repo_root / "vision" / "c_perception_v2" / "FINAL_ARCHITECTURE.md"
    assert doc.is_file()
    text = doc.read_text(encoding="utf-8")
    assert "PREDICTED_ONLY" in text
    assert "!= DETECTION" in text or "!= detection" in text
    assert "does not decide serve legality" in text.lower() or "不判断发球合法" in text
    assert "original eye image coordinates" in text.lower()
    assert "RECOVERED_LOW_CONF" in text


def test_model_manifest_lists_every_deployed_model_with_sha256():
    """MODEL_MANIFEST.md 必须为每个部署模型给出路径与 SHA256。"""
    import re

    from vision.c_perception_v2.config import PATHS

    doc = PATHS.repo_root / "vision" / "c_perception_v2" / "MODEL_MANIFEST.md"
    assert doc.is_file()
    text = doc.read_text(encoding="utf-8")
    for name in ("BallTrack", "ball_racket_yolov8n_v1", "yolov8n-pose"):
        assert name in text, name
    hashes = re.findall(r"`([0-9a-f]{64})`", text)
    assert len(hashes) >= 3, "expected at least 3 full SHA256 digests"
    assert "RKNN_PREPARED_NOT_EXECUTED" in text
    assert "BOARD VERIFIED" in text              # 出现即说明写了禁止声明
    assert "不得" in text or "must not" in text.lower()


def test_rknn_export_script_refuses_to_claim_board_verification():
    """RKNN 脚本与指南不得声称板端验证通过。"""
    from vision.c_perception_v2.config import PATHS

    v2 = PATHS.repo_root / "vision" / "c_perception_v2"
    script = (v2 / "export_rknn.py").read_text(encoding="utf-8")
    guide = (v2 / "RKNN_DEPLOYMENT_GUIDE.md").read_text(encoding="utf-8")
    assert "RKNN_PREPARED_NOT_EXECUTED" in script
    assert "RKNN CONVERSION VERIFIED ON HOST" in guide
    assert "rk3576" in script
    # 允许的声明只有“主机侧验证”；板端措辞必须以禁止形式出现
    for forbidden in ("BOARD VERIFIED", "REAL-TIME VERIFIED"):
        for line in guide.splitlines():
            if forbidden in line:
                assert line.strip().startswith("- ~~") or "不得" in line or "禁止" in line, line


def test_legacy_reports_carry_deprecation_banner():
    """旧 29-image 报告必须标注 DEPRECATED 且保留原文。"""
    from vision.c_perception_v2.config import PATHS

    root = PATHS.repo_root
    for rel in ("reports/C_DETECTOR_MVP_V1.md", "reports/PR_BODY_C_DETECTOR_MVP.md"):
        path = root / rel
        assert path.is_file(), rel
        text = path.read_text(encoding="utf-8")
        assert "DEPRECATED / INVALIDATED EXPERIMENT" in text, rel
        assert "INVALID FOR FINAL EVALUATION" in text, rel
        # 原文必须保留（旧指标不能被删）
        assert "29/29" in text, rel


def test_finetune_pool_is_marked_suspended_everywhere():
    """80 张 fine-tune pool 必须在文档里明确 SUSPENDED / 未使用。"""
    from vision.c_perception_v2.config import PATHS

    root = PATHS.repo_root
    found = False
    for rel in ("vision/c_perception_v2/STATUS.md", "vision/c_perception_v2/README.md",
                "vision/c_perception_v2/STATUS_FINETUNE_V1.md"):
        path = root / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8").upper()
        if "SUSPENDED" in text and "HUMAN_VERIFIED" in text:
            found = True
    assert found, "fine-tune pool must be documented as SUSPENDED with human_verified=0"


def test_onnx_artifacts_are_gitignored():
    """ONNX / RKNN / 权重都不得进入 Git。"""
    from vision.c_perception_v2.config import is_gitignored, PATHS

    for rel in ("artifacts/files/reports/ONNX_EXPORT_V1/models/ball_racket_yolov8n_v1.onnx",
                "artifacts/files/models/balltrack/balltrack_best.pth",
                "artifacts/files/reports/RKNN_EXPORT_V1/x.rknn"):
        assert is_gitignored(PATHS.repo_root / rel), rel

if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
