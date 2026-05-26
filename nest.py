from pathlib import Path
import os, sys, time


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
            print(f"\r  [NEST] Appuyez sur une touche pour annuler... {remaining:.1f}s ", end="", flush=True)
            if msvcrt.kbhit():
                msvcrt.getch()  # vide le buffer
                print()
                return True
            time.sleep(0.1)
    else:
        import select
        for i in range(steps):
            remaining = timeout - i * 0.1
            print(f"\r  [NEST] Appuyez sur Entrée pour annuler... {remaining:.1f}s ", end="", flush=True)
            r, _, _ = select.select([sys.stdin], [], [], 0)
            if r:
                sys.stdin.readline()
                print()
                return True
            time.sleep(0.1)

    print()
    return False


def R_ECO3(args, log_fn=print):

    ROOT = Path(__file__).resolve().parent.parent
    CP = ROOT / "core" / "trail.py"
    if not CP.exists():
        log_fn(f"[NEST] Impossible de charger le module : {CP} introuvable. (errno: 1)")
        return

    import core
    
    if not (ROOT/"core"/"hive.py").exists() or not (ROOT/"core"/"utils.py").exists() or not (ROOT/"core"/"apix.py").exists() or not (ROOT/"modules"/"spider.py").exists():
        log_fn("[NEST] R-ECOSYSTEM corrompue (modules manquants). (errno: 10)")
        return

    db = core.hive.HiveFS(str(core.trail.DB_FILE))

    # Pré-vérification des clés obligatoires
    required_keys = ("version", "reco_magic", "reco_version", "reco_codename")
    if any(k not in db for k in required_keys):
        log_fn("[NEST] Base de données corrompue (clés manquantes). (errno: 8)")
        return

    if db["version"] != "1.0":
        log_fn("[NEST] Version de base de données inattendue. (warno: 4)")
    if db["reco_magic"] != "R_ECO3":
        log_fn("[NEST] Magic mismatch. (errno: 5)")
        return
    if db["reco_version"] != "3.5.1b":
        log_fn("[NEST] Version R_ECO incompatible. (errno: 6)")
        return
    if db["reco_codename"] != "Ant":
        log_fn("[NEST] Codename incompatible. (errno: 7)")
        return

    # debug résolu avant le if/else pour être disponible partout
    debug = db.get("§sys:nest:debug", "False") == "True"

    if "§sys:nest:status" not in db or "§sys:global:boot:bmodule" not in db:
        db.set("§sys:nest:status", "1")
        log_fn("[NEST] Initialisation en cours...")

        files = _lister_fichiers(core.trail.MODULES_DIR)

        if "§sys:global:boot:bmodule" not in db:
            if "raven.py" in files:
                db.set("§sys:global:boot:bmodule", "raven.py")
            else:
                log_fn("[NEST] raven.py introuvable. (errno: 2)")
                return

        bmodule = db["§sys:global:boot:bmodule"]
        log_fn(f"[NEST] Module de démarrage : {bmodule}")

        if bmodule not in files:
            log_fn(f"[NEST] Module '{bmodule}' introuvable. (errno: 3)")
            return  # BUG CORRIGÉ : return manquant

    else:
        if db["§sys:nest:status"] != "1":
            log_fn("[NEST] Statut inattendu. (errno: 9)")
            return  # BUG CORRIGÉ : return manquant

        bmodule = db["§sys:global:boot:bmodule"]
        if debug:
            log_fn(f"[NEST] Module : {bmodule}")
            
    if debug: log_fn("[NEST] Vérification Bmodule.dep")
    if core.apix.R_ECO3("run spider raven -v" + (" -g" if debug else ""), log_fn)[1] != 0:
        log_fn("[NEST] Bmodule.dep erreur. (errno: 11)")
        return

    log_fn("[NEST] Démarrage dans 2 secondes...")
    if _wait_for_cancel(2.0, log_fn):
        log_fn("[NEST] Démarrage annulé par l'utilisateur.")
        core.apix.R_ECO3("run _start", log_fn)
        return

    log_fn(f"[NEST] Chargement de '{bmodule}'...")
    bmodule = bmodule.replace(".py", "")
    r = core.apix.R_ECO3("run " + bmodule, log_fn)

    if r[1] != 0:
        log_fn("[NEST] Module de démarrage erreur. (errno: 12)")
        return


def R_ECO3dep():
    return (("3.5.1b",), (
            ("core.hive", ("1.1",)),
            ("core.apix", ("1.1",)),
            ("core.utils", ("1.1",)),
            ("core.trail", ("1.1",)),
        ),)


def R_ECO3inf():
    return {
        "name":        "nest",
        "desc":        "Bootloader for R-ECOSYSTEM — validates environment and launches the main module",
        "help":        "Checks database integrity, resolves the boot module, and launches it after a cancellable countdown. No arguments required.",
        "version_mod": "1.1",
        "L2Module":    True,
        "manual": (
            "nest\n\n"
            "AVAILABLE COMMANDS & ARGUMENTS:\n"
            "  nest\n"
            "    Runs the full boot sequence. Takes no arguments.\n\n"
            "BOOT SEQUENCE:\n"
            "  1. Verifies core module integrity (hive, utils, apix, spider).\n"
            "  2. Validates database keys (version, magic, reco_version, codename).\n"
            "  3. Resolves the boot module (§sys:global:boot:bmodule, defaults to raven.py).\n"
            "  4. Checks boot module dependencies via spider.\n"
            "  5. Starts a 2-second cancellable countdown before launch.\n"
            "     Press any key (Windows) or Enter (Unix) to cancel.\n"
            "  6. Loads and runs the boot module via core.apix.\n\n"
            "ERROR CODES:\n"
            "  errno 1  — core/trail.py not found\n"
            "  errno 2  — raven.py not found in modules directory\n"
            "  errno 3  — configured boot module file not found\n"
            "  errno 5  — database magic mismatch\n"
            "  errno 6  — incompatible R_ECO version\n"
            "  errno 7  — incompatible codename\n"
            "  errno 8  — missing required database keys\n"
            "  errno 9  — unexpected nest status value\n"
            "  errno 10 — missing core modules (corrupted ecosystem)\n"
            "  errno 11 — boot module dependency check failed\n"
            "  errno 12 — boot module execution error\n"
            "  warno 4  — unexpected database version (non-fatal)\n"
        )
    }