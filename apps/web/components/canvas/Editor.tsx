'use client';

import {
  addEdge, Background, Controls, ReactFlow, ReactFlowProvider, useEdgesState, useNodesInitialized, useNodesState, useReactFlow,
  type Connection, type Edge,
} from '@xyflow/react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AGENT_TEMPLATES, defaultConfig, edgeProblem, NODE_META, type CanvasGraph, type GraphNode, type NodeType } from '@aivanta/graph-schema';
import { api, streamUrl } from '@/lib/api';
import { applyRecommendedPath, type PathChoice } from '@/lib/agentPath';
import { composeCanvasName, intakePrefix, NAME_SEP, stripIntakePrefix, type ProjectInfo } from '@/lib/canvasName';
import { useSession } from '@/lib/session';
import { Modal, Pill, toast } from '@/components/ui';
import { AgentNode, type AgentFlowNode } from './AgentNode';
import { Inspector } from './Inspector';

const nodeTypes = { aivanta: AgentNode };
const AGENT_OUTPUT: Record<string, [string, string]> = {
  RFP_INTELLIGENCE: ['rfp.v1', 'requirements.v1'], BRD_AUTHOR: ['requirements.v1', 'brd.v1'], SOW_AUTHOR: ['brd.v1', 'sow.v1'],
  SOLUTION_ARCHITECT: ['requirements.v1', 'architecture.v1'], TECH_ADVISOR: ['architecture.v1', 'tech_matrix.v1'], EFFORT_ESTIMATOR: ['tech_matrix.v1', 'effort.v1'],
  CLOUD_FINOPS: ['tech_matrix.v1', 'cloud_cost.v1'], COMMERCIAL_PRICING: ['effort.v1', 'pricing.v1'], RESOURCE_PLANNER: ['effort.v1', 'staffing.v1'],
  GOVERNANCE_REVIEWER: ['package.v1', 'review.v1'],
};
const pretty = (t: string) => t.toLowerCase().split('_').map((w) => w[0].toUpperCase() + w.slice(1)).join(' ');

interface GraphResponse {
  id: string; name: string; draft: CanvasGraph; versions: { version: number; content_hash: string; environment: string }[];
  unpublished_changes: boolean; validation: { ok: boolean; issues: { severity: string; message: string; node_id: string | null; code: string }[] } | null;
}

function toFlow(g: CanvasGraph): { nodes: AgentFlowNode[]; edges: Edge[] } {
  return {
    nodes: g.nodes.map((n) => ({ id: n.id, type: 'aivanta', position: n.position, data: { node: n } })),
    edges: g.edges.map((e) => ({ id: e.id, source: e.source, target: e.target, label: e.label ?? undefined })),
  };
}

function fromFlow(nodes: AgentFlowNode[], edges: Edge[]): CanvasGraph {
  return {
    schema_version: 'canvas.v1',
    nodes: nodes.map((n) => ({ ...n.data.node, position: { x: Math.round(n.position.x), y: Math.round(n.position.y) } })),
    edges: edges.map((e) => ({ id: e.id, source: e.source, target: e.target, label: (e.label as string) || null })),
  };
}

function EditorInner({ graphId }: { graphId: string }) {
  const { can, meta, projectId, session } = useSession();
  const flow = useReactFlow();
  const [graph, setGraph] = useState<GraphResponse | null>(null);
  const [project, setProject] = useState<ProjectInfo | null>(null);
  const [canvasLabel, setCanvasLabel] = useState('');
  const [nodes, setNodes, onNodesChange] = useNodesState<AgentFlowNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [selNode, setSelNode] = useState<string | null>(null);
  const [selEdge, setSelEdge] = useState<string | null>(null);
  const [issues, setIssues] = useState<any[]>([]);
  const [tools, setTools] = useState<{ id: string; approved: boolean; external: boolean }[]>([]);
  const [run, setRun] = useState<any>(null);
  const [events, setEvents] = useState<any[]>([]);
  const [modal, setModal] = useState<{ title: string; body: string } | null>(null);
  const [saveAsOpen, setSaveAsOpen] = useState(false);
  const [saveAsLabel, setSaveAsLabel] = useState('');
  const esRef = useRef<EventSource | null>(null);
  const fitted = useRef(false);
  const paneRef = useRef<HTMLDivElement | null>(null);
  const readOnly = !can('graph:edit');
  const runtime = meta?.runtime ?? 'n8n';

  const load = useCallback(async () => {
    const g = await api<GraphResponse>(`/graphs/${graphId}`);
    setGraph(g);
    const f = toFlow(g.draft);
    setNodes(f.nodes);
    setEdges(f.edges);
    setIssues(g.validation?.issues ?? []);
    fitted.current = false;
  }, [graphId, setNodes, setEdges]);

  useEffect(() => {
    if (!projectId) {
      setProject(null);
      return;
    }
    api<ProjectInfo>(`/projects/${projectId}`)
      .then((p) => setProject({ id: p.id, code: p.code, name: p.name, client: p.client }))
      .catch(() => setProject(null));
  }, [projectId]);

  useEffect(() => {
    if (!graph) return;
    setCanvasLabel(stripIntakePrefix(graph.name, project));
  }, [graph?.id, graph?.name, project?.id, project?.code, project?.name]);

  // Fit once React Flow has measured the nodes (fitting earlier clips wide graphs).
  const initialized = useNodesInitialized();
  useEffect(() => {
    if (!initialized || fitted.current || !nodes.length || !paneRef.current) return;
    fitted.current = true;
    const { width, height } = paneRef.current.getBoundingClientRect();
    const b = flow.getNodesBounds(nodes);
    const zoom = Math.max(0.45, Math.min(1, (width - 48) / b.width, (height - 48) / b.height));
    const x = b.width * zoom <= width - 48 ? (width - b.width * zoom) / 2 - b.x * zoom : 24 - b.x * zoom; // wide graphs anchor on Start
    const y = 28 - b.y * zoom; // anchor to the top so the run drawer never hides the graph
    flow.setViewport({ x, y, zoom });
  }, [initialized, nodes, flow]);

  useEffect(() => {
    load();
    api('/tools').then(setTools);
    return () => esRef.current?.close();
  }, [load]);

  const current = () => fromFlow(nodes, edges);
  const invalid = useMemo(() => new Set(issues.filter((i: any) => i.severity === 'error').map((i: any) => i.node_id)), [issues]);
  const statusOf = (id: string) => run?.node_status?.[id] as string | undefined;
  const viewNodes = nodes.map((n) => ({ ...n, data: { ...n.data, status: statusOf(n.id), invalid: invalid.has(n.id) } }));

  const onConnect = useCallback(async (c: Connection) => {
    if (!c.source || !c.target) return;
    const problem = edgeProblem(fromFlow(nodes, edges), c.source, c.target);
    if (problem) {
      toast(`Invalid connection: ${problem}`, true);
      api(`/graphs/${graphId}/edge-check`, { method: 'POST', json: { source: c.source, target: c.target } }).catch(() => undefined);
      return;
    }
    const src = nodes.find((n) => n.id === c.source)?.data.node;
    const label = src?.type === 'decision' ? `branch ${edges.filter((e) => e.source === c.source).length + 1}` : undefined;
    setEdges((eds) => addEdge({ ...c, id: `e_${Math.random().toString(36).slice(2, 8)}`, label }, eds));
  }, [nodes, edges, graphId, setEdges]);

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    if (readOnly) return toast('Your role can view but not edit canvases.', true);
    const raw = e.dataTransfer.getData('application/aivanta');
    if (!raw) return;
    const { type, template } = JSON.parse(raw) as { type: NodeType; template?: string };
    if (type === 'start' && nodes.some((n) => n.data.node.type === 'start')) return toast('A graph can have only one Start node.', true);
    const position = flow.screenToFlowPosition({ x: e.clientX, y: e.clientY });
    const id = `${template ? template.toLowerCase().split('_')[0] : type}_${Math.random().toString(36).slice(2, 6)}`;
    const config = defaultConfig(type, template);
    if (template && AGENT_OUTPUT[template]) [config.input_schema, config.output_schema] = AGENT_OUTPUT[template];
    const node: GraphNode = { id, type, name: template ? pretty(template) : NODE_META[type].label, position, config };
    setNodes((ns) => [...ns, { id, type: 'aivanta', position, data: { node } }]);
    setSelNode(id);
  }, [flow, nodes, readOnly, setNodes]);

  async function save(labelOverride?: string) {
    const label = (labelOverride ?? canvasLabel).trim() || 'Canvas';
    const name = composeCanvasName(project, label);
    const g = await api<GraphResponse>(`/graphs/${graphId}`, { method: 'PUT', json: { draft: current(), name } });
    setGraph(g);
    setCanvasLabel(stripIntakePrefix(g.name, project));
    setIssues(g.validation?.issues ?? []);
    toast(`Saved as “${g.name}” · ${g.validation?.ok ? 'valid' : `${g.validation?.issues.filter((i) => i.severity === 'error').length} errors`}`);
    return g;
  }

  async function saveAsVersion() {
    const label = saveAsLabel.trim();
    if (!label) return toast('Enter a version / intake label.', true);
    try {
      await save(label);
      setSaveAsOpen(false);
    } catch (e: any) {
      toast(e.message, true);
    }
  }
  async function validate() {
    await save();
    const r = await api<any>(`/graphs/${graphId}/validate`, { method: 'POST' });
    setIssues(r.issues);
    setSelNode(null);
    setSelEdge(null);
    toast(r.ok ? `Valid · ${r.warnings} warnings` : `${r.errors} errors, ${r.warnings} warnings`, !r.ok);
  }
  async function publish() {
    try {
      await save();
      const v = await api<any>(`/graphs/${graphId}/publish`, { method: 'POST' });
      toast(`Published v${v.version} (${v.content_hash}) · compiled for ${v.compiled_for}`);
      load();
    } catch (e: any) {
      toast(e.message, true);
    }
  }
  async function compare() {
    const latest = graph?.versions.at(-1);
    if (!latest) return toast('Nothing published yet.');
    await save();
    const d = await api<any>(`/graphs/${graphId}/diff?against=${latest.version}`);
    setModal({ title: `Draft vs v${latest.version}`, body: JSON.stringify(d, null, 2) });
  }
  async function exportNative() {
    const x = await api<any>(`/graphs/${graphId}/export`);
    setModal({ title: x.format === 'mermaid' ? 'LangGraph (Mermaid)' : x.format === 'n8n-workflow' ? 'n8n workflow JSON (Workflows → Import from file)' : 'AutoGen Studio component', body: (typeof x.content === 'string' ? x.content : JSON.stringify(x.content, null, 2)) + `\n\n# ${x.note}` });
  }
  async function startRun(published: boolean) {
    if (!projectId) return toast('Pick a project in the top bar first.', true);
    try {
      if (!published) await save();
      const latest = graph?.versions.at(-1)?.version ?? null;
      const r = await api<any>('/runs', { method: 'POST', json: { graph_id: graphId, project_id: projectId, version: published ? latest : null } });
      follow(r.id);
      toast(`Run ${r.id.slice(0, 8)} started on ${runtime}`);
    } catch (e: any) {
      toast(e.message, true);
    }
  }
  function follow(runId: string) {
    esRef.current?.close();
    setEvents([]);
    const refresh = () => api(`/runs/${runId}`).then(setRun);
    refresh();
    const es = new EventSource(streamUrl(`/runs/${runId}/stream`));
    es.onmessage = () => refresh();
    ['node_started', 'node_succeeded', 'node_skipped', 'node_failed', 'node_retry', 'approval_requested', 'approval_decided', 'route_selected', 'agent_message', 'run_succeeded', 'run_failed', 'run_paused', 'run_resumed', 'status']
      .forEach((t) => es.addEventListener(t, (ev) => {
        const data = JSON.parse((ev as MessageEvent).data);
        if (t !== 'status') setEvents((x) => [...x.slice(-200), data]);
        refresh();
      }));
    esRef.current = es;
  }
  async function decide(nodeId: string, decision: 'Approved' | 'Rejected') {
    const pending = await api<any[]>('/approvals?status=Pending');
    const a = pending.find((x) => x.run_id === run.id && x.node_id === nodeId);
    if (!a) return toast('Approval not found', true);
    try {
      await api(`/approvals/${a.id}/decide`, { method: 'POST', json: { decision } });
      toast(`${a.kind}: ${decision}`);
      setTimeout(() => api(`/runs/${run.id}`).then(setRun), 400);
    } catch (e: any) {
      toast(e.message, true);
    }
  }

  const sNode = nodes.find((n) => n.id === selNode)?.data.node ?? null;
  const sEdge = edges.find((e) => e.id === selEdge);
  const nameOf = (id: string) => nodes.find((n) => n.id === id)?.data.node.name ?? id;
  const waiting = run ? Object.entries(run.node_status || {}).filter(([, s]) => s === 'approval').map(([id]) => id) : [];
  const latest = graph?.versions.at(-1);

  return (
    <div className="canvas-shell">
      <div className="palette" aria-label="Node palette">
        {[['Flow', ['start', 'end']], ['Tools & logic', ['tool', 'decision', 'approval', 'data', 'calc']]].map(([g, types]) => (
          <div key={g as string}>
            <div className="pg">{g}</div>
            {(types as NodeType[]).map((t) => (
              <div key={t} className="pal-item" draggable onDragStart={(e) => e.dataTransfer.setData('application/aivanta', JSON.stringify({ type: t }))}>
                <i style={{ background: NODE_META[t].color }} />{NODE_META[t].label}
              </div>
            ))}
          </div>
        ))}
        <div className="pg">Agents</div>
        {AGENT_TEMPLATES.map((t) => (
          <div key={t} className="pal-item" draggable onDragStart={(e) => e.dataTransfer.setData('application/aivanta', JSON.stringify({ type: 'agent', template: t }))}>
            <i style={{ background: NODE_META.agent.color }} />{pretty(t)}
          </div>
        ))}
      </div>
      <div className="flow-wrap">
        <div className="toolbar">
          <div className="canvas-name">
            <div className="canvas-name-prefix" title={project ? `${project.code} · ${project.client} · ${project.name}` : 'Pick a project in the top bar to prefix by Project & RFP Intake'}>
              {project ? `${intakePrefix(project)}${NAME_SEP}` : 'No project selected — name will not include intake prefix'}
            </div>
            <div className="canvas-name-row">
              <input
                id="canvas-label"
                aria-label="Canvas name (after project · RFP intake prefix)"
                value={canvasLabel}
                disabled={readOnly}
                placeholder="e.g. RFP-to-SOW · Intake v2"
                onChange={(e) => setCanvasLabel(e.target.value)}
              />
              {latest ? <Pill>{latest.environment}</Pill> : <Pill tone="warn">draft only</Pill>}
              {graph?.unpublished_changes && latest && <Pill tone="warn">unpublished changes</Pill>}
            </div>
          </div>
          <span style={{ flex: 1 }} />
          <button className="btn" onClick={validate}>Validate</button>
          <button className="btn" onClick={() => save().catch((e) => toast(e.message, true))} disabled={readOnly}>Save draft</button>
          <button
            className="btn"
            disabled={readOnly}
            onClick={() => {
              setSaveAsLabel(canvasLabel ? `${canvasLabel.replace(/\s*·\s*v\d+$/i, '')} · v${(graph?.versions.length ?? 0) + 1}` : 'Intake v1');
              setSaveAsOpen(true);
            }}
          >Save as…</button>
          <button className="btn" onClick={compare} disabled={!latest}>Compare</button>
          <button className="btn" onClick={publish} disabled={!can('graph:publish')}>Publish</button>
          <button className="btn" onClick={exportNative}>{runtime === 'AutoGen' ? 'Export to AutoGen Studio' : runtime === 'n8n' ? 'Export n8n workflow' : 'Export LangGraph'}</button>
          <button className="btn" onClick={() => startRun(false)} disabled={!can('run:start')}>Simulate draft</button>
          <button className="btn primary" onClick={() => startRun(true)} disabled={!can('run:start') || !latest}>Run v{latest?.version ?? '–'}</button>
        </div>
        <div className="flow" ref={paneRef} onDrop={onDrop} onDragOver={(e) => e.preventDefault()}>
          <ReactFlow
            nodes={viewNodes} edges={edges.map((e) => ({ ...e, animated: run && statusOf(e.target) === 'running', selected: e.id === selEdge }))}
            nodeTypes={nodeTypes} onNodesChange={onNodesChange} onEdgesChange={onEdgesChange} onConnect={onConnect}
            onNodeClick={(_, n) => { setSelNode(n.id); setSelEdge(null); }} onEdgeClick={(_, e) => { setSelEdge(e.id); setSelNode(null); }}
            onPaneClick={() => { setSelNode(null); setSelEdge(null); }} nodesDraggable={!readOnly} nodesConnectable={!readOnly}
            deleteKeyCode={readOnly ? null : ['Delete', 'Backspace']} minZoom={0.2}
          >
            <Background gap={20} />
            <Controls />
          </ReactFlow>
        </div>
        {run && (
          <div className="run-drawer">
            <div className="row">
              <b className="mono">{run.id.slice(0, 12)}</b><Pill>{run.status}</Pill>
              <span className="muted">{run.graph_version} · {run.runtime} · {run.tokens.toLocaleString()} tokens</span>
              {run.status === 'failed' && <button className="btn" onClick={() => api(`/runs/${run.id}/retry`, { method: 'POST' }).then(() => follow(run.id))}>Resume from failure</button>}
              {['running', 'awaiting_approval', 'queued'].includes(run.status) && <button className="btn" onClick={() => api(`/runs/${run.id}/cancel`, { method: 'POST' }).then(() => follow(run.id))}>Cancel</button>}
            </div>
            {run.error && <p style={{ color: 'var(--bad)' }}>{run.error}</p>}
            {waiting.map((id) => {
              const n = nodes.find((x) => x.id === id)?.data.node;
              const mine = session?.user.roles.includes(n?.config.approver_role);
              return (
                <div key={id} className="row" style={{ marginTop: 6 }}>
                  <Pill tone="gold">awaiting</Pill> <b>{n?.name}</b> <span className="muted">approver: {n?.config.approver_role}</span>
                  <button className="btn primary" disabled={!mine} onClick={() => decide(id, 'Approved')}>Approve</button>
                  <button className="btn danger" disabled={!mine} onClick={() => decide(id, 'Rejected')}>Reject</button>
                  {!mine && <span className="faint">Sign in as {n?.config.approver_role} to decide (segregation of duties).</span>}
                </div>
              );
            })}
            <div className="mono" style={{ fontSize: 11.5, marginTop: 6 }}>
              {events.slice(-12).map((e, i) => (
                <div key={i}><span className="faint">{e.type}</span> {e.node_id ? nameOf(e.node_id) : ''} {e.type === 'agent_message' ? `· ${e.data.source}: ${String(e.data.preview).slice(0, 90)}` : ''}{e.type === 'route_selected' ? `→ ${e.data.label}` : ''}</div>
              ))}
            </div>
          </div>
        )}
      </div>
      <div className="inspector">
        <Inspector
          node={sNode}
          edge={sEdge ? { id: sEdge.id, label: sEdge.label as string, sourceName: nameOf(sEdge.source), targetName: nameOf(sEdge.target) } : null}
          tools={tools} runtime={runtime} readOnly={readOnly} issues={issues}
          graphId={graphId}
          projectId={projectId}
          draft={current()}
          onSave={save}
          onSelectNode={(id) => { setSelNode(id); setSelEdge(null); }}
          onApplyRecommendedPath={async (nodeId, choice: PathChoice = 'follow') => {
            const { graph: next, focusId, message } = applyRecommendedPath(current(), nodeId, choice);
            const f = toFlow(next);
            setNodes(f.nodes);
            setEdges(f.edges);
            setSelNode(focusId);
            setSelEdge(null);
            toast(message);
            try {
              const name = composeCanvasName(project, canvasLabel.trim() || 'Canvas');
              const g = await api<GraphResponse>(`/graphs/${graphId}`, { method: 'PUT', json: { draft: next, name } });
              setGraph(g);
              setCanvasLabel(stripIntakePrefix(g.name, project));
              setIssues(g.validation?.issues ?? []);
            } catch (e: any) {
              toast(e.message || 'Path connected locally; save failed.', true);
            }
          }}
          onNode={(n) => setNodes((ns) => ns.map((x) => (x.id === n.id ? { ...x, data: { ...x.data, node: n } } : x)))}
          onEdgeLabel={(label) => setEdges((es) => es.map((e) => (e.id === selEdge ? { ...e, label } : e)))}
          onDelete={() => {
            if (selNode) { setNodes((ns) => ns.filter((n) => n.id !== selNode)); setEdges((es) => es.filter((e) => e.source !== selNode && e.target !== selNode)); setSelNode(null); }
            if (selEdge) { setEdges((es) => es.filter((e) => e.id !== selEdge)); setSelEdge(null); }
          }}
        />
      </div>
      {modal && <Modal title={modal.title} onClose={() => setModal(null)}><pre className="code">{modal.body}</pre></Modal>}
      {saveAsOpen && (
        <Modal title="Save canvas as intake version" onClose={() => setSaveAsOpen(false)}>
          <div className="stack">
            <p className="muted" style={{ margin: 0 }}>
              Name is prefixed with the selected <b>Project code</b> and <b>RFP Intake</b> name so versions of the same intake stay grouped.
            </p>
            <div className="field">
              <span>Prefix</span>
              <input value={project ? `${intakePrefix(project)}${NAME_SEP}` : '(select a project in the top bar)'} disabled readOnly />
            </div>
            <label className="field">Version / canvas label
              <input
                id="save-as-label"
                autoFocus
                value={saveAsLabel}
                onChange={(e) => setSaveAsLabel(e.target.value)}
                placeholder="e.g. RFP-to-SOW · Intake v2"
              />
            </label>
            <p className="faint mono" style={{ margin: 0 }}>
              Will save as: {composeCanvasName(project, saveAsLabel || 'Canvas')}
            </p>
            <div className="row">
              <button className="btn primary" onClick={saveAsVersion}>Save</button>
              <button className="btn" onClick={() => setSaveAsOpen(false)}>Cancel</button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}

export function Editor({ graphId }: { graphId: string }) {
  return (
    <ReactFlowProvider>
      <EditorInner graphId={graphId} />
    </ReactFlowProvider>
  );
}
