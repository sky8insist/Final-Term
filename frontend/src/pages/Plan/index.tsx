import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  AlertTriangle,
  ArrowRight,
  BookOpen,
  CalendarDays,
  CheckCircle2,
  ChevronRight,
  Circle,
  Clock3,
  LoaderCircle,
  MessageSquareText,
  Printer,
  RotateCcw,
  Sparkles,
  Target,
} from 'lucide-react';
import { api } from '../../api/client';
import { useAppStore } from '../../stores/useAppStore';
import type { ProcessingTask, StudyPhase, StudyPlanOverview, StudyPlanPreview, StudyTask } from '../../types';

const minuteOptions = [30, 45, 60, 90];

function isoLocal(day: Date) {
  const offset = day.getTimezoneOffset();
  return new Date(day.getTime() - offset * 60_000).toISOString().slice(0, 10);
}

function formatDate(value?: string) {
  if (!value) return '—';
  return new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric' }).format(
    new Date(`${value}T00:00:00`),
  );
}

function formatRange(phase: StudyPhase) {
  return phase.startDate === phase.endDate
    ? formatDate(phase.startDate)
    : `${formatDate(phase.startDate)}—${formatDate(phase.endDate)}`;
}

function sourceLabel(source: string) {
  return ({ practice: '练习表现', dialogue: 'AI 对话', course: '课程结构' } as Record<string, string>)[source] || source;
}

export default function Plan() {
  const subject = useAppStore((state) => state.currentSubject)!;
  const [overview, setOverview] = useState<StudyPlanOverview | null>(null);
  const [targetDate, setTargetDate] = useState('');
  const [dailyMinutes, setDailyMinutes] = useState(60);
  const [customMinutes, setCustomMinutes] = useState(false);
  const [weekendExtra, setWeekendExtra] = useState(false);
  const [reserveFinalDay, setReserveFinalDay] = useState(true);
  const [preview, setPreview] = useState<StudyPlanPreview | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [generation, setGeneration] = useState<ProcessingTask | null>(null);
  const [error, setError] = useState('');
  const [selectedDate, setSelectedDate] = useState('');

  const tomorrow = useMemo(() => {
    const value = new Date();
    value.setDate(value.getDate() + 1);
    return isoLocal(value);
  }, []);

  async function loadOverview() {
    const data = await api.plan(subject.id);
    setOverview(data);
    const firstPending = data.tasks.find((task) => !task.completed) || data.tasks[0];
    setSelectedDate((current) => current || firstPending?.scheduledDate || '');
  }

  useEffect(() => {
    setOverview(null);
    setPreview(null);
    setTargetDate('');
    setSelectedDate('');
    setError('');
    void loadOverview().catch(() => setError('复习计划加载失败，请检查连接后重试。'));
  }, [subject.id]);

  useEffect(() => {
    if (!targetDate || targetDate < tomorrow) {
      setPreview(null);
      return;
    }
    const timer = window.setTimeout(async () => {
      setPreviewing(true);
      setError('');
      try {
        setPreview(await api.previewPlan({ subjectId: subject.id, examDate: targetDate, dailyMinutes, weekendExtra, reserveFinalDay }));
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : '无法评估当前计划参数。');
      } finally {
        setPreviewing(false);
      }
    }, 280);
    return () => window.clearTimeout(timer);
  }, [targetDate, dailyMinutes, weekendExtra, reserveFinalDay, subject.id, tomorrow]);

  useEffect(() => {
    if (!generation || !['queued', 'running'].includes(generation.status)) return;
    const timer = window.setInterval(async () => {
      try {
        const next = await api.planGeneration(generation.id);
        setGeneration(next);
        if (next.status === 'succeeded') {
          window.clearInterval(timer);
          await loadOverview();
        } else if (next.status === 'failed') {
          window.clearInterval(timer);
          setError(next.errorMessage || '计划生成失败，请调整参数后重试。');
        }
      } catch {
        window.clearInterval(timer);
        setError('生成状态查询失败，请稍后重试。');
      }
    }, 1200);
    return () => window.clearInterval(timer);
  }, [generation?.id, generation?.status]);

  const phases = overview?.activePlan?.strategy?.phases || [];
  const days = useMemo(
    () => Array.from(new Set((overview?.tasks || []).map((task) => task.scheduledDate).filter(Boolean) as string[])).sort(),
    [overview],
  );
  const selectedTasks = (overview?.tasks || []).filter((task) => task.scheduledDate === selectedDate);
  const isGenerating = generation?.status === 'queued' || generation?.status === 'running';

  async function generate() {
    if (!targetDate) {
      setError('请先选择目标完成日期。');
      return;
    }
    if (targetDate < tomorrow) {
      setError('目标日期不能早于明天。');
      return;
    }
    setError('');
    try {
      setGeneration(await api.generatePlan({
        subjectId: subject.id,
        examDate: targetDate,
        dailyMinutes,
        weekendExtra,
        reserveFinalDay,
        preserveExisting: true,
        title: `${subject.name}复习计划`,
      }));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '计划生成请求失败。');
    }
  }

  async function toggleTask(task: StudyTask) {
    try {
      const next = await api.updateTask(task.id, !task.completed);
      setOverview((current) => {
        if (!current) return current;
        const completed = current.summary.completed + (next.completed ? 1 : -1);
        return {
          ...current,
          tasks: current.tasks.map((item) => item.id === next.id ? { ...item, ...next } : item),
          summary: {
            ...current.summary,
            completed,
            completionRate: current.summary.total ? completed / current.summary.total : 0,
          },
        };
      });
    } catch {
      setError('任务状态更新失败，请稍后重试。');
    }
  }

  return (
    <div className="plan-page h-full overflow-y-auto bg-slate-50 p-6 text-slate-900 md:p-8">
      <div className="mx-auto max-w-[1480px]">
        <header className="plan-no-print mb-7 flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-3xl font-bold tracking-tight text-slate-900">复习计划</h1>
            <p className="mt-2 text-sm leading-6 text-slate-500">
              基于 <strong className="text-slate-700">{subject.name}</strong> 的练习表现和学习互动，安排每天可完成的复习任务。
            </p>
          </div>
          {overview?.activePlan && (
            <button
              type="button"
              onClick={() => window.print()}
              className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-slate-300 bg-white px-4 text-sm font-semibold text-slate-700 shadow-sm transition-colors hover:bg-slate-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600"
            >
              <Printer className="size-4" />导出 / 打印计划
            </button>
          )}
        </header>

        <section className="plan-no-print rounded-2xl border border-slate-200 bg-white p-6 shadow-sm" aria-labelledby="plan-generator-title">
          <div className="flex flex-wrap items-start justify-between gap-4 border-b border-slate-100 pb-5">
            <div>
              <h2 id="plan-generator-title" className="text-lg font-semibold text-slate-900">生成计划</h2>
              <p className="mt-1 text-sm leading-6 text-slate-500">先确定目标日期和每日容量；重新生成时会保留已完成及手动调整的任务。</p>
            </div>
            {preview && (
              <div className="flex flex-wrap gap-x-6 gap-y-2 text-sm">
                <span><b className="text-lg text-blue-700">{preview.daysRemaining}</b> 天剩余</span>
                <span><b className="text-lg text-blue-700">{preview.estimatedKnowledgePoints}</b> 个知识点</span>
                <span><b className="text-lg text-blue-700">{preview.estimatedMinutes}</b> 分钟投入</span>
              </div>
            )}
          </div>

          <div className="mt-5 grid gap-5 xl:grid-cols-[minmax(230px,.8fr)_minmax(440px,1.6fr)_minmax(260px,1fr)]">
            <label className="grid content-start gap-2 text-sm font-medium text-slate-700">
              <span>目标完成日期 / 考试日期 <b className="text-red-600">必填</b></span>
              <input
                type="date"
                min={tomorrow}
                value={targetDate}
                onChange={(event) => setTargetDate(event.target.value)}
                className="min-h-11 rounded-lg border border-slate-300 bg-white px-3 outline-none focus:border-blue-600 focus:ring-2 focus:ring-blue-100"
              />
            </label>

            <fieldset>
              <legend className="mb-2 text-sm font-medium text-slate-700">每日可复习时间</legend>
              <div className="flex flex-wrap gap-2">
                {minuteOptions.map((minutes) => (
                  <button
                    key={minutes}
                    type="button"
                    onClick={() => { setDailyMinutes(minutes); setCustomMinutes(false); }}
                    className={`min-h-11 min-w-14 rounded-lg border px-3 text-sm font-semibold transition-colors ${dailyMinutes === minutes && !customMinutes ? 'border-blue-600 bg-blue-600 text-white' : 'border-slate-300 bg-white text-slate-700 hover:bg-slate-50'}`}
                  >
                    {minutes}
                  </button>
                ))}
                <button
                  type="button"
                  onClick={() => setCustomMinutes(true)}
                  className={`min-h-11 rounded-lg border px-3 text-sm ${customMinutes ? 'border-blue-600 bg-blue-50 text-blue-700' : 'border-slate-300 bg-white text-slate-700 hover:bg-slate-50'}`}
                >
                  自定义
                </button>
                {customMinutes && (
                  <input
                    aria-label="自定义每日分钟数"
                    type="number"
                    min={15}
                    max={720}
                    value={dailyMinutes}
                    onChange={(event) => setDailyMinutes(Math.min(720, Math.max(15, Number(event.target.value))))}
                    className="min-h-11 w-24 rounded-lg border border-slate-300 px-3 outline-none focus:border-blue-600 focus:ring-2 focus:ring-blue-100"
                  />
                )}
              </div>
            </fieldset>

            <div className="grid gap-2 text-sm text-slate-700">
              <label className="flex min-h-10 items-center gap-3"><input type="checkbox" checked={weekendExtra} onChange={(event) => setWeekendExtra(event.target.checked)} className="size-4 accent-blue-600" />周末可以适当增加复习时间</label>
              <label className="flex min-h-10 items-center gap-3"><input type="checkbox" checked={reserveFinalDay} onChange={(event) => setReserveFinalDay(event.target.checked)} className="size-4 accent-blue-600" />保留最后一天用于模拟和总复盘</label>
            </div>
          </div>

          <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 pt-5">
            <div className="text-sm text-slate-500">
              {previewing ? '正在评估当前数据与时间容量…' : preview ? (preview.dataSufficient ? '当前数据足够用于个性化排程。' : '数据较少，计划将更多参考课程知识点重要度。') : '选择日期后将立即评估覆盖范围和时间是否充足。'}
            </div>
            <button
              type="button"
              disabled={!targetDate || targetDate < tomorrow || isGenerating}
              onClick={() => void generate()}
              className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg bg-blue-600 px-5 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-blue-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600"
            >
              {isGenerating ? <><LoaderCircle className="size-4 animate-spin" />正在分析并排程 {generation?.progress || 0}%</> : overview?.activePlan ? <><RotateCcw className="size-4" />保留进度并重新生成</> : <><Sparkles className="size-4" />生成复习计划</>}
            </button>
          </div>

          {(error || preview?.warnings.length) ? (
            <div className="mt-4 flex items-start gap-3 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-950" role="status">
              <AlertTriangle className="mt-0.5 size-4 shrink-0" />
              <div>{error || preview?.warnings.join('；')} {!preview?.timeSufficient && !error && <strong>仍可继续生成，系统会优先保留最重要任务。</strong>}</div>
            </div>
          ) : null}
        </section>

        {!overview ? (
          <div className="grid min-h-64 place-items-center text-sm text-slate-500"><span className="flex items-center gap-2"><LoaderCircle className="size-5 animate-spin" />正在读取计划</span></div>
        ) : !overview.activePlan ? (
          <section className="mt-6 grid min-h-72 place-items-center rounded-2xl border border-dashed border-slate-300 bg-white text-center">
            <div className="max-w-md px-6"><Target className="mx-auto size-9 text-blue-600" /><h2 className="mt-4 text-xl font-semibold">从目标日期开始</h2><p className="mt-2 text-sm leading-6 text-slate-500">选择日期后即可看到数据充足度、预计覆盖范围和时间是否足够。生成前不再显示空的“今日任务”。</p></div>
          </section>
        ) : (
          <section className="plan-export mt-6 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
            <div className="plan-print-only border-b border-slate-200 pb-5">
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-blue-700">Personal Study Roadmap</p>
              <h1 className="mt-2 text-3xl font-bold text-slate-950">{overview.activePlan.title}</h1>
              <p className="mt-2 text-sm text-slate-500">目标日期：{overview.activePlan.examDate || overview.activePlan.exam_date} · 每日 {overview.activePlan.dailyMinutes || overview.activePlan.daily_minutes} 分钟</p>
            </div>

            <div className="border-b border-slate-200 bg-gradient-to-r from-blue-950 to-blue-800 px-6 py-6 text-white md:px-8">
              <div className="flex flex-wrap items-end justify-between gap-5">
                <div><p className="text-xs font-semibold uppercase tracking-[0.16em] text-blue-200">学习路线</p><h2 className="mt-2 text-2xl font-bold">{overview.activePlan.title}</h2><p className="mt-2 text-sm text-blue-100">目标日期 {formatDate(overview.activePlan.examDate || overview.activePlan.exam_date)}</p></div>
                <div className="grid grid-cols-3 gap-5 text-right text-sm"><span><b className="block text-xl">{overview.summary.total}</b>任务</span><span><b className="block text-xl">{overview.summary.scheduledMinutes}</b>分钟</span><span><b className="block text-xl">{Math.round(overview.summary.completionRate * 100)}%</b>完成</span></div>
              </div>
            </div>

            <div className="plan-no-print px-6 py-7 md:px-8">
              <div className="relative grid gap-3 lg:grid-flow-col lg:auto-cols-fr">
                <div className="absolute left-5 right-5 top-4 hidden h-px bg-blue-200 lg:block" />
                {phases.map((phase, index) => (
                  <button key={phase.id} type="button" onClick={() => setSelectedDate(phase.startDate)} className="relative z-10 flex gap-3 rounded-lg bg-white p-1 text-left focus-visible:outline-2 focus-visible:outline-blue-600 lg:block">
                    <span className="grid size-8 shrink-0 place-items-center rounded-full border-4 border-white bg-blue-700 text-xs font-bold text-white lg:mb-3">{index + 1}</span>
                    <strong className="block text-sm text-slate-900">{phase.name}</strong>
                    <span className="mt-1 block text-xs font-medium text-blue-700">{formatRange(phase)}</span>
                    <span className="mt-2 block text-xs leading-5 text-slate-500">{phase.goal}</span>
                  </button>
                ))}
              </div>
            </div>

            <div className="plan-no-print grid border-t border-slate-200 xl:grid-cols-[minmax(0,1fr)_290px]">
              <div className="min-w-0 px-6 py-6 md:px-8">
                <div className="mb-5 flex gap-2 overflow-x-auto pb-2" role="tablist" aria-label="选择计划日期">
                  {days.map((day) => {
                    const tasks = overview.tasks.filter((task) => task.scheduledDate === day);
                    const minutes = tasks.reduce((sum, task) => sum + (task.estimatedMinutes || 0), 0);
                    return <button key={day} role="tab" aria-selected={selectedDate === day} onClick={() => setSelectedDate(day)} className={`min-w-28 rounded-lg border px-3 py-2 text-left text-sm transition-colors ${selectedDate === day ? 'border-blue-700 bg-blue-700 text-white' : 'border-slate-200 bg-white text-slate-700 hover:bg-slate-50'}`}><span className="block font-semibold">{formatDate(day)}</span><span className={`mt-0.5 block text-xs ${selectedDate === day ? 'text-blue-100' : 'text-slate-500'}`}>{tasks.length} 项 · {minutes} 分钟</span></button>;
                  })}
                </div>

                <div className="divide-y divide-slate-200 border-y border-slate-200">
                  {selectedTasks.map((task) => <TaskRow key={task.id} task={task} onToggle={toggleTask} />)}
                  {!selectedTasks.length && <div className="py-12 text-center text-sm text-slate-500">这一天没有安排任务，可选择其他日期。</div>}
                </div>
              </div>

              <aside className="border-t border-slate-200 bg-slate-50 px-6 py-6 text-sm xl:border-l xl:border-t-0">
                <h2 className="font-semibold text-slate-900">计划依据</h2>
                <div className="mt-4 space-y-3 text-slate-600">
                  <p className="flex items-center gap-2"><BookOpen className="size-4 text-blue-700" />练习结果 {overview.activePlan.strategy?.signalStats?.practiceResults || 0} 条</p>
                  <p className="flex items-center gap-2"><MessageSquareText className="size-4 text-blue-700" />互动评价 {overview.activePlan.strategy?.signalStats?.dialogueInteractions || 0} 条</p>
                  <p className="flex items-center gap-2"><CalendarDays className="size-4 text-blue-700" />每日上限 {overview.activePlan.dailyMinutes || overview.activePlan.daily_minutes} 分钟</p>
                </div>
                {overview.activePlan.strategy?.warnings?.length ? <div className="mt-5 rounded-lg border border-amber-200 bg-amber-50 p-4 text-amber-950"><h3 className="flex items-center gap-2 font-semibold"><AlertTriangle className="size-4" />数据提示</h3><p className="mt-2 leading-6">{overview.activePlan.strategy.warnings.join('；')}</p></div> : null}
                <Link to="/exams" className="mt-6 flex items-center justify-between border-y border-slate-200 py-3 font-semibold text-blue-700">生成专项练习<ArrowRight className="size-4" /></Link>
              </aside>
            </div>

            <div className="plan-print-only">
              {days.map((day) => (
                <section key={day} className="plan-print-day">
                  <h2>{formatDate(day)}</h2>
                  {overview.tasks.filter((task) => task.scheduledDate === day).map((task) => (
                    <article key={task.id} className="plan-print-task">
                      <div><strong>{task.completed ? '✓ ' : ''}{task.title}</strong><span>{task.estimatedMinutes || 0} 分钟</span></div>
                      <p><b>方法：</b>{task.metadata?.method || '按计划复习'}</p>
                      <p><b>安排原因：</b>{task.metadata?.reason || '依据学习优先级安排'}</p>
                      <p><b>完成标准：</b>{task.metadata?.successCriteria || '完成任务并自检理解程度'}</p>
                    </article>
                  ))}
                </section>
              ))}
            </div>
          </section>
        )}
      </div>
    </div>
  );
}

function TaskRow({ task, onToggle }: { task: StudyTask; onToggle: (task: StudyTask) => Promise<void> }) {
  return (
    <article className={`grid gap-4 py-5 lg:grid-cols-[32px_minmax(0,1fr)_auto] ${task.completed ? 'opacity-60' : ''}`}>
      <button type="button" aria-label={task.completed ? `将 ${task.title} 标记为未完成` : `完成 ${task.title}`} onClick={() => void onToggle(task)} className="mt-0.5 grid size-7 place-items-center rounded-full text-slate-400 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600">
        {task.completed ? <CheckCircle2 className="size-6 text-emerald-600" /> : <Circle className="size-6" />}
      </button>
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <h3 className={`text-base font-semibold text-slate-900 ${task.completed ? 'line-through' : ''}`}>{task.title}</h3>
          <span className="text-xs text-slate-500"><Clock3 className="mr-1 inline size-3.5" />{task.estimatedMinutes} 分钟</span>
          {task.metadata?.sourceSignals?.map((source) => <span key={source} className="rounded-full bg-blue-50 px-2 py-0.5 text-[11px] font-medium text-blue-700">{sourceLabel(source)}</span>)}
        </div>
        <dl className="mt-3 grid gap-3 text-sm leading-6 md:grid-cols-3">
          <div><dt className="font-semibold text-slate-800">怎么学</dt><dd className="text-slate-500">{task.metadata?.method || '按计划复习'}</dd></div>
          <div><dt className="font-semibold text-slate-800">为什么安排</dt><dd className="text-slate-500">{task.metadata?.reason || '依据学习优先级安排'}</dd></div>
          <div><dt className="font-semibold text-slate-800">完成标准</dt><dd className="text-slate-500">{task.metadata?.successCriteria || '完成任务并自检理解程度'}</dd></div>
        </dl>
      </div>
      <div className="flex items-start gap-1 lg:justify-end">
        {task.metadata?.resourceLinks?.slice(0, 2).map((link) => <Link key={link.href} to={link.href} className="inline-flex min-h-10 items-center gap-1 rounded-lg px-2 text-xs font-semibold text-blue-700 hover:bg-blue-50 focus-visible:outline-2 focus-visible:outline-blue-600">{link.label}<ChevronRight className="size-3.5" /></Link>)}
      </div>
    </article>
  );
}
