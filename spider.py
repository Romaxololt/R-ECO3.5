from core.trail import ROOT
import core

def R_ECO3(inp: dict):
    """Point d'entrée du module spider."""
    args = inp["args"]
    log_fn = inp["logfn"]
    positional, kv = core.utils.parse_command(args)

    verify_flag   = kv.get("v") is True or kv.get("verify")   is True
    dep_flag      = kv.get("d") is True or kv.get("dep")      is True
    info_flag     = kv.get("i") is True or kv.get("info")     is True
    run_flag      = kv.get("r") is True or kv.get("run")      is True
    debug_flag    = kv.get("g") is True or kv.get("debug")    is True
    no_print_flag = kv.get("n") is True or kv.get("no-print") is True
    l2verif_flag  = kv.get("only-l2", False)
    run_args      = kv.get("args", "")

    # ── Mode silencieux ────────────────────────────────────────────
    captured_lines = []

    if no_print_flag:
        def _log(msg=""):
            captured_lines.append(msg)
    else:
        def _log(msg=""):
            log_fn(msg)

    # ── Aide ───────────────────────────────────────────────────────
    if kv.get("h") is True:
        _log("Usage : spider <module> [-v] [-d] [-i] [-r] [--args=\"...\"] [-n] [-h]")
        _log("")
        _log("  <module>            Nom du module à inspecter")
        _log("  -v / --verify       Vérifie les dépendances (retourne 1 si manquantes)")
        _log("  -d / --dep          Affiche les dépendances au format dict")
        _log("  -i / --info         Affiche les informations au format dict")
        _log("  -r / --run          Lance le module (après --verify si combiné)")
        _log("  -g / --debug        Lance le module en mode debug")
        _log("  --args=\"...\"        Arguments passés au module lors du --run")
        _log("  -n / --no-print     Silencieux : retourne (code, [lignes]) sans imprimer")
        _log("  -h                  Affiche cette aide")
        _log("")
        _log("  Exemple : spider module -vr --args=\"hello\"")
        _log("  Exemple : spider module -vn  (mode silencieux)")
        return {"status": 0, "value": captured_lines if no_print_flag else None}

    module = positional[0]

    # ── Verify ────────────────────────────────────────────────────
    if verify_flag:
        from core.trail import MODULES_DIR

        visited  = {}
        errors   = []
        warnings = []

        def _resolve_path(mod_name):
            # Les modules core.* sont gérés automatiquement par le système,
            # on ne résout que les modules applicatifs.
            return MODULES_DIR / f"{mod_name}.py"

        def _get_version(mod_name):
            res = core.apix.R_ECO3({"args": f"inf {mod_name}", "logfn": lambda x:x})
            if not isinstance(res, dict):
                return None
            if res.get("status") == 0:
                value = res.get("value")
                if isinstance(value, dict):
                    return value.get("version_mod")
            return None

        def _get_reco(mod_name):
            """Retourne la version reco déclarée par le module, ou None."""
            res = core.apix.R_ECO3({"args": f"dep {mod_name}", "logfn": lambda x:x})
            if not isinstance(res, dict) or res.get("status") != 0:
                return None
            value = res.get("value")
            if not isinstance(value, dict):
                return None
            reco = value.get("reco")
            return reco[0] if isinstance(reco, (list, tuple)) and reco else None

        def _fetch_deps(mod_name):
            """
            Retourne [(child_name, versions_list), ...].
            Ignore les modules core.* (gérés automatiquement).
            [] si pas de dépendances ou format inattendu.
            """
            res = core.apix.R_ECO3({"args": f"dep {mod_name}", "logfn": lambda x:x})
            if not isinstance(res, dict) or res.get("status") != 0:
                return []
            value = res.get("value")
            if not isinstance(value, dict):
                return []
            required_mods = value.get("module")
            if not isinstance(required_mods, (list, tuple)):
                return []

            result = []
            for entry in required_mods:
                if not isinstance(entry, dict):
                    continue
                for child_name, child_versions in entry.items():
                    # Les modules core.* sont inclus automatiquement — on skip
                    if child_name.startswith("core."):
                        continue
                    result.append((child_name, child_versions))
            return result

        def _check_reco_compat(mod_name):
            """
            Vérifie que la version reco déclarée par mod_name est compatible
            avec la version reco du système (core).
            Retourne True si OK, False sinon.
            """
            reco = _get_reco(mod_name)
            if reco is None:
                return True  # pas de contrainte déclarée

            sys_reco = _get_reco("core") if hasattr(core, "apix") else None
            if sys_reco is None:
                return True  # impossible de vérifier, on laisse passer

            try:
                result = core.utils.check_version(reco, sys_reco)
                if result is True:
                    return True
                if isinstance(result, tuple) and result[0] == -1:
                    warnings.append(
                        f"{mod_name} : version reco mineure différente "
                        f"(déclarée {reco}, système {sys_reco})"
                    )
                    return True
                errors.append(
                    f"{mod_name} : version reco incompatible "
                    f"(déclarée {reco}, système {sys_reco})"
                )
                return False
            except Exception:
                return True

        def _check_recursive(mod_name, required_versions=None):
            # ── 1. Existence du fichier ──────────────────────────────
            if not _resolve_path(mod_name).exists():
                errors.append(f"{mod_name} : fichier introuvable")
                return

            # ── 2. Vérification de version si exigée par le parent ───
            actual_ver = _get_version(mod_name)
            if required_versions and actual_ver:
                results = []
                for v_req in required_versions:
                    try:
                        results.append(core.utils.check_version(v_req, actual_ver))
                    except Exception:
                        pass

                if not results or not any(r is True or (isinstance(r, tuple) and r[0] == -1) for r in results):
                    errors.append(
                        f"{mod_name} : version incompatible "
                        f"(requis {'/'.join(str(v) for v in required_versions)}, installé {actual_ver})"
                    )
                elif any(isinstance(r, tuple) and r[0] == -1 for r in results) and not any(r is True for r in results):
                    warnings.append(
                        f"{mod_name} : version mineure différente "
                        f"(requis {'/'.join(str(v) for v in required_versions)}, installé {actual_ver})"
                    )

            # ── 3. Cycle / déjà traité → stop ────────────────────────
            if mod_name in visited:
                return
            visited[mod_name] = actual_ver

            # ── 4. Compatibilité reco (core) ─────────────────────────
            _check_reco_compat(mod_name)

            # ── 5. Récursion dans les dépendances applicatives ───────
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
            return {"status": 1, "value": captured_lines if no_print_flag else None}

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
            res = core.apix.R_ECO3({"args": f"inf {module}", "logfn": _log})
            if not isinstance(res, dict) or res.get("status") != 0:
                _log(f"[spider] Impossible de récupérer les informations de '{module}'.")
                return {"status": 1, "value": captured_lines if no_print_flag else None}
            inf = res.get("value")
            if not isinstance(inf, dict):
                _log(f"[spider] Le module '{module}' n'a pas de metadata.")
                return {"status": 1, "value": captured_lines if no_print_flag else None}
            if inf.get("L2Module") is not True:
                _log(f"[spider] Le module '{module}' n'a pas de flag L2")
                return {"status": 0, "value": captured_lines if no_print_flag else None}

        # Construit le payload en héritant de inp, puis on écrase ce qui doit changer
        run_payload = {**inp, "args": f"run {module} {run_args}".strip(), "logfn": _log}

        res = core.apix.R_ECO3(run_payload)
        if not isinstance(res, dict):
            _log(f"[spider] Échec du lancement de '{module}'.")
            return {"status": 1, "value": captured_lines if no_print_flag else None}
        return res

    # ── Dépendances (dict) ────────────────────────────────────────
    if dep_flag:
        res = core.apix.R_ECO3({"args": f"dep {module}","logfn": _log})
        if not isinstance(res, dict) or res.get("status") != 0:
            _log(f"[spider] Impossible de récupérer les dépendances de '{module}'.")
            return {"status": 1, "value": captured_lines if no_print_flag else None}
        deps = res.get("value")
        if no_print_flag:
            captured_lines.append(deps)
        else:
            log_fn(repr(deps))

    # ── Informations (dict) ───────────────────────────────────────
    if info_flag:
        res = core.apix.R_ECO3({"args": f"inf {module}","logfn": _log})
        if not isinstance(res, dict) or res.get("status") != 0:
            _log(f"[spider] Impossible de récupérer les informations de '{module}'.")
            return {"status": 1, "value": captured_lines if no_print_flag else None}
        inf = res.get("value")
        if no_print_flag:
            captured_lines.append(inf)
        else:
            log_fn(repr(inf))

    return {"status": 0, "value": captured_lines if no_print_flag else None}


def R_ECO3dep():
    return {
        "reco": ["3.5.1b"],
        "module": [],
    }


def R_ECO3inf():
    return {
        "name":        "spider",
        "desc":        "Module inspector — verify dependencies, fetch metadata, and run modules",
        "help":        "Inspects any RAVEN module: recursively verifies dependency tree, displays metadata and dep dicts, and optionally launches the module. Supports silent mode for programmatic use.",
        "version_mod": "2.1",
        "L2Module":    True,
        "alias_rules": "spider /* = banana err --msg='This module cannot be run without arguments. Please refer to the manual for usage instructions.'",
        "manual": (
            "spider — Module inspector  v2.0\n"
            "===============================\n"
            "\n"
            "SYNOPSIS\n"
            "    spider <module> [flags] [--args=\"...\"]\n"
            "\n"
            "COMMANDS\n"
            "    -v / --verify\n"
            "        Recursively checks the full dependency tree.\n"
            "        Core modules are automatically included and only their\n"
            "        declared reco version is checked against the system.\n"
            "\n"
            "    -d / --dep\n"
            "        Prints the raw dependency dict returned by R_ECO3dep().\n"
            "\n"
            "    -i / --info\n"
            "        Prints the raw metadata dict returned by R_ECO3inf().\n"
            "\n"
            "    -r / --run\n"
            "        Runs the module through core.apix.\n"
            "\n"
            "    -g / --debug\n"
            "        Enables verbose output during verification and execution.\n"
            "\n"
            "    --args=\"...\"\n"
            "        Forwards arguments to the target module when running it.\n"
            "\n"
            "    --only-l2\n"
            "        Runs the module only if L2Module is True.\n"
            "\n"
            "    -n / --no-print\n"
            "        Silent mode: returns (code, [lines]) instead of printing.\n"
            "\n"
            "EXAMPLES\n"
            "    spider raven -v\n"
            "    spider raven -vr --args=\"hello\"\n"
            "    spider raven -vn\n"
        ),
    }