Plan, implement, verify. Use for any change that touches more than one function.

1. Restate the goal in one line. Write each thing the user asked for as a checkable item: proof_requirements.
   If something is ambiguous and expensive to get wrong, ask one question now, not later.
2. Locate before reading: find_symbol, then read_file with a line range. Do not read whole directories.
3. Plan the smallest change that satisfies every item. List the files you will touch. Name the test that will
   prove each item; if none exists, write it first and watch it fail (proof_run_tests phase="before").
4. Implement in small steps. After each step run the narrowest test (run_compact). If a step goes wrong,
   rewind_to the last good step instead of patching on top of the mess.
5. Verify: proof_run_tests phase="after", then proof_check each item with the command or path:line that
   proves it. Report what changed, what was proven, and anything you did not do.
