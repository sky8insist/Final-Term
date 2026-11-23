import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { TurnInto } from '../../components/TurnInto';
import { api } from '../../api/client';
import { useAuth } from '../../auth/AuthProvider';
import { useAppStore } from '../../stores/useAppStore';
import type { CourseTopic, Material, NoteArtifact, NoteMode, NoteRewrite, NoteSection, NoteVersion } from '../../types';

const control = 'min-h-11 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600 disabled:bg-slate-100';
const button = 'min-h-11 rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600 disabled:cursor-not-allowed disabled:opacity-50';
const primary = 'min-h-11 rounded-lg bg-blue-600 px-5 py-2 text-sm font-semibold text-white hover:bg-blue-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600 disabled:cursor-not-allowed disabled:opacity-50';
const modes: Record<NoteMode, string> = { summary: '简要总结', standard: '标准笔记', comprehensive: '详细笔记', exam_focus: '考试重点' };
type Draft = { version: number; title: string; content: NoteArtifact['content'] };
const message = (error: unknown) => error instanceof Error ? error.message : '操作未完成，请重试。';

function readDraft(key: string): Draft | null {
  try {
    const value = JSON.parse(sessionStorage.getItem(key) || 'null') as Draft | null;
    return value && typeof value.title === 'string' && Array.isArray(value.content?.sections)
      && value.content.sections.every(section => typeof section.body === 'string' && typeof section.title === 'string' && Array.isArray(section.citationIds)) ? value : null;
  } catch { return null; }
}

function NoteEditor({ note, draftKey, onSaved, onDirty, onBusy }: { note: NoteArtifact; draftKey: string; onSaved: (note: NoteArtifact) => void; onDirty: (dirty: boolean) => void; onBusy: (busy: boolean) => void }) {
  const [stored] = useState(() => readDraft(draftKey));
  const [title, setTitle] = useState(stored?.version === note.version ? stored.title : note.title);
  const [content, setContent] = useState(stored?.version === note.version ? stored.content : note.content);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [draftError, setDraftError] = useState('');
  const [history, setHistory] = useState<Array<Pick<NoteVersion, 'version' | 'created_at'>> | null>(null);
  const [historical, setHistorical] = useState<NoteVersion | null>(null);
  const [selection, setSelection] = useState<Omit<NoteRewrite, 'replacement' | 'citationIds'> | null>(null);
  const [instruction, setInstruction] = useState('用更容易理解的语言改写，保留原意');
  const [preview, setPreview] = useState<NoteRewrite | null>(null);
  const dirty = title !== note.title || JSON.stringify(content) !== JSON.stringify(note.content);
  const staleDraft = stored && stored.version !== note.version ? stored : null;

  useEffect(() => { onDirty(dirty); return () => onDirty(false); }, [dirty, onDirty]);
  useEffect(() => { onBusy(Boolean(busy)); return () => onBusy(false); }, [busy, onBusy]);
  useEffect(() => {
    if (dirty) {
      try { sessionStorage.setItem(draftKey, JSON.stringify({ version: note.version, title, content })); }
      catch { setDraftError('浏览器无法保留草稿，请及时保存笔记。'); }
    }
    const warn = (event: BeforeUnloadEvent) => { if (dirty) { event.preventDefault(); event.returnValue = ''; } };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty, draftKey, note.version, title, content]);

  function changeSection(id: string, patch: Partial<NoteSection>) {
    setContent(current => ({ sections: current.sections.map(section => section.id === id ? { ...section, ...patch } : section) }));
    setSelection(null); setPreview(null);
  }

  async function run(kind: string, action: () => Promise<void>) {
    setBusy(kind); setError(''); setNotice('');
    try { await action(); } catch (reason) { setError(message(reason)); } finally { setBusy(''); }
  }

  function saved(value: NoteArtifact) {
    try { sessionStorage.removeItem(draftKey); } catch { /* Saving in the DB still succeeded. */ }
    onSaved(value);
  }

  function applyPreview() {
    if (!preview || preview.version !== note.version) return;
    const section = content.sections.find(row => row.id === preview.sectionId);
    if (!section) return;
    const chars = Array.from(section.body);
    if (chars.slice(preview.selectionStart, preview.selectionEnd).join('') !== preview.selectedText) {
      setError('选中文本已改变，请重新生成改写预览。'); return;
    }
    const body = chars.slice(0, preview.selectionStart).join('') + preview.replacement + chars.slice(preview.selectionEnd).join('');
    if (body.length > 20000) { setError('改写后正文过长，请缩短改写内容后重试。'); return; }
    changeSection(section.id, { body,
      citationIds: [...new Set([...section.citationIds, ...preview.citationIds])] });
    setNotice('改写已放入草稿；保存后才会写入笔记。');
  }

  return <article className="min-w-0 flex-1 bg-white p-5 lg:p-8" aria-label="笔记编辑器">
    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 pb-5">
      <p className="text-sm text-slate-600">{modes[note.generation_params.mode]} · 版本 {note.version} · {note.is_user_edited ? '已人工编辑' : 'AI 生成'} · {dirty ? '有未保存修改' : '已保存'}</p>
      <div className="flex flex-wrap gap-2">
<button className={button} disabled={Boolean(busy)} onClick={() => void run('history', async () => setHistory(await api.noteVersions(note.id)))}>版本历史</button>
<button className={button} disabled={Boolean(busy) || dirty} onClick={() => void run('export', async () => api.exportNote(note.id))}>导出 Markdown</button>
<button className={primary} disabled={Boolean(busy) || !dirty || !title.trim()} onClick={() => void run('save', async () => saved(await api.updateNote(note.id, { version: note.version, title, content })))}>保存笔记</button>
</div>
    </div>
    {busy && <p role="status" className="mt-4 text-sm text-blue-800">{busy === 'save' ? '正在保存笔记…' : '正在处理，请稍候…'}</p>}
    {error && <p role="alert" className="mt-4 bg-rose-50 p-4 text-sm leading-6 text-rose-900">{error} 草稿仍保留在本页。版本冲突时，请复制草稿后重新读取笔记。</p>}
    {notice && <p role="status" className="mt-4 text-sm text-emerald-800">{notice}</p>}
    {draftError && <p role="alert" className="mt-4 text-sm text-rose-800">{draftError}</p>}
    {error && <button className={`${button} mt-3`} disabled={Boolean(busy)} onClick={() => void run('reload', async () => onSaved(await api.note(note.id)))}>读取最新版本，保留浏览器草稿</button>}
    {staleDraft && <details className="mt-5 bg-amber-50 p-4 text-amber-950">
<summary className="min-h-11 cursor-pointer py-2 font-semibold">有版本 {staleDraft.version} 的旧草稿，展开后可复制并合并</summary>
<pre className="max-h-64 overflow-auto whitespace-pre-wrap text-sm">{staleDraft.title}{'\n\n'}{staleDraft.content.sections.map(section => `${section.title}\n${section.body}`).join('\n\n')}</pre>
</details>}
    <fieldset disabled={Boolean(busy)} className="mt-6 space-y-8">
      <legend className="sr-only">编辑标题、章节和来源</legend>
      <label className="block text-sm font-semibold">笔记标题<input className={`${control} mt-2 w-full text-xl font-semibold`} value={title} maxLength={300} onChange={event => { setTitle(event.target.value); setSelection(null); setPreview(null); }}/>
</label>
      {content.sections.map((section, index) => <section key={section.id} className="border-t border-slate-200 pt-6">
        <div className="flex items-end gap-3">
<label className="min-w-0 flex-1 text-sm font-semibold">章节标题<input className={`${control} mt-2 w-full`} value={section.title} maxLength={300} onChange={event => changeSection(section.id, { title: event.target.value })}/>
</label>
<button type="button" className={button} disabled={content.sections.length <= 1} aria-label={`移除章节：${section.title}`} onClick={() => { setContent({ sections: content.sections.filter(row => row.id !== section.id) }); setSelection(null); setPreview(null); }}>移除</button>
</div>
        <label className="mt-4 block text-sm font-semibold">正文<textarea className={`${control} mt-2 w-full resize-y text-base leading-7`} rows={Math.min(16, Math.max(6, section.body.split('\n').length + 2))} maxLength={20000} value={section.body} onChange={event => changeSection(section.id, { body: event.target.value })} onSelect={event => {
          const input = event.currentTarget;
          if (dirty || input.selectionStart === input.selectionEnd) return;
          setSelection({ version: note.version, sectionId: section.id, selectionStart: Array.from(input.value.slice(0, input.selectionStart)).length,
            selectionEnd: Array.from(input.value.slice(0, input.selectionEnd)).length, selectedText: input.value.slice(input.selectionStart, input.selectionEnd) }); setPreview(null);
        }}/>
</label>
        <details className="mt-3 text-sm">
<summary className="min-h-11 cursor-pointer py-3 font-semibold text-blue-800 focus-visible:outline-2 focus-visible:outline-blue-600">来源与页码（{section.citationIds.length} 条）</summary>
<p className="mb-3 leading-6 text-slate-600">来源为生成时保存的快照。修改观点后，请核对并保留支持该观点的来源。</p>
<div className="space-y-4">{note.citations.map(citation => <div key={citation.id}>
<label className="flex min-h-11 items-start gap-2">
<input type="checkbox" className="mt-1 accent-blue-600" checked={section.citationIds.includes(citation.id)} onChange={event => changeSection(section.id, { citationIds: event.target.checked ? [...section.citationIds, citation.id] : section.citationIds.filter(id => id !== citation.id) })}/>
<span>{citation.filename} · {citation.pageNumber ? `第 ${citation.pageNumber} 页` : '无页码'}{citation.startTime != null ? ` · ${citation.startTime}–${citation.endTime ?? '?'} 秒` : ''}</span>
</label>
<blockquote className="max-h-48 overflow-y-auto whitespace-pre-wrap bg-slate-50 p-3 leading-6 text-slate-700">{citation.chunkText}</blockquote>
</div>)}</div>
</details>
        <p className="sr-only">第 {index + 1} 节</p>
      </section>)}
      <button className={button} disabled={content.sections.length >= 100} onClick={() => { setContent({ sections: [...content.sections, { id: crypto.randomUUID(), title: '新章节', body: '', citationIds: note.citations[0] ? [note.citations[0].id] : [] }] }); setSelection(null); setPreview(null); }}>添加章节</button>
    </fieldset>
    <section className="mt-8 border-t border-slate-200 pt-6" aria-labelledby="rewrite-heading">
<h2 id="rewrite-heading" className="text-lg font-semibold">局部 AI 改写</h2>
<p className="mt-2 text-sm leading-6 text-slate-600">先保存笔记，再在正文中选中文字。改写会先显示预览，应用后仍需保存。</p>{selection && <p className="mt-3 whitespace-pre-wrap bg-slate-50 p-3 text-sm">已选择：{selection.selectedText}</p>}<label className="mt-3 block text-sm font-semibold">改写要求<input className={`${control} mt-2 w-full`} value={instruction} maxLength={1000} disabled={Boolean(busy)} onChange={event => setInstruction(event.target.value)}/>
</label>
<button className={`${button} mt-3`} disabled={Boolean(busy) || dirty || !selection || selection.selectedText.length > 5000 || !instruction.trim()} onClick={() => void run('rewrite', async () => { if (selection) setPreview(await api.rewriteNote(note.id, { ...selection, instruction })); })}>生成改写预览</button>{preview && <div className="mt-4 bg-blue-50 p-4 text-blue-950">
<h3 className="font-semibold">改写预览</h3>
<p className="mt-3 whitespace-pre-wrap leading-7">{preview.replacement}</p>
<div className="mt-4 flex gap-3">
<button className={primary} disabled={Boolean(busy)} onClick={applyPreview}>应用到草稿</button>
<button className={button} onClick={() => setPreview(null)}>放弃预览</button>
</div>
</div>}</section>
    <TurnInto key={`${note.id}:${note.version}`} subjectId={note.subject_id} source={{ kind: 'notes', id: note.id, version: note.version }} disabled={dirty || Boolean(busy)}/>
    {history && <section className="mt-8 border-t border-slate-200 pt-6">
<h2 className="text-lg font-semibold">版本历史（最近 100 个）</h2>
<div className="mt-4 flex flex-wrap gap-2">{history.map(row => <button key={row.version} className={button} aria-pressed={historical?.version === row.version} disabled={Boolean(busy)} onClick={() => void run('history', async () => setHistorical(await api.noteVersion(note.id, row.version)))}>版本 {row.version} · {new Date(row.created_at).toLocaleString('zh-CN')}</button>)}</div>{historical && <div className="mt-5">
<h3 className="font-semibold">{historical.snapshot.title}</h3>{historical.snapshot.content.sections.map(section => <div key={section.id} className="mt-4">
<h4 className="font-semibold">{section.title}</h4>
<p className="mt-2 whitespace-pre-wrap leading-7 text-slate-700">{section.body}</p>
</div>)}<button className={`${button} mt-5`} disabled={Boolean(busy) || dirty || historical.version === note.version} onClick={() => void run('restore', async () => saved(await api.restoreNote(note.id, note.version, historical.version)))}>以此版本恢复为新版本</button>
<p className="mt-2 text-sm text-slate-600">历史不会被覆盖。来源已删除或知识点已归档时，恢复会被阻止。</p>
</div>}</section>}
    {dirty && <button className={`${button} mt-8`} disabled={Boolean(busy)} onClick={() => { setTitle(note.title); setContent(note.content); setSelection(null); setPreview(null); try { sessionStorage.removeItem(draftKey); } catch { /* Optional draft storage. */ } }}>放弃本次修改</button>}
  </article>;
}

function NotesWorkspace({ subjectId, userId }: { subjectId: string; userId: string }) {
  const [params] = useSearchParams();
  const [notes, setNotes] = useState<NoteArtifact[]>([]);
  const [topics, setTopics] = useState<CourseTopic[]>([]);
  const [materials, setMaterials] = useState<Material[]>([]);
  const [materialIds, setMaterialIds] = useState<string[]>([]);
  const [topicId, setTopicId] = useState('');
  const [scope, setScope] = useState('');
  const [mode, setMode] = useState<NoteMode>('standard');
  const [selectedId, setSelectedId] = useState(params.get('noteId') || '');
  const [pendingId, setPendingId] = useState('');
  const [dirty, setDirty] = useState(false);
  const [editorBusy, setEditorBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [reload, setReload] = useState(0);
  const selected = notes.find(note => note.id === selectedId);
  useEffect(() => {
    const targetId = params.get('noteId');
    if (targetId && notes.some(row => row.id === targetId) && targetId !== selectedId) {
      if (dirty || editorBusy) setPendingId(targetId);
      else setSelectedId(targetId);
    }
  }, [params]);
  const draftKey = (id: string) => `examai-note-draft:${userId}:${id}`;
  useEffect(() => {
    let stopped = false;
    Promise.all([api.notes(subjectId), api.materials(subjectId), api.courseStructure(subjectId)]).then(([rows, sources, structure]) => {
      if (stopped) return;
      setNotes(rows); setMaterials(sources.filter(row => row.status === 'indexed')); setTopics(structure.topics.filter(row => !row.archived));
      setSelectedId(current => rows.some(row => row.id === current) ? current : rows[0]?.id || ''); setError('');
    }).catch(reason => { if (!stopped) setError(message(reason)); }).finally(() => { if (!stopped) setLoading(false); });
    return () => { stopped = true; };
  }, [subjectId, reload]);

  function saved(note: NoteArtifact) {
    setNotes(current => [note, ...current.filter(row => row.id !== note.id)]); setSelectedId(note.id); setPendingId(''); setNotice(`当前笔记版本 ${note.version}。`);
  }

  async function generate() {
    setGenerating(true); setError(''); setNotice('');
    try { saved(await api.generateNote({ subjectId, mode, scope: scope.trim() || undefined, materialIds: materialIds.length ? materialIds : undefined, knowledgePointId: topicId || undefined })); }
    catch (reason) { setError(message(reason)); } finally { setGenerating(false); }
  }

  return <div className="h-full overflow-y-auto bg-slate-50 p-6 lg:p-8">
<div className="mx-auto max-w-7xl">
    <h1 className="text-2xl font-bold text-slate-950">学习笔记</h1>
<p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">把课程资料整理成可编辑的笔记。每个章节保留来源与页码，保存修改时创建新版本。</p>
    {error && <p role="alert" className="mt-5 bg-rose-50 p-4 text-sm text-rose-900">{error}<button className={`${button} ml-3`} disabled={dirty || editorBusy || generating} onClick={() => { setLoading(true); setReload(value => value + 1); }}>重新读取</button>
</p>}
    {notice && <p role="status" className="mt-4 text-sm text-emerald-800">{notice}</p>}
    <details className="my-6 border-y border-slate-200 py-3" open={!notes.length}>
<summary className="min-h-11 cursor-pointer py-3 font-semibold focus-visible:outline-2 focus-visible:outline-blue-600">生成新笔记</summary>
<form onSubmit={event => { event.preventDefault(); void generate(); }} className="mt-4 space-y-5">
<fieldset disabled={generating || loading || dirty || editorBusy}>
<legend className="sr-only">笔记生成范围</legend>
<div className="flex flex-wrap gap-5">
<label className="flex min-w-48 flex-1 flex-col gap-2 text-sm font-semibold">详细程度<select className={control} value={mode} onChange={event => setMode(event.target.value as NoteMode)}>{Object.entries(modes).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>
</label>
<label className="flex min-w-48 flex-1 flex-col gap-2 text-sm font-semibold">绑定知识点<select className={control} value={topicId} onChange={event => setTopicId(event.target.value)}>
<option value="">不绑定单个知识点</option>{topics.map(topic => <option key={topic.id} value={topic.id}>{topic.title}</option>)}</select>
</label>
<label className="flex min-w-64 flex-[2] flex-col gap-2 text-sm font-semibold">整理范围（可选）<input className={control} maxLength={1000} placeholder="例如：矩阵特征值的定义与计算条件" value={scope} onChange={event => setScope(event.target.value)}/>
</label>
</div>
<fieldset className="mt-4">
<legend className="text-sm font-semibold">课程资料（不勾选表示不限制资料）</legend>
<div className="mt-2 flex flex-wrap gap-x-6 gap-y-2">{materials.map(material => <label key={material.id} className="flex min-h-11 max-w-full items-center gap-2 text-sm">
<input type="checkbox" className="accent-blue-600" checked={materialIds.includes(material.id)} onChange={event => setMaterialIds(current => event.target.checked ? [...current, material.id] : current.filter(id => id !== material.id))}/>
<span className="break-all">{material.name}</span>
</label>)}</div>
</fieldset>
</fieldset>
<button className={primary} disabled={generating || loading || dirty || editorBusy || !materials.length}>{generating ? '正在生成笔记…' : '生成笔记'}</button>{dirty && <p className="text-sm text-slate-600">请先保存或放弃当前草稿，再生成新笔记。</p>}{!loading && !materials.length && <p className="text-sm text-slate-600">需要先上传并处理课程资料。<Link to="/materials" className="ml-2 font-semibold text-blue-700 underline">前往资料中心</Link>
</p>}</form>
</details>
    {pendingId && <div role="alert" className="mb-5 bg-amber-50 p-4 text-amber-950">
<p>当前笔记有未保存修改。保存后可切换，也可以放弃草稿。</p>
<div className="mt-3 flex gap-3">
<button className={button} onClick={() => setPendingId('')}>继续编辑</button>
<button className={button} onClick={() => { try { sessionStorage.removeItem(draftKey(selectedId)); } catch { /* Optional draft storage. */ } setSelectedId(pendingId); setPendingId(''); setDirty(false); }}>放弃草稿并切换</button>
</div>
</div>}
    {loading ? <p role="status" className="py-8 text-slate-600">正在读取课程笔记…</p> : <div className="flex flex-col gap-6 xl:flex-row">
<nav className="shrink-0 xl:w-64" aria-label="当前课程的笔记">
<h2 className="mb-3 text-sm font-semibold text-slate-700">笔记列表（最近 100 份）</h2>{notes.length ? <ul className="divide-y divide-slate-200">{notes.map(note => <li key={note.id}>
<button className={`min-h-11 w-full py-4 text-left focus-visible:outline-2 focus-visible:outline-blue-600 ${selectedId === note.id ? 'font-semibold text-blue-800' : 'text-slate-700 hover:text-blue-800'}`} aria-current={selectedId === note.id ? 'true' : undefined} disabled={generating || editorBusy} onClick={() => { if (note.id === selectedId) return; if (dirty) setPendingId(note.id); else { setSelectedId(note.id); setPendingId(''); } }}>
<span className="block break-words">{note.title}</span>
<span className="mt-1 block text-xs font-normal text-slate-600">{modes[note.generation_params.mode]} · 版本 {note.version}</span>
</button>
</li>)}</ul> : <p className="text-sm leading-6 text-slate-600">还没有笔记。选择上方的详细程度和课程资料开始整理。</p>}</nav>{selected && <fieldset disabled={generating} className="min-w-0 flex-1">
<NoteEditor key={`${selected.id}:${selected.version}`} note={selected} draftKey={draftKey(selected.id)} onSaved={saved} onDirty={setDirty} onBusy={setEditorBusy}/>
</fieldset>}</div>}
  </div>
</div>;
}

export default function Notes() {
  const { currentSubject } = useAppStore();
  const { user } = useAuth();
  return currentSubject && user ? <NotesWorkspace key={currentSubject.id} subjectId={currentSubject.id} userId={user.id}/> : null;
}
