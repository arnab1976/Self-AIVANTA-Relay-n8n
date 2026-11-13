'use client';

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import { money, ROLE_LABELS } from '@/lib/format';
import { useSession } from '@/lib/session';
import { Card, PageHeader, Pill, toast } from '@/components/ui';

export default function Admin() {
  const { can } = useSession();
  const [tenant, setTenant] = useState<any>(null);
  const [all, setAll] = useState<any[]>([]);
  const [form, setForm] = useState({ code: '', name: '', currency: 'INR', region: 'India (Mumbai)', isolation_model: 'schema-per-tenant' });
  const admin = can('tenant:admin');
  const [requests, setRequests] = useState<any[]>([]);
  const [users, setUsers] = useState<any[]>([]);
  const load = () => {
    api('/tenants/current').then(setTenant);
    if (admin) {
      api<any[]>('/tenants').then(setAll);
      api<any[]>('/access-requests').then(setRequests).catch(() => null);
      api<any[]>('/tenant-admin/users').then(setUsers).catch(() => null);
    }
  };
  const decide = (id: string, decision: string) => api(`/access-requests/${id}/decide`, { method: 'POST', json: { decision } })
    .then(() => { toast(`Request ${decision.toLowerCase()}`); load(); }).catch((e) => toast(e.message, true));
  const setRole = (id: string, role: string) => api(`/tenant-admin/users/${id}`, { method: 'PATCH', json: { roles: [role] } })
    .then(() => { toast('Role updated'); load(); }).catch((e) => toast(e.message, true));
  useEffect(load, [admin]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!tenant) return null;
  const patch = (json: any) => api('/tenants/current', { method: 'PATCH', json }).then(setTenant).catch((e) => toast(e.message, true));
  return (
    <>
      <PageHeader title="Tenant Administration" sub="Each tenant has its own projects, graphs, runs, artifacts, tool approvals, model allowlist, rate card and audit chain." />
      <div className="grid g3">
        <Card title={tenant.name}>
          <div className="split"><span>Region · currency</span><b>{tenant.region} · {tenant.currency}</b></div>
          <div className="split"><span>Isolation</span><b>{tenant.isolation_model}</b></div>
          <div className="split"><span>Identity</span><b>{tenant.identity_provider}</b></div>
          <div className="split"><span>Margin floor · discount limit</span><b>{tenant.margin_floor_pct}% · {tenant.discount_limit_pct}%</b></div>
          <div className="split"><span>Rate card · FX</span><b>{tenant.rate_card_version} · {tenant.fx_version}</b></div>
        </Card>
        <Card title="Model profile allowlist">
          {tenant.model_profiles.map((m: string) => (
            <label key={m} className="split"><span className="mono">{m}</span>
              <input type="checkbox" disabled={!admin} checked={tenant.allowed_models.includes(m)}
                onChange={(e) => patch({ allowed_models: e.target.checked ? [...tenant.allowed_models, m] : tenant.allowed_models.filter((x: string) => x !== m) })} /></label>
          ))}
          <p className="faint" style={{ fontSize: 12 }}>Canvases using a disallowed profile fail validation and cannot be published.</p>
        </Card>
        <Card title="Rate card">
          {Object.entries(tenant.rate_card).map(([role, rate]) => <div key={role} className="split"><span>{role}</span><b>{money(rate as number, tenant.currency)}</b></div>)}
        </Card>
      </div>
      {admin && (
        <div className="grid g2" style={{ marginTop: 14 }}>
          <Card title={`Access requests (${requests.filter((r) => r.status === 'Pending').length} pending)`}>
            {requests.length === 0 && <p className="muted">No join requests. People request access from the home page.</p>}
            {requests.map((r) => (
              <div key={r.id} className="split">
                <span>{r.name} <span className="faint">{r.email} · {r.role_label}</span><br /><span className="faint">{r.note}</span></span>
                {r.status === 'Pending'
                  ? <span className="row"><button className="btn primary" onClick={() => decide(r.id, 'Approved')}>Approve</button><button className="btn danger" onClick={() => decide(r.id, 'Rejected')}>Reject</button></span>
                  : <Pill>{r.status}</Pill>}
              </div>
            ))}
          </Card>
          <Card title="Users & roles">
            {users.map((u) => (
              <div key={u.id} className="split"><span>{u.name} <span className="faint">{u.email}</span></span>
                <select value={u.roles[0]} onChange={(e) => setRole(u.id, e.target.value)}>{Object.entries(ROLE_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></div>
            ))}
          </Card>
        </div>
      )}
      {admin && (
        <div className="grid g2" style={{ marginTop: 14 }}>
          <Card title="All tenants">
            {all.map((t) => <div key={t.id} className="split"><span>{t.name} <span className="faint">{t.code}</span></span><b>{t.isolation_model}</b></div>)}
          </Card>
          <Card title="Provision tenant">
            <div className="form">
              {(['code', 'name', 'region'] as const).map((k) => <label key={k} className="field">{k}<input id={`t-${k}`} value={form[k]} onChange={(e) => setForm({ ...form, [k]: e.target.value })} /></label>)}
              <label className="field">currency<select id="t-cur" value={form.currency} onChange={(e) => setForm({ ...form, currency: e.target.value })}><option>INR</option><option>USD</option></select></label>
              <label className="field">isolation<select id="t-iso" value={form.isolation_model} onChange={(e) => setForm({ ...form, isolation_model: e.target.value })}><option>schema-per-tenant</option><option>dedicated-database</option><option>row-level-security</option></select></label>
            </div>
            <button className="btn primary" style={{ marginTop: 10 }} onClick={() => api('/tenants', { method: 'POST', json: form }).then(() => { toast('Tenant provisioned'); load(); }).catch((e) => toast(e.message, true))}>Provision</button>
          </Card>
        </div>
      )}
    </>
  );
}
