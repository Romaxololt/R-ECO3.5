# mule.py — Module R-ECO3
# Gestionnaire de fichiers distants via GitHub raw
# Base URL : https://raw.githubusercontent.com/Romaxololt/R-ECO3.5/main/

_VERSION = "1.3"
_BASE_URL = "https://raw.githubusercontent.com/Romaxololt/R-ECO3.5/main/"
_DB_KEY_PREFIX = "§sys:mule:installed:"
_DB_KEY_LIST = "§sys:mule:list"
_SEP = "<MULE_SEP:=:>"

# ─────────────────────────────────────────────
# Helpers internes
# ─────────────────────────────────────────────

def _get_db():
    import core.trail as trail
    import core.hive as hive
    return hive.HiveFS(str(trail.DB_FILE))


def _get_installed(db) -> list:
    raw = db.get(_DB_KEY_LIST, as_str=True)
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

    code, _ = apix.R_ECO3(f'run vine {url} --no-status', log_fn=_capture)
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

def _cmd_install(filename: str, log_fn) -> tuple:
    db = _get_db()
    installed = _get_installed(db)

    if filename in installed:
        path = _real_path(filename)
        if path.exists():
            log_fn(f"[mule] '{filename}' est déjà installé. Utilisez 'mule update {filename}' pour mettre à jour.")
            db.close()
            return 0, None
        log_fn(f"[mule] '{filename}' marqué installé mais absent du disque, réinstallation...")
        installed.remove(filename)
        _save_installed(db, installed)

    log_fn(f"[mule] Téléchargement de '{filename}'...")
    code, content = _fetch_file(filename, log_fn)
    if code != 0:
        log_fn(f"[mule] ✗ {content}")
        db.close()
        return 1, content

    if not _write_file(filename, content, log_fn):
        db.close()
        return 1, f"Échec de l'écriture de '{filename}'"

    _register(db, installed, filename)
    db.close()
    log_fn(f"[mule] ✓ '{filename}' installé avec succès.")
    return 0, None


def _cmd_uninstall(filename: str, log_fn) -> tuple:
    db = _get_db()
    installed = _get_installed(db)

    if filename not in installed:
        log_fn(f"[mule] '{filename}' n'est pas dans la liste des fichiers gérés par mule.")
        db.close()
        return 1, f"'{filename}' non installé"

    if not _remove_file(filename, log_fn):
        db.close()
        return 1, f"Échec de la suppression de '{filename}'"

    installed.remove(filename)
    _save_installed(db, installed)
    try:
        db.delete(_DB_KEY_PREFIX + filename)
    except Exception:
        pass
    db.close()
    log_fn(f"[mule] ✓ '{filename}' désinstallé.")
    return 0, None


def _cmd_update_all(log_fn) -> tuple:
    """
    mule update * — scanne modules/ et core/, tente une mise à jour depuis le repo
    pour chaque fichier trouvé. Ignore les 404 silencieusement.
    Enregistre dans mule les fichiers qui ont un correspondant sur le repo.
    """
    files = _scan_disk()
    if not files:
        log_fn("[mule] Aucun fichier trouvé sur le disque.")
        return 0, []

    log_fn(f"[mule] {len(files)} fichier(s) détecté(s) sur le disque.")

    ok_list = []
    skip_list = []
    err_list = []

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

        db = _get_db()
        inst = _get_installed(db)
        _register(db, inst, fname)
        db.close()

        log_fn(f"[mule] ✓ '{fname}' mis à jour.")
        ok_list.append(fname)

    log_fn(f"[mule] Terminé — {len(ok_list)} mis à jour, {len(skip_list)} ignorés (absents du repo), {len(err_list)} erreur(s).")
    return (1, err_list) if err_list else (0, ok_list)


def _cmd_update(target: str, log_fn) -> tuple:
    if target == "*":
        return _cmd_update_all(log_fn)

    db = _get_db()
    installed = _get_installed(db)
    db.close()

    if target not in installed:
        log_fn(f"[mule] '{target}' n'est pas géré par mule. Utilisez 'mule install {target}' d'abord.")
        return 1, f"'{target}' non installé"

    log_fn(f"[mule] Mise à jour de '{target}'...")
    code, content = _fetch_file(target, log_fn)
    if code != 0:
        log_fn(f"[mule] ✗ {content}")
        return 1, content

    if not _write_file(target, content, log_fn):
        return 1, f"Échec écriture '{target}'"

    log_fn(f"[mule] ✓ '{target}' mis à jour.")
    return 0, None


# ─────────────────────────────────────────────
# Interface R-ECO3
# ─────────────────────────────────────────────

def R_ECO3(args: str, log_fn=print) -> tuple:
    """
    Point d'entrée principal de mule.

    Commandes :
        mule install <fichier>
        mule desinstall <fichier>
        mule update <fichier>
        mule update *
    """
    import core.utils as utils

    positional, flags = utils.parse_command(args)

    cmd = positional[0].lower()

    if cmd == "install":
        if len(positional) < 2:
            log_fn("[mule] Usage : mule install <fichier>")
            return 1, "argument manquant"
        return _cmd_install(positional[1], log_fn)

    elif cmd in ("desinstall", "uninstall"):
        if len(positional) < 2:
            log_fn("[mule] Usage : mule desinstall <fichier>")
            return 1, "argument manquant"
        return _cmd_uninstall(positional[1], log_fn)

    elif cmd == "update":
        if len(positional) < 2:
            log_fn("[mule] Usage : mule update <fichier> | mule update *")
            return 1, "argument manquant"
        return _cmd_update(positional[1], log_fn)

    elif cmd in ("help", "-h", "--help"):
        log_fn(_HELP_TEXT)
        return 0, None

    else:
        log_fn(f"[mule] Commande inconnue : '{cmd}'. Tapez 'mule help' pour l'aide.")
        return 1, f"commande inconnue : {cmd}"


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
        "name":        "mule",
        "desc":        "Gestionnaire de fichiers distants (GitHub raw)",
        "help":        (
            "mule install <f>      Télécharge et installe un fichier depuis le dépôt\n"
            "mule desinstall <f>   Supprime un fichier installé via mule\n"
            "mule update <f>|*     Met à jour un fichier (ou tout le disque avec *)"
        ),
        "version_mod": _VERSION,
        "alias_rules": "mule /* = banana err --msg='This module cannot be run without arguments. Please refer to the manual for usage instructions.'",
        "L2Module":    True,
        "manual": (
            "mule — Remote file manager via GitHub raw  v1.3\n"
            "===============================================\n"
            "\n"
            "SYNOPSIS\n"
            "    mule install <fichier>\n"
            "    mule desinstall <fichier>\n"
            "    mule uninstall <fichier>\n"
            "    mule update <fichier>\n"
            "    mule update *\n"
            "    mule help\n"
            "\n"
            "COMMANDS\n"
            "    install <fichier>\n"
            "        Télécharge et installe le fichier depuis le dépôt distant.\n"
            "\n"
            "    desinstall <fichier>\n"
            "        Supprime le fichier du disque et de la base HiveFS.\n"
            "\n"
            "    uninstall <fichier>\n"
            "        Alias de desinstall.\n"
            "\n"
            "    update <fichier>\n"
            "        Retélécharge et écrase la version locale du fichier.\n"
            "\n"
            "    update *\n"
            "        Scanne modules/ et core/, puis met à jour tous les fichiers\n"
            "        qui existent aussi sur le dépôt distant.\n"
            "\n"
            "    help\n"
            "        Affiche l'aide du module.\n"
            "\n"
            "STORED KEYS\n"
            "    §sys:mule:list\n"
            "        Liste des fichiers suivis par mule.\n"
            "\n"
            "    §sys:mule:installed:<filename>\n"
            "        URL source du fichier installé.\n"
            "\n"
            "EXAMPLES\n"
            "    mule install vine.py\n"
            "    mule update vine.py\n"
            "    mule update *\n"
            "    mule desinstall test.py\n"
        ),
    }


# ─────────────────────────────────────────────
# Textes d'aide
# ─────────────────────────────────────────────

_HELP_TEXT = """\
mule v1.3 — Gestionnaire de fichiers distants R-ECO3
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