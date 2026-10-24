# INPUT / OUTPUT PROTOCOL (给 C++ 集成)

## 输入
- 名称: images
- 形状: [1, 3, 960, 960]
- 类型: float32
- 语义: Gray8 复制成 3 通道 -> letterbox(114 填充) -> /255
  scale = min(960/W, 960/H); pad_x=(960-round(W*scale))//2; pad_y 同理

## 输出
- 名称: output0
- 形状: [1, 7, 18900]
- 通道: 0..3 = cx,cy,w,h (960 输入空间像素); 4..6 = ball,hand,racket 的 sigmoid 分数
- 图内无 NMS, 调用方按类做 NMS (IoU 0.50, max_det 30-60)

## 坐标还原
x1 = (cx - w/2 - pad_x) / scale ; y1 = (cy - h/2 - pad_y) / scale
x2 = (cx + w/2 - pad_x) / scale ; y2 = (cy + h/2 - pad_y) / scale
单位为原图像素, 原点左上, y 向下。

## 类别
0 = ball, 1 = hand, 2 = racket (固定)

## 阈值建议
统一 conf = 0.25; 分门限可用 ball 0.20 / hand 0.25 / racket 0.25

## 与现有 DetectorBackend 的兼容性
- 现 V2.4 统一模式假定 3 类图且 id 为 0=ball,1=hand,2=racket —— 与本模型一致
- 但现有统一 ONNX 是 960 输入, 本模型同为 960, 输入尺寸一致
- 未改动任何 C++ 文件; 替换前需在目标机复测延迟 (CPU 约 49 ms/帧)
