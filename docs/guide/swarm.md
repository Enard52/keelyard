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
```

## Measured

See [Benchmarks](../BENCHMARKS.md#swarm-quality). Short version: with a 1.5B local model the checks remove
every false "verified" patch, and context packs cut input tokens per call about 6x. Neither makes a 1.5B
model good at fixing bugs. Use 7B or larger for real work.
