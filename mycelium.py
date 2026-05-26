"""
mycelium.py — R-ECOSYSTEM module mycelium & command dispatcher
Version : 1.1
Codename: Ant

Responsibilities
----------------
1. Scan MODULES_DIR for every .py file that declares L2Module=True in R_ECO3inf().
   mycelium itself is included so that "mycelium help", "mycelium set", etc. are routable.
2. For each discovered L2 module check §sys:mycelium:<module_stem> in HiveFS.
   If the key exists its value is a "|||"-separated list of alias rules.
   Each rule has the form:
       keyword * = args /*          (passes caller args verbatim to module)
       keyword    = args            (fixed args, no caller args forwarded)
   Syntax summary:
       •  "keyword *"  on the left  → the keyword accepts extra args
       •  "/*"         on the right → append caller args at that position
       •  "*" alone on left as keyword matches anything (catch-all)
   Examples stored in HiveFS:
       §sys:mycelium:echo  →  "echo * = echo *||| echo /* = echo"
       §sys:mycelium:help  →  "help /* = help"
3. Expose R_ECO3() so that raven (or any other shell) can call:
       mycelium <command> [args...]
   mycelium resolves which module + args to call and dispatches via core.apix.

Database key format
-------------------
    §sys:mycelium:<stem>   → rule string ("|||"-separated alias rules)

Rule grammar (informal)
-----------------------
    rule      := lhs "=" rhs
    lhs       := keyword ["*"]        # keyword with optional wildcard suffix
    rhs       := module_cmd ["/*"]    # fixed command with optional arg injection

    "*" on lhs  → keyword matches the input token AND extra tokens are captured
    "/*" on rhs → captured extra tokens are injected at that position in the rhs

    Special lhs keyword "*" → catches any unmatched command (default route).
"""

import os
import sys

# ---------------------------------------------------------------------------
# Bootstrap: make sure core is importable regardless of cwd
# ---------------------------------------------------------------------------
try:
    import core.trail as trail
    import core.hive as hive_mod
    import core.apix as apix
except ImportError:
    _here = os.path.dirname(os.path.abspath(__file__))
    _root = os.path.dirname(_here)           # modules/ → root
    if _root not in sys.path:
        sys.path.insert(0, _root)
    import core.trail as trail
    import core.hive as hive_mod
    import core.apix as apix

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Sub-commands that mycelium handles internally.
# Used only for documentation / help display — NOT used to short-circuit routing.
_INTERNAL_CMDS = frozenset({"list", "set", "del", "rule", "exe", "help"})

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _open_db():
    """Return an open HiveFS handle to the main database."""
    return hive_mod.HiveFS(filepath=str(trail.DB_FILE))


def _load_l2_modules():
    """
    Return a dict  stem → module_object  for every .py in MODULES_DIR
    whose R_ECO3inf() reports L2Module=True.

    Unlike v1.0, "mycelium" is NO LONGER excluded — it must be routeable
    so that commands like "mycelium help", "mycelium set ...", etc. resolve correctly.
    """
    l2 = {}
    for fname in os.listdir(str(trail.MODULES_DIR)):
        if not fname.endswith(".py") or fname.startswith("_"):
            continue
        stem = fname[:-3]
        try:
            mod = apix.load_module(stem)
            if not hasattr(mod, "R_ECO3inf"):
                continue
            info = mod.R_ECO3inf()
            if info.get("L2Module") is True:
                l2[stem] = mod
        except Exception:
            pass
    return l2


def _parse_rule(rule_str: str):
    """
    Parse a single alias rule string.

    Syntax (strict — any other form is a syntax error):
        cmd *       = rhs [*]    LHS ends with " *"  → matches cmd + zero or more args
        cmd /*      = rhs        LHS ends with " /*" → matches cmd with EXACTLY zero args
        cmd sub *   = rhs [*]    sub-keyword + args (more specific than cmd *)
        cmd sub /*  = rhs        sub-keyword + no args

    The last token of the LHS must be either "*" or "/*" — anything else
    is invalid and returns None (syntax error).

    Returns: (lhs_tokens: list[str], no_args: bool, rhs_tokens: list[str|None])
        lhs_tokens : all keyword tokens BEFORE the marker  e.g. ["cmd", "sub"]
        no_args    : True if marker is "/*" (zero args required)
                     False if marker is "*"  (zero or more args accepted)
        rhs_tokens : list where None is an arg injection point

    Returns None on syntax error.
    """
    if "=" not in rule_str:
        return None

    lhs_raw, rhs_raw = rule_str.split("=", 1)
    lhs_raw = lhs_raw.strip()
    rhs_raw = rhs_raw.strip()

    # --- LHS parsing ---
    lhs_parts = lhs_raw.split()
    if not lhs_parts:
        return None

    marker = lhs_parts[-1]
    if marker == "/*":
        no_args    = True
        lhs_tokens = lhs_parts[:-1]
    elif marker == "*":
        no_args    = False
        lhs_tokens = lhs_parts[:-1]
    else:
        # No valid marker — syntax error
        return None

    if not lhs_tokens:
        # Bare "*" or "/*" with no keyword — catch-all
        lhs_tokens = ["*"]

    # --- RHS parsing ---
    # "*" and "/*" on the RHS are both arg injection points
    rhs_tokens = []
    for tok in rhs_raw.split():
        if tok in ("*", "/*"):
            rhs_tokens.append(None)
        else:
            rhs_tokens.append(tok)

    return (lhs_tokens, no_args, rhs_tokens)


def _load_rules_for_stem(db, stem: str):
    """
    Read §sys:mycelium:<stem> from HiveFS and return a list of parsed rules.
    Returns [] if the key does not exist or all rules have syntax errors.
    """
    raw = db.get(f"§sys:mycelium:{stem}", default=None, as_str=True)
    if not raw:
        return []
    rules = []
    for part in raw.split("|||"):
        part = part.strip()
        if not part:
            continue
        parsed = _parse_rule(part)
        if parsed:
            rules.append(parsed)
    return rules


def _default_rules_for_stem(stem: str):
    """
    Implicit rule when no HiveFS entry exists:
        <stem> * = <stem> *
        <stem> /* = <stem>
    Format: (lhs_tokens, no_args, rhs_tokens)
    """
    return [
        ([stem], False, [stem, None]),   # stem * = stem *
        ([stem], True,  [stem]),         # stem /* = stem
    ]


def _build_mycelium(db):
    """
    Return a list of (stem, rules) for every L2 module, INCLUDING mycelium itself.

    - If §sys:mycelium:<stem> exists in HiveFS, parse and use those rules.
    - If no entry exists, fall back to the implicit default:
          <stem> * = <stem> *
          <stem> /* = <stem>
    """
    l2 = _load_l2_modules()

    # Ensure mycelium itself is always present even if load_module skips it
    # (e.g. circular-import guard during boot).
    if "mycelium" not in l2:
        import importlib.util as _ilu
        _spec = _ilu.spec_from_file_location("mycelium", os.path.abspath(__file__))
        if _spec:
            _mod = _ilu.module_from_spec(_spec)
            try:
                _spec.loader.exec_module(_mod) # type: ignore
                l2["mycelium"] = _mod
            except Exception:
                pass

    result = []
    for stem in sorted(l2.keys()):
        rules = _load_rules_for_stem(db, stem)
        if not rules:
            rules = _default_rules_for_stem(stem)
        result.append((stem, rules))
    return result


def _resolve(command_line: str, mycelium):
    """
    Resolve command_line against the mycelium.

    Matching rules
    --------------
    Each rule has (lhs_tokens, no_args, rhs_tokens).

    lhs_tokens : the keyword chain the input must start with
                 e.g. ["cmd", "sub"] matches input starting with "cmd sub"
    no_args    : True  → input must have NO tokens after lhs_tokens  (/* marker)
                 False → input may have zero or more extra tokens     (*  marker)

    Specificity : rules with more lhs_tokens win over shorter ones.
    Among equal length, no_args=True (/*) wins over no_args=False (*).
    Catch-all lhs_tokens=["*"] is tried last.

    Returns (dispatch_string, None) or (None, error_message).
    """
    if not command_line.strip():
        return None, "empty command"

    input_tokens = command_line.split()

    candidates = []   # (score, no_args_int, rhs_tokens, extra_tokens)

    for _stem, rules in mycelium:
        for (lhs_tokens, no_args, rhs_tokens) in rules:

            # ── catch-all ───────────────────────────────────────────
            if lhs_tokens == ["*"]:
                extra = input_tokens
                score = 0
                if no_args and extra:
                    continue
                candidates.append((score, int(no_args), rhs_tokens, extra))
                continue

            # ── prefix match ────────────────────────────────────────
            n = len(lhs_tokens)
            if input_tokens[:n] != lhs_tokens:
                continue

            extra = input_tokens[n:]

            if no_args and extra:
                continue

            score = n
            candidates.append((score, int(no_args), rhs_tokens, extra))

    if not candidates:
        return None, f"unknown command: '{input_tokens[0]}'"

    # Most specific: highest lhs length, then /* preferred over *
    best = max(candidates, key=lambda c: (c[0], c[1]))
    _, _, rhs_tokens, extra = best

    final_tokens = []
    for tok in rhs_tokens:
        if tok is None:
            final_tokens.extend(extra)
        else:
            final_tokens.append(tok)

    return " ".join(final_tokens), None


# ---------------------------------------------------------------------------
# Public Python API
# ---------------------------------------------------------------------------

def rebuild_mycelium(log_fn=print):
    """
    Scan all L2 modules and print which ones have mycelium entries.
    Does not write anything — mycelium entries are managed externally via HiveFS.
    Returns a dict: stem → raw_rule_str | None
    """
    db = _open_db()
    try:
        l2 = _load_l2_modules()
        result = {}
        for stem in sorted(l2.keys()):
            raw = db.get(f"§sys:mycelium:{stem}", default=None, as_str=True)
            if raw:
                result[stem] = raw
                log_fn(f"  [mycelium] {stem}: {raw}")
            else:
                log_fn(f"  [mycelium] {stem}: (no entry — using default)")
        return result
    finally:
        db.close()


def resolve_command(command_line: str, log_fn=print):
    """
    Resolve command_line to a dispatchable apix command string.
    Returns (dispatch_str | None, error_str | None).
    """
    db = _open_db()
    try:
        idx = _build_mycelium(db)
        return _resolve(command_line, idx)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Internal sub-command handlers
# ---------------------------------------------------------------------------

def _cmd_list(tokens, db, log_fn):
    l2 = _load_l2_modules()
    if len(tokens) > 1:
        stem = tokens[1]
        if stem not in l2:
            log_fn(f"[mycelium] '{stem}' is not a registered L2 module")
            return 1
        raw = db.get(f"§sys:mycelium:{stem}", default=None, as_str=True)
        if raw:
            log_fn(f"§sys:mycelium:{stem} = {raw}")
            rules = _load_rules_for_stem(db, stem)
            for (kw_tokens, no_args, rhs_tokens) in rules:
                kw_str  = " ".join(kw_tokens)
                marker  = " /*" if no_args else " *"
                rhs_str = " ".join("/*" if t is None else t for t in rhs_tokens)
                log_fn(f"  rule: '{kw_str}{marker}' → '{rhs_str}'")
        else:
            log_fn(f"§sys:mycelium:{stem} = (no entry — default: {stem} * = {stem} *)")
        return 0

    log_fn("L2 modules and their mycelium entries:")
    for stem in sorted(l2.keys()):
        raw = db.get(f"§sys:mycelium:{stem}", default=None, as_str=True)
        status = raw if raw else f"(default: {stem} * = {stem} *)"
        log_fn(f"  {stem:<20} {status}")
    return 0


def _cmd_set(tokens, args_raw, db, log_fn):
    if len(tokens) < 3:
        log_fn("[mycelium] usage: mycelium set <stem> <rules>")
        return 1
    stem = tokens[1]
    parts = args_raw.strip().split(None, 2)
    if len(parts) < 3:
        log_fn("[mycelium] usage: mycelium set <stem> <rules>")
        return 1
    rules = parts[2]
    if len(rules) >= 2 and rules[0] in ('"', "'") and rules[-1] == rules[0]:
        rules = rules[1:-1]
    db.set(f"§sys:mycelium:{stem}", rules)
    log_fn(f"[mycelium] §sys:mycelium:{stem} set to: {rules}")
    return 0


def _cmd_del(tokens, db, log_fn):
    if len(tokens) < 2:
        log_fn("[mycelium] usage: mycelium del <stem>")
        return 1
    stem = tokens[1]
    if db.delete(f"§sys:mycelium:{stem}"):
        log_fn(f"[mycelium] §sys:mycelium:{stem} deleted")
    else:
        log_fn(f"[mycelium] §sys:mycelium:{stem} not found")
    return 0


def _cmd_rule(args_raw, log_fn):
    parts = args_raw.strip().split(None, 1)
    rule_cmd = parts[1] if len(parts) > 1 else ""
    if not rule_cmd:
        log_fn("[mycelium] usage: mycelium rule <command> [args...]")
        return 1
    db = _open_db()
    try:
        idx = _build_mycelium(db)
    finally:
        db.close()
    dispatch, err = _resolve(rule_cmd, idx)
    if dispatch is None:
        log_fn(f"[mycelium] {err}")
        return 1
    d_parts  = dispatch.split()
    mod_name = d_parts[0]
    mod_args = " ".join(d_parts[1:]) if len(d_parts) > 1 else ""
    if mod_args:
        log_fn(f"[mycelium] '{rule_cmd}' → {mod_name} --args=\"{mod_args}\"")
    else:
        log_fn(f"[mycelium] '{rule_cmd}' → {mod_name}")
    return 0


# ---------------------------------------------------------------------------
# Shared execute helper — used by both R_ECO3 (mycelium exe) and exe.R_ECO3
# ---------------------------------------------------------------------------

def _exe(command_line: str, log_fn=print):
    """
    Resolve command_line via the mycelium and dispatch through spider -vr.
    Returns an int exit code.
    """
    if not command_line.strip():
        log_fn("[mycelium] usage: mycelium exe <command> [args...]")
        return 1

    db = _open_db()
    try:
        idx = _build_mycelium(db)
    finally:
        db.close()

    dispatch, err = _resolve(command_line, idx)
    if dispatch is None:
        log_fn(f"[mycelium] {err}")
        return 1

    d_parts  = dispatch.split()
    mod_name = d_parts[0]
    mod_args = " ".join(d_parts[1:]) if len(d_parts) > 1 else ""

    spider_args = f"{mod_name} -vr"
    if mod_args:
        spider_args += f" --args=\"{mod_args}\""

    code, result = apix.run_module_cmd("spider", "run", spider_args, log_fn=log_fn)
    return code if isinstance(code, int) else 0


# ---------------------------------------------------------------------------
# R_ECO3 — main entry point
# ---------------------------------------------------------------------------

def R_ECO3(args: str, log_fn=print):
    """
    mycelium <command> [args...]

    Resolves <command> (and optional args) against the module mycelium stored in
    §sys:mycelium:* and dispatches to the appropriate module via core.apix.

    Special sub-commands
    --------------------
    mycelium list            — list all L2 modules and their mycelium entries
    mycelium list <stem>     — show rules for a specific module stem
    mycelium set <stem> <rules>
                          — write §sys:mycelium:<stem> in HiveFS
    mycelium del <stem>      — delete §sys:mycelium:<stem> from HiveFS
    mycelium rule <cmd>      — show resolved dispatch without running
    mycelium exe <cmd>       — resolve and run via spider -vr
    mycelium help            — show this help
    """
    try:
        import core.utils as _utils
        tokens = _utils.tokenize(args.strip()) if args.strip() else []
    except Exception:
        tokens = args.strip().split() if args.strip() else []

    if not tokens:
        log_fn("[mycelium] usage: mycelium <command> [args...]")
        log_fn("        run 'mycelium help' for details")
        return 1

    sub = tokens[0]

    # ------------------------------------------------------------------ list
    if sub == "list":
        db = _open_db()
        try:
            return _cmd_list(tokens, db, log_fn)
        finally:
            db.close()

    # ------------------------------------------------------------------- set
    if sub == "set":
        db = _open_db()
        try:
            return _cmd_set(tokens, args, db, log_fn)
        finally:
            db.close()

    # ------------------------------------------------------------------- del
    if sub == "del":
        db = _open_db()
        try:
            return _cmd_del(tokens, db, log_fn)
        finally:
            db.close()

    # ------------------------------------------------------------------ rule
    if sub == "rule":
        return _cmd_rule(args, log_fn)

    # ------------------------------------------------------------------ exe
    if sub == "exe":
        parts = args.strip().split(None, 1)
        exe_cmd = parts[1] if len(parts) > 1 else ""
        if not exe_cmd:
            log_fn("[mycelium] usage: mycelium exe <command> [args...]")
            return 1
        return _exe(exe_cmd, log_fn)

    # ------------------------------------------------------------------ help
    if sub == "help":
        log_fn(R_ECO3inf()["manual"])
        return 0

    # ------------------------------------------------------------------ unknown
    log_fn(f"[mycelium] unknown sub-command: '{sub}' — use 'mycelium help'")
    return 1


# ---------------------------------------------------------------------------
# R_ECO3dep / R_ECO3inf
# ---------------------------------------------------------------------------

def R_ECO3dep():
    return (
        ("3.5.1b",),
        (
            ("core.hive",  ("1.1",)),
            ("core.apix",  ("1.1",)),
            ("core.trail", ("1.1",)),
            ("core.utils", ("1.1",)),
            ("spider",     ("1.8",)),
        ),
    )


def R_ECO3inf():
    return {
        "name":        "mycelium",
        "desc":        "Module mycelium: maps keyword aliases to L2 modules via §sys:mycelium:*",
        "help":        "mycelium <command> [args] | mycelium list | mycelium set <stem> <rules> | mycelium del <stem>",
        "version_mod": "1.1",
        "L2Module":    True,
        "manual": """
mycelium — R-ECOSYSTEM module mycelium & command dispatcher
======================================================

SYNOPSIS
    mycelium <command> [args...]
    mycelium list [<stem>]
    mycelium set <stem> <rules>
    mycelium del <stem>
    mycelium rule <cmd>
    mycelium exe <cmd> [args...]
    mycelium help

DESCRIPTION
    mycelium scans MODULES_DIR for every Python module whose R_ECO3inf()
    declares L2Module=True. For each such module it looks up the key
    §sys:mycelium:<stem> in HiveFS.

    If the key exists, its value is a "|||"-separated list of alias rules.
    When a user types a command that matches one of those rules, mycelium
    rewrites it into the target module call and dispatches it through
    core.apix (via spider -vr for exe).

    mycelium itself is always included in the routing table, so commands
    like "mycelium help", "mycelium set ...", "exe mycelium set ..." all resolve
    correctly without any special-casing.

RULE SYNTAX
    Each rule is strictly:

        lhs_tokens MARKER = rhs_tokens

    LHS MARKERS (mandatory — no marker = syntax error)
        keyword *         matches "keyword" + zero or more args (args forwarded)
        keyword /*        matches "keyword" with EXACTLY zero args

    Sub-keywords for specificity:
        keyword sub *     matches "keyword sub" + zero or more args
        keyword sub /*    matches "keyword sub" with zero args

    More tokens on the LHS = higher specificity (wins over shorter rules).
    Among equal length, /* beats * when both match.

    RHS
        module arg *      inject extra args at "*" position
        module arg        fixed dispatch, no injection

    Catch-all: bare "* = ..." or "/* = ..." (lowest priority)

    Rule separator: "|||"  (not ";")

EXAMPLES
    §sys:mycelium:echo = "echo * = echo *||| echo /* = echo"

        echo              →  echo                    (/* rule, zero args)
        echo hello world  →  echo hello world        (* rule, args forwarded)

    §sys:mycelium:echo = "test * = echo test *||| test /* = echo test"

        test              →  echo test               (/* rule)
        test foo bar      →  echo test foo bar       (* rule)

DATABASE KEYS
    §sys:mycelium:<stem>     Rule string for module <stem>

SUB-COMMANDS
    list [<stem>]         Show L2 modules and their raw rule strings.
                          With a stem, show the parsed rule breakdown.
    set <stem> <rules>    Write §sys:mycelium:<stem> in HiveFS.
    del <stem>            Delete §sys:mycelium:<stem> from HiveFS.
    rule <cmd>            Dry-run: show resolved dispatch without executing.
    exe <cmd> [args...]   Resolve and execute via spider -vr.
    help                  Show this manual.
""",
    }