# Memory and recovery

Fresnel stores an immutable task charter, an append-only event ledger, a compact situation
model derived from events, exact evidence blobs, named `ask` sessions, and validated procedural
playbooks. Repository facts never cross project boundaries; only generalized, evaluated playbooks
may be global.

At the start of each worker attempt, reconstruct current state from the charter, event ledger, Git
diff, and validation evidence. Retrieve exact file or documentation excerpts just in time. Do not
use a growing transcript as memory and do not ask Spark to decide what permanent lesson to keep.

```bash
fresnel memory status --repo /absolute/repo
fresnel memory inspect --run RUN_ID
fresnel memory replay RUN_ID
fresnel memory gc --dry-run
```

After interruption, replay first. Resume only from evidence that is still fresh for the current
repository hashes. Never treat generated summaries as stronger evidence than code or validation.
