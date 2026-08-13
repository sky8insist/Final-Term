import { useEffect, useState } from 'react';
import { Network, RefreshCw } from 'lucide-react';
import { api } from '../../api/client';
import { useAppStore } from '../../stores/useAppStore';
import type { MindMapData } from '../../types';

export default function MindMap() {
  const subject = useAppStore((state) => state.currentSubject)!;
  const [data, setData] = useState<MindMapData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    setLoading(true);
    setError('');
    void api.mindMap(subject.id)
      .then(setData)
      .catch(() => setError('暂时无法读取思维导图，请稍后重试。'))
      .finally(() => setLoading(false));
  }, [subject.id]);

  const regenerate = async () => {
    setLoading(true);
    setError('');
    try {
      setData(await api.generateMindMap(subject.id));
    } catch {
      setError('生成失败，请确认已上传学习资料后重试。');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center justify-between border-b bg-white px-6 py-4">
        <div>
          <h1 className="text-xl font-bold">{subject.name} · 思维导图</h1>
          <p className="text-sm text-slate-500">用掌握度颜色识别重点与薄弱知识点</p>
        </div>
        <button
          type="button"
          onClick={() => void regenerate()}
          disabled={loading}
          className="flex items-center rounded-lg border px-3 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-60"
        >
          <RefreshCw size={16} className={`mr-2 ${loading ? 'animate-spin' : ''}`} />
          {loading ? '生成中' : '重新生成'}
        </button>
      </header>
      <div className="relative flex-1 overflow-auto bg-[radial-gradient(#cbd5e1_1px,transparent_1px)] [background-size:20px_20px] p-8">
        {error ? <div role="alert" className="mx-auto max-w-xl rounded-xl border border-rose-200 bg-rose-50 p-4 text-center text-sm text-rose-700">{error}</div> : null}
        {!error && !loading && !data?.nodes.length ? <div className="mx-auto max-w-xl rounded-xl border bg-white p-6 text-center text-sm text-slate-600">尚未生成导图，点击“重新生成”开始整理当前学科。</div> : null}
        {data?.nodes.length ? (
          <div className="mx-auto flex min-h-full max-w-5xl flex-col items-center justify-center">
            <div className="mb-16 rounded-2xl border-2 border-blue-400 bg-blue-600 px-8 py-5 text-xl font-bold text-white shadow-lg">
              <Network className="mr-2 inline" />{data.nodes[0].label}
            </div>
            <div className="grid w-full grid-cols-3 gap-6">
              {data.nodes.slice(1).map((node) => (
                <div key={node.id} className="relative rounded-2xl border bg-white p-6 text-center shadow-sm before:absolute before:-top-16 before:left-1/2 before:h-16 before:border-l before:border-slate-300">
                  <h3 className="font-bold">{node.label}</h3>
                  <div className="mt-4 h-2 rounded-full bg-slate-100"><div className={`h-full rounded-full ${node.mastery >= 80 ? 'bg-emerald-400' : node.mastery >= 50 ? 'bg-amber-400' : 'bg-rose-400'}`} style={{ width: `${node.mastery}%` }} /></div>
                  <p className="mt-2 text-sm text-slate-500">掌握度 {node.mastery}%</p>
                </div>
              ))}
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
