"""
vine.py — Module HTTP client pour R-ECO3
Version : 1.0 · L2Module : True
"""

import urllib.request
import urllib.error
import urllib.parse
import json
import os
import time


# ─── helpers ──────────────────────────────────────────────────────────────────

def _build_request(url, method, data, headers, is_json):
    """Construit un urllib.request.Request."""
    body = None

    if data is not None:
        if isinstance(data, str):
            body = data.encode("utf-8")
        else:
            body = data

    req = urllib.request.Request(url, data=body, method=method.upper())

    for h in headers:
        if ":" in h:
            k, v = h.split(":", 1)
            req.add_header(k.strip(), v.strip())

    if is_json:
        req.add_header("Content-Type", "application/json")

    return req


def _do_request(req, timeout):
    """Exécute la requête. Retourne (status, headers, body_bytes) ou lève."""
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        status  = resp.status
        headers = dict(resp.headers)
        body    = resp.read()
    return status, headers, body


def _fmt_size(n):
    if n < 1024:
        return f"{n} B"
    if n < 1024 ** 2:
        return f"{n/1024:.1f} KB"
    return f"{n/1024**2:.2f} MB"


# ─── commandes ────────────────────────────────────────────────────────────────

def _cmd_request(url, method, data, headers, is_json, out_file, timeout, silent, no_status, log_fn):
    """Commande principale : effectue la requête HTTP."""
    try:
        req    = _build_request(url, method, data, headers, is_json)
        t0     = time.time()
        status, resp_headers, body = _do_request(req, timeout)
        elapsed = time.time() - t0
    except urllib.error.HTTPError as e:
        status   = e.code
        resp_headers = dict(e.headers) if e.headers else {}
        body     = e.read()
        elapsed  = 0
    except urllib.error.URLError as e:
        log_fn(f"[vine] Erreur réseau : {e.reason}")
        return 1, str(e.reason)
    except TimeoutError:
        log_fn(f"[vine] Timeout après {timeout}s")
        return 1, "timeout"
    except Exception as e:
        log_fn(f"[vine] Erreur inattendue : {e}")
        return 1, str(e)

    # ── sauvegarde fichier ──
    if out_file:
        try:
            with open(out_file, "wb") as f:
                f.write(body)
            if not silent:
                log_fn(f"[vine] Réponse sauvegardée → {out_file} ({_fmt_size(len(body))})")
        except OSError as e:
            log_fn(f"[vine] Impossible d'écrire {out_file} : {e}")
            return 1, str(e)

    # ── mode silencieux ──
    if silent:
        return 0, status

    # ── affichage ──
    if not no_status:
        status_icon = "✓" if 200 <= status < 300 else "✗"
        log_fn(f"[vine] {status_icon} {method.upper()} {url}")
        log_fn(f"       Status  : {status}  |  Taille : {_fmt_size(len(body))}  |  Temps : {elapsed*1000:.0f} ms")

    ct = resp_headers.get("Content-Type", "")
    if not out_file:
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError:
            text = body.decode("latin-1", errors="replace")

        if "application/json" in ct:
            try:
                parsed = json.loads(text)
                log_fn(json.dumps(parsed, indent=2, ensure_ascii=False))
            except json.JSONDecodeError:
                log_fn(text)
        else:
            log_fn(text)

    return 0, status


def _cmd_status(log_fn):
    """Affiche le statut du module vine."""
    log_fn("[vine] Module vine v1.0 — client HTTP urllib (no deps)")
    log_fn("       Verbes supportés : GET, POST, PUT, PATCH, DELETE, HEAD, OPTIONS")
    log_fn("       Encodage réponse : UTF-8 (fallback latin-1)")
    log_fn("       Timeout défaut   : 10 s")
    return 0, None


# ─── interface R-ECO3 ─────────────────────────────────────────────────────────

def R_ECO3(args: str, log_fn=print):
    """
    vine <url> [options]
    vine status

    Options :
      --method=VERB     Verbe HTTP (défaut : GET)
      --data=<str>      Body de la requête
      --header=K:V      Ajouter un header (répétable)
      --json            Force Content-Type: application/json
      --out=<fichier>   Sauvegarde la réponse dans un fichier
      --timeout=N       Timeout en secondes (défaut : 10)
      --silent          Pas d'affichage, retourne seulement le code HTTP
    """
    # ── imports locaux (disponibles si core installé) ──
    try:
        import sys, os
        import core
        parse_command = core.utils.parse_command # type: ignore
    except Exception:
        # fallback parser minimaliste
        def parse_command(cmd):
            tokens   = cmd.split()
            pos      = []
            kv       = {}
            i        = 0
            while i < len(tokens):
                t = tokens[i]
                if t.startswith("--"):
                    t = t[2:]
                    if "=" in t:
                        k, v = t.split("=", 1)
                        if k in kv and isinstance(kv[k], list):
                            kv[k].append(v)
                        elif k in kv:
                            kv[k] = [kv[k], v]
                        else:
                            kv[k] = v
                    else:
                        kv[t] = True
                elif t.startswith("-") and len(t) > 1:
                    for c in t[1:]:
                        kv[c] = True
                else:
                    pos.append(t)
                i += 1
            return pos, kv

    positional, kv = parse_command(args.strip())

    # ── vine status ──
    if positional and positional[0].lower() == "status":
        return _cmd_status(log_fn)

    # ── aide ──
    if not positional or kv.get("h") or kv.get("help"):
        log_fn(R_ECO3.__doc__)
        return 0, None

    url = positional[0]

    # ── paramètres ──
    method  = str(kv.get("method", "GET")).upper()
    data    = kv.get("data", None)
    is_json = bool(kv.get("json", False))
    out     = kv.get("out", None)
    no_status = bool(kv.get("no-status", False))
    silent  = bool(kv.get("silent", False))
    try:
        timeout = float(kv.get("timeout", 10))
    except (ValueError, TypeError):
        log_fn("[vine] --timeout doit être un nombre")
        return 1, "bad timeout"

    # headers : --header peut apparaître plusieurs fois
    raw_h = kv.get("header", [])
    if isinstance(raw_h, str):
        raw_h = [raw_h]
    elif not isinstance(raw_h, list):
        raw_h = list(raw_h)

    # Si data fourni sans méthode explicite → POST
    if data is not None and "method" not in kv:
        method = "POST"

    return _cmd_request(url, method, data, raw_h, is_json, out, timeout, silent, no_status, log_fn)


def R_ECO3dep():
    return (
        ("3.5.1b",),
        (
            ("core.utils", ("1.1",)),
        )
    )


def R_ECO3inf():
    return {
        "name":        "vine",
        "desc":        "Client HTTP léger (urllib, sans dépendances externes)",
        "help":        "vine <url> [--method=] [--data=] [--header=K:V] [--json] [--out=] [--timeout=] [--silent]",
        "version_mod": "1.0",
        "L2Module":    True,
        "manual": """
vine — Client HTTP R-ECO3
==========================

SYNOPSIS
  vine <url> [options]
  vine status

DESCRIPTION
  vine est un client HTTP minimaliste basé sur urllib (stdlib Python).
  Il ne requiert aucune dépendance externe.

OPTIONS
  --method=VERB      Verbe HTTP : GET, POST, PUT, PATCH, DELETE, HEAD, OPTIONS
                     Défaut : GET (POST si --data est fourni)
  --data=<str>       Body de la requête (chaîne brute)
  --header=K:V       Ajouter un header HTTP. Répétable :
                       vine url --header=Authorization:Bearer\\ xyz --header=X-Foo:bar
  --json             Ajoute automatiquement Content-Type: application/json
  --out=<fichier>    Sauvegarde le body de la réponse dans un fichier
  --timeout=N        Timeout en secondes (défaut : 10)
  --silent           Supprime tout affichage ; la valeur de retour est
                     (0, <status_code>)
  --no-status       Masque les lignes ✓/✗ et Status (le body reste affiché)

EXEMPLES
  vine https://httpbin.org/get
  vine https://httpbin.org/post --data='{"x":1}' --json
  vine https://httpbin.org/put --method=PUT --data=hello
  vine https://example.com/file --out=page.html
  vine https://httpbin.org/get --silent
  vine status

RETOUR
  (0, status_code) en succès
  (1, message)     en erreur réseau ou de paramètre
""",
    }