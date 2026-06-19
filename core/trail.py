"""
core/trail.py
Toutes les autres parties du projet importent depuis ici.
Ne jamais utiliser __file__ ou os.getcwd() ailleurs.
"""
from pathlib import Path

# Racine du projet = dossier qui contient R_ECO.py
ROOT = Path(__file__).resolve().parent.parent

MODULES_DIR = ROOT / "modules"
DATA_DIR    = ROOT / "data"
CONFIG_FILE = ROOT / "R_ECO.cfg"
DB_FILE     = DATA_DIR / "data.hive"

def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    MODULES_DIR.mkdir(parents=True, exist_ok=True)
    
def R_ECO3(args, log_fn=print):
    log_fn("Trail, provide R-ECOSYSTEM information.")
    
def R_ECO3dep():
    return {
        "reco": ["3.5.2b"],
        "module": [],
    }

def R_ECO3inf():
    return {
        "name": "trail",
        "desc": "Trail, give R-ECOSYSTEM information",
        "help": "No argument, it's an API",
        "version_mod": "3.5.2b",
    }
