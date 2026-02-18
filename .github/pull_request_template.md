## Summary

## Risk Level
- [ ] Low
- [ ] Medium
- [ ] High

## Validation
- [ ] Backend tests: `cd backend && python3 -m pytest -q`
- [ ] Frontend lint: `cd frontend && npm run lint`
- [ ] Frontend build: `cd frontend && npm run build`
- [ ] Any new behavior has tests

## Security + Operations
- [ ] No secrets, tokens, or passkeys in logs, URLs, screenshots, or fixtures
- [ ] Authz/authn changes reviewed for least privilege and failure modes
- [ ] Reminder/conversation webhook signature modes and secrets reviewed for production safety
- [ ] Rollback path documented for schema/runtime changes
- [ ] Env var changes reflected in `.env.example` and `README.md`

## Reviewer Notes For Cj&Jack
- [ ] Include a short business-facing note describing impact and expected demo behavior
