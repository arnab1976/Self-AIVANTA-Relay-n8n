'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { API_URL } from '@/lib/api';
import { money } from '@/lib/format';
import { Card, Pill, toast } from '@/components/ui';

const KEY = 'aivanta.provider';

async function papi<T = any>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  let token = '';
  try { token = JSON.parse(window.localStorage.getItem(KEY) || '{}').token || ''; } catch { /* ignore */ }
  const headers: Record<string, string> = { Authorization: `Bearer ${token}` };
  let body = init.body;
  if (init.json !== undefined) { headers['Content-Type'] = 'application/json'; body = JSON.stringify(init.json); }
  const res = await fetch(`${API_URL}/api${path}`, { ...init, headers, body });
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).detail ?? msg; } catch { /* ignore */ }
    throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
  }
  return res.json();
}

export default function Provider() {
  const [signedIn, setSignedIn] = useState(false);
  const [name, setName] = useState('Platform Operations');
  const [data, setData] = useState<any>(null);
  const [reqs, setReqs] = useState<any[]>([]);
  const [tab, setTab] = useState('tenants');
  const [form, setForm] = useState({ code: '', name: '', plan: 'Growth', cloud: 'AWS', region: 'India (Mumbai)', currency: 'INR', admin_email: '' });

  const load = () => {
    papi('/provider/overview').then(setData).catch((e) => { toast(e.message, true); setSignedIn(false); });
    papi<any[]>('/provider/requests').then(setReqs).catch(() => null);
  };
  useEffect(() => {
    try { if (JSON.parse(window.localStorage.getItem(KEY) || '{}').token) { setSignedIn(true); load(); } } catch { /* ignore */ }
  }, []);

  async function signIn(e: React.FormEvent) {
    e.preventDefault();
    try {
      const r = await fetch(`${API_URL}/api/provider/dev-login`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }) });
      if (!r.ok) throw new Error((await r.json()).detail);
      window.localStorage.setItem(KEY, JSON.stringify(await r.json()));
      setSignedIn(true);
      load();
    } catch (err: any) { toast(err.message, true); }
  }
  const act = (p: Promise<any>, msg: string) => p.then(() => { toast(msg); load(); }).catch((e) => toast(e.message, true));

  if (!signedIn) {
    return (
      <main className="login">
        <form className="card stack" onSubmit={signIn}>
          <h1 style={{ fontSize: 24 }}>Provider Admin</h1>
          <p className="muted">For the team that runs AIVANTA Relay as a service: tenants, plans, regions, access requests, usage and n8n placement.
            In production provider staff sign in with the provider&apos;s identity provider (role <span className="mono">aivanta-provider</span>).</p>
          <label className="field">Name<input id="pv-name" value={name} onChange={(e) => setName(e.target.value)} /></label>
          <div className="row"><button className="btn primary" type="submit">Open provider console →</button><Link className="btn ghost" href="/">← Home</Link></div>
        </form>
      </main>
    );
  }
  if (!data) return <main className="main" />;
  const pending = reqs.filter((r) => r.status === 'Pending');
  return (
    <main className="main" style={{ maxWidth: 1240, margin: '0 auto' }}>
      <div className="ph"><div><h1>Provider Admin</h1><p className="sub">{data.runtime.framework} · {data.runtime.version}</p></div>
        <div className="row ph-actions"><Link className="btn ghost" href="/">Home</Link>
          <button className="btn" onClick={() => { window.localStorage.removeItem(KEY); setSignedIn(false); }}>Sign out</button></div></div>
      <div className="grid g4" style={{ marginBottom: 14 }}>
        <div className="card kpi"><small>Tenants</small><b>{data.tenants.length}</b></div>
        <div className="card kpi"><small>Active</small><b>{data.tenants.filter((t: any) => t.status === 'Active').length}</b></div>
        <div className="card kpi"><small>Runs (all tenants)</small><b>{data.tenants.reduce((a: number, t: any) => a + t.runs, 0)}</b></div>
        <div className="card kpi"><small>Pending organisation requests</small><b>{data.pending_org_requests}</b></div>
      </div>
      <Card title="Licence"><p className="muted">{data.licence.n8n}</p></Card>
      <div className="row" style={{ margin: '14px 0' }}>
        {[['tenants', 'Tenants'], ['requests', `Access requests (${pending.length})`], ['provision', 'Provision tenant'], ['plans', 'Plans']].map(([k, l]) => (
          <button key={k} className={`btn ${tab === k ? 'primary' : ''}`} onClick={() => setTab(k)}>{l}</button>))}
      </div>
      {tab === 'tenants' && (
        <div className="card"><table className="tbl"><thead><tr><th>Tenant</th><th>Plan</th><th>Cloud · region</th><th>Isolation · n8n</th><th>Users</th><th>Runs</th><th>Model cost</th><th>Status</th><th /></tr></thead>
          <tbody>{data.tenants.map((t: any) => (
            <tr key={t.id}><td><b>{t.name}</b> <span className="faint mono">{t.code}</span></td>
              <td><select value={t.plan} onChange={(e) => act(papi(`/provider/tenants/${t.id}`, { method: 'PATCH', json: { plan: e.target.value } }), 'Plan changed')}>
                {Object.keys(data.plans).map((p) => <option key={p}>{p}</option>)}</select></td>
              <td>{t.cloud} · {t.region}</td><td>{t.isolation_model} · {t.n8n_placement}</td><td>{t.users}</td><td>{t.runs}</td><td>{money(t.model_cost, t.currency)}</td>
              <td><Pill>{t.status}</Pill></td>
              <td><button className="btn" onClick={() => act(papi(`/provider/tenants/${t.id}`, { method: 'PATCH', json: { status: t.status === 'Active' ? 'Suspended' : 'Active' } }), 'Updated')}>{t.status === 'Active' ? 'Suspend' : 'Activate'}</button></td></tr>))}
          </tbody></table></div>
      )}
      {tab === 'requests' && (
        <div className="card"><table className="tbl"><thead><tr><th>Request</th><th>Requester</th><th>Details</th><th>Status</th><th /></tr></thead>
          <tbody>{reqs.map((r) => (
            <tr key={r.id}><td>{r.kind === 'new_org' ? 'New organisation' : 'Join tenant'}<br /><span className="faint">{r.created_at.slice(0, 16).replace('T', ' ')}</span></td>
              <td>{r.name}<br /><span className="faint">{r.email} · {r.organisation}</span></td>
              <td>{r.kind === 'new_org' ? `${r.details.plan} · ${r.details.cloud} · ${r.details.region}` : `${r.tenant?.name} as ${r.role_label} (tenant admin decides)`}<br /><span className="faint">{r.note}</span></td>
              <td><Pill>{r.status}</Pill></td>
              <td>{r.kind === 'new_org' && r.status === 'Pending' && (<div className="row">
                <button className="btn primary" onClick={() => act(papi(`/provider/requests/${r.id}/decide`, { method: 'POST', json: { decision: 'Approved' } }), `${r.organisation} provisioned`)}>Approve & provision</button>
                <button className="btn danger" onClick={() => act(papi(`/provider/requests/${r.id}/decide`, { method: 'POST', json: { decision: 'Rejected' } }), 'Rejected')}>Reject</button></div>)}</td></tr>))}
          </tbody></table></div>
      )}
      {tab === 'provision' && (
        <Card title="Provision a tenant">
          <div className="form">
            {(['code', 'name', 'admin_email', 'region'] as const).map((k) => <label key={k} className="field">{k.replace('_', ' ')}<input id={`pt-${k}`} value={form[k]} onChange={(e) => setForm({ ...form, [k]: e.target.value })} /></label>)}
            <label className="field">plan<select id="pt-plan" value={form.plan} onChange={(e) => setForm({ ...form, plan: e.target.value })}>{Object.keys(data.plans).map((p) => <option key={p}>{p}</option>)}</select></label>
            <label className="field">cloud<select id="pt-cloud" value={form.cloud} onChange={(e) => setForm({ ...form, cloud: e.target.value })}><option>AWS</option><option>Azure</option><option>GCP</option></select></label>
            <label className="field">currency<select id="pt-cur" value={form.currency} onChange={(e) => setForm({ ...form, currency: e.target.value })}><option>INR</option><option>USD</option></select></label>
          </div>
          <button className="btn primary" style={{ marginTop: 10 }} onClick={() => act(papi('/provider/tenants', { method: 'POST', json: form }), 'Tenant provisioned')}>Provision tenant</button>
        </Card>
      )}
      {tab === 'plans' && (
        <div className="grid g3">{Object.entries(data.plans).map(([k, v]: any) => (
          <Card key={k} title={`${k} · ${v.price}`}>{v.features.map((x: string) => <div key={x} className="split"><span>{x}</span></div>)}
            <div className="split"><span>Isolation · n8n</span><b>{v.isolation} · {v.n8n}</b></div></Card>))}</div>
      )}
    </main>
  );
}
