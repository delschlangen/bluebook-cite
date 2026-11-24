"""Last-resort liveness checks, for the two ways this server can be alive but useless.

A restart policy of ON_FAILURE restarts a process that exits, not one that is stuck, and a stuck
server looks, from outside, exactly like one that is down: the page can only say "could not reach
the server". Two things can leave it stuck, and neither can be interrupted from inside Python.

* A regular expression holds the interpreter lock for the whole of one match. A match that
  never ends (the shapes found so far are fixed, others may exist) stops the event loop, the
  timers and every other thread, so no Python code can notice. `faulthandler` can: its timer is
  a C thread that does not need the lock. It is re-armed every second by a task on the event
  loop; if the loop stops running it for `EVENT_LOOP_STALL_EXIT_S`, the timer prints every
  thread's stack to stderr (which names the pattern) and ends the process, and the platform
  starts a new one.
* A thread cannot be killed. If a CPU job outlives its request's deadline the page has been
  answered, but the job holds the single CPU slot until it ends, so every later analysis waits
  behind it. Past `CPU_JOB_MAX_S` the process is ended the same way.

Both end the process on purpose, which is why they are slow to act (45 s and 180 s, against about
2 s of work for a document at the size limit) and can be turned off with 0. A process ended this
way takes the requests that were running with it; the page sees the new `boot_id` and says the
server restarted.
"""

import asyncio
import faulthandler
import logging
import os
import sys
import time

log = logging.getLogger("bluebook")

STALL_EXIT_S = float(os.getenv("EVENT_LOOP_STALL_EXIT_S", "45"))
CPU_JOB_MAX_S = float(os.getenv("CPU_JOB_MAX_S", "180"))
TICK_S = 1.0

# Set and cleared on the event loop's thread only (see main._cpu), so no lock is needed.
_cpu_job_started: float | None = None


def cpu_job_started() -> None:
    global _cpu_job_started
    _cpu_job_started = time.monotonic()


def cpu_job_finished() -> None:
    global _cpu_job_started
    _cpu_job_started = None


def cpu_job_age() -> float:
    return 0.0 if _cpu_job_started is None else time.monotonic() - _cpu_job_started


def _die(reason: str) -> None:
    log.critical("%s: ending the process so the platform restarts it", reason)
    faulthandler.dump_traceback(file=sys.stderr, all_threads=True)
    sys.stderr.flush()
    os._exit(1)


async def run(
    stall_exit_s: float | None = None,
    cpu_job_max_s: float | None = None,
    tick_s: float = TICK_S,
    on_cpu_job_stuck=None,
) -> None:
    """Run for the life of the process, as a task on the event loop.

    `on_cpu_job_stuck` replaces ending the process, for tests."""
    stall = STALL_EXIT_S if stall_exit_s is None else stall_exit_s
    job_max = CPU_JOB_MAX_S if cpu_job_max_s is None else cpu_job_max_s
    stuck = on_cpu_job_stuck or _die
    try:
        while True:
            if stall > 0:
                # Re-arming cancels the previous timer. If this line is not reached again within
                # `stall` seconds, faulthandler's own thread dumps the stacks and exits.
                faulthandler.dump_traceback_later(stall, exit=True, file=sys.stderr)
            if job_max > 0 and cpu_job_age() > job_max:
                stuck(f"a CPU job has been running for {cpu_job_age():.0f} s")
                cpu_job_finished()  # only reached when `stuck` returns (tests)
            await asyncio.sleep(tick_s)
    finally:
        faulthandler.cancel_dump_traceback_later()
