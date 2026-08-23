import { useMemo, useState } from 'react';
import {
  Background, BackgroundVariant, Controls, MarkerType, MiniMap, ReactFlow,
  type Edge, type Node, type NodeMouseHandler,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import type { MindMapData, MindMapNode } from '../../../types';
import { KnowledgeNode, type KnowledgeNodeData } from './KnowledgeNode';

type Props = { data: MindMapData; onSelect: (node: MindMapNode) => void };
const nodeTypes = { knowledge: KnowledgeNode };

function descendantsOf(id: string, children: Map<string, string[]>): string[] {
  const result: string[] = [];
  const queue = [...(children.get(id) ?? [])];
  while (queue.length) {
    const current = queue.shift()!;
    result.push(current);
    queue.push(...(children.get(current) ?? []));
  }
  return result;
}

export function MindMapCanvas({ data, onSelect }: Props) {
  const [collapsed, setCollapsed] = useState<Set<string>>(() => new Set(
    data.nodes.filter((node) => node.level >= 2).map((node) => node.id),
  ));
  const children = useMemo(() => {
    const map = new Map<string, string[]>();
    data.nodes.forEach((node) => {
      if (node.parentId) map.set(node.parentId, [...(map.get(node.parentId) ?? []), node.id]);
    });
    return map;
  }, [data.nodes]);
  const hidden = useMemo(() => {
    const ids = new Set<string>();
    collapsed.forEach((id) => descendantsOf(id, children).forEach((child) => ids.add(child)));
    return ids;
  }, [children, collapsed]);

  const visible = data.nodes.filter((node) => !hidden.has(node.id));
  const byLevel = new Map<number, MindMapNode[]>();
  visible.forEach((node) => byLevel.set(node.level, [...(byLevel.get(node.level) ?? []), node]));
  const flowNodes: Array<Node<KnowledgeNodeData>> = visible.map((item) => {
    const row = byLevel.get(item.level) ?? [item];
    const index = row.findIndex((node) => node.id === item.id);
    return {
      id: item.id,
      type: 'knowledge',
      position: { x: (index - (row.length - 1) / 2) * 285, y: item.level * 175 },
      data: {
        item,
        collapsed: collapsed.has(item.id),
        hasChildren: children.has(item.id),
        onToggle: (id: string) => setCollapsed((current) => {
          const next = new Set(current);
          if (next.has(id)) next.delete(id); else next.add(id);
          return next;
        }),
      },
    };
  });
  const visibleIds = new Set(visible.map((node) => node.id));
  const flowEdges: Edge[] = data.edges
    .filter((edge) => visibleIds.has(edge.source) && visibleIds.has(edge.target))
    .map((edge, index) => ({
      id: `${edge.source}-${edge.target}-${index}`,
      source: edge.source,
      target: edge.target,
      label: edge.relation,
      type: 'smoothstep',
      markerEnd: { type: MarkerType.ArrowClosed, color: '#94a3b8' },
      style: { stroke: '#94a3b8', strokeWidth: 1.5 },
      labelStyle: { fill: '#64748b', fontSize: 11 },
      labelBgStyle: { fill: '#f8fafc', fillOpacity: 0.92 },
    }));
  const select: NodeMouseHandler = (_event, node) => onSelect((node.data as KnowledgeNodeData).item);

  return (
    <div className="h-full min-h-[520px] w-full">
      <ReactFlow
        nodes={flowNodes}
        edges={flowEdges}
        nodeTypes={nodeTypes}
        onNodeClick={select}
        fitView
        fitViewOptions={{ padding: 0.22 }}
        minZoom={0.25}
        maxZoom={1.8}
        nodesDraggable
        proOptions={{ hideAttribution: true }}
      >
        <Background variant={BackgroundVariant.Dots} gap={22} size={1.2} color="#cbd5e1" />
        <Controls position="bottom-left" />
        <MiniMap position="bottom-right" pannable zoomable nodeColor={(node) => ((node.data as KnowledgeNodeData).item.level === 0 ? '#4f46e5' : '#bfdbfe')} />
      </ReactFlow>
    </div>
  );
}

