import { useEffect, useMemo, useRef, useState } from 'react';
import { AlertCircle, Check, CheckCircle2, CircleX, LoaderCircle, LockKeyhole, RotateCcw } from 'lucide-react';
import { api } from '../../../api/client';
import type { ExamAttempt, ExamAttemptSummary, ExamDetail, ExamQuestion, ExamQuestionType, QuestionGradingResult } from '../../../types';

const labels: Record<ExamQuestionType, string> = {
  single_choice: '单选题', multiple_choice: '多选题', true_false: '判断题', fill_blank: '填空题',
  short_answer: '问答题', calculation: '计算题', essay: '论述题',
};

function normalize(value: unknown): string[] {
  const values = Array.isArray(value) ? value : [value];
  return values.map((item) => String(item ?? '').replace(/\s+/g, '').toLocaleLowerCase()).sort();
}

function answersEqual(left: unknown, right: unknown) {
  return JSON.stringify(normalize(left)) === JSON.stringify(normalize(right));
}

function hasAnswer(question: ExamQuestion, value: unknown) {
  if (question.questionType === 'multiple_choice') return Array.isArray(value) && value.length > 0;
  if (question.questionType === 'true_false') return typeof value === 'boolean';
  return String(value ?? '').trim().length > 0;
}

function answerText(value: unknown) {
  if (Array.isArray(value)) return value.map(String).join('、');
  if (typeof value === 'boolean') return value ? '正确' : '错误';
  return String(value ?? '');
}

function OptionInput({ question, option, index, value, locked, result, onChange }: {
  question: ExamQuestion; option: unknown; index: number; value: unknown; locked: boolean;
  result?: QuestionGradingResult; onChange: (value: unknown) => void;
}) {
  const isMultiple = question.questionType === 'multiple_choice';
  const selected = isMultiple ? Array.isArray(value) && value.some((item) => answersEqual(item, option)) : answersEqual(value, option);
  const correct = result ? (Array.isArray(result.correctAnswer)
    ? result.correctAnswer.some((item) => answersEqual(item, option))
    : answersEqual(result.correctAnswer, option)) : false;
  const incorrectSelection = Boolean(result && selected && !correct);
  const optionLabel = question.questionType === 'true_false' ? answerText(option) : String(option);
  const choiceLabel = question.questionType === 'true_false' ? '' : `${String.fromCharCode(65 + index)}.`;
  const stateClass = correct
    ? 'border-emerald-400 bg-emerald-50 text-emerald-950'
    : incorrectSelection
      ? 'border-rose-400 bg-rose-50 text-rose-950'
      : selected
        ? 'border-blue-500 bg-blue-50 text-blue-950 ring-2 ring-blue-100'
        : 'border-slate-200 bg-white text-slate-800 hover:border-blue-300 hover:bg-slate-50';

  function update() {
    if (locked) return;
    if (!isMultiple) { onChange(option); return; }
    const current = Array.isArray(value) ? value : [];
    onChange(selected ? current.filter((item) => !answersEqual(item, option)) : [...current, option]);
  }

  return <label className={`flex min-h-14 cursor-pointer items-center gap-3 rounded-xl border px-4 py-3 text-base transition ${stateClass} ${locked ? 'cursor-default' : ''}`}>
    <input type={isMultiple ? 'checkbox' : 'radio'} name={`question-${question.id}`} checked={selected} disabled={locked} onChange={update} className="h-4 w-4 shrink-0 accent-blue-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500" />
    <span className="min-w-0 flex-1 break-words"><strong className="me-2">{choiceLabel}</strong>{optionLabel}</span>
    {correct && <span className="flex shrink-0 items-center gap-1 text-sm font-semibold text-emerald-700"><Check size={17} />正确答案</span>}
    {incorrectSelection && <span className="flex shrink-0 items-center gap-1 text-sm font-semibold text-rose-700"><CircleX size={17} />你的选择</span>}
  </label>;
}

function QuestionCard({ question, index, draft, result, pending, onDraft, onConfirm, confidence, onConfidence, formal }: {
  question: ExamQuestion; index: number; draft: unknown; result?: QuestionGradingResult; pending: boolean;
  onDraft: (value: unknown) => void; onConfirm: () => void;
  confidence: number | null; onConfidence: (value: number | null) => void;
  formal: boolean;
}) {
  const locked = Boolean(result);
  const objectiveOptions = question.questionType === 'true_false' && !question.options.length ? [true, false] : question.options;
  const isTextAnswer = ['fill_blank', 'short_answer', 'calculation', 'essay'].includes(question.questionType);
  const isLongAnswer = ['short_answer', 'calculation', 'essay'].includes(question.questionType);

  return <article id={`question-${question.id}`} className="scroll-mt-6 px-5 py-7 sm:px-7">
    <div className="mb-3 flex flex-wrap items-center gap-2 text-sm">
      <span className="rounded-full bg-blue-50 px-2.5 py-1 font-semibold text-blue-700">{labels[question.questionType]}</span>
      <span className="text-slate-500">{question.points} 分</span>
      {question.knowledgeKey && <span className="max-w-full break-words text-slate-500">知识点：{question.knowledgeKey}</span>}
      {locked && <span className="ms-auto flex items-center gap-1 text-xs font-medium text-slate-500"><LockKeyhole size={13} />答案已确认</span>}
    </div>
    <h3 className="max-w-[72ch] break-words text-lg font-semibold leading-8 text-slate-950">{index + 1}. {question.stem}</h3>
    {objectiveOptions.length > 0 && <fieldset className="mt-5 grid gap-3 lg:grid-cols-2" disabled={pending}>
      <legend className="sr-only">第 {index + 1} 题选项</legend>
      {objectiveOptions.map((option, optionIndex) => <OptionInput key={`${String(option)}-${optionIndex}`} question={question} option={option} index={optionIndex} value={draft} locked={locked} result={result} onChange={onDraft} />)}
    </fieldset>}
    {isTextAnswer && <div className="mt-5">
      <label htmlFor={`answer-${question.id}`} className="mb-2 block text-sm font-semibold text-slate-700">{isLongAnswer ? '输入你的回答' : '填写答案'}</label>
      {isLongAnswer
        ? <textarea id={`answer-${question.id}`} value={String(draft ?? '')} onChange={(event) => onDraft(event.target.value)} disabled={locked || pending} maxLength={4000} rows={5} placeholder="请根据课程资料，用自己的语言作答…" className="w-full resize-y rounded-xl border border-slate-300 bg-white px-4 py-3 text-base leading-7 text-slate-900 outline-none transition placeholder:text-slate-500 focus:border-blue-500 focus:ring-2 focus:ring-blue-100 disabled:bg-slate-50" />
        : <input id={`answer-${question.id}`} value={String(draft ?? '')} onChange={(event) => onDraft(event.target.value)} disabled={locked || pending} maxLength={500} placeholder="请输入答案" className="w-full rounded-xl border border-slate-300 bg-white px-4 py-3 text-base text-slate-900 outline-none transition placeholder:text-slate-500 focus:border-blue-500 focus:ring-2 focus:ring-blue-100 disabled:bg-slate-50" />}
    </div>}
    {!locked && <fieldset className="mt-5" disabled={pending}><legend className="text-sm font-semibold text-slate-700">你对这次回答有多确定？<span className="ml-2 font-normal text-slate-500">可选，用于安排后续复习</span></legend><div className="mt-2 flex flex-wrap gap-4">{[{ value: 0.25, label: '不太确定' }, { value: 0.5, label: '有些把握' }, { value: 0.9, label: '很确定' }, { value: null, label: '暂不填写' }].map((choice) => <label key={choice.label} className="flex min-h-11 items-center gap-2 text-sm"><input type="radio" name={`confidence-${question.id}`} checked={confidence === choice.value} onChange={() => onConfidence(choice.value)} className="accent-blue-600 focus-visible:outline-2 focus-visible:outline-blue-600"/>{choice.label}</label>)}</div></fieldset>}
    {!locked && <div className="mt-5 flex flex-wrap items-center gap-3">
      <button type="button" disabled={pending || !hasAnswer(question, draft)} onClick={onConfirm} className="inline-flex min-h-11 items-center justify-center rounded-xl bg-blue-600 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-blue-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-55">
        {pending ? <><LoaderCircle className="me-2 animate-spin" size={17} />正在保存…</> : formal ? '保存本题答案' : '确认本题答案'}
      </button>
      <span className="text-sm text-slate-500">{formal ? '整卷提交前可以修改，保存后可恢复。' : '确认后不可修改，系统会立即判定。'}</span>
    </div>}
    {result && <div className={`mt-6 rounded-xl p-5 ${result.isCorrect ? 'bg-emerald-50 text-emerald-950' : 'bg-rose-50 text-rose-950'}`} role="status" aria-live="polite">
      <div className="flex items-center gap-2 font-bold">
        {result.isCorrect ? <CheckCircle2 className="text-emerald-700" size={20} /> : <CircleX className="text-rose-700" size={20} />}
        {result.isCorrect ? '回答正确' : '回答错误'}
        <span className="ms-auto text-sm font-semibold">{result.earnedPoints}/{result.maxPoints} 分</span>
      </div>
      <dl className="mt-4 grid gap-3 text-sm leading-6">
        {result.learnerConfidence != null && <div><dt className="font-semibold">信心与答题结果</dt><dd className="mt-0.5">{result.learnerConfidence >= 0.75 ? (result.isCorrect ? '高信心且答对，继续巩固。' : '高信心但答错，建议先检查概念理解。') : (result.isCorrect ? '答对了，可以通过回忆练习建立把握。' : '把握不足且答错，建议回到课程资料复习。')}</dd></div>}
        <div><dt className="font-semibold">你的答案</dt><dd className="mt-0.5 break-words">{answerText(draft) || '未作答'}</dd></div>
        <div><dt className="font-semibold">正确答案</dt><dd className="mt-0.5 break-words">{answerText(result.correctAnswer)}</dd></div>
        {result.explanation && <div><dt className="font-semibold">解析</dt><dd className="mt-0.5 max-w-[72ch] break-words">{result.explanation}</dd></div>}
        {result.feedback && result.feedback !== result.explanation && <div><dt className="font-semibold">评分反馈</dt><dd className="mt-0.5 max-w-[72ch] break-words">{result.feedback}</dd></div>}
      </dl>
    </div>}
  </article>;
}

export function ExamQuestionList({ exam, attemptId, onCompleted }: { exam: ExamDetail; attemptId?: string; onCompleted?: (summary: ExamAttemptSummary) => void }) {
  const [attempt, setAttempt] = useState<ExamAttempt | null>(null);
  const [drafts, setDrafts] = useState<Record<string, unknown>>({});
  const [confidences, setConfidences] = useState<Record<string, number | null>>({});
  const [results, setResults] = useState<Record<string, QuestionGradingResult>>({});
  const [pendingQuestionId, setPendingQuestionId] = useState<string | null>(null);
  const [summary, setSummary] = useState<ExamAttemptSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [reviewNote, setReviewNote] = useState('');
  const [clock, setClock] = useState(Date.now());
  const started = useRef<Record<string, number>>({});
  const formal = exam.assessmentMode === 'formal';
  const expired = attempt ? clock >= new Date(attempt.expiresAt).getTime() : false;
  const blocked = Boolean(attempt?.adaptiveState.paused) || expired || attempt?.status === 'graded';

  async function loadAttempt() {
    setLoading(true); setError(''); setSummary(null);
    try {
      const loaded = attemptId ? await api.examAttempt(attemptId) : await api.startExamAttempt(exam.id);
      setAttempt(loaded); setDrafts(loaded.responses); setResults(loaded.results);
      setConfidences(loaded.learnerConfidences);
      if (loaded.status === 'graded') setSummary({ attemptId: loaded.id, score: loaded.score ?? 0, maxScore: loaded.maxScore ?? exam.totalPoints, results: Object.values(loaded.results) });
    } catch (reason) { setError(reason instanceof Error ? reason.message : '无法开始本次练习。'); }
    finally { setLoading(false); }
  }

  useEffect(() => { void loadAttempt(); }, [exam.id, attemptId]);
  useEffect(() => { const timer = window.setInterval(() => setClock(Date.now()), 1000); return () => window.clearInterval(timer); }, []);

  const completedCount = Object.keys(results).length;
  const earnedPoints = useMemo(() => Object.values(results).reduce((sum, result) => sum + result.earnedPoints, 0), [results]);

  async function confirm(question: ExamQuestion) {
    if (!attempt || blocked || !hasAnswer(question, drafts[question.id])) return;
    setPendingQuestionId(question.id); setError(''); setNotice('');
    try {
      const seconds = Math.min(86400, Math.max(0, (Date.now() - (started.current[question.id] ?? Date.now())) / 1000));
      if (formal) {
        await api.saveExamResponse(attempt.id, question.id, drafts[question.id], confidences[question.id] ?? null, seconds);
        setAttempt({ ...attempt, responses: { ...attempt.responses, [question.id]: drafts[question.id] } });
        setNotice(`第 ${exam.questions.indexOf(question) + 1} 题已保存。`);
        return;
      }
      const result = await api.confirmExamResponse(attempt.id, question.id, drafts[question.id], confidences[question.id] ?? null, seconds);
      const nextResults = { ...results, [question.id]: result };
      setResults(nextResults);
      const refreshed = await api.examAttempt(attempt.id);
      setAttempt(refreshed);
      if (Object.keys(nextResults).length === exam.questions.length && !refreshed.adaptiveState.paused) {
        const finished = await api.submitExamAttempt(attempt.id);
        setSummary(finished);
        setAttempt({ ...attempt, status: 'graded', score: finished.score });
        onCompleted?.(finished);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '答案确认失败，输入内容已保留，请重试。');
      try { const fresh = await api.examAttempt(attempt.id); setAttempt(fresh); setResults(fresh.results); } catch { /* Preserve drafts. */ }
    }
    finally { setPendingQuestionId(null); }
  }

  async function finish() {
    if (!attempt) return;
    setPendingQuestionId('submit'); setError('');
    try {
      if (formal && !expired) {
        for (const question of exam.questions) {
          if (hasAnswer(question, drafts[question.id])) await api.saveExamResponse(attempt.id, question.id, drafts[question.id], confidences[question.id] ?? null);
        }
      }
      const finished = await api.submitExamAttempt(attempt.id);
      setSummary(finished); setResults(Object.fromEntries(finished.results.map(result => [result.questionId, result])));
      setAttempt({ ...attempt, status: 'graded' }); onCompleted?.(finished);
    } catch (reason) { setError(reason instanceof Error ? reason.message : '提交失败，已保存的答案可继续提交。'); }
    finally { setPendingQuestionId(null); }
  }

  async function resume() {
    if (!attempt) return;
    setPendingQuestionId('resume'); setError('');
    try { setAttempt(await api.resumeQuiz(attempt.id, reviewNote.trim())); setReviewNote(''); }
    catch (reason) { setError(reason instanceof Error ? reason.message : '暂时无法继续测验。'); }
    finally { setPendingQuestionId(null); }
  }

  if (loading) return <section className="rounded-2xl border border-slate-200 bg-white px-6 py-12 text-center shadow-sm" aria-busy="true"><LoaderCircle className="mx-auto animate-spin text-blue-600" size={28} /><p className="mt-3 text-sm text-slate-600">正在准备答题记录…</p></section>;
  if (!attempt) return <section className="rounded-2xl border border-slate-200 bg-white p-7 shadow-sm"><div className="flex items-start gap-3 text-rose-800"><AlertCircle className="mt-0.5 shrink-0" size={20} /><div><h2 className="font-bold">暂时无法开始答题</h2><p className="mt-1 text-sm leading-6">{error}</p><button type="button" onClick={() => void loadAttempt()} className="mt-4 inline-flex items-center rounded-xl bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-500 focus-visible:ring-offset-2"><RotateCcw className="me-2" size={16} />重新尝试</button></div></div></section>;

  return <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
    <header className="border-b border-slate-200 bg-slate-950 px-5 py-6 text-white sm:px-7">
      <div className="flex flex-wrap items-start justify-between gap-4"><div className="min-w-0"><h2 className="break-words text-xl font-bold">{exam.title}</h2><p className="mt-1 text-sm text-slate-300">{exam.questionCount} 题 · {exam.totalPoints} 分 · 建议 {exam.durationMinutes} 分钟</p></div><div className="shrink-0 text-end"><strong className="block text-lg">{completedCount}/{exam.questionCount}</strong><span className="text-xs text-slate-300">已确认</span></div></div>
      <div className="mt-5 h-2 overflow-hidden rounded-full bg-slate-700" role="progressbar" aria-label="答题进度" aria-valuemin={0} aria-valuemax={exam.questionCount} aria-valuenow={completedCount}><div className="h-full rounded-full bg-emerald-400 transition-[width]" style={{ width: `${exam.questionCount ? completedCount / exam.questionCount * 100 : 0}%` }} /></div>
      <div className="mt-2 flex justify-between gap-4 text-xs text-slate-300"><span>{formal ? '正式考试：整卷提交后显示评分' : '自适应测验：逐题反馈，错误过多时先复习'}</span><span>{formal && !summary ? `剩余 ${Math.max(0, Math.ceil((new Date(attempt.expiresAt).getTime() - clock) / 60000))} 分钟` : `当前 ${earnedPoints}/${exam.totalPoints} 分`}</span></div>
    </header>
    {error && <div className="m-5 flex items-start gap-3 rounded-xl bg-rose-50 p-4 text-sm text-rose-800" role="alert"><AlertCircle className="mt-0.5 shrink-0" size={18} /><span>{error}</span></div>}
    {notice && <p className="m-5 text-sm text-emerald-800" role="status">{notice}</p>}
    {expired && !summary && <p className="m-5 rounded-lg bg-amber-50 p-4 text-sm text-amber-950">答题时间已到，不能修改答案。正式考试可提交已保存的作答；未完成的自适应测验需重新安排。</p>}
    {attempt.adaptiveState.paused && !summary && <div className="m-5 rounded-xl bg-amber-50 p-5 text-amber-950"><h3 className="font-bold">先复习，再继续测验</h3><p className="mt-2 text-sm">暂停原因：{attempt.adaptiveState.reason}。请回顾已确认题目的解析和课程资料，再写下误解与纠正方式。</p><label className="mt-4 block text-sm font-semibold">复习记录（至少 20 字）<textarea className="mt-2 block w-full rounded-lg border border-amber-300 bg-white p-3 text-slate-900 focus:outline-2 focus:outline-blue-600" rows={3} maxLength={2000} value={reviewNote} onChange={event => setReviewNote(event.target.value)}/></label><p className="mt-2 text-xs">这条记录是你的复习说明，系统仍会用后续答题检验掌握程度。</p><button className="mt-4 min-h-11 rounded-lg bg-blue-600 px-4 font-semibold text-white disabled:opacity-50" disabled={Boolean(pendingQuestionId) || expired || reviewNote.trim().length < 20} onClick={() => void resume()}>记录复习并继续</button></div>}
    {summary && <div className="m-5 rounded-xl bg-emerald-50 p-5 text-emerald-950" role="status"><div className="flex items-center gap-2 font-bold"><CheckCircle2 size={20} />本次练习已完成</div><p className="mt-2 text-sm">最终得分 <strong>{summary.score}/{summary.maxScore}</strong>，练习表现已用于掌握度与复习计划。</p></div>}
    <div className="divide-y divide-slate-200">{exam.questions.map((question, index) => <QuestionCard key={question.id} formal={formal} question={question} index={index} draft={drafts[question.id]} result={results[question.id]} pending={Boolean(pendingQuestionId) || blocked} confidence={confidences[question.id] ?? null} onConfidence={(value) => setConfidences((current) => ({ ...current, [question.id]: value }))} onDraft={(value) => { started.current[question.id] ??= Date.now(); setDrafts((current) => ({ ...current, [question.id]: value })); setConfidences((current) => ({ ...current, [question.id]: null })); }} onConfirm={() => void confirm(question)} />)}</div>
    {!summary && (formal || completedCount === exam.questions.length) && <footer className="border-t border-slate-200 p-6"><p className="mb-3 text-sm text-slate-600">{formal ? '未作答题目按零分计算。到时仅提交此前保存的答案。' : '所有题目已确认，可以结束本次测验。'}</p><button className="min-h-11 rounded-lg bg-blue-600 px-5 font-semibold text-white disabled:opacity-50" disabled={Boolean(pendingQuestionId) || Boolean(attempt.adaptiveState.paused)} onClick={() => void finish()}>提交本次评估</button></footer>}
  </section>;
}
