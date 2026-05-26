from core.trail import ROOT


def R_ECO3(args: str, log_fn=print):
    """Point d'entrée du module spider."""
    try:
        import core
    except Exception as e:
        log_fn(f"[spider] Impossible de charger core : {e}")
        return 1

    positional, kv = core.utils.parse_command(args)

    verify_flag  = kv.get("v") is True or kv.get("verify") is True
    dep_flag     = kv.get("d") is True or kv.get("dep")    is True
    info_flag    = kv.get("i") is True or kv.get("info")   is True
    run_flag     = kv.get("r") is True or kv.get("run")    is True
    debug_flag   = kv.get("g") is True or kv.get("debug")  is True
    no_print_flag = kv.get("n") is True or kv.get("no-print") is True
    l2verif_flag = kv.get("only-l2", False)
    run_args     = kv.get("args", "")

    # ── Mode silencieux ────────────────────────────────────────────
    # Quand -n / --no-print est actif, on capture toutes les lignes
    # et on les retourne sous forme de (code, [lignes]) à la fin.
    captured_lines = []

    if no_print_flag:
        def _log(msg=""):
            captured_lines.append(msg)
    else:
        def _log(msg=""):
            log_fn(msg)

    # ── Aide ───────────────────────────────────────────────────────
    if kv.get("h") is True or not positional:
        _log("Usage : spider <module> [-v] [-d] [-i] [-r] [--args=\"...\"] [-n] [-h]")
        _log("")
        _log("  <module>            Nom du module à inspecter")
        _log("  -v / --verify       Vérifie les dépendances (retourne 1 si manquantes)")
        _log("  -d / --dep          Affiche les dépendances au format tuple")
        _log("  -i / --info         Affiche les informations au format tuple")
        _log("  -r / --run          Lance le module (après --verify si combiné)")
        _log("  -g / --debug        Lance le module en mode debug")
        _log("  --args=\"...\"        Arguments passés au module lors du --run")
        _log("  -n / --no-print     Silencieux : retourne (code, [lignes]) sans imprimer")
        _log("  -h                  Affiche cette aide")
        _log("")
        _log("  Exemple : spider module -vr --args=\"hello\"")
        _log("  Exemple : spider module -vn  (mode silencieux)")
        code = 0 if kv.get("h") is True else 1
        return (code, captured_lines) if no_print_flag else code

    module = positional[0]

    # ── Verify ────────────────────────────────────────────────────
    if verify_flag:
        from core.trail import MODULES_DIR
        import importlib

        visited  = {}
        errors   = []
        warnings = []

        def _resolve_path(mod_name):
            if mod_name.startswith("core."):
                return ROOT / "core" / f"{mod_name[5:]}.py"
            return MODULES_DIR / f"{mod_name}.py"

        def _load_mod(mod_name):
            """Charge et retourne le module Python (avec cache sys.modules)."""
            if mod_name.startswith("core."):
                return importlib.import_module(mod_name)
            return core.apix.load_module(mod_name)

        def _call_fn(mod_name, fn_name):
            """
            Appelle fn_name sur le module.
            Retourne (0, résultat) ou (1, None).
            """
            try:
                mod = _load_mod(mod_name)
                fn  = getattr(mod, fn_name, None)
                if fn is None:
                    return 1, None
                return 0, fn()
            except Exception as exc:
                if debug_flag:
                    _log(f"[spider:{module}] ! _call_fn({mod_name}, {fn_name}): {exc}")
                return 1, None

        def _get_version(mod_name):
            status, value = _call_fn(mod_name, "R_ECO3inf")
            if status == 0 and isinstance(value, dict):
                return value.get("version_mod")
            return None

        def _fetch_deps(mod_name):
            """
            Retourne [(child_name, versions_tuple), ...].
            [] si pas de R_ECO3dep ou format inattendu.
            """
            status, value = _call_fn(mod_name, "R_ECO3dep")
            if status != 0 or not isinstance(value, tuple) or len(value) < 2:
                return []
            required_mods = value[1]
            if not isinstance(required_mods, (tuple, list)):
                return []
            return [
                entry for entry in required_mods
                if isinstance(entry, (tuple, list)) and len(entry) >= 2
            ]

        def _check_recursive(mod_name, required_versions=None):
            # ── 1. Existence du fichier ──────────────────────────────
            if not _resolve_path(mod_name).exists():
                errors.append(f"{mod_name} : fichier introuvable")
                return

            # ── 2. Version (même si déjà visité : plusieurs parents
            #        peuvent imposer des contraintes différentes) ──────
            actual_ver = _get_version(mod_name)
            if required_versions and actual_ver:
                if actual_ver not in required_versions:
                    results = []
                    for v_req in required_versions:
                        try:
                            results.append(core.utils.check_version(v_req, actual_ver))
                        except Exception:
                            pass

                    if any(r is True for r in results):
                        pass  # ✓ compatible avec au moins une version requise
                    elif any(isinstance(r, tuple) and r[0] == -1 for r in results):
                        warnings.append(
                            f"{mod_name} : version mineure différente "
                            f"(requis {'/'.join(required_versions)}, installé {actual_ver})"
                        )
                    else:
                        errors.append(
                            f"{mod_name} : version incompatible "
                            f"(requis {'/'.join(required_versions)}, installé {actual_ver})"
                        )

            # ── 3. Cycle / déjà traité → stop ────────────────────────
            if mod_name in visited:
                return
            visited[mod_name] = actual_ver

            # ── 4. Récursion dans les dépendances ────────────────────
            deps = _fetch_deps(mod_name)
            if debug_flag and deps:
                _log(f"[spider:{module}] ~ {mod_name} → {[d[0] for d in deps]}")
            for child_name, child_versions in deps:
                _check_recursive(child_name, child_versions)

        _check_recursive(module)

        for w in warnings:
            _log(f"[spider:{module}] ⚠ {w}")
        for e in errors:
            _log(f"[spider:{module}] ✗ {e}")

        if errors:
            return (1, captured_lines) if no_print_flag else 1

        if debug_flag:
            _log(
                f"[spider:{module}] ✓ Toutes les dépendances sont présentes "
                f"({len(visited)} module(s) vérifié(s))."
            )
            for m, v in visited.items():
                _log(f"[spider:{module}] ✓ {m} ({v})")

    # ── Run ───────────────────────────────────────────────────────
    if run_flag:
        if l2verif_flag:
            res = core.apix.R_ECO3(f"inf {module}", _log)
            code_inf, inf = res if isinstance(res, tuple) and len(res) == 2 else (1, None)
            if code_inf != 0 or inf is None:
                _log(f"[spider] Impossible de récupérer les informations de '{module}'.")
                return 1
            if not isinstance(inf, dict):
                _log(f"[spider] Le module '{module}' n'a pas de metadata.")
                return 1
            
            if inf["L2Module"] is not True:
                if not no_print_flag:
                    log_fn(f"[spider] Le module '{module}' n'a pas de flag L2")
                return 0
            
        res = core.apix.R_ECO3(f"run {module} {run_args}".strip(), _log)
        code_run, result = res if isinstance(res, tuple) and len(res) == 2 else (1, None)
        if code_run != 0 or result is None:
            _log(f"[spider] Échec du lancement de '{module}'.")
            return (1, captured_lines) if no_print_flag else 1
        if no_print_flag:
            return (result if isinstance(result, int) else 0, captured_lines)
        return result if isinstance(result, int) else 0

    # ── Dépendances (tuple) ───────────────────────────────────────
    if dep_flag:
        res = core.apix.R_ECO3(f"dep {module}", _log)
        code_dep, deps = res if isinstance(res, tuple) and len(res) == 2 else (1, None)
        if code_dep != 0 or deps is None:
            _log(f"[spider] Impossible de récupérer les dépendances de '{module}'.")
            return (1, captured_lines) if no_print_flag else 1
        if no_print_flag:
            captured_lines.append(deps)
        else:
            log_fn(repr(deps))

    # ── Informations (tuple) ──────────────────────────────────────
    if info_flag:
        res = core.apix.R_ECO3(f"inf {module}", _log)
        code_inf, inf = res if isinstance(res, tuple) and len(res) == 2 else (1, None)
        if code_inf != 0 or inf is None:
            _log(f"[spider] Impossible de récupérer les informations de '{module}'.")
            return (1, captured_lines) if no_print_flag else 1
        if no_print_flag:
            captured_lines.append(inf)
        else:
            log_fn(repr(inf))

    return (0, captured_lines) if no_print_flag else 0


def R_ECO3dep():
    return (
        ("3.5.1b",),
        (
            ("core.hive", ("1.1",)),
            ("core.apix", ("1.1",)),
        ),
    )


def R_ECO3inf():
    return {
        "name":        "spider",
        "desc":        "Module inspector — verify dependencies, fetch metadata, and run modules",
        "help":        "Inspects any RAVEN module: recursively verifies dependency tree, displays metadata and dep tuples, and optionally launches the module. Supports silent mode for programmatic use.",
        "version_mod": "1.8",
        "L2Module":    True,
        "manual": (
            "spider <module> [flags] [--args=\"...\"]\n\n"
            "AVAILABLE FLAGS:\n"
            "  -v / --verify\n"
            "    Recursively checks the module's full dependency tree.\n"
            "    Returns exit code 1 if any dependency is missing or incompatible.\n\n"
            "  -d / --dep\n"
            "    Prints the module's raw dependency tuple (R_ECO3dep).\n\n"
            "  -i / --info\n"
            "    Prints the module's raw metadata dict (R_ECO3inf).\n\n"
            "  -r / --run\n"
            "    Launches the module via core.apix. Can be combined with -v.\n\n"
            "  -g / --debug\n"
            "    Enables verbose output during dependency verification and run.\n\n"
            "  --args=\"...\"\n"
            "    Arguments forwarded to the module when using -r.\n\n"
            "  --only-l2\n"
            "    Launches the module only if it have the tag 'L2Module' True.\n\n"
            "  -n / --no-print\n"
            "    Silent mode: suppresses all output and returns (code, [lines]) instead.\n\n"
            "  -h\n"
            "    Displays usage help.\n\n"
            "EXAMPLES:\n"
            "  spider raven -v\n"
            "  spider raven -vr --args=\"hello\"\n"
            "  spider raven -vn\n"
        )
    }