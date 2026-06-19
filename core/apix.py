"""
core/apix.py
Remplace le code importlib répété dans chaque module.
"""
import importlib.util
import sys
from pathlib import Path

from core.trail import MODULES_DIR
from modules.banana import err


# ── Chargement dynamique ──────────────────────────────────────────────────────

def _load_module(name: str, path: Path | None = None):
    """Charge un module par nom, avec mise en cache dans sys.modules."""

    module_path = path or (MODULES_DIR / f"{name}.py")
    if not module_path.exists():
        raise FileNotFoundError(f"Module '{name}' introuvable : {module_path}")

    spec = importlib.util.spec_from_file_location(name, module_path)
    if not spec or not spec.loader:
        raise ImportError(f"Impossible de charger '{name}'")

    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# ── Helpers ───────────────────────────────────────────────────────────────────

_ENTRY_POINTS = {
    "run": "R_ECO3",
    "dep": "R_ECO3dep",
    "inf": "R_ECO3inf",
}

def _ok(value=None):
    return {"status": 0, "value": value}

def _fail(value=err):
    return {"status": 1, "value": value}

def _wrap(result):
    """
    Normalise un retour brut en {"status", "value"}.
    Types acceptés :
      - dict avec "status"          → passthrough
      - tuple (status, value)       → {"status": status, "value": value}
      - None                        → {status:0, value:0}
      - 0                           → {status:0, value:0}
      - 1                           → {status:1, value:err}
      - toute autre valeur non-None → {status:0, value:val}
    """
    if isinstance(result, dict) and "status" in result:
        return result
    
    if isinstance(result, tuple) and len(result) == 2:
        status, value = result
        if isinstance(status, int) and status in (0, 1):
            return {"status": status, "value": value}
    
    if result is None or result == 0:
        return _ok(0)
    if result == 1:
        return _fail(err)
    if isinstance(result, (str, list, dict, int, float, bool)):
        return _ok(result)
    
    raise TypeError(f"[apix] Type de retour non géré : {type(result).__name__!r} — valeur : {result!r}")


def _list_all_modules() -> list[str]:
    """Retourne les noms de tous les .py dans MODULES_DIR (sans extension)."""
    return sorted(p.stem for p in MODULES_DIR.glob("*.py") if p.stem != "__init__")

def _is_l2_module(name: str) -> bool:
    """
    Retourne True si le module expose R_ECO3, R_ECO3dep, R_ECO3inf
    et que R_ECO3inf()["L2Module"] is True.
    """
    try:
        mod = _load_module(name)
    except Exception:
        return False

    if not all(hasattr(mod, fn) for fn in _ENTRY_POINTS.values()):
        return False

    try:
        info = mod.R_ECO3inf()
        return bool(info.get("L2Module", False))
    except Exception:
        return False


# ── Dispatch ──────────────────────────────────────────────────────────────────

def _run_module_cmd(name: str, command: str, args: dict, log_fn=print):
    """
    Appelle R_ECO3 / R_ECO3dep / R_ECO3inf sur un module chargé dynamiquement.
    Retourne {"status": 0|1, "value": ...}.
    """
    try:
        mod = _load_module(name)
    except Exception as e:
        log_fn(f"[apix] Erreur chargement module '{name}': {e}")
        return _fail(e)

    fn_name = _ENTRY_POINTS.get(command)
    if fn_name is None:
        log_fn(f"[apix] Commande '{command}' inconnue pour '{name}'")
        return _fail(err)

    fn = getattr(mod, fn_name, None)
    if fn is None:
        log_fn(f"[apix] '{fn_name}' absent du module '{name}'")
        return _fail(err)

    try:
        result = fn(args) if command == "run" else fn()
    except Exception as e:
        log_fn(f"[apix] Erreur exécution '{command}' sur '{name}': {e}")
        return _fail(err)

    try:
        return _wrap(result)
    except TypeError as e:
        log_fn(str(e))
        return _fail(err)


# ── Interface publique ────────────────────────────────────────────────────────

def R_ECO3(args: dict):
    parts = args["args"].split(None, 2)
    if not parts:
        return _fail("usage: <command> [module] [args]")

    command = parts[0]

    if command == "list":
        return _ok(_list_all_modules()) #type: ignore

    if command == "listl2":
        return _ok([name for name in _list_all_modules() if _is_l2_module(name)])

    if len(parts) < 2:
        return _fail("usage: <command> <module> [args]")

    if command not in _ENTRY_POINTS:
        return _fail(err)

    module = parts[1]
    rest   = [parts[2]] if len(parts) > 2 else []
    args["args"] = " ".join(rest)
    return _run_module_cmd(module, command, args, log_fn=args["logfn"])


def R_ECO3dep():
    return {
        "reco": ["3.5.2b"],
        "module": [],
    }


def R_ECO3inf():
    return {
        "name": "apix",
        "desc": "Proxy d'exécution de modules — charge, dispatch et encapsule les appels R_ECO3/dep/inf.",
        "help": (
            "Commandes disponibles :\n"
            "  run <module> [args]  — exécute R_ECO3(args) du module\n"
            "  dep <module>         — retourne R_ECO3dep() du module\n"
            "  inf <module>         — retourne R_ECO3inf() du module\n"
            "  list                 — liste tous les modules disponibles dans MODULES_DIR\n"
            "  listl2               — liste les modules L2 (R_ECO3/dep/inf présents + L2Module=True)\n"
            "\n"
            "Retour : {'status': 0|1, 'value': résultat|erreur}\n"
            "Exemple : apix run banana foo bar"
        ),
        "version_mod": "3.5.2b",
        "L2Module": False,
    }