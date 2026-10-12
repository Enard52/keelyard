# Swarm

Some work is wide rather than deep: summarising 40 files, or answering "where is X handled" across a package.
`swarm` sends tasks like these to a cheaper model in parallel and checks each answer:

- `ask` and `summarize` answers must cite `path:line`. The verifier checks that each cited line exists and
  matches what the answer says.
- `draft_edit` answers must be a patch that passes `git apply --check`. Drafts are never applied.
- `grep` runs locally and needs no model.

If no helper model is configured, the tool returns a plan for the agent's own subagents instead.
`swarm_verify` checks answers from any source, including those subagents.

Configure the helper in `.keelyard/config.toml`:

```toml
[models.cheap]
provider = "openai"            # any OpenAI-compatible endpoint, e.g. Ollama or vLLM
base_url = "http://localhost:11434/v1"
model = "qwen2.5-coder:7b"
```

## Measured

With a 1.5B local model, 3 of 12 tasks verified, and 0 of 8 answers cited a valid line. The verifier
caught every bad answer, but a model that small is not useful as a helper. Use a 7B or larger model.
