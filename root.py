# root.py — R-ECO3 Module
# Logging system with .root file support and HiveFS append-only log store
# Version: 1.0 | Codename: Ant

import os
import sys
import time
import json
import hashlib
from pathlib import Path
from datetime import datetime, timezone


# ──────────────────────────────────────────────
#  Module convention helpers
# ──────────────────────────────────────────────

def R_ECO3dep():
    return (
        ("3.5.1b",),
        (
            ("core.hive", ("1.2",)),
            ("core.apix",  ("1.1",)),
            ("core.utils", ("1.1",)),
            ("core.trail", ("1.0",)),
        )
    )


def R_ECO3inf():
    return {
        "name":        "root",
        "desc":        "Append-only logger with .root file support and HiveFS storage",
        "help":        (
            "root log <level> <message> [--tag=T] [--caller=C]\n"
            "root read [--n=50] [--level=L] [--tag=T] [--caller=C]\n"
            "root export [--file=path.root] [--level=L] [--tag=T]\n"
            "root import <file.root>\n"
            "root purge [--level=L] [--tag=T] [--before=ISO]\n"
            "root stats\n"
            "root tail [--n=20] [--level=L]\n"
            "root grep <pattern> [--n=50]\n"
            "root levels\n"
            "root clear\n"
            "root help"
        ),
        "version_mod": "1.0",
        "L2Module":    True,
        "manual": """
ROOT — Système de logging R-ECO3
=================================

root est un module de journalisation append-only qui stocke les entrées
de log dans HiveFS (§sys:root:log:<id>) et permet de les exporter/importer
au format .root (JSON-lines chiffré-compatible).

NIVEAUX DE LOG (par ordre croissant de sévérité) :
  DEBUG < INFO < SUCCESS < WARNING < ERROR < CRITICAL

COMMANDES :

  log <level> <message> [options]
      Enregistre une entrée de log.
      Options :
        --tag=T       tag libre pour filtrer (ex : "auth", "boot", "network")
        --caller=C    nom de l'appelant (ex : "raven", "mycelium")

  read [options]
      Lit et affiche les entrées stockées en HiveFS.
      Options :
        --n=N         nombre max d'entrées (défaut : 50)
        --level=L     filtre sur le niveau exact (DEBUG/INFO/…)
        --tag=T       filtre sur le tag
        --caller=C    filtre sur l'appelant

  tail [options]
      Affiche en continu les N dernières entrées (snapshot, pas de follow).
      Options :
        --n=N         nombre d'entrées (défaut : 20)
        --level=L     filtre niveau

  grep <pattern> [options]
      Recherche une sous-chaîne dans les messages.
      Options :
        --n=N         limite de résultats (défaut : 50)

  export [options]
      Exporte les logs HiveFS vers un fichier .root (JSON-lines).
      Options :
        --file=path   chemin de sortie (défaut : root_<timestamp>.root)
        --level=L     filtre niveau
        --tag=T       filtre tag

  import <file.root>
      Importe un fichier .root dans HiveFS (dédoublonnage par id).

  purge [options]
      Supprime des entrées sélectives de HiveFS.
      Options :
        --level=L     supprime seulement ce niveau
        --tag=T       supprime seulement ce tag
        --before=ISO  supprime les entrées antérieures à la date ISO 8601

  stats
      Affiche des statistiques agrégées (total, par niveau, par tag, par appelant).

  levels
      Liste les niveaux disponibles avec leur code couleur.

  clear
      Supprime TOUTES les entrées de log en HiveFS (irréversible).

  help
      Affiche ce manuel.

FORMAT .root :
  Fichier JSON-lines, une entrée par ligne.
  En-tête ligne 0 : {"__root__": true, "version": "1.0", "exported_at": "..."}
  Lignes 1+ :
    {
      "id":        "<sha256[:16] du contenu>",
      "ts":        "<ISO 8601 UTC>",
      "ts_unix":   1234567890.123,
      "level":     "INFO",
      "level_n":   2,
      "message":   "...",
      "tag":       "...",
      "caller":    "...",
    }

CLÉS HIVEFS :
  §sys:root:log:<id>       → JSON de l'entrée
  §sys:root:index          → liste des ids séparés par |
  §sys:root:counter        → compteur total d'entrées écrites
""",
    }


# ──────────────────────────────────────────────
#  Constantes internes
# ──────────────────────────────────────────────

_ROOT_VERSION  = "1.0"
_ROOT_MAGIC    = "__root__"
_INDEX_KEY     = "§sys:root:index"
_COUNTER_KEY   = "§sys:root:counter"
_LOG_PREFIX    = "§sys:root:log:"
_SEP           = "|"

# Niveaux : nom → (numéro, style ANSI)
_LEVELS = {
    "DEBUG":    (0, "\033[90m"),    # gris
    "INFO":     (1, "\033[36m"),    # cyan
    "SUCCESS":  (2, "\033[32m"),    # vert
    "WARNING":  (3, "\033[33m"),    # jaune
    "ERROR":    (4, "\033[31m"),    # rouge
    "CRITICAL": (5, "\033[1;31m"),  # rouge gras
}
_RESET = "\033[0m"

_LEVEL_NAMES  = list(_LEVELS.keys())
_LEVEL_NUMS   = {v[0]: k for k, v in _LEVELS.items()}


# ──────────────────────────────────────────────
#  Bootstrap noyau (chargement dynamique)
# ──────────────────────────────────────────────

def _load_core():
    """Charge core.apix via importlib si pas encore dans sys.modules."""
    if "core.apix" in sys.modules:
        return sys.modules["core.apix"]
    # Chemin : root.py est dans modules/, core/ est au même niveau
    here   = Path(__file__).resolve().parent
    root   = here.parent
    apix_p = root / "core" / "apix.py"
    import importlib.util
    spec = importlib.util.spec_from_file_location("core.apix", str(apix_p))
    mod  = importlib.util.module_from_spec(spec)
    sys.modules["core.apix"] = mod
    spec.loader.exec_module(mod)
    return mod


def _get_db():
    """Retourne l'instance HiveFS (via core.hive)."""
    apix = _load_core()
    # core.apix expose la db via le chemin trail
    import importlib.util
    here   = Path(__file__).resolve().parent
    root_p = here.parent

    for mod_name, rel in (("core.trail", "core/trail.py"), ("core.hive", "core/hive.py")):
        if mod_name not in sys.modules:
            p    = root_p / rel
            spec = importlib.util.spec_from_file_location(mod_name, str(p))
            m    = importlib.util.module_from_spec(spec)
            sys.modules[mod_name] = m
            spec.loader.exec_module(m)

    trail = sys.modules["core.trail"]
    hive  = sys.modules["core.hive"]
    return hive.HiveFS(str(trail.DB_FILE))


# ──────────────────────────────────────────────
#  API interne : HiveFS index
# ──────────────────────────────────────────────

def _read_index(db) -> list:
    raw = db.get(_INDEX_KEY, as_str=True)
    if not raw:
        return []
    return [x for x in raw.split(_SEP) if x]


def _write_index(db, ids: list):
    db.set(_INDEX_KEY, _SEP.join(ids))


def _increment_counter(db):
    val = db.get(_COUNTER_KEY, as_str=True)
    n   = int(val) + 1 if val else 1
    db.set(_COUNTER_KEY, str(n))
    return n


# ──────────────────────────────────────────────
#  API publique Python (importable par d'autres modules)
# ──────────────────────────────────────────────

def write_log(level: str, message: str, tag: str = "", caller: str = "", db=None) -> dict:
    """
    Écrit une entrée de log en HiveFS.

    Paramètres :
        level   : niveau parmi DEBUG / INFO / SUCCESS / WARNING / ERROR / CRITICAL
        message : texte du log
        tag     : tag libre (ex. "auth", "boot")
        caller  : nom du module appelant
        db      : instance HiveFS optionnelle (créée si absent)

    Retourne :
        dict avec les champs de l'entrée, ou {} si niveau inconnu.
    """
    level = level.upper()
    if level not in _LEVELS:
        return {}

    own_db = db is None
    if own_db:
        db = _get_db()

    try:
        ts_unix = time.time()
        ts      = datetime.fromtimestamp(ts_unix, tz=timezone.utc).isoformat()
        raw     = f"{ts}:{level}:{tag}:{caller}:{message}"
        entry_id = hashlib.sha256(raw.encode()).hexdigest()[:16]

        entry = {
            "id":       entry_id,
            "ts":       ts,
            "ts_unix":  ts_unix,
            "level":    level,
            "level_n":  _LEVELS[level][0],
            "message":  message,
            "tag":      tag,
            "caller":   caller,
        }

        # Ne pas dupliquer (idempotent)
        existing_ids = _read_index(db)
        if entry_id not in existing_ids:
            db.set(_LOG_PREFIX + entry_id, json.dumps(entry))
            existing_ids.append(entry_id)
            _write_index(db, existing_ids)
            _increment_counter(db)

        return entry
    finally:
        if own_db:
            db.close()


def read_logs(n: int = 50, level: str = None, tag: str = None,
              caller: str = None, db=None) -> list:
    """
    Lit les entrées de log depuis HiveFS.

    Paramètres :
        n      : nombre max d'entrées retournées (les plus récentes)
        level  : filtre exact sur le niveau (None = tous)
        tag    : filtre exact sur le tag (None = tous)
        caller : filtre exact sur le caller (None = tous)
        db     : instance HiveFS optionnelle

    Retourne :
        list[dict] triée du plus ancien au plus récent.
    """
    own_db = db is None
    if own_db:
        db = _get_db()

    try:
        ids     = _read_index(db)
        entries = []
        for eid in ids:
            raw = db.get(_LOG_PREFIX + eid, as_str=True)
            if not raw:
                continue
            try:
                e = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if level  and e.get("level")  != level.upper():
                continue
            if tag     and e.get("tag")    != tag:
                continue
            if caller  and e.get("caller") != caller:
                continue
            entries.append(e)

        # Tri chronologique, on retourne les N dernières
        entries.sort(key=lambda x: x.get("ts_unix", 0))
        return entries[-n:]
    finally:
        if own_db:
            db.close()


def grep_logs(pattern: str, n: int = 50, db=None) -> list:
    """Cherche pattern (sous-chaîne) dans les messages de log."""
    all_entries = read_logs(n=10_000, db=db)
    results = [e for e in all_entries if pattern.lower() in e.get("message", "").lower()]
    return results[-n:]


def export_root(filepath: str, level: str = None, tag: str = None, db=None) -> int:
    """
    Exporte les logs vers un fichier .root (JSON-lines).

    Retourne le nombre d'entrées exportées.
    """
    entries = read_logs(n=100_000, level=level, tag=tag, db=db)
    header  = {
        _ROOT_MAGIC: True,
        "version":     _ROOT_VERSION,
        "exported_at": datetime.now(tz=timezone.utc).isoformat(),
        "count":       len(entries),
    }
    with open(filepath, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(header) + "\n")
        for e in entries:
            fh.write(json.dumps(e) + "\n")
    return len(entries)


def import_root(filepath: str, db=None) -> tuple:
    """
    Importe un fichier .root dans HiveFS.

    Retourne (importés, doublons, erreurs).
    """
    own_db = db is None
    if own_db:
        db = _get_db()

    imported = duplicates = errors = 0
    try:
        with open(filepath, "r", encoding="utf-8") as fh:
            lines = fh.readlines()

        if not lines:
            return 0, 0, 0

        # Valider l'en-tête
        try:
            header = json.loads(lines[0])
            if not header.get(_ROOT_MAGIC):
                raise ValueError("magic manquant")
        except (json.JSONDecodeError, ValueError):
            return 0, 0, 1

        existing_ids = _read_index(db)

        for line in lines[1:]:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
                eid = e.get("id")
                if not eid:
                    errors += 1
                    continue
                if eid in existing_ids:
                    duplicates += 1
                    continue
                db.set(_LOG_PREFIX + eid, json.dumps(e))
                existing_ids.append(eid)
                imported += 1
            except json.JSONDecodeError:
                errors += 1

        _write_index(db, existing_ids)
        if imported:
            val = db.get(_COUNTER_KEY, as_str=True)
            n   = (int(val) if val else 0) + imported
            db.set(_COUNTER_KEY, str(n))

        return imported, duplicates, errors
    finally:
        if own_db:
            db.close()


def purge_logs(level: str = None, tag: str = None,
               before_iso: str = None, db=None) -> int:
    """
    Supprime des entrées sélectives de HiveFS.

    Retourne le nombre d'entrées supprimées.
    """
    own_db = db is None
    if own_db:
        db = _get_db()

    removed = 0
    try:
        before_ts = None
        if before_iso:
            try:
                before_ts = datetime.fromisoformat(before_iso).timestamp()
            except ValueError:
                return -1  # date invalide

        ids        = _read_index(db)
        kept_ids   = []

        for eid in ids:
            raw = db.get(_LOG_PREFIX + eid, as_str=True)
            if not raw:
                continue
            try:
                e = json.loads(raw)
            except json.JSONDecodeError:
                kept_ids.append(eid)
                continue

            should_remove = False
            if level  and e.get("level") == level.upper():
                should_remove = True
            if tag    and e.get("tag")   == tag:
                should_remove = True
            if before_ts and e.get("ts_unix", 0) < before_ts:
                should_remove = True

            # Si aucun filtre actif, ne rien supprimer
            if not level and not tag and not before_iso:
                should_remove = False

            if should_remove:
                db.delete(_LOG_PREFIX + eid)
                removed += 1
            else:
                kept_ids.append(eid)

        _write_index(db, kept_ids)
        return removed
    finally:
        if own_db:
            db.close()


def get_stats(db=None) -> dict:
    """
    Retourne des statistiques agrégées.

    Retourne un dict :
      total, by_level (dict), by_tag (dict), by_caller (dict),
      oldest_ts, newest_ts, counter_total
    """
    own_db = db is None
    if own_db:
        db = _get_db()

    try:
        ids      = _read_index(db)
        by_level  = {}
        by_tag    = {}
        by_caller = {}
        oldest    = None
        newest    = None

        for eid in ids:
            raw = db.get(_LOG_PREFIX + eid, as_str=True)
            if not raw:
                continue
            try:
                e = json.loads(raw)
            except json.JSONDecodeError:
                continue

            lv = e.get("level", "?")
            tg = e.get("tag", "") or "(none)"
            cl = e.get("caller", "") or "(none)"
            tu = e.get("ts_unix", 0)

            by_level[lv]   = by_level.get(lv, 0) + 1
            by_tag[tg]     = by_tag.get(tg, 0) + 1
            by_caller[cl]  = by_caller.get(cl, 0) + 1

            if oldest is None or tu < oldest:
                oldest = tu
            if newest is None or tu > newest:
                newest = tu

        counter_raw = db.get(_COUNTER_KEY, as_str=True)
        return {
            "total":         len(ids),
            "counter_total": int(counter_raw) if counter_raw else 0,
            "by_level":      by_level,
            "by_tag":        by_tag,
            "by_caller":     by_caller,
            "oldest_ts":     oldest,
            "newest_ts":     newest,
        }
    finally:
        if own_db:
            db.close()


def clear_all_logs(db=None) -> int:
    """Supprime TOUTES les entrées de log. Retourne le nombre supprimé."""
    own_db = db is None
    if own_db:
        db = _get_db()

    try:
        ids = _read_index(db)
        for eid in ids:
            db.delete(_LOG_PREFIX + eid)
        db.delete(_INDEX_KEY)
        db.delete(_COUNTER_KEY)
        return len(ids)
    finally:
        if own_db:
            db.close()


# ──────────────────────────────────────────────
#  Raccourcis niveau (API fluide)
# ──────────────────────────────────────────────

def debug(msg, tag="", caller="",    db=None): return write_log("DEBUG",    msg, tag, caller, db)
def info(msg, tag="", caller="",     db=None): return write_log("INFO",     msg, tag, caller, db)
def success(msg, tag="", caller="",  db=None): return write_log("SUCCESS",  msg, tag, caller, db)
def warning(msg, tag="", caller="",  db=None): return write_log("WARNING",  msg, tag, caller, db)
def error(msg, tag="", caller="",    db=None): return write_log("ERROR",    msg, tag, caller, db)
def critical(msg, tag="", caller="", db=None): return write_log("CRITICAL", msg, tag, caller, db)


# ──────────────────────────────────────────────
#  Rendu CLI
# ──────────────────────────────────────────────

def _colorize(level: str, text: str) -> str:
    ansi = _LEVELS.get(level, ("", ""))[1]
    return f"{ansi}{text}{_RESET}"


def _fmt_entry(e: dict) -> str:
    """Formate une entrée pour l'affichage terminal."""
    ts      = e.get("ts", "?")[:19].replace("T", " ")
    level   = e.get("level", "?")
    msg     = e.get("message", "")
    tag     = e.get("tag", "")
    caller  = e.get("caller", "")

    parts = [f"[{ts}]", _colorize(level, f"[{level:<8}]"), msg]
    if tag:
        parts.append(_colorize("\033[35m", f"#{tag}"))   # magenta
    if caller:
        parts.append(f"({caller})")
    return "  ".join(parts)


def _display_entries(entries: list, log_fn):
    if not entries:
        log_fn("  (aucune entrée)")
        return
    for e in entries:
        log_fn(_fmt_entry(e))


# ──────────────────────────────────────────────
#  Point d'entrée R_ECO3
# ──────────────────────────────────────────────

def R_ECO3(args: str, log_fn=print):
    # Import utils pour parser les arguments
    try:
        apix = _load_core()
        # Charger core.utils
        import importlib.util as ilu
        here   = Path(__file__).resolve().parent
        root_p = here.parent
        if "core.utils" not in sys.modules:
            p    = root_p / "core" / "utils.py"
            spec = ilu.spec_from_file_location("core.utils", str(p))
            m    = ilu.module_from_spec(spec)
            sys.modules["core.utils"] = m
            spec.loader.exec_module(m)
        utils = sys.modules["core.utils"]
        positional, kv = utils.parse_command(args)
    except Exception as exc:
        # Fallback parsing minimal si utils non disponible
        positional = args.split()
        kv = {}

    if not positional:
        log_fn(R_ECO3inf()["help"])
        return 0

    cmd = positional[0].lower()

    # ── log ─────────────────────────────────────────────────────────────
    if cmd == "log":
        if len(positional) < 3:
            log_fn("Usage : root log <level> <message> [--tag=T] [--caller=C]")
            return 1
        level   = positional[1].upper()
        message = " ".join(positional[2:])
        tag     = kv.get("tag", "")
        caller  = kv.get("caller", "")
        if level not in _LEVELS:
            log_fn(f"Niveau inconnu : {level}. Valides : {', '.join(_LEVEL_NAMES)}")
            return 1
        entry = write_log(level, message, tag=tag, caller=caller)
        log_fn(_fmt_entry(entry))
        return 0

    # ── read ─────────────────────────────────────────────────────────────
    elif cmd == "read":
        n      = int(kv.get("n", 50))
        level  = kv.get("level", None)
        tag    = kv.get("tag",   None)
        caller = kv.get("caller", None)
        if level:
            level = level.upper()
        entries = read_logs(n=n, level=level, tag=tag, caller=caller)
        log_fn(f"  ── {len(entries)} entrée(s) ──")
        _display_entries(entries, log_fn)
        return 0

    # ── tail ─────────────────────────────────────────────────────────────
    elif cmd == "tail":
        n     = int(kv.get("n", 20))
        level = kv.get("level", None)
        if level:
            level = level.upper()
        entries = read_logs(n=n, level=level)
        log_fn(f"  ── tail {n} ──")
        _display_entries(entries, log_fn)
        return 0

    # ── grep ─────────────────────────────────────────────────────────────
    elif cmd == "grep":
        if len(positional) < 2:
            log_fn("Usage : root grep <pattern> [--n=50]")
            return 1
        pattern = positional[1]
        n       = int(kv.get("n", 50))
        entries = grep_logs(pattern=pattern, n=n)
        log_fn(f"  ── {len(entries)} résultat(s) pour '{pattern}' ──")
        _display_entries(entries, log_fn)
        return 0

    # ── export ───────────────────────────────────────────────────────────
    elif cmd == "export":
        level = kv.get("level", None)
        tag   = kv.get("tag",   None)
        if level:
            level = level.upper()
        ts_str   = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = kv.get("file", f"root_{ts_str}.root")
        try:
            count = export_root(filepath, level=level, tag=tag)
            log_fn(f"  Export OK → {filepath}  ({count} entrée(s))")
            return 0
        except OSError as exc:
            log_fn(f"  Erreur export : {exc}")
            return 1

    # ── import ───────────────────────────────────────────────────────────
    elif cmd == "import":
        if len(positional) < 2:
            log_fn("Usage : root import <file.root>")
            return 1
        filepath = positional[1]
        if not os.path.isfile(filepath):
            log_fn(f"  Fichier introuvable : {filepath}")
            return 1
        ok, dup, err = import_root(filepath)
        log_fn(f"  Import terminé : {ok} importé(s), {dup} doublon(s), {err} erreur(s)")
        return 0 if err == 0 else 1

    # ── purge ─────────────────────────────────────────────────────────────
    elif cmd == "purge":
        level  = kv.get("level", None)
        tag    = kv.get("tag",   None)
        before = kv.get("before", None)
        if level:
            level = level.upper()
        if not level and not tag and not before:
            log_fn("  Aucun filtre spécifié. Utilisez --level, --tag ou --before=ISO.")
            log_fn("  Pour tout supprimer, utilisez : root clear")
            return 1
        n = purge_logs(level=level, tag=tag, before_iso=before)
        if n == -1:
            log_fn("  Date --before invalide (format attendu : ISO 8601, ex. 2025-01-01T00:00:00)")
            return 1
        log_fn(f"  {n} entrée(s) supprimée(s)")
        return 0

    # ── stats ─────────────────────────────────────────────────────────────
    elif cmd == "stats":
        st = get_stats()
        log_fn(f"  Total en base   : {st['total']} entrée(s)")
        log_fn(f"  Total historique: {st['counter_total']} (compteur incrémental)")

        if st["oldest_ts"]:
            oldest = datetime.fromtimestamp(st["oldest_ts"]).strftime("%Y-%m-%d %H:%M:%S")
            newest = datetime.fromtimestamp(st["newest_ts"]).strftime("%Y-%m-%d %H:%M:%S")
            log_fn(f"  Plage           : {oldest} → {newest}")

        if st["by_level"]:
            log_fn("  Par niveau :")
            for lv in _LEVEL_NAMES:
                count = st["by_level"].get(lv, 0)
                if count:
                    log_fn(f"    {_colorize(lv, f'{lv:<10}')} {count}")

        if st["by_tag"] and list(st["by_tag"].keys()) != ["(none)"]:
            log_fn("  Par tag :")
            for tg, cnt in sorted(st["by_tag"].items(), key=lambda x: -x[1]):
                if tg != "(none)":
                    log_fn(f"    #{tg:<20} {cnt}")

        if st["by_caller"] and list(st["by_caller"].keys()) != ["(none)"]:
            log_fn("  Par appelant :")
            for cl, cnt in sorted(st["by_caller"].items(), key=lambda x: -x[1]):
                if cl != "(none)":
                    log_fn(f"    {cl:<22} {cnt}")
        return 0

    # ── levels ────────────────────────────────────────────────────────────
    elif cmd == "levels":
        log_fn("  Niveaux disponibles (du moins au plus sévère) :")
        for name, (num, _) in _LEVELS.items():
            log_fn(f"    {num}  {_colorize(name, f'{name:<10}')}  level_n={num}")
        return 0

    # ── clear ─────────────────────────────────────────────────────────────
    elif cmd == "clear":
        n = clear_all_logs()
        log_fn(f"  {n} entrée(s) supprimée(s). Base de logs vidée.")
        return 0

    # ── help ──────────────────────────────────────────────────────────────
    elif cmd in ("help", "--help", "-h"):
        log_fn(R_ECO3inf()["manual"])
        return 0

    else:
        log_fn(f"  Commande inconnue : '{cmd}'")
        log_fn(f"  Commandes : log, read, tail, grep, export, import, purge, stats, levels, clear, help")
        return 1