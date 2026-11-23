import { FormEvent, useEffect, useRef, useState } from 'react';
import { observeRecommendationImpressions } from '../../api/recommendationExposure';
import { BarChart3, BookOpen, ChevronRight, Clock, Flame, Plus, X } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { api } from '../../api/client';
import { useAppStore } from '../../stores/useAppStore';
import type { DashboardData, RecommendationData, FlashcardQueue } from '../../types';

export default function Dashboard() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [recommendations, setRecommendations] = useState<RecommendationData | null>(null);
  const [recommendationError, setRecommendationError] = useState('');
  const [flashcards, setFlashcards] = useState<FlashcardQueue | null>(null);
  const [flashcardError, setFlashcardError] = useState('');
  const [error, setError] = useState('');
  const [creating, setCreating] = useState(false);
  const { setCurrentSubject } = useAppStore();
  const navigate = useNavigate();
  const recommendationRoot = useRef<HTMLElement>(null);
  useEffect(() => {
    if (!recommendationRoot.current || !recommendations) return;
    return observeRecommendationImpressions(recommendationRoot.current, id => api.recommendationFeedback(id, 'impression'));
  }, [recommendations]);
  const load = () => {
    void api.flashcardQueue().then(value => { setFlashcards(value); setFlashcardError(''); })
      .catch(e => { setFlashcards(null); setFlashcardError(e.message); });
    void api.nextActions().then((value) => { setRecommendations(value); setRecommendationError(''); })
      .catch((e) => { setRecommendations(null); setRecommendationError(e.message); });
    return api.dashboard().then((nextData) => {
    const selected = useAppStore.getState().currentSubject;
    if (selected && !nextData.subjects.some((subject) => subject.id === selected.id)) {
      setCurrentSubject(null);
    }
    setError('');
    setData(nextData);
    }).catch((e) => setError(e.message));
  };
  useEffect(() => { void load(); }, []);
  async function create(event: FormEvent<HTMLFormElement>) { event.preventDefault(); const form = new FormData(event.currentTarget); await api.createSubject({ name: String(form.get('name')), description: String(form.get('description')) }); setCreating(false); load(); }
  function start(subjectId: string, href: string, recommendationId?: string) {
    const subject = data?.subjects.find((item) => item.id === subjectId);
    if (!subject) { setError('学科列表尚未准备好，请刷新后重试。'); return; }
    if (recommendationId) void api.recommendationFeedback(recommendationId, 'clicked').catch(() => {});
    setCurrentSubject(subject); navigate(href);
  }
  return <div className="h-full overflow-y-auto p-6 md:p-8">
    <header className="mb-8 flex flex-wrap items-center justify-between gap-4"><div><h1 className="text-3xl font-bold tracking-tight">准备开始今天的复习了吗？</h1><p className="mt-2 text-slate-500">选择一个学科进入专属学习工作区。</p></div><button onClick={() => setCreating(true)} className="flex items-center rounded-xl bg-blue-600 px-4 py-2.5 font-medium text-white hover:bg-blue-700"><Plus size={18} className="mr-2"/>创建学科</button></header>
    {error && <div className="mb-5 rounded-xl bg-rose-50 p-4 text-rose-700">{error}</div>}
    <section ref={recommendationRoot} className="mb-8" aria-labelledby="next-action-heading">
      <div className="mb-3 flex items-center justify-between gap-3"><h2 id="next-action-heading" className="text-xl font-bold">现在建议做什么</h2><button type="button" onClick={() => void load()} className="min-h-11 rounded-lg px-3 text-sm font-medium text-blue-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600">刷新建议</button></div>
      {recommendationError ? <p role="alert" className="text-sm text-rose-800">建议暂时无法读取：{recommendationError}</p> : !recommendations ? <p role="status" className="text-sm text-slate-600">正在结合考试目标与学习记录安排下一步…</p> : <>
        {recommendations.coldStart && <p className="mb-4 text-sm text-slate-600">评估记录较少，当前建议用于建立学习基线。完成练习后，建议会根据结果调整。</p>}
        {recommendations.actions.length === 0 ? <p className="py-4 text-slate-600">当前没有需要优先处理的知识点。可以设置新的考试目标，或继续执行复习计划。</p> :
          <ol className="divide-y divide-slate-200 border-y border-slate-200">
            {recommendations.actions.map((action, index) =>
              <li key={action.id} data-recommendation-id={action.recommendationId} className={`flex flex-wrap items-center justify-between gap-5 p-4 ${index === 0 ? 'bg-blue-50' : ''}`}>
                <div className="min-w-0 flex-1">
                  <h3 className="break-words text-lg font-semibold">{action.title}</h3>
                  <p className="mt-1 text-sm text-blue-950/80">{action.subjectName} · 预计 {action.estimatedMinutes} 分钟</p>
                  <ul className="mt-3 space-y-1 text-sm text-blue-950">{action.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>
                </div>
                <button type="button" disabled={!data} onClick={() => start(action.subjectId, action.href, action.recommendationId)} className="min-h-11 rounded-lg bg-blue-600 px-5 text-sm font-semibold text-white hover:bg-blue-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600">开始<span className="sr-only">{action.title}</span></button>
              </li>
            )}
          </ol>
        }
        <div className="mt-5 grid gap-6 lg:grid-cols-3"><div><h3 className="font-semibold">即将到来的考试</h3>{recommendations.upcomingExams.length ? <ul className="mt-2 space-y-2 text-sm">{recommendations.upcomingExams.map((exam) => <li key={exam.id}><button type="button" onClick={() => start(exam.subjectId, '/course')} className="min-h-11 text-left text-blue-700 underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-blue-600">{exam.title} · {exam.examDate}<span className="block text-slate-600">{exam.subjectName}</span></button></li>)}</ul> : <p className="mt-2 text-sm text-slate-600">在课程结构中设置考试目标。</p>}</div><div><h3 className="font-semibold">到期复习与薄弱点</h3><p className="mt-2 text-sm text-slate-600">{recommendations.dueReviewCount} 个知识点已到期</p><ul className="mt-2 space-y-2 text-sm">{recommendations.weakTopics.map((topic) => <li key={topic.knowledgePointId}><button type="button" onClick={() => start(topic.subjectId, `/exams?topic=${encodeURIComponent(topic.title)}`)} className="min-h-11 text-left text-blue-700 underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-blue-600">{topic.title} · 掌握度 {Math.round(topic.masteryScore * 100)}%</button></li>)}</ul></div><div><h3 className="font-semibold">今日待办</h3>{recommendations.todayTasks.length ? <ul className="mt-2 space-y-2 text-sm">{recommendations.todayTasks.map((task) => <li key={task.id}><button type="button" onClick={() => start(task.subjectId, '/plan')} className="min-h-11 text-left text-blue-700 underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-blue-600">{task.title} · {task.estimatedMinutes} 分钟</button></li>)}</ul> : <p className="mt-2 text-sm text-slate-600">暂无待办复习任务。</p>}</div></div>
      </>}
    </section>
    {data && <div className="mb-7 grid gap-4 sm:grid-cols-3"><Stat icon={Clock} label="今日学习" value={`${data.stats.studyMinutes} 分钟`}/><Stat icon={BarChart3} label="完成任务" value={`${data.stats.completedTasks} 项`}/><Stat icon={Flame} label="连续学习" value={`${data.stats.streakDays} 天`}/></div>}
    <section className="mb-8" aria-labelledby="due-card-heading"><h2 id="due-card-heading" className="text-xl font-bold">到期闪卡</h2>{flashcardError ? <p role="alert" className="mt-3 text-sm text-rose-800">闪卡队列暂时无法读取：{flashcardError}</p> : !flashcards ? <p role="status" className="mt-3 text-sm text-slate-600">正在读取复习安排…</p> : <><p className="mt-2 text-sm text-slate-600">当前 {flashcards.dueCount} 张到期卡片。</p><ul className="mt-3 divide-y divide-slate-200">{flashcards.subjects.filter(subject => subject.due > 0).map(subject => <li key={subject.subject_id} className="flex items-center justify-between gap-4 py-3"><span>{subject.subject_name} · {subject.due} 张到期 · {subject.overdue} 张逾期</span><button type="button" className="min-h-11 rounded-lg px-3 font-semibold text-blue-700 focus-visible:outline-2 focus-visible:outline-blue-600" onClick={() => start(subject.subject_id, '/flashcards')}>开始复习</button></li>)}</ul></>}</section>
    <h2 className="mb-4 text-xl font-bold">我的学科</h2>
    {!data ? <div className="text-slate-400">正在加载工作台…</div> : <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">{data.subjects.map((subject) => <button key={subject.id} onClick={() => { setCurrentSubject(subject); navigate('/study-room'); }} className="group rounded-2xl border border-slate-200 bg-white p-6 text-left shadow-sm transition hover:-translate-y-1 hover:border-blue-300 hover:shadow-lg">
      <div className="mb-4 flex items-start justify-between"><div className="grid h-12 w-12 place-items-center rounded-xl bg-blue-50 text-blue-600"><BookOpen/></div><ChevronRight className="text-slate-300 group-hover:text-blue-500"/></div><h3 className="text-xl font-bold">{subject.name}</h3><p className="mt-1 h-11 text-sm text-slate-500">{subject.description}</p><div className="mt-5 flex justify-between text-sm"><span>总体进度</span><b>{subject.progress}%</b></div><div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full bg-blue-500" style={{ width: `${subject.progress}%` }}/></div><div className="mt-4 text-xs text-emerald-600">掌握度 {subject.mastery}%</div>
    </button>)}</div>}
    {creating && <div className="fixed inset-0 z-50 grid place-items-center bg-slate-900/30 p-4"><form onSubmit={create} className="w-full max-w-md rounded-2xl bg-white p-6 shadow-2xl"><div className="mb-5 flex justify-between"><h2 className="text-xl font-bold">创建新学科</h2><button type="button" onClick={() => setCreating(false)}><X/></button></div><label className="block text-sm font-medium">学科名称<input name="name" required className="mt-2 w-full rounded-xl border border-slate-200 p-3"/></label><label className="mt-4 block text-sm font-medium">描述<textarea name="description" className="mt-2 w-full rounded-xl border border-slate-200 p-3"/></label><button className="mt-5 w-full rounded-xl bg-blue-600 py-3 font-bold text-white">创建</button></form></div>}
  </div>;
}

function Stat({ icon: Icon, label, value }: { icon: typeof Clock; label: string; value: string }) { return <div className="flex items-center rounded-2xl border border-slate-200 bg-white p-4"><div className="mr-4 rounded-xl bg-blue-50 p-3 text-blue-600"><Icon size={21}/></div><div><div className="text-sm text-slate-500">{label}</div><div className="text-lg font-bold">{value}</div></div></div>; }
