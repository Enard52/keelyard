---
description: Undo recent edits with keelyard rewind
argument-hint: [step]
---
Call `rewind_list`. If a step was given ($ARGUMENTS), call `rewind_diff` on it, then `rewind_to` it.
Otherwise show the last 10 steps with their files and ask which one to go back to.
After rewinding, tell the user the `safety_step` they can use to undo the rewind.
