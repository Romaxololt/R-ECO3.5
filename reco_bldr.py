"""
core/reco_bldr.py
Builder de paquets RCPKG1 chiffrés RSA+AES.
Toutes les primitives crypto transitent par core.apix → module rsa.
Aucun import direct de rsa.py.
"""

import os
import json
import time
import fnmatch


# ─────────────────────────────────────────────
#  CONSTANTES
# ─────────────────────────────────────────────

PACKET_MAGIC = "RCPKG1"
RSA_BITS     = 4096


# ═══════════════════════════════════════════════════════════════
#  HELPERS APIX — wrappers fins autour de core.apix
# ═══════════════════════════════════════════════════════════════

def _rsa(cmd: str, log_fn=print):
    import core
    rc, payload = core.apix.R_ECO3(f"run rsa {cmd}", log_fn)
    if rc != 0:
        raise RuntimeError(f"[reco_bldr] apix erreur fatale : {payload}")
    # apix retourne (0, (rc_module, (status, val)))
    # donc payload = (rc_module, (status, val))
    rc2, inner = payload # type: ignore
    if rc2 != 0:
        raise RuntimeError(f"[reco_bldr] rsa erreur : {inner}")
    status, val = inner
    if status != 0:
        raise RuntimeError(f"[reco_bldr] rsa erreur : {val}")
    return val


def _fingerprint(n: int, log_fn=print) -> str:
    return _rsa(f"fingerprint {n}", log_fn)


def _keygen(bits: int = RSA_BITS, log_fn=print):
    """Retourne (n, e, d)."""
    return _rsa(f"keygen {bits}", log_fn)


def _set_key(passphrase: str, bits: int = RSA_BITS, log_fn=print):
    """Retourne (n, e, d) de façon déterministe."""
    return _rsa(f"set_key {passphrase} {bits}", log_fn)


def _encrypt(n: int, d: int, data: bytes, log_fn=print) -> bytes:
    """Chiffrement hybride RSA+AES avec la clé privée."""
    blob = _rsa(f"encrypt {n} {d} {data.hex()}", log_fn)
    # R_ECO3 du module rsa retourne déjà bytes
    return blob if isinstance(blob, bytes) else bytes.fromhex(blob)


def _decrypt(n: int, e: int, blob: bytes, log_fn=print) -> bytes:
    """Déchiffrement hybride avec la clé publique."""
    plain = _rsa(f"decrypt {n} {e} {blob.hex()}", log_fn)
    return plain if isinstance(plain, bytes) else bytes.fromhex(plain)


# ═══════════════════════════════════════════════════════════════
#  SYSTÈME DE FICHIERS
# ═══════════════════════════════════════════════════════════════

def _list_dir(path: str):
    try:
        entries = os.listdir(path)
    except PermissionError:
        return [], []
    dirs  = sorted(e for e in entries if os.path.isdir(os.path.join(path, e)))
    files = sorted(e for e in entries if os.path.isfile(os.path.join(path, e)))
    return dirs, files


def _collect_all(path: str, excludes: list = None) -> list: # type: ignore
    """Collecte récursivement tous les fichiers sous `path`, en excluant les patterns fnmatch."""
    excludes = excludes or []
    result   = []
    for root, dirs, files in os.walk(path):
        dirs[:] = sorted(
            d for d in dirs
            if not any(fnmatch.fnmatch(d, pat) for pat in excludes)
        )
        for f in sorted(files):
            if not any(fnmatch.fnmatch(f, pat) for pat in excludes):
                result.append(os.path.abspath(os.path.join(root, f)))
    return result


def _browse_step(current: str) -> tuple:
    current = os.path.abspath(current)
    dirs, files = _list_dir(current)

    print(f"\n{'─'*50}")
    print(f"  📂  {current}")
    print(f"{'─'*50}")

    if not dirs and not files:
        print("  (dossier vide)")
    else:
        for i, d in enumerate(dirs):
            print(f"  [{i}]  📁  {d}/")
        if files:
            print(f"  ── {len(files)} fichier(s) ──")
            for f in files:
                print(f"       •  {f}")

    print(f"{'─'*50}")
    print("  .§ → valider ici   ..  → parent   q → quitter")
    print()

    try:
        cmd = input("  > ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return None, []

    if cmd in ("q", "quit", "exit"):
        return None, []
    if cmd == ".§":
        return current, _collect_all(current)
    if cmd == "..":
        parent = os.path.dirname(current)
        if parent == current:
            return _browse_step(current)
        return _browse_step(parent)
    if cmd.isdigit():
        idx = int(cmd)
        if 0 <= idx < len(dirs):
            return _browse_step(os.path.join(current, dirs[idx]))
        print(f"  [!] Numéro invalide — plage autorisée : 0–{len(dirs)-1}")
        return _browse_step(current)

    target = os.path.join(current, cmd)
    if os.path.isdir(target):
        return _browse_step(target)
    print(f"  [!] Commande ou chemin inconnu : '{cmd}'")
    return _browse_step(current)


def browse(start: str = ".") -> tuple:
    return _browse_step(start)


# ═══════════════════════════════════════════════════════════════
#  EXPORT / IMPORT CLÉ PUBLIQUE
# ═══════════════════════════════════════════════════════════════

def export_pubkey(n: int, e: int, path: str = "pubkey.json", log_fn=print) -> str:
    fp = _fingerprint(n, log_fn)
    payload = {
        "magic":       "RCPUB1",
        "fingerprint": fp,
        "bits":        n.bit_length(),
        "n":           hex(n),
        "e":           e,
    }
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, indent=2)
    log_fn(f"[+] Clé publique exportée → {path}")
    log_fn(f"[*] Fingerprint : {fp}  ({n.bit_length()} bits)")
    return path


def load_pubkey(path: str, log_fn=print) -> tuple:
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if data.get("magic") != "RCPUB1":
        raise ValueError(f"Format invalide (magic={data.get('magic')!r}, attendu 'RCPUB1')")
    try:
        n = int(data["n"], 16)
        e = int(data["e"])
    except (KeyError, ValueError) as exc:
        raise ValueError(f"Champs n/e manquants ou invalides : {exc}") from exc
    fp = _fingerprint(n, log_fn)
    log_fn(f"[+] Clé publique chargée depuis '{path}'")
    log_fn(f"[*] Fingerprint : {fp}  ({n.bit_length()} bits)")
    return n, e


def pubkey_to_default_snippet(n: int, e: int, log_fn=print) -> str:
    fp   = _fingerprint(n, log_fn)
    bits = n.bit_length()
    snippet = (
        f"# ── Clé publique DEFAULT (fingerprint: {fp}, RSA-{bits}) ──\n"
        f"# Générée par reco_bldr.pubkey_to_default_snippet()\n"
        f"R_ECO_DEFAULT_PUBKEY = {{\n"
        f'    "magic":       "RCPUB1",\n'
        f'    "fingerprint": "{fp}",\n'
        f'    "bits":        {bits},\n'
        f'    "n":           "{hex(n)}",\n'
        f'    "e":           {e},\n'
        f"}}\n"
    )
    log_fn("\n" + "─" * 60)
    log_fn(snippet)
    log_fn("─" * 60)
    log_fn("[*] Colle ce bloc dans R_ECO.py, juste avant R_ECO3().")
    return snippet


# ═══════════════════════════════════════════════════════════════
#  LIST — contenu d'un paquet RCPKG1
# ═══════════════════════════════════════════════════════════════

def list_package(path: str) -> None:
    if not os.path.isfile(path):
        print(f"[✗] Fichier introuvable : '{path}'")
        return
    try:
        with open(path, 'r', encoding='utf-8') as f:
            manifest = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as ex:
        print(f"[✗] Impossible de lire le paquet : {ex}")
        return
    if manifest.get("magic") != PACKET_MAGIC:
        print(f"[✗] Magic invalide ({manifest.get('magic')!r}) — pas un paquet RCPKG1.")
        return

    files      = manifest.get("files", {})
    fp         = manifest.get("fingerprint", "?")
    created_at = manifest.get("created_at", "?")
    src_root   = manifest.get("source_root", "?")
    file_count = manifest.get("file_count", len(files))
    commandes  = manifest.get("commandes", [])
    total_plain = sum(v.get("size", 0) for v in files.values())
    total_enc   = sum(len(v.get("data", "")) // 2 for v in files.values())

    print(f"\n{'═'*58}")
    print(f"  PAQUET  {os.path.basename(path)}")
    print(f"{'─'*58}")
    print(f"  Format      : RCPKG1")
    print(f"  Fingerprint : {fp}")
    print(f"  Créé le     : {created_at}")
    print(f"  Source      : {src_root}")
    print(f"  Fichiers    : {file_count}")
    print(f"  Taille orig : {total_plain:,} octets")
    print(f"  Taille enc  : {total_enc:,} octets")
    if commandes:
        print(f"  Commandes   : {len(commandes)}")
    print(f"{'─'*58}")
    print(f"  {'Nom fichier':<40} {'Taille orig':>12}  Source")
    print(f"  {'─'*40} {'─'*12}  {'─'*20}")
    for fname, meta in sorted(files.items()):
        size   = meta.get("size", 0)
        source = meta.get("source", "")
        short  = ("…" + source[-39:]) if len(source) > 40 else source
        print(f"  {fname:<40} {size:>12,}  {short}")
    if commandes:
        print(f"{'─'*58}")
        print("  Commandes embarquées :")
        for cmd in commandes:
            print(f"      › {cmd}")
    print(f"{'═'*58}\n")


# ═══════════════════════════════════════════════════════════════
#  VERIFY — intégrité d'un paquet avec la clé publique
# ═══════════════════════════════════════════════════════════════

def verify_package(path: str, n: int, e: int, log_fn=print) -> bool:
    if not os.path.isfile(path):
        log_fn(f"[✗] Fichier introuvable : '{path}'")
        return False
    try:
        with open(path, 'r', encoding='utf-8') as f:
            manifest = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as ex:
        log_fn(f"[✗] Impossible de lire le paquet : {ex}")
        return False
    if manifest.get("magic") != PACKET_MAGIC:
        log_fn(f"[✗] Magic invalide ({manifest.get('magic')!r}) — pas un paquet RCPKG1.")
        return False

    pkg_fp = manifest.get("fingerprint", "")
    key_fp = _fingerprint(n, log_fn)
    files  = manifest.get("files", {})
    total  = len(files)

    log_fn(f"\n{'═'*58}")
    log_fn(f"  VÉRIFICATION  {os.path.basename(path)}")
    log_fn(f"{'─'*58}")
    log_fn(f"  Fingerprint paquet : {pkg_fp}")
    log_fn(f"  Fingerprint clé    : {key_fp}")

    if pkg_fp and pkg_fp != key_fp:
        log_fn("  [⚠] Fingerprints différents — la clé fournie peut ne pas correspondre.")
        log_fn("      (La vérification continue quand même.)")
    else:
        log_fn("  [✓] Fingerprints concordants.")
    log_fn(f"{'─'*58}")

    ok_count = err_count = 0
    for i, (fname, meta) in enumerate(sorted(files.items()), 1):
        try:
            blob = bytes.fromhex(meta["data"])
        except (KeyError, ValueError) as ex:
            log_fn(f"  [{i:>3}/{total}]  ✗  {fname:<36}  hex invalide : {ex}")
            err_count += 1
            continue
        try:
            plain         = _decrypt(n, e, blob, lambda *_: None)   # log silencieux
            expected_size = meta.get("size", -1)
            size_ok       = expected_size < 0 or len(plain) == expected_size
            size_tag      = "✓" if size_ok else f"⚠ taille {len(plain)} ≠ {expected_size}"
            log_fn(f"  [{i:>3}/{total}]  ✓  {fname:<36}  {len(plain):>8,} o  {size_tag}")
            ok_count += 1
        except Exception as ex:
            log_fn(f"  [{i:>3}/{total}]  ✗  {fname:<36}  {ex}")
            err_count += 1

    log_fn(f"{'─'*58}")
    if err_count == 0:
        log_fn(f"  [✓] Paquet intact — {ok_count}/{total} fichier(s) vérifiés.")
        verdict = True
    else:
        log_fn(f"  [✗] {err_count} erreur(s) sur {total} fichier(s).")
        log_fn("      Causes possibles : clé incorrecte, données altérées.")
        verdict = False
    log_fn(f"{'═'*58}\n")
    return verdict


# ═══════════════════════════════════════════════════════════════
#  PACK — génère un paquet RCPKG1
# ═══════════════════════════════════════════════════════════════

def pack(
    path_root: str,
    n: int,
    e: int,
    d: int,
    output_ext: str  = ".reco",
    commandes: list  = None, # type: ignore
    excludes:  list  = None, # type: ignore
    log_fn           = print,
):
    commandes = commandes or []
    excludes  = excludes  or []

    name = ""
    while not name:
        name = input("Nom du paquet (sans extension)> ").strip().lower()
        if not name:
            log_fn("[!] Le nom du paquet est obligatoire.")

    out_filename = name if name.endswith(output_ext) else name + output_ext
    all_files    = _collect_all(path_root, excludes)
    py_files     = [f for f in all_files if f.endswith(".py")]

    if not py_files:
        log_fn(f"[!] Aucun fichier .py dans '{path_root}' après exclusions.")
        if excludes:
            log_fn(f"[!] Exclusions actives : {excludes}")
        return

    total     = len(py_files)
    fp        = _fingerprint(n, log_fn)
    total_src = sum(os.path.getsize(f) for f in py_files if os.path.isfile(f))

    log_fn(f"\n{'═'*52}")
    log_fn(f"  RÉCAPITULATIF AVANT CHIFFREMENT")
    log_fn(f"{'─'*52}")
    log_fn(f"  Paquet cible   : {out_filename}")
    log_fn(f"  Source         : {path_root}")
    log_fn(f"  Fichiers .py   : {total}")
    log_fn(f"  Taille totale  : {total_src:,} octets")
    log_fn(f"  Clé (fp)       : {fp}  (RSA-{n.bit_length()})")
    if excludes:
        log_fn(f"  Exclusions     : {', '.join(excludes)}")
    if commandes:
        log_fn(f"  Commandes auto : {len(commandes)}")
        for cmd in commandes:
            log_fn(f"      › {cmd}")
    log_fn(f"{'═'*52}")

    confirm = input("\n  Confirmer le chiffrement ? [o/N] > ").strip().lower()
    if confirm not in ("o", "oui", "y", "yes"):
        log_fn("[*] Opération annulée — aucun fichier écrit.")
        return

    log_fn(f"\n[*] Démarrage du chiffrement RSA-{n.bit_length()} + AES-256-CBC via apix...\n")

    all_crypt = {}
    errors    = []

    for i, file in enumerate(py_files, 1):
        try:
            with open(file, 'rb') as f:
                content = f.read()

            blob = _encrypt(n, d, content, lambda *_: None)  # log silencieux

            parts = file.replace("\\", "/").split("/")
            fname = ("core." + parts[-1]) if (len(parts) >= 2 and parts[-2] == "core") else parts[-1]

            if fname in all_crypt:
                base, *ext = fname.rsplit(".", 1)
                suffix = ext[0] if ext else ""
                fname  = f"{base}_{i}.{suffix}" if suffix else f"{base}_{i}"

            ratio = len(blob) / len(content) if content else 0
            all_crypt[fname] = {
                "data":   blob.hex(),
                "size":   len(content),
                "source": file,
            }
            log_fn(
                f"  [{i:>3}/{total}]  ✓  {fname:<40}"
                f"  {len(content):>7} o → {len(blob):>7} o  (×{ratio:.1f})"
            )
        except Exception as ex:
            log_fn(f"  [{i:>3}/{total}]  ✗  {file}")
            log_fn(f"           └─ {ex}")
            errors.append((file, str(ex)))

    manifest = {
        "magic":       PACKET_MAGIC,
        "fingerprint": fp,
        "created_at":  time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source_root": path_root,
        "file_count":  len(all_crypt),
        "files":       all_crypt,
        "commandes":   commandes,
    }

    with open(out_filename, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    out_size  = os.path.getsize(out_filename)
    ok_count  = len(all_crypt)
    err_count = len(errors)

    log_fn(f"\n{'═'*52}")
    log_fn(f"  PAQUET GÉNÉRÉ  —  {out_filename}")
    log_fn(f"{'─'*52}")
    log_fn(f"  Format         : RCPKG1")
    log_fn(f"  Fingerprint    : {fp}")
    log_fn(f"  Créé le        : {manifest['created_at']}")
    log_fn(f"  Source         : {path_root}")
    log_fn(f"  Fichiers OK    : {ok_count}")
    if err_count:
        log_fn(f"  Fichiers KO    : {err_count}")
        for bad_file, reason in errors:
            log_fn(f"      ✗  {os.path.basename(bad_file)} : {reason}")
    else:
        log_fn("  Erreurs        : aucune ✓")
    if excludes:
        log_fn(f"  Exclusions     : {', '.join(excludes)}")
    log_fn(f"  Taille source  : {total_src:,} o")
    log_fn(f"  Taille paquet  : {out_size:,} o")
    if commandes:
        log_fn(f"{'─'*52}")
        log_fn("  Commandes embarquées :")
        for cmd in commandes:
            log_fn(f"      › {cmd}")
    log_fn(f"{'─'*52}")
    log_fn(f"  Installation :")
    log_fn(f"      r_eco> install {out_filename}")
    log_fn(f"{'═'*52}\n")


# ═══════════════════════════════════════════════════════════════
#  REPL reco_bldr
# ═══════════════════════════════════════════════════════════════

_HELP = """\
  keygen              génère une paire RSA aléatoire (via apix → rsa)
  set_key             dérive les clés depuis une passphrase (déterministe)
  status              fingerprint + bits + état clé privée
  export_pubkey       exporte pubkey.json (clé publique seule)
  load_pubkey [path]  charge une pubkey.json
  gen_default         génère le snippet R_ECO_DEFAULT_PUBKEY
  clear               efface les clés de la mémoire
  command             ajoute une commande auto-exécutée à l'install
  exclude [pattern]   ajoute/liste/retire des patterns d'exclusion (fnmatch)
  select              navigue dans le FS pour choisir un dossier source
  pack                chiffre la sélection → paquet RCPKG1
  list <paquet.reco>  liste le contenu d'un paquet sans déchiffrer
  verify <paquet>     vérifie l'intégrité du paquet (nécessite clé publique)
  quit                quitte"""


def R_ECO3(args, log_fn=print):
    import core

    # ── État de la session ──────────────────────────────────────
    n         = None
    e         = None
    d         = None
    path_root = None   # dossier source sélectionné
    commandes = []
    excludes  = []

    # ── Bannière ────────────────────────────────────────────────
    core.apix.R_ECO3("run banana banner", log_fn)
    core.apix.R_ECO3(
        'run banana panel'
        ' --msg="Builder de paquets [bold cyan]RCPKG1[/bold cyan]'
        '\nRSA+AES via [dim]apix → rsa[/dim]"'
        ' --title="reco_bldr"'
        ' --subtitle="R-ECO v1.5"'
        ' --border=cyan'
        ' --align=center'
        ' --box=ROUNDED',
        log_fn
    )
    log_fn("  Tape 'help' pour la liste des commandes.\n")

    # ── Boucle REPL ─────────────────────────────────────────────
    while True:
        try:
            cmd_raw = input("reco_bldr> ").strip()
        except (EOFError, KeyboardInterrupt):
            log_fn()
            break

        if not cmd_raw:
            continue

        parts = cmd_raw.split()
        verb  = parts[0].lower()

        # ── quit ────────────────────────────────────────────────
        if verb in ("q", "quit", "exit"):
            break

        # ── keygen ──────────────────────────────────────────────
        elif verb == "keygen":
            bits_in = input("Bits (défaut 4096)> ").strip()
            bits    = int(bits_in) if bits_in.isdigit() else RSA_BITS
            if n is not None:
                fp_cur = _fingerprint(n, log_fn) # type: ignore
                log_fn(f"[!] Clés déjà en mémoire (fp: {fp_cur}).")
                confirm = input("    Écraser ? [o/N] > ").strip().lower()
                if confirm not in ("o", "oui", "y", "yes"):
                    log_fn("[*] Keygen annulé.")
                    continue
            try:
                n, e, d = _keygen(bits, log_fn)
                log_fn("[*] Clés actives en mémoire.")
            except RuntimeError as ex:
                log_fn(f"[✗] {ex}")

        # ── set_key ─────────────────────────────────────────────
        elif verb == "set_key":
            passphrase = input("Passphrase> ").strip()
            if not passphrase:
                log_fn("[!] Passphrase vide — annulé.")
                continue
            bits_in = input("Bits (défaut 4096)> ").strip()
            bits    = int(bits_in) if bits_in.isdigit() else RSA_BITS
            if n is not None:
                fp_cur = _fingerprint(n, log_fn) # type: ignore
                log_fn(f"[!] Clés déjà en mémoire (fp: {fp_cur}).")
                confirm = input("    Écraser ? [o/N] > ").strip().lower()
                if confirm not in ("o", "oui", "y", "yes"):
                    log_fn("[*] set_key annulé.")
                    continue
            try:
                n, e, d = _set_key(passphrase, bits, log_fn)
                log_fn("[*] Clés actives en mémoire.")
                log_fn(f"[*] Dans _start : set_rsa_key {passphrase!r}  (ou clé DEFAULT)")
            except RuntimeError as ex:
                log_fn(f"[✗] {ex}")

        # ── status ──────────────────────────────────────────────
        elif verb == "status":
            if n is not None:
                fp = _fingerprint(n, log_fn) # type: ignore
                log_fn(f"[*] Fingerprint : {fp}  ({n.bit_length()} bits)") # type: ignore
                log_fn(f"[*] e (public)  : {e}")
                log_fn(f"[*] Clé privée  : {'présente' if d is not None else 'absente'}")
            else:
                log_fn("[*] Aucune clé en mémoire. Utilise 'keygen' ou 'set_key'.")
            log_fn(f"[*] Source      : {path_root or '(non sélectionnée)'}")
            log_fn(f"[*] Exclusions  : {excludes or '(aucune)'}")
            log_fn(f"[*] Commandes   : {len(commandes)}")

        # ── export_pubkey ───────────────────────────────────────
        elif verb == "export_pubkey":
            if n is None:
                log_fn("[!] Aucune clé en mémoire.")
            else:
                path = parts[1] if len(parts) > 1 else "pubkey.json"
                export_pubkey(n, e, path, log_fn) # type: ignore

        # ── load_pubkey ─────────────────────────────────────────
        elif verb == "load_pubkey":
            path = parts[1] if len(parts) > 1 else "pubkey.json"
            try:
                ln, le = load_pubkey(path, log_fn)
                log_fn(f"[*] n={hex(ln)[:20]}...  e={le}")
            except FileNotFoundError:
                log_fn(f"[✗] Fichier introuvable : '{path}'")
            except Exception as ex:
                log_fn(f"[✗] Échec : {ex}")

        # ── gen_default ─────────────────────────────────────────
        elif verb == "gen_default":
            if n is None:
                log_fn("[!] Aucune clé en mémoire.")
            else:
                pubkey_to_default_snippet(n, e, log_fn) # type: ignore

        # ── clear ───────────────────────────────────────────────
        elif verb == "clear":
            if n is None:
                log_fn("[*] Aucune clé en mémoire — rien à effacer.")
            else:
                fp = _fingerprint(n, log_fn) # type: ignore
                log_fn(f"[!] Clés actuelles : {fp}  ({n.bit_length()} bits)") # type: ignore
                confirm = input("    Effacer définitivement ? [o/N] > ").strip().lower()
                if confirm in ("o", "oui", "y", "yes"):
                    n = e = d = None
                    log_fn("[*] Clés effacées.")
                else:
                    log_fn("[*] Effacement annulé.")

        # ── select ──────────────────────────────────────────────
        elif verb == "select":
            start    = parts[1] if len(parts) > 1 else "."
            selected, _ = browse(start)
            if selected:
                path_root = selected
                filtered  = _collect_all(path_root, excludes)
                py_count  = sum(1 for f in filtered if f.endswith(".py"))
                log_fn(f"[*] Sélection : '{path_root}'")
                log_fn(f"[*] {py_count} fichier(s) .py  ({len(filtered)} au total)")
                if excludes:
                    log_fn(f"[*] Exclusions actives : {excludes}")
                if py_count == 0:
                    log_fn("[!] Aucun .py détecté — 'pack' ne trouvera rien à chiffrer.")
            else:
                log_fn("[*] Sélection annulée.")

        # ── exclude ─────────────────────────────────────────────
        elif verb == "exclude":
            if len(parts) == 1:
                if excludes:
                    log_fn(f"[*] Exclusions actives ({len(excludes)}) :")
                    for i, pat in enumerate(excludes):
                        log_fn(f"      [{i}]  {pat}")
                    log_fn("[*] 'exclude rm <n>'  |  'exclude clear'")
                else:
                    log_fn("[*] Aucune exclusion active.")
                    log_fn("[*] Usage : exclude <pattern>   ex: exclude __pycache__")
            elif len(parts) == 2 and parts[1].lower() == "clear":
                excludes = []
                log_fn("[*] Toutes les exclusions supprimées.")
            elif len(parts) == 3 and parts[1].lower() == "rm":
                idx_str = parts[2]
                if idx_str.isdigit() and 0 <= int(idx_str) < len(excludes):
                    removed = excludes.pop(int(idx_str))
                    log_fn(f"[*] Exclusion supprimée : '{removed}'")
                else:
                    log_fn(f"[!] Index invalide — plage : 0–{len(excludes)-1}")
            else:
                for pat in parts[1:]:
                    if pat not in excludes:
                        excludes.append(pat)
                        log_fn(f"[+] Exclusion ajoutée : '{pat}'")
                    else:
                        log_fn(f"[*] Pattern déjà présent : '{pat}'")
                log_fn(f"[*] Exclusions actives : {excludes}")

        # ── pack ────────────────────────────────────────────────
        elif verb == "pack":
            if n is None:
                log_fn("[!] Aucune clé — utilise 'keygen' ou 'set_key'.")
            elif d is None:
                log_fn("[!] Clé privée absente — impossible de chiffrer.")
            elif not path_root:
                log_fn("[!] Aucun dossier sélectionné — utilise 'select'.")
            else:
                pack(path_root, n, e, d, ".reco", commandes, excludes, log_fn) # type: ignore

        # ── command ─────────────────────────────────────────────
        elif verb == "command":
            new_cmd = input("reco_bldr: commande> ").strip()
            if new_cmd:
                commandes.append(new_cmd)
                log_fn(f"[*] Commande ajoutée ({len(commandes)}) : {new_cmd!r}")

        # ── list ────────────────────────────────────────────────
        elif verb == "list":
            if len(parts) < 2:
                log_fn("[!] Usage : list <paquet.reco>")
            else:
                list_package(parts[1])

        # ── verify ──────────────────────────────────────────────
        elif verb == "verify":
            if len(parts) < 2:
                log_fn("[!] Usage : verify <paquet.reco>")
            elif n is None:
                log_fn("[!] Aucune clé — charge une pubkey avec 'load_pubkey'.")
            else:
                verify_package(parts[1], n, e, log_fn) # type: ignore

        # ── help ────────────────────────────────────────────────
        elif verb in ("help", "?", "h"):
            log_fn(_HELP)

        # ── commande inconnue ────────────────────────────────────
        else:
            log_fn(f"[?] Commande inconnue : '{cmd_raw}'. Tape 'help'.")

    return 0, (0, None)

def R_ECO3dep():
    return (("3.5.1b",), (
        ("rsa",    ("1.0",)),
        ("banana", ("1.1",)),
    ),)


def R_ECO3inf():
    return {
        "name":        "reco_bldr",
        "desc":        "Interactive builder for RSA+AES encrypted RCPKG1 packages",
        "help":        "REPL tool to generate RSA key pairs, select a source directory, encrypt Python files into a .reco package, and verify or inspect existing packages. All crypto operations go through core.apix → rsa.",
        "version_mod": "1.5",
        "L2Module":    True,
        "manual": (
            "reco_bldr\n\n"
            "AVAILABLE COMMANDS & ARGUMENTS:\n"
            "  reco_bldr\n"
            "    Launches the interactive RCPKG1 builder REPL.\n"
            "    Takes no arguments.\n"
            "    Type 'help' inside the REPL for the full command reference.\n"
        )
    }