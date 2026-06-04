def R_ECO3(args, log_fn=print):
    import core
    pos, kv = core.utils.parse_command(args)

    if not pos:
        core.apix.R_ECO3(
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
        _, response_data = core.apix.R_ECO3(f"run spider {module} -in")
        inf = response_data[1][0] #type: ignore
    except Exception as e:
        core.apix.R_ECO3(f"run banana err --msg='Failed to load module: {module}'", log_fn)
        return 1

    if not isinstance(inf, dict):
        core.apix.R_ECO3(f"run banana err --msg='No metadata found for: {module}'", log_fn)
        return 1

    name    = inf.get("name",        module)
    desc    = inf.get("desc",        "")
    version = inf.get("version_mod", "?")
    manual  = inf.get("manual",      None)
    help_   = inf.get("help",        "")

    core.apix.R_ECO3(
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

    core.apix.R_ECO3('run banana rule --style="blue dim"', log_fn)

    return 0


def R_ECO3dep():
    return (
        ("3.5.1b",),
        (
            ("core.trail", ("1.1",)),
            ("spider",     ("1.8",)),
            ("banana",     ("1.1",)),
        )
    )


def R_ECO3inf():
    return {
        "name":        "manual",
        "desc":        "Display the full manual for a RAVEN module",
        "help":        "Fetches and renders the manual entry of any module via spider. Falls back to the help field if no manual is defined.",
        "version_mod": "1.0",
        "alias_rules": "manual /* = banana err --msg='This module cannot be run without arguments. Please refer to the manual for usage instructions.'",
        "L2Module":    True,
        "manual": (
            "manual <module>\n\n"
            "AVAILABLE COMMANDS & ARGUMENTS:\n"
            "  manual <module>\n"
            "    Displays the full manual of the given module.\n"
            "    Falls back to the help field if no manual is defined.\n"
            "    Takes no additional arguments.\n"
        )
    }