'use client';

import { Handle, Position, type Node, type NodeProps } from '@xyflow/react';
import { NODE_META, type GraphNode } from '@aivanta/graph-schema';

export type AgentNodeData = { node: GraphNode; status?: string; invalid?: boolean };
export type AgentFlowNode = Node<AgentNodeData, 'aivanta'>;

function subtitle(n: GraphNode): string {
  const c = n.config || {};
  switch (n.type) {
    case 'agent': return `${c.model_profile ?? ''} · ${(c.tools ?? []).length} tools${c.team_pattern === 'author_reviewer' ? ' · team' : ''}`;
    case 'tool': return `${c.tool_id}.${c.operation}`;
    case 'approval': return `approver: ${c.approver_role} · SLA ${c.sla_hours}h`;
    case 'decision': return c.rule ?? '';
    case 'data': return c.knowledge_base ?? '';
    case 'calc': return c.rate_card_version ?? '';
    case 'start': return c.input_schema ?? '';
    default: return c.output_schema ?? '';
  }
}

export function AgentNode({ data, selected }: NodeProps<AgentFlowNode>) {
  const n = data.node;
  const meta = NODE_META[n.type];
  const cls = ['anode', selected ? 'selected' : '', data.status ? `st-${data.status}` : '', data.invalid ? 'bad' : ''].join(' ');
  return (
    <div className={cls}>
      {n.type !== 'start' && n.type !== 'data' && <Handle type="target" position={Position.Left} />}
      <div className="h" style={{ background: `${meta.color}22`, color: meta.color }}>
        {n.type === 'agent' ? n.config.template : meta.label}
        {data.status && <span style={{ float: 'right' }}>{data.status}</span>}
      </div>
      <div className="n">{n.name}</div>
      <div className="s">{subtitle(n)}</div>
      {n.type !== 'end' && <Handle type="source" position={Position.Right} />}
    </div>
  );
}
