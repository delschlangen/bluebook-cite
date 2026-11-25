"""Find every regular expression in the app, wherever it is written, and attack each one with
input built from the pattern itself.

    python tests/regex_inline_scan.py        (run by tests/test_regex_inline.py)

Why this exists as well as regex_flood_harness.py. That harness finds patterns that are compiled
at import time (module and class attributes) and floods them with about fifty fixed shapes. Six
freezes got past it, found by reviewers after it was in place:

    main.py              re.match(r"(\\d+)\\s+([A-Za-z.\\s]+)\\s+(\\d+)", citation)     cubic
    lookup_service.py    re.search(r"(\\d+)\\s*U\\.?S\\.?C\\.?...", text)              quadratic
    source_finder.py     re.findall(r"([A-Z][a-zA-Z]+)\\s+v\\.\\s+...", sentence)     quadratic
    transforms.py        re.sub(r"\\B(?=(\\d{3})+(?!\\d))", ",", digits)             quadratic

for two reasons. They are written inline in a function body, so nothing at import time holds
them; and most need a particular beginning before the repeated part ("1" then 3,000 spaces), which
a flood of one repeated shape never has. A 3 KB request was enough to hold the event loop for 45
seconds, at which point the watchdog ended the process.

What this does.
1. Reads the source of every module under app/ and collects each call to re.match, re.search,
   re.sub, re.split, re.findall, re.finditer, re.fullmatch and re.compile, plus every pattern the
   older harness finds at import time. A pattern that cannot be worked out from the source (it is
   built from a function's arguments) is reported as UNRESOLVED, and the test fails on it unless
   it is listed below with the reason it is safe: a pattern nobody can test is not allowed in.
2. For each pattern, walks its parsed form. For every repetition that is unbounded or large, it
   builds an attack: the shortest text that matches everything before the repetition, then the
   repeated part `size` times, then a character that makes the match fail. That is the input that
   makes a careless pattern back off through every split of the run (cubic) or start again from
   every position in it (quadratic).
3. Times the call the way the app makes it: `match` for re.match and re.fullmatch (anchored, so no
   restarts), `finditer` for everything else and for import-time patterns whose use is unknown.
   Each attack is tried at sizes growing from 16 to 25,600 characters and reported as SLOW at the first
   size that takes over 0.05 s (a linear pattern needs a few milliseconds at most at any of them).

It prints START / DONE lines like the other harness so that a hang has a name. It proves nothing
about inputs it did not build; the watchdog remains underneath.
"""

import ast
import importlib
import pkgutil
import re
import re._constants as sre_c
import re._parser as sre_parse
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

RE_FUNCTIONS = {"match", "fullmatch", "search", "sub", "subn", "split", "findall", "finditer", "compile"}
ANCHORED = {"match", "fullmatch"}

# A repetition allowed at least this many times is treated as unbounded: 30,000 characters of
# input can drive it that far. Smaller bounds cannot cost more than the bound squared.
LARGE = 200

# Each attack is tried at growing sizes and stopped at the first one that is slow, so that a
# cubic or exponential pattern is caught at a size where it still returns. The small sizes grow
# by 15% at a time because an exponential pattern can go from a millisecond to a minute within
# ten characters ("(a+)+$" was 0.02 s at 20 characters and never returned at 400); the large ones
# grow fourfold, which is enough to tell linear from quadratic. A linear pattern takes a few
# milliseconds at most at every one of these. The last size is there for the mild quadratic
# ones: "\\s+v\\.?\\s+" under re.split took 0.04 s at 6,400 spaces and 3 s at 60,000.
def _tiers() -> tuple[int, ...]:
    sizes, n = [], 16.0
    while n < 400:
        sizes.append(int(n))
        n *= 1.15
    return tuple(dict.fromkeys(sizes + [400, 1600, 6400, 25600]))


TIERS = _tiers()
BORDERLINE_SECONDS = 0.008
LAST_RESORT = TIERS[-1] * 4
SLOW_SECONDS = 0.05

# Inline patterns that cannot be worked out from the source, with the reason each is safe.
# Format: "module:function" -> reason. Every entry is a pattern nobody attacks here, so keep it
# short and say where it IS covered.
UNRESOLVED_ALLOWED: dict[str, str] = {
    "app.services.source_finder:__init__": (
        "compiled once into the ClaimDetector instance; the import-time discovery visits it"
    ),
    "app.services.spec_engine:__init__": (
        "compiled once from the citation spec into ENGINE; the import-time discovery visits it"
    ),
    "app.services.transforms:institution": (
        "a literal phrase from a fixed table between word boundaries: no repetition to attack"
    ),
    "app.utils.bluebook_patterns:abbreviate_party_name": (
        "re.escape of a word from a fixed table between word boundaries: no repetition to attack"
    ),
}


# --- 1. collecting the patterns ---------------------------------------------------------------


def _modules():
    import app  # noqa: PLC0415

    out = [app]
    for info in pkgutil.walk_packages(app.__path__, "app."):
        try:
            out.append(importlib.import_module(info.name))
        except Exception as exc:
            print(f"NOTE could not import {info.name}: {exc!r}", flush=True)
    return out


def _is_re_call(node: ast.Call) -> str | None:
    f = node.func
    if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "re" and f.attr in RE_FUNCTIONS:
        return f.attr
    return None


_ALLOWED_NODES = (
    ast.Expression, ast.Constant, ast.Name, ast.Load, ast.JoinedStr, ast.FormattedValue,
    ast.BinOp, ast.Add, ast.BitOr, ast.Attribute, ast.Mod, ast.Tuple, ast.List,
)


def _evaluate(node: ast.AST, namespace: dict):
    """The value of a pattern or flags expression, using the module's own globals. Only names,
    constants, f-strings, concatenation and `|` are evaluated; anything else is 'unknown'."""
    for sub in ast.walk(node):
        if not isinstance(sub, _ALLOWED_NODES):
            raise ValueError(f"not a constant expression ({type(sub).__name__})")
    scope = {"re": re, **namespace}
    return eval(compile(ast.Expression(node), "<pattern>", "eval"), scope)  # noqa: S307


def _local_values(function: ast.AST, name: str, namespace: dict) -> list:
    """Every constant value a local variable can hold: `name = "..."`, or `for name in [...]`
    over a list written in the function (directly or through another local name)."""
    values: list = []
    for node in ast.walk(function):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            values.append(_evaluate(node.value, namespace))
        elif isinstance(node, ast.For) and isinstance(node.target, ast.Name) and node.target.id == name:
            source = node.iter
            if isinstance(source, ast.Name):
                for items in _local_values(function, source.id, namespace):
                    values.extend(items)
            else:
                values.extend(_evaluate(source, namespace))
    if not values:
        raise NameError(f"name {name!r} is not a constant in this function")
    return values


def _pattern_values(node: ast.AST, function: ast.AST | None, namespace: dict) -> list:
    try:
        return [_evaluate(node, namespace)]
    except NameError:
        if isinstance(node, ast.Name) and function is not None:
            return _local_values(function, node.id, namespace)
        raise


def inline_patterns():
    """(label, pattern, flags, anchored) for each re.* call in the source, and a list of
    (label, reason) for the ones that could not be resolved."""
    found, unresolved = [], []
    for module in _modules():
        path = getattr(module, "__file__", None)
        if not path or not path.endswith(".py"):
            continue
        tree = ast.parse(Path(path).read_text(encoding="utf-8"))
        # which function each call sits in, for a readable label
        owner: dict[int, ast.AST] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                for sub in ast.walk(node):
                    owner[id(sub)] = node          # the innermost function wins (walk is outer first)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function = _is_re_call(node)
            if not function or not node.args:
                continue
            enclosing = owner.get(id(node))
            where = enclosing.name if enclosing is not None else None
            if function == "compile" and where is None:
                continue  # module level: the import-time discovery has it, with its real flags
            label = f"{module.__name__}:{where or '<module>'}:{node.lineno} re.{function}"
            try:
                patterns = _pattern_values(node.args[0], enclosing, vars(module))
                flags = 0
                flag_nodes = [k.value for k in node.keywords if k.arg == "flags"]
                positional = {"compile": 1, "match": 2, "fullmatch": 2, "search": 2, "findall": 2,
                              "finditer": 2, "split": 3, "sub": 4, "subn": 4}[function]
                if len(node.args) > positional:
                    flag_nodes.append(node.args[positional])
                for flag_node in flag_nodes:
                    flags |= int(_evaluate(flag_node, vars(module)))
                for pattern in patterns:
                    if isinstance(pattern, re.Pattern):
                        pattern = pattern.pattern
                    if not isinstance(pattern, str | bytes):
                        raise ValueError(f"pattern is a {type(pattern).__name__}")
                    found.append((label, pattern, flags, function in ANCHORED))
            except Exception as exc:
                key = f"{module.__name__}:{where or '<module>'}"
                if key not in UNRESOLVED_ALLOWED:
                    unresolved.append((label, f"{type(exc).__name__}: {exc}"))
    return found, unresolved


# --- 2. building the attacks ------------------------------------------------------------------

_PREFERRED = "a1 A.-_/,:;§&'\"()[]\n\t"


def _char_for_class(items, negate_outer=False) -> str:
    """One character that the character class accepts."""
    negate = False
    accept: list = []
    for op, arg in items:
        if op is sre_c.NEGATE:
            negate = True
        else:
            accept.append((op, arg))

    def inside(ch: str) -> bool:
        code = ord(ch)
        for op, arg in accept:
            if op is sre_c.LITERAL and code == arg:
                return True
            if op is sre_c.RANGE and arg[0] <= code <= arg[1]:
                return True
            if op is sre_c.CATEGORY:
                name = str(arg)
                hit = (
                    ("DIGIT" in name and ch.isdigit())
                    or ("SPACE" in name and ch.isspace())
                    or ("WORD" in name and (ch.isalnum() or ch == "_"))
                )
                if "NOT" in name:
                    hit = not (
                        ("DIGIT" in name and ch.isdigit())
                        or ("SPACE" in name and ch.isspace())
                        or ("WORD" in name and (ch.isalnum() or ch == "_"))
                    )
                if hit:
                    return True
        return False

    for ch in _PREFERRED + "".join(chr(c) for c in range(33, 127)):
        if inside(ch) != negate:
            return ch
    return "a"


def _sample(seq) -> str:
    """A short text that the sub-pattern matches (approximately: lookarounds and back-references
    are ignored, which is fine for building a prefix)."""
    out = []
    for op, arg in seq:
        if op is sre_c.LITERAL:
            out.append(chr(arg))
        elif op is sre_c.NOT_LITERAL:
            out.append("a" if arg != ord("a") else "b")
        elif op is sre_c.ANY:
            out.append("a")
        elif op is sre_c.IN:
            out.append(_char_for_class(arg))
        elif op is sre_c.CATEGORY:
            out.append(_char_for_class([(op, arg)]))
        elif op is sre_c.BRANCH:
            out.append(_sample(arg[1][0]))
        elif op is sre_c.SUBPATTERN:
            out.append(_sample(arg[3]))
        elif op in (sre_c.MAX_REPEAT, sre_c.MIN_REPEAT, sre_c.POSSESSIVE_REPEAT):
            low, _high, item = arg
            out.append(_sample(item) * low)
        elif op is sre_c.ATOMIC_GROUP:
            out.append(_sample(arg))
        # AT (anchors), ASSERT, ASSERT_NOT, GROUPREF, GROUPREF_EXISTS: nothing
    return "".join(out)


_KINDS = ("a", "A", "1", " ", ".", "-", "\n")


def _units(item) -> list[str]:
    """The texts to repeat for one repetition. For a single character class, one character of each
    kind it accepts (a lower-case letter, a capital, a digit, a space, ...): which kind matters,
    because a run only makes a search start again at every position if its characters can also
    BEGIN a match ("[A-Z][a-zA-Z]+" is linear on a run of "a" and quadratic on a run of "A")."""
    if len(item) == 1 and item[0][0] in (sre_c.IN, sre_c.ANY, sre_c.NOT_LITERAL, sre_c.CATEGORY):
        compiled = None
        try:
            # a one-character pattern equivalent to the class, to ask what it accepts
            sub = sre_parse.SubPattern(sre_parse.State(), list(item))
            import re._compiler as sre_compile  # noqa: PLC0415

            compiled = sre_compile.compile(sub)
        except Exception:
            compiled = None
        if compiled is not None:
            found = [ch for ch in _KINDS if compiled.fullmatch(ch)]
            if found:
                return found
    unit = _sample(item)
    return [unit] if unit else []


def attacks(pattern: str | bytes, flags: int, size: int):
    """Yield (description, text) for each large repetition in the pattern."""
    is_bytes = isinstance(pattern, bytes)
    try:
        parsed = sre_parse.parse(pattern.decode("latin-1") if is_bytes else pattern, flags & ~re.LOCALE)
    except Exception as exc:
        print(f"NOTE could not parse {pattern[:60]!r}: {exc!r}", flush=True)
        return

    seen: set[str] = set()

    def walk(seq, prefix: str):
        before = prefix
        for op, arg in seq:
            if op in (sre_c.MAX_REPEAT, sre_c.MIN_REPEAT, sre_c.POSSESSIVE_REPEAT):
                low, high, item = arg
                if high is sre_c.MAXREPEAT or high >= LARGE:
                    for unit in _units(item):
                        repeats = max(1, size // len(unit))
                        for tail in ("\x00", "!", ""):
                            text = before + unit * repeats + tail
                            key = f"{before!r}+{unit!r}*n+{tail!r}"
                            if key not in seen:
                                seen.add(key)
                                yield key, text
                yield from walk(item, before)          # repetitions nested inside this one
                before += _sample(item) * max(low, 1 if high else 0)
            elif op is sre_c.SUBPATTERN:
                yield from walk(arg[3], before)
                before += _sample(arg[3])
            elif op is sre_c.ATOMIC_GROUP:
                yield from walk(arg, before)
                before += _sample(arg)
            elif op is sre_c.BRANCH:
                for alternative in arg[1]:
                    yield from walk(alternative, before)
                before += _sample(arg[1][0])
            elif op in (sre_c.ASSERT, sre_c.ASSERT_NOT):
                yield from walk(arg[1], before)        # a lookahead can scan a long way too
            else:
                before += _sample([(op, arg)])

    for key, text in walk(parsed, ""):
        yield key, (text.encode("latin-1", "replace") if is_bytes else text)


# --- 3. timing --------------------------------------------------------------------------------


def _run(compiled, text, anchored: bool) -> float:
    began = time.perf_counter()
    if anchored:
        compiled.match(text)
    else:
        count = 0
        for _ in compiled.finditer(text):
            count += 1
            if count > 2_000_000:
                break
    return time.perf_counter() - began


def _is_superlinear(tier: int, seconds: float, previous: tuple[int, float] | None) -> bool:
    """Slow, and growing faster than the text did. Time alone is not the test: a bounded pattern
    with a large constant can take 0.06 s on 25,600 characters and be perfectly linear, and
    reporting it one run in three would make this check worthless. A pattern is reported when it
    is over the limit AND took much more than its share compared with the size before (four
    times the text for 16 times the time is quadratic), or when it is over a second outright."""
    if seconds <= SLOW_SECONDS:
        return False
    if seconds > 1.0 or previous is None:
        return True
    before_tier, before_seconds = previous
    growth = tier / before_tier
    return seconds / max(before_seconds, 1e-5) > growth * 1.6


def main() -> None:
    # Imported here, not at the top: the older harness reads its size from the command line as
    # it is imported, which a test importing this module for its functions must not trigger.
    try:
        from tests.regex_flood_harness import MATCH_ONLY, discover_patterns  # noqa: PLC0415
    except ImportError:  # run as a script from the tests directory
        from regex_flood_harness import (  # type: ignore[no-redef]  # noqa: PLC0415
            MATCH_ONLY,
            discover_patterns,
        )

    inline, unresolved = inline_patterns()
    for label, reason in unresolved:
        print(f"UNRESOLVED {label}: {reason}", flush=True)

    targets = []
    for label, pattern, flags, anchored in inline:
        try:
            targets.append((label, re.compile(pattern, flags), pattern, flags, anchored))
        except re.error as exc:
            print(f"NOTE {label} does not compile: {exc}", flush=True)
    for name, compiled in discover_patterns().items():
        targets.append((f"import-time {name}", compiled, compiled.pattern, compiled.flags, name in MATCH_ONLY))

    print(f"PATTERNS {len(targets)} ({len(inline)} inline)", flush=True)
    tried = 0
    for label, compiled, pattern, flags, anchored in targets:
        item = f"{label} /{str(pattern)[:50]!r}/"
        print(f"START {item}", flush=True)       # so that a pattern that never returns has a name
        worst = 0.0
        slow_keys: set[str] = set()
        previous: dict[str, tuple[int, float]] = {}
        for tier in TIERS:
            for key, text in attacks(pattern, flags, tier):
                if key in slow_keys:
                    continue
                tried += 1
                seconds = _run(compiled, text, anchored)
                if _is_superlinear(tier, seconds, previous.get(key)) and seconds < 5:
                    # Measure again and keep the faster: one slow reading on a busy machine must
                    # not condemn a pattern, and a pattern that is really slow is slow twice.
                    seconds = min(seconds, _run(compiled, text, anchored))
                worst = max(worst, seconds)
                if _is_superlinear(tier, seconds, previous.get(key)):
                    slow_keys.add(key)
                    print(f"SLOW {seconds:.3f} s on {tier} characters: {item} attack {key}", flush=True)
                previous[key] = (tier, seconds)
        # A pattern that is noticeably slow at the largest size without being reported is either
        # linear with a large constant or quadratic with a small one. One more fourfold step
        # tells them apart for certain, and only these few pay for it.
        for key, text in attacks(pattern, flags, LAST_RESORT):
            before = previous.get(key)
            if key in slow_keys or before is None or before[0] != TIERS[-1] or before[1] < BORDERLINE_SECONDS:
                continue
            tried += 1
            seconds = min(_run(compiled, text, anchored), _run(compiled, text, anchored))
            worst = max(worst, seconds)
            if _is_superlinear(LAST_RESORT, seconds, before):
                print(f"SLOW {seconds:.3f} s on {LAST_RESORT} characters: {item} attack {key}", flush=True)
        print(f"DONE {worst:.3f} {item}", flush=True)
    print(f"ATTACKS {tried}", flush=True)
    print("FINISHED", flush=True)


if __name__ == "__main__":
    main()
