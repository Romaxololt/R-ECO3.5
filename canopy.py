# canopy 3.5.2 : Beta
import core
import core.apix as apix
import core.trail as trail

def _apix(arg, log_fn, db=None):
    payload = {"args": arg, "logfn": log_fn}
    if db is not None:
        payload["db"] = db
    return core.apix.R_ECO3(payload)

def R_ECO3(inp):
    args = inp["args"]
    log_fn = inp["logfn"]
    
    if args.strip():
        _apix(f"run banana err --msg='canopy takes no arguments'", log_fn)
        return 1

    # ── Collect all L2 modules + their res["value"] ───────────────────────────────
    entries = []  # list of (keyword, desc, version, source_module)
    for fname in _apix("listl2", log_fn)["value"]:
        stem = fname
        try:
            res = _apix(f"inf {stem}", log_fn)
            if res["status"] != 0 or not isinstance(res["value"], dict):
                continue

            name    = res["value"].get("name", stem)
            desc    = res["value"].get("desc", "")
            version = res["value"].get("version_mod", "")
            raw_aliases = res["value"].get("alias_rules", "")

            # Extract keywords from alias_rules
            keywords = set()
            if raw_aliases:
                for part in raw_aliases.split("|||"):
                    part = part.strip()
                    if "=" not in part:
                        continue
                    lhs = part.split("=")[0].strip().split()
                    if lhs and lhs[0] not in ("*", "/*"):
                        keywords.add(lhs[0])

            # Fallback: use module name itself as keyword
            if not keywords:
                keywords.add(name)

            for kw in sorted(keywords):
                entries.append((kw, desc, version, name))

        except Exception:
            pass

    if not entries:
        _apix("run banana err --msg='No L2 modules found.'", log_fn)
        return 0

    # ── Build display ─────────────────────────────────────────────────────
    entries.sort(key=lambda e: e[0])
    max_kw  = max(len(e[0]) for e in entries)
    max_mod = max(len(e[3]) for e in entries)

    lines = []
    lines.append(f"[bold cyan]{'command':<{max_kw}}  {'module':<{max_mod}}  description[/]")
    lines.append(f"[dim]{'─'*(max_kw)}  {'─'*max_mod}  {'─'*36}[/]")

    for kw, desc, version, mod_name in entries:
        ver_str = f" [dim]v{version}[/]" if version else ""
        kw_col  = f"[bold white]{kw:<{max_kw}}[/]"
        mod_col = f"[dim]{mod_name:<{max_mod}}[/]"
        lines.append(f"{kw_col}  {mod_col}  {desc}{ver_str}")

    content = "\n".join(lines)
    _apix(f"run banana panel --msg=\"{content}\" --title=\"[bold blue]R-ECOSYSTEM commands[/]\" --border=blue --box=ROUNDED", log_fn)
    _apix("run banana print --msg=\"[dim]Use [bold]<command> help[/] for details  ·  [bold]mycelium rule <command>[/] to inspect routing[/]\"", log_fn)

    return 0


def R_ECO3dep():
    return {
        "reco": ["3.5.2b"],
        "module": [
            {"banana": ["2.1"]},
        ]
    }

def R_ECO3inf():
    return {
        "name": "canopy",
        "desc": "Lists all available commands (from alias_rules) with descriptions",
        "help": "canopy (no arguments)",
        "version_mod": "2.1",
        "alias_rules": "canopy /* = canopy ||| canopy * = banana err --msg='This module cannot be run with arguments. Please refer to the manual for usage instructions.'",
        "L2Module": True,
        "manual": (
            "canopy — R-ECOSYSTEM command browser  v1.0\n"
            "==========================================\n"
            "\n"
            "SYNOPSIS\n"
            "    canopy\n"
            "\n"
            "DESCRIPTION\n"
            "    Scans all L2 modules in MODULES_DIR, reads their alias_rules\n"
            "    to extract routable command keywords, and displays a formatted\n"
            "    table of commands with their description and version.\n"
            "\n"
            "    Takes no arguments.\n"
            "    Use '<command> help' for per-module details.\n"
            "    Use 'mycelium rule <command>' to inspect routing layers.\n"
        ),
    }