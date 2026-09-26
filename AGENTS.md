# Codestra Global Development Governance v1.0

Mandatory entry: scripts/agent_preflight.sh

Repository: Codestra-Document-Intelligence
Canonical active worktree: /home/codestra/Worktrees/document-intelligence/Codestra-Document-Intelligence
Canonical branch: mission/document-intelligence-foundation-20260925
Recorded base: development at 69c3fd67cc7c1945a99d10d2a06edecfea7e1ac1

One-line continuation:
cd /home/codestra/Worktrees/document-intelligence/Codestra-Document-Intelligence && ./scripts/agent_preflight.sh

Rules:
- Work only in the canonical active worktree and active branch above.
- Never edit main/master/production, detached HEAD, a dirty start, or a branch with the wrong upstream.
- .codestra-mission/ACTIVE-LANE.env and .governance/authority.json are machine authority.
- Stale base SHA, wrong origin, wrong upstream, unresolved Git state, or production effects fail closed.
- Preserve historical/dirty work as reconciliation evidence. Never reset, stash, discard, overwrite, force-push, or delete unproven history.
- Do not expose /metrics or /internal publicly or add wildcard CORS.
- Production effects default OFF.
- Finish with scripts/agent_finish.sh.
- Certification must use scripts/certify.sh from a clean exact-SHA isolated lane plus repository-specific deterministic tests.
- Publication is Appolon-only, normal non-force push, with exact remote-SHA compare-and-swap and post-push readback.
