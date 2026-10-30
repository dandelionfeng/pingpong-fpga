"""Draw observed flight points, fitted/extrapolated path, height and chord angle."""
from pathlib import Path
import math
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Arc
import numpy as np

plt.rcParams.update({'font.sans-serif':['Microsoft YaHei'],'axes.unicode_minus':False,'svg.fonttype':'none'})


def make_plot(index, record, event, frames, output):
    release=np.array(record['candidate_release_world_m'],float)
    apex=np.array(record['apex_world_m'],float)
    height=apex[2]-release[2]
    vec=apex[:2]-release[:2];distance=float(np.linalg.norm(vec));unit=vec/distance if distance else np.array([1.,0.])
    angle=math.degrees(math.atan2(distance,height))
    assert abs(height-record['metric']['height_m'])<1e-9 and abs(angle-record['metric']['angle_deg'])<1e-7
    selected=set(event['used_pair_ids']);observed=[]
    for row in frames:
        m=row['measurement'];p=m.get('world_xyz_m')
        if row['pair_id'] in selected and m.get('status')=='observed' and m.get('semantic_ball_supported') and p and len(p)==3 and np.isfinite(p).all():
            observed.append((row['pair_id'],row['timestamp_ns'],np.array(p,float)))
    assert len(observed)==len(selected),(index,len(observed),len(selected))
    observed.sort(key=lambda x:x[1]);release_ns=record['candidate']['timestamp_ns'];first_ns=observed[0][1];last_ns=observed[-1][1]
    assert release_ns<first_ns<last_ns
    origin=event['fit_origin_ns'];x,y,z=(event[k] for k in ('x_coefficients','y_coefficients','z_coefficients'))
    def xyz(ns):
        t=(np.asarray(ns,dtype=float)-origin)*1e-9
        return np.column_stack((x[0]+x[1]*t,y[0]+y[1]*t,z[0]+z[1]*t+z[2]*t*t))
    def project(points):
        return (points[:,:2]-release[:2])@unit,points[:,2]-release[2]
    ext_ns=np.linspace(release_ns,first_ns,100);fit_ns=np.linspace(first_ns,last_ns,140)
    assert np.allclose(xyz([release_ns])[0],release,rtol=0,atol=1e-9), 'curve must pass release point'
    assert np.allclose(xyz([origin+event['apex_s']*1e9])[0],apex,rtol=0,atol=1e-9), 'curve must pass apex'
    epx,epy=project(xyz(ext_ns));fpx,fpy=project(xyz(fit_ns))
    pts=np.stack([p for _,_,p in observed]);px,py=project(pts)
    times=np.array([(t-release_ns)*1e-9 for _,t,_ in observed]);apex_time=(event['fit_origin_ns']+event['apex_s']*1e9-release_ns)*1e-9
    fig,(ax,timeline)=plt.subplots(1,2,figsize=(15,7.8),gridspec_kw={'width_ratios':[1.23,1]},layout='constrained')
    title=record.get('title',f'ffk final{index if index>1 else ""}')
    fig.set_facecolor('#f6faf8');fig.suptitle(title+'  |  球轨迹与抛球测量',fontsize=20,fontweight='bold',color='#173a35')
    for axis in (ax,timeline):
        axis.set_facecolor('white');axis.grid(color='#dbe7e1',linewidth=.8);axis.set_axisbelow(True)
        for side in ('top','right'):axis.spines[side].set_visible(False)
        axis.spines['left'].set_color('#9fb8ad');axis.spines['bottom'].set_color('#9fb8ad')
        axis.tick_params(colors='#516a60')
    ax.plot(epx,epy,color='#ec9446',lw=2.5,ls='--',label='拟合曲线向前外推')
    ax.plot(fpx,fpy,color='#198d80',lw=2.7,label='飞行段拟合')
    ax.scatter(px,py,s=31,color='#1e5966',edgecolor='white',linewidth=.65,zorder=4,label='实际双目观测')
    ax.plot([0,distance],[0,height],color='#61746d',lw=1.5,ls=':',label='离手—最高点连线')
    ax.plot([distance,distance],[0,height],color='#429768',lw=1.8,ls='-.')
    ax.axhline(0,color='#abbfb4',ls='--',lw=1)
    ax.scatter([0],[0],s=125,color='#eea33b',edgecolor='white',linewidth=1,zorder=6)
    ax.scatter([distance],[height],s=125,color='#13a77c',edgecolor='white',linewidth=1,zorder=6)
    ax.annotate(f'离手候选  pair {record["candidate"]["pair_id"]}',(0,0),xytext=(8,11),textcoords='offset points',fontsize=10,color='#98520d',fontweight='bold')
    apex_ns=event['fit_origin_ns']+event['apex_s']*1e9
    apex_pair=min(frames,key=lambda row:abs(row['timestamp_ns']-apex_ns))['pair_id']
    ax.annotate(f'最高点  pair {apex_pair}',
                (distance,height),xytext=(-8,13),textcoords='offset points',ha='right',fontsize=10,color='#087554',fontweight='bold')
    ax.annotate(f'高度 {height*100:.2f} cm',(distance,height*.5),xytext=(9,0),textcoords='offset points',fontsize=10,color='#18764b',fontweight='bold')
    radius=min(height,distance if distance else height)*.25
    ax.add_patch(Arc((distance,height),radius*2,radius*2,angle=0,theta1=270-angle,theta2=270,color='#bd7140',lw=1.7))
    ax.annotate(f'{angle:.2f}°',(distance-radius*.55,height-radius*1.4),xytext=(-4,0),textcoords='offset points',ha='right',fontsize=10,color='#a75820',fontweight='bold')
    ax.set_title('空间轨迹投影：高度和角度',loc='left',fontsize=13,fontweight='bold',pad=12)
    ax.set_xlabel('水平位移（沿离手点到最高点方向，m）');ax.set_ylabel('相对离手水平面高度（m）')
    ax.set_aspect('equal',adjustable='datalim');ax.legend(loc='lower right',fontsize=8,frameon=True,facecolor='white')
    timeline.plot((ext_ns-release_ns)*1e-9,epy,color='#ec9446',lw=2.5,ls='--',label='向前外推')
    timeline.plot((fit_ns-release_ns)*1e-9,fpy,color='#198d80',lw=2.7,label='飞行段拟合')
    timeline.scatter(times,py,s=35,color='#1e5966',edgecolor='white',linewidth=.65,zorder=4,label='实际双目观测')
    timeline.axvline(0,color='#e9a040',ls=':',lw=1.5);timeline.axvline(apex_time,color='#36a47a',ls=':',lw=1.5)
    timeline.scatter([0,apex_time],[0,height],s=75,color=['#eea33b','#13a77c'],edgecolor='white',zorder=6)
    timeline.annotate('离手候选',(0,0),xytext=(7,10),textcoords='offset points',color='#98520d',fontsize=9)
    timeline.annotate('最高点',(apex_time,height),xytext=(-5,10),textcoords='offset points',ha='right',color='#087554',fontsize=9)
    timeline.set_title('高度随时间变化',loc='left',fontsize=13,fontweight='bold',pad=12)
    timeline.set_xlabel('相对离手候选时间（秒）');timeline.set_ylabel('相对离手水平面高度（m）');timeline.legend(loc='lower right',fontsize=9)
    fig.text(.5,-.01,'橙色虚线为向前外推，离手候选和物理精度尚未独立验证。',ha='center',fontsize=10,color='#93602e')
    output=Path(output);fig.savefig(output/'trajectory.png',dpi=160,bbox_inches='tight',facecolor=fig.get_facecolor());fig.savefig(output/'trajectory.svg',bbox_inches='tight',facecolor=fig.get_facecolor());plt.close(fig)
    return {'observed_pairs':[p for p,_,_ in observed], 'candidate_pair':record['candidate']['pair_id'],'candidate_timestamp_ns':release_ns,
            'first_observed_timestamp_ns':first_ns,'apex_time_s_from_candidate':apex_time,'height_m':height,'angle_deg':angle}
