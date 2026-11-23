import { useRef, useState } from 'react';
import { api, ApiError } from '../api/client';
import type { FlashcardReviewLog, ScheduledFlashcard } from '../types';

const ratings = [['again', '忘记了'], ['hard', '较难'], ['good', '记住了'], ['easy', '很轻松']] as const;
const button = 'min-h-11 rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-800 hover:bg-slate-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600 disabled:opacity-50';

export function FlashcardReviewPanel({ card, onReviewed, onConflict, completed = false }: {
  card: ScheduledFlashcard; onReviewed: () => void; onConflict: () => void; completed?: boolean;
}) {
  const [revealed, setRevealed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [history, setHistory] = useState<FlashcardReviewLog[] | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const pending = useRef<{ id: string; rating: string; version: number } | null>(null);
  async function review(rating: string) {
    if (busy || (pending.current && pending.current.rating !== rating)) return;
    pending.current ??= { id: crypto.randomUUID(), rating, version: card.state.version };
    setBusy(true); setError('');
    try {
      await api.reviewFlashcard(card.artifact_id, card.card_id, rating, pending.current.id, pending.current.version);
      pending.current = null; onReviewed();
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 409) { pending.current = null; onConflict(); }
      setError(reason instanceof Error ? reason.message : '评价未确认，请重试相同评价。');
    } finally { setBusy(false); }
  }
  async function showHistory() {
    if (historyOpen) { setHistoryOpen(false); return; }
    setBusy(true); setError('');
    try { setHistory(await api.flashcardHistory(card.artifact_id, card.card_id)); setHistoryOpen(true); }
    catch (reason) { setError(reason instanceof Error ? reason.message : '无法读取复习记录。'); }
    finally { setBusy(false); }
  }
  return <article className="rounded-xl border border-slate-200 bg-white p-6" aria-busy={busy}>
    <p className="text-sm text-slate-600">复习 {card.state.review_count} 次 · 遗忘 {card.state.lapse_count} 次{card.overdue && ' · 已逾期'}</p>
    <h2 className="mt-4 whitespace-pre-wrap text-xl font-semibold leading-relaxed text-slate-950">{card.front}</h2>
    {!revealed && !completed && <button type="button" className={`${button} mt-5`} onClick={() => setRevealed(true)}>先回忆，再查看答案</button>}
    {(revealed || completed) && <p className="mt-5 whitespace-pre-wrap border-t border-slate-200 pt-5 leading-7 text-slate-700">{card.back}</p>}
    {completed ? <p role="status" className="mt-4 text-sm text-blue-800">本步骤已评价，下次复习：{new Date(card.state.next_review).toLocaleString('zh-CN')}</p> : revealed && <div className="mt-6 flex flex-wrap gap-3">{ratings.map(([rating, label]) => <button key={rating} type="button" className={button} disabled={busy || Boolean(pending.current && pending.current.rating !== rating)} onClick={() => void review(rating)}>{pending.current?.rating === rating ? `${label} · 重试保存` : label}</button>)}</div>}
    {error && <p role="alert" className="mt-4 text-sm text-rose-800">{error}</p>}
    <div className="mt-5 flex flex-wrap items-center justify-between gap-3 text-sm text-slate-600"><span>到期：{new Date(card.state.next_review).toLocaleString('zh-CN')}</span><button type="button" className={button} disabled={busy} aria-expanded={historyOpen} onClick={() => void showHistory()}>{historyOpen ? '收起记录' : '复习记录'}</button></div>
    {historyOpen && <div className="mt-4 border-t border-slate-200 pt-4">{!history?.length ? <p className="text-sm text-slate-600">还没有复习记录。</p> : <ol className="space-y-3 text-sm text-slate-700">{history.map(log => <li key={log.id}>{new Date(log.reviewed_at).toLocaleString('zh-CN')} · {ratings.find(([rating]) => rating === log.rating)?.[1]} · 下次 {new Date(log.state_after.next_review).toLocaleString('zh-CN')} · 内容版本 {log.content_version}</li>)}</ol>}</div>}
  </article>;
}
