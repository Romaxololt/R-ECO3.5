import json
import time
import core
import rich
import readline
import rich.console


def apix(args, logfn=None, db=None, token=None):
    payload = {"args": args, "logfn": logfn}
    if db    is not None: payload["db"]    = db
    if token is not None: payload["token"] = token
    return core.apix.R_ECO3(payload)


def _resolve_ecopass(token: str, db) -> dict | None:
    """
    Résout un token depuis §sys:ecopass.raven.
    Retourne l'entrée { username, useruid, expiration } ou None si invalide/expiré.
    """
    try:
        raw = db.get("§sys:ecopass.raven")
        if raw is None:
            return None
        ecopass = json.loads(raw)
        entry = ecopass.get(token)
        if entry is None:
            return None
        if int(time.time()) > entry.get("expiration", 0):
            return None
        return entry
    except Exception:
        return None


# ─── Point d'entrée R_ECO3 ───────────────────────────────────────────────────

def R_ECO3(inp):
    logfn = inp["logfn"]
    args  = inp["args"]
    db    = inp["db"]

    try:
        console = rich.console.Console()
        printl  = core.bird.R_ECO3(None)
    except Exception as e:
        print(f"ERREUR: Initialisation état échouée — {e}")
        return 1

    # ── Banner ────────────────────────────────────────────────────
    try:
        apix("run banana banner", printl)
    except Exception as e:
        print(f"ERREUR: Affichage banner échoué — {e}")
        return 1

    # ── Authentification ──────────────────────────────────────────
    try:
        result = apix("run spider login -vr", printl, db)
        if result["status"] == 1:
            apix("run banana err --msg='Authentication failed'", printl)
            return 1
    except Exception as e:
        print(f"ERREUR: Login échoué — {e}")
        return 1

    try:
        token = result["value"]
        if token is None:
            apix("run banana err --msg='No session token received'", printl)
            return 1
    except (KeyError, TypeError) as e:
        print(f"ERREUR: Extraction token échouée — {e}")
        return 1

    # ── Résolution ecopass ────────────────────────────────────────
    try:
        session = _resolve_ecopass(token, db)
        if session is None:
            apix("run banana err --msg='Session not found or expired'", printl)
            return 1
        username = session["username"]
        uid      = session["useruid"]
    except Exception as e:
        print(f"ERREUR: Résolution ecopass échouée — {e}")
        return 1

    # ── Panneau de session ────────────────────────────────────────
    try:
        apix(
            f'run banana panel'
            f' --msg="Logged in as [bold blue]{username}[/bold blue] and token: [dim]{token}[/dim]"'
            f' --title=" Session"'
            f' --subtitle="RAVEN v1.1"'
            f' --border=blue'
            f' --align=center'
            f' --box=ROUNDED',
            printl
        )
    except Exception as e:
        print(f"ERREUR: Affichage panel session échoué — {e}")
        return 1

    # ─── Main loop ────────────────────────────────────────────────
    while True:
        # Vérification expiration en cours de session
        try:
            session = _resolve_ecopass(token, db)
            if session is None:
                apix("run banana err --msg='Session expired — please login again'", printl)
                break
        except Exception as e:
            print(f"ERREUR: Vérification session échouée — {e}")
            break

        # Style et cwd
        try:
            usrlist  = json.loads(db.get("§sys:user:usrlist.raven", "{}"))
            entry    = usrlist.get(uid, {})
            username = entry.get("username", username)
            style    = entry.get("style", "Default")
        except Exception as e:
            print(f"ERREUR: Récupération style/username échouée — {e}")
            continue

        try:
            cwd_res = apix("run tree cwd", lambda x:x, db)
            cwd = cwd_res["value"]
        except Exception as e:
            print(f"ERREUR: Récupération cwd échouée — {e}")
            continue

        # Prompt
        try:
            cmd = apix(
                f"run moss --style={style} --folder={cwd} --user={username} --host=R-ECO3",
                printl
            )["value"]
            cmd = str(cmd).strip()
        except Exception as e:
            print(f"ERREUR: Prompt moss échoué — {e}")
            continue

        if not cmd or cmd == "None":
            continue

        if cmd == "KeyboardInterrupt":
            try:
                apix("run banana rule --text='Goodbye'", printl)
            except Exception:
                pass
            break

        if cmd in ("exit", "quit", "q"):
            try:
                apix("run banana rule --text='Goodbye'", printl)
            except Exception:
                pass
            break

        # Dispatcher
        try:
            dispatcher  = db.get("§sys:raven:dispatcher",   "squid")
            dispatcher2 = db.get("§sys:raven:dispatcher_2", "dsp2")
        except Exception as e:
            print(f"ERREUR: Récupération dispatcher échouée — {e}")
            dispatcher  = "mycelium"
            dispatcher2 = "dsp2"

        try:
            result = apix(f"run {dispatcher} exe {cmd}", printl, db, token)
            if result["status"] == -1:
                result = apix(f"run {dispatcher2} exe {cmd}", printl, db, token)
                if result["status"] == -1:
                    apix(
                        f"run banana err --msg='Module not found: [bold]{cmd}[/bold]'",
                        printl
                    )
                    
        except Exception as e:
            print(f"ERREUR: Exécution dispatcher échouée — {e}")

        # BEE post-command
        try:
            apix("run bee execute RAVEN_COMMAND_AFTER -i", printl, db)
        except Exception as e:
            print(f"ERREUR: BEE post-command échoué — {e}")
            continue

    return 0


def R_ECO3dep():
    return {
        "reco": ["3.5.2b"],
        "module": [
            {"banana": ["2.1"]},
            {"spider": ["2.1"]},
            {"moss":   ["2.1"]},
            {"login":  ["2.2"]},
            {"tree":   ["2.1"]},
        ]
    }


def R_ECO3inf():
    return {
        "name":        "raven",
        "desc":        "Main RAVEN shell — authenticates the user and runs the interactive command loop",
        "help":        "Displays the banner, authenticates via login (which returns a token), resolves the session from §sys:ecopass.raven, then enters the interactive prompt loop. Commands are dispatched through the configured dispatcher. Type 'exit', 'quit', or 'q' to leave.",
        "version_mod": "2.2",
        "L2Module":    False,
        "manual": (
            "raven — Main RAVEN shell  v2.2\n"
            "==============================\n"
            "\n"
            "SYNOPSIS\n"
            "    raven\n"
            "\n"
            "DESCRIPTION\n"
            "    Starts the RAVEN interactive shell.\n"
            "    Shows the banner, authenticates the user via login, receives a session\n"
            "    token, resolves it from §sys:ecopass.raven, then enters the main loop.\n"
            "    The session expiration is checked at each iteration.\n"
            "    Commands are dispatched through §sys:raven:dispatcher (default: mycelium),\n"
            "    with fallback to §sys:raven:dispatcher_2 (default: dsp2).\n"
            "\n"
            "SESSION\n"
            "    Token resolved from §sys:ecopass.raven:\n"
            "      { token: { username, useruid, expiration } }\n"
            "    Expiration checked at every loop iteration.\n"
            "\n"
            "EXAMPLES\n"
            "    raven\n"
        ),
    }