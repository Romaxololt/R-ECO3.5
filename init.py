def sha256(text: str) -> str:
    import hashlib
    return hashlib.sha256(text.encode()).hexdigest()

def randomuid(length: int) -> str:
    import os
    return os.urandom(length).hex()[:length]

def ask_password(log_fn, questionary):
    password = questionary.password("Please enter password", qmark="🔒").ask()
    password2 = questionary.password("Please re-enter password", qmark="🔒").ask()
    while password != password2:
        log_fn("[bold red] ✘ Passwords do not match")
        password = questionary.password("Please enter password", qmark="🔒").ask()
        password2 = questionary.password("Please re-enter password", qmark="🔒").ask()
    return password

def R_ECO3(args, log_fn=print):
    import core
    import questionary
    _, r = core.apix.R_ECO3("run banana input --msg='Please enter username'")
    username = r[1].lower().strip() # type: ignore
    password = sha256(ask_password(log_fn, questionary))
    uid = sha256(username)
    sid = randomuid(16)
    
    core.apix.R_ECO3("run banana ok --msg='Account created'")
    
    db = core.hive.HiveFS(str(core.trail.DB_FILE))
    db["§sys:user:uid:" + uid + ".password"] = password
    db["§sys:user:uid:" + uid + ".name"] = username
    db["§sys:user:sid:" + sid + ".uid"] = uid
    
    return sid


def R_ECO3dep():
    return (("3.5.1b",), (("core.apix", ("1.1",)),
                          ("banana", ("1.1",)),
                          ("core.hive", ("1.1",)),))

def R_ECO3inf():
    return {
        "name": "init",
        "desc": "Initialize and register a new RAVEN user account",
        "help": "Prompts for a username and password, hashes credentials, and stores the new account in the RAVEN database. Returns a fresh session ID on success.",
        "version_mod": "1.1",
        "L2Module": True,
        "manual": (
            "init — RAVEN account initialisation  v1.1\n"
            "==========================================\n"
            "\n"
            "SYNOPSIS\n"
            "    init\n"
            "\n"
            "DESCRIPTION\n"
            "    Interactively creates a new RAVEN user account.\n"
            "    Prompts for a username and a confirmed password, hashes the credentials\n"
            "    with SHA-256, and stores them in the RAVEN database.\n"
            "    Returns a fresh session ID (sid) on success.\n"
            "\n"
            "    init takes no arguments.\n"
            "\n"
            "STORED KEYS\n"
            "    §sys:user:uid:<uid>.password   SHA-256 hash of the password\n"
            "    §sys:user:uid:<uid>.name       lowercase username\n"
            "    §sys:user:sid:<sid>.uid        maps the session ID to the user UID\n"
            "\n"
            "EXAMPLES\n"
            "    init\n"
            "        → prompts for username and password\n"
            "        → returns a 16-char session ID on success\n"
        )
    }