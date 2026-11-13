'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import { when } from '@/lib/format';
import { useSession } from '@/lib/session';
import { composeCanvasName } from '@/lib/canvasName';
import { PageHeader, Pill, toast } from '@/components/ui';

export default function Canvases() {
  const { can, projectId } = useSession();
  const [graphs, setGraphs] = useState<any[]>([]);
  const [templates, setTemplates] = useState<any[]>([]);
  const [project, setProject] = useState<{ id: string; code: string; name: string; client: string } | null>(null);
  const load = () =>
    api<any[]>('/graphs')
      .then(setGraphs)
      .catch((e: any) => toast(e.message, true));
  useEffect(() => {
    load();
    api<any[]>('/graphs/templates')
      .then(setTemplates)
      .catch((e: any) => toast(e.message, true));
  }, []);
  useEffect(() => {
    if (!projectId) {
      setProject(null);
      return;
    }
    api<{ id: string; code: string; name: string; client: string }>(`/projects/${projectId}`)
      .then((p) => setProject({ id: p.id, code: p.code, name: p.name, client: p.client }))
      .catch(() => setProject(null));
  }, [projectId]);

  async function create(key: string, name: string) {
    try {
      const label = `${name} · v${graphs.filter((g) => String(g.name).includes(name)).length + 1}`;
      const fullName = composeCanvasName(project, label);
      const g = await api<any>('/graphs', { method: 'POST', json: { name: fullName, template: key } });
      window.location.href = `/canvas/${g.id}`;
    } catch (e: any) {
      toast(e.message, true);
    }
  }

  return (
    <>
      <PageHeader
        title="Agent Canvas"
        sub={project
          ? `New canvases are named “${project.code} · ${project.name} · …” from the selected project / RFP intake so versions stay identifiable.`
          : 'Versioned canvas graphs (canvas.v1). Select a project in the top bar to prefix new canvases with Project · RFP Intake.'}
      />
      <div className="grid g3">
        {graphs.map((g) => (
          <Link key={g.id} href={`/canvas/${g.id}`} className="card canvas-card-link" aria-label={`Open canvas ${g.name}`}>
            <header className="card-head">
              <h3 className="canvas-card-title">{g.name}</h3>
            </header>
            <div className="row">{g.versions.length ? <Pill>{g.versions.at(-1).environment}</Pill> : <Pill tone="warn">draft only</Pill>}
              {g.validation?.errors ? <Pill tone="bad">{g.validation.errors} errors</Pill> : <Pill tone="good">valid</Pill>}</div>
            <div className="split"><span>Nodes · connections</span><b>{g.nodes} · {g.edges}</b></div>
            <div className="split"><span>Latest version</span><b>{g.versions.length ? `v${g.versions.at(-1).version} · ${g.versions.at(-1).content_hash}` : '—'}</b></div>
            <div className="split"><span>Saved</span><b>{when(g.saved_at)}</b></div>
            <div className="canvas-card-open">Open canvas →</div>
          </Link>
        ))}
      </div>
      <h3 style={{ margin: '24px 0 10px', fontSize: 16 }}>New canvas from a template</h3>
      <div className="grid g3">
        {templates.map((t) => (
          <button key={t.key} className="choice" disabled={!can('graph:edit')} onClick={() => create(t.key, t.name)}>
            <b>{t.name}</b><div className="muted" style={{ fontSize: 13 }}>{t.description}</div><div className="faint mono" style={{ fontSize: 11 }}>{t.nodes} nodes · {t.edges} connections</div>
          </button>
        ))}
      </div>
    </>
  );
}
