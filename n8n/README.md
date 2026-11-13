# n8n assets

`workflows/` holds the n8n workflows that AIVANTA generates from its built-in templates, in both agent modes:

| File | Template |
|---|---|
| `rfp_sow.native.json` | RFP-to-SOW (20 canvas nodes → 62 n8n nodes: AI Agents, Switch, Merges, 3 Wait approvals) |
| `rfp_brd.native.json` | RFP-to-BRD |
| `est_prop.native.json` | Estimate-to-Proposal |
| `cloud_review.native.json` | Cloud Cost Review |
| `res_deploy.native.json` | Resource Deployment (Jira create behind an approval) |
| `*.service.json` | The same, with agents executed by AIVANTA (no AI Agent nodes) |

Regenerate with `make n8n-workflows`. These files are compiled artefacts: change workflows on the AIVANTA canvas and publish. AIVANTA deploys and activates them through the n8n API, with real credential ids and a per-tenant webhook path.

## Credentials AIVANTA creates in n8n

| Name | Type | Used by |
|---|---|---|
| AIVANTA Bridge | Header Auth (`X-Aivanta-Bridge-Token`) | Every HTTP Request node, and the Trigger webhook's authentication |
| AIVANTA Model Gateway | OpenAI (API key = bridge token, base URL = `<AIVANTA_BRIDGE_URL>/gateway/v1`) | OpenAI Chat Model sub-nodes of AI Agent nodes |

## Manual import

To inspect a workflow in a scratch n8n: Workflows → Import from file, then point the two credentials at an AIVANTA API. Running it outside AIVANTA fails at the first bridge call, because AIVANTA has no run with that id. That is intentional.
