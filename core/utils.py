import re
def tokenize(command: str) -> list[str]:
    """
    Découpe la commande en tokens en respectant les guillemets
    simples et doubles, sans shlex ni re.
    """
    tokens = []
    current = []
    in_quote = None  # None | '"' | "'"
 
    for char in command:
        if in_quote:
            if char == in_quote:
                in_quote = None          # fermeture du guillemet
            else:
                current.append(char)
        elif char in ('"', "'"):
            in_quote = char              # ouverture du guillemet
        elif char == ' ':
            if current:
                tokens.append(''.join(current))
                current = []
        else:
            current.append(char)
 
    if in_quote:
        raise ValueError(f"Guillemet '{in_quote}' non fermé dans la commande")
 
    if current:
        tokens.append(''.join(current))
 
    return tokens
 
def parse_command(command: str) -> tuple[list[str], dict[str, str | bool]]:
    """
    Parse une chaîne de commande et retourne :
      - positional (list[str])           : arguments sans tiret
      - kv         (dict[str, str|bool]) : arguments avec clé

    Formats supportés :
      run file.txt          → positional
      -v                    → {v: True}
      -ale                  → {a: True, l: True, e: True}
      -f=value              → {f: 'value'}
      -f value              → {f: 'value'}
      --key                 → {key: True}
      --key=value           → {key: 'value'}
      --key value           → {key: 'value'}
      --key=val ue          → {key: 'val ue'}   ← NOUVEAU : valeur avec espace
      --key val ue          → {key: 'val ue'}   ← NOUVEAU : idem via token suivant

    Règle de fin de valeur multi-token :
      La capture s'arrête dès qu'on rencontre un token qui commence par '-'
      ou qu'on atteint la fin de la chaîne.

    Clés répétées :
      --header=A --header=B → {header: ['A', 'B']}
    """
    tokens = tokenize(command)
    positional: list[str] = []
    kv: dict[str, str | bool | list] = {}

    def _store(k: str, v: str | bool) -> None:
        """Stocke k→v ; si k existe déjà, convertit en liste."""
        if k in kv:
            existing = kv[k]
            if isinstance(existing, list):
                existing.append(v)
            else:
                kv[k] = [existing, v]
        else:
            kv[k] = v

    def _collect_value(start: int) -> tuple[str, int]:
        """
        À partir de l'index `start`, collecte tous les tokens consécutifs
        qui ne commencent pas par '-' et les joint avec un espace.
        Retourne (valeur_assemblée, nouvel_index).
        """
        parts = []
        j = start
        while j < len(tokens) and not tokens[j].startswith('-'):
            parts.append(tokens[j])
            j += 1
        return ' '.join(parts), j - 1  # j-1 car la boucle principale fera i+=1

    i = 0
    while i < len(tokens):
        token = tokens[i]

        if token.startswith('--'):
            body = token[2:]
            if '=' in body:
                key, _, val_start = body.partition('=')
                # val_start peut être vide si le = est en fin de token
                if val_start:
                    # Vérifier si les tokens suivants prolongent la valeur
                    if i + 1 < len(tokens) and not tokens[i + 1].startswith('-'):
                        extra, i = _collect_value(i + 1)
                        _store(key, val_start + ' ' + extra)
                    else:
                        _store(key, val_start)
                else:
                    # --key= sans valeur → capturer les tokens suivants
                    if i + 1 < len(tokens) and not tokens[i + 1].startswith('-'):
                        val, i = _collect_value(i + 1)
                        _store(key, val)
                    else:
                        _store(key, True)
            else:
                # --key sans =
                if i + 1 < len(tokens) and not tokens[i + 1].startswith('-'):
                    val, i = _collect_value(i + 1)
                    _store(body, val)
                else:
                    _store(body, True)

        elif token.startswith('-'):
            body = token[1:]
            if '=' in body:
                key, _, value = body.partition('=')
                _store(key, value)
            elif len(body) > 1:
                # flags groupés : -ale → a, l, e booléens
                for flag in body:
                    _store(flag, True)
            else:
                if i + 1 < len(tokens) and not tokens[i + 1].startswith('-'):
                    val, i = _collect_value(i + 1)
                    _store(body, val)
                else:
                    _store(body, True)

        else:
            positional.append(token)

        i += 1

    return positional, kv  

def check_version(v_required, v_get):
    """
    Vérifie la compatibilité de version.
    Retourne True si OK, (1, detail) si v_get est trop vieille/incompatible,
    (-1, detail) si v_get est plus récente que prévu.

    Types supportés :
      t1 : a.b[d]     ex: "1.2", "1.2b"
      t2 : a.b.c[d]   ex: "1.2.3", "1.2.3rc"
    """

    def parse(v):
        parts = v.split(".")
        # Strip le descriptor (lettres) du dernier segment
        last_num = re.match(r"(\d+)", parts[-1])
        if not last_num:
            return None, None
        parts[-1] = last_num.group(1)
        try:
            nums = [int(p) for p in parts]
        except ValueError:
            return None, None
        if len(nums) == 2:
            return 1, nums
        if len(nums) == 3:
            return 2, nums
        return None, None

    t_req, p_req = parse(v_required)
    t_get, p_get = parse(v_get)

    if t_req is None or t_get is None:
        return (1, "Format de version invalide")

    # --- Types différents ---
    if t_req != t_get:
        return (1, f"Types incompatibles : requis t{t_req} ({v_required}), obtenu t{t_get} ({v_get})")

    # --- t1 : a.b[d] ---
    if t_req == 1:
        a_r, b_r = p_req
        a_g, b_g = p_get

        if a_g < a_r:
            return (1,  f"Majeure insuffisante : {a_g} < {a_r}")
        if a_g > a_r:
            return (-1, f"Majeure supérieure   : {a_g} > {a_r}")

        if b_g < b_r:
            return (1,  f"Mineure insuffisante : {b_g} < {b_r}")
        if b_g > b_r:
            return (-1, f"Mineure supérieure   : {b_g} > {b_r}")  # ← manquait

        return True

    # --- t2 : a.b.c[d] ---
    a_r, b_r, c_r = p_req
    a_g, b_g, c_g = p_get

    if a_g != a_r:
        return (1,  f"Majeure différente   : {a_g} ≠ {a_r}")

    if b_g < b_r:
        return (1,  f"Mineure insuffisante : {b_g} < {b_r}")
    if b_g > b_r:
        return (-1, f"Mineure supérieure   : {b_g} > {b_r}")

    # b identique → on passe à c
    if c_g < c_r:
        return (1,  f"Patch insuffisant    : {c_g} < {c_r}")

    # c >= requis → ok
    return True
    
def R_ECO3(args, log_fn=print):
    log_fn("utils")

def R_ECO3dep():
    return (("3.5.1b",), (("core.trail", ("1.1",)),))

def R_ECO3inf():
    return {
        "name": "utils",
        "desc": "Utils, outils utiles",
        "help": "No argument, it's an API",
        "version_mod": "1.1",
    }
