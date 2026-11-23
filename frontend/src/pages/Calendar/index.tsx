import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api } from '../../api/client';
import { useAppStore } from '../../stores/useAppStore';
import type { Subject } from '../../types';
import type { CalendarData, CalendarDay, CalendarTask } from '../../types/calendar';
import { Syllabus } from './Syllabus';

const control='min-h-11 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600 disabled:opacity-50';
const weekdays=['一','二','三','四','五','六','日'];
function shanghaiToday(){return new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());}
function addDays(day:string,amount:number){const value=new Date(day+'T00:00:00Z');value.setUTCDate(value.getUTCDate()+amount);return value.toISOString().slice(0,10);}
function gridStart(month:string){const value=new Date(month+'-01T00:00:00Z');return addDays(month+'-01',-((value.getUTCDay()+6)%7));}

function DayAgenda({day,today,onSaved,onOpen,subjectNames}:{day:CalendarDay;today:string;onSaved:()=>void;onOpen:(subjectId:string,href:string)=>void;subjectNames:Record<string,string>}){
  const [minutes,setMinutes]=useState(day.minutes===null?'':String(day.minutes));
  const [target,setTarget]=useState(today);
  const [busy,setBusy]=useState('');
  const [error,setError]=useState('');
  async function save(){
    setBusy('availability');setError('');
    try{await api.saveAvailability(day.date,Number(minutes),day.version);onSaved();}
    catch(reason){setError(reason instanceof Error?reason.message:'时间保存失败，请刷新后重试。');}
    finally{setBusy('');}
  }
  async function move(task:CalendarTask){
    setBusy(task.id);setError('');
    try{await api.moveCalendarTask(task.id,target,task.planVersion);onSaved();}
    catch(reason){setError(reason instanceof Error?reason.message:'改期失败，请刷新后重试。');}
    finally{setBusy('');}
  }
  return <section aria-label="当天任务" className="min-w-0 border-l border-slate-200 bg-white p-5">
    <h2 className="text-lg font-semibold">{day.date} 的学习安排</h2>
    <p className="mt-2 text-sm leading-6 text-slate-600">全部科目已安排 {day.plannedMinutes} 分钟{day.minutes===null?' · 尚未设置可用时间':` / 可用 ${day.minutes} 分钟`}。此预算包含当日已完成任务，不包含闪卡预计耗时。</p>
    {day.overCapacity&&<p role="status" className="mt-3 text-sm font-semibold text-rose-800">任务总时长超过可用时间。请增加时间，或改期尚未开始的自动任务。</p>}
    {day.examConflict&&<p className="mt-3 text-sm text-amber-800">全部科目当天有多场考试，请核对具体时段。本轮仅记录考试日期。</p>}
    {day.date>=today&&<div className="mt-4 flex flex-wrap items-end gap-3">
      <label className="flex flex-col gap-2 text-sm">当天可用分钟<input type="number" min={0} max={1440} className={`${control} w-36`} disabled={Boolean(busy)} value={minutes} onChange={event=>setMinutes(event.target.value)}/>
</label>
      <button type="button" className={control} disabled={Boolean(busy)||minutes===''||!Number.isInteger(Number(minutes))||Number(minutes)<0||Number(minutes)>1440} onClick={()=>void save()}>{busy==='availability'?'正在保存…':'保存时间'}</button>
    </div>}
    {error&&<p role="alert" className="mt-4 text-sm text-rose-800">{error}</p>}
    {day.exams.map(exam=>
<div key={exam.id} className="mt-5 border-t border-slate-200 pt-4">
<p className="text-sm font-semibold text-blue-800">考试 · {exam.title}</p>
<p className="mt-1 text-sm text-slate-600">{subjectNames[exam.subject_id]}</p>
<button type="button" className={`${control} mt-2 text-blue-700`} onClick={()=>onOpen(exam.subject_id,`/plan?examEventId=${encodeURIComponent(exam.id)}`)}>查看考试复习计划</button>
</div>)}
    {day.dueCards>0&&<div className="mt-5 text-sm text-slate-700">
<p>{day.dueCards} 张闪卡在当天到期；今天的数量也包含逾期卡片。</p>
<div className="mt-2 flex flex-wrap gap-2">{day.dueSubjects.map(row=>
<button type="button" key={row.subject_id} className={`${control} text-blue-700`} onClick={()=>onOpen(row.subject_id,'/flashcards')}>复习 {subjectNames[row.subject_id]} · {row.count} 张</button>)}</div>
</div>}
    {!day.tasks.length&&!day.exams.length&&!day.dueCards&&<p className="mt-6 text-sm text-slate-600">当天没有已安排的学习活动。可以先设置可用时间，再到复习计划安排任务。</p>}
    <ul className="mt-4 divide-y divide-slate-200">{day.tasks.map(task=>
<li key={task.id} className="py-5">
      <p className="text-sm font-semibold">{task.title}</p>
      <p className="mt-2 text-sm text-slate-600">{subjectNames[task.subject_id]} · {task.estimated_minutes} 分钟 · {task.status==='completed'?'已完成':task.status==='skipped'?'已跳过':day.date<today?'已逾期':'待完成'}{task.locked?' · 已锁定':''}{task.source==='user'?' · 手工任务':''}</p>
      <button type="button" className={`${control} mt-3 text-blue-700`} onClick={()=>onOpen(task.subject_id,task.knowledge_point_id?`/guided-study?topicId=${encodeURIComponent(task.knowledge_point_id)}`:'/plan')}>进入学习</button>
      {task.source==='system'&&!task.locked&&['pending','overdue'].includes(task.status)&&task.planExamDate>=today&&<div className="mt-3 flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-2 text-sm">改到哪一天<input type="date" min={today} max={task.planExamDate} className={control} disabled={Boolean(busy)} value={target} onChange={event=>setTarget(event.target.value)}/>
</label>
        <button type="button" className={control} disabled={Boolean(busy)||!target||target<today||target===day.date} onClick={()=>void move(task)}>{busy===task.id?'正在改期…':'改期并锁定'}</button>
      </div>}
      {task.planExamDate<today&&['pending','overdue'].includes(task.status)&&<p className="mt-3 text-sm text-amber-800">计划目标日期已过，请在复习计划中重新设置目标。</p>}
    </li>)}</ul>
    <p className="mt-3 text-sm leading-6 text-slate-600">改期前请先设置目标日可用时间。改期不计为完成；锁定后自动重排会保留日期。</p>
  </section>;
}

export default function Calendar(){
  const current=useAppStore(state=>state.currentSubject);
  const navigate=useNavigate();
  const [month,setMonth]=useState(shanghaiToday().slice(0,7));
  const [selected,setSelected]=useState(shanghaiToday());
  const [all,setAll]=useState(true);
  const [subjects,setSubjects]=useState<Subject[]>([]);
  const [data,setData]=useState<CalendarData|null>(null);
  const [error,setError]=useState('');
  const [loading,setLoading]=useState(true);
  const [reload,setReload]=useState(0);
  const start=gridStart(month);
  useEffect(()=>{let stopped=false;api.subjects().then(values=>{if(!stopped)setSubjects(values);}).catch(reason=>{if(!stopped)setError(reason.message);});return()=>{stopped=true;};},[]);
  useEffect(()=>{
    let stopped=false;setLoading(true);setError('');
    api.calendar(start,addDays(start,41),all?undefined:current?.id).then(value=>{if(!stopped)setData(value);})
      .catch(reason=>{if(!stopped)setError(reason instanceof Error?reason.message:'日历加载失败，请重试。');})
      .finally(()=>{if(!stopped)setLoading(false);});
    return()=>{stopped=true;};
  },[start,all,current?.id,reload]);
  function open(subjectId:string,href:string){const subject=subjects.find(row=>row.id===subjectId);if(!subject){setError('科目信息未读取完成，请刷新后重试。');return;}useAppStore.getState().setCurrentSubject(subject);navigate(href);}
  function changeMonth(amount:number){const date=new Date(month+'-01T00:00:00Z');date.setUTCMonth(date.getUTCMonth()+amount);const value=date.toISOString().slice(0,7);setMonth(value);setSelected(value+'-01');}
  const day=data?.days.find(row=>row.date===selected);
  const subjectNames=Object.fromEntries(subjects.map(row=>[row.id,row.name]));
  return <div className="h-full overflow-y-auto bg-slate-50 p-6 lg:p-8">
    <header>
<h1 className="text-2xl font-bold text-slate-950">学习日历</h1>
<p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">把考试、复习任务和到期闪卡放在同一张日历上，按每天真实可用时间安排学习。日期均以北京时间显示。</p>
</header>
    <div className="my-6 flex flex-wrap items-center gap-3">
      <button type="button" className={control} disabled={month<='2000-01'} onClick={()=>changeMonth(-1)} aria-label="上个月">上个月</button>
      <label className="flex items-center gap-2 text-sm">月份<input type="month" min="2000-01" max="2100-12" className={control} value={month} onChange={event=>{const value=event.target.value;if(/^\d{4}-(0[1-9]|1[0-2])$/.test(value)&&value>='2000-01'&&value<='2100-12'){setMonth(value);setSelected(value+'-01');}}}/>
</label>
      <button type="button" className={control} disabled={month>='2100-12'} onClick={()=>changeMonth(1)} aria-label="下个月">下个月</button>
      <button type="button" className={control} onClick={()=>{const today=shanghaiToday();setMonth(today.slice(0,7));setSelected(today);}}>今天</button>
      <label className="ml-auto flex min-h-11 items-center gap-2 text-sm">
<input type="checkbox" checked={all} disabled={!current} onChange={event=>setAll(event.target.checked)}/>查看全部科目</label>
      <button type="button" className={control} disabled={loading} onClick={()=>setReload(value=>value+1)}>刷新日历</button>
    </div>
    <p className="mb-4 text-sm text-slate-600">可用时间由全部科目共享；切换筛选不会改变容量统计。没有设置时间的日期不作容量承诺。</p>
    {error&&<p role="alert" className="mb-4 text-sm text-rose-800">{error}</p>}
    {loading?<p role="status" className="py-12 text-slate-600">正在读取日历…</p>:!error&&data&&<div className="grid border border-slate-200 bg-white xl:grid-cols-[minmax(0,1.3fr)_minmax(320px,1fr)]">
      <section aria-label="月历" className="min-w-0 p-4">
<div className="grid grid-cols-7">{weekdays.map(label=>
<div key={label} className="py-3 text-center text-sm font-semibold text-slate-600">周{label}</div>)}</div>
        <div className="grid grid-cols-7 border-l border-t border-slate-200">{data.days.map(row=>
<button type="button" key={row.date} aria-label={`${row.date}，${row.tasks.length} 项任务，${row.exams.length} 场考试，${row.dueCards} 张到期闪卡${row.overCapacity?'，超过可用时间':''}`} aria-pressed={selected===row.date} onClick={()=>setSelected(row.date)} className={`min-h-28 min-w-0 border-b border-r border-slate-200 px-2 py-3 text-left text-sm focus-visible:z-10 focus-visible:outline-2 focus-visible:outline-blue-600 ${selected===row.date?'bg-blue-50 text-blue-950':row.date.slice(0,7)!==month?'bg-slate-50 text-slate-500':'text-slate-800 hover:bg-slate-50'}`}>
          <span className={row.date===data.today?'font-bold underline underline-offset-4':'font-semibold'}>{Number(row.date.slice(-2))}</span>
          {row.exams.length>0&&<span className="mt-1 block text-xs font-semibold text-blue-800">{row.exams.length} 场考试</span>}
          {row.tasks.length>0&&<span className="mt-1 block text-xs">{row.tasks.length} 项任务</span>}
          {row.dueCards>0&&<span className="mt-1 block text-xs">{row.dueCards} 张闪卡</span>}
          {row.overCapacity&&<span className="mt-1 block text-xs font-semibold text-rose-800">时间不足</span>}
          {row.missedCount>0&&<span className="mt-1 block text-xs text-amber-800">{row.missedCount} 项逾期</span>}
        </button>)}</div>
      </section>
      {day&&<DayAgenda key={`${day.date}:${day.version}:${reload}`} day={day} today={data.today} subjectNames={subjectNames} onSaved={()=>setReload(value=>value+1)} onOpen={open}/>}
    </div>}
    {current?<Syllabus key={current.id} subjectId={current.id} subjectName={current.name} onConfirmed={()=>setReload(value=>value+1)}/>:<p className="mt-8 text-sm text-slate-600">选择当前科目后，可以从大纲提取考试。<Link to="/" className="ml-2 text-blue-700 underline">前往科目首页</Link>
</p>}
  </div>;
}
