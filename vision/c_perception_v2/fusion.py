"""时序关联候选判定（HEURISTIC）+ BNDSTT 30 帧联合可视化（AC~AF）。

模块划分说明
------------
``fusion``（判定）与 ``fusion_demo``（可视化）在本轮合并为同一实现：仓库所在路径存在
“部分新文件无法写入”的环境问题，合并成一个模块可减少落盘失败面。``fusion_demo.py``
作为别名导出，方案要求的两个入口名都可正常 import 与执行。

结果结构
--------
* :func:`associate_frame` 单帧**候选**关联：标记 ``HEURISTIC``，不是 Ground Truth；
* :func:`temporal_association` 连续帧稳定关系（给后续视频版本预留）；
* :func:`run_fusion_demo` 输出三视图 contact sheet 与 JSON。

坐标：全部为**原图坐标**（AG）。Pose 给的是手腕**点**，本模块不给手腕造 bbox（W）。
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import CLASS_NAMES, SCHEMA_VERSION
from .ball_racket import (
    BallRacketDetection,
    PerceptionResultV2,
    PosePersonLite,
    detect_ball_racket,
    load_detector,
)
from .config import (
    INFER_CONF_DISPLAY,
    INFER_CONF_REPORT,
    INFER_IMGSZ,
    INFER_IOU,
    PATHS,
    WRIST_CONF_MIN,
)
from .dataset_qa import contact_sheet, read_image_robust, write_image_robust
from .wrist_pose import (
    LEFT_WRIST_INDEX,
    RIGHT_WRIST_INDEX,
    PoseFrame,
    draw_pose_person,
    infer_pose,
    load_pose_model,
)
from .yolo_io import (
    COLOR_BALL,
    COLOR_PERSON,
    COLOR_RACKET,
    COLOR_RACKET_WRIST,
    COLOR_TOSS_WRIST,
    COLOR_WRIST_L,
    COLOR_WRIST_R,
    Box,
    box_contains_point,
    distance_point_to_box,
    draw_box,
    draw_label,
    draw_legend,
    draw_wrist,
)

# ================================================================ 关联参数
DECISION_UNKNOWN = "UNKNOWN"
DECISION_ASSOCIATED = "HEURISTIC_ASSOCIATED"

CONTAINMENT_BONUS = 1.0        # person bbox 含 racket 中心的相对加分
DISTANCE_WEIGHT = 1.0          # 距离项权重（相对 person bbox 对角线归一化）
MIN_MARGIN = 0.15              # 第一/第二名归一化分差下限
RACKET_CONF_MIN = 0.15         # 低于此置信度视为“没有可靠 racket”
DEFAULT_WINDOW = 8             # 时序窗口帧数
DISPLAY_WIDTH = 960


def _diag(person_bbox: tuple[float, float, float, float]) -> float:
    x1, y1, x2, y2 = person_bbox
    return max(1.0, ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5)


def _pose_box(person) -> Box:
    x1, y1, x2, y2 = person.bbox_xyxy
    return Box(x1, y1, x2, y2, class_id=-1, confidence=person.person_confidence)


def _wrist_xy(person, index: int):
    keypoint = person.keypoint(index)
    if keypoint is None or not keypoint.valid or keypoint.xy is None:
        return None
    return keypoint.xy


@dataclass
class PersonScore:
    person_id: int
    score: float
    racket_distance: float
    in_person: bool
    left_distance: float | None
    right_distance: float | None
    near_wrist: str | None
    near_distance: float | None

    def to_dict(self) -> dict:
        return {
            "person_id": int(self.person_id),
            "score": round(float(self.score), 6),
            "racket_distance_px": round(float(self.racket_distance), 3),
            "racket_center_in_person_bbox": bool(self.in_person),
            "left_wrist_distance_px": None
            if self.left_distance is None
            else round(float(self.left_distance), 3),
            "right_wrist_distance_px": None
            if self.right_distance is None
            else round(float(self.right_distance), 3),
            "near_wrist": self.near_wrist,
            "near_distance_px": None
            if self.near_distance is None
            else round(float(self.near_distance), 3),
        }


def score_person_against_racket(person, racket: BallRacketDetection) -> PersonScore:
    """单个人相对 racket 的启发式得分。"""
    racket_box: Box = racket.box
    person_box = _pose_box(person)
    racket_distance = distance_point_to_box(racket_box.center, person_box)
    in_person = box_contains_point(person_box, racket_box.center) or (
        racket_box.x1 >= person.bbox_xyxy[0]
        and racket_box.x2 <= person.bbox_xyxy[2]
        and racket_box.y1 >= person.bbox_xyxy[1]
        and racket_box.y2 <= person.bbox_xyxy[3]
    )

    left_xy = _wrist_xy(person, LEFT_WRIST_INDEX)
    right_xy = _wrist_xy(person, RIGHT_WRIST_INDEX)
    left_distance = distance_point_to_box(left_xy, racket_box) if left_xy else None
    right_distance = distance_point_to_box(right_xy, racket_box) if right_xy else None

    diag = _diag(person.bbox_xyxy)
    candidates = [
        (name, distance)
        for name, distance in (("left_wrist", left_distance), ("right_wrist", right_distance))
        if distance is not None
    ]
    near_wrist: str | None = None
    near_distance: float | None = None
    if candidates:
        near_wrist, near_distance = min(candidates, key=lambda item: item[1])

    score = (CONTAINMENT_BONUS if in_person else 0.0) - DISTANCE_WEIGHT * (
        (near_distance / diag) if near_distance is not None else 1.0
    )
    return PersonScore(
        person_id=person.person_id,
        score=score,
        racket_distance=racket_distance,
        in_person=in_person,
        left_distance=left_distance,
        right_distance=right_distance,
        near_wrist=near_wrist,
        near_distance=near_distance,
    )


def select_rackets(
    detections: list[BallRacketDetection], conf_min: float = RACKET_CONF_MIN
) -> list[BallRacketDetection]:
    return sorted(
        (d for d in detections if d.class_name == "racket" and d.confidence >= conf_min),
        key=lambda d: -d.confidence,
    )


def associate_frame(
    pose: PoseFrame,
    detections: list[BallRacketDetection],
    conf_min: float = RACKET_CONF_MIN,
    min_margin: float = MIN_MARGIN,
) -> dict:
    """单帧启发式关联；不确定就返回 ``UNKNOWN``（不强行分类）。"""
    base = {
        "name": "serving_player_candidate",
        "heuristic": True,
        "is_ground_truth": False,
        "decision": DECISION_UNKNOWN,
        "candidate_server_person_id": None,
        "candidate_racket_wrist": None,
        "candidate_toss_wrist": None,
        "racket_class_id": None,
        "racket_confidence": None,
        "racket_bbox_xyxy": None,
        "reason": "",
        "person_scores": [],
    }

    rackets = select_rackets(detections, conf_min=conf_min)
    if not rackets:
        base["reason"] = "no reliable racket detection"
        return base
    if not pose.persons:
        base["reason"] = "no pose person detected"
        return base

    racket = rackets[0]
    base["racket_class_id"] = racket.class_id
    base["racket_confidence"] = round(float(racket.confidence), 6)
    base["racket_bbox_xyxy"] = [round(v, 3) for v in racket.box.to_xyxy()]

    scores = [score_person_against_racket(person, racket) for person in pose.persons]
    scores.sort(key=lambda item: -item.score)
    base["person_scores"] = [item.to_dict() for item in scores]

    best = scores[0]
    if best.near_wrist is None:
        base["reason"] = "best person has no valid wrist keypoint"
        return base
    if len(scores) > 1:
        margin = best.score - scores[1].score
        if margin < min_margin:
            base["reason"] = f"ambiguous margin {margin:.3f} < {min_margin:.3f}"
            return base

    other_wrist = "right_wrist" if best.near_wrist == "left_wrist" else "left_wrist"
    other_index = RIGHT_WRIST_INDEX if other_wrist == "right_wrist" else LEFT_WRIST_INDEX
    person = next(p for p in pose.persons if p.person_id == best.person_id)
    other_keypoint = person.keypoint(other_index)
    other_valid = bool(other_keypoint and other_keypoint.valid and other_keypoint.xy)

    base["decision"] = DECISION_ASSOCIATED
    base["candidate_server_person_id"] = int(best.person_id)
    near_index = LEFT_WRIST_INDEX if best.near_wrist == "left_wrist" else RIGHT_WRIST_INDEX
    near_keypoint = person.keypoint(near_index)
    base["candidate_racket_wrist"] = {
        "wrist": best.near_wrist,
        "keypoint_index": near_index,
        "xy": [round(float(near_keypoint.xy[0]), 3), round(float(near_keypoint.xy[1]), 3)],
        "distance_px": round(float(best.near_distance), 3),
    }
    base["candidate_toss_wrist"] = (
        {
            "wrist": other_wrist,
            "keypoint_index": other_index,
            "xy": [round(float(other_keypoint.xy[0]), 3), round(float(other_keypoint.xy[1]), 3)],
            "distance_px": round(
                float(best.right_distance if other_wrist == "right_wrist" else best.left_distance),
                3,
            ),
        }
        if other_valid
        else None
    )
    base["reason"] = "closest wrist to the highest-confidence racket within the same person"
    return base


# ---------------------------------------------------------------- 时序（预留）
@dataclass
class TemporalWristObservation:
    frame_index: int
    person_id: int
    racket_distance_px: float

    def to_dict(self) -> dict:
        return {
            "frame_index": int(self.frame_index),
            "person_id": int(self.person_id),
            "racket_distance_px": round(float(self.racket_distance_px), 3),
        }


@dataclass
class TemporalAssociation:
    """连续帧上的稳定关系（静态 30 帧 benchmark 不构成正式时序判定）。"""

    window: int
    frames_considered: int
    left_median_px: float | None
    right_median_px: float | None
    racket_wrist: str | None
    toss_wrist: str | None
    decided: bool
    reason: str
    observations: dict[str, list[TemporalWristObservation]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name": "temporal_wrist_identity",
            "heuristic": True,
            "is_ground_truth": False,
            "window": int(self.window),
            "frames_considered": int(self.frames_considered),
            "left_median_distance_px": None
            if self.left_median_px is None
            else round(float(self.left_median_px), 3),
            "right_median_distance_px": None
            if self.right_median_px is None
            else round(float(self.right_median_px), 3),
            "racket_wrist": self.racket_wrist,
            "toss_wrist": self.toss_wrist,
            "decided": bool(self.decided),
            "reason": self.reason,
            "observations": {
                key: [obs.to_dict() for obs in value] for key, value in self.observations.items()
            },
        }


def temporal_association(
    observations: list[tuple[int, int, str, float]],
    window: int = DEFAULT_WINDOW,
    min_frames: int = 3,
    margin_ratio: float = 1.25,
) -> TemporalAssociation:
    """在最近 ``window`` 个有效观测上比较两只手腕到 racket 的中位距离。"""
    recent = observations[-window:] if window > 0 else list(observations)
    by_wrist: dict[str, list[TemporalWristObservation]] = {"left_wrist": [], "right_wrist": []}
    for frame_index, person_id, wrist, distance in recent:
        if wrist not in by_wrist:
            continue
        by_wrist[wrist].append(
            TemporalWristObservation(int(frame_index), int(person_id), float(distance))
        )

    left_values = [obs.racket_distance_px for obs in by_wrist["left_wrist"]]
    right_values = [obs.racket_distance_px for obs in by_wrist["right_wrist"]]
    left_median = statistics.median(left_values) if left_values else None
    right_median = statistics.median(right_values) if right_values else None

    result = TemporalAssociation(
        window=int(window),
        frames_considered=len(recent),
        left_median_px=left_median,
        right_median_px=right_median,
        racket_wrist=None,
        toss_wrist=None,
        decided=False,
        reason="",
        observations=by_wrist,
    )
    if (
        left_median is None
        or right_median is None
        or len(left_values) < min_frames
        or len(right_values) < min_frames
    ):
        result.reason = (
            f"insufficient valid frames (left={len(left_values)}, right={len(right_values)}, "
            f"min_frames={min_frames})"
        )
        return result

    smaller, larger = min(left_median, right_median), max(left_median, right_median)
    if smaller <= 0 or larger / max(smaller, 1e-6) < margin_ratio:
        result.reason = (
            f"medians too close (left={left_median:.2f}, right={right_median:.2f}, "
            f"ratio<{margin_ratio})"
        )
        return result

    result.racket_wrist = "left_wrist" if left_median < right_median else "right_wrist"
    result.toss_wrist = "right_wrist" if result.racket_wrist == "left_wrist" else "left_wrist"
    result.decided = True
    result.reason = f"median distance ratio {larger / smaller:.2f} >= {margin_ratio}"
    return result


# ================================================================ 绘制
def _split_detections(detections: list[BallRacketDetection]):
    return (
        [d for d in detections if d.class_id == 0],
        [d for d in detections if d.class_id == 1],
    )


def render_ball_racket_panel(image, detections: list[BallRacketDetection], title: str, conf: float):
    """只画 ball / racket bbox（AF 的 ball_racket_only 视图）。"""
    canvas = image.copy()
    balls, rackets = _split_detections(detections)
    for det in balls:
        draw_box(canvas, det.box, label=f"ball {det.confidence:.2f}", color=COLOR_BALL, thickness=2)
    for det in rackets:
        draw_box(
            canvas, det.box, label=f"racket {det.confidence:.2f}", color=COLOR_RACKET, thickness=2
        )
    draw_legend(
        canvas,
        [(f"ball x{len(balls)}", COLOR_BALL), (f"racket x{len(rackets)}", COLOR_RACKET)],
    )
    draw_label(canvas, title, (8, canvas.shape[0] - 26), (40, 40, 40), scale=0.5)
    draw_label(canvas, f"conf={conf}", (8, 26), (40, 40, 40), scale=0.5)
    return canvas


def render_pose_panel(image, pose_frame, title: str, wrist_conf_min: float):
    """只画 Pose：person bbox + 骨架 + 两只手腕点（AF 的 pose_only 视图）。"""
    canvas = image.copy()
    for person in pose_frame.persons:
        draw_pose_person(canvas, person, color=COLOR_PERSON)
        left = person.left_wrist
        right = person.right_wrist
        if left and left.valid and left.xy:
            draw_wrist(canvas, left.xy, COLOR_WRIST_L, label=f"L {left.confidence:.2f}")
        if right and right.valid and right.xy:
            draw_wrist(canvas, right.xy, COLOR_WRIST_R, label=f"R {right.confidence:.2f}")
    draw_legend(
        canvas,
        [
            (f"person x{pose_frame.person_count}", COLOR_PERSON),
            ("left_wrist (kp 9)", COLOR_WRIST_L),
            ("right_wrist (kp 10)", COLOR_WRIST_R),
        ],
    )
    draw_label(canvas, title, (8, canvas.shape[0] - 26), (40, 40, 40), scale=0.5)
    draw_label(canvas, f"wrist_conf>={wrist_conf_min}", (8, 26), (40, 40, 40), scale=0.5)
    return canvas


def render_fusion_panel(
    image,
    detections: list[BallRacketDetection],
    pose_frame,
    association: dict,
    title: str,
    conf: float,
):
    """ball bbox + racket bbox + 淡色 person + 手腕点 + 候选身份标注。"""
    canvas = image.copy()
    for person in pose_frame.persons:
        draw_pose_person(canvas, person, color=COLOR_PERSON)

    balls, rackets = _split_detections(detections)
    for det in balls:
        draw_box(canvas, det.box, label=f"ball {det.confidence:.2f}", color=COLOR_BALL, thickness=2)
    for det in rackets:
        draw_box(
            canvas, det.box, label=f"racket {det.confidence:.2f}", color=COLOR_RACKET, thickness=2
        )

    candidate_racket = association.get("candidate_racket_wrist")
    candidate_toss = association.get("candidate_toss_wrist")
    server_id = association.get("candidate_server_person_id")

    for person in pose_frame.persons:
        for index, fallback_color in (
            (LEFT_WRIST_INDEX, COLOR_WRIST_L),
            (RIGHT_WRIST_INDEX, COLOR_WRIST_R),
        ):
            keypoint = person.keypoint(index)
            if not keypoint or not keypoint.valid or keypoint.xy is None:
                continue
            role = None
            if person.person_id == server_id:
                if candidate_racket and candidate_racket["keypoint_index"] == index:
                    role = "racket"
                elif candidate_toss and candidate_toss["keypoint_index"] == index:
                    role = "toss"
            if role == "racket":
                draw_wrist(
                    canvas,
                    keypoint.xy,
                    COLOR_RACKET_WRIST,
                    label=f"candidate racket wrist {keypoint.confidence:.2f}",
                    radius=7,
                )
            elif role == "toss":
                draw_wrist(
                    canvas,
                    keypoint.xy,
                    COLOR_TOSS_WRIST,
                    label=f"candidate toss wrist {keypoint.confidence:.2f}",
                    radius=7,
                )
            else:
                side = "L" if index == LEFT_WRIST_INDEX else "R"
                draw_wrist(
                    canvas,
                    keypoint.xy,
                    fallback_color,
                    label=f"{side} {keypoint.confidence:.2f}",
                    radius=5,
                )

    draw_legend(
        canvas,
        [
            (f"ball x{len(balls)} (conf {conf})", COLOR_BALL),
            (f"racket x{len(rackets)}", COLOR_RACKET),
            ("person (pose)", COLOR_PERSON),
            ("left_wrist kp9", COLOR_WRIST_L),
            ("right_wrist kp10", COLOR_WRIST_R),
            ("candidate racket wrist (HEURISTIC)", COLOR_RACKET_WRIST),
            ("candidate toss wrist (HEURISTIC)", COLOR_TOSS_WRIST),
        ],
    )
    reason = association.get("reason", "")
    decision = association.get("decision", "")
    draw_label(canvas, title, (8, canvas.shape[0] - 26), (40, 40, 40), scale=0.5)
    draw_label(
        canvas,
        decision + (" | " + reason if reason else ""),
        (8, 48),
        (60, 60, 60),
        scale=0.45,
    )
    return canvas


def _downscale(image, width: int = DISPLAY_WIDTH):
    import cv2

    height, current_width = image.shape[:2]
    if current_width <= width:
        return image
    scale = width / float(current_width)
    return cv2.resize(image, (width, int(round(height * scale))), interpolation=cv2.INTER_AREA)


# ================================================================ 主流程
@dataclass
class FrameResult:
    image_id: str
    image_path: str
    image_width: int
    image_height: int
    stage_hint: str
    session_id: str
    report: dict = field(default_factory=dict)
    display: dict = field(default_factory=dict)
    association: dict = field(default_factory=dict)
    pose: dict = field(default_factory=dict)
    v2_keys: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "image_id": self.image_id,
            "image_path": self.image_path,
            "image_width": self.image_width,
            "image_height": self.image_height,
            "stage_hint": self.stage_hint,
            "session_id": self.session_id,
            "detections_conf015": self.report,
            "detections_conf025_display": self.display,
            "pose": self.pose,
            "association": self.association,
            "perception_result_v2_keys": self.v2_keys,
        }


def summarize_frames(frames: list[FrameResult]) -> dict:
    """统计 BNDSTT 30 的检测/姿态覆盖情况（AL 的失败分类）。"""
    ball_frames = racket_frames = both_frames = 0
    person_frames = 0
    person_total = 0
    both_wrist = one_wrist = no_wrist = 0
    unknown = 0
    associated = 0
    failures: dict[str, list[str]] = {
        "no_ball": [],
        "no_racket": [],
        "no_person": [],
        "no_valid_wrist": [],
        "association_unknown": [],
    }
    for frame in frames:
        balls = [d for d in frame.report["detections"] if d["class_name"] == "ball"]
        rackets = [d for d in frame.report["detections"] if d["class_name"] == "racket"]
        has_ball, has_racket = bool(balls), bool(rackets)
        ball_frames += int(has_ball)
        racket_frames += int(has_racket)
        both_frames += int(has_ball and has_racket)
        pose = frame.pose
        person_frames += int(pose["person_count"] > 0)
        person_total += pose["person_count"]
        both_wrist += pose["both_wrists_valid"]
        one_wrist += pose["one_wrist_valid"]
        no_wrist += pose["no_wrist_valid"]
        if frame.association.get("decision") == DECISION_ASSOCIATED:
            associated += 1
        else:
            unknown += 1
            failures["association_unknown"].append(frame.image_id)
        if not has_ball:
            failures["no_ball"].append(frame.image_id)
        if not has_racket:
            failures["no_racket"].append(frame.image_id)
        if pose["person_count"] == 0:
            failures["no_person"].append(frame.image_id)
        if pose["both_wrists_valid"] == 0:
            failures["no_valid_wrist"].append(frame.image_id)
    return {
        "frames": len(frames),
        "ball_detected_frames": ball_frames,
        "racket_detected_frames": racket_frames,
        "both_detected_frames": both_frames,
        "pose_person_detected_frames": person_frames,
        "pose_person_total": person_total,
        "both_wrists_valid_persons": both_wrist,
        "one_wrist_valid_persons": one_wrist,
        "no_wrist_valid_persons": no_wrist,
        "association_associated_frames": associated,
        "association_unknown_frames": unknown,
        "failure_images": failures,
        "class_names": list(CLASS_NAMES),
    }


def run_fusion_demo(
    weights: str | Path | None = None,
    pose_weights: str | Path | None = None,
    manifest: Path | None = None,
    out_dir: Path | None = None,
    device: str | int = 0,
    imgsz: int = INFER_IMGSZ,
    conf_report: float = INFER_CONF_REPORT,
    conf_display: float = INFER_CONF_DISPLAY,
    iou: float = INFER_IOU,
    wrist_conf_min: float = WRIST_CONF_MIN,
    limit: int | None = None,
) -> dict:
    """对固定 30 帧跑检测器 A + Pose 并输出全部可视化与 JSON。"""
    import cv2

    from .bndstt_benchmark import load_benchmark

    rows = load_benchmark(manifest)
    if limit:
        rows = rows[:limit]
    out = Path(out_dir) if out_dir is not None else PATHS.fusion_dir
    out.mkdir(parents=True, exist_ok=True)

    detector = load_detector(weights, device=device)
    pose_model = load_pose_model(pose_weights, device=device)

    frames: list[FrameResult] = []
    panel_fusion, panel_br, panel_pose = [], [], []
    report_lines: list[str] = []
    display_lines: list[str] = []

    for index, row in enumerate(rows, start=1):
        image_path = Path(row["image_path"])
        image = read_image_robust(image_path)
        if image is None:
            raise ValueError(f"cannot read benchmark image: {image_path}")
        height, width = image.shape[:2]

        report_dets, _ = detect_ball_racket(
            detector, image, conf=conf_report, iou=iou, imgsz=imgsz, device=device
        )
        display_dets = [d for d in report_dets if d.confidence >= conf_display]
        pose_frame = infer_pose(
            pose_model,
            image,
            conf=0.25,
            imgsz=imgsz,
            device=device,
            wrist_conf_min=wrist_conf_min,
        )
        association = associate_frame(pose_frame, report_dets)

        v2 = PerceptionResultV2(
            image_path=str(image_path),
            image_width=width,
            image_height=height,
            ball_racket_detections=report_dets,
            pose_persons=[
                PosePersonLite(
                    person_id=person.person_id,
                    bbox_xyxy=list(person.bbox_xyxy),
                    confidence=person.person_confidence,
                    left_wrist=person.to_dict()["left_wrist"],
                    right_wrist=person.to_dict()["right_wrist"],
                )
                for person in pose_frame.persons
            ],
            wrists=pose_frame.wrist_records(),
            association=association,
        )

        result = FrameResult(
            image_id=row["image_id"],
            image_path=str(image_path),
            image_width=width,
            image_height=height,
            stage_hint=row.get("stage_hint", ""),
            session_id=row.get("session_id", ""),
            report={"conf": conf_report, "detections": [d.to_dict() for d in report_dets]},
            display={"conf": conf_display, "detections": [d.to_dict() for d in display_dets]},
            pose=pose_frame.to_dict(),
            association=association,
            v2_keys=sorted(v2.to_dict().keys()),
        )
        frames.append(result)

        title = f"#{index:02d} {Path(row['image_id']).name}"
        fusion_panel = render_fusion_panel(
            image, report_dets, pose_frame, association, title, conf_report
        )
        br_panel = render_ball_racket_panel(image, report_dets, title, conf_report)
        pose_panel = render_pose_panel(image, pose_frame, title, wrist_conf_min)

        stem = Path(row["image_id"]).name
        write_image_robust(out / f"fusion_{index:02d}_{stem}.jpg", fusion_panel)
        write_image_robust(out / f"ball_racket_{index:02d}_{stem}.jpg", br_panel)
        write_image_robust(out / f"pose_{index:02d}_{stem}.jpg", pose_panel)

        panel_fusion.append(_downscale(fusion_panel))
        panel_br.append(_downscale(br_panel))
        panel_pose.append(_downscale(pose_panel))
        report_lines.append(json.dumps(result.to_dict()["detections_conf015"], ensure_ascii=False))
        display_lines.append(
            json.dumps(result.to_dict()["detections_conf025_display"], ensure_ascii=False)
        )
        n_balls = sum(1 for d in report_dets if d.class_id == 0)
        n_rackets = sum(1 for d in report_dets if d.class_id == 1)
        print(
            f"[{index:02d}/{len(rows)}] {stem} balls={n_balls} rackets={n_rackets} "
            f"persons={pose_frame.person_count} decision={association.get('decision')}"
        )

    newline = chr(10)
    (out / "detections_conf015.jsonl").write_text(
        newline.join(report_lines) + newline, encoding="utf-8"
    )
    (out / "detections_conf025_display.jsonl").write_text(
        newline.join(display_lines) + newline, encoding="utf-8"
    )
    (out / "fusion_results.json").write_text(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "pose_wrist_conf_min": wrist_conf_min,
                "note": "association 为 HEURISTIC 候选，不是 Ground Truth",
                "frames": [frame.to_dict() for frame in frames],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    write_image_robust(out / "fusion_contact_sheet_30.jpg", contact_sheet(panel_fusion, columns=6))
    write_image_robust(out / "ball_racket_only_30.jpg", contact_sheet(panel_br, columns=6))
    write_image_robust(out / "pose_only_30.jpg", contact_sheet(panel_pose, columns=6))

    summary = summarize_frames(frames)
    summary.update(
        {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "weights": str(weights) if weights else str(PATHS.model_out_dir / "best.pt"),
            "pose_weights": str(pose_weights) if pose_weights else str(PATHS.pose_weights_path),
            "conf_report": conf_report,
            "conf_display": conf_display,
            "wrist_conf_min": wrist_conf_min,
            "out_dir": str(out),
        }
    )
    (out / "fusion_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="BNDSTT 30 帧 ball+racket / pose 联合可视化")
    parser.add_argument("--weights", type=Path, default=None)
    parser.add_argument("--pose-weights", type=Path, default=None)
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--device", default="0")
    parser.add_argument("--limit", type=int, default=None, help="只跑前 N 张（调试用）")
    args = parser.parse_args(argv)

    summary = run_fusion_demo(
        weights=args.weights,
        pose_weights=args.pose_weights,
        manifest=args.manifest,
        out_dir=args.out_dir,
        device=args.device,
        limit=args.limit,
    )
    printable = {k: v for k, v in summary.items() if k != "failure_images"}
    print(json.dumps(printable, ensure_ascii=False, indent=2))
    return 0


__all__ = [
    "CONTAINMENT_BONUS",
    "DECISION_ASSOCIATED",
    "DECISION_UNKNOWN",
    "DEFAULT_WINDOW",
    "MIN_MARGIN",
    "PersonScore",
    "RACKET_CONF_MIN",
    "TemporalAssociation",
    "TemporalWristObservation",
    "associate_frame",
    "render_ball_racket_panel",
    "render_fusion_panel",
    "render_pose_panel",
    "run_fusion_demo",
    "score_person_against_racket",
    "select_rackets",
    "summarize_frames",
    "temporal_association",
]


if __name__ == "__main__":  # pragma: no cover
    import sys

    sys.exit(main())
