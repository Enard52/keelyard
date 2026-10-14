# Swarm

Some work is wide rather than deep: answering "where is X handled" across a package, or drafting the same
small fix in five files. `swarm` sends tasks like these to a cheaper model in parallel, and never trusts
an answer it has not checked.

## Plan

`swarm_plan(goal)` (or `keelyard swarm plan "goal"`) splits a goal into one task per relevant file. It finds
the files that define the functions or classes the goal names, and gives each task a **context pack**: only
those definitions plus the file's imports, with real line numbers. No model call is involved.

```console
$ keelyard swarm plan "fix total() so SAVE10 takes 10% off" --json
{"tasks": [{"kind": "draft_edit", "files": ["cart.py"], "symbols": ["total"], ...}]}
```

## Run and check

For each task keelyard:

1. asks the helper model for a structured answer. Questions use a JSON schema (`answer`, `citations`,
   `quotes`). A fix to one definition asks for the new definition only, and keelyard builds the diff itself,
   because small models write correct code far more often than correct diffs.
2. checks it. Citations must point at real lines, and quoted code must exist. Patches must apply, then the
   tests run on a **throwaway copy** of the project. If the suite was already failing, a patch passes when it
   fixes at least one failing test and breaks none.
3. samples `best_of` answers (2 by default) and keeps a checked one. For questions it prefers the answer whose
   citations the others agree with; for patches, the smallest one that passes.
4. if none pass, retries `retries` times (1 by default) with the checker's notes, such as the failing test
   output, added to the prompt.
5. if it still fails, tries once with `escalate_model` (`[models.strong]`) when that is configured.

Nothing is applied to your files. The agent gets the checked patch and decides.

## Your agent's own subagents

With no helper model configured, `swarm` returns `subagent_tasks`: one ready prompt per task, with the context
pack and the required output format. Hand them to the Claude Code Task tool or OpenCode subagents, then check
what comes back with `swarm_verify`. `keelyard swarm plan "goal" --subagents` prints the same prompts.

## Cooperative mode (default)

`swarm` runs as a team, not as separate calls:

- **Planner → workers → verifier.** `swarm_plan` (or `keelyard swarm plan`) splits the goal. Workers draft,
  and keelyard checks every draft (citations exist, the patch applies and passes the tests in a copy).
- **Blackboard.** What one worker got verified, and what was tried and rejected, goes into the prompt of the
  next worker on the same files, capped at 1,200 characters.
- **Critic.** Each candidate that passes the checks is reviewed by a second call (`APPROVE` or
  `REJECT: reason`). A rejection sends the task back with the reason. Turn it off with `critic = false`.
- **Voting.** Among accepted candidates, the one most others agree with wins (same changed lines, or the
  same cited lines).
- **Cheapest capable model.** Tasks start on the first model in `ladder` and move up only when the checks
  fail. When a model keeps failing a kind of task (fewer than 1 in 3 after 3 tries), later tasks of that
  kind start one step higher.
- **Hard token budget.** Every call reserves its worst case (prompt characters / 3 plus `max_tokens`) before
  it is sent. A call that would cross `budget_tokens` or `task_budget_tokens` is refused, and the task
  reports `stopped: ... budget ... reached`. Results include `tokens`, `tokens_by_model` and
  `tokens_per_verified`.
- **Many workers.** `workers` sets how many tasks run at once. The tests run 250 tasks with more than 200
  calls in flight, and the token total matches exactly.

`keelyard swarm run tasks.json --basic`, or `cooperative = false`, gives the plain swarm.

## Configure

```toml
[models.cheap]
provider = "openai"            # any OpenAI-compatible endpoint, e.g. Ollama or vLLM
base_url = "http://localhost:11434/v1"
model = "qwen2.5-coder:7b"

[swarm]
best_of = 2
retries = 1
escalate_model = "strong"      # "" turns escalation off
test_patches = true
cooperative = true
ladder = ["cheap", "strong"]   # cheapest first; [] = helper_model then escalate_model
workers = 64
critic = true
budget_tokens = 200000         # hard cap per swarm call, 0 = none
task_budget_tokens = 20000
```

## Measured

On 5 small bug fixes with a 1.5B local model, the old single-shot swarm got 0 right and marked 2-3 wrong
patches as verified. The new pipeline got 4 of 5 right in both runs and marked no wrong patch verified, using
about half the input tokens. For questions, "verified" only means the cited lines exist: 5 were verified, 2-3
were right. Details: [Benchmarks](../BENCHMARKS.md#swarm-quality).
