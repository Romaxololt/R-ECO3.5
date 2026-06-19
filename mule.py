# mule.py — Module R-ECO3
# Gestionnaire de fichiers distants via GitHub raw
# Base URL : https://raw.githubusercontent.com/Romaxololt/R-ECO3.5/main/

_VERSION = "2.1"
_BASE_URL = "https://raw.githubusercontent.com/Romaxololt/R-ECO3.5/main/"
_DB_KEY_PREFIX = "§sys:mule:installed:"
_DB_KEY_LIST = "§sys:mule:list"
_SEP = "<MULE_SEP:=:>"

# ─────────────────────────────────────────────
# Helpers internes
# ─────────────────────────────────────────────

def _get_installed(db) -> list:
    raw = db.get(_DB_KEY_LIST)
    if not raw:
        return []
    return [f for f in raw.split(_SEP) if f]


def _save_installed(db, lst: list):
    db.set(_DB_KEY_LIST, _SEP.join(lst))


def _real_path(filename: str):
    import core.trail as trail
    if filename.startswith("core."):
        return trail.ROOT / "core" / filename[5:]
    return trail.MODULES_DIR / filename


def _fetch_file(filename: str, log_fn) -> tuple:
    import core.apix as apix
    url = _BASE_URL + filename
    lines = []

    def _capture(msg=""):
        lines.append(str(msg))

    result = apix.R_ECO3({"args": f'run vine {url} --no-status', "logfn": _capture})

    # ── compatibilité API v2 (dict) et legacy (tuple) ──────────────────
    if isinstance(result, dict):
        code = result.get("status", 1)
    elif isinstance(result, (tuple, list)) and len(result) >= 1:
        code = result[0]
    else:
        code = 0 if result == 0 else 1

    if code != 0:
        return 1, f"Erreur réseau pour '{filename}'"

    content = "\n".join(lines)
    if not content.strip():
        return 1, f"Réponse vide pour '{filename}'"

    if "404: Not Found" in content or content.strip() == "404: Not Found":
        return 1, "404"

    return 0, content


def _write_file(filename: str, content: str, log_fn) -> bool:
    target_path = _real_path(filename)
    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(content)
        return True
    except OSError as exc:
        log_fn(f"[mule] Erreur écriture '{target_path}': {exc}")
        return False


def _remove_file(filename: str, log_fn) -> bool:
    import os
    target_path = _real_path(filename)
    try:
        if target_path.exists():
            os.remove(target_path)
            return True
        log_fn(f"[mule] Fichier introuvable sur disque : '{target_path}'")
        return False
    except OSError as exc:
        log_fn(f"[mule] Erreur suppression '{target_path}': {exc}")
        return False


def _scan_disk() -> list:
    import core.trail as trail
    _IGNORE = {"__init__.py", "__pycache__"}
    found = []

    if trail.MODULES_DIR.exists():
        for p in trail.MODULES_DIR.iterdir():
            if p.is_file() and p.name not in _IGNORE and not p.name.endswith(".pyc"):
                found.append(p.name)

    core_dir = trail.ROOT / "core"
    if core_dir.exists():
        for p in core_dir.iterdir():
            if p.is_file() and p.name not in _IGNORE and not p.name.endswith(".pyc"):
                found.append("core." + p.name)

    return found


def _register(db, installed: list, filename: str):
    if filename not in installed:
        installed.append(filename)
        _save_installed(db, installed)
        db.set(_DB_KEY_PREFIX + filename, _BASE_URL + filename)


# ─────────────────────────────────────────────
# Commandes
# ─────────────────────────────────────────────

def _cmd_install(filename: str, log_fn, db) -> dict:
    installed = _get_installed(db)

    if filename in installed:
        path = _real_path(filename)
        if path.exists():
            log_fn(f"[mule] '{filename}' est déjà installé. Utilisez 'mule update {filename}' pour mettre à jour.")
            return {"status": 0, "value": None}
        log_fn(f"[mule] '{filename}' marqué installé mais absent du disque, réinstallation...")
        installed.remove(filename)
        _save_installed(db, installed)

    log_fn(f"[mule] Téléchargement de '{filename}'...")
    code, content = _fetch_file(filename, log_fn)
    if code != 0:
        log_fn(f"[mule] ✗ {content}")
        return {"status": 1, "value": content}

    if not _write_file(filename, content, log_fn):
        return {"status": 1, "value": f"Échec de l'écriture de '{filename}'"}

    _register(db, installed, filename)
    log_fn(f"[mule] ✓ '{filename}' installé avec succès.")
    return {"status": 0, "value": None}


def _cmd_uninstall(filename: str, log_fn, db) -> dict:
    installed = _get_installed(db)

    if filename not in installed:
        log_fn(f"[mule] '{filename}' n'est pas dans la liste des fichiers gérés par mule.")
        return {"status": 1, "value": f"'{filename}' non installé"}

    if not _remove_file(filename, log_fn):
        return {"status": 1, "value": f"Échec de la suppression de '{filename}'"}

    installed.remove(filename)
    _save_installed(db, installed)
    try:
        db.delete(_DB_KEY_PREFIX + filename)
    except Exception:
        pass

    log_fn(f"[mule] ✓ '{filename}' désinstallé.")
    return {"status": 0, "value": None}


def _cmd_update_all(log_fn, db) -> dict:
    """
    mule update * — scanne modules/ et core/, tente une mise à jour depuis le repo
    pour chaque fichier trouvé. Ignore les 404 silencieusement.
    """
    files = _scan_disk()
    if not files:
        log_fn("[mule] Aucun fichier trouvé sur le disque.")
        return {"status": 0, "value": []}

    log_fn(f"[mule] {len(files)} fichier(s) détecté(s) sur le disque.")

    ok_list   = []
    skip_list = []
    err_list  = []

    for fname in files:
        code, content = _fetch_file(fname, log_fn)

        if code != 0:
            if "404" in content:
                skip_list.append(fname)
            else:
                log_fn(f"[mule] ✗ {fname} : {content}")
                err_list.append(fname)
            continue

        if not _write_file(fname, content, log_fn):
            err_list.append(fname)
            continue

        inst = _get_installed(db)
        _register(db, inst, fname)
        log_fn(f"[mule] ✓ '{fname}' mis à jour.")
        ok_list.append(fname)

    log_fn(
        f"[mule] Terminé — {len(ok_list)} mis à jour, "
        f"{len(skip_list)} ignorés (absents du repo), "
        f"{len(err_list)} erreur(s)."
    )
    return {"status": 1 if err_list else 0, "value": err_list if err_list else ok_list}


def _cmd_update(target: str, log_fn, db) -> dict:
    if target == "*":
        return _cmd_update_all(log_fn, db)

    installed = _get_installed(db)

    if target not in installed:
        log_fn(f"[mule] '{target}' n'est pas géré par mule. Utilisez 'mule install {target}' d'abord.")
        return {"status": 1, "value": f"'{target}' non installé"}

    log_fn(f"[mule] Mise à jour de '{target}'...")
    code, content = _fetch_file(target, log_fn)
    if code != 0:
        log_fn(f"[mule] ✗ {content}")
        return {"status": 1, "value": content}

    if not _write_file(target, content, log_fn):
        return {"status": 1, "value": f"Échec écriture '{target}'"}

    log_fn(f"[mule] ✓ '{target}' mis à jour.")
    return {"status": 0, "value": None}


# ─────────────────────────────────────────────
# Interface R-ECO3
# ─────────────────────────────────────────────

def R_ECO3(inp: dict) -> dict:
    """
    Point d'entrée principal de mule.

    Commandes :
        mule install <fichier>
        mule desinstall <fichier>
        mule update <fichier>
        mule update *
    """
    args   = inp["args"]
    log_fn = inp["logfn"]
    db     = inp["db"]

    import core.utils as utils
    positional, flags = utils.parse_command(args)

    if not positional:
        log_fn("[mule] Usage : mule <install|desinstall|update> <fichier>")
        log_fn("Tapez 'mule help' pour l'aide complète.")
        return {"status": 1, "value": "commande manquante"}

    cmd = positional[0].lower()

    if cmd == "install":
        if len(positional) < 2:
            log_fn("[mule] Usage : mule install <fichier>")
            return {"status": 1, "value": "argument manquant"}
        return _cmd_install(positional[1], log_fn, db)

    elif cmd in ("desinstall", "uninstall"):
        if len(positional) < 2:
            log_fn("[mule] Usage : mule desinstall <fichier>")
            return {"status": 1, "value": "argument manquant"}
        return _cmd_uninstall(positional[1], log_fn, db)

    elif cmd == "update":
        if len(positional) < 2:
            log_fn("[mule] Usage : mule update <fichier> | mule update *")
            return {"status": 1, "value": "argument manquant"}
        return _cmd_update(positional[1], log_fn, db)

    elif cmd in ("help", "-h", "--help"):
        log_fn(_HELP_TEXT)
        return {"status": 0, "value": None}

    else:
        log_fn(f"[mule] Commande inconnue : '{cmd}'. Tapez 'mule help' pour l'aide.")
        return {"status": 1, "value": f"commande inconnue : {cmd}"}


def R_ECO3dep() -> dict:
    return {
        "reco": ["3.5.2b"],
        "module": [
            {"vine":        ["2.1"]},
        ],
    }


def R_ECO3inf() -> dict:
    return {
        "name":        "mule",
        "desc":        "Gestionnaire de fichiers distants (GitHub raw)",
        "help": (
            "mule install <f>      Télécharge et installe un fichier depuis le dépôt\n"
            "mule desinstall <f>   Supprime un fichier installé via mule\n"
            "mule update <f>|*     Met à jour un fichier (ou tout le disque avec *)"
        ),
        "version_mod": _VERSION,
        "alias_rules": (
            "mule /* = banana err --msg='Usage: mule <install|desinstall|update> <fichier>'\n"
            "mule * = mule /*"
        ),
        "L2Module": True,
        "manual": (
            "mule — Remote file manager via GitHub raw  v2.1\n"
            "=================================================\n"
            "\n"
            "SYNOPSIS\n"
            "    mule install <fichier>\n"
            "    mule desinstall <fichier>\n"
            "    mule uninstall <fichier>\n"
            "    mule update <fichier>\n"
            "    mule update *\n"
            "    mule help\n"
            "\n"
            "COMMANDES\n"
            "    install <fichier>\n"
            "        Télécharge et installe le fichier depuis le dépôt distant.\n"
            "        Si déjà installé et présent sur le disque, ne fait rien\n"
            "        (utiliser 'update' pour forcer).\n"
            "\n"
            "    desinstall <fichier>  /  uninstall <fichier>\n"
            "        Supprime le fichier du disque et de la base HiveFS.\n"
            "\n"
            "    update <fichier>\n"
            "        Retélécharge et écrase la version locale du fichier.\n"
            "        Le fichier doit avoir été installé via mule.\n"
            "\n"
            "    update *\n"
            "        Scanne modules/ et core/, puis met à jour tous les fichiers\n"
            "        qui existent aussi sur le dépôt distant.\n"
            "        Les 404 sont ignorés silencieusement.\n"
            "\n"
            "    help\n"
            "        Affiche l'aide du module.\n"
            "\n"
            "RÉSOLUTION DES CHEMINS\n"
            "    fichier.py     → modules/fichier.py\n"
            "    core.utils     → core/utils\n"
            "    (le préfixe 'core.' est détecté automatiquement)\n"
            "\n"
            "CLÉS HIVEFS\n"
            "    §sys:mule:list\n"
            "        Liste des fichiers suivis (séparateur <MULE_SEP:=:>).\n"
            "\n"
            "    §sys:mule:installed:<filename>\n"
            "        URL source du fichier installé.\n"
            "\n"
            "EXEMPLES\n"
            "    mule install vine.py\n"
            "    mule update vine.py\n"
            "    mule update *\n"
            "    mule desinstall test.py\n"
        ),
    }


# ─────────────────────────────────────────────
# Texte d'aide
# ─────────────────────────────────────────────

_HELP_TEXT = """\
mule v2.1 — Gestionnaire de fichiers distants R-ECO3
Base URL : https://raw.githubusercontent.com/Romaxololt/R-ECO3.5/main/

Commandes :
  mule install <fichier>      Télécharge et installe <fichier> depuis le dépôt
  mule desinstall <fichier>   Désinstalle <fichier> (supprime du disque + base)
  mule update <fichier>       Retélécharge et écrase <fichier>
  mule update *               Scanne modules/ et core/, met à jour tout ce qui
                              existe sur le repo (404 ignorés silencieusement)

Résolution des chemins :
  fichier.py     → modules/fichier.py
  core.utils     → core/utils  (préfixe "core." détecté automatiquement)

Exemples :
  mule install vine.py
  mule update *
  mule update vine.py
  mule desinstall test.py
"""