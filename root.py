"""
root.py — Module de logging pour R-ECO3
Version : 1.0  |  Codename : Ant
"""

import os
import time
import datetime


# ─── helpers internes ────────────────────────────────────────────────────────

def _get_db():
    """Charge et retourne l'instance HiveFS partagée."""
    import core.trail as trail
    import core.hive  as hive
    return hive.HiveFS(str(trail.DB_FILE))


def _resolve_log_path(db, filename: str) -> str:
    """
    Résout le chemin absolu du fichier de log.
    Priorité :
      1. Le dossier cible stocké dans HiveFS  (§sys:root:target_dir)
      2. ROOT / "logs"  comme fallback
    """
    import core.trail as trail

    target_dir = db.get("§sys:root:target_dir", as_str=True)
    if not target_dir:
        target_dir = str(trail.ROOT / "logs")

    os.makedirs(target_dir, exist_ok=True)
    return os.path.join(target_dir, filename)


def _write_entry(path: str, mode_flag: str, line: str):
    """Écrit une ligne dans le fichier selon le mode."""
    with open(path, mode_flag, encoding="utf-8") as f:
        f.write(line + "\n")


def _fmt_timestamp() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _get_mode(db) -> str:
    """Retourne le mode actuel stocké en HiveFS (défaut : append)."""
    mode = db.get("§sys:root:mode", as_str=True)
    return mode if mode in ("append", "overwrite", "new") else "append"


def _get_filename(db) -> str:
    """Retourne le nom de fichier actuel stocké en HiveFS (défaut : reco.log)."""
    name = db.get("§sys:root:filename", as_str=True)
    return name if name else "reco.log"


def _effective_path(db) -> str:
    """Retourne le chemin effectif du fichier de log selon le mode."""
    mode     = _get_mode(db)
    filename = _get_filename(db)

    if mode == "new":
        # Génère un nom unique horodaté  →  reco_20250615_143012.log
        base, ext = os.path.splitext(filename)
        ts       = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{base}_{ts}{ext}"

    return _resolve_log_path(db, filename)


# ─── sous-commandes ──────────────────────────────────────────────────────────

def _cmd_write(tokens: list, log_fn):
    """
    root write [--file=NAME] [--level=INFO|WARN|ERROR] <message...>
    Écrit une entrée dans le fichier de log courant.
    """
    import core.utils as utils

    positional, kv = utils.parse_command(" ".join(tokens))
    message = " ".join(positional)

    if not message:
        log_fn("[root] write : message vide, rien à écrire.")
        return 1

    level = str((kv.get("level") or "INFO")).upper()
    ts    = _fmt_timestamp()
    line  = f"[{ts}] [{level}] {message}"

    db        = _get_db()
    mode      = _get_mode(db)
    file_path = _effective_path(db)

    # Détermine le flag d'ouverture
    if mode == "overwrite":
        flag = "w"
        # On repasse en append pour les écritures suivantes dans la même session
        # (on n'écrase que la première fois par commande write)
    else:
        flag = "a"

    _write_entry(file_path, flag, line)
    log_fn(f"[root] → {file_path}  ({mode})  {line}")
    db.close()
    return 0


def _cmd_set_dir(tokens: list, log_fn):
    """
    root set_dir <chemin>
    Définit le dossier cible pour les fichiers de log.
    """
    if not tokens:
        log_fn("[root] set_dir : chemin manquant.")
        return 1

    path = tokens[0]
    path = os.path.expanduser(path)
    path = os.path.abspath(path)

    try:
        os.makedirs(path, exist_ok=True)
    except OSError as exc:
        log_fn(f"[root] set_dir : impossible de créer {path} — {exc}")
        return 1

    db = _get_db()
    db.set("§sys:root:target_dir", path)
    db.close()
    log_fn(f"[root] Dossier cible défini → {path}")
    return 0


def _cmd_set_mode(tokens: list, log_fn):
    """
    root set_mode <append|overwrite|new>
      append    — ajoute à la suite du fichier existant  (défaut)
      overwrite — écrase le fichier à chaque write
      new       — crée un nouveau fichier horodaté à chaque write
    """
    valid = ("append", "overwrite", "new")
    if not tokens or tokens[0] not in valid:
        log_fn(f"[root] set_mode : mode invalide. Valeurs : {', '.join(valid)}")
        return 1

    db = _get_db()
    db.set("§sys:root:mode", tokens[0])
    db.close()
    log_fn(f"[root] Mode défini → {tokens[0]}")
    return 0


def _cmd_set_file(tokens: list, log_fn):
    """
    root set_file <nom_fichier>
    Définit le nom du fichier de log (ex. : app.log, debug.log).
    """
    if not tokens:
        log_fn("[root] set_file : nom de fichier manquant.")
        return 1

    name = tokens[0]
    db   = _get_db()
    db.set("§sys:root:filename", name)
    db.close()
    log_fn(f"[root] Fichier défini → {name}")
    return 0


def _cmd_status(log_fn):
    """
    root status
    Affiche la configuration active du root.
    """
    db        = _get_db()
    mode      = _get_mode(db)
    filename  = _get_filename(db)
    target    = db.get("§sys:root:target_dir", as_str=True) or "(défaut : ROOT/logs)"
    db.close()

    log_fn("─" * 48)
    log_fn("  root — configuration active")
    log_fn("─" * 48)
    log_fn(f"  Mode        : {mode}")
    log_fn(f"  Fichier     : {filename}")
    log_fn(f"  Dossier     : {target}")
    log_fn("─" * 48)
    return 0


def _cmd_show(tokens: list, log_fn):
    """
    root show [--file=NAME] [--lines=N]
    Affiche les N dernières lignes du fichier de log courant (défaut : 20).
    """
    import core.utils as utils

    _, kv     = utils.parse_command(" ".join(tokens))
    db        = _get_db()

    filename  = kv.get("file") or _get_filename(db)
    n_lines   = int(kv.get("lines") or 20)
    file_path = _resolve_log_path(db, filename)
    db.close()

    if not os.path.exists(file_path):
        log_fn(f"[root] show : fichier introuvable — {file_path}")
        return 1

    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    tail = lines[-n_lines:]
    log_fn(f"─── {file_path}  (dernières {len(tail)} lignes) ───")
    for line in tail:
        log_fn(line.rstrip())
    return 0


def _cmd_clear(tokens: list, log_fn):
    """
    root clear [--file=NAME]
    Vide le contenu du fichier de log sans le supprimer.
    """
    import core.utils as utils

    _, kv     = utils.parse_command(" ".join(tokens))
    db        = _get_db()
    filename  = kv.get("file") or _get_filename(db)
    file_path = _resolve_log_path(db, filename)
    db.close()

    open(file_path, "w", encoding="utf-8").close()
    log_fn(f"[root] Fichier vidé → {file_path}")
    return 0


def _cmd_list(log_fn):
    """
    root list
    Liste les fichiers de log présents dans le dossier cible.
    """
    import core.trail as trail

    db         = _get_db()
    target_dir = db.get("§sys:root:target_dir", as_str=True) or str(trail.ROOT / "logs")
    db.close()

    if not os.path.isdir(target_dir):
        log_fn(f"[root] Dossier introuvable : {target_dir}")
        return 1

    files = sorted(
        f for f in os.listdir(target_dir)
        if os.path.isfile(os.path.join(target_dir, f))
    )

    if not files:
        log_fn(f"[root] Aucun fichier dans {target_dir}")
        return 0

    log_fn(f"─── Fichiers de log dans {target_dir} ───")
    for fname in files:
        full  = os.path.join(target_dir, fname)
        size  = os.path.getsize(full)
        mtime = datetime.datetime.fromtimestamp(os.path.getmtime(full)).strftime("%Y-%m-%d %H:%M")
        log_fn(f"  {fname:<35}  {size:>8} o   {mtime}")
    return 0


# ─── point d'entrée R-ECO3 ───────────────────────────────────────────────────

def R_ECO3(inp):
    """
    root <sous-commande> [options]

    Sous-commandes :
      write    [--level=INFO|WARN|ERROR] <message>  Écrit une entrée de log
      set_dir  <chemin>                             Dossier cible des fichiers
      set_file <nom>                                Nom du fichier de log
      set_mode <append|overwrite|new>               Mode d'écriture
      status                                        Affiche la config active
      show     [--file=NAME] [--lines=N]            Affiche les dernières lignes
      clear    [--file=NAME]                        Vide un fichier de log
      list                                          Liste les fichiers de log
    """
    import core.utils as utils
    
    args = inp["args"]
    log_fn = inp["logfn"]

    tokens = utils.tokenize(args.strip()) if args.strip() else []

    if not tokens:
        log_fn(R_ECO3.__doc__)
        return 0

    subcmd, *rest = tokens

    dispatch = {
        "write":    lambda: _cmd_write(rest, log_fn),
        "set_dir":  lambda: _cmd_set_dir(rest, log_fn),
        "set_file": lambda: _cmd_set_file(rest, log_fn),
        "set_mode": lambda: _cmd_set_mode(rest, log_fn),
        "status":   lambda: _cmd_status(log_fn),
        "show":     lambda: _cmd_show(rest, log_fn),
        "clear":    lambda: _cmd_clear(rest, log_fn),
        "list":     lambda: _cmd_list(log_fn),
    }

    if subcmd not in dispatch:
        log_fn(f"[root] Sous-commande inconnue : '{subcmd}'")
        log_fn("  Commandes disponibles : " + ", ".join(dispatch.keys()))
        return 1

    return dispatch[subcmd]()


# ─── métadonnées R-ECO3 ──────────────────────────────────────────────────────

def R_ECO3dep():
    return {
        "reco": ["3.5.1b"],
        "module": [],
    }


def R_ECO3inf():
    return {
        "name":        "root",
        "desc":        "Logging fichier configurable (append / overwrite / new)",
        "help":        (
            "root write [--level=INFO|WARN|ERROR] <msg>\n"
            "root set_dir <chemin> | set_file <nom> | set_mode <append|overwrite|new>\n"
            "root status | show [--lines=N] | clear | list"
        ),
        "version_mod": "1.0",
        "L2Module":    True,
        "manual": (
            "root — module de logging R-ECO3\n"
            "══════════════════════════════════════════════════════\n\n"
            "DESCRIPTION\n"
            "  Écrit des messages horodatés dans un fichier texte.\n"
            "  Le dossier, le nom et le mode d'écriture sont\n"
            "  persistés dans HiveFS.\n\n"
            "MODES D'ÉCRITURE\n"
            "  append    Ajoute chaque entrée à la suite du fichier\n"
            "            existant. Rien n'est perdu entre les sessions.\n"
            "            C'est le mode par défaut.\n\n"
            "  overwrite Écrase le fichier à chaque commande write.\n"
            "            Utile pour un journal 'live' que l'on relit\n"
            "            souvent depuis le début.\n\n"
            "  new       Crée un nouveau fichier horodaté\n"
            "            (ex. reco_20250615_143012.log) à chaque write.\n"
            "            Idéal pour garder une trace par session.\n\n"
            "CONFIGURATION\n"
            "  Clés HiveFS :\n"
            "    §sys:root:target_dir  — dossier cible (défaut ROOT/logs)\n"
            "    §sys:root:filename    — nom de fichier (défaut reco.log)\n"
            "    §sys:root:mode        — mode d'écriture (défaut append)\n\n"
            "COMMANDES\n"
            "  root write [--level=INFO|WARN|ERROR] <message>\n"
            "      Écrit une entrée. Niveaux : INFO (défaut), WARN, ERROR.\n\n"
            "  root set_dir <chemin>\n"
            "      Définit le dossier de destination. Le crée si absent.\n\n"
            "  root set_file <nom>\n"
            "      Définit le nom du fichier (ex. : app.log).\n\n"
            "  root set_mode <append|overwrite|new>\n"
            "      Change le mode d'écriture.\n\n"
            "  root status\n"
            "      Affiche la configuration active.\n\n"
            "  root show [--file=NAME] [--lines=N]\n"
            "      Affiche les N dernières lignes (défaut 20).\n\n"
            "  root clear [--file=NAME]\n"
            "      Vide le contenu du fichier sans le supprimer.\n\n"
            "  root list\n"
            "      Liste tous les fichiers de log dans le dossier cible.\n\n"
            "EXEMPLES\n"
            "  root set_dir /var/log/reco\n"
            "  root set_file app.log\n"
            "  root set_mode append\n"
            "  root write --level=INFO Démarrage du module raven\n"
            "  root write --level=ERROR Echec connexion base de données\n"
            "  root show --lines=50\n"
            "  root list\n"
        ),
    }