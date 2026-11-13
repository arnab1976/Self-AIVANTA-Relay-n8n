'use client';

import { useEffect, useState } from 'react';
import { api, download } from '@/lib/api';
import { when } from '@/lib/format';
import { useSession } from '@/lib/session';
import { Card, Empty, PageHeader, Pill, toast } from '@/components/ui';

export default function Artifacts() {
  const { projectId, can } = useSession();
  const [rows, setRows] = useState<any[]>([]);
  const [sel, setSel] = useState<any>(null);
  const load = () => projectId && api<any[]>(`/artifacts?project_id=${projectId}`).then(setRows);
  useEffect(() => { load(); setSel(null); }, [projectId]); // eslint-disable-line react-hooks/exhaustive-deps
  const open = (id: string) => api(`/artifacts/${id}`).then(setSel);
  return (
    <>
      <PageHeader title="Artifacts & Documents" sub="Versioned outputs with source IDs, reviewer, approval state and storage URI. Exports include version, assumptions, review status and evidence." />
      <div className="grid g2">
        <div className="tbl"><table><thead><tr><th>Artifact</th><th>Version</th><th>State</th><th>Produced</th></tr></thead><tbody>
          {rows.map((a) => <tr key={a.id} className={`click ${sel?.id === a.id ? 'sel' : ''}`} onClick={() => open(a.id)}><td>{a.type}</td><td className="mono">v{a.version} · {a.graph_version}</td><td><Pill>{a.approval_state}</Pill></td><td>{when(a.created_at)}</td></tr>)}
          {rows.length === 0 && <tr><td colSpan={4}><Empty>No artifacts yet. Run a canvas on this project.</Empty></td></tr>}
        </tbody></table></div>
        {sel && (
          <Card title={`${sel.type} v${sel.version}`} actions={<>
            {['docx', 'pdf', 'xlsx'].map((f) => <button key={f} className="btn" onClick={() => download(`/artifacts/${sel.id}/export?format=${f}`, `${sel.type}_v${sel.version}.${f}`)}>{f.toUpperCase()}</button>)}
            {can('artifact:review') && sel.approval_state === 'in_review' && <button className="btn primary" onClick={() => api(`/artifacts/${sel.id}/review`, { method: 'POST', json: { decision: 'approved' } }).then(() => { toast('Artifact approved'); open(sel.id); load(); })}>Approve</button>}
          </>}>
            <div className="split"><span>Sources</span><b style={{ fontSize: 12 }}>{sel.source_ids.slice(0, 4).join(' · ')}</b></div>
            <div className="split"><span>Reviewer</span><b>{sel.reviewer_role}</b></div>
            <div className="split"><span>Storage</span><b className="mono" style={{ fontSize: 11 }}>{sel.storage_uri}</b></div>
            <pre className="code" style={{ marginTop: 10 }}>{JSON.stringify(sel.content, null, 2)}</pre>
          </Card>
        )}
      </div>
    </>
  );
}
