"""
tree.py — Gestionnaire de fichiers R-ECO3
Version : 1.0 · L2Module : True

Alias de commandes système (cd, ls, mkdir, ...) avec deux modes :
  - mode fs   : opérations sur le système de fichiers réel
  - mode hive : opérations sur la base HiveFS (clés §-préfixées, séparateur :)
"""

import os
import shutil
import pathlib
import fnmatch


# ─────────────────────────────────────────────────────────────
#  Constantes
# ─────────────────────────────────────────────────────────────

_VERSION   = "1.0"
_HIVE_SEP  = ":"
_HIVE_ROOT = "§"

# Clé HiveFS qui mémorise le répertoire courant de chaque mode
_KEY_CWD_FS   = "§_tree:cwd:fs"
_KEY_CWD_HIVE = "§_tree:cwd:hive"
_KEY_MODE     = "§_tree:mode"       # "fs" | "hive"


# ─────────────────────────────────────────────────────────────
#  Helpers génériques
# ─────────────────────────────────────────────────────────────

def _get_db():
    """Charge la base HiveFS via core.apix."""
    try:
        import core.apix as apix
        import core.trail as trail
        import core.hive as hive
        return hive.HiveFS(str(trail.DB_FILE))
    except Exception as e:
        raise RuntimeError(f"Impossible d'ouvrir HiveFS : {e}")


def _get_mode(db) -> str:
    return db.get(_KEY_MODE, as_str=True) or "fs"


def _get_cwd_fs(db) -> str:
    stored = db.get(_KEY_CWD_FS, as_str=True)
    if stored and os.path.isdir(stored):
        return stored
    return os.path.expanduser("~")


def _get_cwd_hive(db) -> str:
    stored = db.get(_KEY_CWD_HIVE, as_str=True)
    return stored if stored else _HIVE_ROOT


# ─────────────────────────────────────────────────────────────
#  Helpers HiveFS — manipulation de chemins de clés
# ─────────────────────────────────────────────────────────────

def _hive_segments(key: str) -> list:
    """
    Découpe une clé HiveFS en segments LOGIQUES pour la navigation.

    Le '§' est séparé du reste comme niveau racine implicite, ce qui
    permet à '..' depuis §sys de remonter correctement à §.

    Exemples :
        "§"               → ["§"]
        "§sys"            → ["§", "sys"]
        "§sys:user"       → ["§", "sys", "user"]
        "§version"        → ["§", "version"]
        "§sys:user:uid:x" → ["§", "sys", "user", "uid", "x"]
    """
    if not key or key == _HIVE_ROOT:
        return [_HIVE_ROOT]
    raw_parts = key.split(_HIVE_SEP)
    result = []
    for i, part in enumerate(raw_parts):
        if not part:
            continue
        if i == 0 and part.startswith(_HIVE_ROOT):
            result.append(_HIVE_ROOT)
            remainder = part[len(_HIVE_ROOT):]
            if remainder:
                result.append(remainder)
        else:
            result.append(part)
    return result if result else [_HIVE_ROOT]


def _hive_from_segments(segs: list) -> str:
    """
    Reconstruit une clé HiveFS réelle depuis ses segments logiques.

    ["§"]               → "§"
    ["§", "sys"]        → "§sys"
    ["§", "sys","user"] → "§sys:user"
    ["§", "version"]    → "§version"
    """
    if not segs:
        return _HIVE_ROOT
    result = segs[0]                       # "§"
    for part in segs[1:]:
        if result == _HIVE_ROOT:
            result = _HIVE_ROOT + part      # "§" + "sys" = "§sys"
        else:
            result = result + _HIVE_SEP + part
    return result


def _hive_abspath(cwd: str, path: str) -> str:
    """
    Résout un chemin HiveFS relatif ou absolu.

    Chemin absolu : commence par '§'  → utilisé tel quel.
    Chemin relatif : les segments sont appliqués sur cwd.
    '..' remonte d'un niveau logique ; depuis § on reste à §.

    Exemples (cwd = §sys:user) :
        "uid"          → §sys:user:uid
        "uid:42"       → §sys:user:uid:42
        ".."           → §sys
        "§sys:raven"   → §sys:raven   (absolu)
    Exemples (cwd = §sys) :
        ".."           → §
        "user"         → §sys:user
    Exemples (cwd = §) :
        "sys"          → §sys
        ".."           → §            (reste à la racine)
    """
    if path.startswith(_HIVE_ROOT):
        return _hive_from_segments(_hive_segments(path))
    base = _hive_segments(cwd)
    for part in path.split(_HIVE_SEP):
        if not part or part == ".":
            continue
        if part == "..":
            if len(base) > 1:
                base.pop()
        else:
            base.append(part)
    return _hive_from_segments(base)


def _hive_list_children(db, prefix: str) -> list:
    """
    Retourne les enfants DIRECTS d'un préfixe HiveFS (niveau +1 uniquement).

    Exemples :
        prefix=§           → [§reco_magic, §sys, §version]
        prefix=§sys        → [§sys:mycelium, §sys:raven, §sys:user]
        prefix=§sys:user   → [§sys:user:uid]

    La racine § reconstruit les clés de premier niveau depuis les segments logiques.
    """
    all_keys = db.list()
    norm     = _hive_from_segments(_hive_segments(prefix))
    children = set()

    for key in all_keys:
        if key == norm:
            continue
        if norm == _HIVE_ROOT:
            segs  = _hive_segments(key)
            if len(segs) >= 2:
                child = _hive_from_segments(segs[:2])  # "§sys"
            else:
                child = key
        else:
            expected = norm + _HIVE_SEP
            if not key.startswith(expected):
                continue
            rest     = key[len(expected):]
            next_seg = rest.split(_HIVE_SEP)[0]
            child    = norm + _HIVE_SEP + next_seg
        children.add(child)

    return sorted(children)


def _hive_is_leaf(db, key: str) -> bool:
    """Une clé est une feuille si elle a une valeur ET aucun enfant direct."""
    return db.exists(key) and not bool(_hive_list_children(db, key))


def _hive_basename(key: str) -> str:
    """Dernier segment logique d'une clé. '§sys:user:name' → 'name'."""
    segs = _hive_segments(key)
    return segs[-1] if segs else key


def _hive_parent(key: str) -> str:
    """Parent logique. '§sys:user' → '§sys', '§sys' → '§'."""
    segs = _hive_segments(key)
    if len(segs) <= 1:
        return _HIVE_ROOT
    return _hive_from_segments(segs[:-1])


# ─────────────────────────────────────────────────────────────
#  Commandes — Mode FS
# ─────────────────────────────────────────────────────────────

def _fs_cwd(db, log_fn):
    cwd = _get_cwd_fs(db)
    log_fn(cwd)
    return 0, cwd


def _fs_cd(db, args, log_fn):
    if not args:
        target = os.path.expanduser("~")
    else:
        target = args[0]
    cwd = _get_cwd_fs(db)
    new = os.path.normpath(os.path.join(cwd, target))
    if not os.path.isdir(new):
        log_fn(f"tree: cd: {new}: Dossier introuvable")
        return 1, f"Dossier introuvable : {new}"
    db.set(_KEY_CWD_FS, new)
    return 0, new


def _fs_ls(db, args, log_fn):
    cwd = _get_cwd_fs(db)
    target = os.path.normpath(os.path.join(cwd, args[0])) if args else cwd
    if not os.path.exists(target):
        log_fn(f"tree: ls: {target}: introuvable")
        return 1, "introuvable"
    entries = sorted(os.listdir(target)) if os.path.isdir(target) else [os.path.basename(target)]
    for entry in entries:
        full = os.path.join(target, entry)
        suffix = "/" if os.path.isdir(full) else ""
        log_fn(f"{entry}{suffix}")
    return 0, entries


def _fs_mkdir(db, args, log_fn):
    if not args:
        log_fn("tree: mkdir: argument manquant")
        return 1, "argument manquant"
    cwd = _get_cwd_fs(db)
    target = os.path.normpath(os.path.join(cwd, args[0]))
    try:
        os.makedirs(target, exist_ok=True)
        log_fn(f"Dossier créé : {target}")
        return 0, target
    except Exception as e:
        log_fn(f"tree: mkdir: {e}")
        return 1, str(e)


def _fs_rmdir(db, args, log_fn):
    if not args:
        log_fn("tree: rmdir: argument manquant")
        return 1, "argument manquant"
    cwd = _get_cwd_fs(db)
    target = os.path.normpath(os.path.join(cwd, args[0]))
    try:
        os.rmdir(target)
        log_fn(f"Dossier supprimé : {target}")
        return 0, target
    except Exception as e:
        log_fn(f"tree: rmdir: {e}")
        return 1, str(e)


def _fs_rm(db, args, log_fn):
    if not args:
        log_fn("tree: rm: argument manquant")
        return 1, "argument manquant"
    recursive = "-r" in args or "--recursive" in args
    targets = [a for a in args if not a.startswith("-")]
    cwd = _get_cwd_fs(db)
    for name in targets:
        path = os.path.normpath(os.path.join(cwd, name))
        try:
            if os.path.isdir(path):
                if recursive:
                    shutil.rmtree(path)
                    log_fn(f"Supprimé (récursif) : {path}")
                else:
                    log_fn(f"tree: rm: {path} est un dossier (utilisez -r)")
                    return 1, "dossier sans -r"
            else:
                os.remove(path)
                log_fn(f"Supprimé : {path}")
        except Exception as e:
            log_fn(f"tree: rm: {e}")
            return 1, str(e)
    return 0, None


def _fs_cp(db, args, log_fn):
    flags = [a for a in args if a.startswith("-")]
    paths = [a for a in args if not a.startswith("-")]
    if len(paths) < 2:
        log_fn("tree: cp: usage : cp <src> <dst>")
        return 1, "arguments insuffisants"
    recursive = "-r" in flags or "--recursive" in flags
    cwd = _get_cwd_fs(db)
    src = os.path.normpath(os.path.join(cwd, paths[0]))
    dst = os.path.normpath(os.path.join(cwd, paths[1]))
    try:
        if os.path.isdir(src):
            if recursive:
                shutil.copytree(src, dst)
            else:
                log_fn(f"tree: cp: {src} est un dossier (utilisez -r)")
                return 1, "dossier sans -r"
        else:
            shutil.copy2(src, dst)
        log_fn(f"Copié : {src} → {dst}")
        return 0, dst
    except Exception as e:
        log_fn(f"tree: cp: {e}")
        return 1, str(e)


def _fs_mv(db, args, log_fn):
    paths = [a for a in args if not a.startswith("-")]
    if len(paths) < 2:
        log_fn("tree: mv: usage : mv <src> <dst>")
        return 1, "arguments insuffisants"
    cwd = _get_cwd_fs(db)
    src = os.path.normpath(os.path.join(cwd, paths[0]))
    dst = os.path.normpath(os.path.join(cwd, paths[1]))
    try:
        shutil.move(src, dst)
        log_fn(f"Déplacé : {src} → {dst}")
        return 0, dst
    except Exception as e:
        log_fn(f"tree: mv: {e}")
        return 1, str(e)


def _fs_touch(db, args, log_fn):
    if not args:
        log_fn("tree: touch: argument manquant")
        return 1, "argument manquant"
    cwd = _get_cwd_fs(db)
    created = []
    for name in args:
        path = os.path.normpath(os.path.join(cwd, name))
        try:
            pathlib.Path(path).touch()
            log_fn(f"Touché : {path}")
            created.append(path)
        except Exception as e:
            log_fn(f"tree: touch: {e}")
            return 1, str(e)
    return 0, created


def _fs_cat(db, args, log_fn):
    """Affiche le contenu d'un ou plusieurs fichiers (mode FS)."""
    if not args:
        log_fn("tree: cat: argument manquant")
        return 1, "argument manquant"
    cwd = _get_cwd_fs(db)
    lines = []
    for name in args:
        path = os.path.normpath(os.path.join(cwd, name))
        if not os.path.exists(path):
            log_fn(f"tree: cat: {path}: fichier introuvable")
            return 1, f"introuvable : {path}"
        if os.path.isdir(path):
            log_fn(f"tree: cat: {path}: est un dossier")
            return 1, "est un dossier"
        try:
            with open(path, "r", errors="replace") as f:
                content = f.read()
            log_fn(content)
            lines.append(content)
        except Exception as e:
            log_fn(f"tree: cat: {e}")
            return 1, str(e)
    return 0, "\n".join(lines)


# ─────────────────────────────────────────────────────────────
#  Commandes — Mode Hive
# ─────────────────────────────────────────────────────────────

def _hive_cwd_cmd(db, log_fn):
    cwd = _get_cwd_hive(db)
    log_fn(cwd)
    return 0, cwd


def _hive_cd(db, args, log_fn):
    cwd = _get_cwd_hive(db)
    if not args:
        new = _HIVE_ROOT
    else:
        new = _hive_abspath(cwd, args[0])
    # Vérifier que ce préfixe existe (a des enfants ou est une clé)
    children = _hive_list_children(db, new)
    exists_as_key = db.exists(new)
    if new != _HIVE_ROOT and not children and not exists_as_key:
        log_fn(f"tree: cd: {new}: chemin HiveFS introuvable")
        return 1, f"introuvable : {new}"
    db.set(_KEY_CWD_HIVE, new)
    return 0, new


def _hive_ls_cmd(db, args, log_fn):
    cwd = _get_cwd_hive(db)
    target = _hive_abspath(cwd, args[0]) if args else cwd

    # Cas : clé inexistante et pas d'enfants
    children = _hive_list_children(db, target)
    has_val  = db.exists(target)
    if not children and not has_val and target != _HIVE_ROOT:
        log_fn(f"tree: ls: {target}: introuvable")
        return 1, []

    # Si la cible est elle-même une feuille (valeur sans enfants), cat implicite
    if has_val and not children:
        val = db.get(target, as_str=True)
        log_fn(f"{target} = {val!r}")
        return 0, []

    # Namespace : lister les enfants directs
    names = []
    col_w = max((len(_hive_basename(c)) for c in children), default=0) + 1
    for child in children:
        base = _hive_basename(child)
        sub  = _hive_list_children(db, child)
        is_val = db.exists(child)
        if sub and is_val:
            # namespace + valeur propre : afficher la valeur entre crochets
            val = db.get(child, as_str=True)
            suffix = f"/  [{val!r}]"
        elif sub:
            suffix = "/"
        elif is_val:
            val = db.get(child, as_str=True)
            # Tronquer les valeurs longues
            display = (val[:40] + "…") if len(val) > 40 else val
            suffix = f"  {display!r}"
        else:
            suffix = "  (?)"
        log_fn(f"  {base:<{col_w}}{suffix}")
        names.append(base)
    return 0, names


def _hive_mkdir(db, args, log_fn):
    """
    En HiveFS, 'mkdir' crée un namespace vide en posant une clé sentinelle.
    Chemin : §sys:tree:namespaces:<nom>
    """
    if not args:
        log_fn("tree: mkdir: argument manquant")
        return 1, "argument manquant"
    cwd = _get_cwd_hive(db)
    target = _hive_abspath(cwd, args[0])
    sentinel = target + _HIVE_SEP + ".dir"
    db.set(sentinel, "1")
    log_fn(f"Namespace HiveFS créé : {target}")
    return 0, target


def _hive_rmdir(db, args, log_fn):
    """Supprime le namespace HiveFS (sentinel) — échoue s'il a des enfants."""
    if not args:
        log_fn("tree: rmdir: argument manquant")
        return 1, "argument manquant"
    cwd = _get_cwd_hive(db)
    target = _hive_abspath(cwd, args[0])
    children = _hive_list_children(db, target)
    non_sentinel = [c for c in children if not c.endswith(":.dir")]
    if non_sentinel:
        log_fn(f"tree: rmdir: {target}: namespace non vide")
        return 1, "namespace non vide"
    sentinel = target + _HIVE_SEP + ".dir"
    db.delete(sentinel)
    log_fn(f"Namespace supprimé : {target}")
    return 0, target


def _hive_rm(db, args, log_fn):
    """Supprime une ou plusieurs clés HiveFS. -r supprime récursivement."""
    if not args:
        log_fn("tree: rm: argument manquant")
        return 1, "argument manquant"
    recursive = "-r" in args or "--recursive" in args
    targets = [a for a in args if not a.startswith("-")]
    cwd = _get_cwd_hive(db)
    for name in targets:
        key = _hive_abspath(cwd, name)
        children = _hive_list_children(db, key)
        if children and not recursive:
            log_fn(f"tree: rm: {key} a des sous-clés (utilisez -r)")
            return 1, "sous-clés sans -r"
        if recursive:
            all_keys = db.list()
            norm = key.rstrip(_HIVE_SEP)
            to_del = [k for k in all_keys if k == norm or k.startswith(norm + _HIVE_SEP)]
            for k in to_del:
                db.delete(k)
                log_fn(f"  Supprimé : {k}")
        else:
            if not db.exists(key):
                log_fn(f"tree: rm: {key}: clé introuvable")
                return 1, "introuvable"
            db.delete(key)
            log_fn(f"Supprimé : {key}")
    return 0, None


def _hive_cp(db, args, log_fn):
    """Copie une clé HiveFS (ou sous-arbre avec -r)."""
    flags = [a for a in args if a.startswith("-")]
    paths = [a for a in args if not a.startswith("-")]
    if len(paths) < 2:
        log_fn("tree: cp: usage : cp <src> <dst>")
        return 1, "arguments insuffisants"
    recursive = "-r" in flags
    cwd = _get_cwd_hive(db)
    src = _hive_abspath(cwd, paths[0])
    dst = _hive_abspath(cwd, paths[1])

    if recursive:
        all_keys = db.list()
        norm = src.rstrip(_HIVE_SEP)
        to_copy = [k for k in all_keys if k == norm or k.startswith(norm + _HIVE_SEP)]
        for k in to_copy:
            new_key = dst + k[len(norm):]
            db.set(new_key, db.get(k))
            log_fn(f"  {k} → {new_key}")
    else:
        if not db.exists(src):
            log_fn(f"tree: cp: {src}: clé introuvable")
            return 1, "introuvable"
        db.set(dst, db.get(src))
        log_fn(f"Copié : {src} → {dst}")
    return 0, dst


def _hive_mv(db, args, log_fn):
    """Déplace (renomme) une clé ou sous-arbre HiveFS."""
    paths = [a for a in args if not a.startswith("-")]
    if len(paths) < 2:
        log_fn("tree: mv: usage : mv <src> <dst>")
        return 1, "arguments insuffisants"
    cwd = _get_cwd_hive(db)
    src = _hive_abspath(cwd, paths[0])
    dst = _hive_abspath(cwd, paths[1])
    all_keys = db.list()
    norm = src.rstrip(_HIVE_SEP)
    to_move = [k for k in all_keys if k == norm or k.startswith(norm + _HIVE_SEP)]
    if not to_move:
        log_fn(f"tree: mv: {src}: introuvable")
        return 1, "introuvable"
    for k in to_move:
        new_key = dst + k[len(norm):]
        db.set(new_key, db.get(k))
        db.delete(k)
        log_fn(f"  {k} → {new_key}")
    return 0, dst


def _hive_touch(db, args, log_fn):
    """Crée une clé HiveFS vide si elle n'existe pas."""
    if not args:
        log_fn("tree: touch: argument manquant")
        return 1, "argument manquant"
    cwd = _get_cwd_hive(db)
    created = []
    for name in args:
        key = _hive_abspath(cwd, name)
        if not db.exists(key):
            db.set(key, "")
            log_fn(f"Clé créée : {key}")
        else:
            log_fn(f"Clé déjà présente : {key}")
        created.append(key)
    return 0, created


def _hive_cat(db, args, log_fn):
    """
    Affiche la valeur d'une ou plusieurs clés HiveFS.
    Si la clé est un namespace (a des enfants), liste ses enfants directs.
    """
    if not args:
        log_fn("tree: cat: argument manquant")
        return 1, "argument manquant"
    cwd = _get_cwd_hive(db)
    results = []
    for name in args:
        key = _hive_abspath(cwd, name)
        children = _hive_list_children(db, key)
        has_val  = db.exists(key)
        if not has_val and not children:
            log_fn(f"tree: cat: {key}: clé introuvable")
            return 1, f"introuvable : {key}"
        if has_val:
            val = db.get(key, as_str=True)
            if len(args) > 1:
                log_fn(f"{key}:")
            log_fn(val)
            results.append(val)
        if children:
            if has_val:
                log_fn(f"  (namespace — sous-clés :)")
            else:
                if len(args) > 1:
                    log_fn(f"{key}:")
            for child in children:
                base = _hive_basename(child)
                sub  = _hive_list_children(db, child)
                marker = "/" if sub else ""
                log_fn(f"  {base}{marker}")
    return 0, results


# ─────────────────────────────────────────────────────────────
#  Commandes communes (mode-agnostiques)
# ─────────────────────────────────────────────────────────────

def _cmd_mode(db, args, log_fn):
    if not args:
        mode = _get_mode(db)
        log_fn(f"Mode actuel : {mode}")
        return 0, mode
    new_mode = args[0].lower()
    if new_mode not in ("fs", "hive"):
        log_fn(f"tree: mode: valeur invalide '{new_mode}' (fs|hive)")
        return 1, "valeur invalide"
    db.set(_KEY_MODE, new_mode)
    log_fn(f"Mode → {new_mode}")
    return 0, new_mode


def _cmd_status(db, log_fn):
    mode = _get_mode(db)
    cwd_fs   = _get_cwd_fs(db)
    cwd_hive = _get_cwd_hive(db)
    log_fn(f"tree v{_VERSION}")
    log_fn(f"  Mode     : {mode}")
    log_fn(f"  CWD FS   : {cwd_fs}")
    log_fn(f"  CWD Hive : {cwd_hive}")
    return 0, {"mode": mode, "cwd_fs": cwd_fs, "cwd_hive": cwd_hive}


# ─────────────────────────────────────────────────────────────
#  Dispatch
# ─────────────────────────────────────────────────────────────

_HELP =  """
tree — Gestionnaire de fichiers R-ECO3  v1.0
============================================

SYNOPSIS
    tree <commande> [args...]
    tree mode [fs|hive]
    tree status
    tree cwd
    tree cd <chemin>
    tree ls [chemin]
    tree mkdir <nom>
    tree rmdir <nom>
    tree rm [-r] <cible>
    tree cp [-r] <src> <dst>
    tree mv <src> <dst>
    tree touch <nom> [...]
    tree cat <cible> [...]

COMMANDS
    mode [fs|hive]
        Displays or changes the current mode.

    status
        Shows the current mode and both working directories.

    cwd
        Prints the current working directory for the active mode.

    cd <chemin>
        Changes the current directory or HiveFS namespace.

    ls [chemin]
        Lists files in FS mode or direct children in Hive mode.

    mkdir <nom>
        Creates a folder in FS mode or a namespace sentinel in Hive mode.

    rmdir <nom>
        Removes an empty folder in FS mode or an empty namespace in Hive mode.

    rm [-r] <cible>
        Removes files or keys. Use -r for recursive removal.

    cp [-r] <src> <dst>
        Copies files or HiveFS keys. Use -r for recursive copy.

    mv <src> <dst>
        Moves or renames files, keys, or subtrees.

    touch <nom> [...]
        Creates empty files in FS mode or empty keys in Hive mode.

    cat <cible> [...]
        Prints file contents in FS mode or key values / child listings in Hive mode.

STORED KEYS
    §_tree:cwd:fs
        Stores the current working directory for FS mode.

    §_tree:cwd:hive
        Stores the current working namespace for Hive mode.

    §_tree:mode
        Stores the active mode value: fs or hive.

EXAMPLES
    tree mode hive
    tree cwd
    tree ls
    tree cd §sys:user
    tree touch test.txt
""",


def _simple_tokenize(s: str) -> list:
    """
    Tokenisation simple respectant les guillemets simples et doubles.
    N'utilise PAS core.utils.parse_command pour ne pas interpréter § ou :
    comme des opérateurs spéciaux.
    """
    tokens = []
    current = []
    in_quote = None
    for ch in s:
        if in_quote:
            if ch == in_quote:
                in_quote = None
            else:
                current.append(ch)
        elif ch in ('"', "'"):
            in_quote = ch
        elif ch == ' ':
            if current:
                tokens.append(''.join(current))
                current = []
        else:
            current.append(ch)
    if current:
        tokens.append(''.join(current))
    return tokens


def R_ECO3(args: str, log_fn=print):
    tokens = _simple_tokenize(args.strip()) if args.strip() else []

    cmd = tokens[0].lower()
    rest = tokens[1:]

    try:
        db = _get_db()
    except RuntimeError as e:
        log_fn(f"[tree] Erreur HiveFS : {e}")
        return 1, str(e)

    mode = _get_mode(db)

    # ── Commandes communes ──
    if cmd in ("help", "-h", "--help"):
        log_fn(_HELP)
        db.close()
        return 0

    if cmd == "status":
        result = _cmd_status(db, log_fn)
        db.close()
        return result

    if cmd == "mode":
        result = _cmd_mode(db, rest, log_fn)
        db.close()
        return result

    # ── Dispatch selon le mode ──
    if mode == "fs":
        dispatch = {
            "cwd":   lambda: _fs_cwd(db, log_fn),
            "cd":    lambda: _fs_cd(db, rest, log_fn),
            "ls":    lambda: _fs_ls(db, rest, log_fn),
            "mkdir": lambda: _fs_mkdir(db, rest, log_fn),
            "rmdir": lambda: _fs_rmdir(db, rest, log_fn),
            "rm":    lambda: _fs_rm(db, rest, log_fn),
            "cp":    lambda: _fs_cp(db, rest, log_fn),
            "mv":    lambda: _fs_mv(db, rest, log_fn),
            "touch": lambda: _fs_touch(db, rest, log_fn),
            "cat":   lambda: _fs_cat(db, rest, log_fn),
        }
    else:  # mode hive
        dispatch = {
            "cwd":   lambda: _hive_cwd_cmd(db, log_fn),
            "cd":    lambda: _hive_cd(db, rest, log_fn),
            "ls":    lambda: _hive_ls_cmd(db, rest, log_fn),
            "mkdir": lambda: _hive_mkdir(db, rest, log_fn),
            "rmdir": lambda: _hive_rmdir(db, rest, log_fn),
            "rm":    lambda: _hive_rm(db, rest, log_fn),
            "cp":    lambda: _hive_cp(db, rest, log_fn),
            "mv":    lambda: _hive_mv(db, rest, log_fn),
            "touch": lambda: _hive_touch(db, rest, log_fn),
            "cat":   lambda: _hive_cat(db, rest, log_fn),
        }

    if cmd not in dispatch:
        log_fn(f"tree: commande inconnue '{cmd}'. Tapez 'tree help'.")
        db.close()
        return 1, f"commande inconnue : {cmd}"

    result = dispatch[cmd]()
    db.close()
    return result


# ─────────────────────────────────────────────────────────────
#  Métadonnées R-ECO3
# ─────────────────────────────────────────────────────────────

def R_ECO3dep():
    return (
        ("3.5.1b",),
        (
            ("core.hive",  ("1.1",)),
            ("core.apix",  ("1.1",)),
            ("core.utils", ("1.1",)),
            ("core.trail", ("1.1",)),
        )
    )


def R_ECO3inf():
    # ── alias_rules (mycelium 1.2) ──────────────────────────────────────────
    # Format par keyword : "/* = rhs ||| * = rhs /*"
    # Chaque entrée |||‑séparée = un variant (/* = zéro-arg, * = avec args).
    #
    # Aliases exposés :
    #   tree              → tree (sans args)          [tree /*]
    #   tree <cmd> ...    → tree <cmd> ...             [tree *]
    #   cd  <chemin>      → tree cd <chemin>           alias direct
    #   ls  [chemin]      → tree ls [chemin]           alias direct
    #   mkdir <nom>       → tree mkdir <nom>           alias direct
    #   rmdir <nom>       → tree rmdir <nom>           alias direct
    #   rm  [-r] <cible>  → tree rm [-r] <cible>      alias direct
    #   cp  [-r] <s> <d>  → tree cp [-r] <s> <d>      alias direct
    #   mv  <src> <dst>   → tree mv <src> <dst>        alias direct
    #   touch <nom> ...   → tree touch <nom> ...       alias direct
    #   cwd               → tree cwd                   alias direct
    #   mode [fs|hive]    → tree mode [...]            alias direct
    #
    # Les aliases directs (cd, ls, …) n'ont pas de variante /* autonome :
    # appeler "cd" sans arg est géré par tree.R_ECO3 lui-même (retour au home).
    # ────────────────────────────────────────────────────────────────────────
    _alias = " ||| ".join([
        "tree /* = banana err --msg='This module cannot be run without arguments. Please refer to the manual for usage instructions.'",

        # ── cd ──
        "cd /* = tree cd",
        "cd * = tree cd /*",

        # ── ls ──
        "ls /* = tree ls",
        "ls * = tree ls /*",

        # ── mkdir ──
        "mkdir * = tree mkdir /*",

        # ── rmdir ──
        "rmdir * = tree rmdir /*",

        # ── rm ──
        "rm * = tree rm /*",

        # ── cp ──
        "cp * = tree cp /*",

        # ── mv ──
        "mv * = tree mv /*",

        # ── touch ──
        "touch * = tree touch /*",

        # ── cat ──
        "cat /* = tree cat",
        "cat * = tree cat /*",

        # ── cwd ──
        "cwd /* = tree cwd",

        # ── mode ──
        "mode /* = tree mode",
        "mode * = tree mode /*",
    ])

    return {
        "name":        "tree",
        "desc":        "Gestionnaire de fichiers — alias cd/ls/mkdir/rm/… (modes fs et hive)",
        "help":        "Usage : tree <commande> [args]. Tapez 'tree help' pour la liste complète.",
        "version_mod": _VERSION,
        "L2Module":    True,
        "alias_rules": _alias,
        "manual": _HELP,
    }