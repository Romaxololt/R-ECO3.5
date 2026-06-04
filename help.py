import os

def list_py_modules(path):
    """Returns only the names of Python files (without the .py extension)."""
    return [
        os.path.splitext(item)[0] 
        for item in os.listdir(path) 
        if item.endswith('.py') and os.path.isfile(os.path.join(path, item))
    ]

def R_ECO3(args, log_fn=print):
    import core
    pos, kv = core.utils.parse_command(args)
    
    if not pos and not kv:
        modules_dir = core.trail.MODULES_DIR
        modules = list_py_modules(modules_dir)

        core.apix.R_ECO3(
            'run banana panel'
            ' --msg="Available modules on this system"'
            ' --title="[bold cyan] Help[/bold cyan]"'
            ' --border=cyan'
            ' --align=center'
            ' --box=ROUNDED',
            log_fn
        )

        rows = []
        for module in modules:
            try:
                _, response_data = core.apix.R_ECO3(f"run spider {module} -in")
                inf = response_data[1][0] # type: ignore
                if isinstance(inf, dict):
                    name = inf.get("name", module)
                    desc = inf.get("desc", "")
                    rows.append((name, desc))
            except Exception:
                continue

        for name, desc in rows:
            log_fn(f"  [bold blue]{name:<20}[/bold blue] [dim]{desc}[/dim]")

        core.apix.R_ECO3(
            f'run banana rule --text="{len(rows)} module(s) found"'
            ' --style="blue dim"',
            log_fn
        )

    return 0

def R_ECO3dep():
    return (
        ("3.5.1b",), 
        (
            ("core.trail", ("1.1",)),
            ("core.apix",  ("1.1",)),
            ("core.utils", ("1.1",)),
            ("spider",     ("1.8",)),
            ("banana",     ("1.1",)),
        )
    )

def R_ECO3inf():
    return {
        "name":        "help",
        "desc":        "Display help and descriptions for all available RAVEN modules",
        "help":        "Lists all available RAVEN modules with their name and short description. When called with no arguments, iterates over every module in the modules directory and prints its metadata.",
        "version_mod": "1.0",
        "alias_rules": "help * = manual *",
        "L2Module":    True,
        "manual": (
            "help\n\n"
            "AVAILABLE COMMANDS & ARGUMENTS:\n"
            "  help\n"
            "    Lists all available modules with their name and description.\n"
            "    Takes no arguments.\n"
        )
    }
