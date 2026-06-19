"""
mycelium.py — R-ECOSYSTEM module — alias/registry manager  v2.0

Responsabilités :
  - Registre des modules (core + user)
  - Table de routage 3 couches (L1 user / L2 module / L3 default)
  - Résolution d'alias  →  mycelium resolve <cmd>
  - Affichage dry-run   →  mycelium rule <cmd>
  - Gestion des règles  →  set / del / update / list / reverse

N'exécute RIEN. L'exécution appartient à squid.
db est toujours fourni par le caller (squid/raven) — mycelium ne rouvre jamais la DB.
"""

import os
import core
import core.trail as trail
import core.apix  as apix
import core.hive  as hive
import core.utils as utils

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PREFIX_USER   = "§sys:mycelium:rules:user:"
_PREFIX_MODULE = "§sys:mycelium:rules:module:"

_KEY_REGISTRY      = "§sys:mycelium:registry"
_KEY_REGISTRY_CORE = "§sys:mycelium:registry:core"

_SEP = "|||"

_CORE_STEMS = frozenset({
    "nest", "raven", "spider", "mycelium", "squid",
    "bee", "login", "init", "moss", "banana",
    "manual", "help", "echo", "rsa", "vine",
    "prism", "reco_bldr",
})

_INTERNAL_CMDS = frozenset({
    "list", "set", "del", "rule", "resolve",
    "help", "update", "reverse",
    "install", "uninstall", "init",
})

_LAYER_COLOUR = {
    "user (L1)":    "bold magenta",
    "module (L2)":  "bold cyan",
    "default (L3)": "dim",
}

# ---------------------------------------------------------------------------
# apix bridge  (contrat dict v2)
# ---------------------------------------------------------------------------

def _apix(args_str: str, log_fn, db=None, token=None):
    payload = {"args": args_str, "logfn": log_fn}
    if db    is not None: payload["db"]    = db
    if token is not None: payload["token"] = token
    return apix.R_ECO3(payload)


# ---------------------------------------------------------------------------
# banana bridge
# ---------------------------------------------------------------------------

def _q(s: str) -> str:
    return '"' + str(s).replace('"', '\\"') + '"'


def _b(log_fn):
    def bn(args):
        r = _apix(f"run banana {args}", log_fn)
        return r.get("value") if isinstance(r, dict) else r

    def _ok(msg):    bn(f"ok --msg={_q(msg)}")
    def _err(msg):   bn(f"err --msg={_q(msg)}")
    def _print(msg): bn(f"print --msg={_q(msg)}")

    def _panel(content, title="", border="blue", subtitle="", box="ROUNDED"):
        a = f"panel --msg={_q(content)} --border={border} --box={box}"
        if title:    a += f" --title={_q(title)}"
        if subtitle: a += f" --subtitle={_q(subtitle)}"
        bn(a)

    def _question(msg, choices):
        r = bn(f"question --msg={_q(msg)} --choices={_q(','.join(choices))}")
        return r["value"] if isinstance(r, dict) else r

    def _checkbox(msg, choices):
        r = bn(f"question --msg={_q(msg)} --choices={_q(','.join(choices))} --multi=true")
        val = r["value"] if isinstance(r, dict) else r
        return val or []

    return {
        "ok":       _ok,
        "err":      _err,
        "print":    _print,
        "panel":    _panel,
        "question": _question,
        "checkbox": _checkbox,
        "raw":      bn,
    }


# ---------------------------------------------------------------------------
# DB helper — lecture simple, pas de as_str
# ---------------------------------------------------------------------------

def _dbget(db, key: str):
    """Lecture neutre : retourne str ou None, sans as_str."""
    val = db.get(key)
    if val is None:
        return None
    return str(val) if not isinstance(val, str) else val

# ---------------------------------------------------------------------------
# Registry helpers
# ---------------------------------------------------------------------------

def _reg_read(db, key: str) -> list:
    raw = _dbget(db, key)
    if not raw:
        return []
    return [s.strip() for s in raw.split(_SEP) if s.strip()]


def _reg_write(db, key: str, stems: list):
    db.set(key, _SEP.join(sorted(set(stems))))


def _ensure_core_registry(db):
    current = set(_reg_read(db, _KEY_REGISTRY_CORE))
    present = {s for s in _CORE_STEMS if (trail.MODULES_DIR / f"{s}.py").exists()}
    if present != current:
        _reg_write(db, _KEY_REGISTRY_CORE, list(present))


def _all_registered_stems(db) -> list:
    _ensure_core_registry(db)
    core_stems = _reg_read(db, _KEY_REGISTRY_CORE)
    user_stems = _reg_read(db, _KEY_REGISTRY)
    seen, result = set(), []
    for stem in core_stems + user_stems:
        if stem not in seen:
            seen.add(stem)
            result.append(stem)
    return result


# ---------------------------------------------------------------------------
# L2 module loader
# ---------------------------------------------------------------------------

def _load_l2_mods(db) -> dict:
    """Charge tous les modules L2. db est toujours fourni."""
    _all_registered_stems(db)   # s'assure que le registre core est à jour

    result = _apix("listl2", lambda _: None)
    stems  = result.get("value", []) if isinstance(result, dict) else []

    l2 = {}
    for stem in stems:
        try:
            import importlib.util as _ilu
            path = trail.MODULES_DIR / f"{stem}.py"
            spec = _ilu.spec_from_file_location(stem, path)
            mod  = _ilu.module_from_spec(spec) #type: ignore
            spec.loader.exec_module(mod) #type: ignore
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
    marker = marker_raw.strip()
    if marker == "/*":
        no_args = True
    elif marker == "*":
        no_args = False
    else:
        return None
    lhs_tokens = [keyword]
    rhs_tokens = [None if tok == "*" else tok for tok in rhs_raw.strip().split()]
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
    lhs_parts = lhs_raw.strip().split()
    if not lhs_parts:
        return None
    marker = lhs_parts[-1]
    if marker == "/*":
        no_args, lhs_tokens = True,  lhs_parts[:-1]
    elif marker == "*":
        no_args, lhs_tokens = False, lhs_parts[:-1]
    else:
        return None
    if not lhs_tokens:
        lhs_tokens = ["*"]
    rhs_tokens = [None if tok in ("*", "/*") else tok for tok in rhs_raw.strip().split()]
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
    raw = _dbget(db, f"{prefix}{keyword}")
    if not raw:
        return []
    return _parse_stored_value(keyword, raw)


def _layer_keywords(db, prefix: str) -> list:
    try:
        keys = [k for k in db.list() if k.startswith(prefix)]
        return [k[len(prefix):] for k in keys]
    except AttributeError:
        pass
    l2 = _load_l2_mods(db)
    existing = []
    for kw in list(l2) + ["*"]:
        if _dbget(db, f"{prefix}{kw}"):
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
    l2 = _load_l2_mods(db)
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
        default_vals = {_build_stored_value([d]) for d in _default_rules_for_stem(kw)}
        l2_v = [r for r in rules if _build_stored_value([r]) not in default_vals]
        l3_v = [r for r in rules if _build_stored_value([r]) in default_vals]
        if l2_v: routing_table.append((kw, "module (L2)", l2_v))
        if l3_v: routing_table.append((kw, "default (L3)", l3_v))
        all_keywords_seen.add(kw)

    for stem in sorted(l2):
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
            if l2_only: normalized.append((kw, "module (L2)", l2_only))
            if l3_only: normalized.append((kw, "default (L3)", l3_only))
        else:
            normalized.append((kw, src, rules))
    return normalized


# ---------------------------------------------------------------------------
# Resolver (pur, sans effet de bord)
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
                if no_args and extra:         continue
                if not no_args and not extra: continue
                candidates.append((0, int(no_args), rhs_tokens, extra))
                continue
            n = len(lhs_tokens)
            if input_tokens[:n] != lhs_tokens:
                continue
            extra = input_tokens[n:]
            if no_args and extra:         continue
            if not no_args and not extra: continue
            candidates.append((n, int(no_args), rhs_tokens, extra))

    if not candidates:
        return None, None

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
# Rule display helper
# ---------------------------------------------------------------------------

def _rule_to_str(lhs_tokens, no_args, rhs_tokens) -> str:
    lhs_str = " ".join(lhs_tokens)
    marker  = " /*" if no_args else " *"
    rhs_str = " ".join("*" if t is None else t for t in rhs_tokens)
    return f"{lhs_str}{marker} = {rhs_str}"


# ---------------------------------------------------------------------------
# Sub-command: init
# ---------------------------------------------------------------------------

def _cmd_init(db, log_fn):
    b = _b(log_fn)
    b["panel"]("Scanning [bold]modules/[/] for unregistered L2 modules…",
               title=" mycelium init ", border="cyan")

    registered  = set(_all_registered_stems(db))
    list_result = _apix("list", lambda _: None)
    all_stems   = list_result.get("value", []) if isinstance(list_result, dict) else []

    candidates = []
    for stem in all_stems:
        if stem in registered:
            continue
        inf_result = _apix(f"inf {stem}", lambda _: None)
        inf        = inf_result.get("value", {}) if isinstance(inf_result, dict) else {}
        if inf.get("L2Module") is not True:
            continue
        candidates.append((stem, inf.get("name", stem),
                            inf.get("version_mod", "?"), inf.get("desc", "")))

    if not candidates:
        b["ok"]("No new modules found — registry is already up to date.")
        return 0

    choices = [
        f"{stem}  —  {desc}  [v{ver}]" if desc else f"{stem}  [v{ver}]"
        for stem, _, ver, desc in candidates
    ]
    b["print"](f"[dim]Found [bold]{len(candidates)}[/] unregistered module(s).[/]")

    selected_labels = b["checkbox"](
        "Select modules to install  (space = toggle, enter = confirm)", choices)

    if not selected_labels:
        b["print"]("[dim]Nothing selected — no changes made.[/]")
        return 0

    label_to_stem = {label: stem for (stem, _, ver, desc), label in zip(candidates, choices)}
    user_stems    = _reg_read(db, _KEY_REGISTRY)
    installed     = []

    for label in selected_labels:
        stem = label_to_stem.get(label)
        if not stem or stem in user_stems:
            continue
        user_stems.append(stem)
        installed.append(stem)

    if installed:
        _reg_write(db, _KEY_REGISTRY, user_stems)
        for stem in installed:
            b["ok"](f"Installed: [bold]{stem}[/]")
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
        inf_result = _apix(f"inf {stem}", lambda _: None)
        inf        = inf_result.get("value", {}) if isinstance(inf_result, dict) else {}
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
        title=" Module installed ", border="green")
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

    path        = trail.MODULES_DIR / f"{stem}.py"
    delete_file = False

    if path.exists():
        choice = b["question"](
            f"Uninstall '{stem}' — also delete {stem}.py?",
            ["Remove from registry only", "Delete file too", "Cancel"])
        if choice is None or "cancel" in str(choice).lower():
            b["print"]("[dim]Uninstall cancelled.[/]")
            return 0
        delete_file = "delete" in str(choice).lower()
    else:
        choice = b["question"](
            f"'{stem}.py' not found on disk. Remove '{stem}' from registry?",
            ["Yes", "Cancel"])
        if choice is None or "cancel" in str(choice).lower():
            b["print"]("[dim]Uninstall cancelled.[/]")
            return 0

    user_stems = [s for s in user_stems if s != stem]
    _reg_write(db, _KEY_REGISTRY, user_stems)

    for prefix in (_PREFIX_USER, _PREFIX_MODULE):
        key = f"{prefix}{stem}"
        if _dbget(db, key):
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
    l2 = _load_l2_mods(db)

    # ── Detail view for one keyword ───────────────────────────────────────
    if len(tokens) > 1:
        target = tokens[1]
        lines  = []
        found  = False

        for prefix, label, colour in (
            (_PREFIX_USER,   "user (L1)",   "magenta"),
            (_PREFIX_MODULE, "module (L2)", "cyan"),
        ):
            raw = _dbget(db, f"{prefix}{target}")
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

    reg_lines = []
    reg_lines.append(f"[bold]Core modules[/]  [dim]({len(core_reg)} auto-registered)[/]")
    for stem in sorted(core_reg):
        path     = trail.MODULES_DIR / f"{stem}.py"
        status   = "[green]✓[/]" if path.exists() else "[red]✗ MISSING[/]"
        mod      = l2.get(stem)
        desc     = mod.R_ECO3inf().get("desc", "")        if mod else ""
        ver      = mod.R_ECO3inf().get("version_mod", "") if mod else ""
        ver_str  = f" [dim]v{ver}[/]"  if ver  else ""
        desc_str = f"  [dim]{desc}[/]" if desc else ""
        reg_lines.append(f"  {status} [cyan]{stem:<18}[/]{ver_str}{desc_str}")

    reg_lines.append("")
    reg_lines.append(f"[bold]User modules[/]  [dim]({len(user_reg)} installed)[/]")
    if user_reg:
        for stem in sorted(user_reg):
            path     = trail.MODULES_DIR / f"{stem}.py"
            status   = "[green]✓[/]" if path.exists() else "[red]✗ MISSING[/]"
            mod      = l2.get(stem)
            desc     = mod.R_ECO3inf().get("desc", "")        if mod else ""
            ver      = mod.R_ECO3inf().get("version_mod", "") if mod else ""
            ver_str  = f" [dim]v{ver}[/]"  if ver  else ""
            desc_str = f"  [dim]{desc}[/]" if desc else ""
            reg_lines.append(f"  {status} [magenta]{stem:<18}[/]{ver_str}{desc_str}")
    else:
        reg_lines.append(
            "  [dim](none — use [bold]mycelium install <stem>[/] or [bold]mycelium init[/])[/]")

    b["panel"]("\n".join(reg_lines), title=" Registry ", border="cyan", box="ROUNDED")

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
            route_lines.append(f"  [bold]{kw:<20}[/] [dim]{_build_stored_value(rules)}[/]")
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
    l2      = _load_l2_mods(db)

    if db.delete(l1_key):
        b["ok"](f"user (L1) override for [bold]{keyword}[/] removed")
        raw_l2 = _dbget(db, l2_key)
        if raw_l2:
            b["print"](f"  [dim]→ now resolved via module (L2): {raw_l2}[/]")
        elif keyword in l2:
            b["print"]("  [dim]→ now resolved via default (L3)[/]")
        else:
            b["print"]("  [yellow]→ no L2/L3 fallback — keyword will be unknown[/]")
        return 0

    raw_l2 = _dbget(db, l2_key)
    if raw_l2:
        b["print"](f"[dim]'{keyword}' has no user (L1) override to delete.[/]")
        b["print"](f"[dim]Current module (L2): {raw_l2}[/]")
        b["print"](f"[dim]To override: [bold]mycelium set {keyword} <variants>[/][/]")
        return 0

    for stem, mod in l2.items():
        if keyword in _rules_from_inf(stem, mod):
            b["print"](f"[dim]'{keyword}' only in inf of '{stem}' — run update first[/]")
            return 0

    b["err"](f"'{keyword}': not found in any layer")
    return 1


# ---------------------------------------------------------------------------
# Sub-command: rule  (dry-run human — db fourni par _with_db)
# ---------------------------------------------------------------------------

def _cmd_rule(args_raw, db, log_fn):
    b        = _b(log_fn)
    parts    = args_raw.strip().split(None, 1)
    rule_cmd = parts[1] if len(parts) > 1 else ""
    if not rule_cmd:
        b["err"]("usage: mycelium rule <command> [args...]")
        return 1

    table = _build_mycelium(db)
    dispatch, err_msg = _resolve(rule_cmd, table)
    if dispatch is None:
        if err_msg is not None:
            b["err"](err_msg)
        return 1

    d_parts  = dispatch.split()
    mod_name = d_parts[0]
    mod_args = " ".join(d_parts[1:]) if len(d_parts) > 1 else ""

    input_kw = rule_cmd.split()[0]
    raw_l1   = _dbget(db, f"{_PREFIX_USER}{input_kw}")
    raw_l2   = _dbget(db, f"{_PREFIX_MODULE}{input_kw}")

    if raw_l1:
        source_label, source_col = "user (L1)",   "magenta"
    elif raw_l2:
        source_label, source_col = "module (L2)", "cyan"
    else:
        l2  = _load_l2_mods(db)
        mod = l2.get(mod_name)
        inf_grp = _rules_from_inf(mod_name, mod) if mod else {}
        if input_kw in inf_grp:
            source_label, source_col = "inf (run update)", "yellow"
        else:
            source_label, source_col = "default (L3)", "dim"

    arrow = f"[bold]{rule_cmd}[/]  →  [bold green]{mod_name}[/]"
    if mod_args:
        arrow += f"  [dim]--args=\"{mod_args}\"[/]"
    arrow += f"  [[{source_col}]{source_label}[/]]"
    b["panel"](arrow, title=" rule resolution ", border="blue", box="SIMPLE")
    return 0


# ---------------------------------------------------------------------------
# Sub-command: resolve  (machine-facing, appelé par squid)
# ---------------------------------------------------------------------------

def _cmd_resolve(tokens, args_raw, db, log_fn):
    """
    Résolution pure. Retourne la dispatch string ou 1.
    apix._wrap() encapsule en {"status":0, "value":dispatch}.
    """
    b     = _b(log_fn)
    parts = args_raw.strip().split(None, 1)
    cmd_line = parts[1] if len(parts) > 1 else ""

    if not cmd_line:
        b["err"]("usage: mycelium resolve <command> [args...]")
        return 1

    table = _build_mycelium(db)
    dispatch, err_msg = _resolve(cmd_line, table)
    if dispatch is None:
        if err_msg is not None:
            b["err"](err_msg)
        return 1

    return dispatch


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

    # A) Intégrité du registre
    removed_total = 0
    for reg_key, label in ((_KEY_REGISTRY_CORE, "core"), (_KEY_REGISTRY, "user")):
        stems = _reg_read(db, reg_key)
        kept  = []
        for stem in stems:
            if (trail.MODULES_DIR / f"{stem}.py").exists():
                kept.append(stem)
            else:
                b["print"](f"[yellow]  ✗ '{stem}' missing — removed from {label} registry[/]")
                removed_total += 1
        if len(kept) != len(stems):
            _reg_write(db, reg_key, kept)

    if removed_total == 0:
        b["ok"]("Registry integrity OK — all modules present on disk.")
    else:
        b["print"](f"[yellow]  {removed_total} missing module(s) purged.[/]")

    # B) Sync L2 alias
    l2                          = _load_l2_mods(db)
    written = skipped = updated = conflicts = deleted = 0

    inf_index = {}
    for stem in sorted(l2):
        for keyword, inf_rules in _rules_from_inf(stem, l2[stem]).items():
            inf_index[keyword] = _build_stored_value(inf_rules)

    existing_l2 = set(_layer_keywords(db, _PREFIX_MODULE))

    for keyword, new_val in inf_index.items():
        l2_key  = f"{_PREFIX_MODULE}{keyword}"
        cur_val = _dbget(db, l2_key)
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
                f"  current L2 : {cur_val}\n"
                f"  new   (inf): {new_val}",
                ["Keep current (L2)", "Use new (inf)", "Skip"])
            if choice and "new"  in str(choice).lower():
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
        f"[green]wrote {written}[/]  [dim]skipped {skipped}[/]  "
        f"[cyan]updated {updated}[/]  [yellow]conflicts {conflicts}[/]  "
        f"[red]deleted {deleted}[/]  [yellow]registry_removed {removed_total}[/]"
    )
    b["panel"](summary + "\n\n[dim]User (L1) overrides are never modified by update.[/]",
               title=" update complete ", border="green", box="ROUNDED")
    return 0


# ---------------------------------------------------------------------------
# R_ECO3 — point d'entrée  (contrat dict apix v2)
# ---------------------------------------------------------------------------

def R_ECO3(inp):
    """
    inp = {args, logfn, db?, token?}
    db est réutilisé s'il est fourni — mycelium n'ouvre jamais la DB
    sauf en dernier recours (appels directs sans caller, ex. tests).
    """
    args   = inp.get("args",  "")    if isinstance(inp, dict) else str(inp)
    log_fn = inp.get("logfn", print) if isinstance(inp, dict) else print
    ext_db = inp.get("db")           if isinstance(inp, dict) else None

    try:
        tokens = utils.tokenize(args.strip()) if args.strip() else []
    except Exception:
        tokens = args.strip().split() if args.strip() else []

    if not tokens:
        _b(log_fn)["err"]("This module requires arguments — use 'mycelium help'.")
        return 1

    sub = tokens[0]

    def _with_db(fn):
        if ext_db is not None:
            return fn(ext_db)

    if sub == "init":      return _with_db(lambda db: _cmd_init(db, log_fn))
    if sub == "install":   return _with_db(lambda db: _cmd_install(tokens, db, log_fn))
    if sub == "uninstall": return _with_db(lambda db: _cmd_uninstall(tokens, db, log_fn))
    if sub == "list":      return _with_db(lambda db: _cmd_list(tokens, db, log_fn))
    if sub == "set":       return _with_db(lambda db: _cmd_set(tokens, args, db, log_fn))
    if sub == "del":       return _with_db(lambda db: _cmd_del(tokens, db, log_fn))
    if sub == "rule":      return _with_db(lambda db: _cmd_rule(args, db, log_fn))
    if sub == "resolve":   return _with_db(lambda db: _cmd_resolve(tokens, args, db, log_fn))
    if sub == "update":    return _with_db(lambda db: _cmd_update(db, log_fn))
    if sub == "reverse":   return _with_db(lambda db: _cmd_reverse(tokens, db, log_fn))
    if sub == "help":
        log_fn(R_ECO3inf()["manual"])
        return 0

    _b(log_fn)["err"](f"Unknown sub-command: '{sub}' — use 'mycelium help'")
    return 1


# ---------------------------------------------------------------------------
# R_ECO3dep / R_ECO3inf
# ---------------------------------------------------------------------------

def R_ECO3dep():
    return {
        "reco": ["3.5.2b"],
        "module": [{"banana": ["2.1"]}],
    }


def R_ECO3inf():
    return {
        "name":        "mycelium",
        "desc":        "3-layer alias/registry manager — résout les commandes, n'exécute rien",
        "help":        (
            "mycelium init | install <stem> | uninstall <stem> | list [kw] | "
            "set <kw> <v> | del <kw> | rule <cmd> | resolve <cmd> | update | reverse <mod>"
        ),
        "version_mod": "2.0",
        "L2Module":    True,
        "manual": """
mycelium — R-ECOSYSTEM alias / registry manager  v2.0
=======================================================

SYNOPSIS
    mycelium init
    mycelium install   <stem>
    mycelium uninstall <stem>
    mycelium list      [<keyword>]
    mycelium set       <keyword> <variants>
    mycelium del       <keyword>
    mycelium rule      <cmd> [args...]
    mycelium resolve   <cmd> [args...]
    mycelium update
    mycelium reverse   <module>
    mycelium help

PRINCIPES v2.0
    mycelium ne fait QUE gérer le registre et les règles d'alias.
    L'exécution appartient à squid.

    db est toujours fourni par le caller (squid/raven) via le payload
    {args, logfn, db, token}. mycelium ne rouvre jamais la DB sauf
    en dernier recours (appels directs sans db, ex. tests CLI).

    Tous les db.get() passent par _dbget() — jamais de as_str=True.

CONTRAT apix v2
    R_ECO3 accepte uniquement un dict : {args, logfn, db?, token?}

REGISTRE
    §sys:mycelium:registry         — modules user
    §sys:mycelium:registry:core    — modules système (auto)

ROUTAGE 3 COUCHES
    L1 user    §sys:mycelium:rules:user:<keyword>
    L2 module  §sys:mycelium:rules:module:<keyword>
    L3 default implicite : <stem> /* = <stem>  /  * = <stem> *

EXEMPLES
    mycelium resolve vine status    → retourne "vine status"
    mycelium rule vine status       → affiche le panel dry-run
    mycelium list
    mycelium update
""",
    }