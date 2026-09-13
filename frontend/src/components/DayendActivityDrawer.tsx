import { FormEvent, useMemo, useState } from 'react';
import { Check, LoaderCircle, Moon, Send, TriangleAlert, X } from 'lucide-react';
import { api, DayendActivity } from '../api/client';

type Props = { open: boolean; onClose: () => void };

const agentNames: Record<string, string> = {
  supervisor_agent: '统筹', closure_agent: '收尾', planning_agent: '规划', emotion_agent: '情绪', safety_agent: '安全', critic_agent: '复核',
};

export function DayendActivityDrawer({ open, onClose }: Props) {
  const [input, setInput] = useState('');
  const [events, setEvents] = useState<DayendActivity[]>([]);
  const [threadId, setThreadId] = useState<string>();
  const [confirming, setConfirming] = useState(false);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState('');
  const pending = useMemo(() => [...events].reverse().find((item) => item.event === 'confirmation_required'), [events]);

  if (!open) return null;

  async function start(event: FormEvent) {
    event.preventDefault();
    if (!input.trim()) return;
    setEvents([]); setError(''); setRunning(true); setThreadId(undefined);
    try {
      await api.streamDayendRun({ userInput: input.trim(), entryPoint: 'night' }, (activity) => {
        setEvents((current) => [...current, activity]);
        const id = activity.data.threadId;
        if (typeof id === 'string') setThreadId(id);
      });
    } catch (cause) { setError(cause instanceof Error ? cause.message : '夜间流程暂时不可用。'); }
    finally { setRunning(false); }
  }

  async function confirm() {
    if (!threadId) return;
    setConfirming(true); setError('');
    try {
      await api.resumeDayendRun(threadId, { confirmed: true });
      setEvents((current) => [...current, { event: 'run_completed', data: { threadId } }]);
    } catch (cause) { setError(cause instanceof Error ? cause.message : '确认未提交，请重试。'); }
    finally { setConfirming(false); }
  }

  return <div className="fixed inset-0 z-50 flex justify-end bg-slate-950/25" role="presentation" onMouseDown={onClose}>
    <aside className="flex h-full w-full max-w-md flex-col bg-white shadow-2xl" role="dialog" aria-modal="true" aria-label="夜间流程活动" onMouseDown={(event) => event.stopPropagation()}>
      <header className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
        <div><h2 className="text-lg font-bold text-slate-900">夜间流程</h2><p className="mt-0.5 text-sm text-slate-500">记录今天，整理明天的行动。</p></div>
        <button type="button" onClick={onClose} aria-label="关闭夜间流程" className="rounded-lg p-2 text-slate-500 hover:bg-slate-100 focus-visible:outline-2 focus-visible:outline-blue-600"><X size={20}/></button>
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5">
        <form onSubmit={start} className="space-y-3">
          <label htmlFor="dayend-input" className="text-sm font-semibold text-slate-800">今天想收尾什么？</label>
          <textarea id="dayend-input" value={input} onChange={(event) => setInput(event.target.value)} maxLength={8000} rows={5} placeholder="例如：完成了高数第三章，但特征值部分仍然不稳……" className="w-full resize-none rounded-xl border border-slate-300 bg-slate-50 px-3 py-3 text-sm leading-6 text-slate-900 outline-none placeholder:text-slate-400 focus:border-blue-600 focus:bg-white focus:ring-2 focus:ring-blue-100" />
          <button disabled={running || !input.trim()} className="flex min-h-10 w-full items-center justify-center gap-2 rounded-xl bg-slate-900 px-4 text-sm font-semibold text-white transition hover:bg-slate-700 disabled:cursor-not-allowed disabled:bg-slate-300"><Moon size={16}/>{running ? '正在协调各角色…' : '开始夜间整理'}<Send size={15}/></button>
        </form>
        {error && <p role="alert" className="mt-4 flex gap-2 rounded-xl bg-red-50 p-3 text-sm leading-5 text-red-800"><TriangleAlert className="mt-0.5 shrink-0" size={17}/>{error}</p>}
        {pending && <section className="mt-5 rounded-xl bg-amber-50 p-4" aria-live="polite"><h3 className="font-semibold text-amber-950">需要你的确认</h3><p className="mt-1 text-sm leading-6 text-amber-900">系统已整理待确认内容；确认后会继续生成明日计划。</p><button type="button" disabled={confirming} onClick={confirm} className="mt-3 flex min-h-10 items-center gap-2 rounded-lg bg-amber-900 px-4 text-sm font-semibold text-white hover:bg-amber-800 disabled:bg-amber-500"><Check size={16}/>{confirming ? '正在继续…' : '确认并继续'}</button></section>}
        {events.length > 0 && <section className="mt-6"><h3 className="text-sm font-semibold text-slate-800">实时进度</h3><ol className="mt-3 space-y-3 border-l border-slate-200 pl-4">{events.map((item, index) => <li key={`${item.event}-${index}`} className="relative text-sm text-slate-600"><span className="absolute -left-[21px] top-1 h-2.5 w-2.5 rounded-full bg-blue-600" />{item.event === 'agent_completed' ? `${agentNames[String(item.data.agent)] || String(item.data.agent)}已完成` : item.event === 'agent_started' ? `正在处理：${String(item.data.node)}` : item.event === 'confirmation_required' ? '等待你的确认' : item.event === 'run_completed' ? '流程已完成' : item.event === 'run_failed' ? `流程未完成：${String(item.data.message || '请稍后重试')}` : String(item.data.node || item.event)}</li>)}</ol></section>}
        {running && <div className="mt-5 flex items-center gap-2 text-sm text-slate-500"><LoaderCircle size={16} className="animate-spin"/>保持此面板打开以查看实时进度。</div>}
      </div>
    </aside>
  </div>;
}
