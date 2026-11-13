'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import { money, when } from '@/lib/format';
import { useSession } from '@/lib/session';
import { Card, Kpi, PageHeader, Pill } from '@/components/ui';

export default function Dashboard() {
  const { session, meta } = useSession();
  const [runs, setRuns] = useState<any[]>([]);
  const [graphs, setGraphs] = useState<any[]>([]);
  const [approvals, setApprovals] = useState<any[]>([]);
  const [tenant, setTenant] = useState<any>(null);
  useEffect(() => {
    api<any[]>('/runs').then(setRuns);
    api<any[]>('/graphs').then(setGraphs);
    api<any[]>('/approvals?status=Pending').then(setApprovals);
    api('/tenants/current').then(setTenant);
  }, []);
  const ok = runs.filter((r) => r.status === 'succeeded').length;
  const failed = runs.filter((r) => r.status === 'failed').length;
  const cost = runs.reduce((a, r) => a + (r.cost || 0), 0);
  return (
    <>
      <PageHeader title="Command Center" sub={`${session?.tenant.name} · ${meta?.product ?? ''} on ${meta?.runtime ?? ''}`}
        actions={<Link className="btn primary" href="/canvas">Open Agent Canvas</Link>} />
      <div className="grid g4" style={{ marginBottom: 14 }}>
        <Kpi label="Canvases · published versions" value={`${graphs.length} · ${graphs.reduce((a, g) => a + g.versions.length, 0)}`} />
        <Kpi label="Runs · success rate" value={`${runs.length} · ${ok + failed ? Math.round((ok / (ok + failed)) * 100) : 0}%`} note={`${failed} failed`} />
        <Kpi label="Pending approvals" value={approvals.length} />
        <Kpi label="Model spend" value={money(cost, tenant?.currency)} note={`${runs.reduce((a, r) => a + r.tokens, 0).toLocaleString()} tokens`} />
      </div>
      <Card title="Recent runs" actions={<Link className="btn" href="/runs">All runs</Link>}>
        <div className="tbl"><table><thead><tr><th>Run</th><th>Version</th><th>Status</th><th className="r">Tokens</th><th>Started</th></tr></thead><tbody>
          {runs.slice(0, 8).map((r) => (
            <tr key={r.id} className="click" onClick={() => (window.location.href = `/runs/${r.id}`)}>
              <td className="mono">{r.id.slice(0, 10)}</td><td>{r.graph_version} · {r.mode}</td><td><Pill>{r.status}</Pill></td><td className="r">{r.tokens.toLocaleString()}</td><td>{when(r.started_at)}</td>
            </tr>
          ))}
        </tbody></table></div>
      </Card>
    </>
  );
}
