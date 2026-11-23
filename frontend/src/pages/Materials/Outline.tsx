import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../../api/client';
import type { MaterialOutline, MaterialSection, TopicProposal } from '../../types/materialOutline';

const control = 'min-h-11 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600 disabled:opacity-50';

function ProposalRow({ section, proposal, disabled, onDecide }: {
  section: MaterialSection; proposal?: TopicProposal; disabled: boolean;
  onDecide: (proposal: TopicProposal, action: 'accept' | 'reject', title: string) => Promise<void>;
}) {
  const [title, setTitle] = useState(proposal?.title ?? section.title);
  const id = proposal?.id ?? section.blockIds[0];
  return <li className="min-w-0 border-t border-slate-200 py-4 first:border-0">
    <p className="break-words font-medium">{section.headingPath.join(' / ') || section.title}</p>
    <p className="mt-1 text-sm text-slate-600">{section.blockIds.length} 个内容块{section.pageNumber ? ` · 第 ${section.pageNumber} 页起` : ' · 原文件无页码'}</p>
    <blockquote className="mt-2 whitespace-pre-wrap break-words text-sm leading-6 text-slate-700">原文标题：{section.title}</blockquote>
    {proposal?.status === 'pending' ? <div className="mt-3 flex flex-wrap items-end gap-3">
      <div className="min-w-0 flex-1 basis-52"><label htmlFor={`topic-${id}`} className="mb-1 block text-sm text-slate-700">确认知识点名称</label>
        <input id={`topic-${id}`} maxLength={300} disabled={disabled} value={title} onChange={(event) => setTitle(event.target.value)} className={`${control} w-full`}/></div>
      <button type="button" disabled={disabled || !title.trim()} className={control} onClick={() => void onDecide(proposal, 'accept', title.trim())}>接受提案</button>
      <button type="button" disabled={disabled} className={control} onClick={() => void onDecide(proposal, 'reject', title.trim())}>拒绝提案</button>
    </div> : proposal ? <p className="mt-3 text-sm font-medium text-slate-700">{proposal.status === 'accepted' ? `已接受：${proposal.title}` : '已拒绝，不会加入课程结构'}</p> : <p className="mt-2 text-sm text-slate-600">正文前言保留为章节内容，不生成知识点。</p>}
  </li>;
}

export function Outline({ subjectId, materialId }: { subjectId: string; materialId: string }) {
  const [outline, setOutline] = useState<MaterialOutline | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  useEffect(() => {
    let stopped = false;
    api.materialOutline(subjectId, materialId).then((value) => { if (!stopped) setOutline(value); })
      .catch((cause: Error) => { if (!stopped) setError(cause.message); })
      .finally(() => { if (!stopped) setLoading(false); });
    return () => { stopped = true; };
  }, [subjectId, materialId]);
  async function prepare() {
    setBusy(true); setError(''); setNotice('');
    try { setOutline(await api.prepareMaterialOutline(subjectId, materialId)); }
    catch (cause) { setError(cause instanceof Error ? cause.message : '章节生成失败，请重试。'); }
    finally { setBusy(false); }
  }
  async function decide(proposal: TopicProposal, action: 'accept' | 'reject', title: string) {
    setBusy(true); setError(''); setNotice('');
    try {
      const saved = await api.decideMaterialTopic(proposal.id, proposal.version, action, action === 'accept' ? title : undefined);
      setOutline((current) => current ? { ...current, proposals: current.proposals.map((row) => row.id === saved.id ? saved : row) } : current);
      setNotice(action === 'accept' ? '已加入课程结构。已有同名知识点会沿用原记录。' : '已拒绝此提案。');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '确认失败，请刷新提案。');
      // A conflict can mean another tab decided it or the source changed.
      try { setOutline(await api.materialOutline(subjectId, materialId)); } catch { /* keep the action error visible */ }
    } finally { setBusy(false); }
  }
  return <section aria-label="章节与知识点提案" className="col-span-full min-w-0 border-t border-slate-200 pt-4">
    <div className="flex flex-wrap items-center justify-between gap-3"><h2 className="text-base font-semibold">章节与知识点提案</h2>
      <button type="button" className={control} disabled={busy || loading} onClick={() => void prepare()}>{busy ? '正在处理…' : outline ? '重新检查章节' : '生成章节提案'}</button></div>
    <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">按资料标题划分章节。接受后才加入<Link to="/course" className="mx-1 text-blue-800 underline underline-offset-4">课程结构</Link>，不会自动标记已学会；请先核对原文标题和章节归属。</p>
    {loading && <p role="status" className="mt-3 text-sm text-slate-600">正在加载章节…</p>}
    {error && <p role="alert" className="mt-3 break-words text-sm text-rose-800">{error}</p>}
    {notice && <p role="status" className="mt-3 text-sm text-slate-700">{notice}</p>}
    {outline?.stale && <p role="status" className="mt-3 text-sm font-medium text-rose-800">原文或处理状态已变化，旧提案不能继续确认。请重新检查章节。</p>}
    {!loading && !outline && <p className="mt-3 text-sm text-slate-600">尚未生成章节，可点击上方按钮开始。</p>}
    {outline && !outline.proposals.length && <p className="mt-3 text-sm text-slate-600">未识别到可用标题，正文仍保留。当前不会从正文猜测知识点。</p>}
    {outline && <ul className="mt-3">{outline.sections.map((section) => {
      const proposal = outline.proposals.find((row) => row.source_block_id === section.sourceBlockId);
      return <ProposalRow key={`${outline.id}:${section.blockIds[0]}`} section={section} proposal={proposal} disabled={busy || outline.stale} onDecide={decide}/>;
    })}</ul>}
  </section>;
}
