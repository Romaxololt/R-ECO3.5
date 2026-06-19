import hashlib
import json
import os
import time
import questionary
import core


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def randomuid(length: int) -> str:
    return os.urandom(length).hex()[:length]


def _load_passfile(db) -> dict:
    """Charge §sys:user:pass.raven — { uid: password_hash, ... }."""
    try:
        raw = db.get("§sys:user:pass.raven")
        if raw is None:
            return {}
        return json.loads(raw)
    except Exception:
        return {}


def _create_ecopass(db, token: str, username: str, uid: str) -> None:
    """Ajoute ou met à jour une entrée dans §sys:ecopass.raven."""
    raw = db.get("§sys:ecopass.raven", "{}")
    ecopass = json.loads(raw)
    ecopass[token] = {
        "username":   username,
        "useruid":    uid,
        "expiration": int(time.time()) + 86400,  # 24h
    }
    db["§sys:ecopass.raven"] = json.dumps(ecopass)


# ─── Sous-routines ────────────────────────────────────────────────────────────

def _create(log_fn, db) -> dict:
    """Délègue la création de compte à init. Retourne dict."""
    try:
        result = core.apix.R_ECO3({"args": "run init", "logfn": log_fn, "db": db})
        return result if isinstance(result, dict) else {"status": 1, "value": None}
    except Exception as e:
        log_fn(f"[bold red]✘ Account creation failed: {e}")
        return {"status": 1, "value": None}


def _login(uid: str, username: str, db, log_fn) -> dict:
    """
    Authentifie un utilisateur par uid.
    Retourne {"status": 0, "value": token} ou {"status": 1, "value": None}.
    """
    try:
        passfile = _load_passfile(db)
        stored_hash = passfile.get(uid)
        if stored_hash is None:
            core.apix.R_ECO3({"args": "run banana err --msg='Account not found'", "logfn": log_fn, "db": db})
            return {"status": 1, "value": None}

        for _ in range(3):
            try:
                attempt = questionary.password("Password", qmark="🔒").ask()
                if attempt is None:
                    core.apix.R_ECO3({"args": "run banana err --msg='Cancelled'", "logfn": log_fn, "db": db})
                    return {"status": 1, "value": None}

                if sha256(attempt) == stored_hash:
                    token = randomuid(32)
                    _create_ecopass(db, token, username, uid)
                    return {"status": 0, "value": token}

                core.apix.R_ECO3({"args": "run banana err --msg='Wrong password'", "logfn": log_fn, "db": db})

            except Exception as e:
                log_fn(f"[bold red]✘ Password attempt failed: {e}")
                return {"status": 1, "value": None}

        core.apix.R_ECO3({"args": "run banana err --msg='Too many attempts'", "logfn": log_fn, "db": db})
        return {"status": 1, "value": None}

    except Exception as e:
        log_fn(f"[bold red]✘ Login failed: {e}")
        return {"status": 1, "value": None}


def _select_account(usrlist: dict, db, log_fn) -> dict:
    """
    Affiche un menu de sélection des comptes existants.
    Retourne dict {"status": 0/1, "value": token|None}.
    """
    try:
        RAVEN_STYLE = questionary.Style([
            ("qmark",       "fg:#5b8def bold"),
            ("question",    "fg:#cdd6f4 bold"),
            ("answer",      "fg:#89b4fa bold"),
            ("pointer",     "fg:#89dceb bold"),
            ("highlighted", "fg:#89dceb bold"),
            ("selected",    "fg:#a6e3a1"),
            ("separator",   "fg:#6c7086"),
            ("instruction", "fg:#6c7086 italic"),
            ("text",        "fg:#cdd6f4"),
        ])

        # Mapping nom affiché → (uid, username)
        accounts: dict[str, tuple[str, str]] = {}
        for uid, entry in usrlist.items():
            username = entry.get("username")
            if username:
                accounts[f"  {username}"] = (uid, username)

        if not accounts:
            log_fn("[bold red]✘ No valid accounts found")
            return {"status": 1, "value": None}

        NEW = "  ＋  Create new account"
        choices = list(accounts.keys()) + [NEW]

        chosen = questionary.select(
            "Select account",
            choices=choices,
            style=RAVEN_STYLE,
            qmark="›",
            pointer="❯",
        ).ask()

        if chosen is None:
            core.apix.R_ECO3({"args": "run banana err --msg='Cancelled'", "logfn": log_fn, "db": db})
            return {"status": 1, "value": None}

        if chosen == NEW:
            return _create(log_fn, db)

        uid, username = accounts[chosen]
        return _login(uid, username, db, log_fn)

    except Exception as e:
        log_fn(f"[bold red]✘ Account selection failed: {e}")
        return {"status": 1, "value": None}


# ─── Point d'entrée R_ECO3 ───────────────────────────────────────────────────

def R_ECO3(inp) -> dict:
    """Point d'entrée principal. Retourne toujours dict {"status": 0/1, "value": token|None}."""
    args   = inp["args"]
    log_fn = inp["logfn"]
    db     = inp["db"]

    try:
        pos, kv = core.utils.parse_command(str(args))
    except Exception as e:
        log_fn(f"[bold red]✘ Command parsing failed: {e}")
        return {"status": 1, "value": None}

    try:
        raw_uid = kv.get("uid", None)
        uid = None if (raw_uid is None or raw_uid == "None") else raw_uid
    except Exception as e:
        log_fn(f"[bold red]✘ UID extraction failed: {e}")
        return {"status": 1, "value": None}

    # Chargement de la usrlist
    try:
        raw_usrlist = db.get("§sys:user:usrlist.raven", "{}")
        usrlist = json.loads(raw_usrlist)
    except Exception as e:
        log_fn(f"[bold red]✘ Failed to load usrlist: {e}")
        return {"status": 1, "value": None}

    # Aucun compte → création obligatoire
    if not usrlist:
        try:
            core.apix.R_ECO3({"args": "run banana rule --text='First launch'", "logfn": log_fn, "db": db})
            log_fn("[dim]No account found — let's create one.[/dim]")
            return _create(log_fn, db)
        except Exception as e:
            log_fn(f"[bold red]✘ First launch setup failed: {e}")
            return {"status": 1, "value": None}

    # UID fourni → login direct
    if uid is not None:
        try:
            entry = usrlist.get(uid)
            if entry is None:
                log_fn(f"[bold red]✘ UID not found in usrlist")
                return {"status": 1, "value": None}
            username = entry.get("username", uid)
            return _login(str(uid), username, db, log_fn)
        except Exception as e:
            log_fn(f"[bold red]✘ Direct login failed: {e}")
            return {"status": 1, "value": None}

    # UID absent → menu de sélection
    try:
        return _select_account(usrlist, db, log_fn)
    except Exception as e:
        log_fn(f"[bold red]✘ Account selection failed: {e}")
        return {"status": 1, "value": None}


def R_ECO3dep():
    return {
        "reco": ["3.5.2b"],
        "module": [
            {"banana": ["2.1"]},
            {"init":   ["2.2"]},
        ]
    }


def R_ECO3inf():
    return {
        "name":        "login",
        "desc":        "Account authentication and creation for RAVEN",
        "help":        "Handles user login and account creation. Shows an account picker if no UID is provided, attempts direct login if a UID is supplied, and triggers first-time account creation if no accounts exist. On success, creates an ecopass entry and returns the session token.",
        "version_mod": "2.2",
        "L2Module":    False,
        "manual": (
            "login — Account authentication and creation for RAVEN  v2.2\n"
            "=============================================================\n"
            "\n"
            "SYNOPSIS\n"
            "    login\n"
            "    login [--uid=UID]\n"
            "    login [--uid=None]\n"
            "\n"
            "DESCRIPTION\n"
            "    Handles user login and account creation.\n"
            "    Reads password hashes from §sys:user:pass.raven.\n"
            "    On successful auth, writes a token entry into §sys:ecopass.raven\n"
            "    and returns that token to the caller (raven).\n"
            "\n"
            "    If no UID is provided, an interactive account picker is shown.\n"
            "    If --uid is provided, the module attempts a direct login.\n"
            "    If no account exists, first-time account creation is triggered.\n"
            "\n"
            "DB KEYS (read)\n"
            "    §sys:user:usrlist.raven     { uid: { username, style }, ... }\n"
            "    §sys:user:pass.raven        { uid: sha256(password), ... }\n"
            "    §sys:rules:password         password policy rules\n"
            "\n"
            "DB KEYS (write)\n"
            "    §sys:ecopass.raven          { token: { username, useruid, expiration }, ... }\n"
            "\n"
            "RETURN\n"
            "    {\"status\": 0, \"value\": \"<token>\"}   on success\n"
            "    {\"status\": 1, \"value\": None}         on failure\n"
            "\n"
            "EXAMPLES\n"
            "    login\n"
            "    login --uid=abc123\n"
            "    login --uid=None\n"
        ),
    }