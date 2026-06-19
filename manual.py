import core

def apix(args, logfn=None, db=None, token=None):
    payload = {"args": args, "logfn": logfn}
    if db    is not None: payload["db"]    = db
    if token is not None: payload["token"] = token
    return core.apix.R_ECO3(payload)

def R_ECO3(inp):
    args = inp["args"]
    log_fn = inp["logfn"]
    pos, kv = core.utils.parse_command(args)

    if not pos:
        apix(
            'run banana panel'
            ' --msg="Usage : [bold cyan]manual <module>[/bold cyan]"'
            ' --title="[bold cyan] Manual[/bold cyan]"'
            ' --border=cyan'
            ' --align=center'
            ' --box=ROUNDED',
            log_fn
        )
        return 0

    module = pos[0]

    try:
        inf = apix(f"inf {module}")["value"]
    except Exception as e:
        apix(f"run banana err --msg='Failed to load module: {module}'", log_fn)
        return 1

    if not isinstance(inf, dict):
        apix(f"run banana err --msg='No metadata found for: {module}'", log_fn)
        return 1

    name    = inf.get("name",        module)
    desc    = inf.get("desc",        "")
    version = inf.get("version_mod", "?")
    manual  = inf.get("manual",      None)
    help_   = inf.get("help",        "")

    apix(
        f'run banana panel'
        f' --msg="{desc}"'
        f' --title="[bold cyan] {name}[/bold cyan]  [dim]v{version}[/dim]"'
        f' --border=cyan'
        f' --align=left'
        f' --box=ROUNDED',
        log_fn
    )

    if manual:
        log_fn(f"[bold white]{manual}[/bold white]")
    elif help_:
        log_fn(f"  [dim]{help_}[/dim]")
    else:
        log_fn("  [dim]No manual available for this module.[/dim]")

    apix('run banana rule --style="blue dim"', log_fn)

    return 0


def R_ECO3dep():
    return {
        "reco": ["3.5.2b"],
        "module": [
            {"banana": ["2.1"]},
            {"spider": ["2.1"]}
        ]
    }


def R_ECO3inf():
    return {
        "name":        "manual",
        "desc":        "Display the full manual for a RAVEN module",
        "help":        "Fetches and renders the manual entry of any module via spider. Falls back to the help field if no manual is defined.",
        "version_mod": "2.1",
        "alias_rules": "manual /* = banana err --msg='This module cannot be run without arguments. Please refer to the manual for usage instructions.'",
        "L2Module":    True,
        "manual": (
            "manual — Display the full manual for a RAVEN module  v1.0\n"
            "=========================================================\n"
            "\n"
            "SYNOPSIS\n"
            "    manual <module>\n"
            "\n"
            "DESCRIPTION\n"
            "    Displays the full manual of the given module.\n"
            "    Falls back to the help field if no manual is defined.\n"
            "\n"
            "EXAMPLES\n"
            "    manual login\n"
            "    manual moss\n"
            "    manual mule\n"
        ),
    }