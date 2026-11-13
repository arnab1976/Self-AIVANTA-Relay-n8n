'use client';

import { useEffect, useState } from 'react';
import { api, getSession, setSession, type Session } from '@/lib/api';
import { ROLE_LABELS } from '@/lib/format';
import { toast } from '@/components/ui';

interface TenantOption { code: string; name: string; region: string; currency: string; isolation_model: string }

const DEFAULT_ROLE = 'architect';
const DEFAULT_TENANT = 'FP';
const DEFAULT_NAME = ROLE_LABELS[DEFAULT_ROLE];

function destinationFor(role: string) {
  if (role === 'admin') return '/admin';
  if (role === 'finance') return '/estimate';
  return '/canvas';
}

export default function Login() {
  const [status, setStatus] = useState('Entering workspace…');
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function enter() {
      try {
        const existing = getSession();
        if (existing) {
          // Confirm the tenant in the token still exists (API reseed invalidates old ids).
          setStatus('Checking saved session…');
          try {
            await api('/auth/me');
            if (cancelled) return;
            const role = existing.user.roles[0] || DEFAULT_ROLE;
            window.location.href = destinationFor(role);
            return;
          } catch {
            setSession(null);
            /* fall through to a fresh login */
          }
        }

        const tenants = await api<TenantOption[]>('/auth/tenants');
        const preferred = tenants.find((t) => t.code === DEFAULT_TENANT) || tenants[0];
        if (!preferred) {
          throw new Error('No demo tenants available. Is the API running and seeded?');
        }
        if (cancelled) return;
        setStatus(`Signing in to ${preferred.name}…`);
        const s = await api<Session>('/auth/dev-login', {
          method: 'POST',
          json: { tenant_code: preferred.code, role: DEFAULT_ROLE, name: DEFAULT_NAME },
        });
        if (cancelled) return;
        setSession(s);
        window.location.href = destinationFor(DEFAULT_ROLE);
      } catch (err: any) {
        if (cancelled) return;
        setFailed(true);
        setStatus(err?.message || 'Could not enter workspace');
        toast(err?.message || 'Could not enter workspace', true);
      }
    }

    enter();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <main className="login">
      <div className="card stack" style={{ maxWidth: 420, textAlign: 'center' }}>
        <h1 style={{ fontSize: 22 }}>Entering workspace</h1>
        <p className="muted">{status}</p>
        {failed && (
          <a className="btn primary" href="/" style={{ justifyContent: 'center' }}>
            Back to home
          </a>
        )}
      </div>
    </main>
  );
}
