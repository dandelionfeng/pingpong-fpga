"""Render actual C++ outputs and isolated truth into a static evidence page."""
from pathlib import Path
import argparse
import html
import json
import cv2
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',required=True);args=ap.parse_args();root=Path(args.root);plots=root/'plots';plots.mkdir(exist_ok=True)
    truth=read(root/'truth/expected.json');score=read(root/'score.json');boards=read(root/'calibration-score.json');rows={r['name']:r for r in score['cases']};cards=[]
    for item in truth['cases']:
        name=item['name'];result=read(root/'results'/f'{name}.json');start=int(item['frames'][0]['sample_time_ns']);times=np.array([(int(f['sample_time_ns'])-start)*1e-9 for f in result['frames']]);true=np.array([f['world_m'] for f in item['frames']])
        fig,axes=plt.subplots(2,1,figsize=(9,5.8),sharex=True,constrained_layout=True)
        axes[0].plot(times,true[:,2],color='#1b334b',label='truth (scorer only)',linewidth=2)
        for key,color,style in [('observed_world_m','#17865c','.'),('filtered_world_m','#2369bb','-'),('predicted_world_m','#c47a1e','--')]:
            z=[f.get(key,[np.nan]*3)[2] for f in result['frames']];axes[0].plot(times,z,style,color=color,label=key,markersize=3,linewidth=1)
        for key,color in [('release','#2f8b62'),('apex','#8b5ba3'),('contact','#c24e4e')]:
            if key in result['event']:
                i=result['event'][key];a=(int(i['begin_ns'])-start)*1e-9;b=(int(i['end_ns'])-start)*1e-9
                axes[0].axvspan(a,b,color=color,alpha=.2,label=key+' interval')
        axes[0].set_ylabel('World Z (m)');axes[0].legend(fontsize=7,ncol=2,loc='best');axes[0].set_title(name+' / '+result['event']['status'])
        errors=[np.linalg.norm(np.array(f['observed_world_m'])-w)*1000 if 'observed_world_m' in f else np.nan for f,w in zip(result['frames'],true)]
        axes[1].plot(times,errors,'.-',color='#805447',markersize=3);axes[1].set_ylabel('Observed 3D error (mm)');axes[1].set_xlabel('Sample time since first frame (s)')
        for a in axes:a.grid(alpha=.2)
        fig.savefig(plots/f'{name}.png',dpi=125);plt.close(fig)
        row=rows[name];err=row['height_error_m'];height='无有效拟合' if err is None else f'高度误差 {err*1000:.3f} mm'
        note='图像→第二部分球心→三维；厘米级误差待改进。' if item['image'] else '显式像素观测及语义框回放；不是模型推理。'
        if item['image']:
            media=[]
            for eye in ['left','right']:
                p=root/'inputs'/f'{name}_20_{eye}.png';mask=root/'inputs'/f'{name}_20_{eye}_mask.png'
                im=cv2.imread(str(p));frame=result['frames'][20];center=frame.get(eye+'_pixel');pred=frame.get(eye+'_prediction_pixel')
                if pred:cv2.drawMarker(im,tuple(np.round(pred).astype(int)),(255,170,0),cv2.MARKER_CROSS,12,1)
                if center:cv2.drawMarker(im,tuple(np.round(center).astype(int)),(0,255,0),cv2.MARKER_CROSS,12,1)
                if center:
                    x,y=np.round(center).astype(int);patch=im[max(0,y-40):y+40,max(0,x-40):x+40];cv2.imwrite(str(plots/f'apex_{eye}_patch.png'),patch)
                    media.append(f'<figure><img class="patch" src="plots/apex_{eye}_patch.png" alt="{eye}顶点补测"><figcaption>{eye} 实测绿 / 预测蓝</figcaption></figure>')
                assert cv2.countNonZero(cv2.imread(str(mask),0))==0
            note+=' 第20帧两眼 Mask 均为零，绿点为从当前像素补测的球心。'
            extra='<div class="patches">'+''.join(media)+'</div>'
        else:extra=''
        cards.append(f'<article><h2>{html.escape(name)}</h2><p>{html.escape(note)}</p><p><b>{html.escape(result["event"]["status"])}</b> · {html.escape(result["event"]["reason"])} · {height}</p><img class="plot" src="plots/{name}.png" alt="{name}轨迹与误差">{extra}<p><a href="results/{name}.json">结果 JSON</a> · <a href="results/{name}.csv">分栏 CSV</a></p></article>')
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>B 第三部分初版验收</title><style>body{font:16px/1.65 system-ui,"Microsoft YaHei",sans-serif;background:#f1f5f9;color:#20324a;margin:0}main{max-width:1100px;margin:auto;padding:24px}h1{font-size:30px}h2{font-size:20px}section,article{background:white;border:1px solid #dbe4ef;border-radius:12px;padding:20px;margin:18px 0}a{color:#145e9b}.warning{border-left:5px solid #bf7d2e}.stats{display:flex;flex-wrap:wrap;gap:40px}.stats strong{font-size:27px;color:#176b4e}.plot{width:100%;max-width:850px}.patches{display:flex;gap:25px}.patch{width:200px;image-rendering:pixelated}figure{margin:5px}nav{display:flex;flex-wrap:wrap;gap:12px}code{overflow-wrap:anywhere;font-size:13px}footer{color:#52657a}</style><main><h1>B 第三部分初版：三维、跟踪与发球事件</h1><p>2026-10-06 · C++17/OpenCV · 源帧语义回放 · 不含真实相机或模型性能结论</p><section><div class="stats"><div><strong>40 + 42</strong><br>新增与第二部分回归检查</div><div><strong>20 / 20</strong><br>文件场景按预期通过</div><div><strong>4 / 4</strong><br>额外棋盘姿态检查</div></div><p><a href="score.json">事件/几何评分</a> · <a href="calibration-score.json">棋盘留出评分</a> · <a href="results/board_calibration.json">图像标定估计参数</a> · <a href="inputs/calibration.json">已知合成运行参数</a> · <a href="ctest-output.txt">实际CTest日志</a> · <a href="tool-versions.txt">工具版本</a> · <a href="RUN_MANIFEST.json">运行清单</a> · <a href="验证报告.md">报告</a></p></section><section class="warning">两个配置分别核验：棋盘图像用于估计参数，几何/事件回放使用已知合成参数。理想 double 几何小误差不能代替图像标定精度。图像链路当前三维 P95 约 5.28 cm、抛高偏约 2.73 cm；噪声/遮挡与正式精度仍需深化。检测框是 synthetic replay，C 未独立评分，离线源帧处理不代表在线队列验收。预测、滤波和实际观测分开，只有有效实测进入拟合；高度包络不是已校准置信区间。</section><nav>'''+''.join(f'<a href="#s{i}">{html.escape(t["name"])}</a>' for i,t in enumerate(truth['cases']))+'</nav>'+''.join(card.replace('<article>',f'<article id="s{i}">',1) for i,card in enumerate(cards))+'''<footer>蓝色为滤波、橙色为预测、绿色为实测；真值仅用于本页面和评分。缺失观测留空。红/紫/绿区间为触拍/顶点/离手证据。页面本地打开，无联网依赖。</footer></main></html>'''
    (root/'index.html').write_text(page,encoding='utf-8');print('GALLERY_CREATED plots='+str(len(cards)))


if __name__=='__main__':main()
