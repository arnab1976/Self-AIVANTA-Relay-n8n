import { AGENT_TEMPLATES, defaultConfig, type CanvasGraph } from '@aivanta/graph-schema';

/** Default journey after each agent template (presales-to-delivery). */
export const AGENT_JOURNEY_NEXT: Record<string, string | 'end'> = {
  RFP_INTELLIGENCE: 'BRD_AUTHOR',
  BRD_AUTHOR: 'SOLUTION_ARCHITECT',
  SOLUTION_ARCHITECT: 'TECH_ADVISOR',
  TECH_ADVISOR: 'EFFORT_ESTIMATOR',
  EFFORT_ESTIMATOR: 'CLOUD_FINOPS',
  CLOUD_FINOPS: 'COMMERCIAL_PRICING',
  COMMERCIAL_PRICING: 'RESOURCE_PLANNER',
  RESOURCE_PLANNER: 'GOVERNANCE_REVIEWER',
  GOVERNANCE_REVIEWER: 'SOW_AUTHOR',
  SOW_AUTHOR: 'end',
};

const AGENT_IO: Record<string, [string, string]> = {
  RFP_INTELLIGENCE: ['rfp.v1', 'requirements.v1'],
  BRD_AUTHOR: ['requirements.v1', 'brd.v1'],
  SOW_AUTHOR: ['brd.v1', 'sow.v1'],
  SOLUTION_ARCHITECT: ['requirements.v1', 'architecture.v1'],
  TECH_ADVISOR: ['architecture.v1', 'tech_matrix.v1'],
  EFFORT_ESTIMATOR: ['tech_matrix.v1', 'effort.v1'],
  CLOUD_FINOPS: ['tech_matrix.v1', 'cloud_cost.v1'],
  COMMERCIAL_PRICING: ['effort.v1', 'pricing.v1'],
  RESOURCE_PLANNER: ['effort.v1', 'staffing.v1'],
  GOVERNANCE_REVIEWER: ['package.v1', 'review.v1'],
};

const pretty = (t: string) => t.toLowerCase().split('_').map((w) => w[0].toUpperCase() + w.slice(1)).join(' ');

export function suggestedNextTemplate(template: string | undefined): string | 'end' {
  if (!template) return 'BRD_AUTHOR';
  return AGENT_JOURNEY_NEXT[template] ?? 'end';
}

export function hasInbound(graph: CanvasGraph, nodeId: string): boolean {
  return graph.edges.some((e) => e.target === nodeId);
}

export function hasOutbound(graph: CanvasGraph, nodeId: string): boolean {
  return graph.edges.some((e) => e.source === nodeId);
}

export function pathIssues(graph: CanvasGraph, nodeId: string): string[] {
  const issues: string[] = [];
  if (!hasInbound(graph, nodeId) && !graph.nodes.find((n) => n.id === nodeId && n.type === 'start')) {
    issues.push('Not connected from Start — wire Trigger → this agent.');
  }
  if (!hasOutbound(graph, nodeId) && !graph.nodes.find((n) => n.id === nodeId && n.type === 'end')) {
    issues.push('No outbound path — wire this agent to the next step or End.');
  }
  return issues;
}

function edgeId() {
  return `e_${Math.random().toString(36).slice(2, 8)}`;
}

function nodeId(prefix: string) {
  return `${prefix}_${Math.random().toString(36).slice(2, 6)}`;
}

export type PathChoice = 'follow' | 'skip';

/** Wire Start → agent → recommended next (follow) or Start → agent → End (skip). */
export function applyRecommendedPath(
  graph: CanvasGraph,
  agentId: string,
  choice: PathChoice = 'follow',
): { graph: CanvasGraph; focusId: string; message: string } {
  const nodes = graph.nodes.map((n) => ({ ...n, position: { ...n.position }, config: { ...n.config } }));
  let edges = graph.edges.map((e) => ({ ...e }));
  const agent = nodes.find((n) => n.id === agentId);
  if (!agent || agent.type !== 'agent') {
    return { graph, focusId: agentId, message: 'Select an agent node first.' };
  }

  let start = nodes.find((n) => n.type === 'start');
  if (!start) {
    start = {
      id: nodeId('start'),
      type: 'start',
      name: 'Start',
      position: { x: Math.max(40, agent.position.x - 260), y: agent.position.y },
      config: defaultConfig('start'),
    };
    nodes.push(start);
  }

  let end = nodes.find((n) => n.type === 'end');
  if (!end) {
    end = {
      id: nodeId('end'),
      type: 'end',
      name: 'End',
      position: { x: agent.position.x + 520, y: agent.position.y },
      config: defaultConfig('end'),
    };
    nodes.push(end);
  }

  const link = (source: string, target: string) => {
    if (source === target) return;
    if (edges.some((e) => e.source === source && e.target === target)) return;
    edges.push({ id: edgeId(), source, target, label: null });
  };

  link(start.id, agent.id);

  const nextTpl = suggestedNextTemplate(agent.config?.template);
  const skippedName = nextTpl === 'end' ? 'End' : pretty(nextTpl);

  // Skip: bypass the recommended next agent and finish at End.
  if (choice === 'skip') {
    edges = edges.filter((e) => e.source !== agent.id);
    link(agent.id, end.id);
    end.position = { x: Math.max(end.position.x, agent.position.x + 280), y: agent.position.y };
    return {
      graph: { schema_version: 'canvas.v1', nodes, edges },
      focusId: end.id,
      message: `Skipped ${skippedName}. Connected Start → ${agent.name} → End.`,
    };
  }

  let focusId = agent.id;
  let message: string;

  if (nextTpl === 'end') {
    link(agent.id, end.id);
    focusId = end.id;
    message = `Followed recommendation. Connected Start → ${agent.name} → End.`;
  } else {
    let next = nodes.find((n) => n.type === 'agent' && n.config?.template === nextTpl && n.id !== agent.id);
    if (!next) {
      const cfg = defaultConfig('agent', nextTpl);
      const io = AGENT_IO[nextTpl];
      if (io) {
        cfg.input_schema = io[0];
        cfg.output_schema = io[1];
      }
      if (AGENT_TEMPLATES.includes(nextTpl as typeof AGENT_TEMPLATES[number])) {
        cfg.template = nextTpl;
      }
      next = {
        id: nodeId(nextTpl.toLowerCase().split('_')[0]),
        type: 'agent',
        name: pretty(nextTpl),
        position: { x: agent.position.x + 280, y: agent.position.y },
        config: cfg,
      };
      nodes.push(next);
    }
    link(agent.id, next.id);
    link(next.id, end.id);
    end.position = { x: Math.max(end.position.x, next.position.x + 260), y: next.position.y };
    focusId = next.id;
    message = `Followed recommendation. Connected Start → ${agent.name} → ${next.name} → End.`;
  }

  return {
    graph: { schema_version: 'canvas.v1', nodes, edges },
    focusId,
    message,
  };
}

/** Outbound target that matches the journey recommendation, if already wired. */
export function recommendedOutboundId(graph: CanvasGraph, agentId: string): string | null {
  const agent = graph.nodes.find((n) => n.id === agentId);
  if (!agent) return null;
  const nextTpl = suggestedNextTemplate(agent.config?.template);
  const outs = graph.edges.filter((e) => e.source === agentId).map((e) => graph.nodes.find((n) => n.id === e.target)).filter(Boolean);
  if (nextTpl === 'end') {
    return outs.find((n) => n!.type === 'end')?.id ?? outs[0]?.id ?? null;
  }
  return outs.find((n) => n!.type === 'agent' && n!.config?.template === nextTpl)?.id
    ?? outs.find((n) => n!.type === 'agent')?.id
    ?? outs[0]?.id
    ?? null;
}

export function endNodeId(graph: CanvasGraph): string | null {
  return graph.nodes.find((n) => n.type === 'end')?.id ?? null;
}

export function recommendLabel(template: string | undefined): string {
  const next = suggestedNextTemplate(template);
  if (next === 'end') return 'Respond / End';
  return pretty(next);
}
