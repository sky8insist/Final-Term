import { FormEvent } from 'react';
import { Search, Sparkles } from 'lucide-react';
import type { MindMapMode } from '../../../types';

type Props = {
  mode: MindMapMode;
  query: string;
  loading: boolean;
  onModeChange: (mode: MindMapMode) => void;
  onQueryChange: (query: string) => void;
  onGenerate: () => void;
};

const modes: Array<{ value: MindMapMode; label: string }> = [
  { value: 'question', label: '根据问题' },
  { value: 'topic', label: '知识点' },
  { value: 'chapter', label: '整章知识地图' },
];

export function MindMapToolbar({ mode, query, loading, onModeChange, onQueryChange, onGenerate }: Props) {
  const placeholder = mode === 'question'
    ? '输入你想理解的问题，例如：战略和战术最核心的区别是什么？'
    : mode === 'topic'
      ? '输入知识点，例如：战略'
      : '输入章节名称；留空则整理当前课程';

  function submit(event: FormEvent) {
    event.preventDefault();
    onGenerate();
  }

  return (
    <form onSubmit={submit} className="border-b border-slate-200 bg-white px-5 py-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex rounded-xl bg-slate-100 p-1" aria-label="知识地图生成方式">
          {modes.map((item) => (
            <button
              key={item.value}
              type="button"
              aria-pressed={mode === item.value}
              onClick={() => onModeChange(item.value)}
              className={`rounded-lg px-3 py-2 text-sm font-medium transition ${mode === item.value ? 'bg-white text-blue-700 shadow-sm' : 'text-slate-600 hover:text-slate-900'}`}
            >
              {item.label}
            </button>
          ))}
        </div>
        <label className="relative min-w-[320px] flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={18} />
          <span className="sr-only">学习问题或知识点</span>
          <input
            value={query}
            onChange={(event) => onQueryChange(event.target.value)}
            placeholder={placeholder}
            maxLength={1000}
            disabled={loading}
            className="h-11 w-full rounded-xl border border-slate-200 bg-slate-50 pl-10 pr-4 text-sm outline-none transition focus:border-blue-400 focus:bg-white focus:ring-2 focus:ring-blue-100"
          />
        </label>
        <button
          type="submit"
          disabled={loading || (mode !== 'chapter' && !query.trim())}
          className="inline-flex h-11 items-center gap-2 rounded-xl bg-slate-900 px-5 text-sm font-semibold text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Sparkles size={17} />
          {loading ? '生成中' : '生成知识地图'}
        </button>
      </div>
    </form>
  );
}

