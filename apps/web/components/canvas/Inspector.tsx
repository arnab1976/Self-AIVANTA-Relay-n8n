'use client';

import { useEffect, useMemo, useState } from 'react';
import { AGENT_TEMPLATES, NODE_META, type CanvasGraph, type GraphNode } from '@aivanta/graph-schema';
import {
  endNodeId, hasOutbound, pathIssues, recommendLabel, recommendedOutboundId,
  suggestedNextTemplate, type PathChoice,
} from '@/lib/agentPath';
import { api, download } from '@/lib/api';
import { ROLE_LABELS } from '@/lib/format';
import { toast } from '@/components/ui';

const MODEL_PROFILES = ['enterprise-reasoning', 'enterprise-fast', 'local-open-weight', 'experimental-preview'];
const DEFAULT_GUARDRAILS = [
  'cite_sources', 'json_schema', 'pii_redaction', 'injection_filter',
  'no_external_send', 'human_review_required', 'bounded_context', 'tool_allowlist_only',
];

interface NextStep {
  node_id: string;
  name: string;
  type: string;
  label?: string | null;
  recommended?: boolean;
  suggested?: boolean;
  template?: string | null;
}

interface InputFrom {
  node_id: string;
  name: string;
  template: string;
  artifact_id?: string | null;
  simulated?: boolean;
  summary?: string;
}

interface RunResult {
  output_text: string;
  artifact_id?: string | null;
  next_recommendation?: NextStep | null;
  next_steps?: NextStep[];
  inputs_from?: InputFrom[];
  simulated?: boolean;
}

interface Props {
  node: GraphNode | null;
  edge: { id: string; label?: string | null; sourceName: string; targetName: string } | null;
  tools: { id: string; approved: boolean; external: boolean }[];
  runtime: string;
  readOnly: boolean;
  issues: { severity: string; message: string; node_id: string | null }[];
  graphId: string;
  projectId: string | null;
  draft: CanvasGraph;
  onNode: (n: GraphNode) => void;
  onEdgeLabel: (label: string) => void;
  onDelete: () => void;
  onSave: () => Promise<void>;
  onSelectNode: (id: string) => void;
  onApplyRecommendedPath: (nodeId: string, choice?: PathChoice) => Promise<void> | void;
}

function ChipList({
  options, selected, disabled, onToggle,
}: { options: string[]; selected: string[]; disabled?: boolean; onToggle: (id: string, on: boolean) => void }) {
  return (
    <div className="row">
      {options.map((id) => (
        <label key={id} className="pill" style={{ cursor: disabled ? 'default' : 'pointer' }}>
          <input
            type="checkbox"
            disabled={disabled}
            checked={selected.includes(id)}
            onChange={(e) => onToggle(id, e.target.checked)}
          />{' '}{id}
        </label>
      ))}
    </div>
  );
}

export function Inspector({
  node, edge, tools, runtime, readOnly, issues, graphId, projectId, draft,
  onNode, onEdgeLabel, onDelete, onSave, onSelectNode, onApplyRecommendedPath,
}: Props) {
  const [busy, setBusy] = useState<string | null>(null);
  const [runResult, setRunResult] = useState<RunResult | null>(null);
  const [guardrailOpts, setGuardrailOpts] = useState<string[]>(DEFAULT_GUARDRAILS);
  const [mcpOpts, setMcpOpts] = useState<string[]>(tools.map((t) => t.id));

  useEffect(() => {
    setRunResult(null);
  }, [node?.id]);

  const agentPathHints = useMemo(() => {
    if (!node || node.type !== 'agent') return [] as string[];
    return pathIssues(draft, node.id);
  }, [node, draft]);
  const outboundOk = node ? hasOutbound(draft, node.id) : false;
  const nextName = recommendLabel(node?.config?.template);
  const nextTpl = suggestedNextTemplate(node?.config?.template);

  useEffect(() => {
    api<{ guardrails: string[]; mcp_tools: string[] }>('/agent-studio/options')
      .then((o) => {
        if (o.guardrails?.length) setGuardrailOpts(o.guardrails);
        if (o.mcp_tools?.length) setMcpOpts(o.mcp_tools);
      })
      .catch(() => undefined);
  }, []);

  if (edge) {
    return (
      <div className="stack">
        <h3 style={{ fontSize: 15 }}>Connection</h3>
        <p className="muted">{edge.sourceName} → {edge.targetName}</p>
        <label className="field">Branch label (routing outcome for decisions)
          <input id="edge-label" value={edge.label ?? ''} disabled={readOnly} onChange={(e) => onEdgeLabel(e.target.value)} placeholder="e.g. gaps found" />
        </label>
        <p className="faint" style={{ fontSize: 12 }}>Handoff payload: project_id, run_id, graph_version, artifact_id, source refs, status, schema_version.</p>
        <button className="btn danger" disabled={readOnly} onClick={onDelete}>Disconnect</button>
      </div>
    );
  }
  if (!node) {
    return (
      <div className="stack">
        <h3 style={{ fontSize: 15 }}>Validation</h3>
        {issues.length === 0 ? <p className="muted">Select a node or connection to configure it, or run Validate.</p> :
          issues.map((i, k) => <div key={k} className="issue"><span className={`pill ${i.severity === 'error' ? 'bad' : 'warn'}`}>{i.severity}</span> {i.message}</div>)}
      </div>
    );
  }

  const c = node.config;
  const set = (patch: Record<string, unknown>) => onNode({ ...node, config: { ...c, ...patch } });
  const text = (key: string, label: string, type = 'text') => (
    <label className="field" key={key}>{label}
      <input id={`cfg-${key}`} type={type} value={c[key] ?? ''} disabled={readOnly}
        onChange={(e) => set({ [key]: type === 'number' ? Number(e.target.value) : e.target.value })} />
    </label>
  );
  const select = (key: string, label: string, options: string[], labels?: Record<string, string>) => (
    <label className="field" key={key}>{label}
      <select id={`cfg-${key}`} value={c[key] ?? ''} disabled={readOnly} onChange={(e) => set({ [key]: e.target.value })}>
        {options.map((o) => <option key={o} value={o}>{labels?.[o] ?? o}</option>)}
      </select>
    </label>
  );
  const slider = (key: string, label: string, min: number, max: number, step: number) => (
    <label className="field" key={key}>{label}
      <div className="range-row">
        <input
          id={`cfg-${key}`}
          type="range"
          min={min}
          max={max}
          step={step}
          disabled={readOnly}
          value={Number(c[key] ?? 0)}
          onChange={(e) => set({ [key]: Number(e.target.value) })}
        />
        <span className="mono faint">{Number(c[key] ?? 0).toFixed(2)}</span>
      </div>
    </label>
  );

  const nodeIssues = issues.filter((i) => i.node_id === node.id);
  const mcpSelected: string[] = c.mcp_tools ?? c.tools ?? [];
  const guardSelected: string[] = c.guardrails ?? [];

  async function synthesizeAll() {
    setBusy('synthesize');
    try {
      const live = { ...draft, nodes: draft.nodes.map((n) => (n.id === node!.id ? node! : n)) };
      const r = await api<{
        description?: string;
        instructions?: string;
        role?: string;
      }>('/agent-studio/synthesize', {
        method: 'POST',
        json: { graph_id: graphId, node_id: node!.id, draft: live, fields: ['description', 'instructions'] },
      });
      const patch: Record<string, unknown> = {};
      if (r.description !== undefined) patch.description = r.description;
      if (r.instructions !== undefined) patch.instructions = r.instructions;
      if (r.role && !c.role) patch.role = r.role;
      // Drop legacy tagline if present on older drafts.
      if (c.tagline) patch.tagline = '';
      set(patch);
      toast('Synthesized description and instructions');
    } catch (e: any) {
      toast(e.message, true);
    } finally {
      setBusy(null);
    }
  }

  async function saveSettings() {
    setBusy('save');
    try {
      await onSave();
      toast('Agent settings saved');
    } catch (e: any) {
      toast(e.message, true);
    } finally {
      setBusy(null);
    }
  }

  async function runAgent() {
    if (!projectId) return toast('Pick a project in the top bar first.', true);
    setBusy('run');
    try {
      await onSave();
      const live = { ...draft, nodes: draft.nodes.map((n) => (n.id === node!.id ? node! : n)) };
      const r = await api<RunResult>('/agent-studio/run', {
        method: 'POST',
        json: { graph_id: graphId, node_id: node!.id, project_id: projectId, draft: live },
      });
      setRunResult(r);
      toast(`Ran ${node!.name}`);
    } catch (e: any) {
      toast(e.message, true);
    } finally {
      setBusy(null);
    }
  }

  async function exportOutput(format: 'docx' | 'pdf' | 'txt') {
    if (!runResult?.artifact_id && !runResult?.output_text) {
      return toast('Run the agent first to produce output.', true);
    }
    setBusy(`export-${format}`);
    try {
      if (format === 'txt') {
        const blob = new Blob([runResult.output_text || ''], { type: 'text/plain;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${node!.name.replace(/\s+/g, '_')}.txt`;
        a.click();
        URL.revokeObjectURL(url);
        toast('Saved as text file');
      } else if (runResult.artifact_id) {
        await download(`/artifacts/${runResult.artifact_id}/export?format=${format}`, `${node!.name.replace(/\s+/g, '_')}.${format}`);
        toast(`Exported ${format.toUpperCase()}`);
      } else {
        toast('DOCX/PDF export needs a project-backed run artifact.', true);
      }
    } catch (e: any) {
      toast(e.message, true);
    } finally {
      setBusy(null);
    }
  }

  async function publish(mode: 'single' | 'append') {
    if (!projectId) return toast('Pick a project in the top bar first.', true);
    if (!runResult?.output_text) return toast('Run the agent first.', true);
    setBusy(`publish-${mode}`);
    try {
      const r = await api<{ version: number; sections: number }>('/agent-studio/publish', {
        method: 'POST',
        json: {
          project_id: projectId,
          mode,
          agent_name: node!.name,
          title: `${node!.name} portal pack`,
          body: runResult.output_text,
          node_id: node!.id,
          graph_id: graphId,
        },
      });
      toast(mode === 'append' ? `Appended to portal pack v${r.version} (${r.sections} sections)` : `Published to portal pack v${r.version}`);
    } catch (e: any) {
      toast(e.message, true);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="stack">
      <h3 style={{ fontSize: 15, color: NODE_META[node.type].color }}>{NODE_META[node.type].label}</h3>
      <label className="field">Name<input id="node-name" value={node.name} disabled={readOnly} onChange={(e) => onNode({ ...node, name: e.target.value })} /></label>

      {node.type === 'agent' && (
        <>
          <div className="inspector-section">
            <h4>Agent identity</h4>
            {select('template', 'Agent template', [...AGENT_TEMPLATES])}
            <label className="field">Role
              <input id="cfg-role" value={c.role ?? ''} disabled={readOnly} onChange={(e) => set({ role: e.target.value })} placeholder="e.g. Extract requirements and clarifications" />
            </label>
            <label className="field">Description
              <textarea id="cfg-description" rows={3} value={c.description ?? ''} disabled={readOnly} onChange={(e) => set({ description: e.target.value })} placeholder="What this agent does in the journey — or use Synthesize all" />
            </label>
            <label className="field" style={{ marginTop: 8 }}>Instructions override (bounded prompt, optional)
              <textarea id="cfg-instructions" rows={3} value={c.instructions ?? ''} disabled={readOnly} onChange={(e) => set({ instructions: e.target.value })} placeholder="Optional bounded prompt — or use Synthesize all" />
            </label>
            <div className="agent-actions" style={{ marginTop: 8 }}>
              <button className="btn primary" disabled={readOnly || !!busy} onClick={synthesizeAll}>
                {busy === 'synthesize' ? 'Synthesizing…' : 'Synthesize all'}
              </button>
            </div>
          </div>

          <div className="inspector-section">
            <h4>LLM parameters</h4>
            {select('model_profile', 'LLM model', MODEL_PROFILES)}
            {slider('temperature', 'Temperature', 0, 2, 0.05)}
            {slider('frequency_penalty', 'Frequency penalty', 0, 2, 0.05)}
            {slider('presence_penalty', 'Presence penalty', 0, 2, 0.05)}
          </div>

          <div className="inspector-section">
            <h4>Guardrails</h4>
            <ChipList
              options={guardrailOpts}
              selected={guardSelected}
              disabled={readOnly}
              onToggle={(id, on) => set({
                guardrails: on ? [...guardSelected, id] : guardSelected.filter((x) => x !== id),
              })}
            />
          </div>

          <div className="inspector-section">
            <h4>MCP tools</h4>
            <ChipList
              options={mcpOpts.length ? mcpOpts : tools.map((t) => t.id)}
              selected={mcpSelected}
              disabled={readOnly}
              onToggle={(id, on) => {
                const next = on ? [...mcpSelected, id] : mcpSelected.filter((x) => x !== id);
                set({ mcp_tools: next, tools: next });
              }}
            />
            <div className="form" style={{ marginTop: 8 }}>
              {text('input_schema', 'Input schema')}
              {text('output_schema', 'Output schema')}
              {text('retry', 'Retries', 'number')}
              {text('timeout_s', 'Timeout (s)', 'number')}
            </div>
            {runtime === 'AutoGen' && select('team_pattern', 'AutoGen team pattern', ['single', 'author_reviewer'], { single: 'Single AssistantAgent', author_reviewer: 'Author + reviewer (RoundRobinGroupChat)' })}
            <label className="row" style={{ fontSize: 12.5 }}><input type="checkbox" disabled={readOnly} checked={!!c.fail_simulation} onChange={(e) => set({ fail_simulation: e.target.checked })} /> Simulate a transient failure</label>
          </div>

          <div className="inspector-section">
            <h4>Actions</h4>
            <div className="agent-actions">
              <button className="btn primary" disabled={readOnly || !!busy} onClick={saveSettings}>Save agent settings</button>
              <button className="btn primary" disabled={readOnly || !!busy} onClick={runAgent}>{busy === 'run' ? 'Running…' : 'Run agent'}</button>
              <button className="btn" disabled={!!busy || !runResult} onClick={() => exportOutput('docx')}>Word</button>
              <button className="btn" disabled={!!busy || !runResult} onClick={() => exportOutput('pdf')}>PDF</button>
              <button className="btn" disabled={!!busy || !runResult} onClick={() => exportOutput('txt')}>Text</button>
            </div>
            <div className="agent-actions" style={{ marginTop: 8 }}>
              <button className="btn" disabled={!!busy || !runResult} onClick={() => publish('single')}>Publish (this agent)</button>
              <button className="btn" disabled={!!busy || !runResult} onClick={() => publish('append')}>Append to portal pack</button>
            </div>
          </div>

          {runResult && (
            <div className="inspector-section">
              <h4>Output {runResult.simulated ? <span className="pill warn">simulated</span> : null}</h4>
              {(runResult.inputs_from?.length ?? 0) > 0 && (
                <div className="rec-card" style={{ marginBottom: 10 }}>
                  <div className="row"><span className="pill acc">Chain input</span><b>Enriched from prior agents</b></div>
                  <ul style={{ margin: '6px 0 0', paddingLeft: 18, fontSize: 12.5 }}>
                    {runResult.inputs_from!.map((i) => (
                      <li key={i.node_id}>
                        <button className="btn ghost" style={{ padding: 0, height: 'auto' }} onClick={() => onSelectNode(i.node_id)}>
                          {i.name}
                        </button>
                        {' — '}{i.summary || i.template}
                        {i.simulated ? ' (auto-simulated)' : ''}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              <pre className="code agent-output">{runResult.output_text}</pre>
            </div>
          )}
        </>
      )}

      {node.type === 'tool' && (
        <>
          {select('tool_id', 'Connector', tools.map((t) => t.id))}
          {text('operation', 'Operation')}{text('credential_ref', 'Credential reference (vault://…)')}
          <div className="form">{text('timeout_s', 'Timeout (s)', 'number')}{text('retry', 'Retries', 'number')}</div>
          <label className="row" style={{ fontSize: 12.5 }}><input type="checkbox" disabled={readOnly} checked={!!c.fail_simulation} onChange={(e) => set({ fail_simulation: e.target.checked })} /> Simulate a transient failure</label>
        </>
      )}
      {node.type === 'decision' && <>{text('rule', 'Rule (e.g. open_clarifications > 0)')}{text('sim_outcome', 'Simulation outcome (auto or a branch label)')}</>}
      {node.type === 'approval' && <>{select('approver_role', 'Approver role', Object.keys(ROLE_LABELS), ROLE_LABELS)}{text('sla_hours', 'SLA (hours)', 'number')}{text('evidence', 'Evidence required')}</>}
      {node.type === 'data' && <>{text('knowledge_base', 'Knowledge base')}{select('retrieval', 'Retrieval', ['hybrid', 'vector', 'keyword'])}{select('access_filter', 'Access filter', ['tenant+project', 'project', 'tenant'])}{text('top_k', 'Top K', 'number')}</>}
      {node.type === 'calc' && <>{select('formula', 'Formula', ['selling_price', 'cloud_scenarios'])}{text('rate_card_version', 'Rate card version')}{text('tax_rule', 'Tax rule')}</>}
      {node.type === 'start' && text('input_schema', 'Input schema')}
      {node.type === 'end' && text('output_schema', 'Output schema')}
      {nodeIssues.map((i, k) => <div key={k} className="issue"><span className={`pill ${i.severity === 'error' ? 'bad' : 'warn'}`}>{i.severity}</span> {i.message}</div>)}

      {node.type === 'agent' && (
        <div className="inspector-section">
          <h4>Path recommendation</h4>
          <div className="rec-card recommended" style={{ marginBottom: 8 }}>
            <div className="row">
              <span className="pill acc">Recommended</span>
              <b>{nextName}</b>
              <span className="faint mono">{nextTpl === 'end' ? 'end' : 'agent'}</span>
            </div>
            <p className="muted" style={{ margin: '6px 0 0', fontSize: 12.5 }}>
              {outboundOk
                ? `Next step on the journey: ${nextName}. Follow to continue, or skip to End.`
                : `Follow wires Start → ${node.name} → ${nextName}${nextTpl === 'end' ? '' : ' → End'}. Skip bypasses ${nextName} and goes to End.`}
            </p>
            {agentPathHints.map((h) => (
              <div key={h} className="issue" style={{ marginTop: 6 }}>
                <span className="pill bad">error</span> {h}
              </div>
            ))}
            <div className="agent-actions" style={{ marginTop: 8 }}>
              <button
                className="btn primary"
                disabled={readOnly || !!busy}
                onClick={async () => {
                  const wired = recommendedOutboundId(draft, node.id);
                  if (wired && outboundOk) {
                    onSelectNode(wired);
                    toast(`Following recommended path → ${nextName}`);
                    return;
                  }
                  setBusy('follow');
                  try {
                    await onApplyRecommendedPath(node.id, 'follow');
                  } finally {
                    setBusy(null);
                  }
                }}
              >
                {busy === 'follow' ? 'Connecting…' : 'Follow recommended'}
              </button>
              <button
                className="btn"
                disabled={readOnly || !!busy || nextTpl === 'end'}
                onClick={async () => {
                  const endId = endNodeId(draft);
                  if (outboundOk && endId && draft.edges.some((e) => e.source === node.id && e.target === endId)) {
                    onSelectNode(endId);
                    toast(`Skipped ${nextName} → End`);
                    return;
                  }
                  setBusy('skip');
                  try {
                    await onApplyRecommendedPath(node.id, 'skip');
                  } finally {
                    setBusy(null);
                  }
                }}
              >
                {busy === 'skip' ? 'Skipping…' : `Skip ${nextName}`}
              </button>
            </div>
          </div>
        </div>
      )}

      <button className="btn danger" disabled={readOnly} onClick={onDelete}>Delete node</button>
    </div>
  );
}
