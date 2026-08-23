import { FormEvent, useEffect, useState } from 'react';
import { BarChart3, BookOpen, ChevronRight, Clock, Flame, Plus, X } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { api } from '../../api/client';
import { useAppStore } from '../../stores/useAppStore';
import type { DashboardData } from '../../types';

export default function Dashboard() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState('');
  const [creating, setCreating] = useState(false);
  const { setCurrentSubject } = useAppStore();
  const navigate = useNavigate();
  const load = () => api.dashboard().then((nextData) => {
    const selected = useAppStore.getState().currentSubject;
    if (selected && !nextData.subjects.some((subject) => subject.id === selected.id)) {
      setCurrentSubject(null);
    }
    setError('');
    setData(nextData);
  }).catch((e) => setError(e.message));
  useEffect(() => { void load(); }, []);
  async function create(event: FormEvent<HTMLFormElement>) { event.preventDefault(); const form = new FormData(event.currentTarget); await api.createSubject({ name: String(form.get('name')), description: String(form.get('description')) }); setCreating(false); load(); }
  return <div className="h-full overflow-y-auto p-6 md:p-8">
    <header className="mb-8 flex flex-wrap items-center justify-between gap-4"><div><h1 className="text-3xl font-bold tracking-tight">准备开始今天的复习了吗？</h1><p className="mt-2 text-slate-500">选择一个学科进入专属学习工作区。</p></div><button onClick={() => setCreating(true)} className="flex items-center rounded-xl bg-blue-600 px-4 py-2.5 font-medium text-white hover:bg-blue-700"><Plus size={18} className="mr-2"/>创建学科</button></header>
    {error && <div className="mb-5 rounded-xl bg-rose-50 p-4 text-rose-700">{error}</div>}
    {data && <div className="mb-7 grid gap-4 sm:grid-cols-3"><Stat icon={Clock} label="今日学习" value={`${data.stats.studyMinutes} 分钟`}/><Stat icon={BarChart3} label="完成任务" value={`${data.stats.completedTasks} 项`}/><Stat icon={Flame} label="连续学习" value={`${data.stats.streakDays} 天`}/></div>}
    <h2 className="mb-4 text-xl font-bold">我的学科</h2>
    {!data ? <div className="text-slate-400">正在加载工作台…</div> : <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">{data.subjects.map((subject) => <button key={subject.id} onClick={() => { setCurrentSubject(subject); navigate('/study-room'); }} className="group rounded-2xl border border-slate-200 bg-white p-6 text-left shadow-sm transition hover:-translate-y-1 hover:border-blue-300 hover:shadow-lg">
      <div className="mb-4 flex items-start justify-between"><div className="grid h-12 w-12 place-items-center rounded-xl bg-blue-50 text-blue-600"><BookOpen/></div><ChevronRight className="text-slate-300 group-hover:text-blue-500"/></div><h3 className="text-xl font-bold">{subject.name}</h3><p className="mt-1 h-11 text-sm text-slate-500">{subject.description}</p><div className="mt-5 flex justify-between text-sm"><span>总体进度</span><b>{subject.progress}%</b></div><div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full bg-blue-500" style={{ width: `${subject.progress}%` }}/></div><div className="mt-4 text-xs text-emerald-600">掌握度 {subject.mastery}%</div>
    </button>)}</div>}
    {creating && <div className="fixed inset-0 z-50 grid place-items-center bg-slate-900/30 p-4"><form onSubmit={create} className="w-full max-w-md rounded-2xl bg-white p-6 shadow-2xl"><div className="mb-5 flex justify-between"><h2 className="text-xl font-bold">创建新学科</h2><button type="button" onClick={() => setCreating(false)}><X/></button></div><label className="block text-sm font-medium">学科名称<input name="name" required className="mt-2 w-full rounded-xl border border-slate-200 p-3"/></label><label className="mt-4 block text-sm font-medium">描述<textarea name="description" className="mt-2 w-full rounded-xl border border-slate-200 p-3"/></label><button className="mt-5 w-full rounded-xl bg-blue-600 py-3 font-bold text-white">创建</button></form></div>}
  </div>;
}

function Stat({ icon: Icon, label, value }: { icon: typeof Clock; label: string; value: string }) { return <div className="flex items-center rounded-2xl border border-slate-200 bg-white p-4"><div className="mr-4 rounded-xl bg-blue-50 p-3 text-blue-600"><Icon size={21}/></div><div><div className="text-sm text-slate-500">{label}</div><div className="text-lg font-bold">{value}</div></div></div>; }
