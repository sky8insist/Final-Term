import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, BrainCircuit, CheckCircle2, LoaderCircle } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';
import { ApiError, api } from '../../api/client';
import { useAppStore } from '../../stores/useAppStore';
import type { MindMapData, MindMapMode } from '../../types';
import { MindMapCanvas } from './components/MindMapCanvas';
import { MindMapToolbar } from './components/MindMapToolbar';
import { NodeDetailDrawer } from './components/NodeDetailDrawer';

const loadingStages = ['正在理解你的学习目标…', '正在检索课程资料…', '正在整理核心概念…', '正在分析知识关系…', '正在生成知识地图…'];
type ViewMode = 'knowledge' | 'exam';

export default function MindMap() {
  const subject = useAppStore((state) => state.currentSubject)!;
  return <MindMapWorkspace key={subject.id} />;
}

function MindMapWorkspace() {
  const subject = useAppStore((state) => state.currentSubject)!;
  const [searchParams] = useSearchParams();
  const [data, setData] = useState<MindMapData | null>(null);
  const [mode, setMode] = useState<MindMapMode>('question');
  const [query, setQuery] = useState(searchParams.get('topic') ?? '');
  const [viewMode, setViewMode] = useState<ViewMode>('knowledge');
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const selectedNode = data?.nodes.find(node => node.id === selectedNodeId);
  const request = useRef(0);
  const [refreshing, setRefreshing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadingStage, setLoadingStage] = useState(0);
  const [error, setError] = useState('');

  useEffect(() => {
    const sequence = ++request.current;
    setLoading(true);
    setRefreshing(false);
    setSelectedNodeId(null);
    setError('');
    api.mindMap(subject.id, searchParams.get('artifactId') || undefined)
      .then(value => {
        if (sequence !== request.current) return;
        setData(value);
        setSelectedNodeId(searchParams.get('nodeId'));
      })
      .catch((reason) => { if (sequence === request.current) setError(reason instanceof Error ? reason.message : '暂时无法读取知识地图。'); })
      .finally(() => { if (sequence === request.current) setLoading(false); });
    return () => { request.current++; };
  }, [subject.id, searchParams]);

  const refresh = useCallback(async () => {
    if (!data?.artifactId) return;
    const sequence = ++request.current;
    setRefreshing(true); setError('');
    try {
      const value = await api.mindMap(subject.id, data.artifactId);
      if (sequence === request.current) setData(value);
    } catch (reason) {
      if (sequence === request.current) { setSelectedNodeId(null); setError(reason instanceof Error ? reason.message : '刷新失败，请重试。'); }
    } finally { if (sequence === request.current) setRefreshing(false); }
  }, [subject.id, data?.artifactId]);

  useEffect(() => {
    const onFocus = () => { if (!loading && !refreshing) void refresh(); };
    window.addEventListener('focus', onFocus);
    return () => window.removeEventListener('focus', onFocus);
  }, [refresh, loading, refreshing]);

  useEffect(() => {
    if (!loading) { setLoadingStage(0); return undefined; }
    const timer = window.setInterval(() => setLoadingStage((stage) => Math.min(stage + 1, loadingStages.length - 1)), 1800);
    return () => window.clearInterval(timer);
  }, [loading]);

  async function generate() {
    if (mode !== 'chapter' && !query.trim()) return;
    const sequence = ++request.current;
    setLoading(true); setRefreshing(false); setLoadingStage(0); setError(''); setSelectedNodeId(null);
    try {
      const value = await api.generateMindMap({ subjectId: subject.id, mode, query: query.trim() || undefined });
      if (sequence === request.current) setData(value);
    } catch (reason) {
      if (sequence !== request.current) return;
      if (reason instanceof ApiError && reason.status === 422) setError(reason.message);
      else if (reason instanceof ApiError && reason.status === 408) setError('生成时间过长，已停止等待。请缩小问题或章节范围后重试。');
      else setError(reason instanceof Error ? reason.message : '知识地图生成失败，请稍后重试。');
    } finally { if (sequence === request.current) setLoading(false); }
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


  return (
    <div className="flex h-full min-h-0 flex-col bg-slate-50">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b bg-white px-5 py-3">
        <div className="flex items-center gap-3"><div className="grid h-10 w-10 place-items-center rounded-xl bg-gradient-to-br from-blue-600 to-violet-600 text-white"><BrainCircuit size={21} /></div><div><h1 className="font-bold text-slate-900">AI 知识地图</h1><p className="text-xs text-slate-500">{subject.name} · 围绕学习问题建立知识结构</p></div></div>
        <div className="flex rounded-xl border bg-slate-50 p-1">
          <button type="button" disabled={loading || refreshing || !data?.artifactId} onClick={() => void refresh()} className="min-h-11 rounded-lg px-3 text-xs font-semibold text-blue-700 disabled:opacity-50">{refreshing ? '正在刷新…' : '刷新学习状态'}</button>
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
          <MindMapCanvas key={`${data?.artifactId}-${viewMode}`} data={displayData} onSelect={node => setSelectedNodeId(node.id)} />
        </div> : null}
        {selectedNode && data && <NodeDetailDrawer key={`${data.artifactId}:${selectedNode.id}:${selectedNode.learning?.bindingVersion}`} node={selectedNode} data={data} onSaved={refresh} onClose={() => setSelectedNodeId(null)} />}
      </main>
    </div>
  );
}
