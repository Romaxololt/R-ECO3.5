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
    
    #! Verification core
    
    if not (ROOT/"core"/"hive.py").exists() or not (ROOT/"core"/"utils.py").exists() or not (ROOT/"core"/"apix.py").exists() or not (ROOT/"modules"/"spider.py").exists():
        log_fn("[NEST] R-ECOSYSTEM corrompue (modules manquants). (errno: 10)")
        return

    db = core.hive.HiveFS(str(core.trail.DB_FILE))

    debug = db.get("§sys:nest:debug", "False") == "True"
    
    if debug:
        log_fn("[NEST] Procédure d'initialisation en cours...")
        log_fn("[NEST] Core modules OK.")
    
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
    
    if debug:
        log_fn("[NEST] Base de données OK.")

    if "§sys:nest:status" not in db or "§sys:global:boot:bmodule" not in db:
        db.set("§sys:nest:status", "1")
        log_fn("[NEST] Initialisation en cours...")

        files = _lister_fichiers(core.trail.MODULES_DIR)

        if "§sys:global:boot:bmodule" not in db:
            if "raven.py" in files:
                db.set("§sys:global:boot:bmodule", "raven.py")
            else:
                log_fn("[NEST] raven.py (default boot module) introuvable, veuillez l'ajouter via _start : set §sys:global:boot:bmodule <module>. (errno: 2)")
                return
            
        if "spider.py" not in files:
            log_fn("[NEST] spider.py introuvable, veuillez l'ajouter via _start : set §sys:global:boot:bmodule spider.py. (errno: 13)")
            return

        bmodule = db["§sys:global:boot:bmodule"]
        log_fn(f"[NEST] Module de démarrage : {bmodule}")

        if bmodule not in files:
            log_fn(f"[NEST] Module '{bmodule}' introuvable. (errno: 3)")

    else:
        if db["§sys:nest:status"] != "1":
            log_fn("[NEST] Statut inattendu. (errno: 9)")

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
    bmodule = bmodule.replace(".py", "") #type: ignore
    r = core.apix.R_ECO3("run " + bmodule, log_fn) #type: ignore

    if r[1] != 0:
        log_fn("[NEST] Module de démarrage erreur. (errno: 12)")
        return

def R_ECO3dep():
    return (("3.5.1b",), (
            ("core.hive", ("1.2",)),
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