"""
core/apix.py
Remplace le code importlib répété dans chaque module.
"""
import importlib.util
import sys
from pathlib import Path
from core.trail import MODULES_DIR
from core.utils import parse_command


def load_module(name: str, path: Path | None = None):
    """
    Charge un module par son nom (cherché dans MODULES_DIR par défaut).
    Met en cache dans sys.modules pour éviter les doubles chargements.
    """
    if name in sys.modules:
        return sys.modules[name]

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


def run_module_cmd(name: str, command: str, *args, log_fn=print):
    """
    Appelle R_ECO3 / R_ECO3dep / R_ECO3inf sur un module par nom.
    Retourne (0, valeur) en succès, (0, 0) si None, (1, message) en erreur.
    """
    try:
        mod = load_module(name)
    except Exception as e:
        log_fn(f"[apix] Erreur chargement module '{name}': {e}")
        return (1, str(e))

    dispatch = {
        "run": getattr(mod, "R_ECO3",    None),
        "dep": getattr(mod, "R_ECO3dep", None),
        "inf": getattr(mod, "R_ECO3inf", None),
    }
    fn = dispatch.get(command)
    if fn is None:
        msg = f"Commande '{command}' inconnue pour le module '{name}'"
        log_fn(f"[apix] {msg}")
        return (1, msg)

    try:
        str_args = " ".join(str(a) for a in args)
        if command == "run":
            result = fn(str_args, log_fn=log_fn)
        else:
            result = fn()
    except Exception as e:
        log_fn(f"[apix] Erreur exécution '{command}' sur '{name}': {e}")
        return (1, str(e))

    return (0, 0) if result is None else (0, result)


def R_ECO3(args, log_fn=print):
    parts = args.split(None, 2)   # max 3 morceaux
    if len(parts) < 2:
        return (1, "usage: <command> <module> [args]")
    command  = parts[0]
    module   = parts[1]
    rest_str = parts[2] if len(parts) > 2 else ""
    return run_module_cmd(module, command, rest_str, log_fn=log_fn)


def R_ECO3dep():
    
    return (("3.5.1b",), (("core.trail", ("1.1",)),))

def R_ECO3inf():
    return {
        "name": "apix",
        "desc": "Apix, run a module",
        "help": "run,dep,inf module *args",
        "version_mod": "1.1",
    }
