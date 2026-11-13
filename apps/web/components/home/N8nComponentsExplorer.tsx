'use client';

import { useEffect, useMemo, useState } from 'react';

type ComponentId =
  | 'trigger'
  | 'agent'
  | 'http'
  | 'switch'
  | 'wait'
  | 'vector'
  | 'code'
  | 'respond'
  | 'workflow'
  | 'execution'
  | 'credential';

interface N8nPart {
  id: ComponentId;
  label: string;
  n8nName: string;
  color: string;
  blurb: string;
  how: string[];
  aivanta: string;
}

const PARTS: N8nPart[] = [
  {
    id: 'trigger',
    label: 'Trigger',
    n8nName: 'Webhook / Manual / Schedule',
    color: '#24323C',
    blurb: 'Starts a workflow when an event arrives — file upload, API call, cron, or a button click.',
    how: [
      'Receives the first item of data (JSON) into the workflow.',
      'In queue mode, each trigger can spawn a worker execution.',
      'Auth (header tokens, basic auth) sits on the trigger, not in later nodes.',
    ],
    aivanta: 'Maps to the canvas Start node: project ID + input schema enter here.',
  },
  {
    id: 'agent',
    label: 'AI Agent',
    n8nName: 'AI Agent + Chat Model',
    color: '#B85600',
    blurb: 'Calls an LLM with tools to reason over the payload and produce structured output.',
    how: [
      'Prompt + model + optional tools are configured on the node.',
      'Output can be typed JSON that downstream nodes consume.',
      'Retries and error branches handle model failures.',
    ],
    aivanta: 'Models only go through the AIVANTA gateway (allowlist, metering, schemas).',
  },
  {
    id: 'http',
    label: 'HTTP / App',
    n8nName: 'HTTP Request & app nodes',
    color: '#2A5FBF',
    blurb: 'Talks to external systems — SharePoint, CRM, Jira, email — using credentials from the vault.',
    how: [
      'Credentials are stored once in n8n and referenced by name.',
      'Each call is an item transformation: input JSON → response JSON.',
      'Timeouts and retries are node-level settings.',
    ],
    aivanta: 'Calls route via the AIVANTA tool gateway so scopes and schemas stay governed.',
  },
  {
    id: 'switch',
    label: 'IF / Switch',
    n8nName: 'IF · Switch',
    color: '#B58300',
    blurb: 'Routes the execution down different branches based on rules or labels.',
    how: [
      'Each branch is a separate output handle on the canvas.',
      'Rules should be exhaustive so no item is dropped silently.',
      'Useful after agents (e.g. open clarifications → pause vs continue).',
    ],
    aivanta: 'Rules are evaluated by AIVANTA; n8n Switch performs the route.',
  },
  {
    id: 'wait',
    label: 'Send & Wait',
    n8nName: 'Wait (resume on webhook)',
    color: '#B83A6B',
    blurb: 'Pauses the run until a human approves, rejects, or a timer fires.',
    how: [
      'Execution status becomes waiting; queue workers free up.',
      'A resume webhook continues from the Wait node with the decision payload.',
      'Keeps humans in the loop without polling.',
    ],
    aivanta: 'Approvals live in Relay (role, SLA, evidence); n8n resumes on decide.',
  },
  {
    id: 'vector',
    label: 'Vector Store',
    n8nName: 'Vector Store / retrieval',
    color: '#2F7D3B',
    blurb: 'Retrieves tenant-scoped knowledge so agents cite real sources instead of inventing facts.',
    how: [
      'Embeddings + filters return top-K chunks into the agent context.',
      'Source locators travel with the chunks for auditability.',
    ],
    aivanta: 'Access filters enforce tenant + project boundaries.',
  },
  {
    id: 'code',
    label: 'Code (pricing)',
    n8nName: 'Code node',
    color: '#5C6670',
    blurb: 'Runs deterministic logic — rate cards, margins, cloud sizing — with no LLM arithmetic.',
    how: [
      'Pure functions over the item JSON; same input → same output.',
      'Ideal for commercials where auditability matters.',
    ],
    aivanta: 'Pricing engine uses the versioned tenant rate card and policy floors.',
  },
  {
    id: 'respond',
    label: 'Respond / End',
    n8nName: 'Respond to Webhook / NoOp',
    color: '#24323C',
    blurb: 'Closes the path: returns a response to the caller or marks the branch complete.',
    how: [
      'Every started path should reach a terminal node.',
      'Output schema documents what the run produced.',
    ],
    aivanta: 'Canvas End node — artifacts are versioned before the run finishes.',
  },
  {
    id: 'workflow',
    label: 'Workflow',
    n8nName: 'Workflow definition',
    color: '#1a6b75',
    blurb: 'The saved graph of nodes and connections — the automation blueprint.',
    how: [
      'Published versions are immutable snapshots.',
      'Active workflows accept triggers; inactive ones are drafts.',
    ],
    aivanta: 'Publishing a canvas compiles to an n8n workflow tagged by tenant.',
  },
  {
    id: 'execution',
    label: 'Execution',
    n8nName: 'Execution / run history',
    color: '#3d5a73',
    blurb: 'One concrete run of a workflow with the data that passed through each node.',
    how: [
      'You can open any node and inspect its input/output items.',
      'Failed nodes show error + retry history.',
    ],
    aivanta: 'Relay tracks run status, tokens, approvals and the audit chain.',
  },
  {
    id: 'credential',
    label: 'Credentials',
    n8nName: 'Credentials store',
    color: '#2a5fbf',
    blurb: 'Encrypted secrets for APIs and databases — never pasted into node JSON.',
    how: [
      'Nodes reference a credential by id; secrets stay out of exports.',
      'Shared credentials can be scoped per environment.',
    ],
    aivanta: 'Vault references (vault://…) keep secrets out of the canvas draft.',
  },
];

const FLOW: ComponentId[] = ['trigger', 'agent', 'switch', 'wait', 'http', 'code', 'respond'];

export function N8nComponentsExplorer() {
  const [active, setActive] = useState<ComponentId>('trigger');
  const [pulse, setPulse] = useState(0);

  useEffect(() => {
    const t = setInterval(() => setPulse((p) => (p + 1) % FLOW.length), 2200);
    return () => clearInterval(t);
  }, []);

  const part = useMemo(() => PARTS.find((p) => p.id === active) || PARTS[0], [active]);
  const flowIndex = FLOW.indexOf(active);

  return (
    <div className="n8n-explorer">
      <div className="n8n-flow" aria-hidden>
        <div className="n8n-flow-track">
          {FLOW.map((id, i) => {
            const p = PARTS.find((x) => x.id === id)!;
            const on = active === id;
            const lit = pulse === i || on;
            return (
              <button
                key={id}
                type="button"
                className={`n8n-flow-node ${on ? 'on' : ''} ${lit ? 'lit' : ''}`}
                style={{ ['--node' as string]: p.color }}
                onClick={() => setActive(id)}
              >
                <span className="n8n-flow-dot" />
                <span className="n8n-flow-label">{p.label}</span>
              </button>
            );
          })}
          <div
            className="n8n-flow-beam"
            style={{
              width: `${(100 / Math.max(FLOW.length - 1, 1)) * Math.max(flowIndex >= 0 ? flowIndex : pulse, 0)}%`,
            }}
          />
        </div>
      </div>

      <div className="n8n-picker">
        {PARTS.map((p) => (
          <button
            key={p.id}
            type="button"
            className={`n8n-chip ${active === p.id ? 'on' : ''}`}
            style={{ ['--node' as string]: p.color }}
            onClick={() => setActive(p.id)}
          >
            <i />
            {p.label}
          </button>
        ))}
      </div>

      <div className="n8n-detail" key={part.id}>
        <div className="n8n-detail-head">
          <span className="n8n-swatch" style={{ background: part.color }} />
          <div>
            <h3>{part.label}</h3>
            <p className="faint mono">{part.n8nName}</p>
          </div>
        </div>
        <p className="n8n-blurb">{part.blurb}</p>
        <div className="n8n-cols">
          <div>
            <div className="eyebrow">How it works</div>
            <ul>
              {part.how.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </div>
          <div>
            <div className="eyebrow">In AIVANTA Relay</div>
            <p className="muted" style={{ margin: 0 }}>{part.aivanta}</p>
          </div>
        </div>
      </div>
    </div>
  );
}

const HERO_NODES = [
  { label: 'Trigger', color: '#24323C' },
  { label: 'AI Agent', color: '#B85600' },
  { label: 'Switch', color: '#B58300' },
  { label: 'Wait', color: '#B83A6B' },
  { label: 'End', color: '#24323C' },
];

export function HeroFlowVisual() {
  const [step, setStep] = useState(0);
  const nodes = HERO_NODES;

  useEffect(() => {
    const t = setInterval(() => setStep((s) => (s + 1) % HERO_NODES.length), 1600);
    return () => clearInterval(t);
  }, []);

  return (
    <div className="hero-flow" aria-hidden>
      <div className="hero-flow-title faint mono">n8n execution path</div>
      <div className="hero-flow-nodes">
        {nodes.map((n, i) => (
          <div key={n.label} className={`hero-flow-node ${i <= step ? 'on' : ''}`} style={{ ['--node' as string]: n.color }}>
            <span />
            {n.label}
          </div>
        ))}
      </div>
      <div className="hero-flow-bar">
        <i style={{ width: `${((step + 1) / nodes.length) * 100}%` }} />
      </div>
      <p className="muted" style={{ margin: '10px 0 0', fontSize: 13 }}>
        Data items move node → node. Waits pause; approvals resume; every step stays visible.
      </p>
    </div>
  );
}
