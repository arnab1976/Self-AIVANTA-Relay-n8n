'use client';

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import { money } from '@/lib/format';
import { useSession } from '@/lib/session';
import { Card, PageHeader, Pill, toast } from '@/components/ui';

const ROLES = ['Solution Architect', 'Frontend Engineer', 'Python / AI Engineer', 'Platform Engineer', 'QA Engineer', 'Business Analyst', 'Security Reviewer', 'Project Manager'];

export default function Estimate() {
  const { projectId, can } = useSession();
  const [project, setProject] = useState<any>(null);
  const [tenant, setTenant] = useState<any>(null);
  const [inputs, setInputs] = useState<any>(null);
  const [res, setRes] = useState<any>(null);
  const [cloud, setCloud] = useState<any>(null);
  const [example, setExample] = useState<any>(null);
  const [history, setHistory] = useState<any[]>([]);

  useEffect(() => {
    api('/tenants/current').then(setTenant);
    api('/pricing/blueprint-example').then(setExample);
  }, []);
  useEffect(() => {
    if (!projectId) return;
    api<any>(`/projects/${projectId}`).then((p) => { setProject(p); setInputs(p.estimate_inputs); });
    api<any[]>(`/projects/${projectId}/estimates`).then(setHistory);
  }, [projectId]);
  useEffect(() => {
    if (!projectId || !inputs) return;
    const t = setTimeout(() => api(`/projects/${projectId}/estimates/preview`, { method: 'POST', json: { inputs } }).then(setRes).catch((e) => toast(e.message, true)), 250);
    return () => clearTimeout(t);
  }, [inputs, projectId]);
  useEffect(() => {
    if (project?.workload) api('/finops/compare', { method: 'POST', json: { workload: project.workload } }).then(setCloud);
  }, [project]);

  if (!inputs || !tenant) return null;
  const cur = tenant.currency;
  const r = res?.result;
  const set = (k: string, v: unknown) => setInputs({ ...inputs, [k]: v });
  const setLine = (i: number, k: string, v: unknown) => set('role_lines', inputs.role_lines.map((l: any, j: number) => (j === i ? { ...l, [k]: v } : l)));
  const editable = can('estimate:write');

  async function saveVersion() {
    try {
      const out = await api<any>(`/projects/${projectId}/estimates`, { method: 'POST', json: { inputs } });
      toast(`Estimate v${out.version} saved${out.flags.length ? ` · ${out.flags.length} flags` : ''}`);
      api<any[]>(`/projects/${projectId}/estimates`).then(setHistory);
    } catch (e: any) { toast(e.message, true); }
  }

  return (
    <>
      <PageHeader title="Estimation, Pricing & FinOps" sub="person-months = FTE × months · delivery cost = labor + cloud + licenses + travel + overhead + contingency · price = cost ÷ (1 − margin). Computed by the deterministic engine, never by an LLM."
        actions={<button className="btn primary" disabled={!editable} onClick={saveVersion}>Save estimate version</button>} />
      <div className="grid g4" style={{ marginBottom: 14 }}>
        <div className="card kpi"><small>Person-months</small><b>{Number(r?.person_months ?? 0).toFixed(1)}</b></div>
        <div className="card kpi"><small>Delivery cost</small><b>{money(r?.delivery_cost, cur)}</b></div>
        <div className="card kpi"><small>Selling price (base)</small><b>{money(r?.selling_price, cur)}</b></div>
        <div className="card kpi"><small>Effective margin</small><b>{r?.effective_margin_pct}%</b><span className="muted">floor {tenant.margin_floor_pct}% · {tenant.rate_card_version}</span></div>
      </div>
      {res?.flags?.length > 0 && <Card title="Checks">{res.flags.map((f: any, i: number) => <div key={i} className="row"><Pill tone={f.severity === 'blocker' ? 'bad' : 'warn'}>{f.code}</Pill> {f.message}</div>)}</Card>}
      <div className="grid g2" style={{ marginTop: 14 }}>
        <Card title="Role lines">
          <div className="tbl"><table><thead><tr><th>Role</th><th className="r">FTE</th><th className="r">Months</th><th className="r">Rate</th></tr></thead><tbody>
            {inputs.role_lines.map((l: any, i: number) => (
              <tr key={i}>
                <td><select id={`r-${i}`} value={l.role} disabled={!editable} onChange={(e) => setLine(i, 'role', e.target.value)}>{ROLES.map((x) => <option key={x}>{x}</option>)}</select></td>
                <td className="r"><input id={`f-${i}`} type="number" step="0.25" style={{ width: 80 }} value={l.fte} disabled={!editable} onChange={(e) => setLine(i, 'fte', Number(e.target.value))} /></td>
                <td className="r"><input id={`m-${i}`} type="number" step="0.5" style={{ width: 80 }} value={l.months} disabled={!editable} onChange={(e) => setLine(i, 'months', Number(e.target.value))} /></td>
                <td className="r">{money(tenant.rate_card[l.role], cur)}</td>
              </tr>
            ))}
          </tbody></table></div>
          <div className="row" style={{ marginTop: 8 }}><button className="btn" disabled={!editable} onClick={() => set('role_lines', [...inputs.role_lines, { role: 'Frontend Engineer', fte: 1, months: 1 }])}>Add line</button></div>
          <div className="form" style={{ marginTop: 10 }}>
            {[['target_margin_pct', 'Target margin %'], ['discount_pct', 'Discount %'], ['overhead_pct', 'Overhead %'], ['contingency_pct', 'Contingency %'], ['licenses', 'Licenses'], ['travel', 'Travel']].map(([k, label]) => (
              <label key={k} className="field">{label}<input id={`in-${k}`} type="number" value={inputs[k] ?? 0} disabled={!editable} onChange={(e) => set(k, Number(e.target.value))} /></label>
            ))}
            <label className="field">Cloud provider<select id="in-provider" value={inputs.provider ?? 'azure'} disabled={!editable} onChange={(e) => set('provider', e.target.value)}>{['aws', 'gcp', 'azure'].map((x) => <option key={x}>{x}</option>)}</select></label>
          </div>
        </Card>
        <Card title="Low / base / high scenarios">
          <div className="tbl"><table><thead><tr><th></th>{['low', 'base', 'high'].map((s) => <th className="r" key={s}>{s}</th>)}</tr></thead><tbody>
            {['labor', 'cloud', 'delivery_cost', 'selling_price'].map((k) => <tr key={k}><td>{k.replace('_', ' ')}</td>{['low', 'base', 'high'].map((s) => <td className="r" key={s}>{money(res?.scenarios?.[s]?.[k], cur)}</td>)}</tr>)}
          </tbody></table></div>
          <p className="faint" style={{ fontSize: 12 }}>Low: effort −10%, cloud −20%. High: effort +15%, cloud +30%. Lines reconcile: {String(r?.reconciled)}.</p>
          {example && <div className="split"><span>Blueprint example (30 PM × ₹1,80,000 + ₹16,00,000 @ 30%)</span><b>{money(example.selling_price, 'INR')}</b></div>}
          <h3 style={{ fontSize: 14, marginTop: 12 }}>Estimate versions</h3>
          {history.map((h) => <div key={h.version} className="split"><span>v{h.version} · {h.created_by}</span><b>{money(h.selling_price, cur)} @ {h.margin_pct}%</b></div>)}
        </Card>
      </div>
      {cloud && (
        <Card title={`Cloud FinOps · snapshot ${cloud.snapshot_effective_date}${cloud.illustrative ? ' (illustrative prices)' : ''}`} className="mt">
          <div className="tbl"><table><thead><tr><th>Provider</th><th>Stack</th><th className="r">Low / month</th><th className="r">Base / month</th><th className="r">High / month</th></tr></thead><tbody>
            {Object.entries(cloud.providers).map(([k, v]: [string, any]) => <tr key={k}><td>{v.base.name}</td><td className="faint">{v.base.stack}</td>{['low', 'base', 'high'].map((s) => <td className="r" key={s}>{money(v[s].monthly, cur)}</td>)}</tr>)}
          </tbody></table></div>
          {tenant.price_snapshot_age_days > 30 && <div className="row" style={{ marginTop: 8 }}><Pill tone="warn">Snapshot {tenant.price_snapshot_age_days} days old</Pill>
            <button className="btn" onClick={() => api('/tenants/current', { method: 'PATCH', json: { refresh_price_snapshot: true } }).then(setTenant)}>Refresh snapshot</button></div>}
        </Card>
      )}
    </>
  );
}
