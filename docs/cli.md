# CLI reference

Generated from `keelyard --help` by `docs/demo/gen_reference.py`.

Every command accepts `--json` and prints exactly one JSON object with `ok` and `exit` keys.

```text
usage: keelyard <command> [options]

keelyard makes coding agents prove their work, lets you undo any step,
and keeps their context small. Works with Claude Code, Codex and OpenCode.

start here:
  init              set up this project and wire every agent it finds
  doctor            check that everything is installed and wired correctly
  status            what keelyard knows about this project right now

everyday:
  rewind            list, inspect and undo agent steps
  proof             the evidence an agent collected before saying "done"
  run               run a command and print a compact version of its output
  code              outline a file, map the project, find a symbol
  memory            search past sessions across all your agents
  usage             tokens and cost from your local agent logs

more:
  swarm             fan small, checkable tasks out to a cheap model
  arena             run one task across agents and models, compare results
  bench             measure savings on your own machine
  selftest          a scripted agent completes a full task through the agent interface
  install/uninstall wire or unwire one agent by hand
  filter            compact output piped on stdin
  recall            print the full output that `run` shortened

options:
  -h, --help   show this help message and exit
  --version    show program's version number and exit

commands:
  <command>
    init       set up this project and wire the agents found on this machine
    doctor     check the installation and wiring; exits 3 if something is broken
    status     show what keelyard knows about this project
    selftest   a scripted agent runs a full task through MCP and hooks in a temp folder
    install    wire one agent in this project
    uninstall  unwire one agent in this project
    rewind     list, inspect and undo agent steps
    proof      the evidence an agent collected before saying done
    run        run a command and print a compact version of its output
    filter     compact output piped on stdin
    recall     print the full output that `run` shortened
    code       outline a file, map the project, find a symbol
    memory     search past sessions across all your agents
    usage      tokens and cost from your local agent logs
    swarm      fan small, checkable tasks out to a cheap model
    arena      run one task across agents and models, compare results
    bench      measure savings on your own machine

exit codes:
  0  success
  1  error (the message says what went wrong and how to fix it)
  2  usage error (bad command or arguments)
  3  a check did not pass (doctor found a problem, proof not complete, tests failed, selftest failed)
  `keelyard run` exits with the code of the command it ran.

Run `keelyard <command> --help` for examples. Every command accepts --json.
```

## init

```text
usage: keelyard <command> [options] init [-h] [--json] [--agent {claude,codex,opencode}]
                                         [--no-agents] [--dry-run] [--global]

set up this project and wire the agents found on this machine

options:
  -h, --help            show this help message and exit
  --json                print one JSON object on stdout (for scripts and agents)
  --agent {claude,codex,opencode}
                        wire only this agent (repeatable)
  --no-agents           create the config but wire no agent
  --dry-run             print what would change and stop
  --global              wire the agents for every project of this user (~/.claude, ~/.codex,
                        ~/.config/opencode); projects set themselves up on their first session

examples:
  keelyard init                    # detect agents, wire them, take a first snapshot
  keelyard init --agent claude     # only Claude Code
  keelyard init --dry-run          # show what would change
```

## doctor

```text
usage: keelyard <command> [options] doctor [-h] [--json]

check the installation and wiring; exits 3 if something is broken

options:
  -h, --help  show this help message and exit
  --json      print one JSON object on stdout (for scripts and agents)

examples:
  keelyard doctor
  keelyard doctor --json
```

## status

```text
usage: keelyard <command> [options] status [-h] [--json]

show what keelyard knows about this project

options:
  -h, --help  show this help message and exit
  --json      print one JSON object on stdout (for scripts and agents)

examples:
  keelyard status
  keelyard status --json
```

## selftest

```text
usage: keelyard <command> [options] selftest [-h] [--json] [--keep]

a scripted agent runs a full task through MCP and hooks in a temp folder

options:
  -h, --help  show this help message and exit
  --json      print one JSON object on stdout (for scripts and agents)
  --keep      keep the temporary project

examples:
  keelyard selftest
  keelyard selftest --keep   # keep the temp project to inspect
```

## rewind

```text
usage: keelyard <command> [options] rewind [-h] <action> ...

list, inspect and undo agent steps

options:
  -h, --help  show this help message and exit

actions:
  <action>
    list      list snapshots
    show      show the diff a step made
    to        restore files to a step (undoable)
    fork      copy a step into a new folder
    snap      take a snapshot now

examples:
  keelyard rewind                  # every step agents took, newest last
  keelyard rewind list -i          # browse steps and diffs full-screen
  keelyard rewind show 12          # the diff that step 12 made
  keelyard rewind to 9             # put the files back as they were after step 9
  keelyard rewind fork 9 ../try-b  # copy step 9 into another folder
  keelyard rewind snap             # take a snapshot by hand
```

### rewind list

```text
usage: keelyard <command> [options] rewind list [-h] [--json] [-i] [-n N]

list snapshots

options:
  -h, --help         show this help message and exit
  --json             print one JSON object on stdout (for scripts and agents)
  -i, --interactive  open the timeline browser
  -n N               show the last N steps (default 30)
```

### rewind show

```text
usage: keelyard <command> [options] rewind show [-h] [--json] step

show the diff a step made

positional arguments:
  step

options:
  -h, --help  show this help message and exit
  --json      print one JSON object on stdout (for scripts and agents)
```

### rewind to

```text
usage: keelyard <command> [options] rewind to [-h] [--json] step

restore files to a step (undoable)

positional arguments:
  step

options:
  -h, --help  show this help message and exit
  --json      print one JSON object on stdout (for scripts and agents)
```

### rewind fork

```text
usage: keelyard <command> [options] rewind fork [-h] [--json] step dest

copy a step into a new folder

positional arguments:
  step
  dest

options:
  -h, --help  show this help message and exit
  --json      print one JSON object on stdout (for scripts and agents)
```

### rewind snap

```text
usage: keelyard <command> [options] rewind snap [-h] [--json]

take a snapshot now

options:
  -h, --help  show this help message and exit
  --json      print one JSON object on stdout (for scripts and agents)
```

## proof

```text
usage: keelyard <command> [options] proof [-h] <action> ...

the evidence an agent collected before saying done

options:
  -h, --help  show this help message and exit

actions:
  <action>
    status    what is proven and what is missing
    add       add requirements
    check     mark a requirement met, with evidence
    test      run the test command and record the result
    shot      screenshot the app
    report    write the HTML report

examples:
  keelyard proof status
  keelyard proof add "discount applies once" "empty cart costs 0"
  keelyard proof check 1 "test_discount_once passes"
  keelyard proof test after
  keelyard proof report            # writes an HTML report
```

### proof status

```text
usage: keelyard <command> [options] proof status [-h] [--json]

what is proven and what is missing

options:
  -h, --help  show this help message and exit
  --json      print one JSON object on stdout (for scripts and agents)
```

### proof add

```text
usage: keelyard <command> [options] proof add [-h] [--json] items [items ...]

add requirements

positional arguments:
  items

options:
  -h, --help  show this help message and exit
  --json      print one JSON object on stdout (for scripts and agents)
```

### proof check

```text
usage: keelyard <command> [options] proof check [-h] [--json] id evidence

mark a requirement met, with evidence

positional arguments:
  id
  evidence

options:
  -h, --help  show this help message and exit
  --json      print one JSON object on stdout (for scripts and agents)
```

### proof test

```text
usage: keelyard <command> [options] proof test [-h] [--json] [--cmd TEST_CMD] {before,after}

run the test command and record the result

positional arguments:
  {before,after}

options:
  -h, --help      show this help message and exit
  --json          print one JSON object on stdout (for scripts and agents)
  --cmd TEST_CMD  override [proof].test_cmd
```

### proof shot

```text
usage: keelyard <command> [options] proof shot [-h] [--json] [url]

screenshot the app

positional arguments:
  url

options:
  -h, --help  show this help message and exit
  --json      print one JSON object on stdout (for scripts and agents)
```

### proof report

```text
usage: keelyard <command> [options] proof report [-h] [--json] [--open]

write the HTML report

options:
  -h, --help  show this help message and exit
  --json      print one JSON object on stdout (for scripts and agents)
  --open      open it in the browser
```

## run

```text
usage: keelyard <command> [options] run [-h] [--json] ...

run a command and print a compact version of its output

positional arguments:
  command

options:
  -h, --help  show this help message and exit
  --json      print one JSON object on stdout (for scripts and agents)

examples:
  keelyard run pytest -q
  keelyard run git log --stat
  keelyard run -- ruff check .     # use -- if the command has its own flags first
```

## filter

```text
usage: keelyard <command> [options] filter [-h] [--json] [--for FOR_CMD]

compact output piped on stdin

options:
  -h, --help     show this help message and exit
  --json         print one JSON object on stdout (for scripts and agents)
  --for FOR_CMD  the command that produced the output (picks the rules)

examples:
  pytest -q 2>&1 | keelyard filter --for 'pytest -q'
```

## recall

```text
usage: keelyard <command> [options] recall [-h] [--json] id

print the full output that `run` shortened

positional arguments:
  id

options:
  -h, --help  show this help message and exit
  --json      print one JSON object on stdout (for scripts and agents)

examples:
  keelyard recall 3f9a1c2b7d4e
```

## code

```text
usage: keelyard <command> [options] code [-h] <action> ...

outline a file, map the project, find a symbol

options:
  -h, --help  show this help message and exit

actions:
  <action>
    outline   signatures only
    map       compact project map
    find      where a symbol is defined

examples:
  keelyard code outline src/app.py
  keelyard code map
  keelyard code find Cart
```

### code outline

```text
usage: keelyard <command> [options] code outline [-h] [--json] path

signatures only

positional arguments:
  path

options:
  -h, --help  show this help message and exit
  --json      print one JSON object on stdout (for scripts and agents)
```

### code map

```text
usage: keelyard <command> [options] code map [-h] [--json]

compact project map

options:
  -h, --help  show this help message and exit
  --json      print one JSON object on stdout (for scripts and agents)
```

### code find

```text
usage: keelyard <command> [options] code find [-h] [--json] name

where a symbol is defined

positional arguments:
  name

options:
  -h, --help  show this help message and exit
  --json      print one JSON object on stdout (for scripts and agents)
```

## memory

```text
usage: keelyard <command> [options] memory [-h] <action> ...

search past sessions across all your agents

options:
  -h, --help  show this help message and exit

actions:
  <action>
    index     read new sessions from Claude Code, Codex and OpenCode
    stats     what is indexed
    search    full-text search

examples:
  keelyard memory index            # read new sessions from all agents
  keelyard memory search "rate limit retry"
  keelyard memory stats
```

### memory index

```text
usage: keelyard <command> [options] memory index [-h] [--json]

read new sessions from Claude Code, Codex and OpenCode

options:
  -h, --help  show this help message and exit
  --json      print one JSON object on stdout (for scripts and agents)
```

### memory search

```text
usage: keelyard <command> [options] memory search [-h] [--json] [--project PROJECT]
                                                  [--budget BUDGET]
                                                  query

full-text search

positional arguments:
  query

options:
  -h, --help         show this help message and exit
  --json             print one JSON object on stdout (for scripts and agents)
  --project PROJECT
  --budget BUDGET    max characters returned (default 2400)
```

### memory stats

```text
usage: keelyard <command> [options] memory stats [-h] [--json]

what is indexed

options:
  -h, --help  show this help message and exit
  --json      print one JSON object on stdout (for scripts and agents)
```

## usage

```text
usage: keelyard <command> [options] usage [-h] [--json] [--by {day,model,agent}]

tokens and cost from your local agent logs

options:
  -h, --help            show this help message and exit
  --json                print one JSON object on stdout (for scripts and agents)
  --by {day,model,agent}

examples:
  keelyard usage
  keelyard usage --by model
```

## swarm

```text
usage: keelyard <command> [options] swarm [-h] <action> ...

fan small, checkable tasks out to a cheap model

options:
  -h, --help  show this help message and exit

actions:
  <action>
    run       run tasks from a JSON file
    plan      split a goal into focused helper tasks (no model call)

examples:
  keelyard swarm plan "fix total() for SAVE10" --json > tasks.json
  keelyard swarm run tasks.json   # [{"kind": "ask", "prompt": "...", "files": ["a.py"], "symbols": ["total"]}]
  keelyard swarm plan "where is auth checked" --subagents
```

### swarm run

```text
usage: keelyard <command> [options] swarm run [-h] [--json] [--model MODEL] [--best-of BEST_OF]
                                              [--retries RETRIES] [--basic]
                                              tasks

run tasks from a JSON file

positional arguments:
  tasks

options:
  -h, --help         show this help message and exit
  --json             print one JSON object on stdout (for scripts and agents)
  --model MODEL      a [models.<key>] from the config (default: [swarm].helper_model)
  --best-of BEST_OF  samples per task (default: [swarm].best_of)
  --retries RETRIES  retries with checker feedback (default: [swarm].retries)
  --basic            no blackboard, critic, routing or budget (the plain swarm)
```

## arena

```text
usage: keelyard <command> [options] arena [-h] <action> ...

run one task across agents and models, compare results

options:
  -h, --help  show this help message and exit

actions:
  <action>
    run       run a task spec
    render    re-render the report from results.json

examples:
  keelyard arena run examples/arena/discount/task.toml
  keelyard arena render arena-results
```

### arena run

```text
usage: keelyard <command> [options] arena run [-h] [--json] [--out OUT] [--only [NAME ...]] spec

run a task spec

positional arguments:
  spec

options:
  -h, --help         show this help message and exit
  --json             print one JSON object on stdout (for scripts and agents)
  --out OUT
  --only [NAME ...]  only these contenders
```

### arena render

```text
usage: keelyard <command> [options] arena render [-h] [--json] out

re-render the report from results.json

positional arguments:
  out

options:
  -h, --help  show this help message and exit
  --json      print one JSON object on stdout (for scripts and agents)
```

## bench

```text
usage: keelyard <command> [options] bench [-h] [--json]

measure savings on your own machine

options:
  -h, --help  show this help message and exit
  --json      print one JSON object on stdout (for scripts and agents)

examples:
  keelyard bench
  keelyard bench --json
```

## install

```text
usage: keelyard <command> [options] install [-h] [--json] [--global] [{claude,codex,opencode}]

wire one agent in this project

positional arguments:
  {claude,codex,opencode}

options:
  -h, --help            show this help message and exit
  --json                print one JSON object on stdout (for scripts and agents)
  --global              wire at user level (all agents if none named)

examples:
  keelyard install claude
  keelyard install --global
```

## uninstall

```text
usage: keelyard <command> [options] uninstall [-h] [--json] [--global] [{claude,codex,opencode}]

unwire one agent in this project

positional arguments:
  {claude,codex,opencode}

options:
  -h, --help            show this help message and exit
  --json                print one JSON object on stdout (for scripts and agents)
  --global              unwire at user level (all agents if none named)

examples:
  keelyard uninstall claude
  keelyard uninstall --global
```
