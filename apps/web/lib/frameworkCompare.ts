/** Panel appendix: agent orchestration frameworks comparison (2025–2026 landscape). */

export interface FrameworkRow {
  id: string;
  name: string;
  abstraction: string;
  execution: string;
  orchestration: string;
  deployment: string;
  concurrency: string;
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
    deployment: 'Library in your app/service; LangGraph Platform / self-host workers + checkpointer DB (Postgres/Redis); API or embedded runtime',
    concurrency: 'Both — sequential edges by default; fan-out/fan-in & Send API for parallel branches; async nodes scale per worker',
    bestFit: 'Complex branching, approvals, long-running production flows',
    watchOut: 'Steeper learning curve; graph thinking required',
    architecture: [
      'Core: StateGraph — shared state, nodes, conditional edges',
      'Runtime: checkpointers for pause/resume & audit',
      'Components: tools, subgraphs, interrupt (HITL)',
      'Architecture: code-defined DAG/state machine over LLMs',
      'Deploy: app-embedded or LangGraph Platform with durable state store',
      'Parallelism: explicit fan-out/fan-in; otherwise step-sequential',
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
    deployment: 'Python/.NET process or notebook; Azure-centric successor (Agent Framework); no built-in multi-tenant workflow ops plane',
    concurrency: 'Mostly sequential chat turns; optional concurrent tool/agent calls in newer patterns — not a queue workflow engine',
    bestFit: 'Research prototypes, code-execution agent chats (legacy)',
    watchOut: 'Maintenance mode; MS points new work to Agent Framework / AG2',
    architecture: [
      'Core: Assistant / UserProxy-style agents in a chat',
      'Runtime: conversation loop + optional code sandbox',
      'Components: group chat, tool use, human proxy',
      'Architecture: multi-agent dialogue (not a fixed workflow engine)',
      'Deploy: in-process / service wrapper; Azure migration path for production',
      'Parallelism: turn-based sequential; limited structured parallel workflows',
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
    deployment: 'Python/TS services with vector DBs (pgvector, etc.); Workflows as app code; often behind FastAPI / serverless handlers',
    concurrency: 'Both — Workflows support async fan-out of steps; ingest/retrieval parallelizes; agent loops often sequential',
    bestFit: 'Agentic RAG, document/knowledge assistants',
    watchOut: 'Weaker as a general enterprise workflow runtime',
    architecture: [
      'Core: Indexes / retrievers + Workflows (events)',
      'Runtime: event-driven steps, async fan-out',
      'Components: VectorStoreIndex, agents, tools, workflows',
      'Architecture: data plane first, orchestration second',
      'Deploy: app + vector store + optional workflow workers',
      'Parallelism: async event fan-out; RAG retrieval highly parallelizable',
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
    deployment: 'Self-host (Docker/K8s) or n8n Cloud; main + queue workers + Redis/Postgres; webhooks & credentials vault',
    concurrency: 'Both — node graph is often sequential; Split In Batches / parallel branches + queue mode run many executions concurrently',
    bestFit: 'Ops/integration-heavy agentic pipelines; visible to business',
    watchOut: 'Less granular than pure code for deep agent loops',
    architecture: [
      'Core: Workflow JSON → node graph in editor/API',
      'Runtime: executions (queue mode), Wait + webhook resume',
      'Components: Trigger, AI Agent, HTTP, IF/Switch, Code, Credentials',
      'Architecture: automation platform; AI is one node class among many',
      'Deploy: editor + webhook + queue workers (AIVANTA Relay target runtime)',
      'Parallelism: per-execution sequential path; scale-out via concurrent executions',
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
    deployment: 'Python services (REST/gRPC); document stores (Elastic, OpenSearch, etc.); deepset Cloud or self-host',
    concurrency: 'Mostly sequential pipeline stages; components can run async; batch/query parallelism at service layer',
    bestFit: 'Production search, RAG, NLP QA systems',
    watchOut: 'Not a free-form multi-agent OS',
    architecture: [
      'Core: Pipeline / Component graph for NLP & RAG',
      'Runtime: synchronous or async component execution',
      'Components: retrievers, readers, generators, rankers, agents',
      'Architecture: search/QA factory with eval & observability',
      'Deploy: API service + document/vector store',
      'Parallelism: stage-sequential; horizontal scale of query workers',
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
    deployment: 'Python app/service; CrewAI enterprise/cloud options; typically containerized workers calling LLM APIs',
    concurrency: 'Primarily sequential or hierarchical handoffs; async/parallel task support in Flows — not default multi-queue ops',
    bestFit: 'Content/research pipelines with clear role division',
    watchOut: 'Role metaphor strains on highly dynamic tasks',
    architecture: [
      'Core: Agent (role/goal/backstory) + Task + Crew / Flow',
      'Runtime: process types (sequential, hierarchical)',
      'Components: tools, memory, delegation, flows',
      'Architecture: org-chart metaphor for multi-agent work',
      'Deploy: Python service / CrewAI hosted offerings',
      'Parallelism: sequential & hierarchical first; Flows can add parallel steps',
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
    deployment: 'Py/TS libraries in your services; adapters to Watsonx/OpenAI/etc.; OpenTelemetry; LF-governed open source',
    concurrency: 'Both — workflows support dynamic steps, retries, nested flows & parallel multi-agent patterns; RequirementAgent loop is iterative/sequential per agent',
    bestFit: 'Governed multi-agent systems needing reliability rules',
    watchOut: 'Younger ecosystem vs LangGraph / LlamaIndex',
    architecture: [
      'Core: Agent, Backend/Adapters, Tools, Memory, Workflows',
      'Runtime: RequirementAgent enforces declarative rules',
      'Components: MCP tools, A2A, emitters/OpenTelemetry',
      'Architecture: LF open governance; Py ↔ TS feature parity',
      'Deploy: embed in services; provider adapters + OTel observability',
      'Parallelism: multi-agent parallel in workflows; agent loops sequential',
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
