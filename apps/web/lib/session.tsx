'use client';

import { createContext, useCallback, useContext, useEffect, useState } from 'react';
import { api, getSession, setSession, type Session } from './api';

interface Meta { product: string; runtime: string; framework_version: string; llm_provider: string }
interface Ctx {
  session: Session | null;
  meta: Meta | null;
  permissions: string[];
  projectId: string | null;
  setProjectId: (id: string) => void;
  can: (perm: string) => boolean;
  signOut: () => void;
  refresh: () => Promise<void>;
}

const SessionContext = createContext<Ctx | null>(null);

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [session, setS] = useState<Session | null>(null);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [permissions, setPermissions] = useState<string[]>([]);
  const [projectId, setPid] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const s = getSession();
    setS(s);
    api<Meta>('/meta').then(setMeta).catch(() => setMeta(null));
    if (s) {
      try {
        const me = await api<{ permissions: string[] }>('/auth/me');
        setPermissions(me.permissions);
      } catch {
        setPermissions([]);
      }
    }
    try {
      setPid(window.localStorage.getItem('aivanta.project'));
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const value: Ctx = {
    session,
    meta,
    permissions,
    projectId,
    setProjectId: (id) => {
      setPid(id);
      try {
        window.localStorage.setItem('aivanta.project', id);
      } catch {
        /* ignore */
      }
    },
    can: (perm) => permissions.includes(perm),
    signOut: () => {
      setSession(null);
      window.location.href = '/';
    },
    refresh,
  };
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): Ctx {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error('useSession must be used inside SessionProvider');
  return ctx;
}
