import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../../api/client';
import type { CourseTopic, Material } from '../../types';
import type { ExamProposal } from '../../types/calendar';

const input='min-h-11 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600 disabled:opacity-50';

function Proposal({value,topics,onConfirmed}:{value:ExamProposal;topics:CourseTopic[];onConfirmed:()=>void}) {
  const [title,setTitle]=useState(value.title);
  const [day,setDay]=useState(value.exam_date);
  const [ids,setIds]=useState<string[]>([]);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const [eventId,setEventId]=useState(value.event_id);
  async function confirm() {
    setBusy(true);setError('');
    try {
      const event=await api.confirmCalendarExam(value.id,{title,exam_date:day,status:'active',topics:ids.map(id=>({knowledge_point_id:id,weight:1}))});
      setEventId(event.id);onConfirmed();
    } catch(reason) {setError(reason instanceof Error?reason.message:'考试确认失败，请重试。');}
    finally {setBusy(false);}
  }
  return <article className="border-t border-slate-200 py-5">
    <h3 className="font-semibold">{eventId?'已确认考试':'待确认考试'}</h3>
    <fieldset disabled={busy||Boolean(eventId)} className="mt-3 flex flex-wrap gap-3">
      <label className="flex min-w-48 flex-1 flex-col gap-2 text-sm">考试名称<input className={input} maxLength={300} value={title} onChange={event=>setTitle(event.target.value)}/></label>
      <label className="flex flex-col gap-2 text-sm">考试日期（北京时间）<input className={input} type="date" value={day} onChange={event=>setDay(event.target.value)}/></label>
    </fieldset>
    {value.scope_text&&<p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-slate-700">识别到的范围：{value.scope_text}</p>}
    <details className="mt-3 text-sm">
      <summary className="min-h-11 cursor-pointer py-2 font-semibold text-blue-700">核对原始大纲</summary>
      {value.evidence.map(source=><div key={source.id} className="mb-3 bg-slate-50 p-3"><p className="font-semibold">{source.filename}{source.pageNumber?` · 第 ${source.pageNumber} 页`:''}</p><p className="mt-2 whitespace-pre-wrap leading-6 text-slate-700">{source.chunkText}</p></div>)}
    </details>
    {!eventId&&<fieldset disabled={busy}>
      <legend className="text-sm font-semibold">确认知识点范围（章节文字不会自动映射）</legend>
      <div className="mt-2 flex max-h-56 flex-wrap gap-x-5 overflow-auto">{topics.map(topic=><label key={topic.id} className="flex min-h-11 items-center gap-2 text-sm"><input type="checkbox" checked={ids.includes(topic.id)} onChange={event=>setIds(values=>event.target.checked?[...values,topic.id]:values.filter(id=>id!==topic.id))}/>{topic.title}</label>)}</div>
      {!topics.length&&<p className="py-3 text-sm text-slate-600">请先在课程结构中建立知识点。</p>}
      <button type="button" className={`${input} mt-3 font-semibold text-blue-700`} disabled={busy||!ids.length||!title.trim()||!day} onClick={()=>void confirm()}>{busy?'正在确认…':'确认并加入考试目标'}</button>
    </fieldset>}
    {eventId&&<Link to={`/plan?examEventId=${encodeURIComponent(eventId)}`} className="mt-3 inline-flex min-h-11 items-center font-semibold text-blue-700 underline">为此考试制定计划</Link>}
    {error&&<p role="alert" className="mt-3 text-sm text-rose-800">{error}</p>}
  </article>;
}

export function Syllabus({subjectId,subjectName,onConfirmed}:{subjectId:string;subjectName:string;onConfirmed:()=>void}) {
  const [materials,setMaterials]=useState<Material[]>([]);
  const [topics,setTopics]=useState<CourseTopic[]>([]);
  const [material,setMaterial]=useState('');
  const [rows,setRows]=useState<ExamProposal[]|null>(null);
  const [error,setError]=useState('');
  const [busy,setBusy]=useState(false);
  const [truncated,setTruncated]=useState(false);
  const [reload,setReload]=useState(0);
  useEffect(()=>{
    let stopped=false;
    Promise.all([api.materials(subjectId),api.courseStructure(subjectId)]).then(([sources,structure])=>{
      if(!stopped){setMaterials(sources.filter(row=>row.status==='indexed'));setTopics(structure.topics.filter(row=>!row.archived));setError('');}
    }).catch(reason=>{if(!stopped)setError(reason instanceof Error?reason.message:'无法读取课程资料。');});
    return ()=>{stopped=true;};
  },[subjectId,reload]);
  async function extract() {
    setBusy(true);setError('');
    try {const result=await api.proposeCalendarExams(subjectId,material);setRows(result.proposals);setTruncated(result.truncated);}
    catch(reason){setError(reason instanceof Error?reason.message:'大纲提取失败，请重试。');}
    finally{setBusy(false);}
  }
  return <details className="mt-10 border-t border-slate-200 pt-5">
    <summary className="min-h-11 cursor-pointer py-2 text-lg font-semibold">从大纲确认考试 · {subjectName}</summary>
    <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-600">先在资料中心上传大纲并等待处理完成，再选择资料。支持明确的考试日期，例如 Final Exam: 2026-12-20；每次最多提取 20 个候选，请核对原文并手动确认知识点范围。</p>
    <div className="mt-4 flex flex-wrap items-end gap-3">
      <label className="flex min-w-60 flex-1 flex-col gap-2 text-sm">大纲资料<select className={input} disabled={busy} value={material} onChange={event=>{setMaterial(event.target.value);setRows(null);}}><option value="">请选择已处理资料</option>{materials.map(row=><option key={row.id} value={row.id}>{row.name}</option>)}</select></label>
      <button type="button" className={input} disabled={busy||!material} onClick={()=>void extract()}>{busy?'正在提取…':'提取候选考试'}</button>
      <button type="button" className={input} disabled={busy} onClick={()=>setReload(value=>value+1)}>刷新资料</button>
      <Link to="/materials" className="inline-flex min-h-11 items-center px-2 text-sm font-semibold text-blue-700 underline">上传大纲</Link>
    </div>
    {error&&<p role="alert" className="mt-4 text-sm text-rose-800">{error}</p>}
    {truncated&&<p className="mt-4 text-sm text-amber-800">资料超过 500 个内容块，本次仅检查前 500 块。</p>}
    {rows?.length===0&&<p role="status" className="mt-4 text-sm text-slate-600">未找到明确日期的考试。请核对解析原文，或前往课程结构手动添加考试目标。</p>}
    {rows?.map(row=><Proposal key={row.id} value={row} topics={topics} onConfirmed={onConfirmed}/>)}
  </details>;
}
