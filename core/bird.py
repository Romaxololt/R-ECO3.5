import sys
import re
import os
import builtins
import shutil
import colorama
from colorama import Fore, Back, Style as CStyle
from typing import Any, Optional

colorama.init(autoreset=False)

# ── Détection de support couleur ──────────────────────────────────────────────

_COLOR_ENABLED = (
    os.environ.get("NO_COLOR") is None
    and os.environ.get("TERM") != "dumb"
    and hasattr(sys.stdout, "isatty")
    and sys.stdout.isatty()
)

# ── Mapping des tags → codes ANSI ────────────────────────────────────────────

_STYLES = {
    # Poids / décoration
    "bold":              "\033[1m",
    "dim":               "\033[2m",
    "italic":            "\033[3m",
    "underline":         "\033[4m",
    "blink":             "\033[5m",
    "reverse":           "\033[7m",
    "strike":            "\033[9m",
    # Couleurs texte
    "black":             Fore.BLACK,
    "red":               Fore.RED,
    "green":             Fore.GREEN,
    "yellow":            Fore.YELLOW,
    "blue":              Fore.BLUE,
    "magenta":           Fore.MAGENTA,
    "cyan":              Fore.CYAN,
    "white":             Fore.WHITE,
    "bright_black":      Fore.LIGHTBLACK_EX,
    "bright_red":        Fore.LIGHTRED_EX,
    "bright_green":      Fore.LIGHTGREEN_EX,
    "bright_yellow":     Fore.LIGHTYELLOW_EX,
    "bright_blue":       Fore.LIGHTBLUE_EX,
    "bright_magenta":    Fore.LIGHTMAGENTA_EX,
    "bright_cyan":       Fore.LIGHTCYAN_EX,
    "bright_white":      Fore.LIGHTWHITE_EX,
    # Couleurs fond
    "bg_black":          Back.BLACK,
    "bg_red":            Back.RED,
    "bg_green":          Back.GREEN,
    "bg_yellow":         Back.YELLOW,
    "bg_blue":           Back.BLUE,
    "bg_magenta":        Back.MAGENTA,
    "bg_cyan":           Back.CYAN,
    "bg_white":          Back.WHITE,
    "bg_bright_black":   Back.LIGHTBLACK_EX,
    "bg_bright_red":     Back.LIGHTRED_EX,
    "bg_bright_green":   Back.LIGHTGREEN_EX,
    "bg_bright_yellow":  Back.LIGHTYELLOW_EX,
    "bg_bright_blue":    Back.LIGHTBLUE_EX,
    "bg_bright_magenta": Back.LIGHTMAGENTA_EX,
    "bg_bright_cyan":    Back.LIGHTCYAN_EX,
    "bg_bright_white":   Back.LIGHTWHITE_EX,
}

_RESET_ALL = CStyle.RESET_ALL

# ── Résolution des parties de tag ─────────────────────────────────────────────

def _parse_part(part: str) -> str:
    """
    Résout une partie de tag en code ANSI.
    Gère les tags simples, color=N (256), bg_color=N, rgb=R,G,B, bg_rgb=R,G,B.
    Lève ValueError si la valeur est invalide.
    """
    # Couleur 256 — texte
    if part.startswith("color="):
        n = int(part[6:])
        if not (0 <= n <= 255):
            raise ValueError(f"color index hors plage: {n}")
        return f"\033[38;5;{n}m"

    # Couleur 256 — fond
    if part.startswith("bg_color="):
        n = int(part[9:])
        if not (0 <= n <= 255):
            raise ValueError(f"bg_color index hors plage: {n}")
        return f"\033[48;5;{n}m"

    # RGB — texte
    if part.startswith("rgb="):
        r, g, b = (int(x) for x in part[4:].split(","))
        for v in (r, g, b):
            if not (0 <= v <= 255):
                raise ValueError(f"rgb hors plage: {v}")
        return f"\033[38;2;{r};{g};{b}m"

    # RGB — fond
    if part.startswith("bg_rgb="):
        r, g, b = (int(x) for x in part[7:].split(","))
        for v in (r, g, b):
            if not (0 <= v <= 255):
                raise ValueError(f"bg_rgb hors plage: {v}")
        return f"\033[48;2;{r};{g};{b}m"

    # Tag standard
    return _STYLES.get(part, "")


# ── Parseur de markup ─────────────────────────────────────────────────────────

_TAG_RE = re.compile(r'\[(/?)([^\[\]]*)\]')

# Sentinelles pour l'échappement des crochets littéraux
_ESC_OPEN  = "\x00LBRACKET\x00"
_ESC_CLOSE = "\x00RBRACKET\x00"


def _resolve_tag(tag: str) -> str:
    """Retourne le code ANSI pour un tag composite comme 'bold red bg_blue'."""
    codes = []
    for part in tag.lower().split():
        try:
            code = _parse_part(part)
        except (ValueError, IndexError):
            continue  # partie invalide → ignorée silencieusement
        if code:
            codes.append(code)
    return "".join(codes)


def _render_markup(text: str) -> str:
    """
    Remplace les tags [bold red]...[/] par les séquences ANSI.
    Supporte l'échappement \\[ et \\] pour les crochets littéraux.
    Si _COLOR_ENABLED est False, les tags sont simplement supprimés.
    """
    # Échappement des crochets littéraux
    text = text.replace("\\[", _ESC_OPEN).replace("\\]", _ESC_CLOSE)

    result = []
    stack = []
    last = 0

    for m in _TAG_RE.finditer(text):
        result.append(text[last:m.start()])
        last = m.end()

        closing, tag = m.group(1), m.group(2).strip()

        if closing:
            if stack:
                stack.pop()
            if _COLOR_ENABLED:
                result.append(_RESET_ALL)
                for codes in stack:
                    result.append(codes)
        else:
            codes = _resolve_tag(tag)
            if codes:
                stack.append(codes)
                if _COLOR_ENABLED:
                    result.append(codes)
            else:
                result.append(m.group(0))   # tag inconnu → laissé tel quel

    result.append(text[last:])

    if stack and _COLOR_ENABLED:
        result.append(_RESET_ALL)

    # Restauration des crochets échappés
    out = "".join(result)
    out = out.replace(_ESC_OPEN, "[").replace(_ESC_CLOSE, "]")
    return out


# ── Helpers visuels ───────────────────────────────────────────────────────────

def _terminal_width() -> int:
    """Retourne la largeur du terminal, 80 par défaut."""
    return shutil.get_terminal_size(fallback=(80, 24)).columns


def _strip_markup(text: str) -> str:
    """Supprime tous les tags [..] du texte (pour calculer la longueur visible)."""
    text = text.replace("\\[", _ESC_OPEN).replace("\\]", _ESC_CLOSE)
    clean = _TAG_RE.sub(
        lambda m: "" if _resolve_tag(m.group(2).strip()) or m.group(1) else m.group(0),
        text,
    )
    return clean.replace(_ESC_OPEN, "[").replace(_ESC_CLOSE, "]")


def _rule(
        title: str = "",
        char: str = "─",
        width: Optional[int] = None,
        style: str = "dim",
        title_style: str = "bold",
        file=None,
        flush: bool = False,
    ) -> None:
    """
    Affiche un séparateur horizontal, optionnellement titré.

    Exemple :
        bird.rule("Section", style="bold cyan")
        bird.rule()
    """
    w = width or _terminal_width()
    if title:
        visible_len = len(_strip_markup(title))
        pad = max(1, (w - visible_len - 2) // 2)
        extra = (w - visible_len - 2) % 2   # compense la parité
        line = (
            f"[{style}]{char * pad}[/] "
            f"[{title_style}]{title}[/] "
            f"[{style}]{char * (pad + extra)}[/]"
        )
    else:
        line = f"[{style}]{char * w}[/]"
    bird(line, file=file, flush=flush)


def _table(
        rows: list,
        headers: Optional[list] = None,
        header_style: str = "bold",
        border_style: str = "dim",
        col_sep: str = " │ ",
        padding: int = 1,
        file=None,
        flush: bool = False,
    ) -> None:
    """
    Affiche un tableau ASCII avec alignement automatique des colonnes.
    Les cellules peuvent contenir du markup bird.

    Exemple :
        bird.table(
            headers=["Nom", "Statut", "Score"],
            rows=[
                ["Alice", "[green]OK[/]",  "98"],
                ["Bob",   "[red]ERR[/]",   "—" ],
            ],
        )
    """
    all_rows = ([headers] if headers else []) + rows
    # Calcul des largeurs max par colonne (sur le texte visible)
    n_cols = max(len(r) for r in all_rows)
    widths = [0] * n_cols
    for row in all_rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(_strip_markup(str(cell))))

    pad = " " * padding

    def _fmt_row(row, row_style: str = "") -> str:
        cells = []
        for i in range(n_cols):
            cell = str(row[i]) if i < len(row) else ""
            visible = len(_strip_markup(cell))
            cell_padded = cell + " " * (widths[i] - visible)
            if row_style:
                cells.append(f"[{row_style}]{pad}{cell_padded}{pad}[/]")
            else:
                cells.append(f"{pad}{cell_padded}{pad}")
        sep = f"[{border_style}]{col_sep}[/]"
        return sep.join(cells)

    def _separator(char="─", cross="┼", left="├", right="┤") -> str:
        segs = [char * (widths[i] + 2 * padding) for i in range(n_cols)]
        inner = f"[{border_style}]{cross}[/]".join(
            f"[{border_style}]{s}[/]" for s in segs
        )
        return inner

    if headers:
        bird(_fmt_row(headers, header_style), file=file, flush=flush)
        bird(_separator(), file=file, flush=flush)
        for row in rows:
            bird(_fmt_row(row), file=file, flush=flush)
    else:
        for row in rows:
            bird(_fmt_row(row), file=file, flush=flush)


# ── bird ──────────────────────────────────────────────────────────────────────

def bird(
        *objects: Any,
        sep: str = " ",
        end: str = "\n",
        file=None,
        flush: bool = False,
        # Paramètres rich-like (acceptés pour compatibilité)
        style: Optional[str] = None,
        justify=None,
        overflow=None,
        no_wrap: Optional[bool] = None,
        emoji: Optional[bool] = None,
        markup: Optional[bool] = True,
        highlight: Optional[bool] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
        crop: bool = True,
        soft_wrap: Optional[bool] = None,
        new_line_start: bool = False,
    ):
    """
    Remplacement de print() avec markup ANSI inline.

    Balises :
      [bold], [red], [bg_blue], [bold bright_cyan bg_black], …
      [color=196], [rgb=255,100,0], [bg_color=22], [bg_rgb=0,50,100]
      [/] ou [/bold]  → fermeture
      \\[ et \\]       → crochets littéraux

    Respecte NO_COLOR et TERM=dumb (désactive silencieusement les codes ANSI).
    """
    if file is None:
        file = sys.stdout

    text = sep.join(str(o) for o in objects)

    # Style global
    if style:
        prefix = _resolve_tag(style)
        if prefix and _COLOR_ENABLED:
            text = f"{prefix}{text}{_RESET_ALL}"

    # Markup inline
    if markup is not False:
        text = _render_markup(text)

    if new_line_start:
        text = "\n" + text

    builtins.print(text, end=end, file=file, flush=flush)


# Attacher les helpers directement sur la fonction
bird.rule  = _rule #type: ignore
bird.table = _table #type: ignore


# ── Interface R_ECO ───────────────────────────────────────────────────────────

def R_ECO3(inp):
    return bird

def R_ECO3dep():
    return {
        "reco": ["3.5.2b"],
        "module": [],
    }


def R_ECO3inf():
    """Retourne les métadonnées et l'aide pour bird."""
    return {
        "name": "bird",
        "desc": "Fonction d'affichage avec markup ANSI inline",
        "help": (
            "Retourne une fonction print enrichie supportant le markup inline [bold red]...[/]. "
            "Usage : code, fn = apix.R_ECO3('run bird') — fn est ensuite utilisable comme print().\n"
            "Helpers : fn.rule(title, style=...) et fn.table(rows, headers=...)."
        ),
        "version_mod": "3.5.2b",
        "L2Module": False,
        "manual": (
            "bird — ANSI markup print function  v1.2\n"
            "=======================================\n"
            "\n"
            "SYNOPSIS\n"
            "    bird [text...]\n"
            "    bird.rule(title='', char='─', width=None, style='dim')\n"
            "    bird.table(rows, headers=None, header_style='bold', border_style='dim')\n"
            "\n"
            "DESCRIPTION\n"
            "    bird() is a print replacement that renders inline ANSI markup.\n"
            "    It supports tags like bold, red, bold red, 256 colors, RGB colors,\n"
            "    and escaping with \\[ and \\].\n"
            "\n"
            "EXAMPLES\n"
            "    bird('[bold green]OK[/] build complete')\n"
            "    bird.rule('Results', style='bold cyan')\n"
            "    bird.table([\n"
            "        ['Alice', '[green]OK[/]'],\n"
            "        ['Bob', '[red]ERR[/]'],\n"
            "    ], headers=['Name', 'Status'])\n"
        ),
    }