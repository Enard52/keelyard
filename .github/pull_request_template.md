## What and why

## How I verified it
- [ ] `pytest -q` and `ruff check src tests` pass
- [ ] New behaviour has a test (hooks: never crash the agent; filters: keep every failure/error line)
- [ ] Any number in docs comes from `keelyard bench` or a script in `bench/`, with machine and date
- [ ] No secrets, personal paths or copied third-party code (see NOTICE)
