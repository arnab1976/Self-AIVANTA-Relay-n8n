'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import { when } from '@/lib/format';
import { PageHeader, Pill } from '@/components/ui';

export default function Runs() {
  const [runs, setRuns] = useState<any[]>([]);
  useEffect(() => {
    const load = () => api<any[]>('/runs').then(setRuns);
    load();
    const t = setInterval(load, 4000);
    return () => clearInterval(t);
  }, []);
  return (
    <>
      <PageHeader title="Runs & Observability" sub="Run state is persisted independently from design state: node states, timeline, tokens, cost and trace IDs." />
      <div className="tbl"><table><thead><tr><th>Run</th><th>Graph version</th><th>Runtime</th><th>Status</th><th className="r">Tokens</th><th className="r">Cost</th><th>Started</th><th>By</th></tr></thead><tbody>
        {runs.map((r) => (
          <tr key={r.id}>
            <td className="mono"><Link href={`/runs/${r.id}`}>{r.id.slice(0, 12)}</Link></td><td>{r.graph_version} · {r.mode}</td><td>{r.runtime}</td>
            <td><Pill>{r.status}</Pill></td><td className="r">{r.tokens.toLocaleString()}</td><td className="r">{r.cost.toFixed(2)}</td><td>{when(r.started_at)}</td><td>{r.started_by}</td>
          </tr>
        ))}
      </tbody></table></div>
    </>
  );
}
