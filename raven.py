from os import stat


def R_ECO3(args, log_fn=print):
    state = {}
    import core
    import rich
    import readline
    import rich.console
    import questionary

    state["console"] = rich.console.Console()
    state["questionary"] = questionary
    printl = state["console"].print

    if core.apix.R_ECO3("run banana banner", printl) != (0, (0, None)):
        return 1

    rsid = core.apix.R_ECO3("run login", printl)
    if rsid[1][0] == 1: #type: ignore
        return 1

    state["sid"] = rsid[1][1] #type: ignore
    sid = state["sid"]

    state["db"] = core.hive.HiveFS(str(core.trail.DB_FILE))

    usr = state["db"].get(f"§sys:user:sid:{sid}.uid")
    if usr is None:
        core.apix.R_ECO3("run banana err --msg='Session not found'", printl)
        return 1

    usrn = state["db"].get(f"§sys:user:uid:{usr}.name")

    core.apix.R_ECO3(
        'run banana panel'
        f' --msg="Logged in as [bold blue]{usrn}[/bold blue]\ncookie: [dim]{sid}[/dim]"'
        ' --title=" Session"'
        ' --subtitle="RAVEN v1.1"'
        ' --border=blue'
        ' --align=center'
        ' --box=ROUNDED',
        printl
    )

    # ─── Main loop ────────────────────────────────────────────────
    while True:
        #* BEE
        core.apix.R_ECO3("run bee execute RAVEN_COMMAND_BEFORE -i", log_fn)
        
        style = state["db"].get(f"§sys:user:uid:{usr}.style", None)
        if style is None:
            state["db"].set(f"§sys:user:uid:{usr}.style", "Default")
        usrn = state["db"].get(f"§sys:user:uid:{usr}.name")

        cmd = core.apix.R_ECO3(
            f"run moss --style={style} --folder=~ --user={usrn} --host=R-ECO3", printl
        )
        cmd = str(cmd[1]).strip()

        if not cmd or cmd == "None":
            continue
        if cmd == "KeyboardInterrupt":
            core.apix.R_ECO3("run banana rule --text='Goodbye'", printl)
            break
        if cmd in ("exit", "quit", "q"):
            core.apix.R_ECO3("run banana rule --text='Goodbye'", printl)
            break

        dispatcher = state["db"].get("§sys:raven:dispatcher", "mycelium")

        result = core.apix.R_ECO3(
            f'run {dispatcher} exe {cmd}', printl
        )
        
        if result[0] == 1:
            core.apix.R_ECO3(
                f"run banana err --msg='Module not found: [bold]{module_name}[/bold]'", #type: ignore
                printl
            )
            
        core.apix.R_ECO3("run bee execute RAVEN_COMMAND_AFTER -i", log_fn)

    return 0


def R_ECO3dep():
    return (("3.5.1b",), (
        ("core.hive",  ("1.1",)),
        ("core.apix",  ("1.1",)),
        ("core.trail", ("1.1",)),
        ("banana",     ("1.1",)),
        ("login",      ("1.1",)),
        ("moss",       ("1.1",)),
        ("spider",     ("1.8",)),
    ),)


def R_ECO3inf():
    return {
        "name":        "raven",
        "desc":        "Main RAVEN shell — authenticates the user and runs the interactive command loop",
        "help":        "Displays the banner, authenticates via login, then enters an interactive prompt loop. Commands are dispatched through spider -vr. Type 'exit', 'quit', or 'q' to leave.",
        "version_mod": "1.2",
        "L2Module":    True,
        "manual": (
            "raven\n\n"
            "AVAILABLE COMMANDS & ARGUMENTS:\n"
            "  raven\n"
            "    Starts the RAVEN interactive shell. Takes no arguments.\n\n"
            "SHELL LOOP:\n"
            "  Any input is dispatched as: spider <cmd> -vr --args=\"<args>\"\n"
            "  exit / quit / q   — exits the shell gracefully\n"
            "  Ctrl+C            — exits the shell gracefully\n\n"
            "BOOT SEQUENCE:\n"
            "  1. Displays the RAVEN banner via banana.\n"
            "  2. Authenticates the user via the login module.\n"
            "  3. Resolves session UID and username from the database.\n"
            "  4. Displays a session panel with username and session cookie.\n"
            "  5. Enters the interactive prompt loop via moss.\n"
        )
    }