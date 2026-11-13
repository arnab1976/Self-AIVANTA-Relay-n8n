// Thin client for the AIVANTA Relay API. The token is kept in localStorage for local development;
// in production put the web app and API behind the same origin and use an httpOnly session cookie.

export const API_URL = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000').replace(/\/$/, '');

export interface Session {
  token: string;
  user: { id: string; name: string; email: string; roles: string[] };
  tenant: { id: string; code: string; name: string };
}

const KEY = 'aivanta.session';

export function getSession(): Session | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as Session) : null;
  } catch {
    return null;
  }
}

export function setSession(s: Session | null) {
  try {
    if (s) window.localStorage.setItem(KEY, JSON.stringify(s));
    else window.localStorage.removeItem(KEY);
  } catch {
    /* storage unavailable */
  }
}

export class ApiError extends Error {
  constructor(public status: number, message: string, public detail?: unknown) {
    super(message);
  }
}

function messageOf(detail: unknown): string {
  if (!detail) return 'Request failed';
  if (typeof detail === 'string') return detail;
  if (typeof detail === 'object' && detail && 'message' in detail) return String((detail as { message: string }).message);
  return JSON.stringify(detail);
}

export async function api<T = any>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const s = getSession();
  const headers: Record<string, string> = { ...(init.headers as Record<string, string>) };
  if (s) headers.Authorization = `Bearer ${s.token}`;
  let body = init.body;
  if (init.json !== undefined) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(init.json);
  }
  const res = await fetch(`${API_URL}/api${path}`, { ...init, headers, body });
  if (!res.ok) {
    let detail: unknown;
    try {
      detail = (await res.json()).detail;
    } catch {
      detail = res.statusText;
    }
    // Stale JWT after API reseed / DB reset: tenant id in the token no longer exists.
    const staleTenant =
      (res.status === 404 && detail === 'Tenant not found') ||
      (typeof detail === 'string' && detail.includes('Tenant no longer exists'));
    if ((res.status === 401 || staleTenant) && typeof window !== 'undefined') {
      setSession(null);
      // Avoid a redirect loop when /login itself is validating a stale session.
      if (!window.location.pathname.startsWith('/login')) {
        window.location.href = '/login';
      }
    }
    throw new ApiError(res.status, messageOf(detail), detail);
  }
  if (res.status === 204) return undefined as T;
  const type = res.headers.get('content-type') || '';
  return (type.includes('application/json') ? res.json() : res.blob()) as Promise<T>;
}

export function streamUrl(path: string): string {
  const s = getSession();
  return `${API_URL}/api${path}${path.includes('?') ? '&' : '?'}access_token=${encodeURIComponent(s?.token || '')}`;
}

export async function download(path: string, filename: string) {
  const blob = await api<Blob>(path);
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
