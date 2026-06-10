from rich.console import Console
from rich.prompt import Prompt
from rich.panel import Panel
from rich.text import Text
import datetime

console = Console()


# ══════════════════════════════════════════════════════════════════
# STYLE 1 — Minimaliste élégant  (inspiré fish shell)
# ══════════════════════════════════════════════════════════════════
def prompt_style_1(log_fn=print, folder="~", user="user", host="R-ECO") -> str:
    log_fn(f"[bold cyan]{user}@{host}[/bold cyan] [dim]{folder}[/dim]")
    return Prompt.ask("[bold magenta]❯[/bold magenta]")


# ══════════════════════════════════════════════════════════════════
# STYLE 2 — Classique Unix  (bash / zsh)
# ══════════════════════════════════════════════════════════════════
def prompt_style_2(log_fn=print, folder="~", user="user", host="raven") -> str:
    prefix = Text()
    prefix.append(f"{user}@{host}", style="bold green")
    prefix.append(":",              style="white")
    prefix.append(folder,           style="bold blue")
    prefix.append(" $ ",            style="bold white")
    log_fn(prefix, end="")
    return console.input("")


# ══════════════════════════════════════════════════════════════════
# STYLE 3 — Panel encadré  (IDE / dashboard)
# ══════════════════════════════════════════════════════════════════
def prompt_style_3(log_fn=print, folder="~") -> str:
    now = datetime.datetime.now().strftime("%H:%M:%S")
    header = Text.assemble(
        ("⏰ ",  "yellow"),
        (now,    "bold yellow"),
        ("  📁 ", "cyan"),
        (folder, "bold cyan"),
    )
    log_fn(Panel(header, border_style="dim blue", padding=(0, 1)))
    return Prompt.ask(
        "[bold yellow]▶[/bold yellow] [bold white]Entrez une commande[/bold white]"
    )


# ══════════════════════════════════════════════════════════════════
# STYLE 4 — Powerline-like  (chevrons colorés)
# ══════════════════════════════════════════════════════════════════
def prompt_style_4(log_fn=print, folder="~", user="user") -> str:
    seg = Text()
    seg.append(f" {user} ",  style="bold white on dark_green")
    seg.append("",            style="dark_green on dark_blue")
    seg.append(f" {folder} ", style="bold white on dark_blue")
    seg.append("",            style="dark_blue on grey15")
    seg.append(" ❯ ",        style="bold cyan on grey15")
    seg.append("",            style="grey15")
    log_fn(seg, end=" ")
    return console.input("")


# ══════════════════════════════════════════════════════════════════
# STYLE 5 — Futuriste / cyberpunk
# ══════════════════════════════════════════════════════════════════
def prompt_style_5(log_fn=print, user="user") -> str:
    now  = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    user = user.upper()
    log_fn(f"[bold red]─── SYS::{user}[/bold red]  [dim]{now}[/dim] [bold red]───[/bold red]")
    return Prompt.ask(
        "[bold red]▓▒░[/bold red] "
        "[bold white]ROOT[/bold white][bold red]@[/bold red][bold green]TERMINAL[/bold green] "
        "[bold red]░▒▓[/bold red]"
    )


STYLES = {
    1: prompt_style_1,
    2: prompt_style_2,
    3: prompt_style_3,
    4: prompt_style_4,
    5: prompt_style_5,
}

# Style par défaut pour RAVEN (minimaliste, cohérent avec son esthétique)
DEFAULT_STYLE = 1


def _resolve_context() -> dict:
    """Valeurs par défaut issues de core.trail.ROOT."""
    ctx = {"folder": "raven", "user": "user", "host": "raven"}
    try:
        import core
        ctx["folder"] = str(core.trail.ROOT.name)   # dernier segment du chemin racine
    except Exception:
        pass
    return ctx


def R_ECO3(args, log_fn=print):
    """
    Point d'entrée appelé par raven via core.apix.R_ECO3("run moss ...", log_fn=printl).

    args  : str  — arguments transmis par apix
    log_fn: callable — fonction d'affichage injectée par l'appelant

    Arguments reconnus (tous optionnels) :
      --style  <str>   style de prompt  (défaut : 1)
      --folder <str>   dossier affiché  (défaut : core.trail.ROOT.name)
      --user   <str>   nom d'utilisateur
      --host   <str>   nom de machine

    Retourne la saisie utilisateur (str).
    """
    import core

    # ── Parse des arguments via core.utils ───────────────────────
    _, kv = core.utils.parse_command(args if isinstance(args, str) else "")
    # ── Contexte : trail.ROOT en fallback, args en priorité ──────
    ctx = _resolve_context()
    if "folder" in kv and isinstance(kv["folder"], str):
        ctx["folder"] = kv["folder"]
    if "user"   in kv and isinstance(kv["user"],   str):
        ctx["user"]   = kv["user"]
    if "host"   in kv and isinstance(kv["host"],   str):
        ctx["host"]   = kv["host"]

    # ── Style ─────────────────────────────────────────────────────
    style = DEFAULT_STYLE
    if "style" in kv:
        if kv["style"] == "Default":
            style = 1
        elif kv["style"] == "Classic Unix":
            style = 2
        elif kv["style"] == "Frame":
            style = 3
        elif kv["style"] == "64":
            style = 4
        elif kv["style"] == "Futur":
            style = 5

    fn = STYLES.get(style, prompt_style_1)

    # ── Dispatch ──────────────────────────────────────────────────
    try:
        if style == 1:
            return fn(log_fn=log_fn, folder=ctx["folder"], user=ctx["user"], host=ctx["host"])
        elif style == 2:
            return fn(log_fn=log_fn, folder=ctx["folder"],
                    user=ctx["user"], host=ctx["host"])
        elif style == 3:
            return fn(log_fn=log_fn, folder=ctx["folder"])
        elif style == 4:
            return fn(log_fn=log_fn, folder=ctx["folder"], user=ctx["user"])
        elif style == 5:
            return fn(log_fn=log_fn, user=ctx["user"])
        else:
            return fn(log_fn=log_fn)
    except KeyboardInterrupt:
        return "KeyboardInterrupt"


def R_ECO3dep():
    return (("3.5.1b",),
            (("core.trail", ("1.1",),),
             ("core.utils", ("1.1",),),
             ))


def R_ECO3inf(): 
    return {
        "name":        "moss",
        "desc":        "Interactive prompt module with 5 Rich-styled themes",
        "help":        "Renders a styled terminal prompt and returns the user's input. Style, folder, user, and host are all configurable.",
        "version_mod": "1.1",
        "L2Module":    True,
        "alias_rules": "/* = banana err --msg='This module cannot be run without arguments. Please refer to the manual for usage instructions.'",
        "manual": (
            "moss — Interactive prompt module with 5 Rich-styled themes  v1.1\n"
            "================================================================\n"
            "\n"
            "SYNOPSIS\n"
            "    moss [--style=STYLE] [--folder=DIR] [--user=NAME] [--host=HOST]\n"
            "\n"
            "DESCRIPTION\n"
            "    Renders a styled terminal prompt and returns the user's input.\n"
            "    The prompt style, folder, user, and host are configurable.\n"
            "    If the user presses Ctrl+C, the module returns 'KeyboardInterrupt'.\n"
            "\n"
            "EXAMPLES\n"
            "    moss\n"
            "    moss --style=Classic Unix\n"
            "    moss --style=Futur --user=root --host=terminal\n"
        ),
    }