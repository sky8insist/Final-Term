import { FormEvent, useEffect, useState } from 'react';
import { api } from '../../api/client';
import { useAppStore } from '../../stores/useAppStore';
import type { CourseStructure, CourseTopic, LearnerState } from '../../types';
import { CourseExamGoals } from './ExamGoals';

const stateLabels = { not_started: '未开始', covered: '已学习', practicing: '练习中', mastered: '已掌握', at_risk: '需复习' };

const inputClass = 'min-h-11 rounded-lg border border-slate-300 bg-white px-3 text-sm focus-visible:outline-2 focus-visible:outline-blue-600';
const buttonClass = 'min-h-11 rounded-lg px-4 text-sm font-semibold focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600';

export default function Course() {
  const subject = useAppStore((state) => state.currentSubject)!;
  const [data, setData] = useState<CourseStructure | null>(null);
  const [learner, setLearner] = useState<LearnerState | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [showArchived, setShowArchived] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setData(null); setLearner(null); setError(''); setNotice(''); setEditing(null);
    Promise.all([api.courseStructure(subject.id), api.learnerState(subject.id)]).then(([value, states]) => { if (active) { setData(value); setLearner(states); } })
      .catch((e) => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [subject.id]);

  async function mutate(action: () => Promise<unknown>, message: string) {
    setBusy(true); setError(''); setNotice('');
    try {
      await action();
      const [next, states] = await Promise.all([api.courseStructure(subject.id), api.learnerState(subject.id)]);
      setData(next); setLearner(states); setEditing(null); setNotice(message);
    } catch (e) { setError(e instanceof Error ? e.message : '保存失败，请重试。'); }
    finally { setBusy(false); }
  }

  function add(event: FormEvent<HTMLFormElement>, kind: 'unit' | 'topic') {
    event.preventDefault();
    const form = event.currentTarget;
    const fields = new FormData(form);
    const title = String(fields.get('title') || '').trim();
    if (!title) { setError('请输入名称。'); return; }
    void mutate(async () => {
      if (kind === 'unit') await api.createUnit(subject.id, title);
      else await api.createTopic(subject.id, title, String(fields.get('unit') || '') || null);
      form.reset();
    }, kind === 'unit' ? '章节已创建。' : '知识点已保存；已有名称会定位到原知识点。');
  }

  function save(event: FormEvent<HTMLFormElement>, topic: CourseTopic) {
    event.preventDefault();
    const fields = new FormData(event.currentTarget);
    void mutate(() => api.updateTopic(subject.id, topic.id, {
      title: String(fields.get('title')).trim(), unit_id: String(fields.get('unit') || '') || null,
      sequence_index: Number(fields.get('sequence')), syllabus_weight: Number(fields.get('weight')),
    }), '知识点已更新，历史练习与掌握度仍关联原知识点。');
  }

  const visible = data?.topics.filter((topic) => showArchived || !topic.archived) || [];
  const states = new Map(learner?.topics.map((item) => [item.knowledgePointId, item]));
  return <div className="h-full overflow-y-auto p-6 md:p-8">
    <header className="mb-7"><h1 className="text-3xl font-bold">课程结构</h1><p className="mt-2 text-slate-600">整理 {subject.name} 的章节与知识点，让练习、闪卡和复习任务使用同一份课程目录。</p></header>
    {error && <div role="alert" className="mb-4 rounded-lg bg-rose-50 p-4 text-rose-800">{error}</div>}
    {notice && <p role="status" className="mb-4 text-emerald-800">{notice}</p>}
    {!data ? <p role="status">{error ? '课程结构暂时无法加载。' : '正在读取课程结构…'}</p> : <>
      <div className="mb-8 grid gap-6 lg:grid-cols-2">
        <form onSubmit={(event) => add(event, 'unit')} className="flex flex-wrap items-end gap-3">
          <label className="grid flex-1 gap-2 text-sm font-medium">新章节<input name="title" required maxLength={300} className={inputClass}/></label>
          <button disabled={busy} className={`${buttonClass} bg-blue-600 text-white`}>添加章节</button>
        </form>
        <form onSubmit={(event) => add(event, 'topic')} className="flex flex-wrap items-end gap-3">
          <label className="grid flex-1 gap-2 text-sm font-medium">新知识点<input name="title" required maxLength={300} className={inputClass}/></label>
          <label className="grid gap-2 text-sm font-medium">所属章节<select name="unit" className={inputClass}><option value="">未分组</option>{data.units.map((unit) => <option key={unit.id} value={unit.id}>{unit.title}</option>)}</select></label>
          <button disabled={busy} className={`${buttonClass} bg-blue-600 text-white`}>添加知识点</button>
        </form>
      </div>
      <label className="mb-5 flex items-center gap-2 text-sm"><input type="checkbox" checked={showArchived} onChange={(event) => setShowArchived(event.target.checked)}/>显示已归档知识点</label>
      {learner && <p className="mb-5 text-sm text-slate-600">已学习 {learner.counts.covered} · 练习中 {learner.counts.practicing} · 已掌握 {learner.counts.mastered} · 需复习 {learner.counts.at_risk}。掌握状态由练习证据确认。</p>}
      {data.topics.length === 0 && <p className="py-8 text-slate-600">还没有知识点。可以手动添加，生成练习或闪卡后也会自动建立关联。</p>}
      {[...data.units, { id: '', title: '未分组', sequence_index: 0 }].map((unit) => {
        const topics = visible.filter((topic) => (topic.unit_id || '') === unit.id);
        return <section key={unit.id} className="mb-7"><h2 className="mb-2 text-lg font-bold">{unit.title}<span className="ml-2 text-sm font-normal text-slate-500">{topics.length} 个知识点</span></h2>
          {!topics.length && <p className="py-3 text-sm text-slate-500">该章节暂无知识点。</p>}
          <ul className="divide-y divide-slate-200 border-y border-slate-200">{topics.map((topic) => <li key={topic.id} className="py-4">
            {editing === topic.id ? <form onSubmit={(event) => save(event, topic)} className="flex flex-wrap items-end gap-3">
              <label className="grid min-w-48 flex-1 gap-2 text-sm">名称<input name="title" defaultValue={topic.title} required maxLength={300} className={inputClass}/></label>
              <label className="grid gap-2 text-sm">章节<select name="unit" defaultValue={topic.unit_id || ''} className={inputClass}><option value="">未分组</option>{data.units.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}</select></label>
              <label className="grid gap-2 text-sm">顺序<input name="sequence" type="number" min={0} required defaultValue={topic.sequence_index} className={`${inputClass} w-24`}/></label>
              <label className="grid gap-2 text-sm">考试权重<input name="weight" type="number" min={0} max={100} step="any" required defaultValue={topic.syllabus_weight} className={`${inputClass} w-24`}/></label>
              <button disabled={busy} className={`${buttonClass} bg-blue-600 text-white`}>保存</button><button type="button" disabled={busy} onClick={() => setEditing(null)} className={buttonClass}>取消</button>
            </form> : <div className="flex flex-wrap items-center justify-between gap-4"><div className="min-w-0"><p className="break-words font-medium">{topic.title}{topic.archived && <span className="ml-2 text-sm text-slate-500">已归档</span>}</p><p className="mt-1 text-sm text-slate-500">顺序 {topic.sequence_index} · 考试权重 {topic.syllabus_weight}</p>{states.has(topic.id) && <p className="mt-2 text-sm text-slate-700">{stateLabels[states.get(topic.id)!.state]} · {states.get(topic.id)!.assessmentCount > 0 ? `掌握度 ${Math.round(states.get(topic.id)!.masteryScore * 100)}%` : '掌握度待评估'} · 评估证据 {states.get(topic.id)!.assessmentCount} 次{states.get(topic.id)!.reasons.length > 0 && ` · ${states.get(topic.id)!.reasons.join('；')}`}</p>}</div><div className="flex shrink-0 flex-wrap gap-1">{states.get(topic.id)?.state === 'not_started' && <button type="button" disabled={busy} onClick={() => void mutate(() => api.coverTopic(subject.id, topic.id), '已记录学习覆盖；完成练习后才能确认掌握。')} className={buttonClass}>标记已学习<span className="sr-only">{topic.title}</span></button>}<button type="button" disabled={busy} onClick={() => setEditing(topic.id)} className={`${buttonClass} text-blue-700`}>编辑<span className="sr-only">{topic.title}</span></button><button type="button" disabled={busy} onClick={() => void mutate(() => api.updateTopic(subject.id, topic.id, { archived: !topic.archived }), topic.archived ? '知识点已恢复。' : '知识点已归档，历史记录保留。')} className={buttonClass}>{topic.archived ? '恢复' : '归档'}<span className="sr-only">{topic.title}</span></button></div></div>}
          </li>)}</ul>
        </section>;
      })}
      <CourseExamGoals subjectId={subject.id} structure={data}/>
    </>}
  </div>;
}
