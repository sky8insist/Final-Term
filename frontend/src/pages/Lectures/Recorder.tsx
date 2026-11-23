import { useEffect, useRef, useState } from 'react';
import { readRecording, writeRecording, type SavedRecording } from './recordingStore';
import type { LectureCapabilities } from '../../types/lecture';

const button='min-h-11 rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600 disabled:opacity-50';

export function Recorder({draftKey,capabilities,busy,onUpload}:{draftKey:string;capabilities:LectureCapabilities;busy:boolean;onUpload:(file:File)=>Promise<boolean>}){
  const recorder=useRef<MediaRecorder|null>(null);
  const alive=useRef(true);
  const bytes=useRef(0);
  const pieces=useRef<Blob[]>([]);
  const pendingWrite=useRef<Promise<void>>(Promise.resolve());
  const [state,setState]=useState<'idle'|'requesting'|'recording'|'paused'>('idle');
  const [saved,setSaved]=useState<SavedRecording|null>(null);
  const [restoring,setRestoring]=useState(true);
  const [elapsed,setElapsed]=useState(0);
  const [error,setError]=useState('');
  const [url,setUrl]=useState('');
  useEffect(()=>{
    alive.current=true;
    readRecording(draftKey).then(value=>{if(alive.current)setSaved(value);}).catch(()=>{if(alive.current)setError('浏览器未能读取录音草稿；录音完成后请及时下载保存。');}).finally(()=>{if(alive.current)setRestoring(false);});
    return()=>{alive.current=false;const value=recorder.current;if(value&&value.state!=='inactive'){value.stop();value.stream.getTracks().forEach(track=>track.stop());}};
  },[draftKey]);
  useEffect(()=>{if(!saved){setUrl('');return;}const value=URL.createObjectURL(saved.blob);setUrl(value);return()=>URL.revokeObjectURL(value);},[saved]);
  useEffect(()=>{
    if(state!=='recording')return;
    const timer=window.setInterval(()=>setElapsed(value=>value+1),1000);
    return()=>window.clearInterval(timer);
  },[state]);
  useEffect(()=>{if(elapsed>=capabilities.maxRecordingSeconds&&recorder.current?.state!=='inactive')recorder.current?.stop();},[elapsed,capabilities.maxRecordingSeconds]);
  useEffect(()=>{const warn=(event:BeforeUnloadEvent)=>{if(saved||state!=='idle'){event.preventDefault();event.returnValue='';}};window.addEventListener('beforeunload',warn);return()=>window.removeEventListener('beforeunload',warn);},[saved,state]);
  async function start(){
    if(saved||state!=='idle'||busy)return;
    setState('requesting');setError('');
    let stream:MediaStream|undefined;
    try{
      if(!navigator.mediaDevices?.getUserMedia||typeof MediaRecorder==='undefined')throw new Error('当前浏览器不支持录音，请上传已有音频。');
      stream=await navigator.mediaDevices.getUserMedia({audio:true});
      if(!alive.current){stream.getTracks().forEach(track=>track.stop());return;}
      const mime=['audio/webm;codecs=opus','audio/mp4'].find(value=>MediaRecorder.isTypeSupported(value));
      if(!mime)throw new Error('浏览器没有支持的录音格式，请上传已有音频。');
      const value=new MediaRecorder(stream,{mimeType:mime});recorder.current=value;pieces.current=[];bytes.current=0;setElapsed(0);
      value.ondataavailable=event=>{
        if(!event.data.size)return;
        pieces.current.push(event.data);bytes.current+=event.data.size;
        if(bytes.current>=capabilities.maxUploadBytes&&value.state!=='inactive')value.stop();
      };
      value.onerror=()=>{if(alive.current)setError('录音发生错误，已收到的音频可下载保留。');if(value.state!=='inactive')value.stop();};
      value.onstop=()=>{
        value.stream.getTracks().forEach(track=>track.stop());
        const blob=new Blob(pieces.current,{type:value.mimeType});pieces.current=[];recorder.current=null;
        if(alive.current)setState('idle');
        if(!blob.size)return;
        const recording={blob,name:`lecture-${Date.now()}.${value.mimeType.includes('mp4')?'m4a':'webm'}`};
        if(alive.current)setSaved(recording);
        pendingWrite.current=writeRecording(draftKey,recording);
        void pendingWrite.current.catch(()=>{if(alive.current)setError('录音未能保存在浏览器中，请先下载；刷新可能丢失录音。');});
      };
      value.start(1000);setState('recording');
    }catch(reason){stream?.getTracks().forEach(track=>track.stop());if(alive.current){setState('idle');setError(reason instanceof DOMException&&reason.name==='NotAllowedError'?'麦克风访问被拒绝，请检查浏览器权限，或上传已有音频。':reason instanceof DOMException&&reason.name==='NotFoundError'?'未找到可用麦克风，请连接设备，或上传已有音频。':reason instanceof Error?reason.message:'无法访问麦克风，请检查浏览器权限。');}}
  }
  async function discard(){
    try{await pendingWrite.current.catch(()=>undefined);await writeRecording(draftKey,null);setSaved(null);setError('');}
    catch{setError('录音草稿未能删除，请检查浏览器存储后重试。');}
  }
  async function upload(){
    if(!saved)return;
    const file=new File([saved.blob],saved.name,{type:saved.blob.type.split(';')[0]});
    if(await onUpload(file))await discard();
  }
  const oversized=Boolean(saved&&saved.blob.size>capabilities.maxUploadBytes);
  return <section className="mt-5 border-t border-slate-200 pt-4" aria-label="课堂录音">
    <h2 className="font-semibold">录制课堂音频</h2>
    <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">点击开始后才会请求麦克风权限。停止录音后可回听、下载，再上传转录；不是实时字幕。录制中离开页面会停止录音，刷新或关闭前请先停止并下载。</p>
    <p className="mt-2 text-sm text-slate-600">单次最多 {Math.floor(capabilities.maxRecordingSeconds/60)} 分钟、{Math.floor(capabilities.maxUploadBytes/1024/1024)} MB；达到上限会自动停止。</p>
    <div className="mt-3 flex flex-wrap items-center gap-3">
      <button type="button" className={button} disabled={restoring||busy||Boolean(saved)||state!=='idle'} onClick={()=>void start()}>{state==='requesting'?'正在请求麦克风…':'开始录音'}</button>
      {(state==='recording'||state==='paused')&&<button type="button" className={button} onClick={()=>{const value=recorder.current;if(!value)return;if(value.state==='recording'){value.pause();setState('paused');}else if(value.state==='paused'){value.resume();setState('recording');}}}>{state==='paused'?'继续录音':'暂停录音'}</button>}
      {(state==='recording'||state==='paused')&&<button type="button" className={button} onClick={()=>{if(recorder.current?.state!=='inactive')recorder.current?.stop();}}>停止并保留</button>}
      <span role="status" className="text-sm text-slate-700">{restoring?'正在恢复录音草稿…':state==='recording'?'正在录音':state==='paused'?'录音已暂停':saved?'录音已保留':'尚未录音'}{elapsed>0?` · 约 ${Math.floor(elapsed/60)} 分 ${elapsed%60} 秒`:''}</span>
    </div>
    {url&&saved&&<div className="mt-4 space-y-3">
<audio controls src={url} className="w-full" aria-label="未上传录音回听"/>
<div className="flex flex-wrap gap-3">
<a href={url} download={saved.name} className={`${button} inline-flex items-center text-blue-700`}>下载录音</a>
<button type="button" className={button} disabled={busy||oversized||!capabilities.canProcessAudio} onClick={()=>void upload()}>上传并创建课堂</button>
<button type="button" className={button} disabled={busy} onClick={()=>void discard()}>放弃这段录音</button>
</div>
<p className="text-sm text-slate-600">停止后的草稿按当前账户和科目保存在本浏览器。上传成功后移除草稿；请保留下载副本。</p>
</div>}
    {oversized&&<p role="alert" className="mt-3 text-sm text-rose-800">录音超过上传上限，请下载后裁剪再上传。</p>}
    {error&&<p role="alert" className="mt-3 text-sm text-rose-800">{error}</p>}
  </section>;
}
