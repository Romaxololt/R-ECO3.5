from os import stat
import core
def  apix(args, logfn): return core.apix.R_ECO3(args, logfn)

def R_ECO3(args, log_fn=print):
    state = {}
    import rich
    import readline
    import rich.console
    import questionary

    state["console"] = rich.console.Console()
    state["questionary"] = questionary
    printl = apix("run bird", lambda x: x)[1][1] # type: ignore
    
    apix("run bee execute RAVEN_START -i", printl) #* BEE

    if apix("run banana banner", printl) != (0, (0, None)):
        return 1

    rsid = apix("run login", printl)
    if rsid[1][0] == 1: #type: ignore
        return 1

    state["sid"] = rsid[1][1] #type: ignore
    sid = state["sid"]

    state["db"] = core.hive.HiveFS(str(core.trail.DB_FILE))

    usr = state["db"].get(f"§sys:user:sid:{sid}.uid")
    if usr is None:
        apix("run banana err --msg='Session not found'", printl)
        return 1

    usrn = state["db"].get(f"§sys:user:uid:{usr}.name")

    apix(
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
        apix("run bee execute RAVEN_COMMAND_BEFORE -i", printl)
        
        style = state["db"].get(f"§sys:user:uid:{usr}.style", None)
        if style is None:
            state["db"].set(f"§sys:user:uid:{usr}.style", "Default")
        usrn = state["db"].get(f"§sys:user:uid:{usr}.name")
        
        cwd = apix("run tree cwd", lambda x: x)[1][1] #type: ignore

        cmd = apix(
            f"run moss --style={style} --folder={cwd} --user={usrn} --host=R-ECO3", printl
        )
        cmd = str(cmd[1]).strip()

        if not cmd or cmd == "None":
            continue
        if cmd == "KeyboardInterrupt":
            apix("run banana rule --text='Goodbye'", printl)
            break
        if cmd in ("exit", "quit", "q"):
            apix("run banana rule --text='Goodbye'", printl)
            break

        dispatcher = state["db"].get("§sys:raven:dispatcher", "mycelium")

        result = apix(
            f'run {dispatcher} exe {cmd}', printl
        )
        
        if result[0] == 1:
            apix(
                f"run banana err --msg='Module not found: [bold]{cmd}[/bold]'", #type: ignore
                printl
            )
            
        apix("run bee execute RAVEN_COMMAND_AFTER -i", printl) #* BEE

    return 0


def R_ECO3dep():
    return (("3.5.1b",), (
        ("core.hive", ("1.2",)),
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
        "L2Module":    False,
        "manual": (
            "raven — Main RAVEN shell  v1.2\n"
            "==============================\n"
            "\n"
            "SYNOPSIS\n"
            "    raven\n"
            "\n"
            "DESCRIPTION\n"
            "    Starts the RAVEN interactive shell.\n"
            "    It shows the banner, authenticates the user, resolves the session,\n"
            "    then enters the main prompt loop.\n"
            "    Every command typed in the shell is dispatched through the active dispatcher.\n"
            "\n"
            "EXAMPLES\n"
            "    raven\n"
        ),
    }