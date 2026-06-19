"""
squid.py — R-ECOSYSTEM module — command executor  v1.0

Flux :
  raven → apix("run squid exe <cmd>", logfn, db, token)
       → squid reçoit inp = {args, logfn, db, token}
       → apix("run mycelium resolve <cmd>", logfn, db, token)
             mycelium résout, retourne la dispatch string
       → apix("run spider <dispatch>", logfn, db, token)
             spider exécute le module cible

squid ne rouvre jamais la DB — il réutilise celle passée par raven.
squid n'a aucune logique d'alias : tout est délégué à mycelium.
"""

import core
import core.apix  as apix
import core.utils as utils


# ---------------------------------------------------------------------------
# apix bridge  (contrat dict v2)
# ---------------------------------------------------------------------------

def _apix(args_str: str, log_fn, db, token):
    """Construit le payload dict et appelle apix. db et token toujours transmis."""
    payload = {"args": args_str, "logfn": log_fn, "db": db, "token": token}
    return apix.R_ECO3(payload)


# ---------------------------------------------------------------------------
# banana bridge
# ---------------------------------------------------------------------------

def _q(s: str) -> str:
    return '"' + str(s).replace('"', '\\"') + '"'


def _b(log_fn, db, token):
    def bn(args):
        r = _apix(f"run banana {args}", log_fn, db, token)
        return r.get("value") if isinstance(r, dict) else r

    def _ok(msg):    bn(f"ok --msg={_q(msg)}")
    def _err(msg):   bn(f"err --msg={_q(msg)}")
    def _print(msg): bn(f"print --msg={_q(msg)}")

    def _panel(content, title="", border="blue", box="ROUNDED"):
        a = f"panel --msg={_q(content)} --border={border} --box={box}"
        if title: a += f" --title={_q(title)}"
        bn(a)

    return {"ok": _ok, "err": _err, "print": _print, "panel": _panel}


# ---------------------------------------------------------------------------
# Étape 1 : résolution via mycelium
# ---------------------------------------------------------------------------

def _resolve(command_line: str, log_fn, db, token) -> str | None:
    """
    Appelle mycelium resolve <command_line>.
    Retourne la dispatch string ou None si échec.
    """
    result = _apix(f"run mycelium resolve {command_line}", log_fn, db, token)
    if not isinstance(result, dict) or result.get("status") != 0:
        return None
    dispatch = result.get("value")
    if not dispatch or not isinstance(dispatch, str):
        return None
    return dispatch.strip()


# ---------------------------------------------------------------------------
# Étape 2 : exécution via spider
# ---------------------------------------------------------------------------

def _exe(dispatch: str, log_fn, db, token) -> dict:
    """
    Lance spider avec la dispatch string renvoyée par mycelium.
    dispatch format : "<module> [args...]"  ex. "vine status"
    """
    d_parts = dispatch.split()
    if not d_parts:
        return {"status": 1, "value": "empty dispatch"}

    mod_name    = d_parts[0]
    mod_args    = " ".join(d_parts[1:]) if len(d_parts) > 1 else ""
    spider_args = f"{mod_name} -vr"
    if mod_args:
        spider_args += f" --args={_q(mod_args)}"

    result = _apix(f"run spider {spider_args}", log_fn, db, token)
    return result if isinstance(result, dict) else {"status": 0, "value": result}


# ---------------------------------------------------------------------------
# R_ECO3 — point d'entrée  (contrat dict apix v2)
# ---------------------------------------------------------------------------

def R_ECO3(inp):
    """
    inp = {args, logfn, db, token}

    Sous-commandes :
      exe <cmd>   résout via mycelium puis exécute via spider
      resolve <cmd>   résout uniquement, retourne la dispatch string
      help
    """
    args   = inp.get("args",  "")    if isinstance(inp, dict) else str(inp)
    log_fn = inp.get("logfn", print) if isinstance(inp, dict) else print
    db     = inp.get("db")           if isinstance(inp, dict) else None
    token  = inp.get("token")        if isinstance(inp, dict) else None

    b = _b(log_fn, db, token)

    try:
        tokens, kv  = utils.parse_command(args.strip()) if args.strip() else []
    except Exception:
        tokens = args.strip().split() if args.strip() else []

    if not tokens:
        b["err"]("This module requires arguments — use 'squid help'.")
        return 1

    sub = tokens[0]

    # ── exe ──────────────────────────────────────────────────────────
    if sub == "exe":
        parts    = args.strip().split(None, 1)
        cmd_line = parts[1] if len(parts) > 1 else ""
        if not cmd_line:
            b["err"]("usage: squid exe <command> [args...]")
            return 1

        dispatch = _resolve(cmd_line, log_fn, db, token)
        if dispatch is None:
            return {"status": -1}                          # mycelium a déjà affiché l'erreur

        result = _exe(dispatch, log_fn, db, token)
        return result.get("status", 1)

    # ── resolve (dry-run) ─────────────────────────────────────────────────
    if sub == "resolve":
        parts    = args.strip().split(None, 1)
        cmd_line = parts[1] if len(parts) > 1 else ""
        if not cmd_line:
            b["err"]("usage: squid resolve <command> [args...]")
            return 1

        dispatch = _resolve(cmd_line, log_fn, db, token)
        if dispatch is None:
            return 1

        b["panel"](
            f"[bold]{cmd_line}[/]  →  [bold green]{dispatch}[/]",
            title=" squid resolve ", border="blue", box="SIMPLE")
        return dispatch      # apix._wrap() → {"status":0, "value":dispatch}

    # ── help ──────────────────────────────────────────────────────────────
    if sub == "help":
        log_fn(R_ECO3inf()["manual"])
        return 0

    return 1


# ---------------------------------------------------------------------------
# R_ECO3dep / R_ECO3inf
# ---------------------------------------------------------------------------

def R_ECO3dep():
    return {
        "reco": ["3.5.2b"],
        "module": [
            {"banana":   ["2.1"]},
            {"mycelium": ["2.0"]},
            {"spider":   ["2.1"]},
        ],
    }


def R_ECO3inf():
    return {
        "name":        "squid",
        "desc":        "Exécuteur de commandes — résout via mycelium, exécute via spider",
        "help":        "squid exe <cmd> | squid resolve <cmd> | squid help",
        "version_mod": "1.0",
        "L2Module":    True,
        "manual": """
squid — R-ECOSYSTEM command executor  v1.0
==========================================

SYNOPSIS
    squid exe <command> [args...]
    squid resolve <command> [args...]
    squid help

FLUX
    raven  →  apix("run squid exe <cmd>", logfn, db, token)
    squid  →  apix("run mycelium resolve <cmd>", logfn, db, token)
                   mycelium retourne la dispatch string
    squid  →  apix("run spider <module> -vr [--args=...]", logfn, db, token)

    db et token proviennent de raven et sont retransmis à chaque appel.
    squid ne rouvre jamais la DB.
    squid n'a aucune logique d'alias — tout vient de mycelium.

SOUS-COMMANDES
    exe <cmd>   résout + exécute, retourne 0 ou 1
    resolve <cmd>   résout uniquement, retourne la dispatch string
    help            affiche ce manuel

EXEMPLES
    squid exe vine status
    squid resolve vine status
""",
    }