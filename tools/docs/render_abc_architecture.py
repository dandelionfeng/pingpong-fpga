"""Render the reviewed A/B/C architecture as native SVG and PNG; no algorithm changes."""
from __future__ import annotations

import argparse
import math
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image, ImageDraw, ImageFont


WIDTH, HEIGHT = 2400, 2320
SCALE = 2
COLORS = {
    'background': '#F6F8FC', 'ink': '#183248', 'body': '#42566A',
    'muted': '#687D90', 'border': '#D8E1EB',
    'a': '#146F78', 'a_fill': '#EAF6F6',
    'b': '#285FA9', 'b_fill': '#EDF3FD',
    'c': '#A86409', 'c_fill': '#FFF6E7',
}


class Diagram:
    def __init__(self, font_dir: Path):
        self.font_dir = font_dir
        self.image = Image.new('RGB', (WIDTH * SCALE, HEIGHT * SCALE), COLORS['background'])
        self.draw = ImageDraw.Draw(self.image)
        self.parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-labelledby="title description">',
            '<title id="title">系统架构与 A/B/C 接口</title>',
            '<desc id="description">目标系统：A 提供共用核心、图像和运动结果；B 提供球心、三维、轨迹事件和 FPGA 后四级；C 提供三类模型和独立评分。Qt 是正式显示和证据复查层，当前 B/C 叠加及板端仍待联调。真值仅进入独立评分。</desc>',
            '<style>text{font-family:"Microsoft YaHei","Noto Sans CJK SC",sans-serif} .api{font-family:"Microsoft YaHei",sans-serif}</style>',
            f'<rect width="{WIDTH}" height="{HEIGHT}" fill="{COLORS["background"]}"/>',
        ]
        self.text_checks = []

    def font(self, size: int, bold: bool = False):
        name = 'msyhbd.ttc' if bold else 'msyh.ttc'
        return ImageFont.truetype(str(self.font_dir / name), size * SCALE)

    def rect(self, x, y, w, h, fill='white', stroke=None, radius=22, width=2):
        if not (0 <= x <= x + w <= WIDTH and 0 <= y <= y + h <= HEIGHT):
            raise ValueError(f'Out-of-canvas rectangle: {(x,y,w,h)}')
        stroke = stroke or COLORS['border']
        self.draw.rounded_rectangle(tuple(v * SCALE for v in (x, y, x+w, y+h)), radius=radius*SCALE, fill=fill, outline=stroke, width=width*SCALE)
        self.parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" fill="{fill}" stroke="{stroke}" stroke-width="{width}"/>')

    def text(self, x, y, value, size=30, color=None, bold=False, max_width=None):
        color = color or COLORS['body']
        use_size = size
        font = self.font(use_size, bold)
        box = self.draw.textbbox((0,0), value, font=font)
        while max_width and (box[2]-box[0])/SCALE > max_width and use_size > 23:
            use_size -= 1
            font = self.font(use_size, bold)
            box = self.draw.textbbox((0,0), value, font=font)
        actual_width = (box[2]-box[0])/SCALE
        if max_width and actual_width > max_width:
            raise ValueError(f'Text exceeds its card: {value}')
        if x + actual_width > WIDTH-15 or y + use_size > HEIGHT-10:
            raise ValueError(f'Text outside canvas: {value}')
        self.draw.text((x*SCALE, y*SCALE), value, font=font, fill=color, anchor='lt')
        self.parts.append(f'<text x="{x}" y="{y}" font-size="{use_size}" font-weight="{700 if bold else 400}" fill="{color}" dominant-baseline="hanging">{escape(value)}</text>')
        self.text_checks.append({'text': value, 'size': use_size, 'width': round(actual_width,1)})

    def arrow(self, points, color=None, width=5):
        color = color or COLORS['a']
        for x,y in points:
            if not (0 <= x <= WIDTH and 0 <= y <= HEIGHT):
                raise ValueError('Arrow outside canvas')
        scaled = [(x*SCALE,y*SCALE) for x,y in points]
        self.draw.line(scaled, fill=color, width=width*SCALE, joint='curve')
        x,y = points[-1]
        previous = next(p for p in reversed(points[:-1]) if p != points[-1])
        dx,dy = x-previous[0],y-previous[1]
        length = math.hypot(dx,dy)
        ux,uy = dx/length,dy/length
        tip = [(x,y),(x-19*ux+9*uy,y-19*uy-9*ux),(x-19*ux-9*uy,y-19*uy+9*ux)]
        self.draw.polygon([(a*SCALE,b*SCALE) for a,b in tip], fill=color)
        path = ' '.join(f'{a},{b}' for a,b in points)
        triangle = ' '.join(f'{a:.2f},{b:.2f}' for a,b in tip)
        self.parts.append(f'<polyline points="{path}" fill="none" stroke="{color}" stroke-width="{width}" stroke-linejoin="round"/><polygon points="{triangle}" fill="{color}"/>')

    def label(self, x, y, value, color=None, size=29):
        font = self.font(size, True)
        box = self.draw.textbbox((0,0), value, font=font)
        w = math.ceil((box[2]-box[0])/SCALE)+26
        self.rect(x-13,y-8,w,size+23,fill=COLORS['background'],stroke=COLORS['background'],radius=10)
        self.text(x,y,value,size,color or COLORS['a'],bold=True)

    def card(self, x,y,w,h,role,title,lines,status=None):
        self.rect(x,y,w,h,fill=COLORS[f'{role}_fill'],stroke=COLORS[role],width=3)
        self.text(x+28,y+25,title,38,COLORS[role],True,w-56)
        pos=y+89
        for line in lines:
            self.text(x+28,pos,line,30,max_width=w-56)
            pos+=43
        if status:
            self.text(x+28,y+h-43,status,25,COLORS['muted'],max_width=w-56)

    def save(self, directory: Path):
        directory.mkdir(parents=True,exist_ok=True)
        stem='ABC系统架构与接口_20261008'
        png=directory/f'{stem}.png'
        svg=directory/f'{stem}.svg'
        self.image.resize((WIDTH,HEIGHT),Image.Resampling.LANCZOS).save(png,optimize=True)
        svg.write_text('\n'.join(self.parts+['</svg>'])+'\n',encoding='utf-8')
        return png,svg


def render(output: Path, font_dir: Path):
    d=Diagram(font_dir)
    d.text(70,48,'系统架构与 A / B / C 接口',59,COLORS['ink'],True)
    d.text(70,126,'正式目标：AFH03（RK3576J + PH1A90SEG324） ·  共用 C++ 核心  ·  Qt 显示与证据回放',32)
    d.rect(70,183,2260,65,fill='#FFF2D6',stroke='#EDD29A',radius=14)
    d.text(94,199,'目标架构图：箭头表示交付方向；A 基础链路可运行，B/C 真实模块、结果叠加与设备绑定仍需联调。',29,COLORS['ink'],max_width=2210)

    d.rect(70,291,2260,151)
    d.text(99,312,'输入可切换，后续测量逻辑共用',34,COLORS['ink'],True)
    d.text(99,366,'当前 PC：YUY2 / 双 GRAY8 文件与清单',31,COLORS['a'])
    d.text(1200,366,'整机目标：同步双 OV9281 → USB3 / V4L2',31,COLORS['a'])
    d.arrow([(1200,442),(1200,514)])

    d.card(70,514,2260,239,'a','A · 共用运行核心：输入、缓存、运动后端、异步调度与模块注册',[
        'FramePair：双眼 1280×720 原图 + 640×360 搜索图；保存 8 对原图及同帧 ROI 上下文',
        'FrameSource / MotionBackend / DetectorScheduler / Registry；统一帧号、采样时间、版本和错误',
        'PC：七级 CPU 整数参考 / 模拟 DMA；整机：PCIe FPGA 后端。B/C 模块由同一核心调用。',
    ])
    d.arrow([(570,753),(570,863)],COLORS['b'])
    d.label(335,792,'I1  A → B：原图 + Mask + 帧身份',COLORS['b'])
    d.arrow([(1810,753),(1810,863)],COLORS['c'])
    d.label(1465,792,'I2  A → C：DetectorContext',COLORS['c'])

    d.card(70,863,1020,302,'b','B · 球心、三维、跟踪与事件',[
        'MeasurementModule::process(...) → Json',
        '接收 FramePair、MotionResult、同帧类别框',
        '原图 ROI 求球心 → 标定 / 三维 → 轨迹 / 事件',
        '输出左右球心、三维米制、事件、质量与版本',
    ],'待接 B 实际库并验收；观测 / 滤波 / 预测分栏')
    d.card(1290,863,1040,302,'c','C · ball / hand / racket 三类识别',[
        'DetectorBackend::infer(context, stop, timeoutMs)',
        '接收原眼灰度与身份；自行预处理和坐标还原',
        'DetectionResult：类别框、置信度、来源帧',
        '交付实际推理库、模型引用、配置与后处理',
    ],'PC 实际模型 → RKNN / NPU；与框回放分开验收')

    # B/C return data to A. C semantics are dispatched onward to B, not a direct call.
    d.arrow([(575,1165),(575,1310),(990,1310)],COLORS['b'])
    d.label(400,1232,'I4  B → A：测量 JSON + 标定配置',COLORS['b'],27)
    d.arrow([(1810,1165),(1810,1310),(1400,1310)],COLORS['c'])
    d.label(1515,1232,'I3  C → A：DetectionResult',COLORS['c'],27)
    d.rect(990,1269,410,124,fill=COLORS['a_fill'],stroke=COLORS['a'],width=3)
    d.text(1018,1293,'A · 对齐、转交与记录',29,COLORS['a'],True,max_width=354)
    d.text(1018,1336,'按来源 pair_id / eye 绑定',26,max_width=354)
    d.arrow([(1180,1269),(1180,1008),(1090,1008)],COLORS['c'])
    d.label(1110,1120,'I3',COLORS['c'],27)
    d.text(1099,1166,'同帧框',25,COLORS['c'])
    d.text(1099,1197,'交给 B',25,COLORS['c'])

    d.arrow([(1105,1393),(1105,1445),(865,1445),(865,1530)])
    d.label(220,1450,'同一来源帧的图像、Mask、测量与检测结果',size=27)
    d.arrow([(1320,1393),(1320,1445),(1400,1445),(1400,1530)],COLORS['c'])
    d.label(1430,1450,'I5  A → C：运行结果 / 证据',COLORS['c'],27)
    d.card(70,1530,1020,243,'a','A · Qt 显示 / 证据回放 + CLI 导出',[
        '现有：左右回放、阶段切换、ROI 检查、导出',
        '待接：B 球心 / 轨迹 / 事件叠加、真实 C 模型',
        '正式目标：AFH03 HDMI 显示；关键片段复查',
    ])
    d.card(1290,1530,1040,243,'c','C · 独立评分（离线验收）',[
        '只在评分器加载独立 truth / 人工参考标签',
        '比较检测、球心、三维、轨迹与事件误差',
        '输出评分报告与失败样例 → A / B / C',
    ])
    d.text(1318,1741,'truth 不进入被测算法；测试输入与答案分开保存',25,COLORS['c'],max_width=980)

    d.text(70,1830,'设备后端：A / B 的 FPGA 边界（接通后替换软件运动前端）',34,COLORS['ink'],True)
    d.rect(70,1898,1020,150,fill=COLORS['a_fill'],stroke=COLORS['a'],width=3)
    d.text(98,1918,'A RTL · Gaussian → 同眼帧差 → 阈值',32,COLORS['a'],True,max_width=965)
    d.text(98,1968,'输入：A 经 PCIe 发送的双眼 640×360 搜索图',28,max_width=965)
    d.text(98,2006,'I6 输出：1 bit 阈值像素 + valid/ready + 帧身份',28,max_width=965)
    d.arrow([(1090,1963),(1290,1963)],COLORS['b'])
    d.label(1142,1912,'I6',COLORS['b'])
    d.rect(1290,1898,1040,150,fill=COLORS['b_fill'],stroke=COLORS['b'],width=3)
    d.text(1318,1918,'B RTL · 后四级形态学 + 1 bit Mask 打包',32,COLORS['b'],True,max_width=985)
    d.text(1318,1968,'腐蚀 → 膨胀 → 膨胀 → 腐蚀；每对 57,600 字节',28,max_width=985)
    d.text(1318,2006,'I7 返回 A：双 Mask / 元数据 → PCIe 接收 / 解包',28,max_width=985)
    d.arrow([(2330,1975),(2367,1975),(2367,682),(2330,682)],COLORS['b'],4)
    d.label(2341,1800,'I7',COLORS['b'],24)

    d.rect(70,2100,2260,176,fill='white',stroke=COLORS['border'],radius=16)
    d.text(95,2120,'接库：B 提供 pipeline_b_module / register_b_module；C 提供 pipeline_c_module / register_c_module。',27,max_width=2210)
    d.text(95,2160,'构建：PIPELINE_B_MODULE_DIR / PIPELINE_C_MODULE_DIR；双方链接 pipeline_module_api。',27,max_width=2210)
    d.text(95,2200,'共同规则：pair_id、眼别、采样时间、reference_id、配置 / 标定 / 模型版本贯穿；三维单位为米。',27,max_width=2210)
    d.text(95,2240,'范围：软件接口 a-motion-v1-draft；硬件绑定待 SDK / 复核；单目复制素材仅验证二维和链路。',26,max_width=2210)
    return d,d.save(output)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=Path(__file__).resolve().parents[2]/'docs/architecture')
    parser.add_argument('--font-dir',type=Path,default=Path('C:/Windows/Fonts'))
    args=parser.parse_args()
    diagram,paths=render(args.output,args.font_dir)
    print(f'Validated {len(diagram.text_checks)} text labels; native SVG and PNG:')
    for path in paths:print(path)


if __name__=='__main__':
    main()
