import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { api } from '../../api/client';
import { ConversionHistory, TurnInto } from '../../components/TurnInto';
import { useAppStore } from '../../stores/useAppStore';
import type { ConversionSource } from '../../types/conversion';

function Workspace({ subjectId }: { subjectId: string }) {
  const [params] = useSearchParams();
  const [kind, setKind] = useState<ConversionSource['kind']>(params.get('sourceKind') === 'wrong_answer' ? 'wrong_answer' : params.get('sourceKind') === 'notes' ? 'notes' : 'material');
  const [id, setId] = useState(params.get('sourceId') || '');
  const [sources, setSources] = useState<Record<string, Array<{ id: string; title: string; version?: number }>>>({});
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);
  useEffect(() => {
    let stopped = false;
    Promise.all([api.materials(subjectId), api.notes(subjectId), api.conversionWrongAnswers(subjectId)]).then(([materials, notes, wrong]) => {
      if (!stopped) { setSources({ material: materials.filter(row => row.status === 'indexed').map(row => ({ id: row.id, title: row.name })), notes, wrong_answer: wrong }); setError(''); }
    }).catch(reason => { if (!stopped) setError(reason instanceof Error ? reason.message : '无法读取学习来源。'); });
    return () => { stopped = true; };
  }, [subjectId, reload]);
  const selected = sources[kind]?.find(row => row.id === id);
  const source: ConversionSource | null = selected ? { kind, id: selected.id, ...(kind === 'notes' ? { version: selected.version } : {}) } : null;
  return <div className="h-full overflow-y-auto p-6 lg:p-8">
    <div className="mx-auto max-w-3xl">
      <h1 className="text-2xl font-bold text-slate-950">换一种方式学习</h1>
      <p className="mt-2 text-sm leading-6 text-slate-600">从课程资料、已保存笔记或错题继续学习。导图节点可在知识地图的详情中转换。</p>
      {error && <p role="alert" className="mt-4 text-rose-800">{error}</p>}
      <div className="mt-6 flex flex-wrap gap-4">
        <label className="flex flex-col gap-2 text-sm">来源类型
          <select className="min-h-11 rounded-lg border bg-white px-3 focus-visible:outline-blue-600" value={kind} onChange={event => { setKind(event.target.value as ConversionSource['kind']); setId(''); }}>
            <option value="material">课程资料</option><option value="notes">学习笔记</option><option value="wrong_answer">错题</option>
          </select>
        </label>
        <label className="flex min-w-60 flex-1 flex-col gap-2 text-sm">学习来源
          <select className="min-h-11 rounded-lg border bg-white px-3 focus-visible:outline-blue-600" value={selected ? id : ''} onChange={event => setId(event.target.value)}>
            <option value="">请选择来源</option>{sources[kind]?.map(row => <option key={row.id} value={row.id}>{row.title}</option>)}
          </select>
        </label>
        <button type="button" className="min-h-11 self-end rounded-lg border px-3 text-sm focus-visible:outline-blue-600" onClick={() => setReload(value => value + 1)}>刷新来源</button>
      </div>
      {sources[kind]?.length === 0 && <p className="mt-4 text-sm text-slate-600">暂无可选来源。资料需要处理完成，正式考试的错题需要整卷提交并完成评分。</p>}
      {source ? <TurnInto key={JSON.stringify(source)} subjectId={subjectId} source={source}/> : <ConversionHistory subjectId={subjectId}/>}
    </div>
  </div>;
}

export default function Conversions() {
  const subject = useAppStore(state => state.currentSubject)!;
  return <Workspace key={subject.id} subjectId={subject.id}/>;
}
