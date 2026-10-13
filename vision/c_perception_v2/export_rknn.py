"""RKNN Toolkit2 导出脚本（目标 rk3576）。

状态：RKNN_PREPARED_NOT_EXECUTED
  本机未安装 rknn-toolkit2（PyPI 镜像也没有该包；Rockchip 只发布在其官方 index）。
  按任务要求，不擅自安装来源不明确的软件，因此只提供脚本与说明。

在装有 rknn-toolkit2 的机器上执行：

    pip install rknn-toolkit2 -i https://pypi.org/simple        # 或 Rockchip 官方 wheel
    python vision/c_perception_v2/export_rknn.py --model yolo   --precision fp16
    python vision/c_perception_v2/export_rknn.py --model pose   --precision fp16
    python vision/c_perception_v2/export_rknn.py --model balltrack --precision fp16
    # INT8 需要校准集（见 calibration_manifest.txt）
    python vision/c_perception_v2/export_rknn.py --model yolo   --precision int8

注意：
  * 没有 AFH03 真机，因此**任何情况下都不得**写 BOARD VERIFIED / RK3576 REAL-TIME VERIFIED；
    只能写 RKNN CONVERSION VERIFIED ON HOST。
  * 该脚本不训练、不修改 ONNX、不修改任何权重。
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
ONNX_DIR = REPO / "artifacts" / "files" / "reports" / "ONNX_EXPORT_V1" / "models"
OUT_DIR = REPO / "artifacts" / "files" / "reports" / "RKNN_EXPORT_V1"
CALIB_MANIFEST = REPO / "vision" / "c_perception_v2" / "calibration_manifest.txt"

TARGET_PLATFORM = "rk3576"

MODELS = {
    "yolo": {
        "onnx": "ball_racket_yolov8n_v1.onnx",
        "rknn": "ball_racket_yolov8n_v1",
        "input_shape": [1, 3, 640, 640],
        "mean_values": [[0, 0, 0]],
        "std_values": [[255, 255, 255]],
        "quantized_dtype": "w8a8",
        "quantized_algorithm": "normal",
        "outputs": ["output0"],
    },
    "pose": {
        "onnx": "yolov8n_pose.onnx",
        "rknn": "yolov8n_pose",
        "input_shape": [1, 3, 640, 640],
        "mean_values": [[0, 0, 0]],
        "std_values": [[255, 255, 255]],
        "quantized_dtype": "w8a8",
        "quantized_algorithm": "normal",
        "outputs": ["output0"],
    },
    "balltrack": {
        "onnx": "balltrack_tracknetv3.onnx",
        "rknn": "balltrack_tracknetv3",
        "input_shape": [1, 15, 288, 512],
        # 模型输入已是 0..1 的 float（训练时 /255 已在外部完成），因此 mean=0, std=1
        "mean_values": [[0] * 15],
        "std_values": [[1] * 15],
        "quantized_dtype": "w8a8",
        "quantized_algorithm": "normal",
        "outputs": ["heatmaps"],
        "warning": "15-channel input + sigmoid heatmap; INT8 量化风险较高，建议先只做 FP16",
    },
}


def build_dataset_txt(calib_dir: pathlib.Path, list_path: pathlib.Path) -> int:
    """生成 rknn.config(dataset=...) 需要的图片列表。"""
    images = sorted(p for p in calib_dir.rglob("*.jpg"))
    list_path.write_text(chr(10).join(str(p) for p in images) + chr(10), encoding="utf-8")
    return len(images)


def convert(name: str, precision: str) -> dict:
    try:
        from rknn.api import RKNN
    except ImportError:
        print("rknn-toolkit2 is not installed in this environment.")
        print("status: RKNN_PREPARED_NOT_EXECUTED")
        print("see vision/c_perception_v2/RKNN_DEPLOYMENT_GUIDE.md")
        return {"status": "RKNN_PREPARED_NOT_EXECUTED", "reason": "rknn-toolkit2 missing"}

    spec = MODELS[name]
    onnx_path = ONNX_DIR / spec["onnx"]
    if not onnx_path.is_file():
        raise SystemExit("missing ONNX: " + str(onnx_path))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    suffix = "fp16" if precision == "fp16" else "int8"
    out_path = OUT_DIR / (spec["rknn"] + "_" + suffix + ".rknn")

    rknn = RKNN(verbose=True)
    rknn.config(
        mean_values=spec["mean_values"],
        std_values=spec["std_values"],
        target_platform=TARGET_PLATFORM,
        quantized_dtype=spec["quantized_dtype"],
        quantized_algorithm=spec["quantized_algorithm"],
        optimization_level=3,
    )
    ret = rknn.load_onnx(model=str(onnx_path), outputs=spec["outputs"])
    if ret != 0:
        raise SystemExit("load_onnx failed: " + str(ret))

    if precision == "int8":
        n = build_dataset_txt(REPO / "artifacts/files/reports/RKNN_EXPORT_V1/calibration",
                              OUT_DIR / "dataset.txt")
        print("calibration images:", n)
        ret = rknn.build(do_quantization=True, dataset=str(OUT_DIR / "dataset.txt"))
    else:
        ret = rknn.build(do_quantization=False)
    if ret != 0:
        raise SystemExit("build failed: " + str(ret))

    ret = rknn.export_rknn(str(out_path))
    if ret != 0:
        raise SystemExit("export_rknn failed: " + str(ret))

    # 主机侧精度分析（不是板端验证）
    try:
        rknn.accuracy_analysis(inputs=[str(ONNX_DIR / spec["onnx"])],
                               output_dir=str(OUT_DIR / ("accuracy_" + suffix)))
    except Exception as exc:
        print("accuracy_analysis skipped:", type(exc).__name__, exc)

    rknn.release()
    return {"status": "RKNN_CONVERSION_VERIFIED_ON_HOST", "precision": precision,
            "rknn": str(out_path), "bytes": out_path.stat().st_size,
            "warning": "no RK3576 board available; NOT board verified"}


def main() -> int:
    parser = argparse.ArgumentParser(description="RKNN export for rk3576")
    parser.add_argument("--model", required=True, choices=sorted(MODELS))
    parser.add_argument("--precision", default="fp16", choices=["fp16", "int8"])
    args = parser.parse_args()
    result = convert(args.model, args.precision)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status", "").startswith("RKNN") else 1


if __name__ == "__main__":
    sys.exit(main())
