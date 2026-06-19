# vine.py — Client HTTP léger pour R-ECO3
# Version 1.1 · Module L2 · Basé sur urllib (stdlib)

import urllib.request
import urllib.error
import urllib.parse
import json as _json_mod


# ─────────────────────────────────────────────
#  Métadonnées
# ─────────────────────────────────────────────

def R_ECO3inf() -> dict:
    return {
        "name":        "vine",
        "desc":        "Client HTTP léger (GET/POST/PUT/PATCH/DELETE/HEAD/OPTIONS)",
        "help":        (
            "vine <url> [options]\n"
            "vine status\n\n"
            "Options :\n"
            "  --method=VERB          GET (défaut), POST, PUT, PATCH, DELETE, HEAD, OPTIONS\n"
            "  --data=<str>           Corps de la requête\n"
            "  --header=K:V           Header HTTP (répétable)\n"
            "  --json                 Ajoute Content-Type: application/json\n"
            "  --out=<fichier>        Sauvegarde le body dans un fichier\n"
            "  --timeout=N            Timeout en secondes (défaut : 10)\n"
            "  --silent               Aucun affichage ; retourne {status:0, value:<code>}\n"
            "  --no-status            Masque les lignes de statut, affiche le body\n"
            "  --debug                Affiche le parsing interne"
        ),
        "version_mod": "2.1",
        "L2Module":    True,
        "manual": (
            "# vine — Client HTTP\n\n"
            "vine est un client HTTP léger sans dépendance externe, basé sur urllib.\n\n"
            "## Synopsis\n\n"
            "    vine <url> [options]\n"
            "    vine status\n\n"
            "## Options\n\n"
            "  --method=VERB    Verbe HTTP : GET, POST, PUT, PATCH, DELETE, HEAD, OPTIONS\n"
            "  --data=<str>     Corps de la requête (body)\n"
            "  --header=K:V     Header HTTP (peut être répété plusieurs fois)\n"
            "  --json           Ajoute automatiquement Content-Type: application/json\n"
            "  --out=<fichier>  Sauvegarde la réponse dans un fichier\n"
            "  --timeout=N      Timeout réseau en secondes (défaut : 10)\n"
            "  --silent         Mode silencieux — retourne {status:0, value:<code_http>}\n"
            "  --no-status      Masque le statut HTTP, affiche uniquement le body\n"
            "  --debug          Affiche le parsing des arguments en interne\n\n"
            "## Notes\n\n"
            "Les erreurs HTTP 4xx/5xx n'entraînent PAS un statut de retour 1 — "
            "le body d'erreur est affiché normalement.\n"
            "Seules les erreurs réseau (timeout, DNS, etc.) retournent status=1.\n\n"
            "## Exemples\n\n"
            "    vine https://httpbin.org/get\n"
            "    vine https://httpbin.org/post --data='{\"x\":1}' --json\n"
            "    vine https://example.com/file --out=page.html\n"
            "    vine https://httpbin.org/get --silent\n"
            "    vine https://httpbin.org/delete --method=DELETE\n"
            "    vine https://api.example.com --header=Authorization:Bearer token --header=X-Custom:val\n"
        ),
        "alias_rules": (
            "/* = vine\n"
            "* = vine /*"
        ),
    }


# ─────────────────────────────────────────────
#  Dépendances
# ─────────────────────────────────────────────

def R_ECO3dep() -> dict:
    return {
        "reco": ["3.5.2b"],
        "module": []
    }


# ─────────────────────────────────────────────
#  Helpers internes
# ─────────────────────────────────────────────

def _parse_args(raw: str) -> tuple:
    """
    Parse la chaîne brute d'arguments.
    Retourne (positionnels: list[str], kv: dict).

    Syntaxe gérée :
      --key=value   → kv["key"] = "value"  (liste si répété)
      --flag        → kv["flag"] = True
      -v            → kv["v"] = True
    Les clés répétées sont agrégées en list.
    """
    tokens = _tokenize(raw)
    pos = []
    kv  = {}

    for tok in tokens:
        if tok.startswith("--"):
            inner = tok[2:]
            if "=" in inner:
                k, v = inner.split("=", 1)
                if k in kv:
                    if isinstance(kv[k], list):
                        kv[k].append(v)
                    else:
                        kv[k] = [kv[k], v]
                else:
                    kv[k] = v
            else:
                kv[inner] = True
        elif tok.startswith("-") and len(tok) > 1 and not tok[1:].lstrip("-"):
            # tiret seul, ignorer
            pos.append(tok)
        elif tok.startswith("-") and len(tok) > 1:
            for ch in tok[1:]:
                kv[ch] = True
        else:
            pos.append(tok)

    return pos, kv


def _tokenize(s: str) -> list:
    """Découpe en tokens en respectant les guillemets simples et doubles."""
    tokens = []
    current = []
    in_quote = None

    for ch in s:
        if ch in ('"', "'") and in_quote is None:
            in_quote = ch
        elif ch == in_quote:
            in_quote = None
        elif ch == " " and in_quote is None:
            if current:
                tokens.append("".join(current))
                current = []
        else:
            current.append(ch)

    if current:
        tokens.append("".join(current))

    return tokens


def _collect_headers(kv: dict) -> dict:
    """
    Extrait les headers depuis kv["header"].
    Accepte une valeur unique ou une liste (--header répété).
    Retourne un dict {nom: valeur}.
    """
    headers = {}
    raw = kv.get("header")
    if raw is None:
        return headers

    entries = raw if isinstance(raw, list) else [raw]
    for entry in entries:
        if ":" in entry:
            k, v = entry.split(":", 1)
            headers[k.strip()] = v.strip()

    return headers


def _do_request(url: str, method: str, data: bytes | None,
                headers: dict, timeout: int) -> tuple:
    """
    Effectue la requête HTTP.
    Retourne (status_code: int, response_headers: dict, body: bytes)
    ou lève une exception réseau.
    """
    req = urllib.request.Request(url, data=data, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as e:
        # Erreurs 4xx/5xx : on lit quand même le body
        try:
            body = e.read()
        except Exception:
            body = b""
        return e.code, dict(e.headers), body


# ─────────────────────────────────────────────
#  Point d'entrée L2
# ─────────────────────────────────────────────

def R_ECO3(inp: dict) -> dict:
    """
    Point d'entrée principal vine.

    inp keys :
      args   : str   — arguments bruts
      logfn  : callable — fonction d'affichage
      db     : HiveFS (optionnel)
      token  : any   (optionnel)
    """
    args_raw = inp.get("args", "").strip()
    log      = inp.get("logfn", print)

    # ── sous-commande "status" ─────────────────
    if args_raw.strip().lower() == "status":
        log("[vine] v1.1 — client HTTP stdlib urllib — aucune dépendance externe")
        log("Méthodes supportées : GET POST PUT PATCH DELETE HEAD OPTIONS")
        return {"status": 0, "value": "ok"}

    # ── parsing ───────────────────────────────
    pos, kv = _parse_args(args_raw)

    silent    = "silent"    in kv
    no_status = "no-status" in kv or "no_status" in kv
    debug     = "debug"     in kv
    use_json  = "json"      in kv

    method    = str(kv.get("method", "GET")).upper()
    data_str  = kv.get("data",    None)
    out_file  = kv.get("out",     None)
    timeout   = int(kv.get("timeout", 10))

    if not pos:
        log("[vine] Erreur : URL manquante.")
        log("Usage : vine <url> [--method=GET] [--data=...] [--json] [--silent] ...")
        return {"status": 1, "value": "missing url"}

    url = pos[0]

    if debug:
        log(f"[vine:debug] url={url!r}  method={method}  timeout={timeout}")
        log(f"[vine:debug] data={data_str!r}  out={out_file!r}")
        log(f"[vine:debug] kv={kv}")

    # ── préparation headers ───────────────────
    headers = _collect_headers(kv)

    if use_json and "Content-Type" not in headers:
        headers["Content-Type"] = "application/json"

    # ── préparation body ──────────────────────
    body_bytes: bytes | None = None
    if data_str is not None:
        body_bytes = data_str.encode("utf-8")
        if method == "GET":
            method = "POST"   # bascule implicite si body fourni sans --method

    # ── requête ───────────────────────────────
    try:
        status_code, resp_headers, resp_body = _do_request(
            url, method, body_bytes, headers, timeout
        )
    except urllib.error.URLError as exc:
        reason = str(exc.reason) if hasattr(exc, "reason") else str(exc)
        if not silent:
            log(f"[vine] Erreur réseau : {reason}")
        return {"status": 1, "value": reason}
    except Exception as exc:
        if not silent:
            log(f"[vine] Erreur inattendue : {exc}")
        return {"status": 1, "value": str(exc)}

    # ── mode silent : retour immédiat ─────────
    if silent:
        return {"status": 0, "value": status_code}

    # ── affichage statut ──────────────────────
    if not no_status:
        content_type = resp_headers.get("Content-Type", resp_headers.get("content-type", ""))
        log(f"[vine] {method} {url}")
        log(f"[vine] HTTP {status_code}  |  Content-Type: {content_type}")

    # ── affichage / écriture body ─────────────
    body_text: str | None = None
    try:
        body_text = resp_body.decode("utf-8")
    except UnicodeDecodeError:
        body_text = None   # binaire

    if out_file:
        try:
            with open(out_file, "wb") as fh:
                fh.write(resp_body)
            if not no_status:
                log(f"[vine] Body sauvegardé → {out_file} ({len(resp_body)} octets)")
        except OSError as exc:
            log(f"[vine] Impossible d'écrire {out_file!r} : {exc}")
            return {"status": 1, "value": str(exc)}
    else:
        if body_text is not None:
            # Tentative d'affichage JSON joliment formaté
            try:
                parsed = _json_mod.loads(body_text)
                log(_json_mod.dumps(parsed, indent=2, ensure_ascii=False))
            except (_json_mod.JSONDecodeError, ValueError):
                log(body_text)
        else:
            log(f"[vine] Réponse binaire ({len(resp_body)} octets) — utilisez --out=<fichier> pour sauvegarder.")

    return {"status": 0, "value": status_code}