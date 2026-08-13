import { useEffect, useState } from 'react';
import { CheckCircle2, Clock, Play, Settings2 } from 'lucide-react';
import { api } from '../../api/client';
import { useAppStore } from '../../stores/useAppStore';
import type { Exam } from '../../types';

export default function Exams() {
  const subject = useAppStore((state) => state.currentSubject)!;
  const [items, setItems] = useState<Exam[]>([]);
  const [count, setCount] = useState(10);
  const [difficulty, setDifficulty] = useState('medium');
  const [busy, setBusy] = useState(false);

  useEffect(() => { void api.exams(subject.id).then(setItems); }, [subject.id]);

  async function generate() {
    setBusy(true);
    try {
      const created = await api.createExam({ subject_id: subject.id, question_count: count, difficulty });
      setItems((rows) => [created, ...rows]);
    } finally {
      setBusy(false);
    }
  }

  return <div className="h-full overflow-y-auto p-6 md:p-8">
    <header className="mb-8"><h1 className="text-3xl font-bold">练习与模拟考试</h1><p className="mt-2 text-slate-500">基于 {subject.name} 的资料生成针对性练习。</p></header>
    <div className="grid gap-7 lg:grid-cols-[2fr_1fr]">
      <section className="rounded-2xl border bg-white p-6 shadow-sm">
        <h2 className="mb-6 flex items-center border-b pb-4 text-xl font-bold"><Settings2 className="mr-3 text-blue-600"/>生成新练习</h2>
        <div className="grid gap-5 sm:grid-cols-2">
          <label className="text-sm font-medium">题目数量<select value={count} onChange={(event) => setCount(Number(event.target.value))} className="mt-2 w-full rounded-xl border p-3"><option value={10}>10 题</option><option value={20}>20 题</option><option value={50}>50 题</option></select></label>
          <label className="text-sm font-medium">难度<select value={difficulty} onChange={(event) => setDifficulty(event.target.value)} className="mt-2 w-full rounded-xl border p-3"><option value="easy">基础</option><option value="medium">中等</option><option value="hard">困难</option></select></label>
        </div>
        <button disabled={busy} onClick={() => void generate()} className="mt-7 flex w-full items-center justify-center rounded-xl bg-blue-600 py-4 text-lg font-bold text-white"><Play size={20} className="mr-2"/>{busy ? '正在生成…' : '生成练习'}</button>
        <p className="mt-3 text-center text-xs text-slate-400">当前为接口占位，后续接入真实出题服务。</p>
      </section>
      <aside className="rounded-2xl border bg-white p-6"><h2 className="mb-4 font-bold">最近记录</h2><div className="space-y-3">{items.map((exam) => <div key={exam.id} className="rounded-xl border bg-slate-50 p-4"><div className="flex justify-between"><b>{exam.title}</b>{exam.score != null && <span className="text-emerald-600">{exam.score} 分</span>}</div><div className="mt-2 flex items-center text-xs text-slate-500">{exam.score != null ? <CheckCircle2 size={14} className="mr-1"/> : <Clock size={14} className="mr-1"/>}{exam.questionCount} 题 · {exam.status || exam.createdAt}</div></div>)}</div></aside>
    </div>
  </div>;
}
