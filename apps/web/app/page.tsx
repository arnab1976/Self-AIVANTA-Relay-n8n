import Link from 'next/link';
import { HeroFlowVisual, N8nComponentsExplorer } from '@/components/home/N8nComponentsExplorer';
import { ThemeSwitcher } from '@/lib/theme';

const OBJECTIVES = [
  ['Automate the bid pipeline', 'An RFP upload triggers an n8n workflow through analysis, solutioning, pricing and SOW.'],
  ['Connect every system', 'SharePoint, CRM, HRMS, Jira and email via governed connectors — no secrets in workflows.'],
  ['Keep people in charge', 'Send & Wait pauses n8n until the right role decides, with segregation of duties.'],
];
const STEPS = [
  ['Design', 'Build on the AIVANTA canvas: triggers, agents, connectors, IF/Switch, Send & Wait.'],
  ['Publish', 'Validate reachability and approvals, then freeze a version.'],
  ['Compile', 'The version becomes an immutable n8n workflow, activated per tenant.'],
  ['Execute', 'n8n runs in queue mode; governed steps call back into AIVANTA.'],
  ['Approve', 'Wait nodes pause; the approver decides in Relay and n8n resumes.'],
  ['Deliver', 'Versioned BRD, architecture, pricing and SOW with export.'],
];
const STACK = ['n8n', 'Next.js', 'FastAPI', 'React Flow', 'PostgreSQL', 'Redis', 'Docker'];

export default function Home() {
  return (
    <main>
      <header className="top" style={{ justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
        <span className="brand" style={{ padding: 0 }}><span className="brand-mark">A</span><span>AIVANTA Relay<small>Built on n8n</small></span></span>
        <div className="row" style={{ flexWrap: 'wrap' }}>
          <ThemeSwitcher />
          <Link className="btn primary" href="/login">Start Journey →</Link>
        </div>
      </header>

      <section className="hero">
        <div>
          <div className="eyebrow">AIVANTA · n8n edition</div>
          <h1>AIVANTA Relay</h1>
          <p>
            Every RFP becomes an n8n workflow your bid team can see — triggers, AI agents, connectors, routing and
            Send &amp; Wait — with AIVANTA governance on top.
          </p>
          <div className="row" style={{ marginTop: 12, flexWrap: 'wrap' }}>
            <Link className="btn primary" href="/login">Start Journey →</Link>
            <a className="btn ghost" href="#n8n-components">Explore n8n components</a>
          </div>
        </div>
        <HeroFlowVisual />
      </section>

      <section className="band" id="n8n-components">
        <div className="eyebrow">n8n building blocks</div>
        <h2>Components &amp; how they work</h2>
        <p className="muted" style={{ maxWidth: 820, margin: '0 0 14px' }}>
          Click a component to see what it does in n8n and how Relay maps it on the canvas. The beam animates along a
          typical RFP-to-SOW path.
        </p>
        <N8nComponentsExplorer />
      </section>

      <section className="band">
        <div className="eyebrow">Powered by</div>
        <h2>Tools &amp; tech stack</h2>
        <div className="powered">
          {STACK.map((name) => (
            <span className="tech" key={name}>{name}</span>
          ))}
        </div>
      </section>

      <section className="band">
        <div className="eyebrow">Objective</div>
        <h2>What Relay sets out to do</h2>
        <div className="grid g3">{OBJECTIVES.map(([t, d]) => <div className="card" key={t}><h3>{t}</h3><p className="muted">{d}</p></div>)}</div>
      </section>

      <section className="band" id="how">
        <div className="eyebrow">How it works</div>
        <h2>From canvas to n8n execution</h2>
        <div className="grid g3">{STEPS.map(([t, d], i) => <div className="card" key={t}><span className="faint mono">STEP {i + 1}</span><h3>{t}</h3><p className="muted">{d}</p></div>)}</div>
      </section>

      <footer className="band faint" style={{ fontSize: 13, paddingTop: 8, paddingBottom: 28 }}>
        AIVANTA Relay · n8n is fair-code under the Sustainable Use License: free for internal use; serving external customers needs an n8n Embed licence.
      </footer>
    </main>
  );
}
