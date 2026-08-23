import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, BrainCircuit, CheckCircle2, LoaderCircle } from 'lucide-react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { ApiError, api } from '../../api/client';
import { useAppStore } from '../../stores/useAppStore';
import type { MindMapData, MindMapMode, MindMapNode } from '../../types';
import { MindMapCanvas } from './components/MindMapCanvas';
import { MindMapToolbar } from './components/MindMapToolbar';
import { NodeDetailDrawer } from './components/NodeDetailDrawer';

const loadingStages = ['正在理解你的学习目标…', '正在检索课程资料…', '正在整理核心概念…', '正在分析知识关系…', '正在生成知识地图…'];
type ViewMode = 'knowledge' | 'exam';

export default function MindMap() {
  const subject = useAppStore((state) => state.currentSubject)!;
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [data, setData] = useState<MindMapData | null>(null);
  const [mode, setMode] = useState<MindMapMode>('question');
  const [query, setQuery] = useState(searchParams.get('topic') ?? '');
  const [viewMode, setViewMode] = useState<ViewMode>('knowledge');
  const [selectedNode, setSelectedNode] = useState<MindMapNode | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingStage, setLoadingStage] = useState(0);
  const [error, setError] = useState('');
  const [creatingFlashcards, setCreatingFlashcards] = useState(false);
  const [flashcardMessage, setFlashcardMessage] = useState('');

  useEffect(() => {
    setLoading(true);
    setError('');
    api.mindMap(subject.id)
      .then(setData)
      .catch((reason) => setError(reason instanceof Error ? reason.message : '暂时无法读取知识地图。'))
      .finally(() => setLoading(false));
  }, [subject.id]);

  useEffect(() => {
    if (!loading) { setLoadingStage(0); return undefined; }
    const timer = window.setInterval(() => setLoadingStage((stage) => Math.min(stage + 1, loadingStages.length - 1)), 1800);
    return () => window.clearInterval(timer);
  }, [loading]);

  async function generate() {
    if (mode !== 'chapter' && !query.trim()) return;
    setLoading(true); setLoadingStage(0); setError(''); setSelectedNode(null);
    try {
      setData(await api.generateMindMap({ subjectId: subject.id, mode, query: query.trim() || undefined }));
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 422) setError(reason.message);
      else if (reason instanceof ApiError && reason.status === 408) setError('生成时间过长，已停止等待。请缩小问题或章节范围后重试。');
      else setError(reason instanceof Error ? reason.message : '知识地图生成失败，请稍后重试。');
    } finally { setLoading(false); }
  }

  const displayData = useMemo(() => {
    if (!data || viewMode === 'knowledge') return data;
    const keep = new Set(data.nodes.filter((node) => node.examImportance === 'high' || node.level === 0).map((node) => node.id));
    let changed = true;
    while (changed) {
      changed = false;
      data.nodes.forEach((node) => {
        if (keep.has(node.id) && node.parentId && !keep.has(node.parentId)) { keep.add(node.parentId); changed = true; }
      });
    }
    return { ...data, nodes: data.nodes.filter((node) => keep.has(node.id)), edges: data.edges.filter((edge) => keep.has(edge.source) && keep.has(edge.target)) };
  }, [data, viewMode]);

  async function createFlashcards(node: MindMapNode) {
    setCreatingFlashcards(true); setFlashcardMessage('');
    try { await api.generateFlashcards(subject.id, node.label); setFlashcardMessage('闪卡已生成并保存。'); }
    catch (reason) { setFlashcardMessage(reason instanceof Error ? reason.message : '闪卡生成失败。'); }
    finally { setCreatingFlashcards(false); }
  }

  return (
    <div className="flex h-full min-h-0 flex-col bg-slate-50">
      <header className="flex items-center justify-between border-b bg-white px-5 py-3">
        <div className="flex items-center gap-3"><div className="grid h-10 w-10 place-items-center rounded-xl bg-gradient-to-br from-blue-600 to-violet-600 text-white"><BrainCircuit size={21} /></div><div><h1 className="font-bold text-slate-900">AI 知识地图</h1><p className="text-xs text-slate-500">{subject.name} · 围绕学习问题建立知识结构</p></div></div>
        <div className="flex rounded-xl border bg-slate-50 p-1">
          <button type="button" onClick={() => setViewMode('knowledge')} className={`rounded-lg px-3 py-1.5 text-xs font-semibold ${viewMode === 'knowledge' ? 'bg-white text-blue-700 shadow-sm' : 'text-slate-500'}`}>知识地图</button>
          <button type="button" onClick={() => setViewMode('exam')} className={`rounded-lg px-3 py-1.5 text-xs font-semibold ${viewMode === 'exam' ? 'bg-white text-blue-700 shadow-sm' : 'text-slate-500'}`}>考试重点</button>
        </div>
      </header>
      <MindMapToolbar mode={mode} query={query} loading={loading} onModeChange={setMode} onQueryChange={setQuery} onGenerate={() => void generate()} />
      <main className="relative min-h-0 flex-1 overflow-hidden">
        {loading && <div className="absolute inset-0 z-30 grid place-items-center bg-white/90 backdrop-blur-sm" role="status"><div className="w-[360px] rounded-3xl border bg-white p-7 text-center shadow-xl"><LoaderCircle className="mx-auto animate-spin text-blue-600" size={34} /><h2 className="mt-4 font-semibold">{loadingStages[loadingStage]}</h2><div className="mt-5 flex justify-center gap-2">{loadingStages.map((_, index) => <span key={index} className={`h-1.5 w-10 rounded-full ${index <= loadingStage ? 'bg-blue-500' : 'bg-slate-200'}`} />)}</div><p className="mt-4 text-xs leading-5 text-slate-500">系统只检索与当前问题相关的课程证据，并进行结构与引用校验。</p></div></div>}
        {error && !loading && <div className="mx-auto mt-10 max-w-xl rounded-2xl border border-rose-200 bg-rose-50 p-5 text-center text-sm text-rose-700" role="alert"><AlertTriangle className="mx-auto mb-2" size={22} />{error}</div>}
        {!loading && !error && !data?.nodes.length && <div className="grid h-full place-items-center p-8"><div className="max-w-md text-center"><BrainCircuit className="mx-auto text-slate-300" size={48} /><h2 className="mt-4 text-lg font-bold">从一个学习问题开始</h2><p className="mt-2 text-sm leading-6 text-slate-500">输入问题、知识点或章节，AI 会基于课程资料建立概念层级和关系。</p></div></div>}
        {!loading && !error && displayData?.nodes.length ? <div className="h-full">
          <div className="pointer-events-none absolute left-5 top-5 z-10 max-w-lg rounded-2xl border border-white/80 bg-white/90 p-4 shadow-sm backdrop-blur"><div className="text-xs font-semibold uppercase tracking-wider text-blue-600">Focus Question</div><div className="mt-1 font-semibold">{data?.focusQuestion || data?.title}</div>{data?.summary && <p className="mt-2 text-xs leading-5 text-slate-500">{data.summary}</p>}{data?.evidenceInsufficient && <div className="mt-2 flex items-center gap-1 text-xs text-amber-700"><AlertTriangle size={13} />课程证据有限，地图仅保留有依据的内容</div>}{data?.evaluation && <div className="mt-2 flex items-center gap-1 text-xs text-emerald-700"><CheckCircle2 size={13} />引用完整度 {Math.round(data.evaluation.grounding * 100)}%</div>}</div>
          <MindMapCanvas key={`${data?.artifactId}-${viewMode}`} data={displayData} onSelect={setSelectedNode} />
        </div> : null}
        {selectedNode && data && <NodeDetailDrawer node={selectedNode} data={data} creatingFlashcards={creatingFlashcards} flashcardMessage={flashcardMessage} onClose={() => { setSelectedNode(null); setFlashcardMessage(''); }} onCreateFlashcards={(node) => void createFlashcards(node)} onCreateExam={(node) => navigate(`/exams?topic=${encodeURIComponent(node.label)}`)} />}
      </main>
    </div>
  );
}
