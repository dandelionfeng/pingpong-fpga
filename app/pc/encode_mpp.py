"""RK MPP JPEG -> H264 export, preserving each source frame's sample time."""
from pathlib import Path
import argparse,json,statistics,threading,time,resource,os
from fractions import Fraction
os.environ['TMPDIR']='/tmp'
import gi
gi.require_version('Gst','1.0')
from gi.repository import Gst
def encode(manifest_path,output):
    Gst.init(None);manifest=json.loads(Path(manifest_path).read_text('utf-8-sig'));frames=manifest['frames']
    if not frames:raise ValueError('No source frames')
    delta=[b['timestamp_ns']-a['timestamp_ns'] for a,b in zip(frames,frames[1:])]
    if delta and min(delta)<=0:raise ValueError('Nonmonotonic source timestamps')
    step=int(statistics.median(delta)) if delta else 16666667
    fps=Fraction(1000000000,step);start=frames[0]['timestamp_ns']
    pipeline=Gst.parse_launch('appsrc name=input format=time block=true max-bytes=2097152 ! jpegparse ! '
        'jpegdec ! videoconvert ! video/x-raw,format=NV12 ! mpph264enc bps=8000000 gop=60 ! '
        'h264parse ! video/x-h264,stream-format=avc,alignment=au ! mp4mux name=mux faststart=true ! filesink name=output')
    source=pipeline.get_by_name('input');sink=pipeline.get_by_name('output')
    source.set_property('caps',Gst.Caps.from_string(f'image/jpeg,width={frames[0]["width"]},height={frames[0]["height"]},framerate={fps.numerator}/{fps.denominator}'))
    sink.set_property('location',str(output))
    pad=pipeline.get_by_name('mux').get_static_pad('video_0')
    if pad and pad.find_property('trak-timescale'):pad.set_property('trak-timescale',1000000)
    errors=[];pushed=[]
    def feed():
        try:
            for i,row in enumerate(frames):
                raw=(Path(manifest_path).parent/row['file']).read_bytes()
                buf=Gst.Buffer.new_allocate(None,len(raw),None);buf.fill(0,raw)
                buf.pts=row['timestamp_ns']-start;buf.dts=buf.pts
                buf.duration=delta[i] if i<len(delta) else step
                flow=source.emit('push-buffer',buf)
                if flow!=Gst.FlowReturn.OK:raise RuntimeError(f'JPEG push failed: {flow}')
                pushed.append(i)
            source.emit('end-of-stream')
        except Exception as e:errors.append(str(e));source.emit('end-of-stream')
    began=time.perf_counter();cpu=time.process_time()
    worker=threading.Thread(target=feed,daemon=True)
    try:
        pipeline.set_state(Gst.State.PLAYING);worker.start()
        message=pipeline.get_bus().timed_pop_filtered(90*Gst.SECOND,Gst.MessageType.ERROR|Gst.MessageType.EOS)
        if message is None:raise TimeoutError('MPP export exceeded 90 seconds')
        if message.type==Gst.MessageType.ERROR:
            error,debug=message.parse_error();raise RuntimeError(str(error)+' '+str(debug))
        if errors:raise RuntimeError('; '.join(errors))
        if len(pushed)!=len(frames):raise RuntimeError('Incomplete hardware export')
    finally:
        pipeline.set_state(Gst.State.NULL);worker.join(timeout=5)
    result={'encoder':'jpegdec-rk-mpp-h264','frames':len(frames),'wall_ms':(time.perf_counter()-began)*1000,
            'cpu_ms':(time.process_time()-cpu)*1000,'max_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            'timing':'original per-frame timestamps, microsecond MP4 track timebase'}
    Path(str(output)+'.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('manifest',type=Path);p.add_argument('output',type=Path);a=p.parse_args();encode(a.manifest,a.output)
