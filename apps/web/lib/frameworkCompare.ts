/** Panel appendix: agent orchestration frameworks comparison (2025–2026 landscape). */

export interface FrameworkRow {
  id: string;
  name: string;
  abstraction: string;
  execution: string;
  orchestration: string;
  bestFit: string;
  watchOut: string;
  architecture: string[];
  e2eStory: string;
  chooseIf: string;
}

export const FRAMEWORKS: FrameworkRow[] = [
  {
    id: 'langgraph',
    name: 'LangGraph',
    abstraction: 'Stateful graph (nodes, edges, checkpoints)',
    execution: 'Explicit control flow; durable / resumable runs',
    orchestration: 'You design the graph; human-in-the-loop first-class',
    bestFit: 'Complex branching, approvals, long-running production flows',
    watchOut: 'Steeper learning curve; graph thinking required',
    architecture: [
      'Core: StateGraph — shared state, nodes, conditional edges',
      'Runtime: checkpointers for pause/resume & audit',
      'Components: tools, subgraphs, interrupt (HITL)',
      'Architecture: code-defined DAG/state machine over LLMs',
    ],
    e2eStory:
      'Trigger → node updates shared state → conditional edges → checkpoint → optional human interrupt → continue → terminal. Best when the path must be auditable and durable (approvals, retries, long jobs).',
    chooseIf: 'Need durable human-in-the-loop & branching control',
  },
  {
    id: 'autogen',
    name: 'AutoGen',
    abstraction: 'Conversational multi-agent chat',
    execution: 'Agents talk in a group until a stop condition',
    orchestration: 'Dialogue-driven; less explicit routing',
    bestFit: 'Research prototypes, code-execution agent chats (legacy)',
    watchOut: 'Maintenance mode; MS points new work to Agent Framework / AG2',
    architecture: [
      'Core: Assistant / UserProxy-style agents in a chat',
      'Runtime: conversation loop + optional code sandbox',
      'Components: group chat, tool use, human proxy',
      'Architecture: multi-agent dialogue (not a fixed workflow engine)',
    ],
    e2eStory:
      'Spawn chat agents → they converse / call tools / write code → stop when consensus or max turns. Powerful for exploration; weaker for fixed enterprise SLAs. Prefer successor for greenfield.',
    chooseIf: 'Maintaining chat-agent experiments (not new greenfield)',
  },
  {
    id: 'llamaindex',
    name: 'LlamaIndex',
    abstraction: 'Data indexes + event-driven Workflows',
    execution: 'Steps emit/consume events over shared context',
    orchestration: 'Strong around retrieval → reason → answer',
    bestFit: 'Agentic RAG, document/knowledge assistants',
    watchOut: 'Weaker as a general enterprise workflow runtime',
    architecture: [
      'Core: Indexes / retrievers + Workflows (events)',
      'Runtime: event-driven steps, async fan-out',
      'Components: VectorStoreIndex, agents, tools, workflows',
      'Architecture: data plane first, orchestration second',
    ],
    e2eStory:
      'Ingest/index data → Workflow steps (retrieve, reason, tool, synthesize) via events → answer grounded in corpus. Best when documents/knowledge are the product.',
    chooseIf: 'Need RAG / document-centric agents',
  },
  {
    id: 'n8n',
    name: 'n8n',
    abstraction: 'Visual workflow nodes + queue executions',
    execution: 'Item-based automation; Wait/resume; retries',
    orchestration: 'Low-code canvas; integrations & credentials built-in',
    bestFit: 'Ops/integration-heavy agentic pipelines; visible to business',
    watchOut: 'Less granular than pure code for deep agent loops',
    architecture: [
      'Core: Workflow JSON → node graph in editor/API',
      'Runtime: executions (queue mode), Wait + webhook resume',
      'Components: Trigger, AI Agent, HTTP, IF/Switch, Code, Credentials',
      'Architecture: automation platform; AI is one node class among many',
    ],
    e2eStory:
      'Trigger item → node chain (AI Agent, HTTP, Switch, Wait) → queue execution → resume after approval → respond. Best when integrations, credentials, and business visibility matter as much as the LLM.',
    chooseIf: 'Need ops integrations + visual runs (AIVANTA Relay plane)',
  },
  {
    id: 'haystack',
    name: 'Haystack',
    abstraction: 'Composable search/RAG pipelines',
    execution: 'Pipeline components; strong eval tooling',
    orchestration: 'Pipeline mindset + optional agent steps',
    bestFit: 'Production search, RAG, NLP QA systems',
    watchOut: 'Not a free-form multi-agent OS',
    architecture: [
      'Core: Pipeline / Component graph for NLP & RAG',
      'Runtime: synchronous or async component execution',
      'Components: retrievers, readers, generators, rankers, agents',
      'Architecture: search/QA factory with eval & observability',
    ],
    e2eStory:
      'Query → retriever → ranker/reader/generator components → evaluated RAG answer (agents optional). Best for search quality and pipeline eval, not open-ended multi-agent ops.',
    chooseIf: 'Need search-first RAG with strong evaluation',
  },
  {
    id: 'crewai',
    name: 'CrewAI',
    abstraction: 'Crews (roles) + Flows (steps)',
    execution: 'Role handoffs; sequential / hierarchical processes',
    orchestration: 'Map work to job roles (researcher → writer → reviewer)',
    bestFit: 'Content/research pipelines with clear role division',
    watchOut: 'Role metaphor strains on highly dynamic tasks',
    architecture: [
      'Core: Agent (role/goal/backstory) + Task + Crew / Flow',
      'Runtime: process types (sequential, hierarchical)',
      'Components: tools, memory, delegation, flows',
      'Architecture: org-chart metaphor for multi-agent work',
    ],
    e2eStory:
      'Goal → assign Tasks to role Agents → sequential or manager-led handoffs → optional Flow for deterministic steps around the crew. Best when the process looks like a team org chart.',
    chooseIf: 'Need fast role-based agent handoffs',
  },
  {
    id: 'beeai',
    name: 'IBM BeeAI',
    abstraction: 'Agents + Workflows + RequirementAgent rules',
    execution: 'Provider-agnostic; MCP/A2A; declarative constraints',
    orchestration: 'LF-hosted; Py/TS parity; enterprise observability',
    bestFit: 'Governed multi-agent systems needing reliability rules',
    watchOut: 'Younger ecosystem vs LangGraph / LlamaIndex',
    architecture: [
      'Core: Agent, Backend/Adapters, Tools, Memory, Workflows',
      'Runtime: RequirementAgent enforces declarative rules',
      'Components: MCP tools, A2A, emitters/OpenTelemetry',
      'Architecture: LF open governance; Py ↔ TS feature parity',
    ],
    e2eStory:
      'Define agents + tools + memory → Workflow steps or RequirementAgent rules → provider adapters → MCP/A2A. Best when you need declarative reliability constraints under open governance.',
    chooseIf: 'Need rule-enforced agents + LF / enterprise governance',
  },
];

export const PANEL_FRAMING =
  'Pick by control plane: LangGraph = durable control flow; CrewAI = role teams; LlamaIndex/Haystack = knowledge; n8n = visual ops automation; BeeAI = rule-constrained multi-agent; AutoGen = legacy chat agents (migrate for new builds).';

export const RELAY_ANGLE = [
  'Relay sits closer to n8n: visual orchestration, Wait/approvals, connectors, queue executions — with AIVANTA governance (models, pricing engine, artifacts, audit) layered on.',
  'LangGraph-class control and BeeAI-class rules are the code-side peers for the same governance goals; LlamaIndex/Haystack are the knowledge plane; CrewAI is the role-team plane.',
];
