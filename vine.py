"""
vine.py — Module HTTP client pour R-ECO3
Version : 1.1 · L2Module : True
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

    # ─── Dans _build_request ──────────────────────────────────────────────────────
    for h in headers:
        if "=" in h:
            k, v = h.split("=", 1)
            req.add_header(k.strip(), v.strip())
        elif ":" in h:
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


# ─── tokenizer interne (respecte les guillemets) ──────────────────────────────

def _tokenize(s):
    """
    Découpe s en tokens en respectant les guillemets simples et doubles.
    Contrairement à str.split(), les espaces à l'intérieur de guillemets
    ne séparent pas les tokens.
    """
    tokens = []
    current = []
    in_quote = None
    i = 0
    while i < len(s):
        c = s[i]
        if in_quote:
            if c == in_quote:
                in_quote = None
            else:
                current.append(c)
        elif c in ('"', "'"):
            in_quote = c
        elif c == ' ':
            if current:
                tokens.append(''.join(current))
                current = []
        else:
            current.append(c)
        i += 1
    if current:
        tokens.append(''.join(current))
    return tokens


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
    log_fn("[vine] Module vine v1.1 — client HTTP urllib (no deps)")
    log_fn("       Verbes supportés : GET, POST, PUT, PATCH, DELETE, HEAD, OPTIONS")
    log_fn("       Encodage réponse : UTF-8 (fallback latin-1)")
    log_fn("       Timeout défaut   : 10 s")
    return 0, None

def _parse_command(cmd):
    """
    Parser maison — gère :
      - guillemets simples et doubles (espaces intérieurs préservés)
      - --key=value  (value peut contenir des espaces si entre guillemets)
      - --key value  (token suivant comme valeur, sauf bool flags)
      - --flag       (booléen)
      - -abc         (flags courts)
      - positionnels
      - clés répétées → liste
    """
    BOOL_FLAGS = {"json", "silent", "no-status", "debug", "h", "help"}

    # ── tokenizer : respecte les guillemets simples et doubles ───────────────
    tokens = []
    i = 0
    while i < len(cmd):
        # sauter les espaces inter-tokens
        while i < len(cmd) and cmd[i] == ' ':
            i += 1
        if i >= len(cmd):
            break

        tok = []
        in_q = None
        while i < len(cmd):
            c = cmd[i]
            if in_q:
                if c == in_q:
                    in_q = None       # fermeture du guillemet
                else:
                    tok.append(c)     # caractère à l'intérieur des guillemets
            elif c in ('"', "'"):
                in_q = c              # ouverture du guillemet
            elif c == ' ':
                break                 # fin du token (hors guillemets)
            else:
                tok.append(c)
            i += 1

        if tok:
            tokens.append(''.join(tok))

    # ── parser les tokens ────────────────────────────────────────────────────
    pos = []
    kv  = {}

    def _store(k, v):
        if k in kv:
            if isinstance(kv[k], list):
                kv[k].append(v)
            else:
                kv[k] = [kv[k], v]
        else:
            kv[k] = v

    i = 0
    while i < len(tokens):
        t = tokens[i]

        if t.startswith("--"):
            key = t[2:]
            if "=" in key:
                k, v = key.split("=", 1)
                _store(k, v)
            elif key in BOOL_FLAGS:
                _store(key, True)
            elif i + 1 < len(tokens) and not tokens[i + 1].startswith("-"):
                i += 1
                _store(key, tokens[i])
            else:
                _store(key, True)

        elif t.startswith("-") and len(t) > 1:
            for c in t[1:]:
                _store(c, True)

        else:
            pos.append(t)

        i += 1

    return pos, kv

# ─── interface R-ECO3 ─────────────────────────────────────────────────────────

def R_ECO3(inp):
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
      --debug           Affiche le parsing interne (url, method, headers, data)
    """
    import core
    
    args = inp["args"]
    log_fn = inp["logfn"]
    
    positional, kv = core.utils.parse_command(args.strip())

    debug = bool(kv.get("debug", False))

    if debug:
        log_fn(f"[vine:debug] args bruts    : {repr(args)}")
        log_fn(f"[vine:debug] positional    : {positional}")
        log_fn(f"[vine:debug] kv            : {kv}")

    # ── vine status ──
    if positional and positional[0].lower() == "status":
        return _cmd_status(log_fn)

    # ── aide ──
    if kv.get("h") or kv.get("help"):
        log_fn(R_ECO3.__doc__)
        return 0, None

    url = positional[0]

    # ── paramètres ──
    method    = str(kv.get("method", "GET")).upper()
    data      = kv.get("data", None)
    is_json   = bool(kv.get("json", False))
    out       = kv.get("out", None)
    no_status = bool(kv.get("no-status", False))
    silent    = bool(kv.get("silent", False))
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
        raw_h = list(raw_h) #type: ignore

    if debug:
        log_fn(f"[vine:debug] url           : {url}")
        log_fn(f"[vine:debug] method        : {method}")
        log_fn(f"[vine:debug] headers bruts : {raw_h}")
        log_fn(f"[vine:debug] data          : {repr(data)}")
        log_fn(f"[vine:debug] json          : {is_json}")
        # Simuler le build du header pour voir ce qui sera envoyé
        # ─── Dans R_ECO3, bloc debug ─────────────────────────────────────────────────
        for h in raw_h:
            if "=" in h:
                k, v = h.split("=", 1)
                log_fn(f"[vine:debug] header envoyé : {repr(k.strip())} → {repr(v.strip())}")
            elif ":" in h:
                k, v = h.split(":", 1)
                log_fn(f"[vine:debug] header envoyé : {repr(k.strip())} → {repr(v.strip())}")
            else:
                log_fn(f"[vine:debug] header IGNORÉ (pas de séparateur) : {repr(h)}")

    # Si data fourni sans méthode explicite → POST
    if data is not None and "method" not in kv:
        method = "POST"

    return _cmd_request(url, method, data, raw_h, is_json, out, timeout, silent, no_status, log_fn)

def R_ECO3dep():
    return {
        "reco": ["3.5.2b"],
        "module": []
    }

def R_ECO3inf():
    return {
        "name":        "vine",
        "desc":        "Client HTTP léger (urllib, sans dépendances externes)",
        "help":        "vine <url> [--method=] [--data=] [--header=K:V] [--json] [--out=] [--timeout=] [--silent] [--debug]",
        "version_mod": "2.1",
        "L2Module":    True,
        "alias_rules": "vine /* = banana err --msg='This module cannot be run without arguments. Please refer to the manual for usage instructions.'",
        "manual": (
            "vine — Client HTTP R-ECO3  v1.1\n"
            "==============================\n"
            "\n"
            "SYNOPSIS\n"
            "    vine <url> [options]\n"
            "    vine status\n"
            "\n"
            "DESCRIPTION\n"
            "    vine is a lightweight HTTP client based on urllib from the Python standard library.\n"
            "    It can send requests, print responses, save output to a file, and run silently when needed.\n"
            "\n"
            "OPTIONS\n"
            "    --method=VERB\n"
            "        HTTP method to use. Default is GET.\n"
            "        If --data is provided and no method is set, the method becomes POST.\n"
            "\n"
            "    --data=<str>\n"
            "        Request body.\n"
            "\n"
            "    --header=K:V\n"
            "        Adds a custom header. Repeatable.\n"
            "\n"
            "    --json\n"
            "        Adds Content-Type: application/json.\n"
            "\n"
            "    --out=<fichier>\n"
            "        Saves the response body to a file.\n"
            "\n"
            "    --timeout=N\n"
            "        Timeout in seconds. Default is 10.\n"
            "\n"
            "    --silent\n"
            "        Suppresses output and returns only the HTTP status code.\n"
            "\n"
            "    --no-status\n"
            "        Hides the status lines while keeping the body output.\n"
            "\n"
            "    --debug\n"
            "        Prints internal parsing information.\n"
            "\n"
            "EXAMPLES\n"
            "    vine https://httpbin.org/get\n"
            "    vine https://httpbin.org/post --data='{\"x\":1}' --json\n"
            "    vine https://example.com/file --out=page.html\n"
            "    vine https://httpbin.org/get --silent\n"
            "    vine https://api.github.com/user --header=Authorization:token ghp_xxx --debug\n"
            "    vine status\n"
        ),
    }