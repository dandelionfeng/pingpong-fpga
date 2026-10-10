"""Static plots of actual C++ outputs, with isolated truth for display only."""
import argparse
import html
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np


def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',required=True);args=ap.parse_args();root=Path(args.root);plots=root/'plots';plots.mkdir(exist_ok=True)
    score=read(root/'score-v2.json');truth={c['name']:c for c in read(root/'truth/expected_v2.json')['cases']};cards=[]
    chosen=['clean_serve_0','image_apex_zero_mask','image_subpixel','image_blur','image_noise','image_multi','image_estimated_calibration','missing_recatch','async_delay160','async_out_of_order','occlusion_5','continuous_two_serves']
    for name in chosen:
        r=read(root/'results'/f'{name}.json');start=int(r['frames'][0]['sample_time_ns']);times=np.array([(int(f['sample_time_ns'])-start)*1e-9 for f in r['frames']]);fig,ax=plt.subplots(2,1,figsize=(9,6),sharex=True,constrained_layout=True)
        if name in truth:
            true=np.array([f['world_m']for f in truth[name]['frames']]);ax[0].plot(times,true[:,2],label='truth (scorer only)',color='#243b50',lw=2)
            err=[np.linalg.norm(np.array(f['observed_world_m'])-w)*1000 if 'observed_world_m'in f else np.nan for f,w in zip(r['frames'],true)];ax[1].plot(times,err,'.-',color='#8b5833',label='3D observation error (mm)')
        for key,color,style in [('observed_world_m','#168451','.'),('filtered_world_m','#236ab5','-'),('predicted_world_m','#bb7b20','--')]:ax[0].plot(times,[f.get(key,[np.nan]*3)[2]for f in r['frames']],style,color=color,label=key,lw=1,ms=3)
        for u in r['online_updates']:
            if not u['finalized']:continue
            for key,color in [('release','#219365'),('apex','#8d58a5'),('contact','#ce5151')]:
                if key in u:a=u[key];ax[0].axvspan((int(a['begin_ns'])-start)*1e-9,(int(a['end_ns'])-start)*1e-9,color=color,alpha=.2)
        ax[0].set_ylabel('World Z (m)');ax[0].set_title(name);ax[0].legend(fontsize=7,ncol=2)
        ax[1].set_ylabel('Error (mm)');ax[1].set_xlabel('Sample time since first frame (s)')
        if name not in truth:
            revisions=r['online_updates'];ax[1].step([(int(u['published_time_ns'])-start)*1e-9 for u in revisions],[int(u['event_id']) for u in revisions],where='post',color='#805491');ax[1].set_ylabel('Online event ID')
        for a in ax:a.grid(alpha=.2)
        target=plots/(name+'.png');fig.savefig(target,dpi=120);plt.close(fig);cards.append(f'<article><h2>{html.escape(name)}</h2><img src="plots/{name}.png"><p><a href="results/{name}.json">结果与在线修订</a> · <a href="results/{name}.csv">观测/滤波/预测 CSV</a></p></article>')
    rows=[]
    for c in score['cases']:
        val=lambda k: '—' if c.get(k)is None else f'{c[k]*1000:.3f}'
        rows.append(f'<tr><td><a href="results/{c["name"]}.json">{html.escape(c["name"])}</a></td><td>{"通过"if c["passed"]else"失败"}</td><td>{html.escape(c["status"])}</td><td>{val("geometry_p95_m")}</td><td>{val("height_error_m")}</td></tr>')
    page=f'''<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>B 第三部分深化验收</title><style>body{{font:16px/1.6 system-ui,"Microsoft YaHei";max-width:1150px;padding:24px;margin:auto;background:#f3f6fa;color:#20334a}}section,article{{background:white;padding:20px;margin:18px 0;border:1px solid #d5deeb}}img{{max-width:100%}}table{{border-collapse:collapse;width:100%;font-size:14px}}th,td{{text-align:left;padding:7px;border-bottom:1px solid #ddd}}a{{color:#145e9b}}.note{{border-left:5px solid #ba7e31}}</style><h1>B 第三部分深化：实际测量、在线事件与证据</h1><p>2026-10-06 · C++17/OpenCV · 合成输入／显式语义回放</p><section><b>{score['passed']}/{score['total']} 文件场景通过</b><p><a href="events.html">事件原图、局部区域和轨迹证据</a> · <a href="score-v2.json">评分</a> · <a href="board_broad-score.json">扩展棋盘留出检查</a> · <a href="rectification-preview.png">双目校正预览</a> · <a href="验证报告.md">验证报告</a> · <a href="SOURCE_SHA256.json">源码哈希</a> · <a href="RUN_MANIFEST.json">复现清单</a></p></section><section class="note">全部是 B 的开发回归，C 尚未冻结数据或独立复核；检测框是显式回放，Mask 是合成搜索提示。估计标定参数已用于完整图像链路，仍不能代表实物精度。小数球心渲染与旧整数渲染分别报告，不能将不同输入的误差差异全部归功于算法。高度区间是声明误差预算包络，不是已校准置信区间；不自动判罚。</section>'''+''.join(cards)+'<section><h2>全部场景</h2><table><tr><th>场景</th><th>检查</th><th>状态</th><th>三维P95/mm</th><th>高度误差/mm</th></tr>'+''.join(rows)+'</table></section>'
    (root/'index.html').write_text(page,encoding='utf-8');print('V2_GALLERY_COMPLETE plots='+str(len(cards)))


if __name__=='__main__':main()
