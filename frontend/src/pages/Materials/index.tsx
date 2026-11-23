import { ChangeEvent, useCallback, useEffect, useRef, useState } from 'react';
import { AlertCircle, CheckCircle2, FileText, Loader2, RotateCcw, UploadCloud } from 'lucide-react';
import { Link } from 'react-router-dom';
import { api } from '../../api/client';
import { useAppStore } from '../../stores/useAppStore';
import type { Material, MaterialProcessing, MaterialPurpose, UploadNotesMode } from '../../types';
import { Outline } from './Outline';

const purposes: Record<MaterialPurpose, string> = { learning: '课程资料', syllabus: '课程大纲', reference: '参考资料' };
const stages: Record<string, string> = { source: '读取原文件', queued: '任务投递', parsing: '解析', embedding: '向量化', indexing: '建立索引' };
const noteModes: Record<UploadNotesMode, string> = { summary: '摘要', standard: '标准', comprehensive: '详细', exam_focus: '考试重点' };
const noteStates: Record<string, string> = { waiting_material: '等待资料入库', pending: '准备笔记任务', queued: '等待生成笔记', running: '正在生成笔记', succeeded: '笔记已生成', failed: '笔记生成失败', cancelled: '笔记生成已取消', enqueue_failed: '笔记任务尚未创建', removed: '笔记结果或任务已删除' };
const control = 'min-h-11 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600 disabled:opacity-50';

function MaterialsWorkspace({ subjectId, subjectName }: { subjectId: string; subjectName: string }) {
  const [items, setItems] = useState<Material[]>([]);
  const [processing, setProcessing] = useState<Record<string, MaterialProcessing>>({});
  const [purpose, setPurpose] = useState<MaterialPurpose>('learning');
  const [notesMode, setNotesMode] = useState<UploadNotesMode | ''>('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [uploading, setUploading] = useState(false);
  const [retrying, setRetrying] = useState('');
  const [loading, setLoading] = useState(true);
  const [openOutline, setOpenOutline] = useState('');
  const sequence = useRef(0);
  const load = useCallback(async () => {
    const request = ++sequence.current;
    try {
      const [materials, summaries] = await Promise.all([api.materials(subjectId), api.materialProcessing(subjectId)]);
      if (request !== sequence.current) return;
      setItems(materials);
      setProcessing(Object.fromEntries(summaries.map((row) => [row.materialId, row])));
      setError('');
    } catch (cause) {
      if (request === sequence.current) setError(cause instanceof Error ? cause.message : '资料加载失败，请刷新重试。');
    } finally {
      if (request === sequence.current) setLoading(false);
    }
  }, [subjectId]);
  useEffect(() => { void load(); return () => { sequence.current++; }; }, [load]);
  const active = items.some((item) => {
    const task = processing[item.id]?.task;
    const ingestionActive = task ? ['queued', 'running'].includes(task.status) : ['queued', 'parsing', 'embedding', 'indexing'].includes(item.status);
    const notes = processing[item.id]?.notes;
    return ingestionActive || !!(notes && (['pending', 'queued', 'running'].includes(notes.status) || (notes.status === 'enqueue_failed' && notes.attempts < 3)));
  });
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => void load(), 3000);
    return () => window.clearInterval(timer);
  }, [active, load]);

  async function select(event: ChangeEvent<HTMLInputElement>) {
    const input = event.target;
    const file = input.files?.[0];
    if (!file) return;
    setUploading(true); setError(''); setNotice('');
    try {
      const result = await api.addMaterial(subjectId, file, purpose, notesMode || undefined);
      setNotice(result.deduplicated ? '该文件已存在，已保留原处理记录。' : result.task?.status === 'failed' ? '文件已保存，任务投递失败。可在下方重试处理。' : '文件已上传，正在等待处理。');
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '上传失败，请重试。');
    } finally {
      setUploading(false); input.value = '';
    }
  }
  async function retry(summary: MaterialProcessing) {
    if (!summary.task) return;
    setRetrying(summary.materialId); setError(''); setNotice('');
    try {
      const task = await api.retryMaterialTask(summary.task.id);
      setNotice(task.status === 'failed' ? '任务服务暂时不可用，文件已保留，请稍后重试。' : '已重新排队。处理将重新运行，并复用可用的音频分段缓存。');
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '重试失败，请刷新列表后再试。');
    } finally { setRetrying(''); }
  }
  async function retryNotes(materialId: string) {
    setRetrying(materialId); setError(''); setNotice('');
    try {
      await api.retryUploadNotes(subjectId, materialId);
      setNotice('已请求重试笔记任务，资料入库状态不受影响。');
      await load();
    } catch (cause) { setError(cause instanceof Error ? cause.message : '笔记重试失败，请刷新列表。'); }
    finally { setRetrying(''); }
  }
  return <div className="h-full overflow-y-auto p-5 md:p-8">
    <header className="mb-7 flex flex-wrap items-start justify-between gap-4">
      <div><h1 className="text-3xl font-bold">资料中心</h1><p className="mt-2 text-slate-600">管理 {subjectName} 的课程文件、用途与处理状态。</p></div>
      <button type="button" className={control} onClick={() => void load()}>刷新列表</button>
    </header>
    <section aria-label="上传资料" className="mb-7">
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <label htmlFor="material-purpose" className="text-sm font-medium">资料用途</label>
        <select id="material-purpose" className={control} value={purpose} disabled={uploading} onChange={(event) => setPurpose(event.target.value as MaterialPurpose)}>
          {Object.entries(purposes).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
        <p className="text-sm text-slate-600">大纲处理完成后，可前往<Link className="ml-1 text-blue-700 underline underline-offset-4" to="/calendar">日历提取考试候选</Link>。</p>
      </div>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <label htmlFor="upload-notes-mode" className="text-sm font-medium">上传后生成笔记</label>
        <select id="upload-notes-mode" className={control} value={notesMode} disabled={uploading} onChange={(event) => setNotesMode(event.target.value as UploadNotesMode | '')}>
          <option value="">不自动生成</option>{Object.entries(noteModes).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
        <p className="text-sm text-slate-600">入库后生成，最多使用前 30 个内容块；长资料可从转换入口选择范围。</p>
      </div>
      <label className={`relative flex min-h-44 flex-col items-center justify-center rounded-2xl border-2 border-dashed border-blue-200 bg-blue-50/40 p-7 text-center focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-blue-600 ${uploading ? 'cursor-wait' : 'cursor-pointer hover:bg-blue-50'}`}>
        <UploadCloud size={32} className="mb-3 text-blue-700" aria-hidden="true"/>
        <span className="font-semibold">{uploading ? '正在上传…' : '选择文件上传'}</span>
        <span className="mt-2 text-sm leading-6 text-blue-950/75">PDF、Word、PPT、Excel、文本、图片或音频</span>
        <input type="file" aria-label="选择资料文件" disabled={uploading} accept=".pdf,.doc,.docx,.ppt,.pptx,.xls,.xlsx,.txt,.png,.jpg,.jpeg,.jp2,.webp,.gif,.bmp,.mp3,.wav,.m4a,.webm" className="sr-only" onChange={(event) => void select(event)}/>
      </label>
    </section>
    {error && <p role="alert" className="mb-4 break-words text-rose-800">{error}</p>}
    {notice && <p role="status" className="mb-4 text-sm text-slate-700">{notice}</p>}
    <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white" aria-busy={loading}>
      <div className="hidden grid-cols-[minmax(0,1fr)_7rem_minmax(16rem,1fr)] gap-5 border-b border-slate-200 bg-slate-50 px-5 py-3 text-sm font-semibold text-slate-600 md:grid"><span>文件 / 用途</span><span>大小</span><span>处理状态</span></div>
      {items.map((item) => {
        const summary = processing[item.id];
        const task = summary?.task;
        const failed = task?.status === 'failed' || item.status === 'failed';
        const cancelled = task?.status === 'cancelled';
        const failedStage = typeof task?.metadata?.failedStage === 'string' ? task.metadata.failedStage : '';
        const busy = retrying === item.id;
        return <article key={item.id} aria-label={item.name} className="grid gap-3 border-b border-slate-100 px-5 py-5 last:border-0 md:grid-cols-[minmax(0,1fr)_7rem_minmax(16rem,1fr)] md:gap-5">
          <div className="flex min-w-0 items-start gap-3"><FileText size={20} className="mt-1 shrink-0 text-blue-700" aria-hidden="true"/><div className="min-w-0">
            {item.status === 'indexed' ? <Link to={`/convert?sourceKind=material&sourceId=${encodeURIComponent(item.id)}`} className="break-words font-medium text-blue-800 underline underline-offset-4 focus-visible:outline-2 focus-visible:outline-blue-600">{item.name}</Link> : <p className="break-words font-medium">{item.name}</p>}
            <p className="mt-1 text-sm text-slate-600">{purposes[item.materialPurpose ?? 'learning']}</p>
            {item.status === 'indexed' && <button type="button" aria-expanded={openOutline === item.id} className={`${control} mt-3`} onClick={() => setOpenOutline((current) => current === item.id ? '' : item.id)}>{openOutline === item.id ? '收起章节提案' : '查看章节提案'}</button>}
          </div></div>
          <p className="text-sm tabular-nums text-slate-600">{Math.ceil(item.size / 1024)} KB</p>
          <div className="min-w-0 text-sm">
            {cancelled ? <p className="text-slate-700">已取消处理。</p> : failed ? <>
              <p className="flex items-center gap-2 font-medium text-rose-800"><AlertCircle size={16} className="shrink-0" aria-hidden="true"/>{stages[failedStage] ? `${stages[failedStage]}失败` : '处理失败'}</p>
              <p className="mt-2 break-words text-slate-700">{task?.errorMessage || item.errorMessage || '请重试处理。'}</p>
              {task?.status === 'failed' && summary?.sourceAvailable ? <button type="button" disabled={!!retrying} aria-label={`重试处理 ${item.name}`} className={`${control} mt-3 inline-flex items-center gap-2`} onClick={() => void retry(summary)}><RotateCcw size={15} className={busy ? 'animate-spin motion-reduce:animate-none' : ''} aria-hidden="true"/>{busy ? '正在重试…' : '重试处理'}</button> : <p className="mt-2 text-slate-600">原文件已过期、不可用或无处理记录，请重新上传。</p>}
            </> : item.status === 'indexed' ? <p className="flex items-center gap-2 text-emerald-800"><CheckCircle2 size={16} aria-hidden="true"/>已入库</p> : <>
              <p className="flex items-center gap-2 text-slate-700"><Loader2 size={16} className="animate-spin motion-reduce:animate-none" aria-hidden="true"/>{task?.status === 'queued' ? '等待处理' : stages[task?.stage ?? item.status] ?? '正在处理'}{task ? ` · ${task.progress}%` : ''}</p>
              {task?.errorCode === 'retry_scheduled' && <p className="mt-2 text-slate-600">{stages[failedStage] ?? '上次处理'}失败，正在自动重试（{task.attempts}/{task.maxAttempts}）。</p>}
            </>}
            {summary?.notes && <div className="mt-4 border-t border-slate-200 pt-3">
              <p className="font-medium text-slate-800">{noteModes[summary.notes.mode]}笔记 · {noteStates[summary.notes.status] ?? '正在准备'}</p>
              <p className="mt-1 text-slate-600">{summary.notes.warnings.includes('material_first_30_blocks') ? '本次只使用了前 30 个内容块。' : '生成范围最多为前 30 个内容块。'}</p>
              {summary.notes.error && <p className="mt-2 break-words text-rose-800">{summary.notes.error}</p>}
              <div className="mt-2 flex flex-wrap gap-3">
                {summary.notes.href && summary.notes.status === 'succeeded' && <Link className="inline-flex min-h-11 items-center text-blue-800 underline underline-offset-4" to={summary.notes.href}>打开笔记</Link>}
                {summary.notes.conversionId && <Link className="inline-flex min-h-11 items-center text-blue-800 underline underline-offset-4" to="/conversions">查看转换任务</Link>}
                {summary.notes.canRetry && <button type="button" className={control} disabled={!!retrying} onClick={() => void retryNotes(item.id)}>{busy ? '正在重试…' : '重试生成笔记'}</button>}
              </div>
            </div>}
          </div>
          {openOutline === item.id && item.status === 'indexed' && <Outline key={item.id} subjectId={subjectId} materialId={item.id}/>}
        </article>;
      })}
      {!items.length && <p className="p-10 text-center text-slate-600">{loading ? '正在加载资料…' : error ? '资料尚未加载成功，请刷新列表。' : '还没有资料，选择文件开始上传。'}</p>}
    </div>
  </div>;
}

export default function Materials() {
  const subject = useAppStore((state) => state.currentSubject);
  return subject ? <MaterialsWorkspace key={subject.id} subjectId={subject.id} subjectName={subject.name}/> : <p className="p-8 text-slate-600">请先选择科目。</p>;
}
