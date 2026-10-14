Debug loop. Use when something fails and the cause is not obvious.

1. Reproduce: get one command that shows the failure (run_compact). No reproduction, no fix.
2. Read the actual error and the stack's top frame in your code. Search memory_search for the error text.
3. Form one hypothesis that explains all of the evidence. Write it down in one sentence.
4. Test the hypothesis cheaply: a print, an assertion, or a smaller input. Change one thing at a time.
5. Wrong hypothesis twice? rewind_to before your experiments, re-read the evidence, widen the search.
6. Fix the cause, not the symptom. Add a test that failed before the fix and passes after.
7. Run the full suite once at the end (proof_run_tests phase="after").
