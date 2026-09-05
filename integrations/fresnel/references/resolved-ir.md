# Resolved program IR handoff

Flow: user intent → orchestrator → resolved program IR → local source generation → compiler and behavioral tests → targeted repair → orchestrator review.

IR here is a language-neutral implementation specification, not a compiler binary format. Use the existing protocol 1.1 `implementation` list and `interfaces`/`invariants`; no new protocol version is required.

Before delegation, resolve the data representation, function signatures, state transitions in execution order, exact branch predicates, boundary handling, return/error behavior, and verified library APIs. Missing design decisions are an orchestrator blocker; missing factual API details may use bounded capability discovery. Keep each component small enough for its output budget.

Example interval merge IR: validate every input pair; sort a copy by start/end; maintain tuple accumulator; append when start > last end, otherwise replace last end with max(last end, end); return accumulator. Invariants: original input unchanged, nested intervals never reduce end, touching intervals merge. This communicates decisions without handing Spark finished source to copy.

The orchestrator owns independent tests. On failure pass the exact diagnostic, relevant source, violated invariant, and smallest affected target. Do not regenerate an entire application. Repeated same-cause failures require IR/toolchain review before more worker calls. A failed test can indicate a wrong specification or test, not just model failure.

`ask` is for bounded questions and experiments; use `run` for confined edits, executable gates, checkpoints and reviewed apply. Continuation appends missing response text; repair changes an erroneous implementation. Never confuse these operations or treat a completion marker as proof that code works.

Measure first-pass and post-repair acceptance, planner input/output and time, worker tokens/time, and review/correction effort. Greater worker reliability is not automatically lower total cost: a fully resolved specification moves reasoning to the orchestrator. Small paired trials establish feasibility, not general superiority.
