import time


SEP = "<RECO_SEP:=:>"

def _get_entries(db) -> list[str]:
    raw = db.get("§sys:bee:available.all", None)
    if not raw:
        return []
    return [e for e in str(raw).split(SEP) if e]

def _set_entries(db, entries: list[str]):
    db["§sys:bee:available.all"] = SEP.join(entries)

def _ensure_in_available(db, captor: str):
    entries = _get_entries(db)
    if captor not in entries:
        entries.append(captor)
        _set_entries(db, entries)
        if not db.exists(f"§sys:bee:stats:{captor}"):
            db[f"§sys:bee:stats:{captor}"] = "0||"


def _parse_stats(db, name: str) -> tuple[int, list[str]]:
    raw = db.get(f"§sys:bee:stats:{name}", None)
    if raw is None:
        return 0, []
    parts = str(raw).split("||", 1)
    count = int(parts[0]) if parts[0].isdigit() else 0
    timestamps = [t for t in (parts[1].split(",") if len(parts) > 1 else []) if t]
    return count, timestamps


def _record_execution(db, name: str):
    count, timestamps = _parse_stats(db, name)
    count += 1
    timestamps.append(str(time.time()))
    timestamps = timestamps[-5:]
    db[f"§sys:bee:stats:{name}"] = f"{count}||{','.join(timestamps)}"


def R_ECO3(args, log_fn=print):
    import core

    db = core.hive.HiveFS(str(core.trail.DB_FILE))
    pos, kv = core.utils.parse_command(args)

    def B(cmd):
        return core.apix.R_ECO3(f"run banana {cmd}", log_fn)

    verb = pos[0]

    # ── set ───────────────────────────────────────────────────────
    if verb == "set":
        if len(pos) < 3:
            B("err --msg='bee set requires at least 2 positional arguments'")
            B("print --msg='  Usage: bee set [bold cyan]<captor> <module> [args...][/bold cyan]'")
            return 1

        captor  = pos[1]
        command = " ".join(pos[2:])
        db[f"§sys:bee:auto:{captor}.cmd"] = command
        B(f"ok --msg='Captor [bold cyan]{captor}[/bold cyan] registered → [dim]{command}[/dim]'")

    # ── execute ───────────────────────────────────────────────────
    elif verb == "execute":
        if len(pos) < 2:
            B("err --msg='bee execute requires at least 1 positional argument'")
            return 1

        captor = pos[1]
        ignore = kv.get("i") is True or kv.get("ignore") is True

        # Always register in available
        _ensure_in_available(db, captor)

        command = db.get(f"§sys:bee:auto:{captor}.cmd", None)
        if command is None:
            if ignore:
                return 0
            B(f"err --msg='No command registered for captor [bold cyan]{captor}[/bold cyan]'")
            return 1

        command = str(command)
        parts   = command.split(" ", 1)
        module_name = parts[0]
        module_args = parts[1] if len(parts) > 1 else ""

        result = core.apix.R_ECO3(
            f'run spider {module_name} -vr --args="{module_args}"', log_fn
        )
        _record_execution(db, captor)

        if isinstance(result, tuple) and result[0] != 0:
            B(f"err --msg='Captor [bold cyan]{captor}[/bold cyan] failed'")
            return 1

    # ── list ──────────────────────────────────────────────────────
    elif verb == "list":
        keys = [k for k in db.list()
                if k.startswith("§sys:bee:auto:") and k.endswith(".cmd")]

        if not keys:
            B("panel --msg='[dim]No captors registered.[/dim]' --title=' Bee · Captors' --border=cyan --box=ROUNDED")
            return 0

        rows = ""
        for k in sorted(keys):
            captor  = k.removeprefix("§sys:bee:auto:").removesuffix(".cmd")
            command = str(db.get(k, ""))
            rows += f"  [bold cyan]{captor:<22}[/bold cyan] [dim]{command}[/dim]\n"

        B(f"panel --msg='{rows.rstrip()}' --title=' Bee · {len(keys)} captor(s)' --border=cyan --box=ROUNDED")

    # ── delete ────────────────────────────────────────────────────
    elif verb == "delete":
        if len(pos) < 2:
            B("err --msg='bee delete requires 1 positional argument'")
            return 1

        captor = pos[1]
        key    = f"§sys:bee:auto:{captor}.cmd"

        if not db.exists(key):
            B(f"err --msg='Captor [bold cyan]{captor}[/bold cyan] not found'")
            return 1

        db.delete(key)
        B(f"ok --msg='Captor [bold cyan]{captor}[/bold cyan] deleted'")

    # ── show ──────────────────────────────────────────────────────
    elif verb == "show":
        if len(pos) < 2:
            B("err --msg='bee show requires 1 positional argument'")
            return 1

        captor  = pos[1]
        command = db.get(f"§sys:bee:auto:{captor}.cmd", None)

        if command is None:
            B(f"err --msg='Captor [bold cyan]{captor}[/bold cyan] not found'")
            return 1

        count, timestamps = _parse_stats(db, captor)
        last = ""
        if timestamps:
            try:
                last = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(timestamps[-1])))
            except (ValueError, OSError):
                last = timestamps[-1]

        msg = (
            f"[dim]command  :[/dim]  [bold white]{command}[/bold white]\n"
            f"[dim]runs     :[/dim]  [bold]{count}[/bold]\n"
            f"[dim]last run :[/dim]  [dim]{last or 'never'}[/dim]"
        )
        B(f"panel --msg='{msg}' --title=' {captor}' --border=cyan --box=ROUNDED")

    # ── add ───────────────────────────────────────────────────────
    elif verb == "add":
        if len(pos) < 2:
            B("err --msg='bee add requires 1 positional argument'")
            return 1

        name    = pos[1]
        entries = _get_entries(db)

        if name in entries:
            B(f"print --msg='[dim]{name} is already in the available list[/dim]'")
            return 0

        entries.append(name)
        _set_entries(db, entries)
        if not db.exists(f"§sys:bee:stats:{name}"):
            db[f"§sys:bee:stats:{name}"] = "0||"

        B(f"ok --msg='[bold cyan]{name}[/bold cyan] added to available list'")

    # ── available ─────────────────────────────────────────────────
    elif verb == "available":
        entries = _get_entries(db)

        if not entries:
            B("panel --msg='[dim]No entries in available list.[/dim]' --title=' Bee · Available' --border=cyan --box=ROUNDED")
            return 0

        rows = ""
        for name in sorted(entries):
            count, timestamps = _parse_stats(db, name)
            has_cmd = "✔" if db.exists(f"§sys:bee:auto:{name}.cmd") else "·"
            rows += f"  [bold cyan]{has_cmd}[/bold cyan] [white]{name:<24}[/white] [dim]{count} run(s)[/dim]\n"

        B(f"panel --msg='{rows.rstrip()}' --title=' Bee · {len(entries)} available' --border=cyan --box=ROUNDED")

    # ── stat ──────────────────────────────────────────────────────
    elif verb == "stat":
        entries = _get_entries(db)

        if not entries:
            B("panel --msg='[dim]No entries in available list.[/dim]' --title=' Bee · Stats' --border=cyan --box=ROUNDED")
            return 0

        msg = ""
        for name in sorted(entries):
            count, timestamps = _parse_stats(db, name)
            has_cmd = db.exists(f"§sys:bee:auto:{name}.cmd")

            msg += f"[bold cyan]{name}[/bold cyan]"
            msg += f"  [dim]({'bound' if has_cmd else 'unbound'})[/dim]\n"
            msg += f"  [dim]runs :[/dim] [bold]{count}[/bold]\n"

            if timestamps:
                for ts in timestamps[-5:]:
                    try:
                        fmt = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(ts)))
                    except (ValueError, OSError):
                        fmt = ts
                    msg += f"    [dim]› {fmt}[/dim]\n"
            else:
                msg += f"  [dim]› never run[/dim]\n"
            msg += "\n"

        B(f"panel --msg='{msg.rstrip()}' --title=' Bee · Stats ({len(entries)} entries)' --border=cyan --box=ROUNDED")

    # ── unknown ───────────────────────────────────────────────────
    else:
        B(f"err --msg='Unknown command: [bold]{verb}[/bold]'")
        B("print --msg='  [dim]set · execute · list · delete · show · add · available · stat[/dim]'")
        return 1

    return 0

def R_ECO3dep():
    return (
        ("3.5.1b",),
        (
            ("core.hive", ("1.2",)),
            ("core.apix",  ("1.1",)),
            ("core.utils", ("1.1",)),
            ("core.trail", ("1.1",)),
            ("banana",     ("1.1",)),
            ("spider",     ("1.8",)),
        ),
    )


def R_ECO3inf():
    return {
        "name":        "bee",
        "desc":        "Captor-based command automation — bind, trigger, and track named commands",
        "help":        "Associates named captors with module commands and executes them on demand. Tracks execution history and exposes a named-entry registry with per-entry statistics.",
        "version_mod": "1.2",
        "L2Module":    True,
        "alias_rules": "bee /* = banana err --msg='This module cannot be run without arguments. Please refer to the manual for usage instructions.'",
        "manual": (
            "bee — Captor automation module  v1.2\n"
            "====================================\n"
            "\n"
            "SYNOPSIS\n"
            "    bee <command> [args...]\n"
            "    bee set <captor> <module> [args...]\n"
            "    bee execute <captor> [-i|--ignore]\n"
            "    bee list\n"
            "    bee delete <captor>\n"
            "    bee show <captor>\n"
            "    bee add <name>\n"
            "    bee available\n"
            "    bee stat\n"
            "\n"
            "COMMANDS\n"
            "    set <captor> <module> [args...]\n"
            "        Registers a command under the given captor name.\n"
            "\n"
            "    execute <captor> [-i|--ignore]\n"
            "        Runs the command registered under the captor via spider -vr.\n"
            "        Always registers the captor in the available list.\n"
            "        -i / --ignore: silent no-op if no command is registered.\n"
            "\n"
            "    list\n"
            "        Lists all registered captors and their commands in a panel.\n"
            "\n"
            "    delete <captor>\n"
            "        Removes a captor command from the database.\n"
            "\n"
            "    show <captor>\n"
            "        Displays the command, run count, and last execution time.\n"
            "\n"
            "    add <name>\n"
            "        Manually adds a named entry to the available registry.\n"
            "\n"
            "    available\n"
            "        Displays all available entries with bound status and run count.\n"
            "\n"
            "    stat\n"
            "        Displays full statistics: run count and last 5 timestamps per entry.\n"
            "\n"
            "STORED KEYS\n"
            "    §sys:bee:auto:<captor>.cmd\n"
            "        Stores the command string bound to a captor.\n"
            "\n"
            "    §sys:bee:available.all\n"
            "        Stores the list of available entries, separated by <RECO_SEP:=:>.\n"
            "\n"
            "    §sys:bee:stats:<name>\n"
            "        Stores execution stats as '<count>||<ts1>,<ts2>,...'.\n"
            "\n"
            "EXAMPLES\n"
            "    bee set test echo hello world\n"
            "    bee execute test\n"
            "    bee list\n"
            "    bee show test\n"
            "    bee add alpha\n"
            "    bee available\n"
            "    bee stat\n"
        ),
    }
