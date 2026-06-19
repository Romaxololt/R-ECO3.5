import core
import hashlib
import json
import os
import questionary


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def randomuid(length: int) -> str:
    return os.urandom(length).hex()[:length]


def ask_password(log_fn) -> str | None:
    """Demande un mot de passe confirmé. Retourne le mot de passe ou None si annulé."""
    password = questionary.password("Please enter password", qmark="🔒").ask()
    if password is None:
        return None
    password2 = questionary.password("Please re-enter password", qmark="🔒").ask()
    if password2 is None:
        return None
    while password != password2:
        log_fn("[bold red] ✘ Passwords do not match")
        password = questionary.password("Please enter password", qmark="🔒").ask()
        if password is None:
            return None
        password2 = questionary.password("Please re-enter password", qmark="🔒").ask()
        if password2 is None:
            return None
    return password


def _load_rules(db) -> dict:
    """Charge les règles depuis §sys:rules:password."""
    try:
        raw = db.get("§sys:rules:password")
        if raw is None:
            return {}
        return json.loads(raw)
    except Exception:
        return {}


def _load_passfile(db) -> dict:
    """Charge §sys:user:pass.raven — { uid: password_hash, ... }."""
    try:
        raw = db.get("§sys:user:pass.raven")
        if raw is None:
            return {}
        return json.loads(raw)
    except Exception:
        return {}


def _save_passfile(db, passfile: dict) -> None:
    db["§sys:user:pass.raven"] = json.dumps(passfile)


def _validate_username(username: str, db, log_fn) -> bool:
    if not username:
        log_fn("[bold red]✘ Username cannot be empty")
        return False
    if len(username) < 3:
        log_fn("[bold red]✘ Username must be at least 3 characters")
        return False
    if not username.isalnum():
        log_fn("[bold red]✘ Username must contain only letters and numbers")
        return False
    # Vérifie unicité dans usrlist
    try:
        raw_usrlist = db.get("§sys:user:usrlist.raven", "{}")
        usrlist = json.loads(raw_usrlist)
        for uid_entry in usrlist.values():
            if uid_entry.get("username") == username:
                log_fn(f"[bold red]✘ Username '{username}' is already taken")
                return False
    except Exception as e:
        log_fn(f"[bold red]✘ Username check failed: {e}")
        return False
    return True


def _validate_password(password: str, username: str, rules: dict, log_fn) -> bool:
    min_length = rules.get("min_length", 8)
    if len(password) < min_length:
        log_fn(f"[bold red]✘ Password must be at least {min_length} characters")
        return False
    if rules.get("require_uppercase", False):
        if not any(c.isupper() for c in password):
            log_fn("[bold red]✘ Password must contain at least one uppercase letter")
            return False
    if rules.get("require_numbers", False):
        if not any(c.isdigit() for c in password):
            log_fn("[bold red]✘ Password must contain at least one number")
            return False
    if rules.get("require_symbols", False):
        symbols = set("!@#$%^&*()_+-=[]{}|;':\",./<>?")
        if not any(c in symbols for c in password):
            log_fn("[bold red]✘ Password must contain at least one symbol")
            return False
    if rules.get("no_username_in_pw", False):
        if username in password.lower():
            log_fn("[bold red]✘ Password must not contain your username")
            return False
    return True


# ─── Point d'entrée R_ECO3 ───────────────────────────────────────────────────

def R_ECO3(inp) -> dict:
    """Crée un nouveau compte RAVEN. Retourne {"status": 0/1, "value": token|None}."""
    db     = inp["db"]
    log_fn = inp["logfn"]

    # 1. Règles
    try:
        rules = _load_rules(db)
    except Exception as e:
        log_fn(f"[bold red]✘ Failed to load password rules: {e}")
        rules = {}

    # 2. Username
    try:
        r = core.apix.R_ECO3({
            "args":  "run banana input --msg='Please enter username'",
            "logfn": log_fn,
            "db":    db,
        })
        raw_username = r.get("value", None)
        if raw_username is None:
            core.apix.R_ECO3({"args": "run banana err --msg='Cancelled'", "logfn": log_fn, "db": db})
            return {"status": 1, "value": None}

        username = str(raw_username).lower().strip()

        if not _validate_username(username, db, log_fn):
            return {"status": 1, "value": None}

    except Exception as e:
        log_fn(f"[bold red]✘ Username prompt failed: {e}")
        return {"status": 1, "value": None}

    # 3. Password
    try:
        password_raw = ask_password(log_fn)
        if password_raw is None:
            core.apix.R_ECO3({"args": "run banana err --msg='Cancelled'", "logfn": log_fn, "db": db})
            return {"status": 1, "value": None}

        if not _validate_password(password_raw, username, rules, log_fn):
            return {"status": 1, "value": None}

        password_hash = sha256(password_raw)

    except Exception as e:
        log_fn(f"[bold red]✘ Password prompt failed: {e}")
        return {"status": 1, "value": None}

    # 4. Génération uid + token
    try:
        uid   = sha256(username)
        token = randomuid(32)
    except Exception as e:
        log_fn(f"[bold red]✘ UID/token generation failed: {e}")
        return {"status": 1, "value": None}

    # 5. Écriture du mot de passe dans §sys:user:pass.raven
    try:
        passfile = _load_passfile(db)
        passfile[uid] = password_hash
        _save_passfile(db, passfile)
    except Exception as e:
        log_fn(f"[bold red]✘ Failed to write password: {e}")
        return {"status": 1, "value": None}

    # 6. Mise à jour §sys:user:usrlist.raven
    try:
        raw_usrlist = db.get("§sys:user:usrlist.raven", "{}")
        usrlist = json.loads(raw_usrlist)
        usrlist[uid] = {
            "username": username,
            "style":    "Default",
        }
        db["§sys:user:usrlist.raven"] = json.dumps(usrlist)
    except Exception as e:
        log_fn(f"[bold red]✘ Failed to update usrlist: {e}")
        return {"status": 1, "value": None}

    # 7. Création de l'ecopass dans §sys:ecopass.raven
    try:
        import time
        raw_ecopass = db.get("§sys:ecopass.raven", "{}")
        ecopass = json.loads(raw_ecopass)
        ecopass[token] = {
            "username":   username,
            "useruid":    uid,
            "expiration": int(time.time()) + 86400,  # 24h
        }
        db["§sys:ecopass.raven"] = json.dumps(ecopass)
    except Exception as e:
        log_fn(f"[bold red]✘ Failed to create ecopass: {e}")
        return {"status": 1, "value": None}

    # 8. Confirmation
    try:
        core.apix.R_ECO3({
            "args":  f"run banana ok --msg='Account created: [bold]{username}[/bold]'",
            "logfn": log_fn,
            "db":    db,
        })
    except Exception as e:
        log_fn(f"[dim]Banner display failed: {e}")

    return {"status": 0, "value": token}


def R_ECO3dep():
    return {
        "reco": ["3.5.2b"],
        "module": [
            {"banana": ["2.1"]},
        ]
    }


def R_ECO3inf():
    return {
        "name":        "init",
        "desc":        "Initialize and register a new RAVEN user account",
        "help":        "Prompts for a username and password, validates against §sys:rules:password, hashes credentials into §sys:user:pass.raven, updates §sys:user:usrlist.raven, creates an ecopass entry in §sys:ecopass.raven and returns the session token.",
        "version_mod": "2.2",
        "L2Module":    True,
        "manual": (
            "init — RAVEN account initialisation  v2.2\n"
            "==========================================\n"
            "\n"
            "SYNOPSIS\n"
            "    init\n"
            "\n"
            "DESCRIPTION\n"
            "    Interactively creates a new RAVEN user account.\n"
            "    Prompts for a username and a confirmed password, validates both\n"
            "    against §sys:rules:password, hashes the password with SHA-256,\n"
            "    and stores the account in the RAVEN database.\n"
            "    Returns a session token on success.\n"
            "\n"
            "VALIDATION\n"
            "    Username  — non-empty, ≥ 3 chars, alphanumeric, not already taken\n"
            "    Password  — validated against §sys:rules:password:\n"
            "                  min_length, require_uppercase, require_numbers,\n"
            "                  require_symbols, no_username_in_pw\n"
            "\n"
            "STORED KEYS\n"
            "    §sys:user:pass.raven        { uid: sha256(password), ... }\n"
            "    §sys:user:usrlist.raven     { uid: { username, style }, ... }\n"
            "    §sys:ecopass.raven          { token: { username, useruid, expiration }, ... }\n"
            "\n"
            "RETURN\n"
            "    {\"status\": 0, \"value\": \"<token>\"}   on success\n"
            "    {\"status\": 1, \"value\": None}         on failure\n"
        )
    }