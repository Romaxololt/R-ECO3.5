"""
banana.py — RAVEN UI module
"""

import rich
import rich.console
from rich.prompt import Prompt, Confirm
from rich.panel import Panel
from rich.text import Text
from rich.align import Align
from rich import box as rich_box
import questionary
from questionary import Style as QStyle
import threading
import time
import itertools
import core

# ─── État interne ─────────────────────────────────────────────────────────────

_state: dict = {"console": None, "log_fn": None, "bird": None}

RAVEN_BANNER = r"""
██████╗  █████╗ ██╗   ██╗███████╗███╗   ██╗
██╔══██╗██╔══██╗██║   ██║██╔════╝████╗  ██║
██████╔╝███████║██║   ██║█████╗  ██╔██╗ ██║
██╔══██╗██╔══██║╚██╗ ██╔╝██╔══╝  ██║╚██╗██║
██║  ██║██║  ██║ ╚████╔╝ ███████╗██║ ╚████║
╚═╝  ╚═╝╚═╝  ╚═╝  ╚═══╝  ╚══════╝╚═╝  ╚═══╝
"""

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

BOX_STYLES = {
    "ROUNDED":  rich_box.ROUNDED,
    "HEAVY":    rich_box.HEAVY,
    "DOUBLE":   rich_box.DOUBLE,
    "SIMPLE":   rich_box.SIMPLE,
    "MINIMAL":  rich_box.MINIMAL,
    "ASCII":    rich_box.ASCII,
    "SQUARE":   rich_box.SQUARE,
    "MARKDOWN": rich_box.MARKDOWN,
}

# ─── Console Rich (utilisée uniquement pour les widgets Rich : Panel, banner) ─

def _console() -> rich.console.Console:
    if _state["console"] is None:
        _state["console"] = rich.console.Console()
    return _state["console"]

def set_log_fn(fn):
    _state["log_fn"] = fn

# ─── Résolution de bird ───────────────────────────────────────────────────────

def _bird():
    """
    Retourne la fonction bird. Tente de la charger via apix si elle n'est
    pas encore en cache. Si apix est indisponible, retombe sur un print
    basique de façon silencieuse.
    """
    if _state["bird"] is not None:
        return _state["bird"]
    try:
        fn = core.bird.R_ECO3(None)
        if callable(fn):
            _state["bird"] = fn
            return fn
    except Exception:
        pass
    import builtins
    _state["bird"] = builtins.print
    return _state["bird"]

# ─── Helpers publics ──────────────────────────────────────────────────────────
# print / ok / err / rule délèguent à bird.
# panel / banner continuent d'utiliser Rich directement (widgets non couverts
# par bird).

def null(*args, **kwargs):
    pass

def print(msg: str = "", **kwargs):
    """Affiche un message avec markup via bird."""
    _bird()(str(msg))

def err(msg: str):
    """Affiche un message d'erreur (croix rouge) via bird."""
    _bird()(f"[bold red]  ✗ {msg}[/]")

def ok(msg: str):
    """Affiche un message de succès (coche verte) via bird."""
    _bird()(f"[bold green]  ✓ {msg}[/]")

def rule(text: str = "", style: str = "blue dim"):
    """Dessine un séparateur horizontal via bird.rule."""
    b = _bird()
    b("")
    if hasattr(b, "rule"):
        b.rule(title=text, style=style) #type: ignore
    else:
        # Fallback si bird.rule absent
        _console().rule(text, style=style)

def banner():
    """Affiche la bannière RAVEN. Utilise Rich pour le rendu centré/aligné."""
    c = _console()
    c.print()
    c.print(Align.center(Text(RAVEN_BANNER, style="bold blue", justify="center")))
    c.print(Align.center(Text("New layer exploitation system & research engine", style="dim cyan", justify="center")))
    c.print(Align.center(Text("v1.1  ·  R-ECO3", style="dim", justify="center")))
    c.print()
    c.rule(style="blue dim")
    c.print()

def panel(
    content: str,
    title: str = "",
    border: str = "blue",
    padding=(1, 2),
    align: str = "left",
    width: int | None = None,
    subtitle: str = "",
    box_style: str = "ROUNDED",
):
    """Affiche un panel encadré. Utilise Rich (bird ne couvre pas Panel)."""
    body = Text.from_markup(content)
    p = Panel(
        Align(body, align=align) if align in ("center", "right") else body,
        title=Text.from_markup(title) if title else None,
        subtitle=Text.from_markup(subtitle) if subtitle else None,
        border_style=border,
        box=BOX_STYLES.get(box_style.upper(), rich_box.ROUNDED),
        padding=padding,
        width=width,
        expand=width is None,
    )
    _console().print(Align.center(p) if align == "center" and width else p)

# ─── Entrées interactives ─────────────────────────────────────────────────────

def ask(text: str, default=None, cant_none: bool = True, password: bool = False) -> str | None:
    try:
        res = Prompt.ask(text, default=default, console=_console(), password=password)
        if cant_none and (res is None or res.strip() == ""):
            err("This field cannot be empty.")
            return ask(text, default=default, cant_none=cant_none, password=password)
        return res
    except KeyboardInterrupt:
        return None

def input(text: str, default: str = "") -> str | None:
    try:
        _console().print()
        result = questionary.text(text, default=default, style=RAVEN_STYLE, qmark="›").ask()
        _console().print()
        return result
    except KeyboardInterrupt:
        return None

def question(text: str, choices: list[str] | None = None, default=None, multi: bool = False) -> str | list[str] | None:
    if not choices:
        return input(text, default=default or "")
    if multi:
        return checkbox(text, choices)
    return select(text, choices)

def confirm(text: str, default: bool = False) -> bool:
    try:
        return Confirm.ask(text, console=_console(), default=default)
    except (KeyboardInterrupt, Exception):
        return False

def select(text: str, choices: list[str]) -> str | None:
    try:
        _console().print()
        result = questionary.select(text, choices=choices, style=RAVEN_STYLE, qmark="›", pointer="❯").ask()
        _console().print()
        return result
    except KeyboardInterrupt:
        return None

def checkbox(text: str, choices: list[str]) -> list[str]:
    try:
        _console().print()
        result = questionary.checkbox(text, choices=choices, style=RAVEN_STYLE, qmark="›", pointer="❯").ask()
        _console().print()
        return result or []
    except KeyboardInterrupt:
        return []

# ─── Loader ───────────────────────────────────────────────────────────────────

class Loader:
    FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, msg: str = "Loading…", delay: float = 0.08):
        self.msg   = msg
        self.delay = delay
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _spin(self):
        b = _bird()
        for frame in itertools.cycle(self.FRAMES):
            if self._stop.is_set():
                break
            b(f"\r[bold cyan]{frame}[/] [dim]{self.msg}[/]", end="")
            time.sleep(self.delay)

    def start(self) -> "Loader":
        self._stop.clear()
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()
        return self

    def stop(self, final_msg: str = ""):
        self._stop.set()
        if self._thread:
            self._thread.join()
        b = _bird()
        b("\r" + " " * (len(self.msg) + 6) + "\r", end="")
        if final_msg:
            b(final_msg)

    def __enter__(self) -> "Loader":
        return self.start()

    def __exit__(self, *_):
        self.stop()

_loader_instance: Loader | None = None

def loader(msg: str = "Loading…", seconds: float | None = None) -> Loader:
    l = Loader(msg)
    l.start()
    if seconds is not None:
        def _auto_stop():
            time.sleep(seconds)
            l.stop()
        threading.Thread(target=_auto_stop, daemon=True).start()
    return l

# ─── R_ECO3 API ───────────────────────────────────────────────────────────────

def R_ECO3(inp):
    log_fn = inp["logfn"]
    args = inp["args"] 
    global _loader_instance

    set_log_fn(log_fn)

    try:
        import core
        pos, kv = core.utils.parse_command(str(args))
    except Exception as e:
        err(f"[banana] parse error: {e}")
        return 1, None

    if not pos:
        return 0, None

    cmd = pos[0]

    if cmd == "banner":
        banner()
        return 0, None

    if cmd == "err":
        err(str(kv.get("msg", " ".join(pos[1:]))))
        return 0, None

    if cmd == "ok":
        ok(str(kv.get("msg", " ".join(pos[1:]))))
        return 0, None

    if cmd == "print":
        print(str(kv.get("msg", " ".join(pos[1:]))))
        return 0, None

    if cmd == "rule":
        rule(str(kv.get("text", " ".join(pos[1:]))), style=str(kv.get("style", "blue dim")))
        return 0, None

    if cmd == "panel":
        panel(
            content   = kv.get("msg",      " ".join(pos[1:])),  # type: ignore
            title     = kv.get("title",    ""),                 # type: ignore
            border    = kv.get("border",   "blue"),             # type: ignore
            align     = kv.get("align",    "left"),             # type: ignore
            subtitle  = kv.get("subtitle", ""),                 # type: ignore
            box_style = kv.get("box",      "ROUNDED"),          # type: ignore
            width     = int(kv["width"]) if kv.get("width") else None,
        )
        return 0, None

    if cmd == "input":
        result = input(str(kv.get("msg", " ".join(pos[1:]))), default=str(kv.get("default", "")))
        return 0, result

    if cmd == "question":
        raw_ch  = kv.get("choices", "")
        choices = [c.strip() for c in raw_ch.split(",") if c.strip()] if raw_ch else None   # type: ignore
        multi   = kv.get("multi", "false").lower() in ("1", "true", "yes")                  # type: ignore
        result  = question(str(kv.get("msg", " ".join(pos[1:]))), choices=choices, default=kv.get("default"), multi=multi)
        return 0, result

    if cmd == "loader":
        sub = pos[1] if len(pos) > 1 else ""
        msg = kv.get("msg", "Loading…")

        if sub == "start":
            if _loader_instance is not None:
                _loader_instance.stop()
            _loader_instance = Loader(str(msg))
            _loader_instance.start()
            return 0, None

        if sub == "stop":
            if _loader_instance is not None:
                final = str(msg) if msg != "Loading…" else ""
                _loader_instance.stop(final_msg=final)
                _loader_instance = None
            return 0, None

        raw_time = kv.get("time", None)
        if raw_time is not None:
            try:
                loader(str(msg), seconds=float(raw_time))
                return 0, None
            except ValueError:
                err(f"loader: valeur --time invalide '{raw_time}'")
                return 1, None

        err("loader: usage → loader start|stop --msg=X  ou  loader --msg=X --time=N")
        return 1, None

    err(f"[banana] unknown command: '{cmd}'")
    return 1, None

def R_ECO3dep():
    """Retourne les dépendances minimales de la version système actuelle."""
    return {
        "reco": ["3.5.2b"],
        "module": []
    }

def R_ECO3inf():
    return {
        "name": "banana",
        "desc": "Banana RAVEN UI — display and interactions via Rich/Questionary",
        "help": "Graphical and interactive user interface module for RAVEN, designed to manage rich text displays, structured panels, animated loaders, and stylized user prompts.",
        "version_mod": "2.1",
        "alias_rules": "banana /* = banana err --msg='This module cannot be run without arguments. Please refer to the manual for usage instructions.'",
        "L2Module": True,
        "manual": (
            "banana — RAVEN UI module  v1.1\n"
            "==============================\n"
            "\n"
            "SYNOPSIS\n"
            "    banana <command> [args...]\n"
            "    banana banner\n"
            "    banana print  [--msg=X]\n"
            "    banana ok     [--msg=X]\n"
            "    banana err    [--msg=X]\n"
            "    banana rule   [--text=X] [--style=S]\n"
            "    banana panel  [--msg=X] [--title=T] [--subtitle=S] [--border=B] [--align=A] [--box=B_STYLE] [--width=N]\n"
            "    banana input  [--msg=X] [--default=D]\n"
            "    banana question [--msg=X] [--choices=a,b,c] [--multi=true|false] [--default=D]\n"
            "    banana loader start|stop [--msg=X]\n"
            "    banana loader [--msg=X] [--time=N]\n"
            "\n"
            "COMMANDS\n"
            "    banner\n"
            "        Displays the RAVEN system welcome banner.\n"
            "\n"
            "    print [--msg=X]\n"
            "        Prints text with Rich markup via bird.\n"
            "        Uses --msg or positional text.\n"
            "\n"
            "    ok [--msg=X]\n"
            "        Prints a success message prefixed with a green checkmark (✓).\n"
            "\n"
            "    err [--msg=X]\n"
            "        Prints an error message prefixed with a red cross (✗).\n"
            "\n"
            "    rule [--text=X] [--style=S]\n"
            "        Draws a horizontal separator line.\n"
            "        --style defaults to 'blue dim'.\n"
            "\n"
            "    panel [--msg=X] [--title=T] [--subtitle=S] [--border=B] [--align=left|center|right] [--box=B_STYLE] [--width=N]\n"
            "        Displays a framed Rich Panel.\n"
            "        Box styles: ROUNDED (default), HEAVY, DOUBLE, SIMPLE, MINIMAL, ASCII, SQUARE, MARKDOWN.\n"
            "\n"
            "    input [--msg=X] [--default=D]\n"
            "        Prompts the user for a single-line text input.\n"
            "        Returns the entered string.\n"
            "\n"
            "    question [--msg=X] [--choices=a,b,c] [--multi=true|false] [--default=D]\n"
            "        Prompts the user with a selection list.\n"
            "        Without --choices: falls back to a plain text input.\n"
            "        With --multi=true: renders a checkbox list; returns a list of selected values.\n"
            "\n"
            "    loader start [--msg=X]\n"
            "        Starts a persistent asynchronous spinner.\n"
            "        Must be stopped explicitly with 'loader stop'.\n"
            "\n"
            "    loader stop [--msg=X]\n"
            "        Stops the active spinner and prints an optional final message.\n"
            "\n"
            "    loader [--msg=X] [--time=N]\n"
            "        Runs a spinner that automatically stops after N seconds.\n"
            "\n"
            "EXAMPLES\n"
            "    banana banner\n"
            "    banana ok --msg=\"Build complete\"\n"
            "    banana err --msg=\"File not found\"\n"
            "    banana panel --msg=\"Summary\" --title=\"Result\" --border=green --box=HEAVY\n"
            "    banana question --msg=\"Choose env\" --choices=\"dev,staging,prod\"\n"
            "    banana loader start --msg=\"Fetching…\"\n"
            "    banana loader stop --msg=\"Done\"\n"
            "    banana loader --msg=\"Compiling…\" --time=3\n"
        )
    }