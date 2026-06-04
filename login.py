def sha256(text: str) -> str:
    import hashlib
    return hashlib.sha256(text.encode()).hexdigest()

def randomuid(length: int) -> str:
    import os
    return os.urandom(length).hex()[:length]

def ask_password(log_fn, questionary):
    password  = questionary.password("Please enter password",    qmark="🔒").ask()
    password2 = questionary.password("Please re-enter password", qmark="🔒").ask()
    while password != password2:
        log_fn("[bold red] ✘ Passwords do not match")
        password  = questionary.password("Please enter password",    qmark="🔒").ask()
        password2 = questionary.password("Please re-enter password", qmark="🔒").ask()
    return password


# ─── Sous-routines ────────────────────────────────────────────────────────────

def _create(core, log_fn) -> tuple:
    return core.apix.R_ECO3("run init", log_fn)


def _login(uid: str, db, log_fn, core, questionary) -> tuple:
    stored = db.get("§sys:user:uid:" + uid + ".password")
    if stored is None:
        core.apix.R_ECO3("run banana err --msg='Account not found'", log_fn)
        return 1, None

    attempt = questionary.password("Password", qmark="🔒").ask()
    if sha256(attempt) != stored:
        core.apix.R_ECO3("run banana err --msg='Wrong password'", log_fn)
        return _login(uid, db, log_fn, core, questionary)

    sid = randomuid(16)
    db["§sys:user:sid:" + sid + ".uid"] = uid
    return 0, sid


def _select_account(uid_keys: list, db, log_fn, core, questionary) -> tuple:
    from questionary import Style as QStyle

    RAVEN_STYLE = QStyle([
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

    # Construit le mapping  nom affiché → uid
    accounts: dict[str, str] = {}
    for key in uid_keys:
        uid  = key.removeprefix("§sys:user:uid:").removesuffix(".name")
        name = db[key]
        accounts[f"  {name}"] = uid

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
        core.apix.R_ECO3("run banana err --msg='Cancelled'", log_fn)
        return 1, None

    if chosen == NEW:
        return _create(core, log_fn)

    uid = accounts[chosen]
    return _login(uid, db, log_fn, core, questionary)


# ─── Point d'entrée R_ECO3 ───────────────────────────────────────────────────

def R_ECO3(args, log_fn=print) -> tuple:
    import core
    import questionary

    pos, kv = core.utils.parse_command(str(args))

    raw_uid = kv.get("uid", None)
    uid     = None if (raw_uid is None or raw_uid == "None") else raw_uid

    db           = core.hive.HiveFS(str(core.trail.DB_FILE))
    all_files    = db.list()
    uid_keys     = [f for f in all_files
                    if f.startswith("§sys:user:uid:") and f.endswith(".name")]

    # Aucun compte → création obligatoire
    if not uid_keys:
        core.apix.R_ECO3("run banana rule --text='First launch'", log_fn)
        log_fn("[dim]No account found — let's create one.[/dim]")
        return _create(core, log_fn)

    # UID fourni → login direct
    if uid is not None:
        return _login(uid, db, log_fn, core, questionary) #type: ignore

    # UID absent → menu de sélection
    return _select_account(uid_keys, db, log_fn, core, questionary)


def R_ECO3dep():
    return (("3.5.1b",), (("banana", ("1.1",)),
                          ("init", ("1.1",)),
                          ("core.apix", ("1.1",)),
                          ("core.utils", ("1.1",)),
                          ("core.trail", ("1.1",)),
                          ("core.hive", ("1.1",)),
                          ))

def R_ECO3inf():
    return {
        "name":        "login",
        "desc":        "Account authentication and creation for RAVEN",
        "help":        "Handles user login and account creation. Shows an account picker if no UID is provided, attempts direct login if a UID is supplied, and triggers first-time account creation if no accounts exist.",
        "version_mod": "1.1",
        "L2Module":    False,
        "manual": (
            "login [--uid=UID]\n\n"
            "AVAILABLE COMMANDS & ARGUMENTS:\n"
            "  login\n"
            "    Opens an interactive account selector.\n"
            "    Prompts for password, then returns a session ID.\n\n"
            "  login --uid=UID\n"
            "    Skips the account picker and attempts direct login for the given UID.\n\n"
            "  login --uid=None\n"
            "    Explicitly forces the account picker menu.\n\n"
            "  (first launch)\n"
            "    If no account exists in the database, creation is triggered automatically.\n"
        )
    }