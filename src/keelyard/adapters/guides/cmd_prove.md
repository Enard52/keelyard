---
description: Prove the current task is done (tests + evidence per requirement)
argument-hint: [extra requirement]
---
Finish the current task with evidence.
1. If `proof_status` shows no requirements, call `proof_requirements` with the user's asks (plus: $ARGUMENTS).
2. Call `proof_run_tests` with phase "after". If it fails, fix the cause first.
3. Call `proof_check` for each open requirement with concrete evidence (command + result, or path:line).
4. Call `proof_status` and report the result. Do not claim done unless it says proven.
