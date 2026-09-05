"""Small paired Spark evaluation; artifacts stay outside the target repository.

Run with PYTHONPATH=src python scripts/evaluate-resolved-ir.py /absolute/output.
This is a feasibility check, not a statistically powered cost benchmark.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

from fresnel.chat import complete
from fresnel.sandbox import clean_environment, command
from fresnel.supervisor import lease

TASKS = [
    (
        "sessions",
        (
            "Implement sessionize(events, gap=30). events is a list of (user, integer minute). "
            "Return one integer session ID per input row, starting at 1 per user. Process each "
            "user chronologically, split only for gaps strictly greater than gap. Preserve input "
            "order and do not mutate events. Negative gap raises ValueError."
        ),
        [
            "Output: list[int] length n; empty -> [].",
            "Validate gap before processing. Allocate IDs length n and a dict of user -> (last_time, session).",
            (
                "Sort indexed events by minute, retaining original index. For each event: unseen user -> session 1; "
                "otherwise increment previous session iff minute-last_time > gap. Update dict and write ID at original index."
            ),
            "Return IDs. Do not sort or mutate the caller's list.",
        ],
        (
            "assert sessionize([])==[]\na=[('a',60),('b',4),('a',0),('a',30),('a',91),('b',35)]\n"
            "b=a.copy()\nassert sessionize(a)==[1,1,1,1,2,2]\nassert a==b\n"
            "assert sessionize([('a',0),('a',0),('a',1)],0)==[1,1,2]\n"
            "try: sessionize([], -1)\nexcept ValueError: pass\nelse: raise AssertionError('negative gap')"
        ),
    ),
    (
        "intervals",
        (
            "Implement merge_intervals(intervals). Input is a list of integer (start,end) pairs. "
            "Return sorted merged closed intervals as tuples, merging touching endpoints. "
            "Do not mutate input. Reject start>end with ValueError, including later invalid intervals."
        ),
        [
            "Validate all pairs before merging. Empty -> []. Sort a new list by start then end.",
            (
                "Accumulator: list of tuples. For each (lo,hi), if accumulator empty or lo > last end, append tuple. "
                "Otherwise replace last tuple with (last start, max(last end,hi)). Return accumulator."
            ),
            "Nested intervals never reduce the current end. Touching endpoints merge. No external packages.",
        ],
        (
            "assert merge_intervals([])==[]\na=[(5,7),(1,10),(2,3),(10,12),(20,20)]\nb=a.copy()\n"
            "assert merge_intervals(a)==[(1,12),(20,20)]\nassert a==b\n"
            "assert merge_intervals([(3,4),(1,2)])==[(1,2),(3,4)]\n"
            "try: merge_intervals([(1,4),(8,3)])\nexcept ValueError: pass\nelse: raise AssertionError('invalid interval')"
        ),
    ),
]


def main():
    output = Path(sys.argv[1]).resolve()
    output.mkdir(parents=True, exist_ok=True)
    results = []
    with lease("resolved-ir-evaluation"):
        for name, task, ir, tests in TASKS:
            for mode in ("direct", "resolved_ir"):
                prompt = task + "\nReturn only Python source, no explanation."
                if mode == "resolved_ir":
                    prompt += (
                        "\nResolved program IR (translate faithfully; do not redesign):\n"
                        + json.dumps(ir)
                    )
                for attempt in range(2):
                    print(f"{name} {mode} attempt {attempt + 1}", flush=True)
                    result = complete(
                        "http://127.0.0.1:8081/v1/chat/completions",
                        prompt,
                        max_tokens=768,
                        temperature=0.15,
                        top_p=0.9,
                        top_k=40,
                        min_p=0,
                    )
                    source = result["content"].strip()
                    match = re.fullmatch(r"```(?:python)?\s*\n(.*?)\n```", source, re.DOTALL)
                    if match:
                        source = match[1]
                    # Generated artifacts are isolated; use Fresnel's network-denied sandbox.
                    run = subprocess.run(
                        command(output, (sys.executable, "-I", "-c", source + "\n" + tests)),
                        cwd=output,
                        env=clean_environment(output),
                        capture_output=True,
                        text=True,
                        timeout=10,
                        check=False,
                    )
                    record = {
                        "task": name,
                        "mode": mode,
                        "attempt": attempt + 1,
                        "passed": run.returncode == 0,
                        "response": result,
                        "error": run.stderr[-4000:],
                    }
                    results.append(record)
                    (output / "results.json").write_text(json.dumps(results, indent=2))
                    if run.returncode == 0:
                        break
                    prompt += (
                        "\nRepair only the failing behavior. Previous source:\n"
                        + source
                        + "\nTest diagnostics:\n"
                        + run.stderr[-2000:]
                    )
    print(json.dumps([{k: v for k, v in r.items() if k != "response"} for r in results], indent=2))


if __name__ == "__main__":
    main()
