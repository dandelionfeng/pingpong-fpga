/* Perspective rendering of a three-dimensional demonstration scene. */
(function(root){
'use strict';
const dot=(a,b)=>a[0]*b[0]+a[1]*b[1]+a[2]*b[2];
const sub=(a,b)=>a.map((v,i)=>v-b[i]);
const cross=(a,b)=>[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];
const unit=v=>{const n=Math.hypot(...v);return v.map(x=>x/n)};
const clamp=(x,a,b)=>Math.max(a,Math.min(b,x));
// Table end line: x=-1.37 m. The toss remains outside it, with a 0.40 m rise.
function trajectory(t){return [-1.62+.06*t,-.25+.02*t,.16+1.6*t*(1-t)]}
function camera(yaw,pitch,width,height,zoom=1){
    const release=trajectory(0),center=[release[0]+.025,release[1]+.008,release[2]+.20],distance=1.55;
    const eye=[center[0]+distance*Math.sin(yaw)*Math.cos(pitch),center[1]-distance*Math.cos(yaw)*Math.cos(pitch),center[2]+distance*Math.sin(pitch)];
    const forward=unit(sub(center,eye)),right=unit(cross(forward,[0,0,1])),up=cross(right,forward);
    return {eye,forward,right,up,width,height,focal:Math.min(width*1.05,height*1.6)*zoom};
}
function project(point,c){
    const v=sub(point,c.eye),depth=dot(v,c.forward);
    return {x:c.width*.5+c.focal*dot(v,c.right)/depth,y:c.height*.48-c.focal*dot(v,c.up)/depth,depth,scale:c.focal/depth};
}
function init(){
    const canvas=document.getElementById('trajectory3d');if(!canvas)return;
    const ctx=canvas.getContext('2d');if(!ctx){canvas.parentNode.insertAdjacentHTML('beforeend','<p>三维视图初始化失败</p>');return}
    const pause=document.getElementById('trajectoryPause'),reset=document.getElementById('trajectoryReset');
    const reduced=matchMedia('(prefers-reduced-motion: reduce)');
    let width=0,height=0,dpr=1,yaw=.59,pitch=.48,targetYaw=yaw,targetPitch=pitch,zoom=1;
    let progress=.25,running=!reduced.matches,drag=null,visible=true,previous=0;
    function pauseLabel(){pause.textContent=running?'暂停':'播放';pause.setAttribute('aria-label',running?'暂停轨迹动画':'播放轨迹动画');pause.setAttribute('aria-pressed',String(!running))}
    function resize(){
        const box=canvas.getBoundingClientRect();width=box.width;height=box.height;dpr=Math.min(devicePixelRatio||1,2);
        canvas.width=Math.round(width*dpr);canvas.height=Math.round(height*dpr);render();
    }
    function render(){
        if(width<10||height<10)return;
        ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,width,height);
        const c=camera(yaw,pitch,width,height,zoom),objects=[];
        function line(points,color,lineWidth=1,dash=[]){
            const p=points.map(v=>project(v,c));
            objects.push({depth:p.reduce((s,v)=>s+v.depth,0)/p.length,draw(){ctx.beginPath();p.forEach((v,i)=>i?ctx.lineTo(v.x,v.y):ctx.moveTo(v.x,v.y));ctx.strokeStyle=color;ctx.lineWidth=lineWidth;ctx.setLineDash(dash);ctx.stroke();ctx.setLineDash([])}});
        }
        function polygon(points,fill,stroke){
            const p=points.map(v=>project(v,c));
            objects.push({depth:p.reduce((s,v)=>s+v.depth,0)/p.length,draw(){ctx.beginPath();p.forEach((v,i)=>i?ctx.lineTo(v.x,v.y):ctx.moveTo(v.x,v.y));ctx.closePath();ctx.fillStyle=fill;ctx.fill();if(stroke){ctx.strokeStyle=stroke;ctx.lineWidth=1;ctx.stroke()}}});
        }
        const releasePoint=trajectory(0),floor=releasePoint[2]-.025;
        const [rx,ry]=releasePoint;
        polygon([[rx-.4,ry-.32,floor],[rx+.4,ry-.32,floor],[rx+.4,ry+.32,floor],[rx-.4,ry+.32,floor]],'#dce8fa25');
        for(let i=-4;i<=4;i++)line([[rx+i*.1,ry-.32,floor],[rx+i*.1,ry+.32,floor]],'#b8cce55c',.7);
        for(let i=-3;i<=3;i++)line([[rx-.4,ry+i*.1,floor],[rx+.4,ry+i*.1,floor]],'#b8cce55c',.7);
        const count=84;
        for(let i=0;i<count;i++){
            const a=trajectory(i/count),b=trajectory((i+1)/count),t=i/count;
            line([a,b],t<.5?'#3475e9':'#42b1a5',2.2);
        }
        const apex=trajectory(.5);
        line([releasePoint,[releasePoint[0],releasePoint[1],apex[2]]],'#a1b2ccaa',1,[2,4]);
        const origin=[rx-.29,ry-.24,floor],axes=[[[.40,0,0],'#4b7ac6','X'],[[0,.40,0],'#31a493','Y'],[[0,0,.45],'#899bb5','Z']];
        for(const [vector,color] of axes){const end=origin.map((v,i)=>v+vector[i]);line([origin,end],color,1.5)}
        objects.sort((a,b)=>b.depth-a.depth).forEach(o=>o.draw());
        // A world-space moving ball, with size changing under perspective.
        const world=trajectory(progress),ball=project(world,c),shadow=project([world[0],world[1],floor+.001],c);
        const radius=clamp(ball.scale*.020,3.5,7.5);
        ctx.save();ctx.translate(shadow.x,shadow.y);ctx.scale(1,.42);const shade=ctx.createRadialGradient(0,0,1,0,0,radius*1.6);shade.addColorStop(0,'#7188ab36');shade.addColorStop(1,'#7188ab00');ctx.fillStyle=shade;ctx.beginPath();ctx.arc(0,0,radius*1.6,0,Math.PI*2);ctx.fill();ctx.restore();
        const glow=ctx.createRadialGradient(ball.x,ball.y,0,ball.x,ball.y,radius*2.6);glow.addColorStop(0,'#6f9dfb27');glow.addColorStop(1,'#6f9dfb00');ctx.fillStyle=glow;ctx.beginPath();ctx.arc(ball.x,ball.y,radius*2.6,0,Math.PI*2);ctx.fill();
        const gradient=ctx.createRadialGradient(ball.x-radius*.35,ball.y-radius*.4,radius*.05,ball.x+radius*.1,ball.y+radius*.1,radius*1.15);
        gradient.addColorStop(0,'#ffffff');gradient.addColorStop(.45,'#eaf2ff');gradient.addColorStop(1,'#a1bdf1');
        ctx.fillStyle=gradient;ctx.strokeStyle='#ffffff';ctx.lineWidth=1.2;ctx.beginPath();ctx.arc(ball.x,ball.y,radius,0,Math.PI*2);ctx.fill();ctx.stroke();
        ctx.font='10px "Segoe UI","Microsoft YaHei",sans-serif';ctx.textAlign='left';
        for(const [vector,color,label] of axes){const p=project(origin.map((v,i)=>v+vector[i]*1.16),c);ctx.fillStyle=color;ctx.fillText(label,p.x+3,p.y+3)}
        for(const [point,label,color] of [[releasePoint,'离手点','#6184b8'],[apex,'最高点','#61a59f']]){
            const p=project(point,c);ctx.fillStyle=color;ctx.beginPath();ctx.arc(p.x,p.y,2.5,0,Math.PI*2);ctx.fill();ctx.fillText(label,p.x+8,p.y-8);
        }
        canvas.dataset.rendered='true';canvas.dataset.frame=String(Number(canvas.dataset.frame||0)+1);canvas.dataset.yaw=yaw.toFixed(4);canvas.dataset.interaction=drag?'drag':running?'auto':'paused';
    }
    function frame(now){
        const dt=previous?Math.min((now-previous)/1000,.05):0;previous=now;
        if(visible){
            if(running){progress=(progress+dt/2.8)%1;if(!drag&&!reduced.matches)targetYaw+=dt*.16}
            yaw+=(targetYaw-yaw)*.16;pitch+=(targetPitch-pitch)*.16;
            if(running||Math.abs(targetYaw-yaw)>.0001||Math.abs(targetPitch-pitch)>.0001)render();
        }
        requestAnimationFrame(frame);
    }
    canvas.addEventListener('pointerdown',e=>{e.preventDefault();drag={x:e.clientX,y:e.clientY,yaw:targetYaw,pitch:targetPitch};canvas.setPointerCapture(e.pointerId)});
    canvas.addEventListener('pointermove',e=>{if(!drag)return;targetYaw=drag.yaw-(e.clientX-drag.x)*.008;targetPitch=clamp(drag.pitch+(e.clientY-drag.y)*.006,.22,1.2);render()});
    const release=()=>drag=null;canvas.addEventListener('pointerup',release);canvas.addEventListener('pointercancel',release);canvas.addEventListener('lostpointercapture',release);
    canvas.addEventListener('wheel',e=>{e.preventDefault();zoom=clamp(zoom*Math.exp(-e.deltaY*.001),.72,1.4);render()},{passive:false});
    function resetView(){targetYaw=.59;targetPitch=.48;zoom=1;render()}
    pause.onclick=()=>{running=!running;pauseLabel();render()};reset.onclick=resetView;
    canvas.addEventListener('keydown',e=>{
        const keys=['ArrowLeft','ArrowRight','ArrowUp','ArrowDown',' ','r','R'];if(!keys.includes(e.key))return;e.preventDefault();
        if(e.key==='ArrowLeft')targetYaw-=.12;if(e.key==='ArrowRight')targetYaw+=.12;
        if(e.key==='ArrowUp')targetPitch=clamp(targetPitch+.1,.22,1.2);if(e.key==='ArrowDown')targetPitch=clamp(targetPitch-.1,.22,1.2);
        if(e.key===' ')pause.click();if(e.key.toLowerCase()==='r')resetView();render();
    });
    reduced.addEventListener('change',e=>{if(e.matches){running=false;pauseLabel();render()}});
    new ResizeObserver(resize).observe(canvas);new IntersectionObserver(entries=>{visible=entries[0].isIntersecting;if(visible)render()}).observe(canvas);
    pauseLabel();resize();requestAnimationFrame(frame);
    root.ServeTrajectory.getState=()=>({yaw,pitch,zoom,progress,running,rendered:canvas.dataset.rendered==='true'});
}
root.ServeTrajectory={trajectory,camera,project};
if(typeof module!=='undefined'&&module.exports)module.exports=root.ServeTrajectory;
if(typeof document!=='undefined')init();
})(globalThis);
