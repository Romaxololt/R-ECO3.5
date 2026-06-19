# dev.py — Module de gestion des versions R-ECO3
# Version 1.0 · Module L2

import sys
import os
import re
import core.apix as apix
import core.trail as trail

# ---------------------------------------------------------------------------
# Métadonnées
# ---------------------------------------------------------------------------

_VERSION = "1.0"
_NAME    = "dev"
_DESC    = "Modifie les versions R-ECO ou les dépendances déclarées dans les modules"
_MANUAL  = """
dev — Gestionnaire de versions pour le développement R-ECO3
============================================================

SYNOPSIS
    dev ver reco <nouvelle_version>
    dev ver module <module_cible> <nouvelle_version>

DESCRIPTION
    Modifie les versions déclarées dans l'écosystème :

    dev ver reco <version>
        Change la version globale R-ECO dans la base HiveFS
        (reco_version) ET met à jour le champ version requise
        dans les tuples R_ECO3dep() des modules sélectionnés.
        Propose via banana question la liste des modules L2
        disponibles (sélection multiple). Pour chaque module,
        demande si la nouvelle version doit s'ajouter aux
        versions acceptées (keep actual) ou les remplacer.

    dev ver module <module_cible> <version>
        Change la version déclarée dans version_mod du module
        cible (R_ECO3inf). Met ensuite à jour les références
        à ce module dans les R_ECO3dep() de tous les autres
        modules qui en dépendent. Même question keep actual.

EXEMPLES
    dev ver reco 3.5.2s
    dev ver module hive 1.2
    dev ver module spider 2.0

NOTES
    - keep actual : ajoute la nouvelle version à côté de
      l'ancienne dans le tuple → ("1.0", "1.1")
    - remplacement : seule la nouvelle version reste → ("1.1",)
    - Les fichiers modifiés sont sauvegardés avec un backup
      .bak avant toute écriture.
    - Seuls les fichiers .py présents dans modules/ et core/
      sont scannés.
"""

# ---------------------------------------------------------------------------
# Conventions L2
# ---------------------------------------------------------------------------

def R_ECO3inf():
    return {
        "name":        _NAME,
        "desc":        _DESC,
        "help":        "dev ver reco <v> | dev ver module <mod> <v>",
        "version_mod": _VERSION,
        "L2Module":    True,
        "manual":      _MANUAL,
        "alias_rules": (
            "/* = dev\n"
            "* = dev /*"
        ),
    }


def R_ECO3dep():
    return {
        "reco": ["3.5.1b"],
        "module": [
            {"spider": ["2.1"]},
            {"banana": ["2.1"]},
            ],
    }


# ---------------------------------------------------------------------------
# Chargement des modules core (lazy, pour éviter les imports circulaires)
# ---------------------------------------------------------------------------


def _banana(apix, cmd, log_fn=print):
    """
    Raccourci pour appeler banana via apix.

    apix.R_ECO3("run banana <cmd>") retourne (outer_code, inner_result)
    ou inner_result est ce que banana.R_ECO3() a retourne, soit :
      - None                    pour les commandes display (ok/err/print...)
      - (inner_code, payload)   pour les commandes interactives (question/input)

    On deroule ces deux niveaux pour toujours retourner directement
    le payload utile (liste, str, None).
    """
    outer_code, inner = apix.R_ECO3(f"run banana {cmd}", log_fn)
    if outer_code != 0:
        return None
    # inner peut etre None (commandes display) ou un tuple (code, payload)
    if isinstance(inner, tuple) and len(inner) == 2:
        inner_code, payload = inner
        return payload if inner_code == 0 else None
    # Cas ou apix a deja extrait directement la valeur
    return inner


# ---------------------------------------------------------------------------
# Helpers fichiers
# ---------------------------------------------------------------------------

def _all_module_files(trail):
    """Liste tous les .py dans modules/ et core/."""
    files = []
    for d in [trail.MODULES_DIR, trail.ROOT / "core"]:
        if d.exists():
            files.extend(sorted(d.glob("*.py")))
    return files


def _read(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None


def _write(path, content, do_backup=False):
    """Ecrit content dans path. Si do_backup=True, cree un .bak avant."""
    if do_backup:
        bak = str(path) + ".bak"
        try:
            import shutil
            shutil.copy2(str(path), bak)
        except Exception:
            pass
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Listing des modules L2 disponibles
# ---------------------------------------------------------------------------

def _list_l2_modules(apix, trail, log_fn):
    """Retourne la liste des noms de modules L2 disponibles."""
    names = []
    for pyfile in _all_module_files(trail):
        stem = pyfile.stem
        if stem.startswith("_") or stem in ("__init__",):
            continue
        try:
            code, inf = apix.R_ECO3(f"inf {stem}", log_fn)
            if code == 0 and isinstance(inf, dict) and inf.get("L2Module"):
                names.append(stem)
        except Exception:
            pass
    return names


# ---------------------------------------------------------------------------
# Sélection via banana question
# ---------------------------------------------------------------------------

def _select_modules(apix, available, prompt_msg, log_fn):
    """
    Affiche un menu de sélection multiple via banana question.
    Retourne la liste des modules choisis.
    """
    choices_str = ",".join(available)
    val = _banana(
        apix,
        f'question --msg="{prompt_msg}" --choices="{choices_str}" --multi=true',
        log_fn
    )
    if val is None:
        return []
    # banana retourne une liste ou une chaîne selon la version
    if isinstance(val, list):
        return val
    if isinstance(val, str):
        return [v.strip() for v in val.split(",") if v.strip()]
    return []


def _ask_backup(apix, log_fn):
    """
    Demande si l utilisateur veut sauvegarder les fichiers avant modification.
    Retourne True = faire les backups, False = ne pas en faire.
    """
    val = _banana(
        apix,
        'question --msg="Sauvegarder les fichiers avant modification ? (.bak)" '
        '--choices="oui,non" --multi=false',
        log_fn
    )
    if val is None:
        return False
    choice = (val if isinstance(val, str) else (val[0] if val else "")).strip().lower()
    return choice == "oui"


def _ask_batch_mode(apix, old_ver, new_ver, log_fn):
    """
    Demande le mode de traitement global avant la boucle :
      - keep all     : tous les modules gardent l'ancienne + ajoutent la nouvelle
      - replace all  : tous les modules remplacent l'ancienne par la nouvelle
      - select       : on demande module par module
    Retourne : "keep" | "replace" | "select"
    """
    msg = (
        f"Mise a jour {old_ver} -> {new_ver} : "
        f"choisir le mode pour tous les modules selectionnes"
    )
    val = _banana(
        apix,
        f'question --msg="{msg}" --choices="keep all,replace all,select" --multi=false',
        log_fn
    )
    if val is None:
        return "replace"
    choice = (val if isinstance(val, str) else (val[0] if val else "")).strip().lower()
    if choice == "keep all":
        return "keep"
    if choice == "replace all":
        return "replace"
    return "select"


def _ask_keep_actual(apix, module_name, old_ver, new_ver, log_fn):
    """
    Demande module par module (mode "select").
    Retourne True = keep actual, False = remplacer.
    """
    msg = (
        f"[{module_name}] version actuelle={old_ver}, nouvelle={new_ver} — garder les deux ou remplacer ?"
    )
    val = _banana(
        apix,
        f'question --msg="{msg}" --choices="keep actual,remplacer" --multi=false',
        log_fn
    )
    if val is None:
        return False
    choice = val if isinstance(val, str) else (val[0] if val else "")
    return choice.strip().lower() == "keep actual"


# ---------------------------------------------------------------------------
# Manipulation des tuples de version dans le source Python
# ---------------------------------------------------------------------------

# Patterns ciblés :
#   R_ECO3dep version tuple : ("3.5.1b",)  dans return ((...),  ...)
#   version_mod              : "version_mod": "1.0"
#   dépendance dans dep      : ("spider", ("1.8",))

def _patch_reco_version_in_dep(source, old_ver, new_ver, keep):
    """
    Remplace la tuple de version R-ECO dans R_ECO3dep (premier élément du return).
    Ex: ("3.5.1b",) → ("3.5.2s",) ou ("3.5.1b", "3.5.2s")
    """
    def replacer(m):
        existing = [v.strip().strip('"').strip("'") for v in m.group(1).split(",") if v.strip()]
        if new_ver in existing:
            return m.group(0)  # déjà présent
        if keep:
            merged = existing + [new_ver]
        else:
            merged = [new_ver]
        inner = ", ".join(f'"{v}"' for v in merged)
        return f"({inner},)"

    # Cible : tuple de strings entre parenthèses, première ligne du return de R_ECO3dep
    pattern = r'\(\s*("[\d\w.]+?"(?:\s*,\s*"[\d\w.]+?")*\s*,?)\s*\)'
    # On ne patche que dans le contexte de R_ECO3dep
    # On cherche la fonction et son return
    func_match = re.search(
        r'(def R_ECO3dep\(\).*?return\s*\()\s*' + pattern,
        source, re.DOTALL
    )
    if not func_match:
        return source, False

    # Remplacement ciblé : première occurrence du pattern après "def R_ECO3dep"
    dep_start = source.find("def R_ECO3dep()")
    if dep_start == -1:
        return source, False

    sub_src = source[dep_start:]
    new_sub, n = re.subn(pattern, replacer, sub_src, count=1)
    if n == 0:
        return source, False
    return source[:dep_start] + new_sub, True


def _patch_module_dep_version(source, dep_name, old_ver, new_ver, keep):
    """
    Remplace la version d une dependance nommee dans R_ECO3dep.
    dep_name peut etre "hive" ou "core.hive" : les deux formes sont essayees.
    Ex: ("core.hive", ("1.1",)) -> ("core.hive", ("1.2",))
    """
    # Normalise : accepte "hive" et "core.hive" en cherchant les deux
    candidates = [dep_name]
    if not dep_name.startswith("core."):
        candidates.append("core." + dep_name)
    else:
        candidates.append(dep_name[5:])  # core.hive -> hive

    patched_any = False
    result = source
    for name in candidates:
        escaped = re.escape(name)

        def replacer(m, _name=name):
            existing = [v.strip().strip('"').strip("'") for v in m.group(1).split(",") if v.strip()]
            if new_ver in existing:
                return m.group(0)
            if keep:
                merged = existing + [new_ver]
            else:
                merged = [new_ver]
            inner = ", ".join(f'"{v}"' for v in merged)
            return f'("{_name}", ({inner},))'

        pattern = (
            r'\(\s*"' + escaped + r'"\s*,\s*'
            r'\(\s*("[\d\w.]+?"(?:\s*,\s*"[\d\w.]+?")*\s*,?)\s*\)\s*\)'
        )
        new_result, n = re.subn(pattern, replacer, result)
        if n > 0:
            result = new_result
            patched_any = True
    return result, patched_any


def _patch_version_mod(source, new_ver):
    """
    Remplace la valeur de version_mod dans R_ECO3inf.
    Ex: "version_mod": "1.0" → "version_mod": "1.2"
    """
    pattern = r'(["\']version_mod["\']\s*:\s*)["\'][\d\w.]+?["\']'
    new_source, n = re.subn(pattern, lambda m: m.group(1) + f'"{new_ver}"', source)
    # Aussi la variable _VERSION en haut de fichier si présente
    new_source2, n2 = re.subn(
        r'^(_VERSION\s*=\s*)["\'][\d\w.]+?["\']',
        lambda m: m.group(1) + f'"{new_ver}"',
        new_source, flags=re.MULTILINE
    )
    return new_source2, (n + n2) > 0


# ---------------------------------------------------------------------------
# Commandes principales
# ---------------------------------------------------------------------------

def _cmd_ver_reco(args_tokens, apix, db, trail, log_fn):
    """
    dev ver reco <nouvelle_version>
    """
    if not args_tokens:
        _banana(apix, 'err --msg="Usage : dev ver reco <version>"', log_fn)
        return 1

    new_ver = args_tokens[0]

    _banana(apix, f'rule --text="dev ver reco → {new_ver}" --style="bold cyan"', log_fn)

    # 1. Récupérer la version actuelle en base
    old_reco_ver = db.get("§sys:global:version.nest") or "?"
    _banana(apix, f'print --msg="Version actuelle en base : {old_reco_ver}"', log_fn)

    # 2. Lister les modules L2
    _banana(apix, 'loader start --msg="Scan des modules L2..."', log_fn)
    available = _list_l2_modules(apix, trail, log_fn)
    _banana(apix, 'loader stop', log_fn)

    if not available:
        _banana(apix, 'err --msg="Aucun module L2 trouvé."', log_fn)
        return 1

    # 3. Sélection des modules à patcher
    selected = _select_modules(
        apix, available,
        f"Quels modules mettre à jour vers reco={new_ver} ?",
        log_fn
    )
    if not selected:
        _banana(apix, 'print --msg="Aucun module sélectionné. Abandon."', log_fn)
        return 0

    # 4. Backup + mode global
    do_backup   = _ask_backup(apix, log_fn)
    batch_mode  = _ask_batch_mode(apix, old_reco_ver, new_ver, log_fn)
    results = {"ok": [], "skip": [], "err": []}

    for mod_name in selected:
        # Trouver le fichier
        pyfile = trail.MODULES_DIR / f"{mod_name}.py"
        if not pyfile.exists():
            pyfile = trail.ROOT / "core" / f"{mod_name}.py"
        if not pyfile.exists():
            _banana(apix, f'err --msg="Fichier introuvable pour {mod_name}"', log_fn)
            results["err"].append(mod_name)
            continue

        src = _read(pyfile)
        if src is None:
            results["err"].append(mod_name)
            continue

        if batch_mode == "keep":
            keep = True
        elif batch_mode == "replace":
            keep = False
        else:
            keep = _ask_keep_actual(apix, mod_name, old_reco_ver, new_ver, log_fn)
        new_src, patched = _patch_reco_version_in_dep(src, old_reco_ver, new_ver, keep)

        if not patched:
            _banana(apix, f'print --msg="[{mod_name}] Aucun tuple R-ECO détecté dans R_ECO3dep — ignoré."', log_fn)
            results["skip"].append(mod_name)
            continue

        if _write(pyfile, new_src, do_backup=do_backup):
            action = "keep+add" if keep else "remplacement"
            _banana(apix, f'ok --msg="[{mod_name}] Patché ({action})"', log_fn)
            results["ok"].append(mod_name)
        else:
            _banana(apix, f'err --msg="[{mod_name}] Échec écriture"', log_fn)
            results["err"].append(mod_name)

    # 5. Mise à jour de la base HiveFS
    try:
        db.set("§sys:global:version.nest", new_ver)
        _banana(apix, f'ok --msg="Base HiveFS mise à jour : reco_version = {new_ver}"', log_fn)
    except Exception as exc:
        _banana(apix, f'err --msg="Échec mise à jour HiveFS : {exc}"', log_fn)

    # 6. Résumé
    ok_list   = results["ok"]
    skip_list = results["skip"]
    err_list  = results["err"]
    _banana(apix, 'rule --text="Résumé" --style="dim"', log_fn)
    _banana(apix, f'print --msg="Patchés  : {len(ok_list)} — {ok_list}"', log_fn)
    _banana(apix, f'print --msg="Ignorés  : {len(skip_list)} — {skip_list}"', log_fn)
    _banana(apix, f'print --msg="Erreurs  : {len(err_list)} — {err_list}"', log_fn)

    return 0


def _cmd_ver_module(args_tokens, apix, db, trail, log_fn):
    """
    dev ver module <module_cible> <nouvelle_version>
    """
    if len(args_tokens) < 2:
        _banana(apix, 'err --msg="Usage : dev ver module <module> <version>"', log_fn)
        return 1

    target_mod = args_tokens[0]
    new_ver    = args_tokens[1]

    _banana(apix, f'rule --text="dev ver module {target_mod} → {new_ver}" --style="bold cyan"', log_fn)

    # 1. Récupérer la version actuelle du module cible
    target_file = trail.MODULES_DIR / f"{target_mod}.py"
    if not target_file.exists():
        target_file = trail.ROOT / "core" / f"{target_mod}.py"
    if not target_file.exists():
        # Essai sans extension (core.hive → core/hive.py)
        clean = target_mod.replace("core.", "")
        target_file = trail.ROOT / "core" / f"{clean}.py"

    if not target_file.exists():
        _banana(apix, f'err --msg="Module cible introuvable : {target_mod}"', log_fn)
        
        return 1

    src_target = _read(target_file)
    if src_target is None:
        _banana(apix, 'err --msg="Impossible de lire le module cible."', log_fn)
        
        return 1

    # Détecter l'ancienne version dans version_mod
    match = re.search(r'["\']version_mod["\']\s*:\s*["\']([^"\']+)["\']', src_target)
    old_ver = match.group(1) if match else "?"
    _banana(apix, f'print --msg="Version actuelle de [{target_mod}] : {old_ver}"', log_fn)

    # 2. Backup + patch version_mod dans le fichier cible
    do_backup = _ask_backup(apix, log_fn)
    new_src_target, ok = _patch_version_mod(src_target, new_ver)
    if ok:
        if _write(target_file, new_src_target, do_backup=do_backup):
            _banana(apix, f'ok --msg="[{target_mod}] version_mod mis à jour → {new_ver}"', log_fn)
        else:
            _banana(apix, f'err --msg="[{target_mod}] Échec écriture version_mod"', log_fn)
    else:
        _banana(apix, f'print --msg="[{target_mod}] Aucune version_mod détectée — fichier non modifié."', log_fn)

    # 3. Scanner tous les autres modules qui dépendent de target_mod
    _banana(apix, f'loader start --msg="Scan des dépendances vers {target_mod}..."', log_fn)
    all_files = _all_module_files(trail)
    dependants = []
    # dep_key : le nom exact du module tel qu'il apparait dans les R_ECO3dep
    # On cherche les deux formes : "hive" et "core.hive"
    dep_key = target_mod
    dep_key_alt = ("core." + target_mod) if not target_mod.startswith("core.") else target_mod[5:]

    def _has_dep(src, key, key_alt):
        """Verifie qu'un fichier declare key ou key_alt comme dependance exacte."""
        if "R_ECO3dep" not in src:
            return False
        for k in (key, key_alt):
            if re.search(r'\("'  + re.escape(k) + r'"\s*,\s*\(', src):
                return True
        return False

    for pyfile in all_files:
        if pyfile == target_file:
            continue
        src = _read(pyfile)
        if src is None:
            continue
        if _has_dep(src, dep_key, dep_key_alt):
            dependants.append(pyfile)

    _banana(apix, 'loader stop', log_fn)

    if not dependants:
        _banana(apix, f'print --msg="Aucun autre module ne déclare [{target_mod}] comme dépendance."', log_fn)
        
        return 0

    dep_names = [p.stem for p in dependants]
    _banana(apix, f'print --msg="Modules dépendants trouvés : {dep_names}"', log_fn)

    # 4. Sélection des modules à patcher
    selected_files = _select_modules(
        apix, dep_names,
        f"Quels modules mettre à jour pour dépendance {target_mod}={new_ver} ?",
        log_fn
    )
    if not selected_files:
        _banana(apix, 'print --msg="Aucun module sélectionné. Abandon."', log_fn)
        
        return 0

    # 5. Mode global : keep all / replace all / select
    batch_mode = _ask_batch_mode(apix, old_ver, new_ver, log_fn)
    results = {"ok": [], "skip": [], "err": []}
    # do_backup deja defini au point 2

    for mod_name in selected_files:
        pyfile = next((p for p in dependants if p.stem == mod_name), None)
        if pyfile is None:
            results["err"].append(mod_name)
            continue

        src = _read(pyfile)
        if src is None:
            results["err"].append(mod_name)
            continue

        if batch_mode == "keep":
            keep = True
        elif batch_mode == "replace":
            keep = False
        else:
            keep = _ask_keep_actual(apix, mod_name, old_ver, new_ver, log_fn)
        new_src, patched = _patch_module_dep_version(src, dep_key, old_ver, new_ver, keep)

        if not patched:
            _banana(apix, f'print --msg="[{mod_name}] Dépendance {dep_key} non trouvée dans R_ECO3dep — ignoré."', log_fn)
            results["skip"].append(mod_name)
            continue

        if _write(pyfile, new_src, do_backup=do_backup):
            action = "keep+add" if keep else "remplacement"
            _banana(apix, f'ok --msg="[{mod_name}] Dépendance {dep_key} patchée ({action})"', log_fn)
            results["ok"].append(mod_name)
        else:
            _banana(apix, f'err --msg="[{mod_name}] Échec écriture"', log_fn)
            results["err"].append(mod_name)

    # 6. Résumé
    ok_list   = results["ok"]
    skip_list = results["skip"]
    err_list  = results["err"]
    _banana(apix, 'rule --text="Résumé" --style="dim"', log_fn)
    _banana(apix, f'print --msg="Patchés  : {len(ok_list)} — {ok_list}"', log_fn)
    _banana(apix, f'print --msg="Ignorés  : {len(skip_list)} — {skip_list}"', log_fn)
    _banana(apix, f'print --msg="Erreurs  : {len(err_list)} — {err_list}"', log_fn)

    
    return 0


# ---------------------------------------------------------------------------
# Point d'entrée L2
# ---------------------------------------------------------------------------

def R_ECO3(inp):
    """
    Syntaxe :
        dev ver reco <version>
        dev ver module <module> <version>
    """
    args = inp["args"]
    log_fn = inp["logfn"]
    db = inp["db"]

    # Tokenisation simple (on retire le préfixe "dev" si spider l'a transmis)
    raw_tokens = args.strip().split()
    # Normalisation : retirer "dev" de tête si présent
    if raw_tokens and raw_tokens[0] == "dev":
        raw_tokens = raw_tokens[1:]

    # Doit commencer par "ver"
    if not raw_tokens or raw_tokens[0] != "ver":
        _banana(apix, 'err --msg="Usage : dev ver reco <v> | dev ver module <mod> <v>"', log_fn)
        return 1, "syntax error"

    sub = raw_tokens[1] if len(raw_tokens) > 1 else ""
    rest = raw_tokens[2:]

    if sub == "reco":
        code = _cmd_ver_reco(rest, apix, db, trail, log_fn)
        return code, None

    if sub == "module":
        code = _cmd_ver_module(rest, apix, db, trail, log_fn)
        return code, None

    _banana(apix, f'err --msg="Sous-commande inconnue : {sub}. Attenu : reco | module"', log_fn)
    return 1, "unknown subcommand"