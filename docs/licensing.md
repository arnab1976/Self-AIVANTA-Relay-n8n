# Licensing and cost

| Component | Licence | Cost |
|---|---|---|
| **n8n** (Community Edition) | Sustainable Use License (fair-code) | Free for your own internal business use |
| n8n Enterprise features (SSO/SAML, LDAP, environments, Git source control, log streaming, external secrets, projects) | n8n Enterprise License (`.ee` code) | Paid n8n plan |
| **n8n Embed** | Commercial | Required when external customers use n8n through your product |
| AIVANTA Relay code in this repository | Yours (proprietary) | — |
| Python / JS dependencies (FastAPI, SQLAlchemy, Next.js, React Flow, httpx, …) | MIT / BSD / Apache-2.0 | Free |
| Model usage | Provider terms | Per token (OpenAI, Azure OpenAI) or your own GPUs (local models) |
| Cloud | Provider terms | Containers, PostgreSQL, Redis, storage, egress |

## What this means for AIVANTA Relay

* **Internal use** (your presales CoE, your delivery units, your subsidiaries): Community Edition is enough. Relay does not depend on any n8n Enterprise feature; tenancy, SSO and audit are implemented in AIVANTA.
* **Selling Relay as SaaS to external clients**: the clients use n8n through your product, so you need a commercial n8n licence (Embed). Budget for it before you onboard the first paying external tenant.
* The Sustainable Use License also restricts modifying or redistributing n8n's source. Relay uses the unmodified official image and its public API only.

Licence terms change. Confirm the current terms with n8n before signing client contracts; this page is not legal advice.
