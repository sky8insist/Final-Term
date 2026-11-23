import { BookOpen, Layers3, Star, X } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../../../api/client';
import { TurnInto } from '../../../components/TurnInto';
import { useAppStore } from '../../../stores/useAppStore';
import type { CourseTopic, MindMapData, MindMapNode } from '../../../types';

type Props = {
  node: MindMapNode; data: MindMapData; onClose: () => void; onSaved: () => Promise<void>;
};

export function NodeDetailDrawer({ node, data, onClose, onSaved }: Props) {
  const subject = useAppStore(state => state.currentSubject)!;
  const learning = node.learning;
  const [topics, setTopics] = useState<CourseTopic[]>([]);
  const [topicId, setTopicId] = useState(learning?.knowledgePointId ?? '');
  const [busy, setBusy] = useState(false);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    let active = true;
    api.courseStructure(subject.id).then(value => { if (active) { setTopics(value.topics.filter(topic => !topic.archived)); setReady(true); } })
      .catch(reason => { if (active) setError(reason instanceof Error ? reason.message : '无法读取课程知识点，请关闭后重试。'); });
    return () => { active = false; };
  }, [subject.id]);
  async function save() {
    if (!data.artifactId || !data.artifactVersion || !learning) return;
    setBusy(true); setError('');
    try {
      await api.bindMindMapTopic(data.artifactId, node.id, topicId || null, data.artifactVersion, learning.bindingVersion);
      await onSaved();
    } catch (reason) { setError(reason instanceof Error ? reason.message : '保存失败，请刷新后重试。'); }
    finally { setBusy(false); }
  }
  const date = (value: string | null | undefined) => value ? new Date(value).toLocaleString('zh-CN') : '暂无记录';
  const percent = (value: number | null | undefined) => value == null ? '尚未评估' : `${Math.round(value * 100)}%`;
  const stateNames = { unbound: '尚未关联', not_started: '尚未开始', covered: '已覆盖', practicing: '练习中', mastered: '已掌握', at_risk: '需巩固' };
  const sources = data.sources.filter((source) => node.sourceIds.includes(source.id));
  const relations = data.edges.filter((edge) => edge.source === node.id || edge.target === node.id);
  const mastery = node.mastery == null ? null : Math.round(node.mastery * 100);
  const nodeName = (id: string) => data.nodes.find((item) => item.id === id)?.label ?? id;
  return (
    <aside className="absolute inset-y-0 right-0 z-20 w-full max-w-[420px] overflow-y-auto border-l border-slate-200 bg-white shadow-2xl" aria-label="知识点详情">
      <div className="sticky top-0 z-10 flex items-center justify-between border-b bg-white/95 px-5 py-4 backdrop-blur">
        <div>
<h2 className="mt-1 text-xl font-bold text-slate-900">{node.label}</h2>
</div>
        <button type="button" onClick={onClose} aria-label="关闭详情" className="min-h-11 min-w-11 rounded-lg p-2 text-slate-500 hover:bg-slate-100">
<X size={19} />
</button>
      </div>
      <div className="space-y-6 p-5">
        <section className="space-y-3">
          <label htmlFor="map-topic" className="block text-sm font-semibold">关联课程知识点</label>
          <select id="map-topic" value={topicId} disabled={!ready || busy} onChange={event => setTopicId(event.target.value)} className="min-h-11 w-full rounded-lg border bg-white px-3 text-sm">
            <option value="">尚未关联</option>
            {topics.map(topic => <option key={topic.id} value={topic.id}>{topic.title}</option>)}
          </select>
          <p className="text-xs leading-5 text-slate-600">关联后读取课程学习记录，不会自动标记已学会。</p>
          {learning?.stale && <p className="text-sm text-amber-800">原节点已变化或知识点已归档，请重新关联。</p>}
          <button type="button" disabled={!ready || busy || !learning} onClick={() => void save()} className="min-h-11 rounded-lg bg-blue-700 px-4 text-sm font-semibold text-white disabled:opacity-50">{busy ? '正在保存…' : '保存关联'}</button>
          {error && <p role="alert" className="text-sm text-rose-700">{error}</p>}
          <Link to="/course" className="block text-sm text-blue-700 underline">管理课程知识点</Link>
        </section>
        <section className="space-y-3 border-y py-4 text-sm">
          <h3 className="font-semibold">学习状态：{stateNames[learning?.state ?? 'unbound']}</h3>
          {learning?.knowledgePointId && <>
            <p>课程知识点：{learning.topicTitle}</p>
            <dl className="grid grid-cols-2 gap-3">
              <div><dt className="text-slate-600">数据置信度</dt><dd>{percent(learning.masteryConfidence)}</dd></div>
              <div><dt className="text-slate-600">自报信心</dt><dd>{percent(learning.learnerConfidence)}</dd></div>
              <div><dt className="text-slate-600">上次复习</dt><dd>{date(learning.lastReviewAt)}</dd></div>
              <div><dt className="text-slate-600">下次复习</dt><dd>{date(learning.nextReviewAt)}</dd></div>
            </dl>
            <p>待复习卡片：{learning.dueCards} 张</p>
            {learning.misconceptionRisk >= 0.75 && <p className="text-amber-800">存在误解风险，建议重新练习并核对解释。</p>}
            <Link className="inline-flex min-h-11 items-center text-blue-700 underline" to={`/guided-study?topicId=${encodeURIComponent(learning.knowledgePointId)}`}>围绕此知识点引导学习</Link>
            <h4 className="font-semibold">关联考试与计划</h4>
            {learning.exams.length ? learning.exams.map(exam => <Link key={exam.id} className="block py-2 text-blue-700 underline" to={`/plan?examEventId=${encodeURIComponent(exam.id)}`}>{exam.title} · {exam.date} · 范围权重 {exam.weight} · 查看考试计划</Link>) : <p className="text-slate-600">暂无关联的待考考试。</p>}
          </>}
        </section>
        <section>
<h3 className="mb-2 text-sm font-semibold text-slate-900">核心解释</h3>
<p className="text-sm leading-7 text-slate-600">{node.description || '暂无补充解释。'}</p>
</section>
        <div className="grid grid-cols-2 gap-3">
          <div className="rounded-xl bg-slate-50 p-3">
<div className="text-xs text-slate-500">掌握度</div>
<div className="mt-1 font-bold">{mastery == null ? '尚未评估' : `${mastery}%`}</div>
</div>
          <div className="rounded-xl bg-slate-50 p-3">
<div className="text-xs text-slate-500">生成时重要度</div>
<div className="mt-1 flex items-center gap-1 font-bold">{node.examImportance === 'high' && <Star size={14} className="fill-amber-400 text-amber-500" />}{node.examImportance === 'high' ? '高' : node.examImportance === 'medium' ? '中' : '低'}</div>
</div>
        </div>
        {relations.length > 0 && <section>
<h3 className="mb-2 flex items-center gap-2 text-sm font-semibold">
<Layers3 size={16} />知识关系</h3>
<div className="space-y-2">{relations.map((edge, index) => <div key={`${edge.source}-${edge.target}-${index}`} className="rounded-xl border bg-slate-50 p-3 text-sm text-slate-600">{nodeName(edge.source)} <span className="mx-1 font-semibold text-blue-600">—{edge.relation}→</span> {nodeName(edge.target)}</div>)}</div>
</section>}
        <section>
<h3 className="mb-2 flex items-center gap-2 text-sm font-semibold">
<BookOpen size={16} />资料来源</h3>{sources.length ? <div className="space-y-3">{sources.map((source) => <article key={source.id} className="rounded-xl border border-emerald-100 bg-emerald-50/50 p-3">
<div className="text-xs font-semibold text-emerald-800">{source.sourceName}{source.pageNumber ? ` · P${source.pageNumber}` : ''}</div>
<p className="mt-2 line-clamp-5 text-xs leading-5 text-emerald-900">{source.text}</p>
</article>)}</div> : <p className="text-sm text-slate-500">该节点没有单独引用；请查看其子节点来源。</p>}</section>
        {data.artifactId && data.artifactVersion && sources.length > 0 ? <TurnInto key={`${data.artifactId}:${data.artifactVersion}:${node.id}`} subjectId={subject.id} source={{ kind: 'mind_map_node', id: data.artifactId, version: data.artifactVersion, nodeId: node.id }}/> : <p className="text-sm text-slate-600">需要已保存的导图版本和节点引用，才能转换此节点。</p>}
      </div>
    </aside>
  );
}
