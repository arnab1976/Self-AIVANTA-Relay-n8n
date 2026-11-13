'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import { when } from '@/lib/format';
import { useSession } from '@/lib/session';
import { Card, Empty, PageHeader, Pill, toast } from '@/components/ui';

export default function Approvals() {
  const { session } = useSession();
  const [rows, setRows] = useState<any[]>([]);
  const [comments, setComments] = useState<Record<string, string>>({});
  const load = () => api<any[]>('/approvals').then(setRows);
  useEffect(() => { load(); }, []);
  async function decide(a: any, decision: string) {
    try {
      await api(`/approvals/${a.id}/decide`, { method: 'POST', json: { decision, comment: comments[a.id] ?? '' } });
      toast(`${a.kind}: ${decision}`);
      load();
    } catch (e: any) { toast(e.message, true); }
  }
  const pending = rows.filter((a) => a.status === 'Pending');
  return (
    <>
      <PageHeader title="Approvals" sub="External emails, staffing commitments, pricing approvals and final SOW sign-off require explicit human authorization by the designated role." />
      <div className="grid g2">
        {pending.length === 0 && <Empty>No pending approvals.</Empty>}
        {pending.map((a) => {
          const mine = session?.user.roles.includes(a.approver_role);
          return (
            <Card key={a.id} title={a.kind} actions={<Pill>Pending</Pill>}>
              <div className="split"><span>Approver</span><b>{a.approver_label}</b></div>
              <div className="split"><span>Evidence</span><b>{a.evidence}</b></div>
              <div className="split"><span>Requested</span><b>{when(a.requested_at)} by {a.requested_by}</b></div>
              {a.run_id && <div className="split"><span>Run</span><Link href={`/runs/${a.run_id}`}>{a.run_id.slice(0, 12)}</Link></div>}
              <input id={`c-${a.id}`} style={{ width: '100%', margin: '8px 0' }} placeholder="Comment for the audit record" disabled={!mine}
                value={comments[a.id] ?? ''} onChange={(e) => setComments({ ...comments, [a.id]: e.target.value })} />
              <div className="row">
                <button className="btn primary" disabled={!mine} onClick={() => decide(a, 'Approved')}>Approve</button>
                <button className="btn danger" disabled={!mine} onClick={() => decide(a, 'Rejected')}>Reject</button>
                {!mine && <span className="faint">Only {a.approver_label} can decide.</span>}
              </div>
            </Card>
          );
        })}
      </div>
      <Card title="Decision history" className="mt">
        <div className="tbl"><table><thead><tr><th>Request</th><th>Decision</th><th>By</th><th>When</th><th>Comment</th></tr></thead><tbody>
          {rows.filter((a) => a.status !== 'Pending').map((a) => <tr key={a.id}><td>{a.kind}</td><td><Pill>{a.status}</Pill></td><td>{a.decided_by}</td><td>{when(a.decided_at)}</td><td>{a.comment}</td></tr>)}
        </tbody></table></div>
      </Card>
    </>
  );
}
