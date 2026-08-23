import { BookOpen, FileQuestion, Layers3, Star, X } from 'lucide-react';
import type { MindMapData, MindMapNode } from '../../../types';

type Props = {
  node: MindMapNode; data: MindMapData; creatingFlashcards: boolean; flashcardMessage: string;
  onClose: () => void; onCreateFlashcards: (node: MindMapNode) => void; onCreateExam: (node: MindMapNode) => void;
};

export function NodeDetailDrawer({ node, data, creatingFlashcards, flashcardMessage, onClose, onCreateFlashcards, onCreateExam }: Props) {
  const sources = data.sources.filter((source) => node.sourceIds.includes(source.id));
  const relations = data.edges.filter((edge) => edge.source === node.id || edge.target === node.id);
  const mastery = node.mastery == null ? null : Math.round(node.mastery * 100);
  const nodeName = (id: string) => data.nodes.find((item) => item.id === id)?.label ?? id;
  return (
    <aside className="absolute inset-y-0 right-0 z-20 w-[390px] overflow-y-auto border-l border-slate-200 bg-white shadow-2xl" aria-label="知识点详情">
      <div className="sticky top-0 z-10 flex items-center justify-between border-b bg-white/95 px-5 py-4 backdrop-blur">
        <div><div className="text-xs font-semibold uppercase tracking-widest text-blue-600">知识点详情</div><h2 className="mt-1 text-xl font-bold text-slate-900">{node.label}</h2></div>
        <button type="button" onClick={onClose} aria-label="关闭详情" className="rounded-lg p-2 text-slate-500 hover:bg-slate-100"><X size={19} /></button>
      </div>
      <div className="space-y-6 p-5">
        <section><h3 className="mb-2 text-sm font-semibold text-slate-900">核心解释</h3><p className="text-sm leading-7 text-slate-600">{node.description || '暂无补充解释。'}</p></section>
        <div className="grid grid-cols-2 gap-3">
          <div className="rounded-xl bg-slate-50 p-3"><div className="text-xs text-slate-500">掌握度</div><div className="mt-1 font-bold">{mastery == null ? '尚未评估' : `${mastery}%`}</div></div>
          <div className="rounded-xl bg-slate-50 p-3"><div className="text-xs text-slate-500">考试重要度</div><div className="mt-1 flex items-center gap-1 font-bold">{node.examImportance === 'high' && <Star size={14} className="fill-amber-400 text-amber-500" />}{node.examImportance === 'high' ? '高' : node.examImportance === 'medium' ? '中' : '低'}</div></div>
        </div>
        {relations.length > 0 && <section><h3 className="mb-2 flex items-center gap-2 text-sm font-semibold"><Layers3 size={16} />知识关系</h3><div className="space-y-2">{relations.map((edge, index) => <div key={`${edge.source}-${edge.target}-${index}`} className="rounded-xl border bg-slate-50 p-3 text-sm text-slate-600">{nodeName(edge.source)} <span className="mx-1 font-semibold text-blue-600">—{edge.relation}→</span> {nodeName(edge.target)}</div>)}</div></section>}
        <section><h3 className="mb-2 flex items-center gap-2 text-sm font-semibold"><BookOpen size={16} />资料来源</h3>{sources.length ? <div className="space-y-3">{sources.map((source) => <article key={source.id} className="rounded-xl border border-emerald-100 bg-emerald-50/50 p-3"><div className="text-xs font-semibold text-emerald-800">{source.sourceName}{source.pageNumber ? ` · P${source.pageNumber}` : ''}</div><p className="mt-2 line-clamp-5 text-xs leading-5 text-slate-600">{source.text}</p></article>)}</div> : <p className="text-sm text-slate-500">该节点没有单独引用；请查看其子节点来源。</p>}</section>
        <section className="space-y-2 border-t pt-5">
          <button type="button" disabled={creatingFlashcards} onClick={() => onCreateFlashcards(node)} className="flex w-full items-center justify-center gap-2 rounded-xl bg-blue-600 px-4 py-3 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-60"><Layers3 size={17} />{creatingFlashcards ? '正在生成闪卡…' : '针对该知识点生成闪卡'}</button>
          <button type="button" onClick={() => onCreateExam(node)} className="flex w-full items-center justify-center gap-2 rounded-xl border px-4 py-3 text-sm font-semibold text-slate-700 hover:bg-slate-50"><FileQuestion size={17} />针对该知识点练习</button>
          {flashcardMessage && <p className="text-center text-xs text-emerald-700" role="status">{flashcardMessage}</p>}
        </section>
      </div>
    </aside>
  );
}

