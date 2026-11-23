import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api } from '../../api/client';
import { useAppStore } from '../../stores/useAppStore';
import type { DailyReport, DailyReview, DailySchedule } from '../../types/dailyReview';

const button = 'min-h-11 rounded-lg border border-slate-300 bg-white px-4 text-sm font-semibold text-slate-800 hover:bg-slate-100 focus-visible:outline-2 focus-visible:outline-blue-600 disabled:opacity-50';
const primary = 'min-h-11 rounded-lg bg-blue-700 px-4 text-sm font-semibold text-white hover:bg-blue-800 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600 disabled:opacity-50';
const stateNames = {pending:'待查看',applied:'已确认',rejected:'已拒绝'};
const format = (value:number|null) => value==null?'尚未评估':`${Math.round(value*100)}%`;

export default function DailyReviewPage() {
  const subject = useAppStore(state=>state.currentSubject)!;
  return <ReviewWorkspace key={subject.id} subjectId={subject.id} subjectName={subject.name}/>;
}

function ReviewWorkspace({subjectId,subjectName}:{subjectId:string;subjectName:string}) {
  const [params,setParams]=useSearchParams();
  const [preview,setPreview]=useState<DailyReport|null>(null);
  const [selected,setSelected]=useState<DailyReview|null>(null);
  const [history,setHistory]=useState<DailyReview[]>([]);
  const [hasMore,setHasMore]=useState(false);
  const [schedule,setSchedule]=useState<DailySchedule|null>(null);
  const [hour,setHour]=useState(22);
  const [busy,setBusy]=useState(false);
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState('');
  const [notice,setNotice]=useState('');
  const sequence=useRef(0);
  const requestId=useRef<string|null>(null);
  const reviewId=params.get('reviewId');

  const load=useCallback(async()=>{
    const token=++sequence.current;
    setLoading(true);setError('');setSelected(null);setPreview(null);
    try {
      const [report,items,config,stored]=await Promise.all([api.dailyPreview(subjectId),api.dailyHistory(subjectId),api.dailySchedule(subjectId),reviewId?api.dailyReview(reviewId):Promise.resolve(null)]);
      if(token!==sequence.current)return;
      if(stored && stored.subject_id!==subjectId)throw new Error('这份复盘属于其他科目，请切换科目后查看。');
      setPreview(report);setHistory(items);setHasMore(items.length===30);setSchedule(config);setHour(config.hour);setSelected(stored);
    } catch(reason){if(token===sequence.current)setError(reason instanceof Error?reason.message:'读取失败，请重试。');}
    finally{if(token===sequence.current)setLoading(false);}
  },[subjectId,reviewId]);
  useEffect(()=>{void load();return()=>{sequence.current++;};},[load]);

  async function generate() {
    setBusy(true);setError('');setNotice('');
    requestId.current??=crypto.randomUUID();
    try {
      const saved=await api.createDailyReview(subjectId,requestId.current);
      requestId.current=null;setParams({reviewId:saved.id});setNotice('复盘已保存。计划改期仍需单独确认。');
    } catch(reason){setError(reason instanceof Error?reason.message:'生成失败，请重试。');}
    finally{setBusy(false);}
  }
  async function decide(approve:boolean) {
    if(!selected)return;
    setBusy(true);setError('');setNotice('');
    try {
      const value=await api.decideDailyReview(selected.id,selected.version,approve);setSelected(value);
      setHistory(items=>items.map(item=>item.id===value.id?value:item));
      setNotice(approve?'改期已确认，任务已在计划中锁定。':'已拒绝这份改期建议，计划保持原安排。');
    } catch(reason){setError(reason instanceof Error?reason.message:'操作失败，请重新生成复盘后重试。');}
    finally{setBusy(false);}
  }
  async function saveSchedule(enabled:boolean) {
    if(!schedule)return;
    setBusy(true);setError('');
    try {await api.saveDailySchedule(subjectId,{enabled,hour,version:schedule.version});setSchedule(await api.dailySchedule(subjectId));setNotice(enabled?'自动复盘已开启，只生成报告，不自动改期。':'自动复盘已关闭。');}
    catch(reason){setError(reason instanceof Error?reason.message:'设置失败，请刷新后重试。');}
    finally{setBusy(false);}
  }
  async function more() {
    const last=history.at(-1);if(!last)return;
    setBusy(true);setError('');
    try {const items=await api.dailyHistory(subjectId,last.created_at,last.id);setHistory(current=>[...current,...items]);setHasMore(items.length===30);}
    catch(reason){setError(reason instanceof Error?reason.message:'读取历史失败，请重试。');}
    finally{setBusy(false);}
  }
  async function retryAutomatic() {
    if(!schedule?.latestJob)return;
    setBusy(true);setError('');
    try {await api.retryLearningJob(schedule.latestJob.id);setSchedule(await api.dailySchedule(subjectId));setNotice('已重新排队，生成后可在历史复盘中查看。');}
    catch(reason){setError(reason instanceof Error?reason.message:'无法重试，请手动生成今日复盘。');}
    finally{setBusy(false);}
  }
  const report=selected?.report??preview;
  const canApprove=!!selected && selected.status==='pending' && selected.day===preview?.day && !!report?.requiresConfirmation;
  return <div className="h-full overflow-y-auto bg-slate-50 p-6 md:p-8">
    <header className="mb-7 flex flex-wrap items-start justify-between gap-4">
      <div><h1 className="text-2xl font-bold text-slate-900">学习复盘</h1><p className="mt-2 text-sm text-slate-600">{subjectName} · 依据学习记录回顾进展，安排明日复习</p></div>
      <div className="flex flex-wrap gap-2"><button className={button} disabled={busy||loading} onClick={()=>void load()}>刷新记录</button><button className={primary} disabled={busy||loading} onClick={()=>void generate()}>{busy?'正在处理…':'生成并保存今日复盘'}</button></div>
    </header>
    {error&&<p role="alert" className="mb-4 rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-900">{error} <button type="button" className="min-h-11 px-2 underline" onClick={()=>void load()}>重新读取</button></p>}
    {notice&&<p role="status" className="mb-4 text-sm text-blue-800">{notice}</p>}
    {loading?<p role="status" className="py-8 text-slate-600">正在读取学习记录…</p>:report&&<div className="grid gap-8 xl:grid-cols-[minmax(0,1fr)_280px]">
      <article className="min-w-0 rounded-xl border border-slate-200 bg-white p-5 md:p-7">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b pb-4"><h2 className="text-lg font-semibold">{report.day} · {selected?'已保存的复盘':'当前记录预览'}</h2>{selected&&<span className="text-sm text-slate-600">{stateNames[selected.status]}</span>}</div>
        <p className="mt-3 text-xs leading-5 text-slate-600">按上海时区统计。保存的报告保留生成时状态；学习记录变化后，请重新生成再确认改期。</p>
        <section className="mt-7"><h3 className="mb-3 font-semibold">今日完成</h3><p className="text-sm text-slate-700">完成任务 {report.todaySummary.completedTasks.length} 项 · 今日提交且已评分的测验 {report.todaySummary.submittedTodayGradedAttempts} 次</p>
          {report.todaySummary.completedTasks.length>0&&<ul className="mt-3 space-y-2 text-sm">{report.todaySummary.completedTasks.map(task=><li key={task.id}>{task.title} · 预算 {task.minutes} 分钟</li>)}</ul>}
        </section>
        <section className="mt-8"><h3 className="mb-3 font-semibold">掌握度变化</h3>{report.masteryChanges.length?<ul className="divide-y">{report.masteryChanges.map(change=><li key={change.topicId} className="flex flex-wrap justify-between gap-2 py-3 text-sm"><span>{change.title}</span><span>{change.deltaPoints==null?'缺少历史基线，无法计算变化':`${change.deltaPoints>0?'+':''}${change.deltaPoints} 个百分点`} · {format(change.before)} → {format(change.after)}</span></li>)}</ul>:<p className="text-sm text-slate-600">今天没有可计算变化的掌握度记录。</p>}</section>
        <section className="mt-8"><h3 className="mb-3 font-semibold">仍需巩固</h3>{report.unresolvedProblems.length?<ul className="space-y-3 text-sm">{report.unresolvedProblems.map(topic=><li key={topic.id} className="flex flex-wrap justify-between gap-2"><span>{topic.title} · {topic.state==='at_risk'?'需巩固':format(topic.masteryScore)}</span><Link className="text-blue-700 underline" to={`/guided-study?topicId=${encodeURIComponent(topic.id)}`}>开始引导学习</Link></li>)}</ul>:<p className="text-sm text-slate-600">暂无已评估的薄弱项；未评估不代表已掌握。</p>}</section>
        <section className="mt-8"><h3 className="mb-3 font-semibold">明日安排与考试</h3><p className="text-sm text-slate-700">全部科目已排 {report.feasibility.existingMinutes} 分钟，可用预算 {report.feasibility.capacityMinutes??'尚未设置'}{report.feasibility.capacityMinutes!=null?' 分钟':''}。</p><p className="mt-2 text-xs text-slate-600">分钟数为任务预算，不是实测学习时长。</p>
          {report.feasibility.warnings.map(warning=><p key={warning} className="mt-3 text-sm text-amber-800">{warning}</p>)}
          <ul className="mt-3 space-y-2 text-sm">{report.tomorrowTasks.map(task=><li key={task.id}>{task.title} · {task.minutes} 分钟{task.locked?' · 已锁定':''}{task.status==='completed'?' · 已完成':''}</li>)}</ul>
          {!report.tomorrowTasks.length&&<p className="mt-3 text-sm text-slate-600">当前科目明日暂无任务。</p>}
          {report.tomorrowExams.map(exam=><p key={exam.id} className="mt-3 text-sm font-medium text-amber-800">明日考试：{exam.title}</p>)}
          <div className="mt-3 flex gap-4 text-sm"><Link className="min-h-11 content-center text-blue-700 underline" to="/calendar">设置日历预算</Link><Link className="min-h-11 content-center text-blue-700 underline" to="/plan">查看复习计划</Link></div>
        </section>
        <section className="mt-8 border-t pt-5"><h3 className="mb-3 font-semibold">建议改期</h3>{report.proposedMoves.length?<><ul className="space-y-3 text-sm">{report.proposedMoves.map(move=><li key={move.taskId}><span className="font-medium">{move.title} · {move.minutes} 分钟</span><p className="mt-1 text-slate-600">原定 {move.from}，建议移到复盘日的下一天。{move.reason}</p></li>)}</ul><p className="mt-4 text-sm text-slate-600">确认后将调整日期并锁定这些任务，防止自动重排覆盖；其他安排保持原值。</p>
          <div className="mt-4 flex flex-wrap gap-3"><button className={primary} disabled={busy||!canApprove} onClick={()=>void decide(true)}>确认这些改期</button><button className={button} disabled={busy||!selected||selected.status!=='pending'} onClick={()=>void decide(false)}>拒绝建议</button></div>
          {!selected&&<p className="mt-3 text-sm text-slate-600">先保存今日复盘，再确认改期。</p>}{selected&&selected.day!==preview?.day&&<p className="mt-3 text-sm text-amber-800">历史报告仅供回顾，不能确认过去的改期建议。</p>}</>:<p className="text-sm text-slate-600">当前没有符合容量与保护条件的改期建议。</p>}</section>
      </article>
      <aside className="space-y-7">
        <section className="rounded-xl border bg-white p-5"><h2 className="font-semibold">自动日终复盘</h2><p className="mt-2 text-sm leading-6 text-slate-600">每天按上海时间生成报告。计划改期始终需要你确认。</p><label className="mt-4 block text-sm" htmlFor="review-hour">生成时间</label><select id="review-hour" className="mt-2 min-h-11 w-full rounded-lg border bg-white px-3 text-sm" value={hour} disabled={busy||!schedule} onChange={event=>setHour(Number(event.target.value))}>{Array.from({length:24},(_,h)=><option key={h} value={h}>{String(h).padStart(2,'0')}:00</option>)}</select>
          <div className="mt-3 flex flex-wrap gap-2"><button className={button} disabled={busy||!schedule} onClick={()=>void saveSchedule(true)}>{schedule?.enabled?'保存时间':'开启自动复盘'}</button>{schedule?.enabled&&<button className={button} disabled={busy} onClick={()=>void saveSchedule(false)}>关闭</button>}</div>
          <p className="mt-3 text-xs leading-5 text-slate-600">{schedule?.enabled?'已开启':'未开启'}。调度服务运行时会在设定时间后处理；不会自动补造过去的报告。</p>
          {schedule?.latestJob&&<p className="mt-3 text-sm text-slate-700">最近任务：{schedule.latestJob.day} · {({queued:'等待生成',running:'生成中',succeeded:'已生成',dead:'未完成，可手动生成今日复盘'} as Record<string,string>)[schedule.latestJob.status]??'待检查'}</p>}
          {schedule?.enabled&&schedule.latestJob?.status==='dead'&&schedule.latestJob.day===preview?.day&&<button className={`${button} mt-3`} disabled={busy} onClick={()=>void retryAutomatic()}>重试自动生成</button>}
        </section>
        <section><h2 className="mb-3 font-semibold">历史复盘</h2><button className="mb-2 min-h-11 text-sm text-blue-700 underline" disabled={busy} onClick={()=>setParams({})}>查看今日预览</button>{history.length?<ul className="divide-y rounded-xl border bg-white">{history.map(item=><li key={item.id}><button className="min-h-11 w-full px-4 py-3 text-left text-sm text-blue-800 hover:bg-blue-50 focus-visible:outline-2 focus-visible:outline-blue-600" disabled={busy} onClick={()=>setParams({reviewId:item.id})}>{item.day} · {stateNames[item.status]}<span className="mt-1 block text-xs text-blue-900">{new Date(item.created_at).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})}</span></button></li>)}</ul>:<p className="text-sm text-slate-600">暂无已保存报告。</p>}{hasMore&&<button className={`${button} mt-3`} disabled={busy} onClick={()=>void more()}>加载更早记录</button>}</section>
      </aside>
    </div>}
  </div>;
}
