# 双目相机标定结果（2026-10-14）

- 输入：2560×720 BMP 左右拼接图，左/右眼各 1280×720。
- 棋盘：方格总数 12×9，对应内角点 11×8；单格 0.03 m。
- 标定图：36 张，成功成对使用 {len(objs)} 对；失败图见 failed.json。
- 验证图：6 张，仅用于独立检查。

- 左相机 RMS：0.415170 px
- 右相机 RMS：0.442940 px
- 双目 RMS：1.793135 px
- 标定估计基线：0.170449 m；尺量基线：0.171 m

## 验证结果
- 20261014192318.bmp: left=True, right=True, vertical RMS=0.4647493064403534 px, max=0.8975830078125 px
- 20261014193939.bmp: left=True, right=True, vertical RMS=1.054239273071289 px, max=1.5138092041015625 px
- 20261014195050.bmp: left=True, right=True, vertical RMS=0.8788020610809326 px, max=1.7684326171875 px
- 20261014195110.bmp: left=True, right=True, vertical RMS=1.0109596252441406 px, max=2.01446533203125 px
- 20261014195153.bmp: left=True, right=True, vertical RMS=0.9090782403945923 px, max=1.6754913330078125 px
- 20261014195622.bmp: left=True, right=True, vertical RMS=1.0977652072906494 px, max=5.285919189453125 px

## PartV
- 原点定义：球网与球台中线交点。
- 球台中线与棋盘中线重合。
- 短边到中线距离按 0.55 m 记录。
- 已对 PartV 图片执行左右相机 solvePnP，结果在 calibration_results.json 的 partv_pnp。
- 由于“短边到中线 0.55 m”的有符号方向和棋盘坐标原点尚未明确，暂不把该假设写成最终世界变换矩阵。