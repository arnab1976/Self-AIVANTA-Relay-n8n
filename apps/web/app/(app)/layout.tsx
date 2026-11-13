'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useEffect, useState } from 'react';
import { api, getSession } from '@/lib/api';
import { ROLE_LABELS } from '@/lib/format';
import { useSession } from '@/lib/session';
import { ThemeSwitcher } from '@/lib/theme';

const NAV: [string, [string, string][]][] = [
  ['Workspace', [['/dashboard', 'Command Center'], ['/projects', 'Projects & RFP Intake']]],
  ['Build', [['/canvas', 'Agent Canvas'], ['/library', 'Agents & Tools']]],
  ['Run', [['/runs', 'Runs & Observability'], ['/approvals', 'Approvals'], ['/artifacts', 'Artifacts & Documents']]],
  ['Commercials', [['/estimate', 'Estimation, Pricing & FinOps']]],
  ['Control', [['/governance', 'Governance & UAT'], ['/admin', 'Tenant Administration']]],
  ['Appendix', [['/appendix', 'Agentic frameworks']]],
];

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const { session, meta, projectId, setProjectId, signOut } = useSession();
  const [projects, setProjects] = useState<{ id: string; code: string; client: string }[]>([]);

  useEffect(() => {
    if (!getSession()) {
      window.location.href = '/login';
      return;
    }
    api<{ id: string; code: string; client: string }[]>('/projects')
      .then((p) => {
        setProjects(p);
        if (p.length && !p.some((x) => x.id === projectId)) setProjectId(p[0].id);
      })
      .catch(() => {
        /* api client redirects on stale tenant / 401 */
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!session) return null;
  return (
    <div className="shell">
      <aside className="side">
        <Link href="/dashboard" className="brand"><span className="brand-mark">A</span><span>Relay<small>{meta?.runtime ?? 'n8n'}</small></span></Link>
        {NAV.map(([group, links]) => (
          <div key={group}>
            <div className="nav-group">{group}</div>
            {links.map(([href, label]) => (
              <Link key={href} href={href} className={`nav-link ${path?.startsWith(href) ? 'on' : ''}`}>{label}</Link>
            ))}
          </div>
        ))}
        <div className="side-foot">{meta?.framework_version}<br />LLM: {meta?.llm_provider}</div>
      </aside>
      <div style={{ minWidth: 0 }}>
        <div className="top">
          <b>{session.tenant.name}</b>
          <select id="project" value={projectId ?? ''} onChange={(e) => setProjectId(e.target.value)} aria-label="Project">
            {projects.map((p) => <option key={p.id} value={p.id}>{p.code} · {p.client}</option>)}
          </select>
          <span className="grow" />
          <ThemeSwitcher />
          <span className="muted">{session.user.name} · {ROLE_LABELS[session.user.roles[0]] ?? session.user.roles[0]}</span>
          <a className="btn" href="/login">Switch role</a>
          <button className="btn ghost" onClick={signOut}>Sign out</button>
        </div>
        <main className="main">{children}</main>
      </div>
    </div>
  );
}
