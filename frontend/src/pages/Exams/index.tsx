import { useEffect, useMemo, useState } from 'react';
import { AlertCircle, BookOpenCheck, CheckCircle2, Clock, Globe2, LoaderCircle, Play, Settings2 } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';
import { api } from '../../api/client';
import { useAppStore } from '../../stores/useAppStore';
import type { Exam, ExamDetail, ExamGenerateInput, KnowledgePolicy, ProcessingTask } from '../../types';
import { ExamQuestionList } from './components/ExamQuestionList';
import { QuestionTypeSelector, type QuestionTypeCounts } from './components/QuestionTypeSelector';

const stageLabels: Record<string, string> = {
  queued: '正在排队…', retrieving: '正在检索课程资料…', generating: '正在生成题目…',
  validating: '正在检查题型、答案和引用…', saving: '正在保存练习…', ready: '生成完成', failed: '生成失败',
};

const initialCounts: QuestionTypeCounts = { single_choice: 5, multiple_choice: 0, true_false: 3, fill_blank: 2, short_answer: 0 };

function taskErrorMessage(task: ProcessingTask) {
  const message = task.errorMessage || '';
  if (message.includes('validation errors for ExamGenerateRequest')) return '该记录来自旧版任务参数，已修复；请重新生成。';
  if (message.includes('超时') || task.errorCode === 'model_timeout') return '模型批次在重试后仍然超时，请减少题量或稍后重试。';
  return message || '后台生成未完成，请检查主题和资料后重试。';
}

export default function Exams() {
  const subject = useAppStore((state) => state.currentSubject)!;
  const [searchParams] = useSearchParams();
  const [items, setItems] = useState<Exam[]>([]);
  const [selectedExam, setSelectedExam] = useState<ExamDetail | null>(null);
  const [counts, setCounts] = useState<QuestionTypeCounts>(initialCounts);
  const [difficulty, setDifficulty] = useState('medium');
  const [scope, setScope] = useState(searchParams.get('topic') ?? '');
  const [scopeTouched, setScopeTouched] = useState(false);
  const [knowledgePolicy, setKnowledgePolicy] = useState<KnowledgePolicy>('course_first');
  const [task, setTask] = useState<ProcessingTask | null>(null);
  const [failedTasks, setFailedTasks] = useState<ProcessingTask[]>([]);
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [historyLoading, setHistoryLoading] = useState(true);
  const totalCount = useMemo(() => Object.values(counts).reduce((sum, value) => sum + value, 0), [counts]);
  const busy = Boolean(activeTaskId);
  const topicValid = scope.trim().length > 0;

  async function refreshHistory() {
    setHistoryLoading(true);
    try { setItems(await api.exams(subject.id)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : '练习记录加载失败。'); }
    finally { setHistoryLoading(false); }
  }

  async function refreshTaskHistory() {
    const tasks = await api.tasks(subject.id, false);
    const examTasks = tasks.filter((item) => item.taskType === 'exam_generation');
    setFailedTasks(examTasks.filter((item) => item.status === 'failed').slice(0, 3));
    const active = examTasks.find((item) => item.status === 'queued' || item.status === 'running');
    if (active) { setTask(active); setActiveTaskId(active.id); }
  }

  useEffect(() => {
    setScope(searchParams.get('topic') ?? '');
    setScopeTouched(false);
    void refreshHistory();
    refreshTaskHistory().catch(() => { /* History remains usable when task recovery is unavailable. */ });
  }, [subject.id]);

  useEffect(() => {
    if (!activeTaskId) return undefined;
    let stopped = false;
    async function poll() {
      try {
        const current = await api.task(activeTaskId!);
        if (stopped) return;
        setTask(current);
        if (current.status === 'succeeded') {
          const examId = String(current.metadata?.examId ?? '');
          if (!examId) throw new Error('生成任务完成，但没有返回练习记录。');
          const detail = await api.exam(examId);
          if (stopped) return;
          setSelectedExam(detail);
          const externalUsed = detail.generation?.retrieval.externalUsed;
          setSuccess(`已生成 ${detail.questionCount} 道题目${externalUsed ? '，并完成课程资料与公开知识的交叉补充' : ''}。`);
          setActiveTaskId(null);
          await refreshHistory();
        } else if (current.status === 'failed' || current.status === 'cancelled') {
          setError(current.errorMessage || (current.status === 'cancelled' ? '练习生成已取消。' : '练习生成失败，请稍后重试。'));
          setActiveTaskId(null);
          void refreshTaskHistory();
        }
      } catch (reason) {
        if (!stopped) { setError(reason instanceof Error ? reason.message : '无法读取生成进度。'); setActiveTaskId(null); }
      }
    }
    void poll();
    const timer = window.setInterval(() => void poll(), 1500);
    return () => { stopped = true; window.clearInterval(timer); };
  }, [activeTaskId]);

  async function generate() {
    setError(''); setSuccess(''); setSelectedExam(null);
    setScopeTouched(true);
    if (!topicValid) { setError('请输入练习主题，例如“战略的作用”。'); return; }
    if (totalCount < 1) { setError('请至少选择一种题型。'); return; }
    if (totalCount > 20) { setError('单次练习最多生成 20 道题，请减少题目数量。'); return; }
    const points: Record<keyof QuestionTypeCounts, number> = { single_choice: 2, multiple_choice: 3, true_false: 1, fill_blank: 2, short_answer: 5 };
    const payload: ExamGenerateInput = {
      subjectId: subject.id, title: scope.trim() ? `${scope.trim()} · 专项练习` : '专项练习',
      durationMinutes: Math.max(10, totalCount * 2), difficulty, assessmentType: 'practice',
      scope: scope.trim(), knowledgePolicy,
      questionTypes: (Object.entries(counts) as Array<[keyof QuestionTypeCounts, number]>)
        .filter(([, count]) => count > 0)
        .map(([questionType, count]) => ({ questionType, count, pointsEach: points[questionType] })),
    };
    try {
      const queued = await api.queueExamGeneration(payload);
      setTask(queued); setActiveTaskId(queued.id);
    } catch (reason) { setError(reason instanceof Error ? reason.message : '无法创建练习生成任务。'); }
  }

  async function openExam(examId: string) {
    setError('');
    try { setSelectedExam(await api.exam(examId)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : '题目内容加载失败。'); }
  }

  const currentStage = String(task?.metadata?.currentStage ?? task?.stage ?? 'queued');
  const stageDetails = (task?.metadata?.stageDetails ?? {}) as Record<string, unknown>;
  const batch = Number(stageDetails.batch ?? 0);
  const batchCount = Number(stageDetails.batchCount ?? 0);
  const stageText = currentStage === 'generating' && batch && batchCount
    ? `正在生成第 ${batch}/${batchCount} 批题目…`
    : stageLabels[currentStage] ?? '正在处理…';

  return <div className="h-full overflow-y-auto bg-slate-50 p-6 md:p-8">
    <header className="mb-7"><h1 className="text-3xl font-bold text-slate-900">练习与模拟考试</h1><p className="mt-2 text-slate-500">基于 {subject.name} 的课程资料生成可追踪的针对性练习。</p></header>
    {error && <div className="mb-5 flex items-start gap-3 rounded-2xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700" role="alert"><AlertCircle className="mt-0.5 shrink-0" size={18} /><span>{error}</span></div>}
    {success && <div className="mb-5 flex items-center gap-3 rounded-2xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-700" role="status"><CheckCircle2 size={18} />{success}</div>}
    <div className="grid items-start gap-7 xl:grid-cols-[minmax(0,2fr)_360px]">
      <div className="space-y-7">
        <section className="rounded-2xl border bg-white p-6 shadow-sm">
          <h2 className="mb-6 flex items-center border-b pb-4 text-xl font-bold"><Settings2 className="mr-3 text-blue-600" />生成新练习</h2>
          <div className="mb-5 grid gap-5 sm:grid-cols-2">
            <label className="text-sm font-medium text-slate-700" htmlFor="practice-topic">练习主题 <span className="text-rose-600" aria-hidden="true">*</span><input id="practice-topic" required maxLength={1000} value={scope} onChange={(event) => setScope(event.target.value)} onBlur={() => setScopeTouched(true)} disabled={busy} placeholder="例如：战略的作用" aria-invalid={scopeTouched && !topicValid} aria-describedby="practice-topic-hint practice-topic-error" className={`mt-2 w-full rounded-xl border p-3 outline-none focus:ring-2 ${scopeTouched && !topicValid ? 'border-rose-400 focus:border-rose-500 focus:ring-rose-100' : 'focus:border-blue-400 focus:ring-blue-100'}`} /><span id="practice-topic-hint" className="mt-2 block text-xs font-normal leading-5 text-slate-500">系统会围绕该主题检索课程资料，并补充可信公开知识。</span>{scopeTouched && !topicValid && <span id="practice-topic-error" className="mt-1 block text-xs font-medium text-rose-600">必须填写主题后才能生成练习。</span>}</label>
            <label className="text-sm font-medium text-slate-700">难度<select value={difficulty} onChange={(event) => setDifficulty(event.target.value)} disabled={busy} className="mt-2 w-full rounded-xl border bg-white p-3"><option value="easy">基础</option><option value="medium">中等</option><option value="hard">困难</option></select></label>
          </div>
          <fieldset disabled={busy} className="mb-6">
            <legend className="text-sm font-semibold text-slate-800">知识来源</legend>
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              <label className={`flex cursor-pointer gap-3 rounded-xl border p-4 text-blue-950 ${knowledgePolicy === 'course_first' ? 'border-blue-300 bg-blue-50/60' : 'border-slate-200'}`}><input type="radio" name="knowledge-policy" value="course_first" checked={knowledgePolicy === 'course_first'} onChange={() => setKnowledgePolicy('course_first')} className="mt-1 accent-blue-600" /><BookOpenCheck className="mt-0.5 shrink-0 text-blue-700" size={18} /><span><strong className="block text-sm">课程优先</strong><span className="mt-1 block text-xs leading-5 text-blue-800">课程资料决定答案口径，公开知识用于补充背景与覆盖。</span></span></label>
              <label className={`flex cursor-pointer gap-3 rounded-xl border p-4 ${knowledgePolicy === 'expanded' ? 'border-blue-300 bg-blue-50/60 text-blue-950' : 'border-slate-200 text-slate-900'}`}><input type="radio" name="knowledge-policy" value="expanded" checked={knowledgePolicy === 'expanded'} onChange={() => setKnowledgePolicy('expanded')} className="mt-1 accent-blue-600" /><Globe2 className="mt-0.5 shrink-0 text-blue-700" size={18} /><span><strong className="block text-sm">扩展覆盖</strong><span className={`mt-1 block text-xs leading-5 ${knowledgePolicy === 'expanded' ? 'text-blue-800' : 'text-slate-600'}`}>提高公开知识与案例覆盖，仍以课程资料为准。</span></span></label>
            </div>
          </fieldset>
          <QuestionTypeSelector value={counts} disabled={busy} onChange={setCounts} />
          <div className="mt-5 flex items-center justify-between text-sm"><span className="text-slate-500">本次共生成</span><strong className={totalCount > 20 ? 'text-rose-600' : 'text-slate-900'}>{totalCount} 题</strong></div>
          <button disabled={busy || !topicValid || totalCount < 1 || totalCount > 20} onClick={() => void generate()} className="mt-5 flex w-full items-center justify-center rounded-xl bg-blue-600 py-4 text-lg font-bold text-white transition hover:bg-blue-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-55"><Play size={20} className="mr-2" />{busy ? '后台生成中…' : '生成练习'}</button>
          {task && busy && <div className="mt-5 rounded-xl bg-blue-50 p-4 text-blue-900" role="status" aria-live="polite"><div className="flex items-center gap-3 text-sm font-semibold"><LoaderCircle className="animate-spin" size={18} />{stageText}</div><div className="mt-3 h-2 overflow-hidden rounded-full bg-blue-100" aria-label={`生成进度 ${task.progress}%`}><div className="h-full rounded-full bg-blue-600 transition-all" style={{ width: `${task.progress}%` }} /></div><div className="mt-2 flex flex-wrap justify-between gap-2 text-xs text-blue-700"><span>已完成 {Number(stageDetails.completedQuestions ?? 0)}/{Number(stageDetails.totalQuestions ?? totalCount)} 题</span><span>{task.progress}%</span></div><p className="mt-2 text-xs text-blue-700">每批结果都会保存；页面关闭或 Worker 重启后可继续处理。</p></div>}
        </section>
        {selectedExam?.generation && <details className="rounded-xl bg-emerald-50 px-5 py-4 text-sm text-emerald-950"><summary className="cursor-pointer font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-600">知识来源说明</summary><div className="mt-3 flex flex-wrap gap-x-5 gap-y-2 text-emerald-800"><span>课程证据 {selectedExam.generation.retrieval.courseEvidenceCount ?? 0} 条</span><span>公开证据 {selectedExam.generation.retrieval.externalEvidenceCount ?? 0} 条</span><span>{selectedExam.generation.retrieval.externalUsed ? '已补充公开知识' : '本次使用课程资料命题'}</span></div>{selectedExam.generation.retrieval.warnings?.includes('external_knowledge_unavailable') && <p className="mt-2 text-emerald-800">公开知识本次未参与，课程资料仍是完整的答案依据，不影响作答。</p>}</details>}
        {selectedExam && <ExamQuestionList exam={selectedExam} onCompleted={() => void refreshHistory()} />}
      </div>
      <aside className="rounded-2xl border bg-white p-6 shadow-sm">
        <h2 className="mb-4 font-bold">最近记录</h2>
        {failedTasks.length > 0 && <div className="mb-4 space-y-2">{failedTasks.map((failed) => <div key={failed.id} className="rounded-xl bg-rose-50 p-3 text-xs text-rose-800"><div className="font-semibold">生成失败</div><div className="mt-1 line-clamp-3 break-words">{taskErrorMessage(failed)}</div></div>)}</div>}
        {historyLoading
          ? <div className="flex items-center gap-2 text-sm text-slate-500"><LoaderCircle className="animate-spin" size={16} />正在读取…</div>
          : items.length
            ? <div className="space-y-3">{items.map((exam) => <button type="button" key={exam.id} onClick={() => void openExam(exam.id)} className="w-full rounded-xl border bg-slate-50 p-4 text-left transition hover:border-blue-300 hover:bg-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"><div className="flex justify-between gap-3"><b className="line-clamp-2 break-words">{exam.title}</b>{exam.score != null && <span className="shrink-0 text-emerald-600">{exam.score} 分</span>}</div><div className="mt-2 flex items-center text-xs text-slate-600">{exam.score != null ? <CheckCircle2 size={14} className="mr-1" /> : <Clock size={14} className="mr-1" />}{exam.questionCount} 题 · {exam.status || exam.createdAt}</div></button>)}</div>
            : <p className="text-sm leading-6 text-slate-600">还没有练习记录。填写主题并生成后，题目会显示在这里。</p>}
      </aside>
    </div>
  </div>;
}
