'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import { ROLE_LABELS } from '@/lib/format';
import { toast } from '@/components/ui';

export default function RequestAccess() {
  const [kind, setKind] = useState<'join' | 'new_org'>('join');
  const [tenants, setTenants] = useState<{ code: string; name: string }[]>([]);
  const [meta, setMeta] = useState<any>(null);
  const [done, setDone] = useState<any>(null);
  const [f, setF] = useState({ name: '', email: '', organisation: '', tenant_code: '', role: 'presales', plan: 'Growth', cloud: 'AWS', region: 'India (Mumbai)', currency: 'INR', note: '' });
  useEffect(() => {
    api<any[]>('/public/tenants').then((t) => { setTenants(t); if (t[0]) setF((x) => ({ ...x, tenant_code: t[0].code })); }).catch(() => null);
    api('/public/plans').then(setMeta).catch(() => null);
  }, []);
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => setF({ ...f, [k]: e.target.value });

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    try {
      setDone(await api('/access-requests', { method: 'POST', json: { kind, ...f } }));
    } catch (err: any) {
      toast(err.message, true);
    }
  }

  if (done) {
    return (
      <main className="login"><div className="card stack">
        <h1 style={{ fontSize: 24 }}>Request submitted</h1>
        <p className="muted">Sent to the <b>{done.routed_to}</b>. You will receive an invitation when it is approved, then sign in with your company identity provider.</p>
        <div className="row"><Link className="btn" href="/">Home</Link><Link className="btn primary" href={done.routed_to === 'Provider Admin' ? '/provider' : '/login?role=admin'}>Open {done.routed_to} →</Link></div>
      </div></main>
    );
  }
  return (
    <main className="login">
      <form className="card stack" onSubmit={submit}>
        <h1 style={{ fontSize: 24 }}>Request access</h1>
        <p className="muted">Join requests go to that tenant&apos;s administrator. New organisations go to the provider team, who choose the plan, cloud, region and n8n placement.</p>
        <div className="row">
          <button type="button" className={`choice ${kind === 'join' ? 'on' : ''}`} onClick={() => setKind('join')}>Join an existing tenant</button>
          <button type="button" className={`choice ${kind === 'new_org' ? 'on' : ''}`} onClick={() => setKind('new_org')}>New organisation tenant</button>
        </div>
        <div className="form">
          <label className="field">Full name<input id="ra-name" required value={f.name} onChange={set('name')} /></label>
          <label className="field">Work email<input id="ra-email" type="email" required value={f.email} onChange={set('email')} /></label>
          <label className="field">Organisation<input id="ra-org" required value={f.organisation} onChange={set('organisation')} /></label>
          {kind === 'join' ? (
            <>
              <label className="field">Tenant<select id="ra-tenant" value={f.tenant_code} onChange={set('tenant_code')}>{tenants.map((t) => <option key={t.code} value={t.code}>{t.name}</option>)}</select></label>
              <label className="field">Role<select id="ra-role" value={f.role} onChange={set('role')}>{Object.entries(ROLE_LABELS).filter(([k]) => k !== 'admin').map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
            </>
          ) : (
            <>
              <label className="field">Plan<select id="ra-plan" value={f.plan} onChange={set('plan')}>{Object.entries(meta?.plans ?? {}).map(([k, v]: any) => <option key={k} value={k}>{k} · {v.price}</option>)}</select></label>
              <label className="field">Cloud<select id="ra-cloud" value={f.cloud} onChange={set('cloud')}>{(meta?.clouds ?? ['AWS']).map((c: string) => <option key={c}>{c}</option>)}</select></label>
              <label className="field">Data residency<select id="ra-region" value={f.region} onChange={set('region')}>{(meta?.regions ?? []).map((r: string) => <option key={r}>{r}</option>)}</select></label>
              <label className="field">Currency<select id="ra-cur" value={f.currency} onChange={set('currency')}><option>INR</option><option>USD</option></select></label>
            </>
          )}
        </div>
        <label className="field">Purpose<textarea id="ra-note" rows={3} value={f.note} onChange={set('note')} /></label>
        <div className="row"><button className="btn primary" type="submit">Submit request</button><Link className="btn ghost" href="/">← Home</Link></div>
      </form>
    </main>
  );
}
