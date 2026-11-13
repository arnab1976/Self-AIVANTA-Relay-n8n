'use client';

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import { useSession } from '@/lib/session';
import { Card, PageHeader, Pill, toast } from '@/components/ui';

export default function Projects() {
  const { can, projectId, setProjectId } = useSession();
  const [rows, setRows] = useState<any[]>([]);
  const [detail, setDetail] = useState<any>(null);
  const [form, setForm] = useState({ client: '', name: '', industry: 'BFSI', scope: '', deadline: '' });
  const [newQ, setNewQ] = useState('');
  const load = () => api<any[]>('/projects').then(setRows);
  useEffect(() => { load(); }, []);
  useEffect(() => { if (projectId) api(`/projects/${projectId}`).then(setDetail); }, [projectId]);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    try {
      const p = await api<any>('/projects', { method: 'POST', json: form });
      setProjectId(p.id);
      load();
      toast(`${p.code} created`);
    } catch (err: any) { toast(err.message, true); }
  }
  async function upload(file: File) {
    const fd = new FormData();
    fd.append('file', file);
    try {
      const r = await api<any>(`/projects/${projectId}/rfp`, { method: 'POST', body: fd });
      toast(`Ingested ${r.filename}: ${r.chunks} chunks, PII redacted ${JSON.stringify(r.pii_redactions)} (scan: ${r.scan_engine})`);
      api(`/projects/${projectId}`).then(setDetail);
      load();
    } catch (err: any) { toast(err.message, true); }
  }
  async function setClar(list: any[]) {
    const p = await api<any>(`/projects/${projectId}`, { method: 'PATCH', json: { clarifications: list } });
    setDetail({ ...detail, ...p });
  }

  async function remove(p: { id: string; code: string; name: string }, e: React.MouseEvent) {
    e.stopPropagation();
    if (!can('project:write')) return;
    if (!window.confirm(`Delete ${p.code} · ${p.name}? Related RFPs, runs, estimates and artifacts for this project will be removed.`)) return;
    try {
      await api(`/projects/${p.id}`, { method: 'DELETE' });
      if (projectId === p.id) {
        setDetail(null);
        const next = rows.find((r) => r.id !== p.id);
        setProjectId(next?.id ?? '');
      }
      await load();
      toast(`${p.code} deleted`);
    } catch (err: any) {
      toast(err.message, true);
    }
  }

  return (
    <>
      <PageHeader title="Projects & RFP Intake" sub="Uploads are malware-scanned and PII-redacted, then chunked for project-scoped retrieval before any agent reads them." />
      <div className="grid g2">
        <Card title="New project">
          <form className="stack" onSubmit={create}>
            <div className="form">
              <label className="field">Client<input id="p-client" required value={form.client} onChange={(e) => setForm({ ...form, client: e.target.value })} /></label>
              <label className="field">Project name<input id="p-name" required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
              <label className="field">Industry<select id="p-ind" value={form.industry} onChange={(e) => setForm({ ...form, industry: e.target.value })}>{['BFSI', 'Insurance', 'Healthcare', 'Pharma', 'Retail', 'Telecom'].map((x) => <option key={x}>{x}</option>)}</select></label>
              <label className="field">Deadline<input id="p-due" type="date" value={form.deadline} onChange={(e) => setForm({ ...form, deadline: e.target.value })} /></label>
            </div>
            <label className="field">Scope<textarea id="p-scope" rows={2} value={form.scope} onChange={(e) => setForm({ ...form, scope: e.target.value })} /></label>
            <button className="btn primary" disabled={!can('project:write')}>Create project</button>
          </form>
        </Card>
        {detail && (
          <Card title={`${detail.code} · ${detail.client}`}>
            <p className="muted">{detail.name} · {detail.industry} · {detail.delivery_model} · {detail.region}</p>
            <label className="btn" style={{ width: 'fit-content' }}>Upload RFP (PDF / DOCX / XLSX / TXT)
              <input type="file" hidden accept=".pdf,.docx,.xlsx,.txt,.md" disabled={!can('project:write')} onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
            </label>
            {detail.documents?.map((d: any) => <div className="split" key={d.id}><span>{d.filename} · {d.pages} pages</span><b>scan {d.scan_engine} · PII {JSON.stringify(d.pii_redactions)}</b></div>)}
            <h3 style={{ fontSize: 14, marginTop: 12 }}>Clarifications (open items route the Requirement Gap decision to a human)</h3>
            {(detail.clarifications || []).map((c: any, i: number) => (
              <div className="row" key={i} style={{ padding: '4px 0' }}>
                <Pill tone={c.open ? 'warn' : 'good'}>{c.open ? 'Open' : 'Answered'}</Pill><span style={{ flex: 1 }}>{c.question}</span>
                <button className="btn" onClick={() => setClar(detail.clarifications.map((x: any, j: number) => (j === i ? { ...x, open: !x.open } : x)))}>{c.open ? 'Mark answered' : 'Reopen'}</button>
              </div>
            ))}
            <div className="row"><input id="new-q" style={{ flex: 1 }} value={newQ} onChange={(e) => setNewQ(e.target.value)} placeholder="New clarification" />
              <button className="btn" onClick={() => { if (newQ) { setClar([...(detail.clarifications || []), { question: newQ, open: true }]); setNewQ(''); } }}>Add</button></div>
          </Card>
        )}
      </div>
      <div className="tbl" style={{ marginTop: 14 }}><table><thead><tr><th>Project</th><th>Client</th><th>Industry</th><th>Stage</th><th>Documents</th><th className="r">Open clarifications</th><th className="r">Actions</th></tr></thead><tbody>
        {rows.map((p) => (
          <tr key={p.id} className={`click ${p.id === projectId ? 'sel' : ''}`} onClick={() => setProjectId(p.id)}>
            <td><span className="mono">{p.code}</span> {p.name}</td><td>{p.client}</td><td>{p.industry}</td><td>{p.deal_stage}</td><td>{p.documents}</td><td className="r">{p.open_clarifications}</td>
            <td className="r" onClick={(e) => e.stopPropagation()}>
              <button className="btn danger" disabled={!can('project:write')} onClick={(e) => remove(p, e)} aria-label={`Delete ${p.code}`}>Delete</button>
            </td>
          </tr>
        ))}
      </tbody></table></div>
    </>
  );
}
