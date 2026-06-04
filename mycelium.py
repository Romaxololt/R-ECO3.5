"""
mycelium.py — R-ECOSYSTEM module mycelium & command dispatcher
Version : 1.3
Codename: Fungus

Responsibilities
----------------
1. Scan MODULES_DIR for every .py file that declares L2Module=True in R_ECO3inf().
   mycelium itself is included so that "mycelium help", "mycelium set", etc. are routable.

2. For each discovered L2 module, route commands through THREE priority layers:

       Layer 1  §sys:mycelium:rules:user:<keyword>      ← user overrides (set/del)
       Layer 2  §sys:mycelium:rules:module:<keyword>     ← written by `mycelium update`
       Layer 3  implicit default                         ← <stem> /* = <stem>
                                                            <stem> *  = <stem> *

   Resolution stops at the first layer that has a match for the input keyword.
   Layer 1 is NEVER modified by `update`.

3. Expose R_ECO3() so that raven (or any other shell) can call:
       mycelium <command> [args...]

Storage keys
------------
    §sys:mycelium:rules:user:<keyword>    — written by `mycelium set`
    §sys:mycelium:rules:module:<keyword>  — written by `mycelium update`

Value format (same for both layers)
------------------------------------
    "|||"-separated list of per-keyword variants:

        "/* = echo ||| * = echo /*"

    Variant syntax:
        /*  = rhs_tokens          zero-arg variant  (matched when NO extra args)
        *   = rhs_tokens          any-arg variant   (matched always)
        *   = rhs_tokens /*       any-arg variant, injects extra args at /* position

    Special keyword "*" → catch-all.

`mycelium update` command
-------------------------
Strict sync of Layer 2 against the alias_rules currently declared by all active
L2 modules.  After `update`, Layer 2 mirrors exactly what the modules declare:
  - Keyword absent in L2               → write it silently.
  - Keyword identical                  → skip silently.
  - Keyword differs                    → ask user via banana (update or skip).
  - Keyword in L2 but no module owns it → DELETE silently (stale entry removed).
Layer 1 (user) keys are NEVER touched by `update`.
"""

import os
import sys

import core

# ---------------------------------------------------------------------------
# Bootstrap: make sure core is importable regardless of cwd
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

_PREFIX_USER   = "§sys:mycelium:rules:user:"     # Layer 1 — user overrides
_PREFIX_MODULE = "§sys:mycelium:rules:module:"   # Layer 2 — module aliases (update)

_INTERNAL_CMDS = frozenset({"list", "set", "del", "rule", "exe",
                             "help", "update", "reverse"})

# Human-readable layer labels
_LAYER_LABEL = {
    _PREFIX_USER:   "user   (L1)",
    _PREFIX_MODULE: "module (L2)",
}

# ---------------------------------------------------------------------------
# Helpers — DB
# ---------------------------------------------------------------------------

def _open_db():
    return hive_mod.HiveFS(filepath=str(trail.DB_FILE))


def _load_l2_modules():
    """Return dict stem → module for every L2Module=True in MODULES_DIR."""
    l2 = {}
    for fname in os.listdir(str(trail.MODULES_DIR)):
        if not fname.endswith(".py") or fname.startswith("_"):
            continue
        stem = fname[:-3]
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
# Rule parsing — stored (per-keyword) format
# ---------------------------------------------------------------------------

def _parse_stored_variant(keyword: str, variant_str: str):
    """
    Parse one variant stored under a layer key.

    variant_str examples (keyword NOT included):
        "/* = echo test"
        "* = echo test /*"
        "* = echo test"

    Returns (lhs_tokens, no_args, rhs_tokens) or None on syntax error.
    """
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
        if tok in ("*", "/*"):
            rhs_tokens.append(None)
        else:
            rhs_tokens.append(tok)

    return (lhs_tokens, no_args, rhs_tokens)


def _parse_stored_value(keyword: str, raw_value: str):
    """
    Parse the full value of a layer key for <keyword>.
    Returns list of (lhs_tokens, no_args, rhs_tokens).
    """
    rules = []
    for part in raw_value.split("|||"):
        part = part.strip()
        if not part:
            continue
        parsed = _parse_stored_variant(keyword, part)
        if parsed:
            rules.append(parsed)
    return rules


def _build_stored_value(rules_for_keyword: list) -> str:
    """
    Serialize a list of (lhs_tokens, no_args, rhs_tokens) back to stored string.
    Only the variant marker and RHS are stored (keyword is the key).
    """
    parts = []
    for (_, no_args, rhs_tokens) in rules_for_keyword:
        marker  = "/*" if no_args else "*"
        rhs_str = " ".join("/*" if t is None else t for t in rhs_tokens)
        parts.append(f"{marker} = {rhs_str}")
    return " ||| ".join(parts)

# ---------------------------------------------------------------------------
# Legacy alias_rules parser (for R_ECO3inf()["alias_rules"])
# ---------------------------------------------------------------------------

def _parse_legacy_rule(rule_str: str):
    """
    Parse a full legacy rule string (as found in alias_rules):
        "echo * = echo /*"
        "echo /* = echo"
        "test /* = echo test"

    Returns (lhs_tokens, no_args, rhs_tokens) or None.
    """
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
        if tok in ("*", "/*"):
            rhs_tokens.append(None)
        else:
            rhs_tokens.append(tok)

    return (lhs_tokens, no_args, rhs_tokens)


def _group_legacy_rules_by_keyword(raw: str) -> dict:
    """
    Parse a legacy alias_rules string and group rules by their first LHS token.
    Returns dict: keyword → list of (lhs_tokens, no_args, rhs_tokens)
    """
    groups = {}
    for part in raw.split("|||"):
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
    """Return parsed rules from a specific layer prefix, or [] if absent."""
    raw = db.get(f"{prefix}{keyword}", default=None, as_str=True)
    if not raw:
        return []
    return _parse_stored_value(keyword, raw)


def _layer_keywords(db, prefix: str) -> list:
    """Return all keywords stored under a given layer prefix."""
    try:
        keys = [k for k in db.list() if k.startswith(prefix)]
        return [k[len(prefix):] for k in keys]
    except AttributeError:
        pass
    # Fallback: scan L2 stems + catch-all
    l2       = _load_l2_modules()
    keywords = list(l2.keys()) + ["*"]
    existing = []
    for kw in keywords:
        raw = db.get(f"{prefix}{kw}", default=None, as_str=True)
        if raw:
            existing.append(kw)
    return existing

# ---------------------------------------------------------------------------
# Default rules
# ---------------------------------------------------------------------------

def _default_rules_for_stem(stem: str):
    """
    Implicit rules when no layer 1 or layer 2 entry exists:
        stem /* = stem
        stem *  = stem *
    """
    return [
        ([stem], True,  [stem]),          # stem /* = stem
        ([stem], False, [stem, None]),    # stem *  = stem *
    ]

# ---------------------------------------------------------------------------
# inf alias_rules reader
# ---------------------------------------------------------------------------

def _rules_from_inf(stem: str, mod) -> dict:
    """
    Read R_ECO3inf()["alias_rules"], parse, group by keyword.
    Returns dict keyword → list of rules.
    """
    try:
        raw = mod.R_ECO3inf().get("alias_rules", "")
        if raw:
            return _group_legacy_rules_by_keyword(raw)
    except Exception:
        pass
    return {}

# ---------------------------------------------------------------------------
# Build mycelium routing table  (3-layer)
# ---------------------------------------------------------------------------

def _build_mycelium(db):
    """
    Build the full routing table as a flat list of
        (keyword, layer_label, rules_list)
    where rules_list = list of (lhs_tokens, no_args, rhs_tokens).

    Priority per keyword:
        Layer 1  §sys:mycelium:rules:user:<keyword>
        Layer 2  §sys:mycelium:rules:module:<keyword>
        Layer 3  implicit default

    Resolution stops at the first layer that has rules for the keyword.
    """
    l2 = _load_l2_modules()

    # Ensure mycelium itself is included
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

    routing_table      = []
    all_keywords_seen  = set()

    # ── Layer 1 : user overrides ──────────────────────────────────────────
    for kw in _layer_keywords(db, _PREFIX_USER):
        rules = _layer_get(db, _PREFIX_USER, kw)
        if rules:
            routing_table.append((kw, "user (L1)", rules))
            all_keywords_seen.add(kw)

    # ── Layer 2 : module aliases (written by update) ──────────────────────
    for kw in _layer_keywords(db, _PREFIX_MODULE):
        if kw in all_keywords_seen:
            continue   # already covered by layer 1
        rules = _layer_get(db, _PREFIX_MODULE, kw)
        if rules:
            routing_table.append((kw, "module (L2)", rules))
            all_keywords_seen.add(kw)

    # ── Layer 3 : implicit defaults for stems not covered above ───────────
    for stem in sorted(l2.keys()):
        if stem not in all_keywords_seen:
            routing_table.append((stem, "default (L3)", _default_rules_for_stem(stem)))
            all_keywords_seen.add(stem)
        else:
            # Stem déjà en L1/L2 — compléter les variantes manquantes avec les defaults
            for (kw, src, rules) in routing_table:
                if kw != stem:
                    continue
                if not any(no_args for (_, no_args, _) in rules):
                    rules.append(([stem], True, [stem]))         # /* = stem
                if not any(not no_args for (_, no_args, _) in rules):
                    rules.append(([stem], False, [stem, None]))  # * = stem *
                break

    return routing_table

# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------

def _resolve(command_line: str, routing_table: list):
    """
    Resolve command_line against the routing table.

    Returns (dispatch_string, None) or (None, error_message).
    """
    if not command_line.strip():
        return None, "empty command"

    input_tokens = command_line.split()
    candidates   = []   # (score, no_args_int, rhs_tokens, extra_tokens)

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

            # Prefix match
            n = len(lhs_tokens)
            if input_tokens[:n] != lhs_tokens:
                continue

            extra = input_tokens[n:]
            if no_args and extra:
                continue
            if not no_args and not extra:   # * requires at least 1 arg
                continue

            candidates.append((n, int(no_args), rhs_tokens, extra))

    if not candidates:
        return None, f"unknown command: '{input_tokens[0]}'"

    # Most specific: longest prefix, then /* preferred over *
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
# Sub-command: list
# ---------------------------------------------------------------------------

def _cmd_list(tokens, db, log_fn):
    l2 = _load_l2_modules()

    if len(tokens) > 1:
        target = tokens[1]
        found  = False

        # Check each layer in order
        for prefix, label in ((_PREFIX_USER, "user (L1)"), (_PREFIX_MODULE, "module (L2)")):
            raw = db.get(f"{prefix}{target}", default=None, as_str=True)
            if raw:
                found = True
                log_fn(f"{prefix}{target}  [{label}]")
                log_fn(f"  stored : {raw}")
                for rule in _parse_stored_value(target, raw):
                    lhs_tokens, no_args, rhs_tokens = rule
                    marker  = " /*" if no_args else " *"
                    rhs_str = " ".join("/*" if t is None else t for t in rhs_tokens)
                    log_fn(f"  rule   : '{' '.join(lhs_tokens)}{marker}' → '{rhs_str}'")

        if not found:
            # Show inf / default
            mod = l2.get(target)
            if mod:
                inf_groups = _rules_from_inf(target, mod)
                if target in inf_groups:
                    rules = inf_groups[target]
                    val   = _build_stored_value(rules)
                    log_fn(f"  (not in HiveFS — inf alias_rules) = {val}")
                    for rule in rules:
                        lhs_tokens, no_args, rhs_tokens = rule
                        marker  = " /*" if no_args else " *"
                        rhs_str = " ".join("/*" if t is None else t for t in rhs_tokens)
                        log_fn(f"  rule   : '{' '.join(lhs_tokens)}{marker}' → '{rhs_str}'")
                    log_fn("  → would be stored in module (L2) after `mycelium update`")
                else:
                    rules = _default_rules_for_stem(target)
                    val   = _build_stored_value(rules)
                    log_fn(f"  (not in HiveFS — implicit default) = {val}")
                    for rule in rules:
                        lhs_tokens, no_args, rhs_tokens = rule
                        marker  = " /*" if no_args else " *"
                        rhs_str = " ".join("/*" if t is None else t for t in rhs_tokens)
                        log_fn(f"  rule   : '{' '.join(lhs_tokens)}{marker}' → '{rhs_str}'")
                return 0

            log_fn(f"[mycelium] '{target}': not found in any layer and not a known L2 stem")
            return 1

        return 0

    # ── Full listing ──────────────────────────────────────────────────────
    table = _build_mycelium(db)

    # Group by layer for readability
    by_layer = {}
    for kw, src, rules in table:
        by_layer.setdefault(src, []).append((kw, rules))

    layer_order = ["user (L1)", "module (L2)", "default (L3)"]
    log_fn("mycelium routing table")
    log_fn("=" * 60)
    for layer in layer_order:
        entries = by_layer.get(layer, [])
        if not entries:
            continue
        log_fn(f"\n  ── {layer} ──")
        for kw, rules in entries:
            val = _build_stored_value(rules)
            log_fn(f"    {kw:<20} {val}")

    return 0

# ---------------------------------------------------------------------------
# Sub-command: set  (writes to Layer 1 — user)
# ---------------------------------------------------------------------------

def _cmd_set(tokens, args_raw, db, log_fn):
    """
    mycelium set <keyword> <variants>

    Always writes to Layer 1 (user overrides).
    variants use the per-keyword format:
        "/* = module args ||| * = module args /*"
    """
    if len(tokens) < 3:
        log_fn("[mycelium] usage: mycelium set <keyword> <variants>")
        log_fn("  variants: '/* = module args ||| * = module args /*'")
        log_fn("  (always stored in Layer 1 — user override)")
        return 1

    keyword = tokens[1]
    parts   = args_raw.strip().split(None, 2)
    if len(parts) < 3:
        log_fn("[mycelium] usage: mycelium set <keyword> <variants>")
        return 1
    raw_val = parts[2]
    if len(raw_val) >= 2 and raw_val[0] in ('"', "'") and raw_val[-1] == raw_val[0]:
        raw_val = raw_val[1:-1]

    parsed = _parse_stored_value(keyword, raw_val)
    if not parsed:
        log_fn(f"[mycelium] syntax error in rule variants: '{raw_val}'")
        log_fn("  expected: '/* = rhs' or '* = rhs' (separated by |||)")
        return 1

    db.set(f"{_PREFIX_USER}{keyword}", raw_val)
    log_fn(f"[mycelium] {_PREFIX_USER}{keyword} set to: {raw_val}  [user (L1)]")
    return 0

# ---------------------------------------------------------------------------
# Sub-command: del  (removes from Layer 1 — user)
# ---------------------------------------------------------------------------

def _cmd_del(tokens, db, log_fn):
    """
    mycelium del <keyword>

    Removes the user (L1) override for <keyword>.
    Does NOT touch Layer 2 (module) entries.
    After deletion, Layer 2 or Layer 3 will take effect.
    """
    if len(tokens) < 2:
        log_fn("[mycelium] usage: mycelium del <keyword>")
        return 1

    keyword  = tokens[1]
    l1_key   = f"{_PREFIX_USER}{keyword}"
    l2_key   = f"{_PREFIX_MODULE}{keyword}"
    l2       = _load_l2_modules()

    if db.delete(l1_key):
        log_fn(f"[mycelium] {l1_key} deleted  [user (L1) removed]")

        # Inform which layer now takes effect
        raw_l2 = db.get(l2_key, default=None, as_str=True)
        if raw_l2:
            log_fn(f"[mycelium] '{keyword}' now resolved via module (L2): {raw_l2}")
        else:
            mod = l2.get(keyword)
            if mod:
                log_fn(f"[mycelium] '{keyword}' now resolved via default (L3)")
            else:
                log_fn(f"[mycelium] '{keyword}' has no L2/L3 fallback — will be unknown")
        return 0

    # Not in L1 — check where it does live
    raw_l2 = db.get(l2_key, default=None, as_str=True)
    if raw_l2:
        log_fn(f"[mycelium] '{keyword}' has no user (L1) override to delete")
        log_fn(f"[mycelium] current module (L2) entry: {raw_l2}")
        log_fn(f"[mycelium] to override instead: mycelium set {keyword} <variants>")
        return 0

    # Check inf
    for stem, mod in l2.items():
        inf_groups = _rules_from_inf(stem, mod)
        if keyword in inf_groups:
            raw_inf = _build_stored_value(inf_groups[keyword])
            log_fn(f"[mycelium] '{keyword}' has no HiveFS entry (source: inf of '{stem}')")
            log_fn(f"[mycelium] inf value: {raw_inf}")
            log_fn(f"[mycelium] run `mycelium update` to load it into L2, or:")
            log_fn(f"[mycelium]     mycelium set {keyword} <variants>  to create an L1 override")
            return 0

    log_fn(f"[mycelium] '{keyword}': not found in any layer")
    return 1

# ---------------------------------------------------------------------------
# Sub-command: rule  (dry-run resolver)
# ---------------------------------------------------------------------------

def _cmd_rule(args_raw, log_fn):
    parts    = args_raw.strip().split(None, 1)
    rule_cmd = parts[1] if len(parts) > 1 else ""
    if not rule_cmd:
        log_fn("[mycelium] usage: mycelium rule <command> [args...]")
        return 1

    db = _open_db()
    try:
        table = _build_mycelium(db)
    finally:
        db.close()

    dispatch, err = _resolve(rule_cmd, table)
    if dispatch is None:
        log_fn(f"[mycelium] {err}")
        return 1

    d_parts  = dispatch.split()
    mod_name = d_parts[0]
    mod_args = " ".join(d_parts[1:]) if len(d_parts) > 1 else ""

    # Find which layer answered
    db2 = _open_db()
    try:
        input_kw = rule_cmd.split()[0]
        raw_l1   = db2.get(f"{_PREFIX_USER}{input_kw}",   default=None, as_str=True)
        raw_l2   = db2.get(f"{_PREFIX_MODULE}{input_kw}", default=None, as_str=True)
        if raw_l1:
            source = f"user (L1): {raw_l1}"
        elif raw_l2:
            source = f"module (L2): {raw_l2}"
        else:
            l2  = _load_l2_modules()
            mod = l2.get(mod_name)
            inf_grp = _rules_from_inf(mod_name, mod) if mod else {}
            if input_kw in inf_grp:
                source = f"inf (not yet in L2 — run update): {_build_stored_value(inf_grp[input_kw])}"
            else:
                source = "default (L3)"
    except Exception:
        source = "?"
    finally:
        db2.close()

    if mod_args:
        log_fn(f"[mycelium] '{rule_cmd}' → {mod_name} --args=\"{mod_args}\"  [{source}]")
    else:
        log_fn(f"[mycelium] '{rule_cmd}' → {mod_name}  [{source}]")
    return 0

# ---------------------------------------------------------------------------
# Sub-command: reverse
# ---------------------------------------------------------------------------

def _cmd_reverse(tokens, db, log_fn):
    if len(tokens) < 2:
        log_fn("[mycelium] usage: mycelium reverse <target_module>")
        return 1
    target = tokens[1]

    table = _build_mycelium(db)
    found = []

    for (kw, src, rules) in table:
        for (lhs_tokens, no_args, rhs_tokens) in rules:
            rhs_mod = next((t for t in rhs_tokens if t is not None), None)
            if rhs_mod != target:
                continue
            lhs_str = " ".join(lhs_tokens)
            marker  = " /*" if no_args else " *"
            rhs_str = " ".join("/*" if t is None else t for t in rhs_tokens)
            found.append((kw, src, f"{lhs_str}{marker} = {rhs_str}"))

    if not found:
        log_fn(f"[mycelium] no rules point to '{target}'")
        return 0

    log_fn(f"Rules pointing to '{target}':")
    for kw, src, rule_str in found:
        log_fn(f"  [{src}] (key:{kw})  {rule_str}")
    return 0

# ---------------------------------------------------------------------------
# Sub-command: update  (strict sync of Layer 2)
# ---------------------------------------------------------------------------

def _cmd_update(db, log_fn):
    """
    Strict sync of Layer 2 (§sys:mycelium:rules:module:*) against the current
    alias_rules declared by all active L2 modules.

    Algorithm
    ---------
    1. Collect every keyword declared by any module's alias_rules  → `inf_index`
    2. Collect every keyword currently stored in L2                → `existing_l2`

    For each keyword in inf_index:
      - Absent in L2  → write silently.
      - Identical     → skip silently.
      - Different     → ask via banana; update or skip.

    For each keyword in existing_l2 NOT in inf_index:
      - Delete silently (module was removed or alias was dropped).

    Layer 1 (user) is NEVER touched.
    """
    l2        = _load_l2_modules()
    written   = 0
    skipped   = 0
    updated   = 0
    conflicts = 0
    deleted   = 0

    try:
        banana = apix.load_module("banana")
    except Exception:
        banana = None

    # ── Step 1: build inf_index  keyword → serialised value ──────────────
    inf_index = {}   # keyword → new_val (last writer wins if two modules clash)
    for stem in sorted(l2.keys()):
        mod        = l2[stem]
        inf_groups = _rules_from_inf(stem, mod)
        for keyword, inf_rules in inf_groups.items():
            inf_index[keyword] = _build_stored_value(inf_rules)

    # ── Step 2: collect existing L2 keywords ─────────────────────────────
    existing_l2 = set(_layer_keywords(db, _PREFIX_MODULE))

    # ── Step 3: add / update ─────────────────────────────────────────────
    for keyword, new_val in inf_index.items():
        l2_key  = f"{_PREFIX_MODULE}{keyword}"
        cur_val = db.get(l2_key, default=None, as_str=True)

        if cur_val is None:
            db.set(l2_key, new_val)
            log_fn(f"[mycelium] update: + {keyword} = {new_val}")
            written += 1

        elif cur_val.strip() == new_val.strip():
            skipped += 1

        else:
            conflicts += 1
            log_fn(f"[mycelium] conflict for keyword '{keyword}':")
            log_fn(f"  current (L2) : {cur_val}")
            log_fn(f"  new     (inf): {new_val}")

            choice = None
            if banana is not None:
                try:
                    _, choice = banana.R_ECO3(
                        f"question --msg=\"Conflict for '{keyword}' — keep which?\" "
                        f"--choices=\"keep current (L2),use new (inf),skip\"",
                        log_fn=log_fn,
                    )
                except Exception:
                    choice = None

            if choice is None:
                log_fn("[mycelium] (non-interactive) keeping current L2 value")
                choice = "keep current"

            if "new" in str(choice).lower() or "inf" in str(choice).lower():
                db.set(l2_key, new_val)
                log_fn(f"[mycelium] update: ~ {keyword} = {new_val}")
                updated += 1
            elif "skip" in str(choice).lower():
                log_fn(f"[mycelium] update: skipped '{keyword}'")
            else:
                log_fn(f"[mycelium] update: kept current L2 value for '{keyword}'")

    # ── Step 4: delete stale L2 entries ──────────────────────────────────
    stale = existing_l2 - set(inf_index.keys())
    for keyword in sorted(stale):
        l2_key = f"{_PREFIX_MODULE}{keyword}"
        db.delete(l2_key)
        log_fn(f"[mycelium] update: - {keyword}  (no longer in any module alias_rules)")
        deleted += 1

    log_fn(
        f"[mycelium] update done — "
        f"wrote:{written}  skipped:{skipped}  updated:{updated}  "
        f"conflicts:{conflicts}  deleted:{deleted}"
    )
    log_fn("[mycelium] note: user (L1) overrides are never modified by update")
    return 0

# ---------------------------------------------------------------------------
# Shared execute helper
# ---------------------------------------------------------------------------

def _exe(command_line: str, log_fn=print):
    if not command_line.strip():
        log_fn("[mycelium] usage: mycelium exe <command> [args...]")
        return 1

    db = _open_db()
    try:
        table = _build_mycelium(db)
    finally:
        db.close()

    dispatch, err = _resolve(command_line, table)
    if dispatch is None:
        log_fn(f"[mycelium] {err}")
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
    """
    mycelium <sub-command> [args...]

    Sub-commands
    ------------
    list [<keyword>]            list routing table (all layers), or detail for one keyword
    set  <keyword> <variants>   write user override  → Layer 1
    del  <keyword>              delete user override from Layer 1
    rule <cmd>                  dry-run: show resolved dispatch + which layer answered
    exe  <cmd> [args...]        resolve and run via spider -vr
    update                      load module alias_rules into Layer 2 (never touches L1)
    reverse <module>            list all rules whose RHS dispatches to <module>
    help                        show this manual
    """
    try:
        import core.utils as _utils
        tokens = _utils.tokenize(args.strip()) if args.strip() else []
    except Exception:
        tokens = args.strip().split() if args.strip() else []

    if not tokens:
        log_fn("This module cannot be run without arguments. Please refer to the manual for usage instructions.")
        return 1

    sub = tokens[0]

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
            log_fn("[mycelium] usage: mycelium exe <command> [args...]")
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
            ("banana",     ("1.1",)),
        ),
    )


def R_ECO3inf():
    return {
        "name":        "mycelium",
        "desc":        "Module mycelium: 3-layer command dispatcher (user / module / default)",
        "help":        "mycelium list | set <kw> <variants> | del <kw> | rule <cmd> | exe <cmd> | update | reverse <mod>",
        "version_mod": "1.3",
        "L2Module":    True,
        "manual": """
mycelium — R-ECOSYSTEM command dispatcher  v1.3
===============================================

SYNOPSIS
    mycelium <command> [args...]
    mycelium list [<keyword>]
    mycelium set  <keyword> <variants>
    mycelium del  <keyword>
    mycelium rule <cmd> [args...]
    mycelium exe  <cmd> [args...]
    mycelium update
    mycelium reverse <module>
    mycelium help

THREE-LAYER ROUTING
    Resolution stops at the first layer that has a match for the keyword.

    Layer 1 — user (L1)      §sys:mycelium:rules:user:<keyword>
        Written by:  mycelium set
        Removed by:  mycelium del
        Never touched by update.
        Use this for personal aliases or to override any module alias.

    Layer 2 — module (L2)    §sys:mycelium:rules:module:<keyword>
        Written by:  mycelium update  (from R_ECO3inf()["alias_rules"])
        Only added or updated, never deleted by update.
        If a Layer 1 entry exists for a keyword, Layer 2 is ignored for it.

    Layer 3 — default (L3)   (no HiveFS entry)
        Implicit rule:  <stem> /* = <stem>
                        <stem> *  = <stem> *
        Applied when neither L1 nor L2 has an entry for the keyword.

VARIANT FORMAT (same for L1 and L2)
    "/* = rhs"                zero-arg variant (matched when no extra args)
    "* = rhs"                 any-arg variant  (matched always)
    "* = rhs /*"              any-arg variant, injects extra args at /* position
    Separate multiple variants with "|||":
        "/* = echo ||| * = echo /*"

COMMANDS
    mycelium set echo "/* = echo ||| * = echo /*"
        → writes to Layer 1 (user override)

    mycelium del echo
        → removes L1 entry; L2 or L3 then takes effect

    mycelium update
        → strict sync: Layer 2 mirrors exactly what modules declare today
        → adds keywords not yet in L2
        → updates keywords whose value changed (prompts via banana on conflict)
        → DELETES L2 keywords no longer declared by any module
        → never modifies Layer 1 (user overrides)

    mycelium list
        → shows all three layers grouped

    mycelium list echo
        → shows which layers have an entry for 'echo' and what they contain

    mycelium rule <cmd>
        → dry-run: shows resolved dispatch + which layer answered

    mycelium reverse <module>
        → lists every rule (all layers) whose RHS dispatches to <module>

EXAMPLES
    §sys:mycelium:rules:user:greet = "/* = hello ||| * = hello /*"
        greet           →  hello        [user (L1)]
        greet world     →  hello world  [user (L1)]

    §sys:mycelium:rules:module:help = "/* = helper"
        help            →  helper       [module (L2)]
        help foo        →  unknown      (no * variant — add it with `mycelium set`)

    stem 'echo' with no HiveFS entry:
        echo            →  echo         [default (L3)]
        echo hi there   →  echo hi there [default (L3)]
""",
    }