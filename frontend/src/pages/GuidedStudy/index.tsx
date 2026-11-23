import { useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { LoaderCircle, RefreshCw } from 'lucide-react';
import { api } from '../../api/client';
import { useAppStore } from '../../stores/useAppStore';
import { FlashcardReviewPanel } from '../../components/FlashcardReviewPanel';
import { MarkdownViewer } from '../../components/MarkdownViewer';
import { ExamQuestionList } from '../Exams/components/ExamQuestionList';
import type { CourseTopic, ExamAttempt, StudySession, ScheduledFlashcard } from '../../types';

const button = 'min-h-11 rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600 disabled:opacity-50';
const secondary = 'min-h-11 rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-100 focus-visible:outline-2 focus-visible:outline-blue-600 disabled:opacity-50';
const input = 'min-h-11 rounded-lg border border-slate-300 bg-white px-3 py-2 text-slate-900 focus:outline-2 focus:outline-blue-600';
const stateLabels: Record<string, string> = { not_started: '尚未开始', covered: '已学习', practicing: '练习中', mastered: '已掌握', at_risk: '需要复习' };
const stepLabels: Record<string, string> = { pending: '待开始', running: '准备中', ready: '进行中', completed: '已完成', skipped: '已跳过' };

function GuidedWorkspace({ subjectId }: { subjectId: string }) {
  const [params, setParams] = useSearchParams();
  const [topics, setTopics] = useState<CourseTopic[]>([]);
  const [recent, setRecent] = useState<Array<{ id: string; goal: string; status: string }>>([]);
  const [topicId, setTopicId] = useState(params.get('topicId') ?? '');
  const [minutes, setMinutes] = useState(30);
  const [session, setSession] = useState<StudySession | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [draftMinutes, setDraftMinutes] = useState<number[]>([]);
  const [reply, setReply] = useState('');
  const [dialogue, setDialogue] = useState('');
  const [cards, setCards] = useState<ScheduledFlashcard[]>([]);
  const [cardReload, setCardReload] = useState(0);
  const [cardsLoading, setCardsLoading] = useState(false);
  const [quizAttempt, setQuizAttempt] = useState<ExamAttempt | null>(null);
  const requestId = useRef(crypto.randomUUID());
  const sessionId = params.get('sessionId');
  const step = session?.steps[session.current_step];

  useEffect(() => {
    let stopped = false;
    setLoading(true);
    Promise.all([api.courseStructure(subjectId), api.studySessions(subjectId)]).then(([course, history]) => {
      if (stopped) return;
      setTopics(course.topics.filter(topic => !topic.archived)); setRecent(history);
    }).catch(reason => { if (!stopped) setError(String(reason.message ?? reason)); })
      .finally(() => { if (!stopped) setLoading(false); });
    return () => { stopped = true; };
  }, [subjectId]);

  useEffect(() => {
    let stopped = false;
    setDraftMinutes([]);
    if (!sessionId) { setSession(null); return; }
    api.studySession(sessionId).then(loaded => {
      if (stopped) return;
      if (loaded.subject_id !== subjectId) { setError('该会话属于其他科目，请切换科目后继续。'); return; }
      setSession(loaded);
    }).catch(reason => { if (!stopped) setError(String(reason.message ?? reason)); });
    return () => { stopped = true; };
  }, [sessionId, subjectId]);

  useEffect(() => {
    setDialogue(''); setReply(''); setCards([]); setQuizAttempt(null);
  }, [step?.id]);

  useEffect(() => {
    if (!session || session.status !== 'active' || step?.kind !== 'quiz' || !step.output.taskId) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const task = await api.task(step!.output.taskId!);
        if (stopped) return;
        if (task.status === 'succeeded') { const attempt = await api.sessionQuizAttempt(session!.id); if (!stopped) setQuizAttempt(attempt); }
        else if (task.status === 'failed' || task.status === 'cancelled') setError(task.errorMessage || '测验生成失败，请取消本会话后重新规划。');
        else timer = setTimeout(() => void poll(), 2000);
      } catch (reason) { if (!stopped) setError(reason instanceof Error ? reason.message : '无法读取测验，请刷新重试。'); }
    }
    void poll();
    return () => { stopped = true; clearTimeout(timer); };
  }, [session?.id, session?.status, step?.id, step?.output.taskId]);

  async function action(name: string, values: Record<string, unknown> = {}) {
    if (!session) return;
    setBusy(true); setError('');
    try { setSession(await api.sessionAction(session.id, session.version, name, values)); }
    catch (reason) {
      setError(reason instanceof Error ? reason.message : '操作失败，请刷新后重试。');
      try { setSession(await api.studySession(session.id)); } catch { /* Retain current content on connection failure. */ }
    } finally { setBusy(false); }
  }

  async function create() {
    setBusy(true); setError('');
    try {
      const created = await api.createStudySession(subjectId, topicId, minutes, requestId.current, params.get('examEventId') ?? undefined,
        topicId === params.get('topicId') ? params.get('recommendationId') ?? undefined : undefined);
      setSession(created); setParams({ sessionId: created.id });
    } catch (reason) { setError(reason instanceof Error ? reason.message : '无法规划学习会话。'); }
    finally { setBusy(false); }
  }

  async function sendReply() {
    if (!session) return;
    setBusy(true); setError('');
    try { const result = await api.sessionMessage(session.id, reply.trim()); setDialogue(result.answer); setReply(''); }
    catch (reason) { setError(reason instanceof Error ? reason.message : '对话失败，内容已保留。'); }
    finally { setBusy(false); }
  }

  useEffect(() => {
    if (step?.kind !== 'flashcards' || !step.output.id || step.status !== 'ready') return;
    let stopped = false; setCardsLoading(true);
    api.flashcardQueue(subjectId, step.output.id, true).then(value => { if (!stopped) setCards(value.cards); })
      .catch(reason => { if (!stopped) setError(reason instanceof Error ? reason.message : '无法恢复闪卡进度。'); })
      .finally(() => { if (!stopped) setCardsLoading(false); });
    return () => { stopped = true; };
  }, [subjectId, step?.id, step?.kind, step?.output.id, step?.status, cardReload]);

  return <div className="h-full overflow-y-auto p-6 lg:p-8"><div className="mx-auto max-w-6xl">
    <header className="mb-7 flex items-start justify-between gap-4"><div><h1 className="text-2xl font-bold text-slate-950">引导学习</h1><p className="mt-2 max-w-[72ch] text-sm leading-6 text-slate-600">先确认学习路径，再按步骤阅读、解释、回忆和测验。进度会保存，随时可以回来继续。</p></div>{session && <button className={secondary} disabled={busy} onClick={() => { setSession(null); setParams({}); requestId.current = crypto.randomUUID(); }}>另开会话</button>}</header>
    {error && <p role="alert" className="mb-5 rounded-lg bg-rose-50 p-4 text-sm text-rose-900">{error}</p>}
    {loading && <p role="status" className="mb-4 text-slate-600">正在载入课程与学习记录…</p>}
    {!session && <><form onSubmit={event => { event.preventDefault(); void create(); }} className="space-y-5 rounded-xl border border-slate-200 bg-white p-6">
      <h2 className="text-lg font-bold">规划本次学习</h2>
      {!topics.length && !loading ? <p className="text-slate-600">请先在 <Link to="/course" className="font-semibold text-blue-700 underline">课程结构</Link> 中建立知识点。</p> : <div className="flex flex-wrap items-end gap-5"><label className="flex min-w-64 flex-1 flex-col gap-2 text-sm font-semibold">学习知识点<select className={input} value={topicId} required onChange={event => { setTopicId(event.target.value); requestId.current = crypto.randomUUID(); }}><option value="">选择一个知识点</option>{topics.map(topic => <option key={topic.id} value={topic.id}>{topic.title}</option>)}</select></label><label className="flex flex-col gap-2 text-sm font-semibold">可用时间（分钟）<input className={`${input} w-32`} type="number" min={10} max={120} required value={minutes} onChange={event => { setMinutes(Number(event.target.value)); requestId.current = crypto.randomUUID(); }}/></label><button className={button} disabled={busy || !topicId || loading}>生成学习路径</button></div>}
      <p className="text-sm text-slate-600">测验未达 80% 时会追加最多两轮补习与重测，每轮约 10 分钟。暂停后的复习记录由你填写，是否掌握仍以评估证据为准。</p>
    </form>{recent.length > 0 && <section className="mt-8"><h2 className="text-lg font-bold">最近的学习会话</h2><ul className="mt-3 divide-y divide-slate-200">{recent.map(item => <li key={item.id} className="flex items-center justify-between gap-3 py-4"><span>{item.goal}<span className="ml-3 text-sm text-slate-500">{({ planned: '待确认', active: '进行中', completed: '已完成', cancelled: '已取消' } as Record<string, string>)[item.status]}</span></span><Link className="min-h-11 py-3 font-semibold text-blue-700 underline" to={`?sessionId=${item.id}`}>查看会话</Link></li>)}</ul></section>}</>}
    {session && <div className="grid items-start gap-8 lg:grid-cols-[260px_minmax(0,1fr)]"><aside><h2 className="text-lg font-bold">{session.goal}</h2><p className="mt-2 text-sm text-slate-600">计划 {session.minutes} 分钟 · 进度 {Math.min(session.current_step, session.steps.length)}/{session.steps.length}</p><ol className="mt-5 space-y-4">{session.steps.map((item, index) => <li key={item.id} aria-current={index === session.current_step ? 'step' : undefined} className={`text-sm ${index === session.current_step ? 'font-semibold text-blue-800' : 'text-slate-600'}`}><div>{index + 1}. {item.title}</div><div className="mt-1 pl-4 font-normal">{item.estimated_minutes} 分钟 · {stepLabels[item.status]}</div></li>)}</ol>{session.status === 'active' && <button className={`${secondary} mt-6 w-full`} disabled={busy} onClick={() => void action('cancel')}>结束本次会话</button>}</aside>
      <section className="min-w-0 rounded-xl border border-slate-200 bg-white p-6" aria-busy={busy}>
        {session.status === 'planned' && <><h2 className="text-xl font-bold">确认学习路径</h2><p className="mt-3 text-sm leading-6 text-slate-600">可以调整各步骤时间，总时间不能超过预算。测验和最后的掌握检查为必需步骤。</p><div className="my-6 space-y-3">{session.steps.map((item, index) => <label key={item.id} className="flex items-center justify-between gap-4 text-sm"><span>{item.title}</span><input aria-label={`${item.title}分钟`} type="number" min={1} max={60} className={`${input} w-24`} value={draftMinutes[index] ?? item.estimated_minutes} onChange={event => setDraftMinutes(session.steps.map((row, i) => i === index ? Number(event.target.value) : draftMinutes[i] ?? row.estimated_minutes))}/></label>)}</div><div className="flex flex-wrap gap-3"><button className={secondary} disabled={busy} onClick={() => void action('edit', { steps: session.steps.map((item, index) => ({ kind: item.kind, estimatedMinutes: draftMinutes[index] ?? item.estimated_minutes })) })}>保存时间调整</button><button className={button} disabled={busy || draftMinutes.some((value, index) => value !== session.steps[index].estimated_minutes)} onClick={() => void action('accept')}>确认并开始</button></div></>}
        {session.status === 'active' && step && <><h2 className="text-xl font-bold">{step.title}</h2>
          {step.kind === 'remediation' && <p className="mt-3 text-sm leading-6 text-amber-900">上一轮测验未达标，已追加补习和重测。最多增加 20 分钟，也可以结束会话后重新安排。</p>}
          {(step.status === 'pending' || step.status === 'running') && <div className="mt-6"><p className="mb-4 text-sm text-slate-600">{step.status === 'running' ? '活动正在准备。中断超过十分钟后可以重试。' : '准备本步骤所需的课程内容。'}</p><button className={button} disabled={busy} onClick={() => void action('execute')}>{busy ? '正在准备…' : '准备活动'}</button><button className={`${secondary} ml-3`} disabled={busy} onClick={() => { void api.studySession(session.id).then(setSession).catch(reason => setError(reason.message)); }}><RefreshCw size={16} className="mr-2 inline"/>刷新进度</button></div>}
          {step.status === 'ready' && <div className="mt-6 space-y-6">
            {step.output.answer && <div className="max-w-[72ch]"><MarkdownViewer content={step.output.answer}/>{step.output.citations?.length ? <p className="mt-4 text-sm text-slate-600">课程来源：{step.output.citations.map((source, i) => `${source.sourceName || `来源 ${i + 1}`}${source.pageNumber || source.page ? `（第 ${source.pageNumber ?? source.page} 页）` : ''}`).join('；')}</p> : null}</div>}
            {step.kind === 'socratic' && <><label className="block text-sm font-semibold">用自己的语言回答<textarea className={`${input} mt-2 block w-full`} rows={5} maxLength={4000} value={reply} disabled={busy} onChange={event => setReply(event.target.value)}/></label><button className={button} disabled={busy || !reply.trim()} onClick={() => void sendReply()}>提交解释，继续追问</button>{dialogue && <MarkdownViewer content={dialogue}/>}</>}
            {step.kind === 'flashcards' && (cardsLoading ? <p role="status" className="text-slate-600">正在恢复闪卡进度…</p> : <div className="space-y-4">{cards.map(card => <FlashcardReviewPanel key={`${card.artifact_id}:${card.card_id}:${card.state.version}`} card={card} completed={card.state.review_count > 0} onReviewed={() => setCardReload(n => n + 1)} onConflict={() => setCardReload(n => n + 1)}/>)}</div>)}
            {step.kind === 'quiz' && (quizAttempt ? <ExamQuestionList key={quizAttempt.id} exam={quizAttempt.exam} attemptId={quizAttempt.id} onCompleted={finished => void action('complete', { attemptId: finished.attemptId })}/> : <p role="status" className="flex items-center gap-2 text-slate-600"><LoaderCircle size={18} className="animate-spin"/>测验正在后台生成，完成后会自动显示。</p>)}
            {step.kind === 'mastery_check' && step.output.learnerState && <p className="leading-7">当前状态：{stateLabels[step.output.learnerState.state]}。掌握度 {Math.round(step.output.learnerState.masteryScore * 100)}%，已有 {step.output.learnerState.assessmentCount} 次评估证据。</p>}
            {step.kind !== 'quiz' && <button className={button} disabled={busy} onClick={() => void action('complete')}>{step.kind === 'mastery_check' ? '完成学习并查看总结' : '完成本步，继续学习'}</button>}
            {step.kind === 'quiz' && quizAttempt?.status === 'graded' && <button className={button} disabled={busy} onClick={() => void action('complete', { attemptId: quizAttempt.id })}>使用已完成测验继续学习</button>}
          </div>}
          {!['quiz', 'mastery_check'].includes(step.kind) && <button className={`${secondary} mt-5`} disabled={busy || step.status === 'running'} onClick={() => void action('skip')}>跳过本步</button>}
        </>}
        {session.status === 'completed' && <><h2 className="text-xl font-bold">本次学习已完成</h2><p className="mt-4 leading-7">学习状态：{stateLabels[session.summary?.before?.state ?? 'not_started']} → {stateLabels[session.summary?.after?.state ?? 'not_started']}。{session.summary?.after?.assessmentCount ?? 0} 次评估证据支持当前判断。</p><p className="mt-2 text-sm text-slate-600">跳过 {session.summary?.skippedSteps ?? 0} 步，追加时间 {Math.max(0, session.summary?.extraMinutes ?? 0)} 分钟。</p><h3 className="mt-6 font-semibold">建议下一步</h3><ul className="mt-3 space-y-3">{session.summary?.nextActions?.map(item => <li key={item.id}><Link className="font-semibold text-blue-700 underline" to={item.href}>{item.title}</Link></li>)}</ul></>}
        {session.status === 'cancelled' && <><h2 className="text-xl font-bold">会话已结束</h2><p className="mt-3 leading-7 text-slate-600">已完成的学习与测验记录已保留。可以另开会话继续复习。</p></>}
      </section></div>}
  </div></div>;
}

export default function GuidedStudy() {
  const subject = useAppStore(state => state.currentSubject)!;
  return <GuidedWorkspace key={subject.id} subjectId={subject.id}/>;
}
