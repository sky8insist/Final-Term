import { ChevronDown, ChevronRight, FileText, Star } from 'lucide-react';
import { Handle, Position, type NodeProps } from '@xyflow/react';
import type { MindMapNode } from '../../../types';

export type KnowledgeNodeData = Record<string, unknown> & {
  item: MindMapNode;
  collapsed: boolean;
  hasChildren: boolean;
  onToggle: (id: string) => void;
};

const typeLabel: Partial<Record<MindMapNode['type'], string>> = {
  definition: '定义', comparison: '对比', process: '过程', example: '示例',
  exam_point: '考点', warning: '易错', concept: '概念',
};

export function KnowledgeNode({ data, selected }: NodeProps) {
  const { item, collapsed, hasChildren, onToggle } = data as KnowledgeNodeData;
  const mastery = item.mastery == null ? null : Math.round(item.mastery * 100);
  const root = item.type === 'root' || item.level === 0;
  const learning = item.learning;
  const states = { unbound: '尚未关联', not_started: '尚未开始', covered: '已覆盖', practicing: '练习中', mastered: '已掌握', at_risk: '需巩固' };
  return (
    <div className={`min-w-[190px] max-w-[240px] rounded-2xl border px-4 py-3 shadow-lg transition ${
      root
        ? 'border-indigo-400 bg-gradient-to-br from-blue-600 to-violet-600 text-white shadow-blue-200'
        : selected
          ? 'border-blue-400 bg-white ring-4 ring-blue-100'
          : learning?.state === 'mastered' ? 'border-emerald-300 bg-emerald-50 text-emerald-950'
            : learning?.state === 'at_risk' ? 'border-amber-300 bg-amber-50 text-amber-950'
              : learning?.state === 'covered' ? 'border-blue-200 bg-blue-50 text-blue-950' : 'border-slate-200 bg-white text-slate-900'
    }`}>
      <Handle type="target" position={Position.Top} className="!h-2 !w-2 !border-0 !bg-blue-400" />
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <div className="mb-1 flex flex-wrap items-center gap-1.5">
            {item.examImportance === 'high' && <Star size={13} className={root ? 'fill-amber-300 text-amber-300' : 'fill-amber-400 text-amber-500'} />}
            {!root && typeLabel[item.type] && <span className="rounded-full bg-white px-1.5 py-0.5 text-[10px] font-semibold text-slate-700">{typeLabel[item.type]}</span>}
            {item.sourceIds.length > 0 && <FileText size={12} className={root ? 'text-blue-100' : 'text-emerald-600'} />}
          </div>
          <div className="font-semibold leading-snug">{item.label}</div>
          <div className="mt-2 text-xs">
            <div>{states[learning?.state ?? 'unbound']}</div>
            {mastery == null ? '尚未评估' : `掌握度 ${mastery}%`}
            {!!learning?.dueCards && <div>待复习 {learning.dueCards} 张</div>}
            {learning && learning.misconceptionRisk >= 0.75 && <div>存在误解风险</div>}
          </div>
        </div>
        {hasChildren && (
          <button
            type="button"
            aria-label={collapsed ? '展开子节点' : '折叠子节点'}
            onClick={(event) => { event.stopPropagation(); onToggle(item.id); }}
            className={`nodrag rounded-lg p-1 ${root ? 'bg-white/15 hover:bg-white/25' : 'bg-slate-100 hover:bg-slate-200'}`}
          >
            {collapsed ? <ChevronRight size={15} /> : <ChevronDown size={15} />}
          </button>
        )}
      </div>
      <Handle type="source" position={Position.Bottom} className="!h-2 !w-2 !border-0 !bg-blue-400" />
    </div>
  );
}

