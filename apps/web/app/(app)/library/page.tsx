'use client';

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import { useSession } from '@/lib/session';
import { Card, PageHeader, Pill, toast } from '@/components/ui';

export default function Library() {
  const { can } = useSession();
  const [agents, setAgents] = useState<any[]>([]);
  const [tools, setTools] = useState<any[]>([]);
  const [sel, setSel] = useState<any>(null);
  const [draft, setDraft] = useState('');
  const load = () => { api<any[]>('/agents').then(setAgents); api<any[]>('/tools').then(setTools); };
  useEffect(load, []);
  useEffect(() => { if (sel) setDraft(sel.tenant_instructions); }, [sel]);

  return (
    <>
      <PageHeader title="Agents & Tools" sub="Controlled agent templates (versioned instructions, model profile, tools, policies) and the MCP tool registry with per-tenant approval." />
      <div className="grid g2">
        <div className="tbl"><table><thead><tr><th>Agent</th><th>Outputs</th><th>Version</th><th className="r">Used in</th></tr></thead><tbody>
          {agents.map((a) => <tr key={a.id} className={`click ${sel?.id === a.id ? 'sel' : ''}`} onClick={() => setSel(a)}><td><b>{a.name}</b><div className="faint mono" style={{ fontSize: 11 }}>{a.id}</div></td><td>{a.outputs}</td><td className="mono">v{a.tenant_version}</td><td className="r">{a.used_in_canvases}</td></tr>)}
        </tbody></table></div>
        {sel && (
          <Card title={`${sel.name} · v${sel.tenant_version}`}>
            <p className="muted">{sel.role}</p>
            <div className="split"><span>Schemas</span><b className="mono">{sel.input_schema} → {sel.output_schema}</b></div>
            <div className="split"><span>Default model</span><b>{sel.default_model}</b></div>
            <div className="split"><span>Tools</span><b className="mono">{sel.tools.join(', ') || 'none'}</b></div>
            <label className="field" style={{ marginTop: 8 }}>Instructions<textarea id="agent-instr" rows={8} value={draft} disabled={!can('agent:edit')} onChange={(e) => setDraft(e.target.value)} /></label>
            <button className="btn primary" disabled={!can('agent:edit')} onClick={() => api<any>(`/agents/${sel.id}/versions`, { method: 'POST', json: { instructions: draft } })
              .then((r) => { toast(`${sel.name} saved as v${r.version}`); load(); }).catch((e) => toast(e.message, true))}>Save new version</button>
            {sel.test_cases.map((t: string) => <div key={t} className="split"><span>{t}</span><Pill tone="good">test</Pill></div>)}
          </Card>
        )}
      </div>
      <Card title="Tool & MCP registry" className="mt">
        <div className="tbl"><table><thead><tr><th>Tool</th><th>Kind</th><th>Endpoint</th><th>Scopes</th><th>Credential</th><th>External</th><th>Approved</th></tr></thead><tbody>
          {tools.map((t) => (
            <tr key={t.id}>
              <td className="mono">{t.id}</td><td>{t.kind}</td><td className="mono" style={{ fontSize: 12 }}>{t.endpoint}</td><td style={{ fontSize: 12 }}>{t.scopes.join(', ')}</td>
              <td className="mono" style={{ fontSize: 12 }}>{t.credential_ref}</td><td>{t.external ? <Pill tone="warn">yes</Pill> : 'no'}</td>
              <td><input type="checkbox" checked={t.approved} disabled={!can('tool:approve')} aria-label={`Approve ${t.id}`}
                onChange={(e) => api(`/tools/${t.id}`, { method: 'PATCH', json: { approved: e.target.checked } }).then(load).catch((err) => toast(err.message, true))} /></td>
            </tr>
          ))}
        </tbody></table></div>
      </Card>
    </>
  );
}
