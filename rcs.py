import time


# ─────────────────────────────────────────────────────────────────────────────
#  Tokeniser
# ─────────────────────────────────────────────────────────────────────────────

_BLOCK_OPENERS = ("if ", "elif ", "else:", "else :", "for ", "while ",
                  "def ", "class ", "try:", "try :", "except", "finally:",
                  "finally :", "with ")

# Préfixes spider connus — étendre si de nouveaux modules top-level sont ajoutés
_SPIDER_PREFIXES = ("banana ", "spider ")


def _looks_like_spider(line: str) -> bool:
    s = line.strip()
    return any(s.startswith(p) for p in _SPIDER_PREFIXES)


def _opens_block(line: str) -> bool:
    s = line.strip()
    return any(s.startswith(k) for k in _BLOCK_OPENERS) and s.endswith(":")


def _is_indented(line: str) -> bool:
    return len(line) > 0 and line[0] in (" ", "\t")


def _split_semis(line: str) -> list[str]:
    """Split a single flat line on ; outside strings."""
    parts   = []
    current = []
    in_str  = False
    str_ch  = None
    for ch in line:
        if not in_str and ch in ('"', "'"):
            in_str = True
            str_ch = ch
            current.append(ch)
        elif in_str and ch == str_ch:
            in_str = False
            str_ch = None
            current.append(ch)
        elif not in_str and ch == ";":
            p = "".join(current).strip()
            if p:
                parts.append(p)
            current = []
        else:
            current.append(ch)
    tail = "".join(current).strip()
    if tail:
        parts.append(tail)
    return parts


def _tokenise(source: str) -> list[str]:
    """
    Split source into logical statements.
    - Newlines and semicolons (outside strings) separate statements.
    - > and ! lines (spider dispatch) are never split.
    - Indented blocks following a block-opener are kept together.
    - Lines that look like spider commands without > raise SyntaxError early.
    """
    raw_lines = source.split("\n")

    # First pass: expand semicolons, detect spider lines, flag missing >
    expanded: list[str] = []
    for lineno, raw in enumerate(raw_lines, 1):
        stripped = raw.strip()
        if not stripped:
            expanded.append("")
            continue
        if stripped.startswith(">") or stripped.startswith("!"):
            expanded.append(raw)
            continue
        if _looks_like_spider(stripped):
            prefix = stripped.split()[0]
            raise SyntaxError(
                f"line {lineno}: '{prefix}' looks like a spider command — "
                f"missing '>' prefix?\n  got:      {stripped}\n  expected: >{stripped}"
            )
        if _is_indented(raw):
            expanded.append(raw)
            continue
        parts = _split_semis(raw)
        expanded.extend(parts)

    # Second pass: group block openers with their indented bodies
    statements: list[str] = []
    i = 0
    while i < len(expanded):
        line = expanded[i]
        flat = line.strip()

        if not flat:
            i += 1
            continue

        if _opens_block(flat):
            block = [line]
            i += 1
            while i < len(expanded):
                nxt = expanded[i]
                if nxt.strip() == "":
                    if i + 1 < len(expanded) and _is_indented(expanded[i + 1]):
                        block.append(nxt)
                        i += 1
                    else:
                        break
                elif _is_indented(nxt):
                    block.append(nxt)
                    i += 1
                elif nxt.strip().startswith(("elif ", "else:", "else :",
                                             "except", "finally:")):
                    block.append(nxt)
                    i += 1
                else:
                    break
            statements.append("\n".join(block))
        else:
            statements.append(flat)
            i += 1

    return [s for s in statements if s.strip()]


# ─────────────────────────────────────────────────────────────────────────────
#  Built-in helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_builtins(log_fn, hive_obj, spider_fn):

    def _print(*args, sep=" ", end="\n", **_):
        log_fn(sep.join(str(a) for a in args))

    def _input(prompt=""):
        if prompt:
            log_fn(str(prompt))
        return ""

    def sleep(seconds):
        time.sleep(float(seconds))

    def hive_get(key, default=None):
        v = hive_obj.get(key, None)
        return default if v is None else v

    def hive_set(key, value):
        hive_obj[key] = value

    def hive_del(key):
        hive_obj.delete(key)

    def hive_exists(key) -> bool:
        return hive_obj.exists(key)

    def hive_list(prefix="") -> list:
        keys = hive_obj.list()
        return [k for k in keys if k.startswith(prefix)] if prefix else list(keys)

    return {
        "print":       _print,
        "input":       _input,
        "log":         log_fn,
        "sleep":       sleep,
        "time":        time,
        "hive":        hive_obj,
        "hive_get":    hive_get,
        "hive_set":    hive_set,
        "hive_del":    hive_del,
        "hive_exists": hive_exists,
        "hive_list":   hive_list,
        "spider":      spider_fn,
    }


# ─────────────────────────────────────────────────────────────────────────────
#  Script executor
# ─────────────────────────────────────────────────────────────────────────────

def _run_script(source: str, log_fn, hive_obj, spider_fn,
                extra_vars=None, debug: bool = False):

    def dbg(msg: str):
        if debug:
            log_fn(f"[rcs:dbg] {msg}")

    try:
        statements = _tokenise(source)
    except SyntaxError as exc:
        log_fn(f"[rcs] {exc}")
        raise RuntimeError(str(exc)) from None

    dbg(f"{len(statements)} statement(s) parsed")
    for idx, s in enumerate(statements):
        dbg(f"  stmt[{idx}] = {repr(s[:80])}")

    ns = _make_builtins(log_fn, hive_obj, spider_fn)
    ns["__builtins__"] = __builtins__
    if extra_vars:
        ns.update(extra_vars)

    py_block: list[str] = []

    def _flush_python():
        if not py_block:
            return
        code = "\n".join(py_block)
        py_block.clear()
        dbg(f"exec python block:\n{code}")
        try:
            exec(compile(code, "<rcs>", "exec"), ns)   # noqa: S102
        except SyntaxError as exc:
            log_fn(f"[rcs] Python error: {exc}")
            raise
        except Exception as exc:
            log_fn(f"[rcs] Python error: {exc}")
            raise

    for stmt in statements:
        stripped = stmt.lstrip()
        if stripped.startswith(">") or stripped.startswith("!"):
            _flush_python()
            cmd = stripped[1:].strip()
            dbg(f"spider cmd (raw)  = {repr(cmd)}")
            try:
                cmd = cmd.format_map(ns)
                dbg(f"spider cmd (fmt)  = {repr(cmd)}")
            except (KeyError, ValueError) as exc:
                dbg(f"format_map skipped: {exc}")
            ns["_result"] = spider_fn(cmd)
            dbg(f"_result = {repr(ns['_result'])}")
        else:
            py_block.append(stmt)

    _flush_python()


# ─────────────────────────────────────────────────────────────────────────────
#  Interactive collector
# ─────────────────────────────────────────────────────────────────────────────

_END_MARKER = "---END---"


def _collect_script(log_fn) -> str | None:
    log_fn("[rcs] Entering script mode — type ---END--- or Ctrl+C to finish")
    lines = []
    try:
        while True:
            try:
                line = input()
            except EOFError:
                break
            if line.strip() == _END_MARKER:
                break
            lines.append(line)
    except KeyboardInterrupt:
        log_fn("")
    return "\n".join(lines) if lines else None


# ─────────────────────────────────────────────────────────────────────────────
#  Argument parser
# ─────────────────────────────────────────────────────────────────────────────

def _parse_rcs_args(raw: str):
    """
    Parse rcs command-line arguments.

    Returns (positional, kv_flags, script_source, needs_input).

    --script [<code>]       interactive input mode (or inline after flag)
    --inline=<code>         verbatim code, quotes NOT stripped
    """
    script_source = None
    needs_input   = False

    if "--script" in raw:
        head, _, tail = raw.partition("--script")
        tail = tail.lstrip(" \t")
        if tail.startswith("\n"):
            tail = tail[1:]
        if _END_MARKER in tail:
            script_source, _, _ = tail.partition(_END_MARKER)
            script_source = script_source.rstrip("\n")
        elif tail.strip() == "":
            needs_input = True
        else:
            script_source = tail.rstrip("\n")
        raw_head = head.strip()

    elif "--inline=" in raw:
        idx           = raw.index("--inline=")
        raw_head      = raw[:idx].strip()
        # Take everything after --inline= verbatim — do NOT strip quotes,
        # they are part of the Python code being saved.
        script_source = raw[idx + len("--inline="):]

    else:
        raw_head = raw

    pos: list[str] = []
    kv:  dict      = {}
    for token in raw_head.split():
        if token.startswith("--"):
            token = token[2:]
            if "=" in token:
                k, _, v = token.partition("=")
                kv[k.strip()] = v.strip()
            else:
                kv[token.strip()] = True
        elif token.startswith("-") and len(token) == 2:
            kv[token[1:]] = True
        else:
            pos.append(token)

    return pos, kv, script_source, needs_input


# ─────────────────────────────────────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────────────────────────────────────

def _start(args, log_fn=print):
    import core

    db = core.hive.HiveFS(str(core.trail.DB_FILE))

    def B(cmd):
        return core.apix.R_ECO3(f"run banana {cmd}", log_fn)

    def spider_fn(cmd):
        """
        Dispatch a spider command.
        cmd = "banana ok --msg='hello'"  →  module=banana, run_args=ok --msg='hello'
        Wrapped in double-quotes at the --args level; single-quotes inside are safe.
        """
        parts    = cmd.split(None, 1)
        module   = parts[0]
        run_args = parts[1] if len(parts) > 1 else ""
        if run_args:
            return core.apix.R_ECO3(
                f"run spider {module} -vr --args='{run_args}'", log_fn
            )
        return core.apix.R_ECO3(f"run spider {module} -vr", log_fn)

    raw = args if isinstance(args, str) else " ".join(args)
    pos, kv, script_source, needs_input = _parse_rcs_args(raw)
    verb        = pos[0] if pos else ""
    debug_mode  = kv.get("d") is True or kv.get("debug") is True

    def _resolve_source(verb_name):
        nonlocal script_source
        if needs_input:
            script_source = _collect_script(log_fn)
            if script_source is None:
                B(f"err --msg='rcs {verb_name}: empty script, aborted'")
                return False
        if script_source is None:
            B(f"err --msg='rcs {verb_name}: no script provided'")
            return False
        return True

    # ── run ───────────────────────────────────────────────────────────────────
    if verb == "run":
        if not _resolve_source("run"):
            return 1
        try:
            _run_script(script_source, log_fn, db, spider_fn, debug=debug_mode)
        except Exception:
            B("err --msg='rcs run failed — see above'")
            return 1
        return 0

    # ── exec ──────────────────────────────────────────────────────────────────
    if verb == "exec":
        if len(pos) < 2:
            B("err --msg='rcs exec: missing script name'")
            return 1
        name   = pos[1]
        source = db.get(f"§sys:rcs:script:{name}", None)
        if source is None:
            B(f"err --msg='rcs: script [bold cyan]{name}[/bold cyan] not found'")
            return 1
        try:
            _run_script(str(source), log_fn, db, spider_fn, debug=debug_mode)
        except Exception:
            B(f"err --msg='rcs exec [{name}] failed — see above'")
            return 1
        return 0

    # ── save ──────────────────────────────────────────────────────────────────
    if verb == "save":
        if len(pos) < 2:
            B("err --msg='rcs save: missing script name'")
            return 1
        name = pos[1]
        if not _resolve_source("save"):
            return 1
        db[f"§sys:rcs:script:{name}"] = script_source
        B(f"ok --msg='Script [bold cyan]{name}[/bold cyan] saved'")
        return 0

    # ── delete ────────────────────────────────────────────────────────────────
    if verb == "delete":
        if len(pos) < 2:
            B("err --msg='rcs delete: missing script name'")
            return 1
        name = pos[1]
        key  = f"§sys:rcs:script:{name}"
        # Check both exists() and list() — handles corrupted entries where
        # list() sees the key but get()/exists() return None/False.
        all_keys = [k for k in db.list() if k.startswith("§sys:rcs:script:")]
        if not db.exists(key) and key not in all_keys:
            B(f"err --msg='rcs: script [bold cyan]{name}[/bold cyan] not found'")
            return 1
        try:
            db.delete(key)
        except Exception:
            pass
        B(f"ok --msg='Script [bold cyan]{name}[/bold cyan] deleted'")
        return 0

    # ── list ──────────────────────────────────────────────────────────────────
    if verb == "list":
        keys = [k for k in db.list() if k.startswith("§sys:rcs:script:")]
        if not keys:
            B("panel --msg='[dim]No scripts saved.[/dim]' --title=' RCS · Scripts' --border=cyan --box=ROUNDED")
            return 0
        rows = ""
        for k in sorted(keys):
            name    = k.removeprefix("§sys:rcs:script:")
            source  = str(db.get(k, ""))
            preview = source.replace("\n", " ; ")[:60]
            rows += f"  [bold cyan]{name:<22}[/bold cyan] [dim]{preview}…[/dim]\n"
        B(f"panel --msg='{rows.rstrip()}' --title=' RCS · {len(keys)} script(s)' --border=cyan --box=ROUNDED")
        return 0

    # ── show ──────────────────────────────────────────────────────────────────
    if verb == "show":
        if len(pos) < 2:
            B("err --msg='rcs show: missing script name'")
            return 1
        name   = pos[1]
        source = db.get(f"§sys:rcs:script:{name}", None)
        if source is None:
            B(f"err --msg='rcs: script [bold cyan]{name}[/bold cyan] not found'")
            return 1
        B(f"panel --msg='{source}' --title=' RCS · {name}' --border=cyan --box=ROUNDED")
        return 0

    # ── unknown ───────────────────────────────────────────────────────────────
    B("err --msg='Unknown rcs command'")
    B("print --msg='  [dim]run · exec · save · delete · list · show[/dim]'")
    return 1


# ─────────────────────────────────────────────────────────────────────────────
#  Framework metadata
# ─────────────────────────────────────────────────────────────────────────────

def R_ECO3(args, log_fn=print):
    return _start(args, log_fn)


def R_ECO3dep():
    return (
        ("1.4",),
        (
            ("core.hive", ("1.2",)),
            ("core.apix",  ("1.1",)),
            ("core.utils", ("1.1",)),
            ("core.trail", ("1.1",)),
            ("banana",     ("1.1",)),
            ("spider",     ("1.8",)),
        ),
    )


def R_ECO3inf():
    return {
        "name":        "rcs",
        "desc":        "Inline & stored script runner — Python + spider dispatch",
        "help":        (
            "Executes rcs scripts: plain Python lines run as-is; "
            "lines starting with > or ! are forwarded to spider -vr. "
            "print() is replaced by the framework log_fn. "
            "hive is pre-bound. if/for/def blocks are handled correctly. "
            "--script triggers interactive input (---END--- or Ctrl+C to finish). "
            "-d / --debug enables verbose execution tracing."
        ),
        "version_mod": "1.4",
        "L2Module":    True,
        "alias_rules": "rcs /* = banana err --msg='This module cannot be run without arguments.'",
        "manual": (
            "rcs — Script runner  v1.4\n"
            "=========================\n"
            "\n"
            "SYNOPSIS\n"
            "    rcs run   [--script | --inline=<code>] [-d]\n"
            "    rcs exec   <name> [-d]\n"
            "    rcs save   <name> [--script | --inline=<code>]\n"
            "    rcs delete <name>\n"
            "    rcs list\n"
            "    rcs show   <name>\n"
            "\n"
            "SCRIPT SYNTAX\n"
            "    Newlines and semicolons (outside strings) separate statements.\n"
            "    if/for/while/def/class blocks are kept together automatically.\n"
            "\n"
            "    Regular lines      → Python (exec)\n"
            "    Lines starting with > or !  → spider dispatch\n"
            "        {varname} interpolated from namespace before dispatch.\n"
            "        Result stored in _result.\n"
            "\n"
            "INPUT MODES\n"
            "    --script            Interactive: type lines, finish with ---END--- or Ctrl+C.\n"
            "    --inline=<code>     Single line of code passed verbatim.\n"
            "                        Quotes inside are preserved as-is.\n"
            "\n"
            "FLAGS\n"
            "    -d / --debug        Verbose mode: prints parsed statements, exec'd blocks,\n"
            "                        spider commands before/after interpolation, and _result.\n"
            "\n"
            "PRE-BOUND NAMES\n"
            "    print  input  log  sleep  time\n"
            "    hive  hive_get  hive_set  hive_del  hive_exists  hive_list\n"
            "    spider  _result\n"
            "\n"
            "EXAMPLES\n"
            "    # Python pur\n"
            "    rcs run --script\n"
            "    x = 5\n"
            "    if x > 3:\n"
            "        print('grand')\n"
            "    ---END---\n"
            "\n"
            "    # Spider dispatch avec variable\n"
            "    rcs run --script\n"
            "    nom = 'monde'\n"
            "    > banana ok --msg='bonjour {nom}'\n"
            "    ---END---\n"
            "\n"
            "    # Inline (guillemets simples recommandés)\n"
            "    rcs run --inline=print('hello')\n"
            "\n"
            "    # Save et exec\n"
            "    rcs save   monscript --script\n"
            "    rcs exec   monscript\n"
            "    rcs exec   monscript -d\n"
            "\n"
            "    # Debug\n"
            "    rcs run --script --debug\n"
            "    total = 0\n"
            "    for i in range(5):\n"
            "        total = total + i\n"
            "    > banana ok --msg='total={total}'\n"
            "    ---END---\n"
            "\n"
            "NOTES\n"
            "    --inline= préserve les quotes — ne pas entourer le code de guillemets.\n"
            "    > et ! sont synonymes pour le dispatch spider.\n"
            "    Les variables Python sont accessibles dans les commandes > via {varname}.\n"
        ),
    }