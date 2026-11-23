import { FormEvent, useEffect, useState } from 'react';
import { api } from '../../api/client';
import type { CourseStructure, ExamEvent, ExamGoals } from '../../types';

const control = 'min-h-11 rounded-lg border border-slate-300 bg-white px-3 text-sm focus-visible:outline-2 focus-visible:outline-blue-600';
const button = 'min-h-11 rounded-lg px-4 text-sm font-semibold focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600';

export function CourseExamGoals({ subjectId, structure }: { subjectId: string; structure: CourseStructure }) {
  const [goals, setGoals] = useState<ExamGoals | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<ExamEvent | null>(null);
  const topics = structure.topics.filter((topic) => !topic.archived || goals?.exam_topic_map.some((map) => map.exam_event_id === editing?.id && map.knowledge_point_id === topic.id));

  useEffect(() => {
    let active = true;
    setGoals(null); setEditing(null); setError(''); setNotice('');
    api.examGoals(subjectId).then((value) => { if (active) setGoals(value); })
      .catch((e) => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [subjectId]);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const fields = new FormData(event.currentTarget);
    const selected = fields.getAll('topic').map(String);
    if (!selected.length) { setError('请至少选择一个考试知识点。'); return; }
    setBusy(true); setError(''); setNotice('');
    try {
      await api.saveExamEvent(subjectId, { title: String(fields.get('title')).trim(), exam_date: String(fields.get('date')),
        syllabus_id: String(fields.get('syllabus') || '') || null, status: String(fields.get('status') || 'active'),
        topics: selected.map((id) => ({ knowledge_point_id: id, weight: Number(fields.get(`weight-${id}`)) })),
      }, editing?.id);
      setGoals(await api.examGoals(subjectId)); setEditing(null); setNotice('考试目标已保存。');
    } catch (e) { setError(e instanceof Error ? e.message : '保存失败，请重试。'); }
    finally { setBusy(false); }
  }

  async function syllabus(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const fields = new FormData(form);
    setBusy(true); setError(''); setNotice('');
    try {
      await api.createSyllabus(subjectId, { title: String(fields.get('title')).trim(),
        content: { source: 'manual', grading: String(fields.get('grading') || ''),
          units: structure.units, topics: structure.topics.filter((topic) => !topic.archived) },
        topic_ids: structure.topics.filter((topic) => !topic.archived).map((topic) => topic.id),
      });
      setGoals(await api.examGoals(subjectId)); form.reset(); setNotice('当前课程目录已保存为大纲，可关联到考试。');
    } catch (e) { setError(e instanceof Error ? e.message : '保存失败，请重试。'); }
    finally { setBusy(false); }
  }

  const weights = new Map(goals?.exam_topic_map.filter((row) => row.exam_event_id === editing?.id).map((row) => [row.knowledge_point_id, row.weight]));
  return <section className="mt-10 border-t border-slate-200 pt-8">
    <h2 className="text-xl font-bold">考试目标与课程大纲</h2><p className="mt-2 text-sm text-slate-600">记录考试日期、范围和相对权重，保留课程大纲快照。</p>
    {error && <p role="alert" className="my-4 text-rose-800">{error}</p>}{notice && <p role="status" className="my-4 text-emerald-800">{notice}</p>}
    {!goals ? <p role="status" className="mt-4">{error ? '考试目标暂时无法加载。' : '正在读取考试目标…'}</p> : <>
      {goals.exam_events.length > 0 && <ul className="my-5 divide-y divide-slate-200">{goals.exam_events.map((exam) => <li key={exam.id} className="flex items-center justify-between gap-4 py-3"><div><p className="font-medium">{exam.title}</p><p className="mt-1 text-sm text-slate-600">{exam.exam_date} · {{ active: '待考试', completed: '已完成', archived: '已归档' }[exam.status]} · {goals.exam_topic_map.filter((row) => row.exam_event_id === exam.id).length} 个知识点</p></div><button type="button" disabled={busy} className={`${button} text-blue-700`} onClick={() => { setEditing(exam); setNotice(''); }}>编辑<span className="sr-only">{exam.title}</span></button></li>)}</ul>}
      <form key={editing?.id || 'new'} onSubmit={save} className="mt-6 space-y-4">
        <h3 className="font-semibold">{editing ? '编辑考试目标' : '添加考试目标'}</h3>
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <label className="grid gap-2 text-sm">考试名称<input name="title" defaultValue={editing?.title || ''} required maxLength={300} className={control}/></label>
          <label className="grid gap-2 text-sm">考试日期<input name="date" type="date" defaultValue={editing?.exam_date || ''} required className={control}/></label>
          <label className="grid gap-2 text-sm">关联大纲<select name="syllabus" defaultValue={editing?.syllabus_id || ''} className={control}><option value="">暂不关联</option>{goals.syllabi.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}</select></label>
          <label className="grid gap-2 text-sm">状态<select name="status" defaultValue={editing?.status || 'active'} className={control}><option value="active">待考试</option><option value="completed">已完成</option><option value="archived">已归档</option></select></label>
        </div>
        <fieldset disabled={busy}><legend className="mb-3 text-sm font-semibold">考试范围与相对权重（0–100，0 表示不计入优先级）</legend><div className="grid gap-3 md:grid-cols-2">{topics.map((topic) => <div key={topic.id} className="flex items-center justify-between gap-3"><label className="flex min-h-11 items-center gap-2 text-sm"><input type="checkbox" name="topic" value={topic.id} defaultChecked={weights.has(topic.id)}/>{topic.title}{topic.archived ? '（已归档）' : ''}</label><input type="number" name={`weight-${topic.id}`} aria-label={`${topic.title} 的考试权重`} min={0} max={100} step="any" defaultValue={weights.get(topic.id) ?? topic.syllabus_weight} className={`${control} w-24`}/></div>)}</div>{topics.length === 0 && <p className="py-3 text-sm text-slate-600">先添加知识点，再设置考试范围。</p>}</fieldset>
        <div className="flex gap-2"><button disabled={busy || topics.length === 0} className={`${button} bg-blue-600 text-white`}>{busy ? '正在保存…' : '保存考试目标'}</button>{editing && <button type="button" disabled={busy} className={button} onClick={() => setEditing(null)}>取消编辑</button>}</div>
      </form>
      <form onSubmit={syllabus} className="mt-8 space-y-4 border-t border-slate-200 pt-6"><h3 className="font-semibold">保存课程大纲</h3><p className="text-sm text-slate-600">将当前所有活动章节与知识点保存为快照。课程目录后续修改时，已有大纲仍保留原记录。</p><div className="grid gap-4 md:grid-cols-2"><label className="grid gap-2 text-sm">大纲名称<input name="title" required maxLength={300} className={control}/></label><label className="grid gap-2 text-sm">评分方式（可选）<input name="grading" maxLength={1000} className={control}/></label></div><button disabled={busy || !structure.topics.some((topic) => !topic.archived)} className={`${button} border border-slate-300`}>保存大纲快照</button></form>
    </>}
  </section>;
}
