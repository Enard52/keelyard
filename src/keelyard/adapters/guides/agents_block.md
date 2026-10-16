## keelyard

This project uses keelyard (proof, rewind, smaller context). Rules:
- Before saying done: proof_requirements, proof_run_tests(phase="after"), proof_check each item. The Stop hook checks.
- Find code with find_symbol and read_file line ranges; repeat reads of unchanged files are skipped.
- Noisy commands: run_compact; recall(id) for the full output.
- Mistake? rewind_list, rewind_to. Every edit is a step.
- Workflows on demand: workflow("plan" | "debug" | "review").
