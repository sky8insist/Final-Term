import { useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { api } from '../../api/client';
import { useAuth } from '../../auth/AuthProvider';
import { TurnInto } from '../../components/TurnInto';
import { useAppStore } from '../../stores/useAppStore';
import type { CourseTopic } from '../../types';
import type { Lecture, LectureCapabilities, LectureDetail, TranscriptBlock, TranscriptPage } from '../../types/lecture';
import { Recorder } from './Recorder';

const control='min-h-11 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600 disabled:opacity-50';
const errorText=(reason:unknown)=>reason instanceof Error?reason.message:'操作未完成，请重试。';
function time(value:number|null){if(value===null)return '时间未知';return `${Math.floor(value/60)}:${String(Math.floor(value%60)).padStart(2,'0')}`;}
const statuses:Record<string,string>={queued:'等待处理',processing:'正在处理',parsing:'正在转录',embedding:'正在建立索引',indexing:'正在建立索引',ready:'转录与知识库已就绪',failed:'处理未完成'};

function LectureViewer({id,subjectId,topics}:{id:string;subjectId:string;topics:CourseTopic[]}){
  const [params]=useSearchParams();
  const [detail,setDetail]=useState<LectureDetail|null>(null);
  const [page,setPage]=useState<TranscriptPage|null>(null);
  const [offset,setOffset]=useState(0);
  const [selected,setSelected]=useState(params.get('blockId')||'');
  const [topicId,setTopicId]=useState('');
  const [error,setError]=useState('');
  const [notice,setNotice]=useState('');
  const [busy,setBusy]=useState(false);
  const [loading,setLoading]=useState(true);
  const [reload,setReload]=useState(0);
  const [url,setUrl]=useState('');
  const audio=useRef<HTMLAudioElement|null>(null);
  const pendingSeek=useRef<number|null>(null);
  const initialBlock=useRef(params.get('blockId')||undefined);
  const current=page?.blocks.find(row=>row.id===selected);
  useEffect(()=>{
    let stopped=false;let timer:number;
    const load=async()=>{
      try{const value=await api.lecture(id,subjectId);if(stopped)return;setDetail(value);setError('');if(!['ready','failed'].includes(value.status)&&!['failed','cancelled'].includes(value.task?.status||''))timer=window.setTimeout(()=>void load(),3000);}
      catch(reason){if(!stopped)setError(errorText(reason));}
      finally{if(!stopped)setLoading(false);}
    };
    void load();return()=>{stopped=true;window.clearTimeout(timer);};
  },[id,subjectId,reload]);
  useEffect(()=>{
    let stopped=false;
    api.lectureTranscript(id,offset,initialBlock.current).then(value=>{if(!stopped){initialBlock.current=undefined;setOffset(value.offset);setPage(value);setSelected(previous=>value.blocks.some(row=>row.id===previous)?previous:value.blocks[0]?.id||'');}})
      .catch(reason=>{if(!stopped)setError(errorText(reason));});
    return()=>{stopped=true;};
  },[id,offset,reload,detail?.status]);
  useEffect(()=>{setTopicId(current?.knowledge_point_id||'');},[current]);
  useEffect(()=>()=>audio.current?.pause(),[]);
  async function source(start?:number){
    setBusy(true);setError('');
    try{const value=await api.materialSource(detail!.material_id);pendingSeek.current=start??null;setUrl(value.url);if(audio.current&&audio.current.src===value.url&&start!==undefined){audio.current.currentTime=start;await audio.current.play();}}
    catch(reason){setError(errorText(reason));}finally{setBusy(false);}
  }
  async function play(block:TranscriptBlock){
    if(block.start_time===null){setError('该片段没有时间信息，请回听完整录音核对。');return;}
    setError('');
    try{if(!url)await source(block.start_time);else if(audio.current){audio.current.currentTime=block.start_time;await audio.current.play();}}
    catch{setError('音频暂时无法播放，请刷新音频链接后重试。');}
  }
  async function align(){
    if(!page||!current)return;
    setBusy(true);setError('');setNotice('');
    try{await api.alignLectureTopic(id,current.id,topicId||null,page.version);setNotice('知识点关联已保存；不会增加掌握度。');setReload(value=>value+1);}
    catch(reason){setError(errorText(reason));}finally{setBusy(false);}
  }
  async function retry(){
    if(!detail?.task)return;
    setBusy(true);setError('');
    try{await api.retryLectureTask(detail.task.id);setReload(value=>value+1);}
    catch(reason){setError(errorText(reason));}finally{setBusy(false);}
  }
  return <section className="min-w-0 flex-1 bg-white p-5 lg:p-7" aria-label="课堂转录">
    <div className="flex flex-wrap items-center justify-between gap-3">
<h2 className="text-xl font-semibold">{detail?.title||'课堂详情'}</h2>
<button type="button" className={control} disabled={busy} onClick={()=>setReload(value=>value+1)}>刷新转录</button>
</div>
    {loading&&<p role="status" className="mt-4 text-sm text-slate-600">正在读取课堂…</p>}
    {detail&&<p role="status" className="mt-3 text-sm text-slate-600">{statuses[detail.status]||detail.status} · {detail.segments.filter(row=>row.status==='ready').length}/{detail.segments.length} 个音频分段已转录{detail.task?` · 总进度 ${detail.task.progress}%`:''}</p>}
    {detail?.error&&<p role="alert" className="mt-3 text-sm text-rose-800">{detail.error}</p>}
    {detail?.task?.status==='failed'&&<button type="button" className={`${control} mt-3`} disabled={busy} onClick={()=>void retry()}>重试音频处理</button>}
    {detail&&<button type="button" className={`${control} mt-4 text-blue-700`} disabled={busy} onClick={()=>void source()}>读取或刷新音频链接</button>}
    {url&&<audio key={url} ref={audio} src={url} controls preload="metadata" className="mt-4 w-full" aria-label="课堂音频回听" onLoadedMetadata={()=>{if(pendingSeek.current!==null&&audio.current){audio.current.currentTime=pendingSeek.current;pendingSeek.current=null;void audio.current.play().catch(()=>setError('请点击音频播放器继续回听。'));}}} onError={()=>setError('音频链接可能过期或原文件已清理，请刷新音频链接。')}/>}
    {error&&<p role="alert" className="mt-4 text-sm text-rose-800">{error}</p>}
    {notice&&<p role="status" className="mt-4 text-sm text-emerald-800">{notice}</p>}
    {page&&<>
<div className="my-5 flex flex-wrap items-center justify-between gap-3">
<p className="text-sm text-slate-600">共 {page.total} 段转录 · 当前 {page.total?offset+1:0}–{Math.min(offset+50,page.total)}</p>
<div className="flex gap-2">
<button type="button" className={control} disabled={busy||offset===0} onClick={()=>{setPage(null);setOffset(value=>Math.max(0,value-50));}}>上一页</button>
<button type="button" className={control} disabled={busy||offset+50>=page.total} onClick={()=>{setPage(null);setOffset(value=>value+50);}}>下一页</button>
</div>
</div>
      {!page.blocks.length&&<p className="text-sm leading-6 text-slate-600">尚无转录内容。音频需要由后台完成转录与索引；处理中可刷新查看状态。</p>}
      <ol className="max-h-96 divide-y divide-slate-200 overflow-auto border-y border-slate-200">{page.blocks.map(block=>
<li key={block.id} className="py-4">
<button type="button" className={`min-h-11 w-full rounded-lg px-3 py-2 text-left text-sm focus-visible:outline-2 focus-visible:outline-blue-600 ${selected===block.id?'bg-blue-50 text-blue-950':'text-slate-800 hover:bg-slate-50'}`} aria-pressed={selected===block.id} disabled={busy} onClick={()=>setSelected(block.id)}>
<span className="font-semibold">{time(block.start_time)}–{time(block.end_time)}{block.topic_title?` · ${block.topic_title}`:' · 尚未关联知识点'}</span>
<span className="mt-2 block whitespace-pre-wrap leading-7">{block.content_text}</span>
<span className="mt-2 block text-xs">{block.timestamp_precision==='asr_segment'?'转录服务提供的时间区间':block.timestamp_precision==='segment_window'?'音频分段区间，非逐句精确时间':'历史时间标注，请回听核对'} · {block.confidence===null||!block.timestamp_precision?'未提供识别置信度':`服务报告置信度 ${Math.round(block.confidence*100)}%，未校准`}</span>
</button>
</li>)}</ol>
    </>}
    {current&&detail&&<div className="mt-5">
      <button type="button" className={control} disabled={busy||current.start_time===null} onClick={()=>void play(current)}>从所选片段回听</button>
      <fieldset disabled={busy||detail.status!=='ready'} className="mt-4 flex flex-wrap items-end gap-3">
<label className="flex min-w-56 flex-1 flex-col gap-2 text-sm">关联课程知识点<select className={control} value={topicId} onChange={event=>setTopicId(event.target.value)}>
<option value="">不关联知识点</option>{topics.map(topic=>
<option key={topic.id} value={topic.id}>{topic.title}</option>)}</select>
</label>
<button type="button" className={control} disabled={busy} onClick={()=>void align()}>保存关联</button>
</fieldset>
      <p className="mt-2 text-sm leading-6 text-slate-600">请先回听核对，再选择稳定知识点。转录原文不会被改写；识别内容和时间可能有误。</p>
      <TurnInto key={`${id}:${current.id}:${page?.version}`} subjectId={subjectId} source={{kind:'material',id:detail.material_id,blockIds:[current.id]}} disabled={busy||detail.status!=='ready'}/>
    </div>}
  </section>;
}

function LectureWorkspace({subjectId,userId}:{subjectId:string;userId:string}){
  const [params]=useSearchParams();
  const [lectures,setLectures]=useState<Lecture[]>([]);
  const [selected,setSelected]=useState(params.get('lectureId')||'');
  const [topics,setTopics]=useState<CourseTopic[]>([]);
  const [materials,setMaterials]=useState<Array<{id:string;filename:string;status:string}>>([]);
  const [material,setMaterial]=useState('');
  const [title,setTitle]=useState('课堂录音');
  const [capabilities,setCapabilities]=useState<LectureCapabilities|null>(null);
  const [error,setError]=useState('');
  const [busy,setBusy]=useState(false);
  const [loading,setLoading]=useState(true);
  const [reload,setReload]=useState(0);
  useEffect(()=>{
    let stopped=false;
    Promise.all([api.lectures(subjectId),api.courseStructure(subjectId),api.lectureAudioMaterials(subjectId),api.lectureCapabilities()]).then(([rows,structure,audio,limits])=>{
      if(stopped)return;setLectures(rows);setTopics(structure.topics.filter(row=>!row.archived));setMaterials(audio);setCapabilities(limits);setSelected(value=>rows.some(row=>row.id===value)?value:rows[0]?.id||'');setError('');
    }).catch(reason=>{if(!stopped)setError(errorText(reason));}).finally(()=>{if(!stopped)setLoading(false);});
    return()=>{stopped=true;};
  },[subjectId,reload]);
  function added(value:Lecture){setLectures(rows=>[value,...rows.filter(row=>row.id!==value.id)]);setSelected(value.id);setReload(count=>count+1);}
  async function upload(file:File,kind:'recording'|'upload'){
    setBusy(true);setError('');
    try{if(!title.trim())throw new Error('请填写课堂名称。');if(capabilities&&file.size>capabilities.maxUploadBytes)throw new Error('音频超过上传大小上限，请先裁剪。');const value=await api.addMaterial(subjectId,file);const lecture=await api.attachLecture(subjectId,value.material.id,title.trim(),kind);added(lecture);return true;}
    catch(reason){setError(errorText(reason)+' 如果上传未返回成功，可刷新已上传音频列表找回资料；录音草稿会保留。');return false;}
    finally{setBusy(false);}
  }
  async function attach(){setBusy(true);setError('');try{added(await api.attachLecture(subjectId,material,title.trim(),'upload'));}catch(reason){setError(errorText(reason));}finally{setBusy(false);}}
  return <div className="h-full overflow-y-auto bg-slate-50 p-6 lg:p-8">
<div className="mx-auto max-w-7xl">
    <h1 className="text-2xl font-bold text-slate-950">课堂录音</h1>
<p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">记录课堂，回听带时间的转录，并将片段关联到课程知识点。停止录音并上传后开始后台转录。</p>
    {error&&<p role="alert" className="mt-4 text-sm text-rose-800">{error}</p>}
    <label className="mt-5 flex max-w-xl flex-col gap-2 text-sm font-semibold">新课堂名称<input className={control} maxLength={300} disabled={busy} value={title} onChange={event=>setTitle(event.target.value)}/>
</label>
    {capabilities?.mocked&&<p role="alert" className="mt-4 text-sm text-amber-800">服务当前启用模拟转录，输出不能作为真实课堂内容。</p>}
    {capabilities&&!capabilities.canProcessAudio&&<p role="status" className="mt-4 text-sm text-amber-800">服务当前缺少音频处理能力，可先录音并下载保存，或查看已完成转录的课堂。</p>}
    {capabilities&&<Recorder key={`${userId}:${subjectId}`} draftKey={`${userId}:${subjectId}`} capabilities={capabilities} busy={busy} onUpload={file=>upload(file,'recording')}/>}
    <div className="my-6 flex flex-wrap items-end gap-3">
<label className={`inline-flex min-h-11 items-center rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-semibold ${busy||!capabilities?.canProcessAudio?'opacity-50':'cursor-pointer hover:bg-slate-50'}`}>上传已有音频<input type="file" className="sr-only" accept=".mp3,.wav,.m4a,.webm" disabled={busy||!capabilities?.canProcessAudio} onChange={event=>{const file=event.target.files?.[0];event.target.value='';if(file)void upload(file,'upload');}}/>
</label>
<label className="flex min-w-60 flex-1 flex-col gap-2 text-sm">已上传音频<select className={control} value={material} disabled={busy} onChange={event=>setMaterial(event.target.value)}>
<option value="">选择录音资料</option>{materials.map(row=>
<option key={row.id} value={row.id}>{row.filename} · {statuses[row.status]||row.status}</option>)}</select>
</label>
<button type="button" className={control} disabled={busy||!material||!title.trim()} onClick={()=>void attach()}>加入课堂列表</button>
<button type="button" className={control} disabled={busy} onClick={()=>{setLoading(true);setReload(value=>value+1);}}>刷新课堂与资料</button>
</div>
    {busy&&<p role="status" className="mb-4 text-sm text-blue-800">正在保存音频或课堂记录，请勿关闭页面…</p>}
    {loading?<p role="status" className="py-8 text-slate-600">正在读取课堂…</p>:<div className="flex min-h-96 border border-slate-200">
<aside className="w-60 shrink-0 border-r border-slate-200 bg-white p-4" aria-label="课堂列表">
<h2 className="font-semibold">最近的课堂</h2>
<ul className="mt-3 divide-y divide-slate-200">{lectures.map(row=>
<li key={row.id}>
<button type="button" className={`min-h-11 w-full break-words py-4 text-left text-sm focus-visible:outline-2 focus-visible:outline-blue-600 ${selected===row.id?'font-semibold text-blue-800':'text-slate-700'}`} disabled={busy} aria-pressed={selected===row.id} onClick={()=>setSelected(row.id)}>{row.title}</button>
</li>)}</ul>{!lectures.length&&<p className="mt-4 text-sm leading-6 text-slate-600">尚无课堂。可以开始录音，或选择已上传音频。</p>}</aside>{selected?<LectureViewer key={selected} id={selected} subjectId={subjectId} topics={topics}/>:<p className="p-6 text-sm text-slate-600">创建课堂后，在这里查看分段转录和原始来源。</p>}</div>}
  </div>
</div>;
}

export default function Lectures(){const subject=useAppStore(state=>state.currentSubject)!;const {user}=useAuth();return user?<LectureWorkspace key={`${user.id}:${subject.id}`} subjectId={subject.id} userId={user.id}/>:null;}
