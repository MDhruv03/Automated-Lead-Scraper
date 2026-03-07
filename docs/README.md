# Technical Deep Dive — LeadPulse

This folder contains a comprehensive technical walkthrough of the LeadPulse automated lead discovery platform. Use it for interview prep, architecture reviews, or onboarding.

## Contents

| Document | Covers |
|----------|--------|
| [architecture.md](architecture.md) | System design, request flow, deployment model, database schema |
| [pipeline.md](pipeline.md) | Discovery → crawl → extract → enrich → score pipeline, quality gates, per-job settings |
| [discovery-engine.md](discovery-engine.md) | Multi-engine search strategy, directory scraping, relevance filtering, denylist |
| [data-extraction.md](data-extraction.md) | Contact extraction, email deobfuscation, phone normalization, tech stack detection |
| [scoring-and-validation.md](scoring-and-validation.md) | Lead scoring algorithm, business validation, location relevance, negative industry filter |
| [worker-architecture.md](worker-architecture.md) | Worker daemon, server API protocol, heartbeat, multi-URL failover |
| [api-reference.md](api-reference.md) | All REST endpoints, request/response schemas, authentication |
| [design-decisions.md](design-decisions.md) | Key trade-offs, why certain approaches were chosen, limitations |
