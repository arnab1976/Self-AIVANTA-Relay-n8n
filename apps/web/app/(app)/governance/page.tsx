'use client';

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import { ROLE_LABELS, when } from '@/lib/format';
import { useSession } from '@/lib/session';
import { Card, PageHeader, Pill, toast } from '@/components/ui';

export default function Governance() {
  const { can } = useSession();
  const [uat, setUat] = useState<any[]>([]);
  const [audit, setAudit] = useState<any>(null);
  const [rbac, setRbac] = useState<any>(null);
  const [graphs, setGraphs] = useState<any[]>([]);
  const load = () => {
    api<any[]>('/governance/uat').then(setUat);
    api('/audit?limit=100').then(setAudit);
    api('/governance/rbac').then(setRbac);
    api<any[]>('/graphs').then(setGraphs);
  };
  useEffect(load, []);
  const promote = (g: any, v: any) => api(`/graphs/${g.id}/versions/${v.version}/promote`, { method: 'POST' }).then(() => { toast(`${g.name} v${v.version} promoted`); load(); }).catch((e) => toast(e.message, true));
  return (
    <>
      <PageHeader title="Governance & UAT" sub="Definition of Done evaluated from this tenant's data, environment promotion, RBAC and the hash-chained audit trail." />
      <div className="grid g2">
        <Card title={`Definition of Done · ${uat.filter((c) => c.met).length}/${uat.length} met`}>
          {uat.map((c) => <div key={c.id} className="split"><span>{c.criterion}<div className="faint" style={{ fontSize: 12 }}>{c.evidence}</div></span><Pill tone={c.met ? 'good' : 'warn'}>{c.met ? 'met' : 'open'}</Pill></div>)}
        </Card>
        <Card title="Environment promotion (dev → staging → prod)">
          {graphs.flatMap((g) => g.versions.map((v: any) => (
            <div key={`${g.id}-${v.version}`} className="split">
              <span>{g.name} v{v.version} <span className="faint mono">{v.content_hash}</span></span>
              <span className="row"><Pill>{v.environment}</Pill>{v.environment !== 'prod' && <button className="btn" disabled={!can('graph:promote')} onClick={() => promote(g, v)}>Promote</button>}</span>
            </div>
          )))}
          <p className="faint" style={{ fontSize: 12 }}>Prod requires a passing validation under current policy and a succeeded run of that version.</p>
        </Card>
      </div>
      {rbac && (
        <Card title="Role permissions" className="mt">
          <div className="tbl"><table><thead><tr><th>Permission</th>{Object.keys(rbac.roles).map((r) => <th key={r} title={ROLE_LABELS[r]}>{r}</th>)}</tr></thead><tbody>
            {Object.entries(rbac.permissions).map(([perm, roles]: [string, any]) => <tr key={perm}><td className="mono">{perm}</td>{Object.keys(rbac.roles).map((r) => <td key={r}>{roles.includes(r) ? '●' : ''}</td>)}</tr>)}
          </tbody></table></div>
        </Card>
      )}
      {audit && (
        <Card title="Audit trail" actions={<Pill tone={audit.chain.valid ? 'good' : 'bad'}>{audit.chain.valid ? `chain valid · ${audit.chain.checked} events` : 'chain broken'}</Pill>} className="mt">
          <div className="tbl"><table><thead><tr><th>Time</th><th>Actor</th><th>Action</th><th>Entity</th><th>Hash ← prev</th></tr></thead><tbody>
            {audit.events.map((e: any) => <tr key={e.id}><td>{when(e.ts)}</td><td>{e.actor} <span className="faint">{e.role}</span></td><td>{e.action}</td><td>{e.entity}</td><td className="mono" style={{ fontSize: 11 }}>{e.hash} ← {e.prev_hash}</td></tr>)}
          </tbody></table></div>
        </Card>
      )}
    </>
  );
}
