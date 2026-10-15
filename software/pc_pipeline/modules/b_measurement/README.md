# B pipeline module

This is the small public-pipeline adapter for the B stereo measurement path.
It consumes same-frame `DetectionResult` ball candidates, checks the pair/eye
identity, and triangulates a valid left-camera point using the calibration file
named by `PIPELINE_B_CALIBRATION`. It intentionally does not turn a detector
box into truth: missing, mismatched, low-disparity, or invalid-depth pairs are
returned as `invalid` with a reason.

Build with `-DPIPELINE_B_MODULE_DIR=software/pc_pipeline/modules/b_measurement`.

