# Bounded application implementation

The Phoenix sand simulation exposed expensive retries on large Canvas/LiveView components, repeated discovery requests, and malformed output. Parser and sandbox repairs alone did not improve decomposition.

- Separate deterministic domain logic, rendering, input/lifecycle and assembly. Supply exact headers/interfaces, state representation, invariants and relevant behavioral tests. Start with a small independently compilable component; roughly 80–150 lines is a useful initial target for Spark, not a hard limit.
- Estimate generated code plus protocol overhead against the output budget. Split oversized work before running it. Do not solve truncation by repeatedly resending the whole project.
- Supply only relevant test excerpts and dependency interfaces. The orchestrator can inspect broad project guidelines and translate the applicable requirements. A worker implementing constants does not need the entire application test suite.
- The harness executes validation after operations. Tell the worker to produce missing files before asking to run their tests. Request capabilities for a concrete missing fact, and reuse returned evidence.
- Preflight compiler/runtime availability and sandboxed validation. Distinguish infrastructure failures from code failures; never spend model repairs on a known broken toolchain.
- After two failures with the same cause, inspect the raw response, narrow the component or correct the harness, and save a new plan. Keep every failed report. Do not loosen path/approval policy to accommodate malformed model output.
- The orchestrator writes acceptance tests and reviews behavior. Compile-only checks do not prove interactive controls, resize, cleanup, or physics. Use sanitizer and pseudo-terminal checks for C terminal programs; browser interaction checks for web apps.
- Never pass a complete implementation for the worker to echo and count it as successful delegation. Label any orchestrator implementation or repair separately.
- Keep evaluation reports outside the target repository. Otherwise lexical retrieval can pull earlier broken implementations back into worker context.
- For C, supply the shared header as an interface, explicitly require normal inclusion in implementation files, and reject copied header guards or invented headers. Compiler diagnostics catch syntax; test state transitions and capacity boundaries separately.
- Once a run passes semantic review, apply its verified checkpoint with `fresnel run --resume RUN_ID --apply`. Rerunning the plan can waste a new generation and produce different code.

The C Snake evaluation retained Spark's initializer (after a repair) and keyboard mapper (first pass, 155 output tokens). Movement and rendering required orchestrator replacement; food placement required semantic correction. Small output size alone did not guarantee correctness. Treat this as evidence for bounded helper delegation, not proof of general C capability or an A/B cost improvement.

Report accepted components, first-pass success, capability calls, repairs, worker input/output tokens, elapsed time, and orchestrator correction effort. Local tokens are not billable API tokens, but consume time and energy. Without measured coordinator usage and a comparable orchestrator-only baseline, do not claim a cost saving.
