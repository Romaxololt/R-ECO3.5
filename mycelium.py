"""
mycelium.py — R-ECOSYSTEM module mycelium & command dispatcher
Version : 1.6
Codename: Fungus

Changes in 1.6
--------------
- All output goes through banana (panels, ok/err, tables via Rich markup)
- New `mycelium init` command: scans MODULES_DIR for unregistered L2 modules,
  presents a checkbox list via banana, installs selected ones, then runs update.
- _b() helper: loads banana once per call, falls back to log_fn transparently.
"""

import os
import sys

import core

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------
try:
    import core.trail as trail
    import core.hive  as hive_mod
    import core.apix  as apix
except ImportError:
    _here = os.path.dirname(os.path.abspath(__file__))
    _root = os.path.dirname(_here)
    if _root not in sys.path:
        sys.path.insert(0, _root)
    import core.trail as trail
    import core.hive  as hive_mod
    import core.apix  as apix

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PREFIX_USER   = "§sys:mycelium:rules:user:"
_PREFIX_MODULE = "§sys:mycelium:rules:module:"

_KEY_REGISTRY      = "§sys:mycelium:registry"
_KEY_REGISTRY_CORE = "§sys:mycelium:registry:core"

_SEP = "|||"

_CORE_STEMS = frozenset({
    "nest", "raven", "spider", "mycelium",
    "bee", "login", "init", "moss", "banana",
    "manual", "help", "echo", "crypto", "vine",
    "prism", "reco_bldr",
})

_INTERNAL_CMDS = frozenset({
    "list", "set", "del", "rule", "exe",
    "help", "update", "reverse",
    "install", "uninstall", "init",
})

# Layer colours used in Rich markup
_LAYER_COLOUR = {
    "user (L1)":    "bold magenta",
    "module (L2)":  "bold cyan",
    "default (L3)": "dim",
}

# ---------------------------------------------------------------------------
# banana bridge
# ---------------------------------------------------------------------------

def _b(log_fn):
    """
    Return a banana-aware helper dict with keys:
      ok(msg), err(msg), print(msg), panel(...), question(...), checkbox(...)
    Falls back to log_fn if banana is unavailable.
    """
    try:
        bn = apix.load_module("banana")
    except Exception:
        bn = None

    def _ok(msg):
        if bn:
            bn.R_ECO3(f"ok --msg={_q(msg)}", log_fn=log_fn)
        else:
            log_fn(f"  ✓ {msg}")

    def _err(msg):
        if bn:
            bn.R_ECO3(f"err --msg={_q(msg)}", log_fn=log_fn)
        else:
            log_fn(f"  ✗ {msg}")

    def _print(msg):
        if bn:
            bn.R_ECO3(f"print --msg={_q(msg)}", log_fn=log_fn)
        else:
            log_fn(msg)

    def _panel(content, title="", border="blue", subtitle="", box="ROUNDED"):
        if bn:
            args = f"panel --msg={_q(content)} --border={border} --box={box}"
            if title:
                args += f" --title={_q(title)}"
            if subtitle:
                args += f" --subtitle={_q(subtitle)}"
            bn.R_ECO3(args, log_fn=log_fn)
        else:
            if title:
                log_fn(f"┌─ {title} " + "─" * max(0, 50 - len(title)) + "┐")
            for line in content.splitlines():
                log_fn(f"  {line}")
            if title:
                log_fn("└" + "─" * 52 + "┘")

    def _question(msg, choices):
        if bn:
            _, ans = bn.R_ECO3(
                f"question --msg={_q(msg)} --choices={_q(','.join(choices))}",
                log_fn=log_fn,
            )
            return ans
        # fallback: numbered list
        log_fn(msg)
        for i, c in enumerate(choices, 1):
            log_fn(f"  {i}. {c}")
        try:
            raw = builtins_input("  Choice: ").strip()
            idx = int(raw) - 1
            return choices[idx] if 0 <= idx < len(choices) else None
        except Exception:
            return None

    def _checkbox(msg, choices):
        if bn:
            _, ans = bn.R_ECO3(
                f"question --msg={_q(msg)} --choices={_q(','.join(choices))} --multi=true",
                log_fn=log_fn,
            )
            return ans or []
        log_fn(f"{msg}  (enter numbers separated by spaces, e.g. 1 3 5)")
        for i, c in enumerate(choices, 1):
            log_fn(f"  {i}. {c}")
        try:
            raw = builtins_input("  Selection: ").strip()
            selected = []
            for tok in raw.split():
                idx = int(tok) - 1
                if 0 <= idx < len(choices):
                    selected.append(choices[idx])
            return selected
        except Exception:
            return []

    return {
        "ok":       _ok,
        "err":      _err,
        "print":    _print,
        "panel":    _panel,
        "question": _question,
        "checkbox": _checkbox,
        "raw":      bn,
    }


def _q(s: str) -> str:
    """Wrap a string in double-quotes, escaping inner double-quotes."""
    return '"' + str(s).replace('"', '\\"') + '"'


import builtins as _builtins
builtins_input = _builtins.input


# ---------------------------------------------------------------------------
# Registry helpers
# ---------------------------------------------------------------------------

def _reg_read(db, key: str) -> list:
    raw = db.get(key, as_str=True)
    if not raw:
        return []
    return [s.strip() for s in raw.split(_SEP) if s.strip()]


def _reg_write(db, key: str, stems: list):
    db.set(key, _SEP.join(sorted(set(stems))))


def _ensure_core_registry(db):
    current = set(_reg_read(db, _KEY_REGISTRY_CORE))
    present = set()
    for stem in _CORE_STEMS:
        path = trail.MODULES_DIR / f"{stem}.py"
        if path.exists():
            present.add(stem)
    if present != current:
        _reg_write(db, _KEY_REGISTRY_CORE, list(present))


def _all_registered_stems(db) -> list:
    _ensure_core_registry(db)
    core_stems = _reg_read(db, _KEY_REGISTRY_CORE)
    user_stems = _reg_read(db, _KEY_REGISTRY)
    seen   = set()
    result = []
    for stem in core_stems + user_stems:
        if stem not in seen:
            seen.add(stem)
            result.append(stem)
    return result

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _open_db():
    return hive_mod.HiveFS(filepath=str(trail.DB_FILE))


def _load_l2_modules(db=None) -> dict:
    own_db = db is None
    if own_db:
        db = _open_db()
    try:
        stems = _all_registered_stems(db)
    finally:
        if own_db:
            db.close()

    l2 = {}
    for stem in stems:
        path = trail.MODULES_DIR / f"{stem}.py"
        if not path.exists():
            continue
        try:
            mod = apix.load_module(stem)
            if not hasattr(mod, "R_ECO3inf"):
                continue
            if mod.R_ECO3inf().get("L2Module") is True:
                l2[stem] = mod
        except Exception:
            pass
    return l2

# ---------------------------------------------------------------------------
# Rule parsing
# ---------------------------------------------------------------------------

def _parse_stored_variant(keyword: str, variant_str: str):
    variant_str = variant_str.strip()
    if "=" not in variant_str:
        return None
    marker_raw, rhs_raw = variant_str.split("=", 1)
    marker  = marker_raw.strip()
    rhs_raw = rhs_raw.strip()
    if marker == "/*":
        no_args = True
    elif marker == "*":
        no_args = False
    else:
        return None
    lhs_tokens = [keyword]
    rhs_tokens = []
    for tok in rhs_raw.split():
        rhs_tokens.append(None if tok == "*" else tok)
    return (lhs_tokens, no_args, rhs_tokens)


def _parse_stored_value(keyword: str, raw_value: str):
    rules = []
    for part in raw_value.split(_SEP):
        part = part.strip()
        if not part:
            continue
        parsed = _parse_stored_variant(keyword, part)
        if parsed:
            rules.append(parsed)
    return rules


def _build_stored_value(rules_for_keyword: list) -> str:
    parts = []
    for (_, no_args, rhs_tokens) in rules_for_keyword:
        marker  = "/*" if no_args else "*"
        rhs_str = " ".join("*" if t is None else t for t in rhs_tokens)
        parts.append(f"{marker} = {rhs_str}")
    return " ||| ".join(parts)


def _parse_legacy_rule(rule_str: str):
    rule_str = rule_str.strip()
    if "=" not in rule_str:
        return None
    lhs_raw, rhs_raw = rule_str.split("=", 1)
    lhs_raw  = lhs_raw.strip()
    rhs_raw  = rhs_raw.strip()
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
        return None
    if not lhs_tokens:
        lhs_tokens = ["*"]
    rhs_tokens = []
    for tok in rhs_raw.split():
        rhs_tokens.append(None if tok in ("*", "/*") else tok)
    return (lhs_tokens, no_args, rhs_tokens)


def _group_legacy_rules_by_keyword(raw: str) -> dict:
    groups = {}
    for part in raw.split(_SEP):
        parsed = _parse_legacy_rule(part)
        if not parsed:
            continue
        lhs_tokens, no_args, rhs_tokens = parsed
        keyword = lhs_tokens[0]
        groups.setdefault(keyword, []).append(parsed)
    return groups

# ---------------------------------------------------------------------------
# Layer helpers
# ---------------------------------------------------------------------------

def _layer_get(db, prefix: str, keyword: str):
    raw = db.get(f"{prefix}{keyword}", as_str=True)
    if not raw:
        return []
    return _parse_stored_value(keyword, raw)


def _layer_keywords(db, prefix: str) -> list:
    try:
        keys = [k for k in db.list() if k.startswith(prefix)]
        return [k[len(prefix):] for k in keys]
    except AttributeError:
        pass
    l2       = _load_l2_modules(db)
    keywords = list(l2.keys()) + ["*"]
    existing = []
    for kw in keywords:
        raw = db.get(f"{prefix}{kw}", as_str=True)
        if raw:
            existing.append(kw)
    return existing

# ---------------------------------------------------------------------------
# Default rules / inf reader
# ---------------------------------------------------------------------------

def _default_rules_for_stem(stem: str):
    return [
        ([stem], True,  [stem]),
        ([stem], False, [stem, None]),
    ]


def _rules_from_inf(stem: str, mod) -> dict:
    try:
        raw = mod.R_ECO3inf().get("alias_rules", "")
        if raw:
            return _group_legacy_rules_by_keyword(raw)
    except Exception:
        pass
    return {}

# ---------------------------------------------------------------------------
# Build routing table
# ---------------------------------------------------------------------------

def _build_mycelium(db):
    l2 = _load_l2_modules(db)
    routing_table     = []
    all_keywords_seen = set()

    for kw in _layer_keywords(db, _PREFIX_USER):
        rules = _layer_get(db, _PREFIX_USER, kw)
        if rules:
            routing_table.append((kw, "user (L1)", rules))
            all_keywords_seen.add(kw)

    for kw in _layer_keywords(db, _PREFIX_MODULE):
        if kw in all_keywords_seen:
            continue
        rules = _layer_get(db, _PREFIX_MODULE, kw)
        if not rules:
            continue
        default_rules = _default_rules_for_stem(kw)
        l2_v, l3_v = [], []
        for rule in rules:
            if any(_build_stored_value([rule]) == _build_stored_value([d]) for d in default_rules):
                l3_v.append(rule)
            else:
                l2_v.append(rule)
        if l2_v:
            routing_table.append((kw, "module (L2)", l2_v))
        if l3_v:
            routing_table.append((kw, "default (L3)", l3_v))
        all_keywords_seen.add(kw)

    for stem in sorted(l2.keys()):
        if stem not in all_keywords_seen:
            routing_table.append((stem, "default (L3)", _default_rules_for_stem(stem)))
            all_keywords_seen.add(stem)
        else:
            for (kw, src, rules) in routing_table:
                if kw != stem:
                    continue
                if not any(na for (_, na, _) in rules):
                    rules.append(([stem], True,  [stem]))
                if not any(not na for (_, na, _) in rules):
                    rules.append(([stem], False, [stem, None]))
                break

    normalized = []
    for (kw, src, rules) in routing_table:
        if src == "module (L2)" and kw in l2:
            default_vals = {_build_stored_value([r]) for r in _default_rules_for_stem(kw)}
            l2_only = [r for r in rules if _build_stored_value([r]) not in default_vals]
            l3_only = [r for r in rules if _build_stored_value([r]) in default_vals]
            if l2_only:
                normalized.append((kw, "module (L2)", l2_only))
            if l3_only:
                normalized.append((kw, "default (L3)", l3_only))
        else:
            normalized.append((kw, src, rules))
    return normalized

# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------

def _resolve(command_line: str, routing_table: list):
    if not command_line.strip():
        return None, "empty command"
    input_tokens = command_line.split()
    candidates   = []
    for (_kw, _src, rules) in routing_table:
        for (lhs_tokens, no_args, rhs_tokens) in rules:
            if lhs_tokens == ["*"]:
                extra = input_tokens
                if no_args and extra:
                    continue
                if not no_args and not extra:
                    continue
                candidates.append((0, int(no_args), rhs_tokens, extra))
                continue
            n = len(lhs_tokens)
            if input_tokens[:n] != lhs_tokens:
                continue
            extra = input_tokens[n:]
            if no_args and extra:
                continue
            if not no_args and not extra:
                continue
            candidates.append((n, int(no_args), rhs_tokens, extra))
    if not candidates:
        return None, f"unknown command: '{input_tokens[0]}'"
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

def resolve_command(command_line: str, log_fn=print):
    db = _open_db()
    try:
        table = _build_mycelium(db)
        return _resolve(command_line, table)
    finally:
        db.close()

# ---------------------------------------------------------------------------
# Rule display helper
# ---------------------------------------------------------------------------

def _rule_to_str(lhs_tokens, no_args, rhs_tokens) -> str:
    lhs_str = " ".join(lhs_tokens)
    marker  = " /*" if no_args else " *"
    rhs_str = " ".join("*" if t is None else t for t in rhs_tokens)
    return f"{lhs_str}{marker} = {rhs_str}"

# ---------------------------------------------------------------------------
# Sub-command: init  (NEW in v1.6)
# ---------------------------------------------------------------------------

def _cmd_init(db, log_fn):
    """
    mycelium init

    Scans MODULES_DIR for .py files that:
      - Are not already registered (neither core nor user)
      - Implement R_ECO3 / R_ECO3dep / R_ECO3inf with L2Module=True

    Presents a checkbox list via banana so the user can choose which ones to
    install.  Selected modules are added to the user registry, then
    `mycelium update` is run to sync their alias rules into L2.
    """
    b = _b(log_fn)

    b["panel"](
        "Scanning [bold]modules/[/] for unregistered L2 modules…",
        title=" mycelium init ",
        border="cyan",
    )

    registered = set(_all_registered_stems(db))

    # Scan filesystem for candidates
    candidates = []   # list of (stem, name, version, desc)
    for fname in sorted(os.listdir(str(trail.MODULES_DIR))):
        if not fname.endswith(".py") or fname.startswith("_"):
            continue
        stem = fname[:-3]
        if stem in registered:
            continue
        path = trail.MODULES_DIR / fname
        if not path.exists():
            continue
        try:
            mod = apix.load_module(stem)
            if not (hasattr(mod, "R_ECO3") and hasattr(mod, "R_ECO3dep") and hasattr(mod, "R_ECO3inf")):
                continue
            inf = mod.R_ECO3inf()
            if inf.get("L2Module") is not True:
                continue
            candidates.append((
                stem,
                inf.get("name",        stem),
                inf.get("version_mod", "?"),
                inf.get("desc",        ""),
            ))
        except Exception:
            continue

    if not candidates:
        b["ok"]("No new modules found — registry is already up to date.")
        return 0

    # Build checkbox choices: "stem — desc (vX.Y)"
    choices = [
        f"{stem}  —  {desc}  [v{ver}]" if desc else f"{stem}  [v{ver}]"
        for stem, _, ver, desc in candidates
    ]

    b["print"](f"[dim]Found [bold]{len(candidates)}[/] unregistered module(s).[/]")

    selected_labels = b["checkbox"](
        "Select modules to install  (space = toggle, enter = confirm)",
        choices,
    )

    if not selected_labels:
        b["print"]("[dim]Nothing selected — no changes made.[/]")
        return 0

    # Map label back to stem
    label_to_stem = {label: stem for (stem, _, ver, desc), label in zip(candidates, choices)}

    installed = []
    failed    = []
    user_stems = _reg_read(db, _KEY_REGISTRY)

    for label in selected_labels:
        stem = label_to_stem.get(label)
        if not stem:
            continue
        if stem in user_stems:
            b["print"](f"[dim]  · {stem} already registered, skipping.[/]")
            continue
        user_stems.append(stem)
        installed.append(stem)

    if installed:
        _reg_write(db, _KEY_REGISTRY, user_stems)
        for stem in installed:
            b["ok"](f"Installed: [bold]{stem}[/]")

        # Run update to sync L2 alias rules for newly installed modules
        b["print"]("\n[dim]Running [bold]mycelium update[/] to sync alias rules…[/]")
        _cmd_update(db, log_fn)
    else:
        b["print"]("[dim]Nothing new to register.[/]")

    return 0

# ---------------------------------------------------------------------------
# Sub-command: install
# ---------------------------------------------------------------------------

def _cmd_install(tokens, db, log_fn):
    b = _b(log_fn)

    if len(tokens) < 2:
        b["err"]("usage: mycelium install <stem>")
        return 1

    stem = tokens[1]

    if stem in _CORE_STEMS:
        b["print"](f"[dim]'{stem}' is a core module — registered automatically.[/]")
        return 0

    path = trail.MODULES_DIR / f"{stem}.py"
    if not path.exists():
        b["err"](f"install failed: '{stem}.py' not found in modules/")
        return 1

    try:
        mod = apix.load_module(stem)
        if not (hasattr(mod, "R_ECO3inf") and hasattr(mod, "R_ECO3") and hasattr(mod, "R_ECO3dep")):
            b["err"](f"'{stem}' does not implement the R-ECO3 convention (R_ECO3 / R_ECO3dep / R_ECO3inf required)")
            return 1
        inf = mod.R_ECO3inf()
        if inf.get("L2Module") is not True:
            b["err"](f"'{stem}' declares L2Module=False — only L2 modules can be registered")
            return 1
        mod_name    = inf.get("name", stem)
        mod_version = inf.get("version_mod", "?")
        mod_desc    = inf.get("desc", "")
    except Exception as exc:
        b["err"](f"could not load '{stem}' — {exc}")
        return 1

    user_stems = _reg_read(db, _KEY_REGISTRY)
    if stem in user_stems:
        b["print"](f"[dim]'{stem}' is already in the user registry.[/]")
        return 0

    user_stems.append(stem)
    _reg_write(db, _KEY_REGISTRY, user_stems)

    b["panel"](
        f"[bold]{mod_name}[/]  v{mod_version}\n{mod_desc}\n\n"
        f"[dim]Run [bold cyan]mycelium update[/] to load alias rules into L2.[/]",
        title=" Module installed ",
        border="green",
    )
    return 0

# ---------------------------------------------------------------------------
# Sub-command: uninstall
# ---------------------------------------------------------------------------

def _cmd_uninstall(tokens, db, log_fn):
    b = _b(log_fn)

    if len(tokens) < 2:
        b["err"]("usage: mycelium uninstall <stem>")
        return 1

    stem = tokens[1]

    if stem in _CORE_STEMS:
        b["err"](f"'{stem}' is a core module and cannot be uninstalled.")
        return 1

    user_stems = _reg_read(db, _KEY_REGISTRY)
    if stem not in user_stems:
        b["err"](f"'{stem}' is not in the user registry.")
        return 1

    path = trail.MODULES_DIR / f"{stem}.py"
    delete_file = False

    if path.exists():
        choice = b["question"](
            f"Uninstall '{stem}' — also delete {stem}.py?",
            ["Remove from registry only", "Delete file too", "Cancel"],
        )
        if choice is None or "cancel" in str(choice).lower():
            b["print"]("[dim]Uninstall cancelled.[/]")
            return 0
        delete_file = "delete" in str(choice).lower()
    else:
        choice = b["question"](
            f"'{stem}.py' not found on disk. Remove '{stem}' from registry?",
            ["Yes", "Cancel"],
        )
        if choice is None or "cancel" in str(choice).lower():
            b["print"]("[dim]Uninstall cancelled.[/]")
            return 0

    # Remove from registry
    user_stems = [s for s in user_stems if s != stem]
    _reg_write(db, _KEY_REGISTRY, user_stems)

    # Clean rules
    for prefix in (_PREFIX_USER, _PREFIX_MODULE):
        key = f"{prefix}{stem}"
        if db.get(key, as_str=True):
            db.delete(key)

    if delete_file and path.exists():
        try:
            os.remove(path)
        except OSError as exc:
            b["err"](f"could not delete {path} — {exc}")

    b["ok"](f"'{stem}' uninstalled successfully.")
    return 0

# ---------------------------------------------------------------------------
# Sub-command: list
# ---------------------------------------------------------------------------

def _cmd_list(tokens, db, log_fn):
    b  = _b(log_fn)
    l2 = _load_l2_modules(db)

    # ── Detail view for one keyword ───────────────────────────────────────
    if len(tokens) > 1:
        target = tokens[1]
        lines  = []
        found  = False

        for prefix, label, colour in (
            (_PREFIX_USER,   "user (L1)",   "magenta"),
            (_PREFIX_MODULE, "module (L2)", "cyan"),
        ):
            raw = db.get(f"{prefix}{target}", as_str=True)
            if not raw:
                continue
            found = True
            lines.append(f"[{colour}]{label}[/]")
            lines.append(f"  [dim]stored :[/] {raw}")
            for rule in _parse_stored_value(target, raw):
                lines.append(f"  [dim]rule   :[/] [bold]{_rule_to_str(*rule)}[/]")

        if not found:
            mod = l2.get(target)
            if mod:
                inf_groups = _rules_from_inf(target, mod)
                if target in inf_groups:
                    rules = inf_groups[target]
                    val   = _build_stored_value(rules)
                    lines.append("[dim]not in HiveFS — source: alias_rules in inf[/]")
                    lines.append(f"  [dim]value  :[/] {val}")
                    for rule in rules:
                        lines.append(f"  [dim]rule   :[/] [bold]{_rule_to_str(*rule)}[/]")
                    lines.append("[dim]→ run [bold cyan]mycelium update[/] to store in L2[/]")
                else:
                    rules = _default_rules_for_stem(target)
                    val   = _build_stored_value(rules)
                    lines.append("[dim]not in HiveFS — implicit default (L3)[/]")
                    lines.append(f"  [dim]value  :[/] {val}")
                    for rule in rules:
                        lines.append(f"  [dim]rule   :[/] [bold]{_rule_to_str(*rule)}[/]")
                b["panel"]("\n".join(lines), title=f" {target} ", border="blue")
                return 0

            b["err"](f"'{target}': not found in any layer and not a known L2 stem")
            return 1

        b["panel"]("\n".join(lines), title=f" {target} ", border="blue")
        return 0

    # ── Full listing ──────────────────────────────────────────────────────
    core_reg = _reg_read(db, _KEY_REGISTRY_CORE)
    user_reg = _reg_read(db, _KEY_REGISTRY)

    # ── Registry panel ────────────────────────────────────────────────────
    reg_lines = []

    reg_lines.append(f"[bold]Core modules[/]  [dim]({len(core_reg)} auto-registered)[/]")
    for stem in sorted(core_reg):
        path   = trail.MODULES_DIR / f"{stem}.py"
        status = "[green]✓[/]" if path.exists() else "[red]✗ MISSING[/]"
        # grab desc if loaded
        mod  = l2.get(stem)
        desc = mod.R_ECO3inf().get("desc", "") if mod else ""
        ver  = mod.R_ECO3inf().get("version_mod", "") if mod else ""
        ver_str  = f" [dim]v{ver}[/]" if ver else ""
        desc_str = f"  [dim]{desc}[/]"  if desc else ""
        reg_lines.append(f"  {status} [cyan]{stem:<18}[/]{ver_str}{desc_str}")

    reg_lines.append("")
    reg_lines.append(f"[bold]User modules[/]  [dim]({len(user_reg)} installed)[/]")
    if user_reg:
        for stem in sorted(user_reg):
            path   = trail.MODULES_DIR / f"{stem}.py"
            status = "[green]✓[/]" if path.exists() else "[red]✗ MISSING[/]"
            mod    = l2.get(stem)
            desc   = mod.R_ECO3inf().get("desc", "") if mod else ""
            ver    = mod.R_ECO3inf().get("version_mod", "") if mod else ""
            ver_str  = f" [dim]v{ver}[/]" if ver else ""
            desc_str = f"  [dim]{desc}[/]" if desc else ""
            reg_lines.append(f"  {status} [magenta]{stem:<18}[/]{ver_str}{desc_str}")
    else:
        reg_lines.append("  [dim](none — use [bold]mycelium install <stem>[/] or [bold]mycelium init[/])[/]")

    b["panel"]("\n".join(reg_lines), title=" Registry ", border="cyan", box="ROUNDED")

    # ── Routing table panel ───────────────────────────────────────────────
    table    = _build_mycelium(db)
    by_layer = {}
    for kw, src, rules in table:
        by_layer.setdefault(src, []).append((kw, rules))

    layer_order = ["user (L1)", "module (L2)", "default (L3)"]
    route_lines = []

    for layer in layer_order:
        entries = by_layer.get(layer, [])
        if not entries:
            continue
        colour = _LAYER_COLOUR.get(layer, "white")
        route_lines.append(f"[{colour}]{layer}[/]")

        from collections import defaultdict as _dd
        merged = _dd(list)
        for kw, rules in entries:
            merged[kw].extend(rules)

        for kw, rules in sorted(merged.items()):
            val = _build_stored_value(rules)
            route_lines.append(f"  [bold]{kw:<20}[/] [dim]{val}[/]")
        route_lines.append("")

    b["panel"]("\n".join(route_lines).rstrip(), title=" Routing table ", border="blue", box="ROUNDED")
    return 0

# ---------------------------------------------------------------------------
# Sub-command: set
# ---------------------------------------------------------------------------

def _cmd_set(tokens, args_raw, db, log_fn):
    b = _b(log_fn)
    if len(tokens) < 3:
        b["err"]("usage: mycelium set <keyword> <variants>")
        b["print"]("  variants: [dim]'/* = module args ||| * = module args *'[/]")
        b["print"]("  (always stored in Layer 1 — user override)")
        return 1

    keyword = tokens[1]
    parts   = args_raw.strip().split(None, 2)
    if len(parts) < 3:
        b["err"]("usage: mycelium set <keyword> <variants>")
        return 1
    raw_val = parts[2]
    if len(raw_val) >= 2 and raw_val[0] in ('"', "'") and raw_val[-1] == raw_val[0]:
        raw_val = raw_val[1:-1]

    parsed = _parse_stored_value(keyword, raw_val)
    if not parsed:
        b["err"](f"syntax error in rule variants: '{raw_val}'")
        b["print"]("  expected: [dim]'/* = rhs' or '* = rhs' (separated by |||)[/]")
        return 1

    db.set(f"{_PREFIX_USER}{keyword}", raw_val)
    b["ok"](f"[magenta]user (L1)[/]  {keyword} = {raw_val}")
    return 0

# ---------------------------------------------------------------------------
# Sub-command: del
# ---------------------------------------------------------------------------

def _cmd_del(tokens, db, log_fn):
    b = _b(log_fn)
    if len(tokens) < 2:
        b["err"]("usage: mycelium del <keyword>")
        return 1

    keyword = tokens[1]
    l1_key  = f"{_PREFIX_USER}{keyword}"
    l2_key  = f"{_PREFIX_MODULE}{keyword}"
    l2      = _load_l2_modules(db)

    if db.delete(l1_key):
        b["ok"](f"user (L1) override for [bold]{keyword}[/] removed")
        raw_l2 = db.get(l2_key, as_str=True)
        if raw_l2:
            b["print"](f"  [dim]→ now resolved via module (L2): {raw_l2}[/]")
        elif keyword in l2:
            b["print"]("  [dim]→ now resolved via default (L3)[/]")
        else:
            b["print"]("  [yellow]→ no L2/L3 fallback — keyword will be unknown[/]")
        return 0

    raw_l2 = db.get(l2_key, as_str=True)
    if raw_l2:
        b["print"](f"[dim]'{keyword}' has no user (L1) override to delete.[/]")
        b["print"](f"[dim]Current module (L2): {raw_l2}[/]")
        b["print"](f"[dim]To override: [bold]mycelium set {keyword} <variants>[/][/]")
        return 0

    for stem, mod in l2.items():
        inf_groups = _rules_from_inf(stem, mod)
        if keyword in inf_groups:
            raw_inf = _build_stored_value(inf_groups[keyword])
            b["print"](f"[dim]'{keyword}' only in inf of '{stem}': {raw_inf}[/]")
            b["print"](f"[dim]Run [bold]mycelium update[/] first, then del.[/]")
            return 0

    b["err"](f"'{keyword}': not found in any layer")
    return 1

# ---------------------------------------------------------------------------
# Sub-command: rule
# ---------------------------------------------------------------------------

def _cmd_rule(args_raw, log_fn):
    b     = _b(log_fn)
    parts = args_raw.strip().split(None, 1)
    rule_cmd = parts[1] if len(parts) > 1 else ""
    if not rule_cmd:
        b["err"]("usage: mycelium rule <command> [args...]")
        return 1

    db = _open_db()
    try:
        table = _build_mycelium(db)
    finally:
        db.close()

    dispatch, err_msg = _resolve(rule_cmd, table)
    if dispatch is None:
        b["err"](err_msg)
        return 1

    d_parts  = dispatch.split()
    mod_name = d_parts[0]
    mod_args = " ".join(d_parts[1:]) if len(d_parts) > 1 else ""

    db2 = _open_db()
    try:
        input_kw = rule_cmd.split()[0]
        raw_l1   = db2.get(f"{_PREFIX_USER}{input_kw}",   as_str=True)
        raw_l2   = db2.get(f"{_PREFIX_MODULE}{input_kw}", as_str=True)
        if raw_l1:
            source_label = "user (L1)"
            source_col   = "magenta"
        elif raw_l2:
            source_label = "module (L2)"
            source_col   = "cyan"
        else:
            l2  = _load_l2_modules(db2)
            mod = l2.get(mod_name)
            inf_grp = _rules_from_inf(mod_name, mod) if mod else {}
            if input_kw in inf_grp:
                source_label = "inf (run update)"
                source_col   = "yellow"
            else:
                source_label = "default (L3)"
                source_col   = "dim"
    except Exception:
        source_label = "?"
        source_col   = "dim"
    finally:
        db2.close()

    arrow = f"[bold]{rule_cmd}[/]  →  [bold green]{mod_name}[/]"
    if mod_args:
        arrow += f"  [dim]--args=\"{mod_args}\"[/]"
    arrow += f"  [[{source_col}]{source_label}[/]]"
    b["panel"](arrow, title=" rule resolution ", border="blue", box="SIMPLE")
    return 0

# ---------------------------------------------------------------------------
# Sub-command: reverse
# ---------------------------------------------------------------------------

def _cmd_reverse(tokens, db, log_fn):
    b = _b(log_fn)
    if len(tokens) < 2:
        b["err"]("usage: mycelium reverse <target_module>")
        return 1
    target = tokens[1]
    table  = _build_mycelium(db)
    found  = []

    for (kw, src, rules) in table:
        for (lhs_tokens, no_args, rhs_tokens) in rules:
            rhs_mod = next((t for t in rhs_tokens if t is not None), None)
            if rhs_mod != target:
                continue
            found.append((kw, src, _rule_to_str(lhs_tokens, no_args, rhs_tokens)))

    if not found:
        b["print"](f"[dim]No rules point to '{target}'.[/]")
        return 0

    lines = []
    for kw, src, rule_str in found:
        colour = _LAYER_COLOUR.get(src, "white")
        lines.append(f"  [[{colour}]{src}[/]]  [dim](key: {kw})[/]  [bold]{rule_str}[/]")

    b["panel"]("\n".join(lines), title=f" → {target} ", border="magenta")
    return 0

# ---------------------------------------------------------------------------
# Sub-command: update
# ---------------------------------------------------------------------------

def _cmd_update(db, log_fn):
    b = _b(log_fn)

    # ── A) Registry integrity ─────────────────────────────────────────────
    removed_total = 0
    for reg_key, label in ((_KEY_REGISTRY_CORE, "core"), (_KEY_REGISTRY, "user")):
        stems = _reg_read(db, reg_key)
        kept  = []
        for stem in stems:
            if (trail.MODULES_DIR / f"{stem}.py").exists():
                kept.append(stem)
            else:
                b["print"](f"[yellow]  ✗ '{stem}' missing on disk — removed from {label} registry[/]")
                removed_total += 1
        if len(kept) != len(stems):
            _reg_write(db, reg_key, kept)

    if removed_total == 0:
        b["ok"]("Registry integrity OK — all modules present on disk.")
    else:
        b["print"](f"[yellow]  {removed_total} missing module(s) purged from registry.[/]")

    # ── B) L2 alias sync ─────────────────────────────────────────────────
    l2        = _load_l2_modules(db)
    written   = 0
    skipped   = 0
    updated   = 0
    conflicts = 0
    deleted   = 0

    inf_index = {}
    for stem in sorted(l2.keys()):
        for keyword, inf_rules in _rules_from_inf(stem, l2[stem]).items():
            inf_index[keyword] = _build_stored_value(inf_rules)

    existing_l2 = set(_layer_keywords(db, _PREFIX_MODULE))

    for keyword, new_val in inf_index.items():
        l2_key  = f"{_PREFIX_MODULE}{keyword}"
        cur_val = db.get(l2_key, as_str=True)

        if cur_val is None:
            db.set(l2_key, new_val)
            b["print"](f"  [cyan]+[/] {keyword} = [dim]{new_val}[/]")
            written += 1
        elif cur_val.strip() == new_val.strip():
            skipped += 1
        else:
            conflicts += 1
            choice = b["question"](
                f"Conflict for '{keyword}' — keep which?\n"
                f"  current L2: {cur_val}\n"
                f"  new   (inf): {new_val}",
                ["Keep current (L2)", "Use new (inf)", "Skip"],
            )
            if choice and "new" in str(choice).lower():
                db.set(l2_key, new_val)
                b["print"](f"  [cyan]~[/] {keyword} updated")
                updated += 1
            elif choice and "skip" in str(choice).lower():
                b["print"](f"  [dim]  {keyword} skipped[/]")
            else:
                b["print"](f"  [dim]  {keyword} kept current[/]")

    for keyword in sorted(existing_l2 - set(inf_index.keys())):
        db.delete(f"{_PREFIX_MODULE}{keyword}")
        b["print"](f"  [red]-[/] {keyword} [dim](stale, removed)[/]")
        deleted += 1

    summary = (
        f"[green]wrote {written}[/]  "
        f"[dim]skipped {skipped}[/]  "
        f"[cyan]updated {updated}[/]  "
        f"[yellow]conflicts {conflicts}[/]  "
        f"[red]deleted {deleted}[/]  "
        f"[yellow]registry_removed {removed_total}[/]"
    )
    b["panel"](
        summary + "\n\n[dim]User (L1) overrides are never modified by update.[/]",
        title=" update complete ",
        border="green",
        box="ROUNDED",
    )
    return 0

# ---------------------------------------------------------------------------
# Execute helper
# ---------------------------------------------------------------------------

def _exe(command_line: str, log_fn=print):
    b = _b(log_fn)
    if not command_line.strip():
        b["err"]("usage: mycelium exe <command> [args...]")
        return 1

    db = _open_db()
    try:
        table = _build_mycelium(db)
    finally:
        db.close()

    dispatch, err_msg = _resolve(command_line, table)
    if dispatch is None:
        b["err"](err_msg)
        return 1

    d_parts     = dispatch.split()
    mod_name    = d_parts[0]
    mod_args    = " ".join(d_parts[1:]) if len(d_parts) > 1 else ""
    spider_args = f"{mod_name} -vr"
    if mod_args:
        spider_args += f" --args=\"{mod_args}\""

    code, result = apix.run_module_cmd("spider", "run", spider_args, log_fn=log_fn)
    return code if isinstance(code, int) else 0

# ---------------------------------------------------------------------------
# R_ECO3 — main entry point
# ---------------------------------------------------------------------------

def R_ECO3(args: str, log_fn=print):
    try:
        import core.utils as _utils
        tokens = _utils.tokenize(args.strip()) if args.strip() else []
    except Exception:
        tokens = args.strip().split() if args.strip() else []

    if not tokens:
        _b(log_fn)["err"]("This module requires arguments — use 'mycelium help'.")
        return 1

    sub = tokens[0]

    if sub == "init":
        db = _open_db()
        try:
            return _cmd_init(db, log_fn)
        finally:
            db.close()

    if sub == "install":
        db = _open_db()
        try:
            return _cmd_install(tokens, db, log_fn)
        finally:
            db.close()

    if sub == "uninstall":
        db = _open_db()
        try:
            return _cmd_uninstall(tokens, db, log_fn)
        finally:
            db.close()

    if sub == "list":
        db = _open_db()
        try:
            return _cmd_list(tokens, db, log_fn)
        finally:
            db.close()

    if sub == "set":
        db = _open_db()
        try:
            return _cmd_set(tokens, args, db, log_fn)
        finally:
            db.close()

    if sub == "del":
        db = _open_db()
        try:
            return _cmd_del(tokens, db, log_fn)
        finally:
            db.close()

    if sub == "rule":
        return _cmd_rule(args, log_fn)

    if sub == "exe":
        parts   = args.strip().split(None, 1)
        exe_cmd = parts[1] if len(parts) > 1 else ""
        if not exe_cmd:
            _b(log_fn)["err"]("usage: mycelium exe <command> [args...]")
            return 1
        return _exe(exe_cmd, log_fn)

    if sub == "update":
        db = _open_db()
        try:
            return _cmd_update(db, log_fn)
        finally:
            db.close()

    if sub == "reverse":
        db = _open_db()
        try:
            return _cmd_reverse(tokens, db, log_fn)
        finally:
            db.close()

    if sub == "help":
        log_fn(R_ECO3inf()["manual"])
        return 0

    _b(log_fn)["err"](f"Unknown sub-command: '{sub}' — use 'mycelium help'")
    return 1

# ---------------------------------------------------------------------------
# R_ECO3dep / R_ECO3inf
# ---------------------------------------------------------------------------

def R_ECO3dep():
    return (
        ("3.5.1b",),
        (
            ("core.hive", ("1.2",)),
            ("core.apix",  ("1.1",)),
            ("core.trail", ("1.1",)),
            ("core.utils", ("1.1",)),
            ("spider",     ("1.8",)),
            ("banana",     ("1.1",)),
        ),
    )


def R_ECO3inf():
    return {
        "name":        "mycelium",
        "desc":        "3-layer command dispatcher with explicit module registry",
        "help":        (
            "mycelium init | install <stem> | uninstall <stem> | list [kw] | "
            "set <kw> <v> | del <kw> | rule <cmd> | exe <cmd> | update | reverse <mod>"
        ),
        "version_mod": "1.6",
        "L2Module":    True,
        "manual": """
mycelium — R-ECOSYSTEM command dispatcher  v1.6
===============================================

SYNOPSIS
    mycelium init
    mycelium install   <stem>
    mycelium uninstall <stem>
    mycelium list      [<keyword>]
    mycelium set       <keyword> <variants>
    mycelium del       <keyword>
    mycelium rule      <cmd> [args...]
    mycelium exe       <cmd> [args...]
    mycelium update
    mycelium reverse   <module>
    mycelium help

NEW IN v1.6
    All output now uses banana (Rich panels, ok/err, checkboxes).
    Falls back to plain log_fn if banana is unavailable.

    mycelium init
        Scans modules/ for unregistered L2 modules, presents a checkbox
        list via banana so you can pick which ones to install.
        After selection, runs `mycelium update` automatically to load
        their alias rules into Layer 2.

MODULE REGISTRY
    §sys:mycelium:registry         — user modules (install/uninstall)
    §sys:mycelium:registry:core    — system modules (auto at boot)

    Core stems: nest raven spider mycelium bee login init moss
                banana manual help echo crypto vine prism reco_bldr

THREE-LAYER ROUTING
    Layer 1 — user (L1)      §sys:mycelium:rules:user:<keyword>
    Layer 2 — module (L2)    §sys:mycelium:rules:module:<keyword>
    Layer 3 — default (L3)   implicit: <stem> /* = <stem> / * = <stem> *

VARIANT FORMAT
    "/* = rhs"       zero-arg   "* = rhs *"  with-arg + inject
    Separate with |||

UPDATE (v1.5+)
    A) Registry check: missing .py files auto-removed from registry.
    B) L2 alias sync from alias_rules. Conflicts prompt via banana.
    User (L1) overrides never touched.

EXAMPLES
    mycelium init                  → checkbox picker for new modules
    mycelium install logger        → add logger to user registry
    mycelium uninstall logger      → remove with confirmation
    mycelium list                  → registry + routing table (Rich)
    mycelium list echo             → detail view for one keyword
    mycelium update                → integrity check + L2 sync
    mycelium rule vine status      → dry-run resolution
    mycelium reverse banana        → all rules dispatching to banana
""",
    }