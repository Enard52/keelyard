# Smaller context

## Output filters

`keelyard run <command>` runs a command and prints a shorter version of its output. Filters exist for
`git status/log/diff`, pytest, cargo, go and jest tests, grep and rg, find and ls, and ruff, eslint and mypy.
Every failure, error and `file:line` is kept; what is dropped is repetition and progress noise. The filtered
output is never longer than the original.

In Claude Code the same filters run on Bash results through `PostToolUse`. The command itself is not
changed, only what the model reads. Each shortened output ends with an id, and `keelyard recall <id>`
(or the MCP `recall` tool) returns the full text.

```bash
keelyard run pytest -q
keelyard run -- git log --stat -n 50
pytest -v 2>&1 | keelyard filter --for "pytest -v"
```

On 8 real commands, the filters cut 56,522 tokens to 5,901 and kept 100% of the facts we extracted
([method](../BENCHMARKS.md)).

## Deduplicated reads

When the agent reads a file it has already read in this session, and the file has not changed, keelyard
answers with a one-line notice instead of the file. If the file changed, the MCP `read_file` tool returns
only the diff. When the agent's context is compacted, this memory is cleared so it can read again.

## Structure first

- `project_map`: files per directory, with approximate token sizes
- `outline path`: classes and signatures with line numbers (Python is parsed properly; other languages use patterns)
- `find_symbol name`: where something is defined

```bash
keelyard code map
keelyard code outline src/cart.py
keelyard code find Cart
```
