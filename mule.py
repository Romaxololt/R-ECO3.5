# mule.py — Module R-ECO3
# Gestionnaire de fichiers distants via GitHub raw
# Base URL : https://raw.githubusercontent.com/Romaxololt/R-ECO3.5/main/

_VERSION = "1.0"
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
    """Retourne la liste des fichiers installés."""
    raw = db.get(_DB_KEY_LIST, as_str=True)
    if not raw:
        return []
    return [f for f in raw.split(_SEP) if f]


def _save_installed(db, lst: list):
    db.set(_DB_KEY_LIST, _SEP.join(lst))


def _fetch_file(filename: str, log_fn) -> tuple:
    import core.apix as apix
    url = _BASE_URL + filename
    lines = []
    def _capture(msg=""):
        lines.append(str(msg))

    code, ret = apix.R_ECO3(f'run vine {url} --no-status', log_fn=_capture)
    
    # DEBUG — à retirer après
    log_fn(f"[mule:debug] code={code} ret={ret} lines={lines[:3]}")
    
    if code != 0:
        return 1, f"Erreur réseau pour '{filename}'"

    content = "\n".join(lines)
    if not content.strip():
        return 1, f"Réponse vide pour '{filename}'"

    if "404: Not Found" in content or content.strip() == "404: Not Found":
        return 1, f"Fichier '{filename}' introuvable sur le dépôt (404)"

    return 0, content


def _write_file(filename: str, content: str, log_fn) -> bool:
    """Écrit le fichier dans modules/ (ou core/ si préfixe core.)."""
    import core.trail as trail
    import os

    if filename.startswith("core."):
        # core.utils → core/utils
        target_name = filename[5:]  # retire "core."
        target_dir = trail.ROOT / "core"
    else:
        target_name = filename
        target_dir = trail.MODULES_DIR

    target_path = target_dir / target_name

    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(content)
        return True
    except OSError as exc:
        log_fn(f"[mule] Erreur écriture '{target_path}': {exc}")
        return False


def _remove_file(filename: str, log_fn) -> bool:
    """Supprime le fichier depuis modules/ ou core/."""
    import core.trail as trail
    import os

    if filename.startswith("core."):
        target_name = filename[5:]
        target_path = trail.ROOT / "core" / target_name
    else:
        target_path = trail.MODULES_DIR / filename

    try:
        if target_path.exists():
            os.remove(target_path)
            return True
        else:
            log_fn(f"[mule] Fichier introuvable sur disque : '{target_path}'")
            return False
    except OSError as exc:
        log_fn(f"[mule] Erreur suppression '{target_path}': {exc}")
        return False


# ─────────────────────────────────────────────
# Commandes
# ─────────────────────────────────────────────

def _cmd_install(filename: str, log_fn) -> tuple:
    """mule install <fichier> — télécharge et installe un fichier distant."""
    db = _get_db()
    installed = _get_installed(db)
    import core.trail as trail

    if filename in installed:
        # Vérifier que le fichier existe vraiment sur disque
        if filename.startswith("core."):
            real_path = trail.ROOT / "core" / filename[5:]
        else:
            real_path = trail.MODULES_DIR / filename

        if real_path.exists():
            log_fn(f"[mule] '{filename}' est déjà installé. Utilisez 'mule update {filename}' pour mettre à jour.")
            db.close()
            return 0, None
        else:
            # Base désynchronisée — on nettoie et on réinstalle
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

    # Enregistrer en base
    installed.append(filename)
    _save_installed(db, installed)
    db.set(_DB_KEY_PREFIX + filename, _BASE_URL + filename)
    db.close()

    log_fn(f"[mule] ✓ '{filename}' installé avec succès.")
    return 0, None


def _cmd_uninstall(filename: str, log_fn) -> tuple:
    """mule desinstall <fichier> — supprime un fichier installé."""
    db = _get_db()
    installed = _get_installed(db)

    if filename not in installed:
        log_fn(f"[mule] '{filename}' n'est pas dans la liste des fichiers gérés par mule.")
        db.close()
        return 1, f"'{filename}' non installé"

    if not _remove_file(filename, log_fn):
        db.close()
        return 1, f"Échec de la suppression de '{filename}'"

    # Retirer de la base
    installed.remove(filename)
    _save_installed(db, installed)
    try:
        db.delete(_DB_KEY_PREFIX + filename)
    except Exception:
        pass
    db.close()

    log_fn(f"[mule] ✓ '{filename}' désinstallé.")
    return 0, None


def _cmd_list(log_fn) -> tuple:
    """mule list — affiche les fichiers installés via mule."""
    db = _get_db()
    installed = _get_installed(db)
    db.close()

    if not installed:
        log_fn("[mule] Aucun fichier installé via mule.")
        return 0, []

    log_fn(f"[mule] Fichiers installés ({len(installed)}) :")
    for fname in installed:
        log_fn(f"  • {fname}  →  {_BASE_URL}{fname}")
    return 0, installed


def _cmd_update(target: str, log_fn) -> tuple:
    """
    mule update <fichier>  — réinstalle un fichier depuis la source distante.
    mule update *          — met à jour tous les fichiers installés.
    """
    db = _get_db()
    installed = _get_installed(db)
    db.close()

    if not installed:
        log_fn("[mule] Aucun fichier installé via mule.")
        return 0, None

    if target == "*":
        targets = list(installed)
    else:
        if target not in installed:
            log_fn(f"[mule] '{target}' n'est pas géré par mule. Utilisez 'mule install {target}' d'abord.")
            return 1, f"'{target}' non installé"
        targets = [target]

    errors = []
    for fname in targets:
        log_fn(f"[mule] Mise à jour de '{fname}'...")
        code, content = _fetch_file(fname, log_fn)
        if code != 0:
            log_fn(f"[mule] ✗ {fname} : {content}")
            errors.append(fname)
            continue
        if not _write_file(fname, content, log_fn):
            log_fn(f"[mule] ✗ {fname} : échec écriture")
            errors.append(fname)
            continue
        log_fn(f"[mule] ✓ '{fname}' mis à jour.")

    if errors:
        log_fn(f"[mule] {len(errors)} erreur(s) : {', '.join(errors)}")
        return 1, errors

    log_fn(f"[mule] Mise à jour terminée ({len(targets)} fichier(s)).")
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
        mule list
        mule update <fichier>
        mule update *
    """
    import core.utils as utils

    positional, flags = utils.parse_command(args)

    if not positional:
        log_fn(_HELP_TEXT)
        return 0, None

    cmd = positional[0].lower()

    # ── install ──────────────────────────────
    if cmd == "install":
        if len(positional) < 2:
            log_fn("[mule] Usage : mule install <fichier>")
            return 1, "argument manquant"
        return _cmd_install(positional[1], log_fn)

    # ── desinstall / uninstall ────────────────
    elif cmd in ("desinstall", "uninstall"):
        if len(positional) < 2:
            log_fn("[mule] Usage : mule desinstall <fichier>")
            return 1, "argument manquant"
        return _cmd_uninstall(positional[1], log_fn)

    # ── list ─────────────────────────────────
    elif cmd == "list":
        return _cmd_list(log_fn)

    # ── update ───────────────────────────────
    elif cmd == "update":
        if len(positional) < 2:
            log_fn("[mule] Usage : mule update <fichier> | mule update *")
            return 1, "argument manquant"
        return _cmd_update(positional[1], log_fn)

    # ── aide ─────────────────────────────────
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
            ("vine",        ("1.0",)),
        )
    )


def R_ECO3inf() -> dict:
    return {
        "name":        "mule",
        "desc":        "Gestionnaire de fichiers distants (GitHub raw)",
        "help":        (
            "mule install <f>      Télécharge et installe un fichier depuis le dépôt distant\n"
            "mule desinstall <f>   Supprime un fichier installé via mule\n"
            "mule list             Liste les fichiers gérés par mule\n"
            "mule update <f>|*     Met à jour un fichier (ou tous avec *)"
        ),
        "version_mod": _VERSION,
        "L2Module":    True,
        "manual":      _MANUAL_TEXT,
    }


# ─────────────────────────────────────────────
# Textes d'aide
# ─────────────────────────────────────────────

_HELP_TEXT = """\
mule — Gestionnaire de fichiers distants R-ECO3
Base URL : https://raw.githubusercontent.com/Romaxololt/R-ECO3.5/main/

Commandes :
  mule install <fichier>      Télécharge et installe <fichier> depuis le dépôt
  mule desinstall <fichier>   Désinstalle <fichier> (supprime du disque + base)
  mule list                   Liste tous les fichiers installés via mule
  mule update <fichier>       Retélécharge et écrase <fichier>
  mule update *               Met à jour TOUS les fichiers installés

Résolution des chemins :
  fichier.py     → modules/fichier.py
  core.utils     → core/utils  (préfixe "core." détecté automatiquement)

Exemples :
  mule install test.py
  mule install core.utils
  mule list
  mule update test.py
  mule update *
  mule desinstall test.py
"""

_MANUAL_TEXT = """\
# mule — Manuel complet

## Description
mule est un gestionnaire de fichiers distants pour R-ECO3.
Il télécharge des fichiers depuis le dépôt GitHub :
  https://raw.githubusercontent.com/Romaxololt/R-ECO3.5/main/

Il utilise le module `vine` (client HTTP stdlib) pour toutes les
requêtes réseau, sans dépendances externes.

## Commandes

### mule install <fichier>
Télécharge <fichier> depuis le dépôt et l'écrit sur le disque.
Enregistre l'installation en base HiveFS pour le suivi.
Refuse si le fichier est déjà installé (utiliser `update` à la place).

### mule desinstall <fichier>
Supprime <fichier> du disque et retire son entrée de la base HiveFS.
Échoue si le fichier n'a pas été installé via mule.

### mule list
Affiche la liste des fichiers actuellement gérés par mule,
avec leur URL source.

### mule update <fichier>
Retélécharge <fichier> et écrase la version locale.
Utile pour récupérer les mises à jour du dépôt distant.

### mule update *
Retélécharge et écrase TOUS les fichiers installés via mule.
Les erreurs individuelles sont signalées sans interrompre le lot.

## Résolution des chemins
- `fichier.py`  → écrit dans `modules/fichier.py`
- `core.utils`  → écrit dans `core/utils`
  (tout nom commençant par "core." est dirigé vers le dossier core/)

## Clés HiveFS utilisées
  §sys:mule:list                  → liste des fichiers (séparateur interne)
  §sys:mule:installed:<fichier>   → URL source du fichier

## Dépendances
  core.utils, core.hive, core.apix, core.trail, vine

## Version
  mule v1.0 — R-ECO3 v3.5.1b (Ant)
"""