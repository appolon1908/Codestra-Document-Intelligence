# CI / Publish Contract

GitHub Actions validates every pull request and architecture/feature branch push.

Before publishing:
1. Fetch the exact remote branch/base.
2. Verify expected local and remote SHA.
3. Require the intended non-main branch.
4. Do not publish dirty, stale or divergent work.
5. Run applicable local tests.
6. Use normal non-force push only.
7. Verify remote SHA after push.
8. Require CI before merge.

Main is never auto-pushed by this workflow. Production promotion requires separate exact-SHA staging evidence.
