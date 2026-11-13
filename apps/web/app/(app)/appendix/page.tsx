'use client';

import { useMemo, useState } from 'react';
import { FRAMEWORKS, PANEL_FRAMING, RELAY_ANGLE } from '@/lib/frameworkCompare';
import { Card, PageHeader, Pill } from '@/components/ui';

export default function AppendixPage() {
  const [active, setActive] = useState(FRAMEWORKS[0].id);
  const fw = useMemo(() => FRAMEWORKS.find((f) => f.id === active) || FRAMEWORKS[0], [active]);

  return (
    <>
      <PageHeader
        title="Appendix · Agentic frameworks"
        sub="End-to-end execution, orchestration, components and architecture — LangGraph, AutoGen, LlamaIndex, n8n, Haystack, CrewAI and IBM BeeAI. Panel-ready decision map (2025–2026 landscape)."
      />

      <Card title="One-line framing">
        <p className="muted" style={{ margin: 0 }}>{PANEL_FRAMING}</p>
        <div className="row" style={{ marginTop: 10, flexWrap: 'wrap' }}>
          <Pill tone="info">Code-first</Pill>
          <Pill tone="good">Automation / low-code</Pill>
          <Pill>RAG / data-centric</Pill>
          <Pill tone="warn">Enterprise governance</Pill>
        </div>
      </Card>

      <div className="mt">
        <Card title="Decision matrix">
          <div className="appendix-table-wrap">
            <table className="appendix-table">
              <thead>
                <tr>
                  <th>Framework</th>
                  <th>Abstraction</th>
                  <th>Execution</th>
                  <th>Orchestration</th>
                  <th>Deployment / production</th>
                  <th>Parallel vs sequential</th>
                  <th>Best fit</th>
                  <th>Watch out</th>
                </tr>
              </thead>
              <tbody>
                {FRAMEWORKS.map((f) => (
                  <tr
                    key={f.id}
                    className={f.id === active ? 'on' : undefined}
                    onClick={() => setActive(f.id)}
                  >
                    <td><b>{f.name}</b></td>
                    <td>{f.abstraction}</td>
                    <td>{f.execution}</td>
                    <td>{f.orchestration}</td>
                    <td>{f.deployment}</td>
                    <td>{f.concurrency}</td>
                    <td>{f.bestFit}</td>
                    <td>{f.watchOut}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="faint" style={{ margin: '10px 0 0', fontSize: 12 }}>
            Click a row for architecture, end-to-end story and usage notes. Sources: vendor docs and 2025–2026 industry comparisons.
          </p>
        </Card>
      </div>

      <div className="row mt" style={{ flexWrap: 'wrap', gap: 8 }}>
        {FRAMEWORKS.map((f) => (
          <button
            key={f.id}
            type="button"
            className={`btn ${f.id === active ? 'primary' : ''}`}
            onClick={() => setActive(f.id)}
          >
            {f.name}
          </button>
        ))}
      </div>

      <div className="grid g2 mt">
        <Card title={`${fw.name} · Architecture & components`}>
          <ul className="appendix-list">
            {fw.architecture.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </Card>
        <Card title={`${fw.name} · End-to-end agentic flow`}>
          <p className="muted" style={{ margin: 0 }}>{fw.e2eStory}</p>
          <p style={{ margin: '12px 0 0' }}>
            <span className="pill acc">Choose if</span>{' '}
            <span className="muted">{fw.chooseIf}</span>
          </p>
        </Card>
      </div>

      <div className="grid g2 mt">
        <Card title={`${fw.name} · Deployment / production`}>
          <p className="muted" style={{ margin: 0 }}>{fw.deployment}</p>
        </Card>
        <Card title={`${fw.name} · Parallel vs sequential`}>
          <p className="muted" style={{ margin: 0 }}>{fw.concurrency}</p>
        </Card>
      </div>

      <div className="grid g2 mt">
        <Card title="When to choose (panel soundbites)">
          <ul className="appendix-list">
            {FRAMEWORKS.map((f) => (
              <li key={f.id}>
                <b>{f.name}</b> — {f.chooseIf}
              </li>
            ))}
          </ul>
        </Card>
        <Card title="AIVANTA Relay angle">
          {RELAY_ANGLE.map((p) => (
            <p key={p} className="muted" style={{ marginTop: 0 }}>{p}</p>
          ))}
        </Card>
      </div>

      <p className="faint mt" style={{ fontSize: 12.5 }}>
        Not vendor rankings — a decision map. Validate against compliance, language stack (.NET/Azure vs Python), and ops model before selecting.
      </p>
    </>
  );
}
