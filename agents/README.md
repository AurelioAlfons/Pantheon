# Agent Configs

Each file here defines one of Pantheon's six agents: YAML frontmatter for metadata (name, role, model, tools, schedule), Markdown body as the literal system prompt. The config loader parses these directly — the body text is what the agent actually sees, so keep meta-commentary out of it. Anything explaining the files themselves belongs here instead.

These six are currently written for the devops-product-team framing: ASSIST dispatches, Hermes researches, Prometheus plans, Asmoday builds, Khepri reviews, Aizen documents. They're generic and public on purpose — no personal info, no real credentials, safe to show in the portfolio demo. They double as the `demo` deployment's committed agent configs.

## Retargeting to a different domain

The six roles are a pattern, not a hardcoded identity. If the use case ever changes, each role maps generically:

| File | Generic role |
|---|---|
| assist.md | Overseer / dispatcher |
| hermes.md | Researcher |
| prometheus.md | Planner |
| asmoday.md | Producer |
| khepri.md | Reviewer / QA |
| aizen.md | Writer / communicator |

To retarget: rewrite `role` in the frontmatter and the body prompt for the new domain, keep the frontmatter shape and the six-role split intact. Don't touch the loader or the orchestrator to do this — the point of a config-driven pattern is that a domain change is a content edit here, not a code change.

## What never goes here

Personal-mode configs with real integrations (real email access, for example) live outside this repo entirely, referenced via `AGENT_CONFIG_DIR` on the personal deployment. Nothing with real personal context belongs in `agents/`.
