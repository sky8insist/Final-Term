import { useEffect, useId, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api/client';
import { useAuth } from '../auth/AuthProvider';
import type { NoteMode } from '../types';
import type { Conversion, ConversionInput, ConversionSource, ConversionTarget } from '../types/conversion';
import { targetNames } from '../types/conversion';

const control = 'min-h-11 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600 disabled:opacity-50';
const statusNames: Record<string, string> = { queued: '等待开始', running: '正在生成', succeeded: '已完成', failed: '未完成', cancelled: '已取消' };
const errorText = (reason: unknown) => reason instanceof Error ? reason.message : '操作未完成，请重试。';

export function ConversionHistory({ subjectId, objectId }: { subjectId: string; objectId?: string }) {
  const [rows, setRows] = useState<Conversion[]>([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState('');
  const [reload, setReload] = useState(0);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let stopped = false;
    let timer: number;
    const load = async () => {
      try {
        const values = await api.conversions(subjectId, objectId);
        if (stopped) return;
        setRows(values); setError('');
        if (values.some(row => ['queued', 'running'].includes(row.task.status))) timer = window.setTimeout(() => void load(), 3000);
      } catch (reason) { if (!stopped) setError(errorText(reason)); }
      finally { if (!stopped) setLoading(false); }
    };
    void load();
    return () => { stopped = true; window.clearTimeout(timer); };
  }, [subjectId, objectId, reload]);
  async function act(id: string, retry: boolean) {
    setBusy(id);
    try { if (retry) await api.retryConversion(id); else await api.cancelConversion(id); setReload(value => value + 1); }
    catch (reason) { setError(errorText(reason)); }
    finally { setBusy(''); }
  }
  return <section aria-label="转换记录" className="mt-5 border-t border-slate-200 pt-4">
    <div className="flex items-center justify-between gap-3">
      <h3 className="font-semibold">转换记录</h3>
      <button type="button" className={control} disabled={Boolean(busy)} onClick={() => setReload(value => value + 1)}>刷新记录</button>
    </div>
    {error && <p role="alert" className="mt-3 text-sm text-rose-800">{error}</p>}
    {loading && <p role="status" className="mt-3 text-sm text-slate-600">正在读取转换记录…</p>}
    {!loading && !rows.length && !error && <p className="mt-3 text-sm text-slate-600">还没有转换记录。来源和生成结果都会保留在这里。</p>}
    <ul className="mt-3 divide-y divide-slate-200">
      {rows.map(row => <li key={row.id} className="py-4">
        <p className="break-words text-sm font-semibold">{row.source_title} → {targetNames[row.target]}</p>
        <p className="mt-1 text-sm text-slate-600" role="status">{statusNames[row.task.status]}{row.source_version ? ` · 来源版本 ${row.source_version}` : ''}{row.source_node_id ? ' · 所选节点' : ''}</p>
        {row.warnings?.includes('material_first_30_blocks') && <p className="mt-2 text-sm text-amber-800">本次使用资料的前 30 个内容块，未覆盖整份资料。</p>}
        {row.task.errorMessage && <p className="mt-2 text-sm text-rose-800">{row.task.errorMessage}</p>}
        <div className="mt-2 flex flex-wrap gap-3">
          {row.source_href && <Link to={row.source_href} className={`${control} inline-flex items-center text-blue-700`}>打开原学习来源</Link>}
          {row.task.status === 'succeeded' && row.result_href && <Link to={row.result_href} className={`${control} inline-flex items-center font-semibold text-blue-700`}>打开{targetNames[row.target]}</Link>}
          {['queued', 'running'].includes(row.task.status) && <button type="button" className={control} disabled={busy === row.id} onClick={() => void act(row.id, false)}>取消转换</button>}
          {row.task.status === 'failed' && row.task.attempts < row.task.maxAttempts && <button type="button" className={control} disabled={busy === row.id} onClick={() => void act(row.id, true)}>重试原任务</button>}
        </div>
      </li>)}
    </ul>
  </section>;
}

export function TurnInto({ subjectId, source, disabled = false }: { subjectId: string; source: ConversionSource; disabled?: boolean }) {
  const { user } = useAuth();
  const labelId = useId();
  const [targets, setTargets] = useState<ConversionTarget[]>([]);
  const [target, setTarget] = useState<ConversionTarget | ''>('');
  const [count, setCount] = useState(10);
  const [mode, setMode] = useState<NoteMode>('standard');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [reload, setReload] = useState(0);
  const [pending, setPending] = useState<ConversionInput | null>(null);
  const scopeKey = `examai-conversion:${user?.id}:${subjectId}:${source.kind}:${source.id}:${source.version || ''}:${source.nodeId || ''}`+(source.blockIds?.length?`:blocks:${source.blockIds.join(',')}`:'');
  useEffect(() => {
    let stopped = false;
    api.conversionCapabilities().then(values => { if (!stopped) { setTargets(values[source.kind]); setTarget(values[source.kind][0]); } })
      .catch(reason => { if (!stopped) setError(errorText(reason)); });
    try {
      const stored = JSON.parse(sessionStorage.getItem(scopeKey) || 'null') as ConversionInput | null;
      if (stored && stored.subjectId === subjectId && JSON.stringify(stored.source) === JSON.stringify(source)) setPending(stored);
    } catch { /* Conversion history remains persisted on the server. */ }
    return () => { stopped = true; };
  }, [source.kind, scopeKey, subjectId]);
  async function submit() {
    if (!target || !user || disabled || busy) return;
    const payload = pending || { requestId: crypto.randomUUID(), subjectId, source, target, count, mode };
    setPending(payload); setBusy(true); setError(''); setNotice('');
    try { sessionStorage.setItem(scopeKey, JSON.stringify(payload)); } catch { /* Keep request ID in memory while this page stays open. */ }
    try {
      await api.convert(payload);
      setPending(null);
      try { sessionStorage.removeItem(scopeKey); } catch { /* A persisted request can safely replay. */ }
      setNotice('转换已提交。可以继续学习，刷新后仍能查看进度。'); setReload(value => value + 1);
    } catch (reason) { setError(errorText(reason)); }
    finally { setBusy(false); }
  }
  return <section aria-labelledby={labelId} className="mt-6">
    <h2 id={labelId} className="font-semibold">换一种方式学习</h2>
    <p className="mt-2 text-sm leading-6 text-slate-600">转换保留来源和引用，完成后打开生成结果。不会改变当前学习内容。</p>
    {source.kind === 'material' && <p className="mt-2 text-sm text-slate-600">{source.blockIds?.length?'仅使用已选择的内容块，保留其原始引用与时间信息。':'最多使用所选资料的前 30 个内容块。'}</p>}
    {disabled && <p className="mt-2 text-sm text-amber-800">请先保存当前内容，再转换已保存的版本。</p>}
    <fieldset disabled={disabled || busy || Boolean(pending)} className="mt-3 flex flex-wrap gap-3">
      <label className="flex flex-col gap-2 text-sm">学习方式
        <select className={control} value={target} onChange={event => setTarget(event.target.value as ConversionTarget)}>{targets.map(value => <option key={value} value={value}>{targetNames[value]}</option>)}</select>
      </label>
      {target !== 'tutor' && <label className="flex flex-col gap-2 text-sm">{target === 'notes' ? '最多章节数' : target === 'quiz' ? '题目数' : '最多条目数'}
        <input className={`${control} w-28`} type="number" min={1} max={20} value={count} onChange={event => setCount(Number(event.target.value))}/>
      </label>}
      {target === 'notes' && <label className="flex flex-col gap-2 text-sm">详细程度
        <select className={control} value={mode} onChange={event => setMode(event.target.value as NoteMode)}>
          <option value="summary">简要总结</option><option value="standard">标准笔记</option><option value="comprehensive">详细笔记</option><option value="exam_focus">考试重点</option>
        </select>
      </label>}
    </fieldset>
    {pending && <div className="mt-3 text-sm text-amber-800">
      <p>待确认转换：{targetNames[pending.target]}。重试会继续原转换，避免重复生成。</p>
      <p className="mt-2">需要更换参数时，请先查看转换记录；新建转换会生成另一份结果。</p>
      <button type="button" className={`${control} mt-2 text-slate-800`} disabled={busy} onClick={() => { setPending(null); setError(''); try { sessionStorage.removeItem(scopeKey); } catch { /* The next submission uses a new request ID. */ } }}>改为新建转换</button>
    </div>}
    <button type="button" className="mt-4 min-h-11 rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600 disabled:opacity-50" disabled={disabled || busy || !target || !Number.isInteger(count) || count < 1 || count > 20} onClick={() => void submit()}>{busy ? '正在提交…' : pending ? '确认原转换请求' : '开始转换'}</button>
    {error && <p role="alert" className="mt-3 text-sm text-rose-800">{error}</p>}
    {notice && <p role="status" className="mt-3 text-sm text-emerald-800">{notice}</p>}
    <ConversionHistory key={reload} subjectId={subjectId} objectId={source.id}/>
  </section>;
}
