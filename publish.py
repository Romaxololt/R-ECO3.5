# publish.py — Module R-ECO3
# Outil de publication de modules vers le dépôt GitHub R-ECO3.5
# Utilise l'API GitHub REST pour pousser des fichiers directement depuis RAVEN.

_VERSION = "1.1"
_REPO_OWNER = "Romaxololt"
_REPO_NAME  = "R-ECO3.5"
_BRANCH     = "main"
_API_BASE   = "https://api.github.com"
_DB_KEY_TOKEN = "§sys:publish:github_token"


# ─────────────────────────────────────────────
# Helpers internes
# ─────────────────────────────────────────────

def _get_db():
    import core.trail as trail
    import core.hive as hive
    return hive.HiveFS(str(trail.DB_FILE))


def _load_token(db) -> str:
    tok = db.get(_DB_KEY_TOKEN, as_str=True)
    return tok.strip() if tok else ""


def _real_path(filename: str):
    import core.trail as trail
    if filename.startswith("core."):
        return trail.ROOT / "core" / filename[5:]
    return trail.MODULES_DIR / filename


def _remote_path(filename: str) -> str:
    if filename.startswith("core."):
        return "core/" + filename[5:]
    if filename.startswith("modules/"):
        return filename[len("modules/"):]  # strip le préfixe
    return filename  # ← racine au lieu de "modules/" + filename


def _api_request(method, path, token, payload=None, log_fn=print):
    import core.apix as apix
    import json

    url = f"{_API_BASE}{path}"
    vine_args = (
        f"'{url}'"
        f" --method={method}"
        f" --header='Authorization: token {token}'"
        f" --header='Accept: application/vnd.github+json'"
        f" --header='X-GitHub-Api-Version: 2022-11-28'"
        f" --no-status"   # ← supprime les lignes ✓/✗ et Status
    )

    if payload is not None:
        body = json.dumps(payload)
        vine_args += f" --data='{body}'"

    lines = []
    def _capture(msg=""):
        lines.append(str(msg))

    apix.R_ECO3(f"run vine {vine_args}", log_fn=_capture)
    raw = "\n".join(lines)

    # Extraire le premier bloc JSON valide
    for i, line in enumerate(lines):
        if line.strip().startswith("{") or line.strip().startswith("["):
            candidate = "\n".join(lines[i:])
            try:
                data = json.loads(candidate)
                return 0, data
            except json.JSONDecodeError:
                pass

    return 1, raw

def _get_file_sha(remote_path: str, token: str, log_fn) -> str:
    path = f"/repos/{_REPO_OWNER}/{_REPO_NAME}/contents/{remote_path}?ref={_BRANCH}"
    code, data = _api_request("GET", path, token, log_fn=log_fn)
    if code != 0 or not isinstance(data, dict):
        return ""
    return data.get("sha", "")


def _push_file(filename: str, token: str, message: str, log_fn) -> tuple:
    import base64

    local = _real_path(filename)
    if not local.exists():
        return 1, f"Fichier local introuvable : '{local}'"

    try:
        content_bytes = local.read_bytes()
    except OSError as exc:
        return 1, f"Erreur lecture '{local}' : {exc}"

    content_b64 = base64.b64encode(content_bytes).decode("ascii")
    rpath = _remote_path(filename)

    sha = _get_file_sha(rpath, token, log_fn)

    payload = {
        "message": message,
        "content": content_b64,
        "branch":  _BRANCH,
    }
    if sha:
        payload["sha"] = sha

    api_path = f"/repos/{_REPO_OWNER}/{_REPO_NAME}/contents/{rpath}"
    code, data = _api_request("PUT", api_path, token, payload=payload, log_fn=log_fn)

    if code != 0:
        return 1, str(data)

    if isinstance(data, dict):
        if "content" in data or "commit" in data:
            return 0, None
        if "message" in data:
            return 1, data["message"]

    return 1, f"Réponse inattendue : {data}"


# ─────────────────────────────────────────────
# Commandes
# ─────────────────────────────────────────────

def _cmd_push(files: list, message: str, token: str, log_fn) -> tuple:
    if not token:
        log_fn("[publish] ✗ Aucun token GitHub configuré.")
        log_fn("[publish]   Utilisez : publish token set <votre_token>")
        return 1, "token manquant"

    ok_list, err_list = [], []

    for fname in files:
        log_fn(f"[publish] Envoi de '{fname}' → {_remote_path(fname)} ...")
        code, detail = _push_file(fname, token, message, log_fn)
        if code == 0:
            log_fn(f"[publish] ✓ '{fname}' publié.")
            ok_list.append(fname)
        else:
            log_fn(f"[publish] ✗ '{fname}' : {detail}")
            err_list.append(fname)

    log_fn(f"[publish] Terminé — {len(ok_list)} publié(s), {len(err_list)} erreur(s).")
    return (1, err_list) if err_list else (0, ok_list)


def _cmd_push_all(message: str, token: str, log_fn) -> tuple:
    import core.trail as trail

    _IGNORE = {"__init__.py", "__pycache__"}
    files = []

    if trail.MODULES_DIR.exists():
        for p in trail.MODULES_DIR.iterdir():
            if p.is_file() and p.name not in _IGNORE and not p.name.endswith(".pyc"):
                files.append(p.name)

    core_dir = trail.ROOT / "core"
    if core_dir.exists():
        for p in core_dir.iterdir():
            if p.is_file() and p.name not in _IGNORE and not p.name.endswith(".pyc"):
                files.append("core." + p.name)

    if not files:
        log_fn("[publish] Aucun fichier trouvé sur le disque.")
        return 0, []

    log_fn(f"[publish] {len(files)} fichier(s) à publier.")
    return _cmd_push(files, message, token, log_fn)


def _cmd_token_set(token_value: str, log_fn) -> tuple:
    db = _get_db()
    db.set(_DB_KEY_TOKEN, token_value.strip())
    db.close()
    log_fn("[publish] ✓ Token GitHub enregistré.")
    return 0, None


def _cmd_token_show(log_fn) -> tuple:
    db = _get_db()
    tok = _load_token(db)
    db.close()

    if not tok:
        log_fn("[publish] Aucun token enregistré.")
        return 1, "pas de token"

    masked = tok[:6] + "****" + tok[-4:] if len(tok) > 10 else "****"
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


def _cmd_list(log_fn) -> tuple:
    db = _get_db()
    token = _load_token(db)
    db.close()

    if not token:
        log_fn("[publish] ✗ Token manquant. Utilisez : publish token set <token>")
        return 1, "token manquant"

    results = []
    for folder in ("modules", "core"):
        path = f"/repos/{_REPO_OWNER}/{_REPO_NAME}/contents/{folder}?ref={_BRANCH}"
        code, data = _api_request("GET", path, token, log_fn=log_fn)
        if code != 0 or not isinstance(data, list):
            log_fn(f"[publish] ✗ Impossible de lister '{folder}' : {data}")
            continue
        for item in data:
            name   = item.get("name", "?")
            size   = item.get("size", 0)
            sha    = item.get("sha", "")[:8]
            prefix = "core." if folder == "core" else ""
            log_fn(f"  {prefix}{name:<30}  {size:>7} o   sha:{sha}")
            results.append(prefix + name)

    if not results:
        log_fn("[publish] Dépôt vide ou inaccessible.")
    return 0, results


def _cmd_diff(filename: str, log_fn) -> tuple:
    import base64
    import hashlib

    db = _get_db()
    token = _load_token(db)
    db.close()

    if not token:
        log_fn("[publish] ✗ Token manquant.")
        return 1, "token manquant"

    local = _real_path(filename)
    if not local.exists():
        log_fn(f"[publish] ✗ Fichier local introuvable : '{local}'")
        return 1, "fichier local absent"

    content = local.read_bytes()
    header  = f"blob {len(content)}\0".encode()
    local_sha = hashlib.sha1(header + content).hexdigest()

    rpath      = _remote_path(filename)
    remote_sha = _get_file_sha(rpath, token, log_fn)

    if not remote_sha:
        log_fn(f"[publish] '{filename}' → absent sur le dépôt (nouveau fichier).")
        return 0, "nouveau"

    if local_sha == remote_sha:
        log_fn(f"[publish] '{filename}' → identique au dépôt. ✓")
        return 0, "identique"

    log_fn(f"[publish] '{filename}' → différent du dépôt.")
    log_fn(f"           local  sha1 : {local_sha[:16]}…")
    log_fn(f"           remote sha1 : {remote_sha[:16]}…")
    return 0, "modifié"


def _cmd_status(log_fn) -> tuple:
    import core.trail as trail

    db = _get_db()
    token = _load_token(db)
    db.close()

    if not token:
        log_fn("[publish] ✗ Token manquant. Utilisez : publish token set <token>")
        return 1, "token manquant"

    _IGNORE = {"__init__.py", "__pycache__"}
    files = []

    if trail.MODULES_DIR.exists():
        for p in trail.MODULES_DIR.iterdir():
            if p.is_file() and p.name not in _IGNORE and not p.name.endswith(".pyc"):
                files.append(p.name)

    core_dir = trail.ROOT / "core"
    if core_dir.exists():
        for p in core_dir.iterdir():
            if p.is_file() and p.name not in _IGNORE and not p.name.endswith(".pyc"):
                files.append("core." + p.name)

    if not files:
        log_fn("[publish] Aucun fichier local trouvé.")
        return 0, {}

    log_fn(f"[publish] Vérification de {len(files)} fichier(s)...\n")
    summary = {"identique": [], "modifié": [], "nouveau": []}

    for fname in files:
        code, state = _cmd_diff(fname, log_fn=lambda *a: None)
        if code == 0 and state in summary:
            summary[state].append(fname)
            icon = {"identique": "=", "modifié": "M", "nouveau": "+"}.get(state, "?")
            log_fn(f"  [{icon}] {fname}")

    log_fn(
        f"\n[publish] {len(summary['nouveau'])} nouveau(x), "
        f"{len(summary['modifié'])} modifié(s), "
        f"{len(summary['identique'])} identique(s)."
    )
    return 0, summary


# ─────────────────────────────────────────────
# Interface R-ECO3
# ─────────────────────────────────────────────

def R_ECO3(args: str, log_fn=print) -> tuple:
    """
    Point d'entrée principal.

    Commandes :
        publish push <fichier> [<fichier2> ...] [--msg="message"]
        publish push *                            [--msg="message"]
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

    if cmd == "push":
        if len(positional) < 2:
            log_fn("[publish] Usage : publish push <fichier> | publish push *")
            return 1, "argument manquant"

        message = flags.get("msg", flags.get("message", flags.get("m",
                  "publish: mise à jour via publish.py")))

        db = _get_db()
        token = _load_token(db)
        db.close()

        target = positional[1]
        if target == "*":
            return _cmd_push_all(message, token, log_fn)

        files = positional[1:]
        return _cmd_push(files, message, token, log_fn)

    elif cmd == "list":
        return _cmd_list(log_fn)

    elif cmd == "diff":
        if len(positional) < 2:
            log_fn("[publish] Usage : publish diff <fichier>")
            return 1, "argument manquant"
        return _cmd_diff(positional[1], log_fn)

    elif cmd == "status":
        return _cmd_status(log_fn)

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

    elif cmd in ("help", "-h", "--help"):
        log_fn(_HELP_TEXT)
        return 0, None

    else:
        log_fn(f"[publish] Commande inconnue : '{cmd}'. Tapez 'publish help' pour l'aide.")
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
            ("core.apix",   ("1.1",)),
            ("core.trail",  ("1.1",)),
            ("vine",        ("1.1",)),
        )
    )


def R_ECO3inf() -> dict:
    return {
        "name":        "publish",
        "desc":        "Publie des modules vers le dépôt GitHub R-ECO3.5",
        "help":        (
            "publish push <f>|*   Pousse un ou tous les fichiers vers GitHub\n"
            "publish status       Compare les fichiers locaux au dépôt\n"
            "publish diff <f>     Vérifie si un fichier local diffère du dépôt\n"
            "publish list         Liste les fichiers présents sur le dépôt\n"
            "publish token ...    Gère le token GitHub (set / show / del)"
        ),
        "alias_rules": "publish /* = banana err --msg='This module cannot be run without arguments. Please refer to the manual for usage instructions.'",
        "version_mod": _VERSION,
        "L2Module":    True,
        "manual":      _MANUAL_TEXT,
    }


# ─────────────────────────────────────────────
# Textes d'aide
# ─────────────────────────────────────────────

_HELP_TEXT = """\
publish v1.1 — Outil de publication vers GitHub R-ECO3.5
Dépôt cible : https://github.com/Romaxololt/R-ECO3.5 (branche main)

Commandes :
  publish push <fichier> [<f2> ...]   Pousse un ou plusieurs fichiers vers le dépôt
  publish push *                      Pousse tout modules/ et core/
    [--msg="message de commit"]       Message de commit personnalisé (optionnel)

  publish status                      Compare tous les fichiers locaux au dépôt
                                        [+] nouveau   [M] modifié   [=] identique

  publish diff <fichier>              Vérifie si un fichier diffère de la version distante

  publish list                        Liste les fichiers présents sur le dépôt

  publish token set <token>           Enregistre le token GitHub (Personal Access Token)
  publish token show                  Affiche le token masqué actuellement enregistré
  publish token del                   Supprime le token de la base

Résolution des chemins :
  fichier.py    → modules/fichier.py   (sur le dépôt)
  core.utils    → core/utils           (préfixe "core." détecté automatiquement)

Prérequis :
  Un Personal Access Token GitHub (classic) avec le scope 'repo' sur le dépôt.
  Générez-en un sur : https://github.com/settings/tokens

Exemples :
  publish token set ghp_xxxxxxxxxxxx
  publish push raven.py --msg="fix: correction du prompt"
  publish push core.utils vine.py --msg="feat: mise à jour groupée"
  publish push * --msg="release: snapshot complet"
  publish status
  publish diff mule.py
"""

_MANUAL_TEXT = """\
# publish — Manuel complet v1.1

## Description
`publish` est le module de publication de R-ECO3.
Il permet de pousser des fichiers locaux (modules/ et core/) directement vers le
dépôt GitHub https://github.com/Romaxololt/R-ECO3.5 via l'API REST GitHub,
sans quitter l'environnement RAVEN.

Ce module est le pendant de `mule` (qui *installe* depuis le dépôt) :
  mule install / update   ← tire du dépôt vers le disque local
  publish push            → pousse du disque local vers le dépôt

## Prérequis

Un **Personal Access Token (PAT) classic** GitHub avec le scope :
  - `repo` (accès complet au dépôt privé ou public)

Générez un token sur : https://github.com/settings/tokens
Puis enregistrez-le : `publish token set <votre_token>`

## Fix v1.1 — Correction du 401

Dans la v1.0, le header Authorization était construit ainsi :
  --header=Authorization:Bearer <token>
L'espace entre "Bearer" et le token faisait que tokenize() de core.utils
découpait la valeur en deux tokens distincts. vine recevait donc le header
sans la valeur du token → GitHub retournait 401.

Correction : encapsulation de chaque header entre guillemets simples, et
utilisation du schéma "token" (PAT classic) au lieu de "Bearer" :
  --header='Authorization: token <token>'

Le double-appel vine (silent + non-silent) a également été supprimé.

## Commandes

### publish push <fichier> [--msg="message"]
Pousse un ou plusieurs fichiers vers le dépôt.
- Si le fichier existe déjà sur le dépôt → il est mis à jour (PUT avec SHA).
- S'il n'existe pas encore → il est créé.
- Le message de commit par défaut est "publish: mise à jour via publish.py".

### publish push * [--msg="message"]
Scanne modules/ et core/ et pousse tous les fichiers trouvés.

### publish status
Compare localement chaque fichier avec sa version sur le dépôt (via SHA blob Git).
  [+] nouveau    → présent localement, absent du dépôt
  [M] modifié    → présent des deux côtés mais SHA différent
  [=] identique  → aucune différence

### publish diff <fichier>
Calcule le SHA blob Git local (sha1("blob <size>\\0<content>")) et le compare
au SHA retourné par l'API GitHub.

### publish list
Liste tous les fichiers présents dans modules/ et core/ sur le dépôt distant.

### publish token set <token>
Enregistre le PAT dans HiveFS sous la clé : §sys:publish:github_token

### publish token show
Affiche le token masqué (6 premiers + 4 derniers caractères).

### publish token del
Supprime le token de HiveFS.

## Résolution des chemins

| Nom logique   | Chemin local            | Chemin GitHub              |
|---------------|-------------------------|----------------------------|
| raven.py      | modules/raven.py        | modules/raven.py           |
| core.utils    | core/utils              | core/utils                 |
| mule.py       | modules/mule.py         | modules/mule.py            |

## Clés HiveFS

  §sys:publish:github_token   → Personal Access Token GitHub

## Dépendances
  core.utils, core.hive, core.apix, core.trail, vine

## Version
  publish v1.1 — R-ECO3 v3.5.1b (Ant)
"""