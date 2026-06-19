"""
depgraph.py — Graphe de dépendances ASCII pour R-ECO3
Version : 1.0  |  Codename : Ant

Génère dans la console un schéma ASCII des dépendances entre modules L2
et modules core, en s'appuyant sur R_ECO3dep() de chaque module.
"""

import os
import sys

import core.trail as trail
import core.apix  as apix


# ─── collecte des dépendances ─────────────────────────────────────────────────

def _collect_deps(stems: list) -> dict:
    graph = {}
    for stem in stems:
        try:
            result = apix.R_ECO3({"args": f"dep {stem}", "logfn": lambda *_: None})
            if result["status"] != 0:
                graph[stem] = []
                continue
            dep = result["value"]

            # Nouveau format : {"reco": [...], "module": [{"name": ["ver"]}, ...]}
            if isinstance(dep, dict):
                deps = [list(d.keys())[0] for d in dep.get("module", []) if d]

            # Ancien format : ( (eco_version,), ( (name, (ver,...)), ... ) )
            elif isinstance(dep, tuple) and len(dep) > 1:
                deps = [d[0] for d in dep[1]]

            else:
                deps = []

            graph[stem] = deps

        except Exception:
            graph[stem] = []
    return graph

def _all_l2_stems() -> list:
    """Liste tous les stems .py dans MODULES_DIR (hors _start)."""
    stems = []
    for fname in sorted(os.listdir(str(trail.MODULES_DIR))):
        if fname.endswith(".py") and not fname.startswith("_"):
            stems.append(fname[:-3])
    return stems


# ─── rendu ASCII ──────────────────────────────────────────────────────────────

# Catégories de nœuds pour le style ASCII
_CAT_CORE   = "core"
_CAT_L2     = "l2"

_CORE_PREFIX = "core."

# Largeur de boîte
_BOX_W = 20


def _node_category(name: str) -> str:
    return _CAT_CORE if name.startswith(_CORE_PREFIX) else _CAT_L2


def _box(name: str, width: int = _BOX_W) -> list:
    """Retourne les 3 lignes d'une boîte ASCII pour un nœud."""
    label = name if len(name) <= width - 2 else name[:width - 5] + "..."
    inner = label.center(width - 2)
    top   = "┌" + "─" * (width - 2) + "┐"
    mid   = "│" + inner              + "│"
    bot   = "└" + "─" * (width - 2) + "┘"
    return [top, mid, bot]


def _render_tree(root: str, graph: dict, prefix: str = "",
                 visited: set = None, last: bool = True) -> list:
    """
    Rendu récursif type `tree` pour un nœud et ses dépendances.
    Retourne une liste de lignes.
    """
    if visited is None:
        visited = set()

    connector = "└── " if last else "├── "
    cat       = _node_category(root)
    tag       = "[core]" if cat == _CAT_CORE else "     "
    lines     = [f"{prefix}{connector}{root}  {tag}"]

    if root in visited:
        lines.append(f"{prefix}{'    ' if last else '│   '}  (déjà affiché)")
        return lines

    visited.add(root)
    deps = graph.get(root, [])

    child_prefix = prefix + ("    " if last else "│   ")
    for i, dep in enumerate(deps):
        is_last = (i == len(deps) - 1)
        lines += _render_tree(dep, graph, child_prefix, visited, is_last)

    return lines


def _render_flat(graph: dict, filter_stem: str = None) -> list:
    """
    Vue à plat : pour chaque module, liste ses dépendances directes.
    Si filter_stem est fourni, affiche seulement ce module et ce qui dépend de lui.
    """
    lines = []
    nodes = [filter_stem] if filter_stem else sorted(graph.keys())

    max_name = max((len(n) for n in nodes), default=10)
    sep      = "─" * (max_name + 2 + 4 + 50)

    lines.append(sep)
    lines.append(f"  {'Module':<{max_name}}    Dépendances directes")
    lines.append(sep)

    for stem in nodes:
        deps = graph.get(stem, [])
        if deps:
            dep_str = "  →  " + ",  ".join(deps)
        else:
            dep_str = "  →  (aucune)"
        lines.append(f"  {stem:<{max_name}}{dep_str}")

    lines.append(sep)
    return lines


def _render_reverse(graph: dict, target: str) -> list:
    """
    Qui dépend de `target` ?  (dépendances inversées)
    """
    dependants = []
    for stem, deps in graph.items():
        if target in deps:
            dependants.append(stem)

    lines = []
    lines.append(f"  Modules qui dépendent de  [{target}]")
    lines.append("  " + "─" * 50)
    if dependants:
        for d in sorted(dependants):
            lines.append(f"    ← {d}")
    else:
        lines.append("    (aucun)")
    return lines


def _render_matrix(graph: dict, stems: list) -> list:
    """
    Matrice de dépendances booléenne (X = dépend de).
    Limitée aux modules L2 pour rester lisible.
    """
    l2 = [s for s in stems if not s.startswith(_CORE_PREFIX)]
    if not l2:
        return ["  (aucun module L2 trouvé)"]

    col_w = max(len(s) for s in l2) + 1
    row_w = col_w

    # En-tête colonnes (noms tronqués à 6 car)
    SHORT = 6
    header_labels = [s[:SHORT].ljust(SHORT) for s in l2]

    lines = []
    # Ligne d'en-tête tournée verticalement (jusqu'à SHORT chars)
    for i in range(SHORT):
        row = " " * (row_w + 2)
        for label in header_labels:
            row += (label[i] if i < len(label) else " ") + " "
        lines.append(row)

    lines.append(" " * (row_w + 2) + ("──" * len(l2)))

    for stem in l2:
        row = f"  {stem:<{row_w - 2}}"
        deps = set(graph.get(stem, []))
        for col_stem in l2:
            row += "X " if col_stem in deps else ". "
        lines.append(row)

    lines.append("")
    lines.append("  X = dépend de (colonne)    . = pas de dépendance")
    return lines


def _render_layers(graph: dict) -> list:
    """
    Vue par couches (topological-style) :
    affiche les modules regroupés par niveau de dépendance.
    Couche 0 = pas de dépendance, couche N = dépend de couches < N.
    """
    # Calcul des niveaux (BFS simplifié, sans gestion de cycles stricts)
    all_nodes = set(graph.keys())
    # Ajouter aussi les dépendances core qui ne sont pas des stems L2
    for deps in list(graph.values()):
        for d in deps:
            all_nodes.add(d)

    levels = {}
    changed = True
    for n in all_nodes:
        levels[n] = 0

    MAX_ITER = 20
    it = 0
    while changed and it < MAX_ITER:
        changed = False
        it += 1
        for stem in list(graph.keys()):
            for dep in graph.get(stem, []):
                new_level = levels.get(dep, 0) + 1
                if new_level > levels.get(stem, 0):
                    levels[stem] = new_level
                    changed = True

    max_level = max(levels.values(), default=0)
    lines = []
    for lvl in range(max_level + 1):
        members = sorted(n for n, l in levels.items() if l == lvl)
        if not members:
            continue
        tag  = "(no deps)" if lvl == 0 else f"(depth {lvl})"
        line = f"  [{lvl}] {tag:<12}  " + "   ".join(members)
        lines.append(line)
    return lines


# ─── sous-commandes ───────────────────────────────────────────────────────────

def _cmd_tree(tokens: list, log_fn):
    """
    depgraph tree [<module>]
    Affiche un arbre de dépendances récursif pour un module ou tous les modules.
    """
    stems = _all_l2_stems()
    graph = _collect_deps(stems)

    # Ajouter les nœuds core dans le graphe (sans dépendances propres)
    all_nodes = set(graph.keys())
    for deps in list(graph.values()):
        for d in deps:
            if d not in graph:
                graph[d] = []
                all_nodes.add(d)

    target = tokens[0] if tokens else None

    if target:
        if target not in graph:
            log_fn(f"[depgraph] module inconnu : '{target}'")
            return 1
        roots = [target]
    else:
        # Racines = modules qui ne sont la dépendance d'aucun autre
        all_deps = set(d for deps in list(graph.values()) for d in deps)
        roots    = sorted(s for s in stems if s not in all_deps)
        if not roots:
            roots = sorted(stems)

    log_fn("  ARBRE DE DÉPENDANCES" + (f"  [{target}]" if target else "  [all roots]"))
    log_fn("  " + "═" * 56)
    for i, root in enumerate(roots):
        is_last = (i == len(roots) - 1)
        lines   = _render_tree(root, graph, prefix="  ", last=is_last)
        for line in lines:
            log_fn(line)
    log_fn("")
    log_fn("  [core] = module core/   sans tag = module L2")
    return 0


def _cmd_flat(tokens: list, log_fn):
    """
    depgraph flat [<module>]
    Liste les dépendances directes de chaque module (vue tabulaire).
    """
    stems  = _all_l2_stems()
    graph  = _collect_deps(stems)
    target = tokens[0] if tokens else None

    if target and target not in graph:
        log_fn(f"[depgraph] module inconnu : '{target}'")
        return 1

    log_fn("")
    for line in _render_flat(graph, filter_stem=target):
        log_fn(line)
    return 0


def _cmd_reverse(tokens: list, log_fn):
    """
    depgraph reverse <module>
    Affiche quels modules dépendent du module cible.
    """
    if not tokens:
        log_fn("[depgraph] reverse : nom de module manquant.")
        return 1

    target = tokens[0]
    stems  = _all_l2_stems()
    graph  = _collect_deps(stems)

    # Ajouter les nœuds core
    for deps in list(list(graph.values())):
        for d in deps:
            if d not in graph:
                graph[d] = []

    log_fn("")
    for line in _render_reverse(graph, target):
        log_fn(line)
    return 0


def _cmd_matrix(log_fn):
    """
    depgraph matrix
    Affiche une matrice booléenne des dépendances entre modules L2.
    """
    stems = _all_l2_stems()
    graph = _collect_deps(stems)

    log_fn("")
    log_fn("  MATRICE DE DÉPENDANCES  (modules L2 uniquement)")
    log_fn("  " + "═" * 56)
    for line in _render_matrix(graph, stems):
        log_fn(line)
    return 0


def _cmd_layers(log_fn):
    """
    depgraph layers
    Affiche les modules regroupés par profondeur de dépendance.
    """
    stems = _all_l2_stems()
    graph = _collect_deps(stems)

    # Ajouter les nœuds core
    for deps in list(list(graph.values())):
        for d in deps:
            if d not in graph:
                graph[d] = []

    log_fn("")
    log_fn("  COUCHES DE DÉPENDANCES  (profondeur topologique)")
    log_fn("  " + "═" * 56)
    for line in _render_layers(graph):
        log_fn(line)
    log_fn("")
    log_fn("  [0] = aucune dépendance   [N] = dépend de modules de niveau < N")
    return 0


def _cmd_focus(tokens: list, log_fn):
    """
    depgraph focus <module>
    Vue complète sur un module : ses deps, qui en dépend, sa couche.
    """
    if not tokens:
        log_fn("[depgraph] focus : nom de module manquant.")
        return 1

    target = tokens[0]
    stems  = _all_l2_stems()
    graph  = _collect_deps(stems)

    for deps in list(list(graph.values())):
        for d in deps:
            if d not in graph:
                graph[d] = []

    if target not in graph:
        log_fn(f"[depgraph] module inconnu : '{target}'")
        return 1

    log_fn("")
    log_fn(f"  FOCUS : {target}")
    log_fn("  " + "═" * 56)

    # Deps directes
    direct = graph.get(target, [])
    log_fn(f"  Dépendances directes ({len(direct)}) :")
    if direct:
        for d in direct:
            cat = "core" if d.startswith(_CORE_PREFIX) else "L2  "
            log_fn(f"    → {d}  [{cat}]")
    else:
        log_fn("    (aucune)")

    log_fn("")

    # Qui en dépend
    log_fn("  Utilisé par :")
    users = sorted(s for s, deps in graph.items() if target in deps)
    if users:
        for u in users:
            log_fn(f"    ← {u}")
    else:
        log_fn("    (aucun module ne dépend de lui)")

    log_fn("")

    # Arbre complet depuis ce module
    log_fn("  Arbre complet :")
    lines = _render_tree(target, graph, prefix="  ", last=True)
    for line in lines:
        log_fn(line)

    return 0


# ─── point d'entrée R-ECO3 ───────────────────────────────────────────────────

def R_ECO3(inp):
    """
    depgraph <sous-commande> [module]

    Sous-commandes :
      tree   [module]   Arbre récursif de dépendances
      flat   [module]   Liste tabulaire des dépendances directes
      reverse <module>  Qui dépend de ce module ?
      matrix            Matrice booléenne (modules L2)
      layers            Regroupement par profondeur topologique
      focus  <module>   Vue complète (deps + utilisateurs + arbre)
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
        "tree":    lambda: _cmd_tree(rest, log_fn),
        "flat":    lambda: _cmd_flat(rest, log_fn),
        "reverse": lambda: _cmd_reverse(rest, log_fn),
        "matrix":  lambda: _cmd_matrix(log_fn),
        "layers":  lambda: _cmd_layers(log_fn),
        "focus":   lambda: _cmd_focus(rest, log_fn),
    }

    if subcmd not in dispatch:
        log_fn(f"[depgraph] Sous-commande inconnue : '{subcmd}'")
        log_fn("  Commandes : " + ", ".join(dispatch.keys()))
        return 1

    return dispatch[subcmd]()


# ─── métadonnées R-ECO3 ──────────────────────────────────────────────────────

def R_ECO3dep():
    return (
        ("3.5.1b",),
        (
            ("core.apix",  ("1.1",)),
            ("core.trail", ("1.1",)),
            ("core.utils", ("1.1",)),
        ),
    )


def R_ECO3inf():
    return {
        "name":        "depgraph",
        "desc":        "Graphe de dépendances ASCII des modules R-ECO3",
        "help":        (
            "depgraph tree [module]  |  flat [module]  |  reverse <module>\n"
            "depgraph matrix         |  layers          |  focus <module>"
        ),
        "version_mod": "1.0",
        "L2Module":    True,
        "alias_rules": "/* = depgraph ||| * = depgraph /*",
        "manual": (
            "DEPGRAPH — visualiseur de dépendances R-ECO3\n"
            "══════════════════════════════════════════════════════\n\n"
            "DESCRIPTION\n"
            "  Génère dans la console des représentations ASCII du graphe\n"
            "  de dépendances entre modules L2 et modules core.\n"
            "  S'appuie sur R_ECO3dep() de chaque module présent dans\n"
            "  modules/. Aucune dépendance externe requise.\n\n"
            "SOUS-COMMANDES\n\n"
            "  depgraph tree [<module>]\n"
            "      Arbre récursif de dépendances (style `tree`).\n"
            "      Sans argument : affiche depuis les racines (modules\n"
            "      qui ne sont la dépendance d'aucun autre).\n"
            "      Avec argument : arbre depuis ce module uniquement.\n\n"
            "  depgraph flat [<module>]\n"
            "      Vue tabulaire : une ligne par module avec ses\n"
            "      dépendances directes. Optionnellement filtré.\n\n"
            "  depgraph reverse <module>\n"
            "      Affiche quels modules dépendent du module cible.\n"
            "      Utile pour évaluer l'impact d'une modification.\n\n"
            "  depgraph matrix\n"
            "      Matrice booléenne NxN des dépendances entre modules L2.\n"
            "      X = dépend de (colonne)   . = pas de dépendance.\n\n"
            "  depgraph layers\n"
            "      Regroupe les modules par profondeur topologique.\n"
            "      Couche 0 = pas de dépendance.\n"
            "      Couche N = dépend de modules de niveau < N.\n\n"
            "  depgraph focus <module>\n"
            "      Vue complète sur un module :\n"
            "        · dépendances directes (avec catégorie core/L2)\n"
            "        · liste des modules qui l'utilisent\n"
            "        · arbre complet depuis ce module\n\n"
            "EXEMPLES\n"
            "  depgraph tree\n"
            "  depgraph tree raven\n"
            "  depgraph flat mycelium\n"
            "  depgraph reverse banana\n"
            "  depgraph matrix\n"
            "  depgraph layers\n"
            "  depgraph focus spider\n"
        ),
    }