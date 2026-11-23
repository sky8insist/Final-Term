import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { ConversionHistory } from '../../components/TurnInto';
import { api } from '../../api/client';
import { FlashcardReviewPanel } from '../../components/FlashcardReviewPanel';
import { useAppStore } from '../../stores/useAppStore';
import type { FlashcardQueue } from '../../types';

function ReviewQueue({ subjectId }: { subjectId: string }) {
  const [params] = useSearchParams();
  const artifactId = params.get('artifactId') || undefined;
  const [queue, setQueue] = useState<FlashcardQueue | null>(null);
  const [future, setFuture] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);
  useEffect(() => {
    let stopped = false; setLoading(true);
    api.flashcardQueue(subjectId, artifactId, future).then(value => {
      if (!stopped) { setQueue(value); setError(''); }
    }).catch(reason => { if (!stopped) setError(reason instanceof Error ? reason.message : '无法读取复习队列。'); })
      .finally(() => { if (!stopped) setLoading(false); });
    return () => { stopped = true; };
  }, [subjectId, artifactId, future, reload]);
  const card = queue?.cards[0];
  return <div className="h-full overflow-y-auto p-6 lg:p-8"><div className="mx-auto max-w-3xl">
    <h1 className="text-2xl font-bold text-slate-950">闪卡复习</h1>
    <p className="mt-2 text-sm leading-6 text-slate-600">先尝试回忆，再查看答案。每张卡片单独安排下次复习，评价会保存到学习记录。</p>
    <div className="my-6 flex flex-wrap items-center justify-between gap-4"><p role="status" className="font-semibold text-slate-800">{queue ? `当前到期 ${queue.dueCount} 张 · 逾期 ${queue.subjects.reduce((n, s) => n + s.overdue, 0)} 张 · 共 ${queue.totalCount} 张` : '正在读取队列…'}</p><button className="min-h-11 rounded-lg px-3 text-sm font-semibold text-blue-700 focus-visible:outline-2 focus-visible:outline-blue-600" disabled={loading} onClick={() => setReload(n => n + 1)}>刷新队列</button></div>
    <label className="mb-5 flex min-h-11 items-center gap-3 text-sm text-slate-700"><input type="checkbox" checked={future} onChange={event => setFuture(event.target.checked)}/>也显示尚未到期的卡片</label>
    {error && <p role="alert" className="mb-5 rounded-lg bg-rose-50 p-4 text-sm text-rose-900">{error}</p>}
    {loading ? <p role="status" className="py-10 text-slate-600">正在更新复习队列…</p> : card ? <FlashcardReviewPanel key={`${card.artifact_id}:${card.card_id}:${card.state.version}`} card={card} onReviewed={() => setReload(n => n + 1)} onConflict={() => setReload(n => n + 1)}/> : <div className="rounded-xl border border-slate-200 bg-white p-6"><h2 className="text-lg font-semibold">{queue?.totalCount ? '当前到期卡片已复习完' : '还没有可复习的闪卡'}</h2><p className="mt-3 text-sm leading-6 text-slate-600">{queue?.subjects[0]?.next_review ? `下一次到期：${new Date(queue.subjects[0].next_review).toLocaleString('zh-CN')}。` : '在引导学习中选择知识点，可以生成并学习闪卡。'}</p><Link to="/guided-study" className="mt-4 inline-block min-h-11 py-3 font-semibold text-blue-700 underline">进入引导学习</Link></div>}
    <p className="mt-6 text-sm leading-6 text-slate-600">逾期指已复习卡片的到期时间早于今天（北京时间）。闪卡评价帮助安排复习；掌握状态仍需要客观评估证据。</p>
    {artifactId && <ConversionHistory subjectId={subjectId} objectId={artifactId}/>}
  </div></div>;
}

export default function Flashcards() {
  const { currentSubject } = useAppStore();
  return currentSubject ? <ReviewQueue key={currentSubject.id} subjectId={currentSubject.id}/> : null;
}
