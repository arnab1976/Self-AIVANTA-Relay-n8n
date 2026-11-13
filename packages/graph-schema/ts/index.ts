// AIVANTA canvas graph schema (canvas.v1). Relay edition: palette labels use n8n vocabulary. — TypeScript types shared by the web app.
// The Python twin lives in ../python/aivanta_graph. Server-side validation is authoritative.

export type NodeType = 'start' | 'end' | 'agent' | 'tool' | 'decision' | 'approval' | 'data' | 'calc';

export interface Position { x: number; y: number }
export interface GraphNode { id: string; type: NodeType; name: string; position: Position; config: Record<string, any> }
export interface GraphEdge { id: string; source: string; target: string; label?: string | null }
export interface CanvasGraph {
  schema_version: 'canvas.v1';
  input_schema?: string;
  output_schema?: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export const NODE_META: Record<NodeType, { label: string; color: string; description: string; rule: string }> = {
  start: { label: 'Trigger', color: '#24323C', description: 'n8n Webhook trigger (header auth) + start step; input schema, project ID', rule: 'One start; reachable terminal path' },
  end: { label: 'Respond / End', color: '#24323C', description: 'Marks the end of the run; output schema', rule: 'Reachable from start' },
  agent: { label: 'AI Agent', color: '#B85600', description: 'n8n AI Agent node + OpenAI Chat Model on the AIVANTA model gateway; template, profile, schema', rule: 'Allowed model, approved tools, bounded prompts' },
  tool: { label: 'HTTP / App node', color: '#2A5FBF', description: 'HTTP Request to the AIVANTA tool gateway: connector, operation, vault credential, timeout', rule: 'Approved endpoint, scopes, schemas' },
  decision: { label: 'IF / Switch', color: '#B58300', description: 'Rule evaluated by AIVANTA, routed by an n8n Switch node; one output per label', rule: 'Exhaustive, deterministic routing' },
  approval: { label: 'Send & Wait', color: '#B83A6B', description: 'Approval request + n8n Wait node (resume on webhook); approver role, SLA, evidence', rule: 'Required before external send, price approval, contract finalization' },
  data: { label: 'Vector Store', color: '#2F7D3B', description: 'Tenant-filtered retrieval; knowledge base, policy, filters', rule: 'Project/tenant access, source traceability' },
  calc: { label: 'Code (pricing)', color: '#5C6670', description: 'Deterministic pricing engine on the versioned rate card (no LLM)', rule: 'Deterministic; no LLM arithmetic' },
};

export const AGENT_TEMPLATES = [
  'RFP_INTELLIGENCE', 'BRD_AUTHOR', 'SOW_AUTHOR', 'SOLUTION_ARCHITECT', 'TECH_ADVISOR',
  'EFFORT_ESTIMATOR', 'CLOUD_FINOPS', 'COMMERCIAL_PRICING', 'RESOURCE_PLANNER', 'GOVERNANCE_REVIEWER',
] as const;

/** Live check while the user drags a connection. Mirrors aivanta_graph.edge_problem. */
export function edgeProblem(graph: CanvasGraph, source: string, target: string): string | null {
  const a = graph.nodes.find((n) => n.id === source);
  const b = graph.nodes.find((n) => n.id === target);
  if (!a || !b) return 'Both ends of a connection must be existing nodes.';
  if (source === target) return 'A node cannot connect to itself.';
  if (b.type === 'start') return 'Start cannot have incoming connections.';
  if (a.type === 'end') return 'End cannot have outgoing connections.';
  if (b.type === 'data') return 'Data / RAG nodes are sources and take no inputs.';
  if (graph.edges.some((e) => e.source === source && e.target === target)) return 'These nodes are already connected.';
  // would the new edge close a loop? (target already reaches source)
  const seen = new Set<string>();
  const stack = [target];
  while (stack.length) {
    const cur = stack.pop() as string;
    if (cur === source) return 'This connection would create a cycle. Use a Decision with a bounded retry instead.';
    if (seen.has(cur)) continue;
    seen.add(cur);
    graph.edges.filter((e) => e.source === cur).forEach((e) => stack.push(e.target));
  }
  return null;
}

export function defaultConfig(type: NodeType, template?: string): Record<string, any> {
  switch (type) {
    case 'agent':
      return {
        template: template ?? 'RFP_INTELLIGENCE',
        role: '',
        description: '',
        model_profile: 'enterprise-fast',
        temperature: 0.2,
        frequency_penalty: 0,
        presence_penalty: 0,
        tools: [],
        mcp_tools: [],
        input_schema: 'requirements.v1',
        output_schema: 'brd.v1',
        retry: 2,
        timeout_s: 180,
        guardrails: ['cite_sources', 'json_schema', 'pii_redaction', 'injection_filter'],
        team_pattern: 'single',
        fail_simulation: false,
      };
    case 'tool':
      return { tool_id: 'document_reader', operation: 'read', credential_ref: 'vault://docs/reader', timeout_s: 60, retry: 1, fail_simulation: false };
    case 'decision':
      return { rule: 'open_clarifications > 0', sim_outcome: 'auto' };
    case 'approval':
      return { approver_role: 'finance', sla_hours: 24, evidence: 'Linked artifacts' };
    case 'data':
      return { knowledge_base: 'approved-proposals', retrieval: 'hybrid', access_filter: 'tenant+project', top_k: 6 };
    case 'calc':
      return { formula: 'selling_price', rate_card_version: 'tenant:current', currency_rule: 'tenant', tax_rule: 'excluded' };
    case 'start':
      return { input_schema: 'project.v1' };
    default:
      return { output_schema: 'proposal_package.v1' };
  }
}
