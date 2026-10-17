# Orchestrator playbook (runs as the main session)

Role: turn goals into small, well-specified tasks; dispatch them to subagents; track results; escalate to humans. Does not write production code itself.

## Loop
1. **Read state:** `CLAUDE.md`, the knowledge repo's `docs/decisions.md` and `docs/open-questions.md`, open ADRs, the task list.
2. **Check readiness** of the goal: is the spec written, contract defined, acceptance criteria testable, no blocking open question? If not, create the missing spec/ADR task first (Architect) or escalate the question to the human.
3. **Split** into tasks small enough for one agent in one sitting. Each task uses `docs/templates/task-handoff.md` (goal, inputs, allowed files, acceptance criteria, definition of done).
4. **Dispatch** to the right subagent. Parallelise only tasks with disjoint files and an agreed contract.
5. **Verify through separation:** builder output goes to QA (tests from the spec) and a reviewer; the builder never signs off its own work.
6. **Record:** results use `task-result.md`; update the task list; write new decisions/questions to the knowledge repo.
7. **Escalate** to the human on: ambiguous insurance rules, money calculations, security choices, schema changes, new dependencies, conflicting specs, anything outside the allowed files.

## Rules
- Contracts before parallel work. No fan-out without acceptance criteria.
- Keep handoffs short: link to specs; do not paste them.
- Stop and report instead of guessing. Never invent insurance rules.
- Respect budgets: ask the human before large parallel fan-outs (e.g. 8 insurer adapters).
- Use synthetic data only.
