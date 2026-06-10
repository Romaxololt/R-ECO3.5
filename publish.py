# publish.py — Module R-ECO3
# Outil de publication de modules vers le dépôt GitHub R-ECO3.5
# Utilise l'API GitHub REST directement via urllib (pas de dépendance à vine/apix).

_VERSION      = "2.0"
_REPO_OWNER   = "Romaxololt"
_REPO_NAME    = "R-ECO3.5"
_BRANCH       = "main"
_API_BASE     = "https://api.github.com"
_DB_KEY_TOKEN = "§sys:publish:github_token"


# ─────────────────────────────────────────────
# Couche HTTP interne  (urllib uniquement)
# ─────────────────────────────────────────────

def _http(method: str, path: str, token: str, payload=None) -> tuple:
    """
    Envoie une requête à l'API GitHub.
    Retourne (status_code: int, data: dict | list | str).
    N'utilise aucune dépendance externe : urllib suffit.
    """
    import json
    import urllib.error
    import urllib.request

    url     = f"{_API_BASE}{path}"
    headers = {
        "Authorization":        f"token {token}",
        "Accept":               "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent":           f"R-ECO3-publish/{_VERSION}",
    }

    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=body, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw  = resp.read().decode("utf-8")
            code = resp.status
    except urllib.error.HTTPError as exc:
        raw  = exc.read().decode("utf-8", errors="replace")
        code = exc.code
    except urllib.error.URLError as exc:
        return -1, str(exc.reason)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = raw

    return code, data


# ─────────────────────────────────────────────
# Helpers de bas niveau
# ─────────────────────────────────────────────

def _get_db():
    import core.trail as trail
    import core.hive  as hive
    return hive.HiveFS(str(trail.DB_FILE))


def _load_token(db) -> str:
    tok = db.get(_DB_KEY_TOKEN, as_str=True)
    return tok.strip() if tok else ""


def _real_path(filename: str):
    """Chemin local réel d'un fichier (module ou core)."""
    import core.trail as trail
    if filename.startswith("core."):
        return trail.ROOT / "core" / filename[5:]
    return trail.MODULES_DIR / filename


def _remote_path(filename: str) -> str:
    """Chemin dans le dépôt GitHub correspondant à un nom de fichier local."""
    if filename.startswith("core."):
        return "core/" + filename[5:]
    if filename.startswith("modules/"):
        return filename[len("modules/"):]
    return filename


def _require_token(token: str, log_fn) -> bool:
    """Vérifie la présence du token et logue un message d'aide si absent."""
    if token:
        return True
    log_fn("[publish] ✗ Aucun token GitHub configuré.")
    log_fn("[publish]   Utilisez : publish token set <votre_token>")
    return False


# ─────────────────────────────────────────────
# Opérations GitHub
# ─────────────────────────────────────────────

def _get_file_sha(remote_path: str, token: str) -> str:
    """Récupère le SHA du blob d'un fichier distant (vide si absent)."""
    code, data = _http(
        "GET",
        f"/repos/{_REPO_OWNER}/{_REPO_NAME}/contents/{remote_path}?ref={_BRANCH}",
        token,
    )
    if code == 200 and isinstance(data, dict):
        return data.get("sha", "")
    return ""


def _push_file(filename: str, token: str, message: str, log_fn) -> tuple:
    """
    Pousse un fichier local vers GitHub (création ou mise à jour).
    Retourne (0, None) en succès, (1, reason) en échec.
    """
    import base64

    local = _real_path(filename)
    if not local.exists():
        return 1, f"fichier local introuvable : '{local}'"

    try:
        content_bytes = local.read_bytes()
    except OSError as exc:
        return 1, f"erreur lecture '{local}' : {exc}"

    rpath   = _remote_path(filename)
    payload = {
        "message": message,
        "content": base64.b64encode(content_bytes).decode("ascii"),
        "branch":  _BRANCH,
    }

    sha = _get_file_sha(rpath, token)
    if sha:
        payload["sha"] = sha  # mise à jour d'un fichier existant

    code, data = _http(
        "PUT",
        f"/repos/{_REPO_OWNER}/{_REPO_NAME}/contents/{rpath}",
        token,
        payload=payload,
    )

    # 200 = mise à jour, 201 = création
    if code in (200, 201):
        return 0, None

    if isinstance(data, dict) and "message" in data:
        return 1, data["message"]

    return 1, f"HTTP {code} — réponse inattendue : {str(data)[:200]}"


def _local_sha1(content: bytes) -> str:
    """Calcule le SHA-1 Git d'un blob (même algorithme que GitHub)."""
    import hashlib
    header = f"blob {len(content)}\0".encode()
    return hashlib.sha1(header + content).hexdigest()


def _collect_local_files() -> list:
    """Retourne la liste de tous les fichiers modules/ et core/ publiables."""
    import core.trail as trail

    _IGNORE = {"__init__.py", "__pycache__"}
    files   = []

    if trail.MODULES_DIR.exists():
        for p in sorted(trail.MODULES_DIR.iterdir()):
            if p.is_file() and p.name not in _IGNORE and not p.name.endswith(".pyc"):
                files.append(p.name)

    core_dir = trail.ROOT / "core"
    if core_dir.exists():
        for p in sorted(core_dir.iterdir()):
            if p.is_file() and p.name not in _IGNORE and not p.name.endswith(".pyc"):
                files.append("core." + p.name)

    return files


# ─────────────────────────────────────────────
# Commandes
# ─────────────────────────────────────────────

def _cmd_push(files: list, message: str, token: str, log_fn) -> tuple:
    if not _require_token(token, log_fn):
        return 1, "token manquant"

    ok_list, err_list = [], []

    for fname in files:
        log_fn(f"[publish] → '{fname}'  ({_remote_path(fname)}) ...")
        code, detail = _push_file(fname, token, message, log_fn)
        if code == 0:
            log_fn(f"[publish] ✓ '{fname}' publié.")
            ok_list.append(fname)
        else:
            log_fn(f"[publish] ✗ '{fname}' : {detail}")
            err_list.append(fname)

    log_fn(
        f"[publish] Terminé — {len(ok_list)} publié(s), {len(err_list)} erreur(s)."
    )
    return (1, err_list) if err_list else (0, ok_list)


def _cmd_push_all(message: str, token: str, log_fn) -> tuple:
    files = _collect_local_files()
    if not files:
        log_fn("[publish] Aucun fichier trouvé sur le disque.")
        return 0, []
    log_fn(f"[publish] {len(files)} fichier(s) à publier.")
    return _cmd_push(files, message, token, log_fn)


def _cmd_list(token: str, log_fn) -> tuple:
    if not _require_token(token, log_fn):
        return 1, "token manquant"

    results = []
    for folder in ("modules", "core"):
        code, data = _http(
            "GET",
            f"/repos/{_REPO_OWNER}/{_REPO_NAME}/contents/{folder}?ref={_BRANCH}",
            token,
        )
        if code != 200 or not isinstance(data, list):
            err = data.get("message", data) if isinstance(data, dict) else data
            log_fn(f"[publish] ✗ Impossible de lister '{folder}' : {err}")
            continue

        for item in data:
            name   = item.get("name", "?")
            size   = item.get("size", 0)
            sha    = item.get("sha", "")[:8]
            prefix = "core." if folder == "core" else ""
            log_fn(f"  {prefix}{name:<32}  {size:>7} o   sha:{sha}")
            results.append(prefix + name)

    if not results:
        log_fn("[publish] Dépôt vide ou inaccessible.")
    return 0, results


def _cmd_diff(filename: str, token: str, log_fn) -> tuple:
    if not _require_token(token, log_fn):
        return 1, "token manquant"

    local = _real_path(filename)
    if not local.exists():
        log_fn(f"[publish] ✗ Fichier local introuvable : '{local}'")
        return 1, "fichier local absent"

    content    = local.read_bytes()
    local_sha  = _local_sha1(content)
    remote_sha = _get_file_sha(_remote_path(filename), token)

    if not remote_sha:
        log_fn(f"[publish] '{filename}' → absent sur le dépôt  [nouveau]")
        return 0, "nouveau"

    if local_sha == remote_sha:
        log_fn(f"[publish] '{filename}' → identique au dépôt ✓")
        return 0, "identique"

    log_fn(f"[publish] '{filename}' → différent du dépôt  [modifié]")
    log_fn(f"           local  sha1 : {local_sha[:16]}…")
    log_fn(f"           remote sha1 : {remote_sha[:16]}…")
    return 0, "modifié"


def _cmd_status(token: str, log_fn) -> tuple:
    if not _require_token(token, log_fn):
        return 1, "token manquant"

    files = _collect_local_files()
    if not files:
        log_fn("[publish] Aucun fichier local trouvé.")
        return 0, {}

    log_fn(f"[publish] Vérification de {len(files)} fichier(s)…\n")
    ICONS   = {"identique": "=", "modifié": "M", "nouveau": "+"}
    summary = {"identique": [], "modifié": [], "nouveau": []}

    for fname in files:
        _, state = _cmd_diff(fname, token, log_fn=lambda *_: None)
        if state in summary:
            summary[state].append(fname)
            log_fn(f"  [{ICONS.get(state, '?')}] {fname}")

    log_fn(
        f"\n[publish] {len(summary['nouveau'])} nouveau(x), "
        f"{len(summary['modifié'])} modifié(s), "
        f"{len(summary['identique'])} identique(s)."
    )
    return 0, summary


def _cmd_token_set(token_value: str, log_fn) -> tuple:
    db = _get_db()
    db.set(_DB_KEY_TOKEN, token_value.strip())
    db.close()
    log_fn("[publish] ✓ Token GitHub enregistré.")
    return 0, None


def _cmd_token_show(log_fn) -> tuple:
    db  = _get_db()
    tok = _load_token(db)
    db.close()

    if not tok:
        log_fn("[publish] Aucun token enregistré.")
        return 1, "pas de token"

    masked = (tok[:6] + "****" + tok[-4:]) if len(tok) > 10 else "****"
    log_fn(f"[publish] Token actif : {masked}  (longueur : {len(tok)})")
    return 0, None


def _cmd_token_del(log_fn) -> tuple:
    db = _get_db()
    try:
        db.delete(_DB_KEY_TOKEN)
        log_fn("[publish] ✓ Token supprimé.")
    except Exception:
        log_fn("[publish] Aucun token à supprimer.")
    db.close()
    return 0, None


# ─────────────────────────────────────────────
# Interface R-ECO3
# ─────────────────────────────────────────────

def R_ECO3(args: str, log_fn=print) -> tuple:
    """
    Point d'entrée principal du module publish.

    Commandes :
        publish push <fichier> [<fichier2> ...] [--msg="message"]
        publish push *                           [--msg="message"]
        publish list
        publish diff <fichier>
        publish status
        publish token set <token>
        publish token show
        publish token del
        publish help
    """
    import core.utils as utils

    positional, flags = utils.parse_command(args)

    if not positional:
        log_fn(_HELP_TEXT)
        return 0, None

    cmd = positional[0].lower()

    # ── push ─────────────────────────────────
    if cmd == "push":
        if len(positional) < 2:
            log_fn("[publish] Usage : publish push <fichier> | publish push *")
            return 1, "argument manquant"

        message = flags.get("msg",
                  flags.get("message",
                  flags.get("m", "publish: mise à jour via publish.py")))

        db    = _get_db()
        token = _load_token(db)
        db.close()

        if positional[1] == "*":
            return _cmd_push_all(message, token, log_fn)

        return _cmd_push(positional[1:], message, token, log_fn)

    # ── list ─────────────────────────────────
    elif cmd == "list":
        db    = _get_db()
        token = _load_token(db)
        db.close()
        return _cmd_list(token, log_fn)

    # ── diff ─────────────────────────────────
    elif cmd == "diff":
        if len(positional) < 2:
            log_fn("[publish] Usage : publish diff <fichier>")
            return 1, "argument manquant"
        db    = _get_db()
        token = _load_token(db)
        db.close()
        return _cmd_diff(positional[1], token, log_fn)

    # ── status ───────────────────────────────
    elif cmd == "status":
        db    = _get_db()
        token = _load_token(db)
        db.close()
        return _cmd_status(token, log_fn)

    # ── token ────────────────────────────────
    elif cmd == "token":
        if len(positional) < 2:
            log_fn("[publish] Usage : publish token set|show|del [<token>]")
            return 1, "argument manquant"

        sub = positional[1].lower()

        if sub == "set":
            if len(positional) < 3:
                log_fn("[publish] Usage : publish token set <votre_token_github>")
                return 1, "token manquant"
            return _cmd_token_set(positional[2], log_fn)

        elif sub == "show":
            return _cmd_token_show(log_fn)

        elif sub in ("del", "delete", "rm", "remove"):
            return _cmd_token_del(log_fn)

        else:
            log_fn(f"[publish] Sous-commande token inconnue : '{sub}'")
            return 1, f"sous-commande inconnue : {sub}"

    # ── help ─────────────────────────────────
    elif cmd in ("help", "-h", "--help"):
        log_fn(_HELP_TEXT)
        return 0, None

    # ── inconnu ──────────────────────────────
    else:
        log_fn(
            f"[publish] Commande inconnue : '{cmd}'. "
            "Tapez 'publish help' pour l'aide."
        )
        return 1, f"commande inconnue : {cmd}"


# ─────────────────────────────────────────────
# Déclarations R-ECO3
# ─────────────────────────────────────────────

def R_ECO3dep() -> tuple:
    return (
        ("3.5.1b",),
        (
            ("core.utils",  ("1.1",)),
            ("core.hive",   ("1.1",)),
            ("core.trail",  ("1.1",)),
        )
    )
    # vine et core.apix ne sont plus requis.


def R_ECO3inf() -> dict:
    return {
        "name":        "publish",
        "desc":        "Publie des modules vers le dépôt GitHub R-ECO3.5",
        "help": (
            "publish push <f>|*   Pousse un ou tous les fichiers vers GitHub\n"
            "publish status       Compare les fichiers locaux au dépôt\n"
            "publish diff <f>     Vérifie si un fichier local diffère du dépôt\n"
            "publish list         Liste les fichiers présents sur le dépôt\n"
            "publish token ...    Gère le token GitHub (set / show / del)"
        ),
        "alias_rules": (
            "publish /* = banana err --msg='This module cannot be run without "
            "arguments. Please refer to the manual for usage instructions.'"
        ),
        "version_mod": _VERSION,
        "L2Module":    True,
        "manual": (
            "publish — Publish modules to GitHub R-ECO3.5  v2.0\n"
            "===================================================\n"
            "\n"
            "SYNOPSIS\n"
            "    publish push <fichier> [<fichier2> ...] [--msg=TEXT]\n"
            "    publish push * [--msg=TEXT]\n"
            "    publish list\n"
            "    publish diff <fichier>\n"
            "    publish status\n"
            "    publish token set <token>\n"
            "    publish token show\n"
            "    publish token del\n"
            "    publish help\n"
            "\n"
            "COMMANDS\n"
            "    push <fichier> [<fichier2> ...] [--msg=TEXT]\n"
            "        Publishes one or more local files to the GitHub repository.\n"
            "\n"
            "    push * [--msg=TEXT]\n"
            "        Scans modules/ and core/ then publishes every eligible file.\n"
            "\n"
            "    list\n"
            "        Lists files currently present in the remote repository.\n"
            "\n"
            "    diff <fichier>\n"
            "        Compares a local file with its remote version using Git SHA-1.\n"
            "\n"
            "    status\n"
            "        Checks all local files and reports whether they are identical,\n"
            "        modified, or new compared to the remote repository.\n"
            "\n"
            "    token set <token>\n"
            "        Stores the GitHub personal access token in HiveFS.\n"
            "\n"
            "    token show\n"
            "        Displays the stored token in masked form.\n"
            "\n"
            "    token del\n"
            "        Deletes the stored GitHub token from HiveFS.\n"
            "\n"
            "IMPLEMENTATION\n"
            "    HTTP calls use Python's stdlib urllib only — no vine, no apix.\n"
            "    Dependency on core.apix and vine has been removed.\n"
            "\n"
            "STORED KEYS\n"
            "    §sys:publish:github_token\n"
            "        GitHub personal access token used by publish.\n"
            "\n"
            "EXAMPLES\n"
            "    publish token set ghp_xxxxxxxxxxxx\n"
            "    publish push raven.py --msg=\"fix: prompt cleanup\"\n"
            "    publish push * --msg=\"release snapshot\"\n"
            "    publish status\n"
            "    publish diff mule.py\n"
        ),
    }


# ─────────────────────────────────────────────
# Texte d'aide
# ─────────────────────────────────────────────

_HELP_TEXT = """\
publish v2.0 — Outil de publication vers GitHub R-ECO3.5
Dépôt cible : https://github.com/Romaxololt/R-ECO3.5  (branche main)

Commandes :
  publish push <fichier> [<f2> ...]   Pousse un ou plusieurs fichiers
  publish push *                      Pousse tout modules/ et core/
    [--msg="message de commit"]       Message de commit (optionnel)

  publish status                      Compare tous les fichiers locaux au dépôt
                                        [+] nouveau   [M] modifié   [=] identique

  publish diff <fichier>              Compare un fichier local à sa version distante

  publish list                        Liste les fichiers présents sur le dépôt

  publish token set <token>           Enregistre le token GitHub (Personal Access Token)
  publish token show                  Affiche le token masqué actuellement enregistré
  publish token del                   Supprime le token de la base

Résolution des chemins :
  fichier.py   → modules/fichier.py   (sur le dépôt)
  core.utils   → core/utils           (préfixe "core." détecté automatiquement)

Prérequis :
  Un Personal Access Token GitHub (classic) avec le scope 'repo'.
  Générez-en un sur : https://github.com/settings/tokens

Changements v2.0 :
  • HTTP via urllib stdlib — vine et core.apix ne sont plus nécessaires.
  • Dépendances déclarées allégées (core.utils, core.hive, core.trail).

Exemples :
  publish token set ghp_xxxxxxxxxxxx
  publish push raven.py --msg="fix: correction du prompt"
  publish push core.utils vine.py --msg="feat: mise à jour groupée"
  publish push * --msg="release: snapshot complet"
  publish status
  publish diff mule.py
"""