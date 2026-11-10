# RebateLedger — build pack for Claude Code

This folder is the starting point of the RebateLedger repository. It contains
no application code yet; Claude Code builds that phase by phase.

## What's inside

| File | Purpose | Loaded by Claude Code |
|---|---|---|
| `CLAUDE.md` | Standing rules: phase discipline, verification, money, security, code standards | Automatically, every session |
| `.claude/settings.json` | Blocks reading secret files; asks before push, cloud, deploy and destructive DB commands | Automatically |
| `.claude/rules/engine.md` | Rules for the rebate calculation engine | When engine files are touched |
| `.claude/rules/backend.md` | FastAPI rules | When backend Python files are touched |
| `.claude/rules/frontend.md` | Next.js rules | When frontend files are touched |
| `docs/SPEC.md` | Full product and technical specification | Read on demand |
| `docs/PHASES.md` | Phases 0–11 with acceptance criteria | Read on demand |
| `docs/PROGRESS.md` | Session log Claude maintains | Read on demand |
| `KICKOFF.md` | Your first message to Claude Code | You paste it |

## How to start

1. Create an empty Git repository and copy everything here into its root.
2. Commit it (so every later change is reviewable).
3. Open Claude Code in the repository root.
4. Paste the contents of `KICKOFF.md` as your first message.
5. Review its questions and Phase 0 plan, answer the [OPEN] items it raises,
   then approve. Repeat the plan → build → report → approve loop per phase.

## Your checkpoints

- **After Phase 1:** you have a working reconciliation CLI. Use it to run paid
  concierge pilots with real distributor data while Phases 2–11 are built.
- **Phase 5:** approve the design brief before any UI is built.
- **Phase 9:** get the legal pages reviewed before production.
- **Phase 11:** approve hosting costs and the production deploy yourself.
