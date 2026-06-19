from pathlib import Path
import os, sys, time
import json

def _lister_fichiers(dossier) -> list[str]:
    return [
        f for f in os.listdir(dossier)
        if os.path.isfile(os.path.join(dossier, f))
    ]

def _wait_for_cancel(timeout: float, log_fn) -> bool:
    """
    Affiche un compte à rebours et retourne True si l'utilisateur annule.
    Utilise msvcrt (Windows, sans droits admin) ou select (Unix).
    """
    steps = int(timeout * 10)

    if sys.platform == "win32":
        import msvcrt
        for i in range(steps):
            remaining = timeout - i * 0.1
            print(f"\r  NEST> Appuyez sur une touche pour annuler... {remaining:.1f}s ", end="", flush=True)
            if msvcrt.kbhit():
                msvcrt.getch()
                print()
                return True
            time.sleep(0.1)
    else:
        import select
        for i in range(steps):
            remaining = timeout - i * 0.1
            print(f"\r  NEST> Appuyez sur Entrée pour annuler... {remaining:.1f}s ", end="", flush=True)
            r, _, _ = select.select([sys.stdin], [], [], 0)
            if r:
                sys.stdin.readline()
                print()
                return True
            time.sleep(0.1)

    print()
    return False


def R_ECO3(useless):
    log_fn = print
    # ── DEBUG: import core ──────────────────────────────────────────────
    try:
        import core
    except Exception as exc:
        log_fn(f"NEST> Impossible de charger le module : core introuvable. (errno: 1)")
        log_fn(f"NEST> [DEBUG] exception import core : {type(exc).__name__}: {exc}")
        log_fn(f"NEST> [DEBUG] sys.path = {sys.path}")
        return

    ROOT = core.trail.MODULES_DIR.parent

    #! Verification core
    missing_core = []
    for rel in ("core/hive.py", "core/utils.py", "core/apix.py", "modules/spider.py"):
        p = ROOT / rel
        if not p.exists():
            missing_core.append(str(p))
    if missing_core:
        log_fn("NEST> R-ECOSYSTEM corrompue (modules manquants). (errno: 10)")
        log_fn(f"NEST> [DEBUG] fichiers manquants : {missing_core}")
        return
    
    debug = False

    with core.hive.Hive(str(core.trail.DB_FILE)) as db:
        debug = db.get("§sys:global:debug.nest", "False") == "True"
        # ── DEBUG: chemins résolus ──────────────────────────────────────────
        if debug :log_fn(f"NEST> [DEBUG] core.__file__         = {getattr(core, '__file__', '?')}")
        if debug :log_fn(f"NEST> [DEBUG] core.trail.MODULES_DIR = {core.trail.MODULES_DIR}")
        if debug :log_fn(f"NEST> [DEBUG] core.trail.DB_FILE     = {core.trail.DB_FILE}")
        if debug :log_fn(f"NEST> [DEBUG] core.trail.DB_FILE existe ? = {Path(core.trail.DB_FILE).exists()}")
        if debug :log_fn(f"NEST> [DEBUG] ROOT (résolu)           = {ROOT}")
        if debug :log_fn(f"NEST> [DEBUG] cwd                     = {os.getcwd()}")
        # ── DEBUG: contenu brut de la DB au moment de l'ouverture ───────────
        try:
            all_keys = list(db)
            if debug :log_fn(f"NEST> [DEBUG] {len(all_keys)} clé(s) trouvée(s) dans la DB ouverte par nest :")
            for k in sorted(all_keys):
                try:
                    v = db.get(k)
                    v_disp = (v[:80] + "…") if isinstance(v, str) and len(v) > 80 else v
                    if debug :log_fn(f"NEST> [DEBUG]    {k!r} = {v_disp!r}  [{type(v).__name__}]")
                except Exception as exc:
                    log_fn(f"NEST> [DEBUG]    {k!r} = <erreur lecture: {exc}>")
        except Exception as exc:
            log_fn(f"NEST> [DEBUG] impossible de lister les clés : {exc}")

        # --- LOG NEST: garde les 25 derniers logs du boot ---
        def _load_boot_logs() -> list[str]:
            raw = db.get("§sys:global:log.nest", "[]")
            if isinstance(raw, list):
                data = raw
            else:
                try:
                    data = json.loads(raw)
                except:
                    data = []
            return data if isinstance(data, list) else []

        boot_logs = _load_boot_logs()
        original_log_fn = log_fn

        def boot_log(msg):
            nonlocal boot_logs
            original_log_fn(msg)
            boot_logs.append(str(msg))
            boot_logs = boot_logs[-25:]
            db.set("§sys:global:log.nest", json.dumps(boot_logs, ensure_ascii=False))

        log_fn = boot_log
        # ---------------------------------------------------

        if debug:
            log_fn("NEST> Procédure d'initialisation en cours...")
            log_fn("NEST> Core modules OK.")

        required_keys = ("§sys:global:version.nest", "§sys:global:codename.nest", "§sys:global:checker.nest")

        # ── DEBUG: vérification clé par clé avec 'in db' ET 'exists' si dispo ─
        for k in required_keys:
            present_in = k in db
            present_exists = None
            if hasattr(db, "exists"):
                try:
                    present_exists = db.exists(k)
                except Exception as exc:
                    present_exists = f"<erreur: {exc}>"
            if debug :log_fn(f"NEST> [DEBUG] clé {k!r} : 'in db'={present_in}  db.exists()={present_exists}")

        if any(k not in db for k in required_keys):
            missing = [k for k in required_keys if k not in db]
            log_fn(
                f"NEST> Base de données corrompue (clés manquantes : {', '.join(missing)}). (errno: 8)"
            )
            if debug :log_fn(f"NEST> [DEBUG] DB path utilisé    = {core.trail.DB_FILE}")
            if debug :log_fn(f"NEST> [DEBUG] DB taille fichier   = {os.path.getsize(core.trail.DB_FILE) if Path(core.trail.DB_FILE).exists() else 'N/A'}")
            if debug :log_fn(f"NEST> [DEBUG] Astuce: vérifie que le module _start écrit bien dans ce même chemin "
                f"(comparer avec current_dir / 'data' / 'data.hive' utilisé par _start.py).")
            return

        if db["§sys:global:version.nest"] != "3.5.2b":
            log_fn("NEST> Version de R-ECO inattendue. (errno: 6)")
            if debug :log_fn(f"NEST> [DEBUG] valeur trouvée = {db['§sys:global:version.nest']!r} (attendu '3.5.2b')")
            return
        if db["§sys:global:checker.nest"] != "0" * 98 :
            log_fn("NEST> Checker mismatch. (errno: 5)")
            val = db["§sys:global:checker.nest"]
            if debug :log_fn(f"NEST> [DEBUG] valeur trouvée (len={len(val)}) = {val!r}")
            return
        if db["§sys:global:codename.nest"] != "Ant":
            log_fn("NEST> Codename incompatible. (errno: 7)")
            if debug :log_fn(f"NEST> [DEBUG] valeur trouvée = {db['§sys:global:codename.nest']!r} (attendu 'Ant')")
            return

        if debug:
            log_fn("NEST> Base de données (minimal) OK.")

        if "§sys:global:bmodule.nest" not in db:
            log_fn("NEST> Initialisation en cours...")

            files = _lister_fichiers(core.trail.MODULES_DIR)
            if debug :log_fn(f"NEST> [DEBUG] fichiers dans MODULES_DIR : {files}")

            if "§sys:global:bmodule.nest" not in db:
                if "raven.py" in files:
                    db.set("§sys:global:bmodule.nest", "raven.py")
                else:
                    log_fn("NEST> raven.py (default boot module) introuvable, veuillez ajouter un boot module via _start : set §sys:global:bmodule.nest <module>. (errno: 2)")
                    return

            if "spider.py" not in files:
                log_fn("NEST> spider.py introuvable, veuillez l'ajouter. (errno: 13)")
                return

            bmodule = db["§sys:global:bmodule.nest"]
            log_fn(f"NEST> Module de démarrage : {bmodule}")

            if bmodule not in files:
                log_fn(f"NEST> Module '{bmodule}' introuvable. (errno: 3)")

        else:
            bmodule = db["§sys:global:bmodule.nest"]
            if debug:
                log_fn(f"NEST> Module : {bmodule}")

        if debug:
            log_fn("NEST> Vérification Bmodule.dep")
        spider_result = core.apix.R_ECO3({"args": "run spider raven -v" + (" -g" if debug else ""), 'logfn': log_fn})
        if debug :log_fn(f"NEST> [DEBUG] résultat apix run spider : {spider_result}")
        if spider_result["status"] != 0:
            log_fn(f"NEST> Bmodule.dep erreur. (errno: 11)")
            return

        log_fn("NEST> Démarrage dans 2 secondes...")
        if _wait_for_cancel(2.0, log_fn):
            log_fn("NEST> Démarrage annulé par l'utilisateur.")
            core.apix.R_ECO3({"args": "run _start", "logfn": print})
            return

        log_fn(f"NEST> Chargement de '{bmodule}'...")
        bmodule = bmodule.replace(".py", "")
        r = core.apix.R_ECO3({"args": f"run {bmodule}", "logfn": print, "db": db})
        if debug :log_fn(f"NEST> [DEBUG] résultat apix run {bmodule} : {r}")

        if r["status"] != 0:
            log_fn(f"NEST> Module de démarrage erreur, status: {r['status']}. (errno: 12)")
            return
        

def R_ECO3dep():
    return {
        "reco": ["3.5.2b"],
        "module": []
    }


def R_ECO3inf():
    return {
        "name":        "nest",
        "desc":        "Bootloader for R-ECOSYSTEM — validates environment and launches the main module",
        "help":        "Checks database integrity, resolves the boot module, and launches it after a cancellable countdown. No arguments required.",
        "version_mod": "2.1",
        "L2Module":    False,
        "manual": (
            "nest — Bootloader for R-ECOSYSTEM  v1.1\n"
            "=====================================\n"
            "\n"
            "SYNOPSIS\n"
            "    nest\n"
            "\n"
            "DESCRIPTION\n"
            "    Runs the full boot sequence for R-ECOSYSTEM.\n"
            "    It validates the environment, checks database integrity, resolves the boot module,\n"
            "    waits for a cancellable countdown, then launches the configured module.\n"
            "\n"
            "EXAMPLES\n"
            "    nest\n"
        ),
    }