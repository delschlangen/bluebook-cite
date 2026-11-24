"""A stand-in for app.services.parse_worker that misbehaves on request, so the tests can prove
what the parent does about a child that hangs, spins inside a regular expression, floods stdout,
crashes with a signal or exits without an answer. The mode is the upload's file name.

    python -E -s -m tests.fake_worker        (started by sandbox.py when it is pointed here)
"""
import json
import os
import re
import signal
import sys
import time

PROTOCOL = 1


def _result(text: str = "ok", **extra) -> bytes:
    body = {"v": PROTOCOL, "ok": True, "format": "txt", "text": text, "footnote_count": 0,
            "endnote_count": 0, "warnings": []}
    body.update(extra)
    return json.dumps(body).encode()


def main() -> None:
    header = json.loads(sys.stdin.buffer.readline())
    mode = header.get("filename") or "ok"
    if mode == "noread":
        os._exit(0)
    sys.stdin.buffer.read(header["size"])
    out = sys.stdout.buffer

    name, _, arg = mode.partition("|")
    if name == "ok":
        out.write(_result())
    elif name == "sleep":                       # sleep|<seconds>: a slow but fine document
        time.sleep(float(arg))
        out.write(_result("slept"))
    elif name == "hang":                        # hang|<pidfile>: never answers
        if arg:
            with open(arg, "w") as handle:
                handle.write(str(os.getpid()))
        time.sleep(600)
    elif name == "spin":                        # a regular expression that holds the interpreter lock
        if arg:
            with open(arg, "w") as handle:
                handle.write(str(os.getpid()))
        re.match(r"(a+)+$", "a" * 60 + "!")
    elif name == "flood":                       # writes far more than any document may produce
        chunk = b"x" * (1 << 20)
        for _ in range(64):
            out.write(chunk)
            out.flush()
    elif name == "segv":
        os.kill(os.getpid(), signal.SIGSEGV)
        time.sleep(5)
    elif name == "abort":
        os.kill(os.getpid(), signal.SIGABRT)
        time.sleep(5)
    elif name == "exit1":
        os._exit(1)
    elif name == "junk":
        out.write(b"this is not json")
    elif name == "badversion":
        out.write(json.dumps({"v": 99, "ok": True, "text": "x"}).encode())
    elif name == "env":                         # what the child can see of the parent
        report = {
            "env_keys": sorted(os.environ),
            "cwd": os.getcwd(),
            "ignore_environment": sys.flags.ignore_environment,
            "no_user_site": sys.flags.no_user_site,
        }
        out.write(_result(json.dumps(report)))
    elif name == "stderr_flood":                # fills the stderr pipe; the parent must keep draining it
        sys.stderr.write("e" * (1 << 22))
        sys.stderr.flush()
        out.write(_result("drained"))
    elif name == "kind":                        # kind|<kind>|<message>: a refusal, as the real worker writes it
        kind, _, message = arg.partition("|")
        out.write(json.dumps({"v": PROTOCOL, "ok": False, "kind": kind, "message": message}).encode())
    out.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
