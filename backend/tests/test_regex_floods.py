"""No regular expression in the app, and no stage built on them, may take quadratic time on a
flood of one repeated shape.

Why this exists. A regex holds the interpreter lock for the whole of one match, so a slow one
freezes the event loop, the timers and every other thread, and the server's own deadline cannot
fire (it was measured: a deadline of 10 s answered after 44 s, and 100,000 digits never
finished). Three of these were found by reviewers after the "no more freezes" tests had passed,
because those tests used `time.sleep` stand-ins that release the lock and so cannot see the
problem. This test runs the real code over floods in a separate process that it can kill, so a
freeze is a failure with a name and not a hung suite.

What it does not prove. It tries about 50 shapes, not all shapes. A pattern that is only slow on
input nobody thought of passes. The process-level watchdog (app/watchdog.py) is the net under it.
"""

import selectors
import subprocess
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
HARNESS = Path(__file__).resolve().parent / "regex_flood_harness.py"

# One item taking longer than this is a failure. A linear pattern takes milliseconds on 30,000
# characters; the quadratic ones took 4 to 30 seconds, so this has a wide margin both ways.
SLOW_SECONDS = 1.0
# No output at all for this long means one item never finished.
STALL_SECONDS = 20.0
WHOLE_RUN_SECONDS = 600.0


def _run_harness(size: int):
    """Run the harness; returns (slow items, the item that hung or None, lines seen)."""
    proc = subprocess.Popen(
        [sys.executable, str(HARNESS), str(size)],
        cwd=BACKEND, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
    )
    slow: list[tuple[float, str]] = []
    current = None
    finished = False
    seen = 0
    started = time.monotonic()
    selector = selectors.DefaultSelector()
    selector.register(proc.stdout, selectors.EVENT_READ)
    last_output = time.monotonic()
    try:
        while True:
            if time.monotonic() - started > WHOLE_RUN_SECONDS:
                return slow, f"the whole run took over {WHOLE_RUN_SECONDS:.0f} s (last: {current})", seen
            if not selector.select(timeout=1.0):
                if time.monotonic() - last_output > STALL_SECONDS:
                    return slow, current or "(before the first item)", seen
                if proc.poll() is not None:
                    break
                continue
            line = proc.stdout.readline()
            if not line:
                break
            last_output = time.monotonic()
            seen += 1
            if line.startswith("START "):
                current = line[6:].strip()
            elif line.startswith("DONE "):
                _, seconds, label = line.strip().split(" ", 2)
                if float(seconds) > SLOW_SECONDS:
                    slow.append((float(seconds), label))
                current = None
            elif line.startswith("FINISHED"):
                finished = True
            elif line.startswith("NOTE could not import"):
                slow.append((0.0, line.strip()))
        if not finished and current is None and proc.poll() not in (0, None):
            slow.append((0.0, f"the harness exited with status {proc.returncode}"))
        return slow, None, seen
    finally:
        proc.kill()
        proc.wait(timeout=10)


def test_nothing_is_quadratic_on_a_flood():
    slow, hung, seen = _run_harness(30_000)

    assert seen > 1000, f"the harness barely ran ({seen} lines): discovery is broken"
    report = "\n".join(f"  {seconds:6.2f} s  {label}" for seconds, label in sorted(slow, reverse=True))
    assert hung is None, f"one item never finished: {hung}\nslow before it:\n{report}"
    assert not slow, f"items slower than {SLOW_SECONDS} s on 30,000 characters:\n{report}"
