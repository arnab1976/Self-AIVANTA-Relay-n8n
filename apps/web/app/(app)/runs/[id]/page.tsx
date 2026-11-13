'use client';

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import { when } from '@/lib/format';
import { Card, PageHeader, Pill, toast } from '@/components/ui';

export default function RunDetail({ params }: { params: { id: string } }) {
  const [run, setRun] = useState<any>(null);
  const [events, setEvents] = useState<any[]>([]);
  const load = () => {
    api(`/runs/${params.id}`).then(setRun);
    api<any[]>(`/runs/${params.id}/events`).then(setEvents);
  };
  useEffect(() => { load(); const t = setInterval(load, 3000); return () => clearInterval(t); }, [params.id]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!run) return null;
  const act = (path: string, label: string) => api(`/runs/${run.id}/${path}`, { method: 'POST' }).then(() => { toast(label); load(); }).catch((e) => toast(e.message, true));
  const transcript = events.filter((e) => e.type === 'agent_message');
  return (
    <>
      <PageHeader title={`Run ${run.id.slice(0, 12)}`} sub={`${run.runtime} · ${run.graph_version} (${run.mode}) · trace ${run.trace_id} · idempotency ${run.idempotency_prefix.slice(0, 12)}`}
        actions={<>
          {run.status === 'failed' && <button className="btn primary" onClick={() => act('retry', 'Resuming from the last checkpoint')}>Resume from failure</button>}
          {['succeeded', 'failed', 'cancelled'].includes(run.status) && <button className="btn" onClick={() => act('replay', 'Replay started')}>Replay</button>}
          {['running', 'awaiting_approval', 'queued'].includes(run.status) && <button className="btn danger" onClick={() => act('cancel', 'Cancel requested')}>Cancel</button>}
        </>} />
      <div className="grid g4" style={{ marginBottom: 14 }}>
        <div className="card kpi"><small>Status</small><b><Pill>{run.status}</Pill></b></div>
        <div className="card kpi"><small>Tokens</small><b>{run.tokens.toLocaleString()}</b></div>
        <div className="card kpi"><small>Cost</small><b>{run.cost.toFixed(2)}</b></div>
        <div className="card kpi"><small>Started / ended</small><b style={{ fontSize: 14 }}>{when(run.started_at)}<br />{when(run.ended_at)}</b></div>
      </div>
      {run.runtime_ref && (
        <Card title="n8n execution" className="mt">
          <div className="split"><span>Workflow</span><b className="mono">{run.runtime_ref.workflow_name} · id {run.runtime_ref.workflow_id}</b></div>
          <div className="split"><span>Execution</span><b className="mono">{run.runtime_ref.execution_id ?? '—'} {(run.runtime_ref.executions ?? []).length > 1 ? `(${run.runtime_ref.executions.length} incl. retries)` : ''}</b></div>
          <div className="split"><span>Mode · agents</span><b>{run.runtime_ref.mode} · {run.runtime_ref.agent_mode}</b></div>
          {process.env.NEXT_PUBLIC_N8N_EDITOR_URL && run.runtime_ref.execution_id && run.runtime_ref.mode === 'rest' && (
            <a className="btn" style={{ marginTop: 8 }} target="_blank" rel="noreferrer"
              href={`${process.env.NEXT_PUBLIC_N8N_EDITOR_URL}/workflow/${run.runtime_ref.workflow_id}/executions/${run.runtime_ref.execution_id}`}>Open execution in n8n ↗</a>
          )}
        </Card>
      )}
      {run.error && <Card title="Error"><p style={{ color: 'var(--bad)' }}>{run.error}</p></Card>}
      <div className="grid g2" style={{ marginTop: 14 }}>
        <Card title="Node states">
          {run.nodes.map((n: any) => <div className="split" key={n.id}><span>{n.name} <span className="faint mono">{n.type}</span></span><Pill>{run.node_status?.[n.id] ?? 'pending'}</Pill></div>)}
        </Card>
        <Card title="Event timeline">
          <div className="code" style={{ whiteSpace: 'pre-wrap', maxHeight: 520 }}>
            {events.map((e) => `${e.ts.slice(11, 19)} ${e.type.padEnd(18)} ${e.node_id ?? ''} ${e.type === 'node_succeeded' ? `tokens=${e.data.tokens ?? 0} ${e.data.model ?? ''}` : e.type === 'route_selected' ? `→ ${e.data.label}` : e.data.error ?? ''}`).join('\n')}
          </div>
        </Card>
      </div>
      {transcript.length > 0 && (
        <Card title="Agent conversation" className="mt">
          {transcript.map((e) => <div key={e.id} className="split"><span className="mono">{e.data.source}</span><span style={{ flex: 1, marginLeft: 12 }}>{e.data.preview ?? `${e.data.model ?? ''} · ${e.data.tokens ?? 0} tokens`}</span></div>)}
        </Card>
      )}
    </>
  );
}
