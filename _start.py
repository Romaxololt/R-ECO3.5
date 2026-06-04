import json
import base64
import time
import importlib.util
import sys
import math
import struct
import hashlib
import os
from pathlib import Path
import readline

VERSION  = "3.5.1b"
CODENAME = "Ant"

R_ECO_DEFAULT_PUBKEY = {
    "magic":       "RCPUB1",
    "fingerprint": "28188c600caba327",
    "bits":        4096,
    "n":           "0x8a6981600838ba7b0807d54c10e387651fb1b892a25d61b0d10455b51fa2f2cd758f3bbdf9df867331eb7934509ffd006e0e08ef7c03212f5081df26a36ea5d063419a58474b4598586a874b691e3b8ca442fdea0f02a9a2697aae03b2dfa40cc016b0cd138f2db19e8523603ad10b38ff3150529c93c37524ff556f03bb87a88181fb0c533e4a8b6be7fcc1cdeb041bfd568d0b520a9b037e60b905364921f8aa0de2dd3f47a89252da00a704dfbcddee63f200792ca30eb73d3fead5ce8e97725c7d192e5538c3435bb8c59751cd86379fdb82838b3813fabc4785dfc07413f05ee7632389500a5e7e826d9d76ba2f1cb0086aaadccc896f1ee7e2154ccdc5b64e7fb2f17e6850789e7b8959866832984644d1c94db362e564136924b9761bf46728a8ad45c7936b8a6b7d9576aa039900de7dc0aef943a40e90420a99d610402934111ae325a0398fa8b744a9c7d7cce122e257011a9f9165273a72be67700c4cab837ae4e6a837a5f9ca44985a00c95ad2dce6ee45a67d3fbfca89118c3f7c57ebe142096ccec3cbbc098c6681146f36b467e078f463b11cde26c4ca8f95d94022cf97321a69b43c65dca78a4dc831ca1b66d489dfa19fae074109fadf9a567c1f1b698d43ccad3566471a6a72b21ba65f442df1e2acad26fbb9e8b6fb43bbe7c09a3153e23e7742bb4dff2796676b06ccabaea643503de5ab64b24ebd9f",
    "e":           65537,
}


# ══════════════════════════════════════════════════════════════════════════════
#  Error codes
# ══════════════════════════════════════════════════════════════════════════════

ERRNO = {
    "E001": "Data file not found",
    "E002": "Data file is not valid JSON",
    "E003": "Data file is not a key/value mapping",
    "E004": "Decryption key must not be empty",
    "E007": "Failed to write module to disk",
    "E008": "Cannot load hive module (hive.py missing or invalid)",
    "E009": "Database integrity check failed",
    "E010": "Metadata module could not be loaded",
    "E011": "Invalid 'set' syntax  —  usage: set <key> <value>",
    "E012": "Failed to write config file",
    "E013": "Module path resolution failed",
    "E014": "Unknown inline command in .reco entry",
    "E015": "Command not allowed in .reco context",
    "E016": "Key not found in database",
    "E017": "Invalid 'get' syntax  —  usage: get <key>",
    "E018": "Invalid 'del' syntax  —  usage: del <key>",
    "E019": "Uninstall failed — data.reco not found or unreadable",
    "E020": "Apix module could not be loaded",
    "E021": "Invalid 'run' syntax  —  usage: run <module> [args]",
    "E022": "RCPKG1 packet: RSA crypto unavailable (internal error)",
    "E023": "RCPKG1 packet: no RSA key available (set_rsa_key or configure DEFAULT)",
    "E024": "RCPKG1 packet: decryption failed for entry",
    "E025": "RCPKG1 packet: fingerprint mismatch (wrong key?)",
    "E026": "Unknown packet format (expected RCPKG1)",
    "E027": "Invalid pubkey file (expected RCPUB1 format)",
    "E028": "Post-install command failed",
}


def _err(code: str, detail: str = "") -> str:
    label = ERRNO.get(code, "Unknown error")
    return f"[{code}] {label}" + (f": {detail}" if detail else "")

# ══════════════════════════════════════════════════════════════════════════════
#  Display helpers
# ══════════════════════════════════════════════════════════════════════════════

_W = 62

def _box_top(title: str = ""):
    if title:
        pad   = _W - len(title) - 4
        left  = pad // 2
        right = pad - left
        print(f"┌{'─' * (left + 1)} {title} {'─' * (right + 1)}┐")
    else:
        print(f"┌{'─' * _W}┐")

def _box_row(text: str = "", indent: int = 2):
    line = " " * indent + text
    pad  = _W - len(line)
    print(f"│{line}{' ' * max(pad, 0)}│")

def _box_bot():
    print(f"└{'─' * _W}┘")

def _ok(msg: str):   print(f"  ✔  {msg}")
def _warn(msg: str): print(f"  ⚠  {msg}")
def _fail(code: str, detail: str = ""):
    print(f"  ✖  {_err(code, detail)}")

def _animated_dots(label: str = "Configuring", steps: int = 3, delay: float = 0.4):
    print(f"  ·  {label}", end="", flush=True)
    for _ in range(steps):
        time.sleep(delay)
        print(".", end="", flush=True)
    print("  done", flush=True)


def _banner(default_fp: str | None):
    _box_top("R  E C O S Y S T E M")
    _box_row()
    _box_row("Bootstrap initialisation utility")
    _box_row(f"Version {VERSION}  —  {CODENAME}")
    _box_row()
    if default_fp:
        _box_row(f"Default key : {default_fp}  ✔")
    else:
        _box_row("Default key : none  (use set_rsa_key for RCPKG1)")
    _box_row()
    _box_row("Commands:")
    _box_row("  install [<file>]           install a reco packet")
    _box_row("  uninstall                  remove all deployed modules")
    _box_row("  set_rsa_key <pp> [bits]    derive & load RSA pub key")
    _box_row("  load_pubkey [<file>]       load pubkey.json into session")
    _box_row("  rsa_status                 show active RSA key info")
    _box_row("  run <module> [args]        launch a module via apix")
    _box_row("  set   <key> <value>        write to DB")
    _box_row("  get   <key>                read from DB")
    _box_row("  del   <key>                delete from DB")
    _box_row("  list_keys                  list all DB keys")
    _box_row("  quit / exit                leave")
    _box_row()
    _box_bot()
    print()

# ─── Constantes ───────────────────────────────────────────────────────────────
_HEADER_MAGIC    = b"RCRYPT1"
_HASH_LEN        = 32        # SHA-256
_AES_KEY_LEN     = 32        # AES-256
_AES_BLOCK       = 16
_RSA_BITS        = 4096
_PBKDF2_ITER     = 100_000
_PBKDF2_SALT_PFX = b"RomaCrypt-setkey-v1-"

# ─── RSA arithmetic ───────────────────────────────────────────────────────────

def _mod_pow(base: int, exp: int, mod: int) -> int:
    result = 1
    base %= mod
    while exp > 0:
        if exp & 1:
            result = result * base % mod
        base = base * base % mod
        exp >>= 1
    return result

def _extended_gcd(a: int, b: int):
    if a == 0:
        return b, 0, 1
    g, x, y = _extended_gcd(b % a, a)
    return g, y - (b // a) * x, x

def _mod_inverse(a: int, m: int) -> int:
    g, x, _ = _extended_gcd(a % m, m)
    if g != 1:
        raise ValueError("Pas d'inverse modulaire")
    return x % m

def _miller_rabin(n: int, rounds: int = 20) -> bool:
    if n < 2:      return False
    if n == 2:     return True
    if n == 3:     return True
    if n % 2 == 0: return False
    r, d = 0, n - 1
    while d % 2 == 0:
        r += 1
        d //= 2
    deterministic = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37]
    witnesses = [a for a in deterministic if a < n]
    for _ in range(rounds):
        witnesses.append(int.from_bytes(os.urandom(8), 'big') % (n - 3) + 2)
    for a in witnesses:
        x = _mod_pow(a, d, n)
        if x == 1 or x == n - 1:
            continue
        for _ in range(r - 1):
            x = x * x % n
            if x == n - 1:
                break
        else:
            return False
    return True

# ─── set_key — dérivation déterministe RSA depuis passphrase ──────────────────

def _derive_seed(passphrase: str, bits: int) -> bytes:
    salt = _PBKDF2_SALT_PFX + str(bits).encode()
    return hashlib.pbkdf2_hmac('sha256', passphrase.encode('utf-8'),
                               salt, _PBKDF2_ITER, dklen=64)

def _make_det_rng(seed: bytes):
    counter = [0]
    buf     = [b""]
    def read(n: int) -> bytes:
        out = b""
        while len(out) < n:
            if not buf[0]:
                h      = hashlib.shake_256(seed + counter[0].to_bytes(8, 'big'))
                buf[0] = h.digest(64)
                counter[0] += 1
            take    = min(n - len(out), len(buf[0]))
            out    += buf[0][:take]
            buf[0]  = buf[0][take:]
        return out
    return read

def _det_random_prime(rng_read, bits: int) -> int:
    half = bits // 8
    while True:
        raw       = rng_read(half)
        candidate = int.from_bytes(raw, 'big')
        candidate |= (1 << (bits - 1))
        candidate |= 1
        if _miller_rabin(candidate):
            return candidate

def _set_key(passphrase: str, bits: int = _RSA_BITS):
    """Dérive (n, e, d) de façon déterministe depuis une passphrase."""
    print(f"[*] Dérivation PBKDF2-SHA256 ({_PBKDF2_ITER:,} itérations)...")
    seed = _derive_seed(passphrase, bits)
    print(f"[*] Expansion RSA-{bits} procédurale en cours...")
    rng  = _make_det_rng(seed)
    e    = 65537
    half = bits // 2
    attempt = 0
    while True:
        attempt += 1
        p   = _det_random_prime(rng, half)
        q   = _det_random_prime(rng, half)
        if p == q:
            continue
        n   = p * q
        phi = (p - 1) * (q - 1)
        if math.gcd(e, phi) == 1:
            d = _mod_inverse(e, phi)
            break
    fp = _make_fingerprint(n)
    print(f"[+] Clés dérivées en {attempt} tentative(s).  RSA-{bits}")
    print(f"[+] Fingerprint : {fp}")
    return n, e, d

# ─── OAEP ─────────────────────────────────────────────────────────────────────

def _mgf1(seed: bytes, length: int) -> bytes:
    out     = b""
    counter = 0
    while len(out) < length:
        c    = struct.pack(">I", counter)
        out += hashlib.sha256(seed + c).digest()
        counter += 1
    return out[:length]

def _oaep_decode(em: bytes, k: int, label: bytes = b"RomaCrypt") -> bytes:
    hLen = _HASH_LEN
    if len(em) != k:
        raise ValueError("Longueur EM incorrecte")
    if em[0] != 0:
        raise ValueError("Premier octet EM invalide")
    maskedSeed = em[1 : 1 + hLen]
    maskedDB   = em[1 + hLen:]
    seedMask   = _mgf1(maskedDB, hLen)
    seed       = bytes(a ^ b for a, b in zip(maskedSeed, seedMask))
    dbMask     = _mgf1(seed, k - hLen - 1)
    DB         = bytes(a ^ b for a, b in zip(maskedDB, dbMask))
    lHash_expected = hashlib.sha256(label).digest()
    lHash_actual   = DB[:hLen]
    if lHash_actual != lHash_expected:
        raise ValueError("Échec vérification label OAEP (données corrompues ou mauvaise clé)")
    rest = DB[hLen:]
    idx  = rest.index(b"\x01")
    return rest[idx + 1:]

# ─── AES-256-CBC (stdlib seulement) ───────────────────────────────────────────

_SBOX = [
    0x63,0x7c,0x77,0x7b,0xf2,0x6b,0x6f,0xc5,0x30,0x01,0x67,0x2b,0xfe,0xd7,0xab,0x76,
    0xca,0x82,0xc9,0x7d,0xfa,0x59,0x47,0xf0,0xad,0xd4,0xa2,0xaf,0x9c,0xa4,0x72,0xc0,
    0xb7,0xfd,0x93,0x26,0x36,0x3f,0xf7,0xcc,0x34,0xa5,0xe5,0xf1,0x71,0xd8,0x31,0x15,
    0x04,0xc7,0x23,0xc3,0x18,0x96,0x05,0x9a,0x07,0x12,0x80,0xe2,0xeb,0x27,0xb2,0x75,
    0x09,0x83,0x2c,0x1a,0x1b,0x6e,0x5a,0xa0,0x52,0x3b,0xd6,0xb3,0x29,0xe3,0x2f,0x84,
    0x53,0xd1,0x00,0xed,0x20,0xfc,0xb1,0x5b,0x6a,0xcb,0xbe,0x39,0x4a,0x4c,0x58,0xcf,
    0xd0,0xef,0xaa,0xfb,0x43,0x4d,0x33,0x85,0x45,0xf9,0x02,0x7f,0x50,0x3c,0x9f,0xa8,
    0x51,0xa3,0x40,0x8f,0x92,0x9d,0x38,0xf5,0xbc,0xb6,0xda,0x21,0x10,0xff,0xf3,0xd2,
    0xcd,0x0c,0x13,0xec,0x5f,0x97,0x44,0x17,0xc4,0xa7,0x7e,0x3d,0x64,0x5d,0x19,0x73,
    0x60,0x81,0x4f,0xdc,0x22,0x2a,0x90,0x88,0x46,0xee,0xb8,0x14,0xde,0x5e,0x0b,0xdb,
    0xe0,0x32,0x3a,0x0a,0x49,0x06,0x24,0x5c,0xc2,0xd3,0xac,0x62,0x91,0x95,0xe4,0x79,
    0xe7,0xc8,0x37,0x6d,0x8d,0xd5,0x4e,0xa9,0x6c,0x56,0xf4,0xea,0x65,0x7a,0xae,0x08,
    0xba,0x78,0x25,0x2e,0x1c,0xa6,0xb4,0xc6,0xe8,0xdd,0x74,0x1f,0x4b,0xbd,0x8b,0x8a,
    0x70,0x3e,0xb5,0x66,0x48,0x03,0xf6,0x0e,0x61,0x35,0x57,0xb9,0x86,0xc1,0x1d,0x9e,
    0xe1,0xf8,0x98,0x11,0x69,0xd9,0x8e,0x94,0x9b,0x1e,0x87,0xe9,0xce,0x55,0x28,0xdf,
    0x8c,0xa1,0x89,0x0d,0xbf,0xe6,0x42,0x68,0x41,0x99,0x2d,0x0f,0xb0,0x54,0xbb,0x16,
]

_INV_SBOX = [0] * 256
for _i, _v in enumerate(_SBOX):
    _INV_SBOX[_v] = _i

_RCON = [0x01,0x02,0x04,0x08,0x10,0x20,0x40,0x80,0x1b,0x36,
         0x6c,0xd8,0xab,0x4d,0x9a,0x2f,0x5e,0xbc,0x63,0xc6,
         0x97,0x35,0x6a,0xd4,0xb3,0x7d,0xfa,0xef,0xc5,0x91]

def _gmul(a, b):
    p = 0
    for _ in range(8):
        if b & 1: p ^= a
        hi = a & 0x80
        a  = (a << 1) & 0xff
        if hi: a ^= 0x1b
        b >>= 1
    return p

def _key_expansion(key: bytes):
    Nk = len(key) // 4
    Nr = Nk + 6
    w  = [list(key[4*i:4*i+4]) for i in range(Nk)]
    for i in range(Nk, 4*(Nr+1)):
        temp = list(w[i-1])
        if i % Nk == 0:
            temp    = temp[1:] + temp[:1]
            temp    = [_SBOX[b] for b in temp]
            temp[0] ^= _RCON[(i // Nk) - 1]
        elif Nk > 6 and i % Nk == 4:
            temp = [_SBOX[b] for b in temp]
        w.append([a ^ b for a, b in zip(w[i-Nk], temp)])
    return w, Nr

def _add_round_key(state, rk):
    for r in range(4):
        for c in range(4):
            state[r][c] ^= rk[c][r]

def _inv_sub_bytes(state):
    for r in range(4):
        for c in range(4):
            state[r][c] = _INV_SBOX[state[r][c]]

def _inv_shift_rows(state):
    for r in range(1, 4):
        state[r] = state[r][-r:] + state[r][:-r]

def _inv_mix_columns(state):
    for c in range(4):
        s = [state[r][c] for r in range(4)]
        state[0][c] = _gmul(s[0],0x0e)^_gmul(s[1],0x0b)^_gmul(s[2],0x0d)^_gmul(s[3],0x09)
        state[1][c] = _gmul(s[0],0x09)^_gmul(s[1],0x0e)^_gmul(s[2],0x0b)^_gmul(s[3],0x0d)
        state[2][c] = _gmul(s[0],0x0d)^_gmul(s[1],0x09)^_gmul(s[2],0x0e)^_gmul(s[3],0x0b)
        state[3][c] = _gmul(s[0],0x0b)^_gmul(s[1],0x0d)^_gmul(s[2],0x09)^_gmul(s[3],0x0e)

def _aes_block_decrypt(block: bytes, w, Nr: int) -> bytes:
    state = [[block[r + 4*c] for c in range(4)] for r in range(4)]
    _add_round_key(state, w[4*Nr:4*Nr+4])
    for rnd in range(Nr-1, 0, -1):
        _inv_shift_rows(state)
        _inv_sub_bytes(state)
        _add_round_key(state, w[4*rnd:4*rnd+4])
        _inv_mix_columns(state)
    _inv_shift_rows(state)
    _inv_sub_bytes(state)
    _add_round_key(state, w[:4])
    return bytes(state[r][c] for c in range(4) for r in range(4))

def _aes_cbc_decrypt(key: bytes, iv: bytes, ciphertext: bytes) -> bytes:
    w, Nr    = _key_expansion(key)
    pt, prev = b"", iv
    for i in range(0, len(ciphertext), _AES_BLOCK):
        blk  = ciphertext[i:i+_AES_BLOCK]
        dec  = _aes_block_decrypt(blk, w, Nr)
        pt  += bytes(a ^ b for a, b in zip(dec, prev))
        prev = blk
    pad = pt[-1]
    if not (1 <= pad <= _AES_BLOCK) or pt[-pad:] != bytes([pad]*pad):
        raise ValueError("Padding PKCS#7 invalide — données corrompues ou clé incorrecte")
    return pt[:-pad]

# ─── Déchiffrement hybride RSA-OAEP + AES-CBC ─────────────────────────────────

def _const_eq(a: bytes, b: bytes) -> bool:
    if len(a) != len(b):
        return False
    result = 0
    for x, y in zip(a, b):
        result |= x ^ y
    return result == 0

def _rsa_oaep_decrypt_key(ciphertext: bytes, n: int, e: int) -> bytes:
    k  = (n.bit_length() + 7) // 8
    c  = int.from_bytes(ciphertext, 'big')
    m  = _mod_pow(c, e, n)
    em = m.to_bytes(k, 'big')
    return _oaep_decode(em, k)

def _decrypt_message(blob: bytes, n: int, e: int) -> bytes:
    """Déchiffrement avec clé publique (n, e) — équivalent de romacrypt.decrypt_message."""
    if not blob.startswith(_HEADER_MAGIC):
        raise ValueError(
            "Magic RCRYPT1 absent en tête de blob — "
            "fichier tronqué, corrompu, ou pas un paquet RomaCrypt"
        )
    pos = len(_HEADER_MAGIC)

    k        = struct.unpack(">I", blob[pos:pos+4])[0]; pos += 4
    enc_key  = blob[pos:pos+k];                          pos += k
    iv       = blob[pos:pos+_AES_BLOCK];                 pos += _AES_BLOCK
    hmac_val = blob[pos:pos+_HASH_LEN];                  pos += _HASH_LEN
    ct       = blob[pos:]

    aes_key  = _rsa_oaep_decrypt_key(enc_key, n, e)

    hmac_key = hashlib.sha256(aes_key + b"hmac").digest()
    expected = hashlib.sha256(hmac_key + enc_key + iv + ct).digest()
    if not _const_eq(hmac_val, expected):
        raise ValueError(
            "HMAC invalide — les données ont été altérées en transit "
            "ou la clé publique ne correspond pas à la clé privée utilisée pour chiffrer"
        )

    return _aes_cbc_decrypt(aes_key, iv, ct)

def make_fingerprint(n: int) -> str:
    nb = n.to_bytes((n.bit_length() + 7) // 8, 'big')
    return hashlib.sha256(nb).hexdigest()[:16]

# Alias interne (utilisé partout dans ce fichier)
_make_fingerprint = make_fingerprint


def _load_default_pubkey() -> tuple[int | None, int | None, str | None]:
    if R_ECO_DEFAULT_PUBKEY is None:
        return None, None, None
    try:
        data = R_ECO_DEFAULT_PUBKEY
        if data.get("magic") != "RCPUB1":
            return None, None, None
        n  = int(data["n"], 16)
        e  = int(data["e"])
        fp = data.get("fingerprint", "?")
        return n, e, fp
    except Exception:
        return None, None, None


def _load_pubkey_from_file(path: str) -> tuple[int, int, str]:
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if data.get("magic") != "RCPUB1":
        raise ValueError(_err("E027", f"magic={data.get('magic')!r}"))
    try:
        n  = int(data["n"], 16)
        e  = int(data["e"])
        fp = data.get("fingerprint", "?")
        return n, e, fp
    except (KeyError, ValueError) as exc:
        raise ValueError(_err("E027", str(exc))) from exc

def extract_metadata(module_path: Path) -> tuple[str, str]:
    if not module_path.exists():
        return "Unknown", "Unknown"
    spec = importlib.util.spec_from_file_location("_dynamic_meta", str(module_path))
    if not spec or not spec.loader:
        return "Unknown", "Unknown"
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception:
        return "Unknown", "Unknown"
    return getattr(module, "VERSION", "Unknown"), getattr(module, "CODENAME", "Unknown")

def _resolve_module_path(root: Path, module_name: str) -> Path | None:
    try:
        if module_name.startswith("core."):
            return root / "core" / module_name[len("core."):]
        return root / "modules" / module_name
    except Exception as exc:
        _fail("E013", str(exc))
        return None


def _load_flatKV(current_dir: Path):
    hive_path = current_dir / "core" / "hive.py"
    if not hive_path.exists():
        raise RuntimeError(_err("E008", f"'{hive_path}' not found"))
    spec = importlib.util.spec_from_file_location("core.hive", str(hive_path))
    if not spec or not spec.loader:
        raise RuntimeError(_err("E008", "importlib could not build a spec"))
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise RuntimeError(_err("E008", str(exc))) from exc
    if not hasattr(module, "HiveFS"):
        raise RuntimeError(_err("E008", "'HiveFS' missing from hive.py"))
    return module.HiveFS


def _open_db(current_dir: Path):
    FlatKV  = _load_flatKV(current_dir)
    db_path = current_dir / "data" / "data.hive"
    if not db_path.exists():
        raise RuntimeError(_err("E001", str(db_path)))
    return FlatKV(str(db_path))

_RECO_FORBIDDEN = {"install", "uninstall", "quit", "exit"}
_HELP_REPL = ("install [<file>]  |  uninstall  |  set_rsa_key  |  load_pubkey  |  "
              "rsa_status  |  run  |  set  |  get  |  del  |  list_keys  |  quit")
_HELP_RECO = "run  |  set  |  get  |  del  |  list_keys"


def _cmd_set(current_dir: Path, raw_cmd: str, *, prefix: str = "") -> bool:
    parts = raw_cmd.split(maxsplit=2)
    if len(parts) < 3:
        _fail("E011"); print(f"{prefix}       Usage:  set <key> <value>"); return False

    key, value = parts[1], parts[2]

    if key == "_start":
        cfg_path = current_dir / "R_ECO.cfg"
        try:
            existing = {}
            if cfg_path.exists():
                try:
                    with cfg_path.open("r", encoding="utf-8") as fh:
                        existing = json.load(fh)
                except Exception:
                    pass
            existing["_start"] = value
            with cfg_path.open("w", encoding="utf-8") as fh:
                json.dump(existing, fh, indent=2)
            print(f"{prefix}  ✔  config._start = {value!r}  →  '{cfg_path}'")
        except OSError as exc:
            _fail("E012", str(exc)); return False
        return True

    try:
        db = _open_db(current_dir)
    except RuntimeError as exc:
        _fail("E008", str(exc)); return False
    db.set(key, value)
    print(f"{prefix}  ✔  db.set  {key!r}  =  {value!r}")
    return True


def _cmd_get(current_dir: Path, raw_cmd: str, *, prefix: str = "") -> bool:
    parts = raw_cmd.split(maxsplit=1)
    if len(parts) < 2:
        _fail("E017"); print(f"{prefix}       Usage:  get <key>"); return False

    key = parts[1].strip()

    if key == "_start":
        cfg_path = current_dir / "R_ECO.cfg"
        if cfg_path.exists():
            try:
                with cfg_path.open("r", encoding="utf-8") as fh:
                    cfg = json.load(fh)
                print(f"{prefix}  ✔  '_start'  =  {cfg.get('_start', '<not set>')!r}  [config]")
                return True
            except Exception as exc:
                _warn(f"Could not read R_ECO.cfg: {exc}")
        else:
            print(f"{prefix}  ·  '_start'  not set  (R_ECO.cfg absent)")
        return True

    try:
        db = _open_db(current_dir)
    except RuntimeError as exc:
        _fail("E008", str(exc)); return False
    if not db.exists(key):
        print(f"{prefix}  ✖  {_err('E016', repr(key))}"); return False

    value     = db.get(key)
    type_name = type(value).__name__
    display   = (value[:64].hex() + f"…  ({len(value)} bytes)"
                 if isinstance(value, bytes) and len(value) > 64 else repr(value))
    print(f"{prefix}  ✔  {key!r}  =  {display}  [{type_name}]")
    return True


def _cmd_del(current_dir: Path, raw_cmd: str, *, prefix: str = "") -> bool:
    parts = raw_cmd.split(maxsplit=1)
    if len(parts) < 2:
        _fail("E018"); print(f"{prefix}       Usage:  del <key>"); return False
    key = parts[1].strip()
    try:
        db = _open_db(current_dir)
    except RuntimeError as exc:
        _fail("E008", str(exc)); return False
    if not db.delete(key):
        print(f"{prefix}  ✖  {_err('E016', repr(key))}"); return False
    print(f"{prefix}  ✔  deleted  {key!r}")
    return True


def _cmd_list_keys(current_dir: Path, *, prefix: str = "") -> bool:
    try:
        db = _open_db(current_dir)
    except RuntimeError as exc:
        _fail("E008", str(exc)); return False
    keys = db.list()
    if not keys:
        print(f"{prefix}  ·  Database is empty."); return True
    st = db.stats()
    print(f"{prefix}  ·  {len(keys)} key(s)  (live: {st['live_size']} B, "
          f"garbage: {st['garbage_ratio']:.0%})\n")
    for i, key in enumerate(keys, 1):
        key_hash = next((h for h, k in db.key_map.items() if k == key), None)
        entry    = db.index.get(key_hash) if key_hash else None
        if entry:
            ts   = time.strftime("%Y-%m-%d %H:%M:%S",
                                 time.localtime(entry.timestamp // 1_000_000))
            comp = "  [z]" if entry.flags & 0x02 else ""
            print(f"{prefix}  {i:>4}.  key={key!r}  size={entry.size:>6} B  ts={ts}{comp}")
        else:
            print(f"{prefix}  {i:>4}.  key={key!r}")
    return True

def _install_rcpkg1(current_dir: Path, data: dict,
                    rsa_n: int | None, rsa_e: int | None) -> tuple[int, list]:
    if rsa_n is None or rsa_e is None:
        _fail("E023")
        print("     → Utilisez 'set_rsa_key <passphrase>' ou 'load_pubkey <fichier>'")
        return 0, list(data.get("files", {}).keys())

    session_fp = _make_fingerprint(rsa_n)
    packet_fp  = data.get("fingerprint", "")

    if packet_fp and packet_fp != session_fp:
        _warn(f"Fingerprint mismatch !")
        _warn(f"  Paquet  : {packet_fp}")
        _warn(f"  Session : {session_fp}")
        _warn("Déchiffrement probable en échec — vérifiez la passphrase.")

    files = data.get("files", {})
    total = len(files)

    print(f"  Format         :  RCPKG1 (RSA+AES / romacrypt)")
    print(f"  Fingerprint    :  {packet_fp or '—'}")
    print(f"  Created at     :  {data.get('created_at', '—')}")
    print(f"  Source root    :  {data.get('source_root', '—')}")
    print(f"  Entries found  :  {total} module(s)")

    commandes = data.get("commandes", [])
    if commandes:
        print(f"  Post-install   :  {len(commandes)} commande(s)")
    print()

    mod_ok, mod_fail = 0, []

    for idx, (fname, meta) in enumerate(files.items(), 1):
        prefix    = f"  [{idx:>2}/{total}]"
        file_path = _resolve_module_path(current_dir, fname)
        if file_path is None:
            mod_fail.append(fname); continue

        hex_data = meta.get("data", "") if isinstance(meta, dict) else str(meta)

        try:
            blob      = bytes.fromhex(hex_data)
            plaintext = _decrypt_message(blob, rsa_n, rsa_e)
        except Exception as exc:
            print(f"{prefix}  ✖  {fname}  —  {_err('E024', str(exc))}")
            mod_fail.append(fname); continue

        file_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            file_path.write_bytes(plaintext)
        except OSError as exc:
            print(f"{prefix}  ✖  {fname}  —  {_err('E007', str(exc))}")
            mod_fail.append(fname); continue

        size_orig = meta.get("size", len(plaintext)) if isinstance(meta, dict) else len(plaintext)
        print(f"{prefix}  ✔  {fname}  ({size_orig} o)")
        mod_ok += 1
        time.sleep(0.05)

    return mod_ok, mod_fail

def _run_post_install_commands(current_dir: Path, commandes: list) -> tuple[int, list]:
    if not commandes:
        return 0, []

    total    = len(commandes)
    cmd_ok   = 0
    cmd_fail = []

    print(f"\n  ── Post-install : {total} commande(s) ──\n")

    for idx, raw_cmd in enumerate(commandes, 1):
        raw_cmd = raw_cmd.strip()
        if not raw_cmd:
            continue
        prefix = f"  [{idx:>2}/{total}]"
        print(f"{prefix}  »  {raw_cmd!r}")

        ok = _dispatch(current_dir, raw_cmd, prefix=prefix + "      ", from_reco=True)
        if ok:
            cmd_ok += 1
        else:
            _fail("E028", raw_cmd)
            cmd_fail.append(raw_cmd)

    return cmd_ok, cmd_fail

def _cmd_install(current_dir: Path,
                 packet_path: Path | None = None,
                 rsa_n: int | None = None,
                 rsa_e: int | None = None):
    _box_top("INSTALL")
    _box_row(f"Target : {current_dir}")
    if packet_path:
        _box_row(f"Packet : {packet_path.name}")
    _box_bot()
    print()

    if packet_path is None:
        packet_path = current_dir / "data.reco"
    if not packet_path.exists():
        _fail("E001", str(packet_path)); return

    try:
        with packet_path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        _fail("E002", str(exc)); return

    if not isinstance(data, dict):
        _fail("E003"); return

    if data.get("magic") != "RCPKG1":
        _fail("E026", f"magic={data.get('magic')!r}, attendu 'RCPKG1'")
        print("     → _start ne supporte que les paquets RCPKG1.")
        print("     → Utilisez reco_bldr pour générer un paquet au bon format.")
        return

    mod_ok, mod_fail = _install_rcpkg1(current_dir, data, rsa_n, rsa_e)
    n_mods = len(data.get("files", {}))

    print()
    print(f"  Modules   :  {mod_ok}/{n_mods} installed"
          + (f"  ({len(mod_fail)} failed)" if mod_fail else ""))
    if mod_fail:
        print()
        for name in mod_fail: print(f"    ✖ module   {name}")
    print()

    root_str = str(current_dir)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
        _ok(f"Added '{root_str}' to sys.path")

    _animated_dots("Configuring")
    print()

    try:
        FlatKV = _load_flatKV(current_dir)
    except RuntimeError as exc:
        _fail("E008", str(exc)); return

    db_path = current_dir / "data" / "data.hive"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = FlatKV(str(db_path))

    db["version"] = "1.0"
    if db["version"] != "1.0":
        _fail("E009"); sys.exit(1)

    db.set("reco_magic",    "R_ECO3")
    db.set("reco_version",  VERSION)
    db.set("reco_codename", CODENAME)
    db.set("packet_format", "rcpkg1")
    _ok("Database initialised")

    commandes = data.get("commandes", [])
    cmd_ok, cmd_fail = _run_post_install_commands(current_dir, commandes)

    if commandes:
        print()
        print(f"  Commands  :  {cmd_ok}/{len(commandes)} executed"
              + (f"  ({len(cmd_fail)} failed)" if cmd_fail else ""))
        if cmd_fail:
            print()
            for name in cmd_fail: print(f"    ✖ command  {name!r}")

    print()
    _box_top("INSTALL COMPLETE")
    _box_row(f"Version   : {VERSION}  —  {CODENAME}")
    _box_row(f"Format    : RCPKG1")
    _box_row(f"Modules   : {mod_ok}/{n_mods}")
    if commandes:
        _box_row(f"Commands  : {cmd_ok}/{len(commandes)}")
    _box_row(f"DB path   : {db_path}")
    _box_bot()
    print()


def _cmd_run(current_dir: Path, raw_cmd: str, *, prefix: str = "") -> bool:
    parts = raw_cmd.split(maxsplit=2)
    if len(parts) < 2:
        _fail("E021"); print(f"{prefix}       Usage:  run <module> [args]"); return False
    module, run_args = parts[1], (parts[2] if len(parts) > 2 else "")
    try:
        apix = _load_apix(current_dir)
    except RuntimeError as exc:
        _fail("E020", str(exc)); return False
    root_str = str(current_dir)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    print(f"{prefix}  »  apix → run {module!r}" + (f"  args={run_args!r}" if run_args else ""))
    status, result = apix.R_ECO3(f"run {module} {run_args}".strip(), print)
    if status != 0:
        print(f"{prefix}  ✖  {module} exited with error: {result}"); return False
    print(f"{prefix}  ✔  {module} exited ({result})")
    return True


def _cmd_uninstall(current_dir: Path):
    import shutil
    _box_top("UNINSTALL")
    _box_row(f"Target : {current_dir}")
    _box_bot()
    print()
    removed, skipped, failed = [], [], []
    for idx, folder in enumerate(["core", "modules", "data"], 1):
        prefix   = f"  [{idx}/3]"
        dir_path = current_dir / folder
        if not dir_path.exists():
            print(f"{prefix}  ·  /{folder}  (already absent)"); skipped.append(folder); continue
        try:
            shutil.rmtree(dir_path)
            print(f"{prefix}  ✔  /{folder}  removed"); removed.append(folder)
        except OSError as exc:
            print(f"{prefix}  ✖  /{folder}  —  {_err('E007', str(exc))}"); failed.append(folder)
    cfg = current_dir / "R_ECO.cfg"
    if cfg.exists():
        try: cfg.unlink(); _ok("R_ECO.cfg removed")
        except OSError: pass
    print(f"\n  Removed: {len(removed)}  Skipped: {len(skipped)}  Failed: {len(failed)}\n")


def _load_apix(current_dir: Path):
    apix_path = current_dir / "core" / "apix.py"
    if not apix_path.exists():
        raise RuntimeError(_err("E020", f"'{apix_path}' not found"))
    spec = importlib.util.spec_from_file_location("core.apix", str(apix_path))
    if not spec or not spec.loader:
        raise RuntimeError(_err("E020", "importlib could not build a spec"))
    module = importlib.util.module_from_spec(spec)
    sys.modules["core.apix"] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise RuntimeError(_err("E020", str(exc))) from exc
    if not hasattr(module, "R_ECO3"):
        raise RuntimeError(_err("E020", "'R_ECO3' missing from apix.py"))
    return module

def _dispatch(current_dir: Path, raw: str, *, prefix: str = "",
              from_reco: bool = False) -> bool:
    if not raw.strip(): return True
    verb = raw.split()[0].lower()
    if from_reco and verb in _RECO_FORBIDDEN:
        print(f"{prefix}  ✖  '{verb}'  —  {_err('E015', f'cannot call {verb!r} from .reco')}")
        return False
    if verb == "set":        return _cmd_set(current_dir, raw, prefix=prefix)
    elif verb == "get":      return _cmd_get(current_dir, raw, prefix=prefix)
    elif verb == "del":      return _cmd_del(current_dir, raw, prefix=prefix)
    elif verb == "list_keys":return _cmd_list_keys(current_dir, prefix=prefix)
    elif verb == "run":      return _cmd_run(current_dir, raw, prefix=prefix)
    else:
        print(f"{prefix}  ✖  {_err('E014', repr(verb))}")
        print(f"{prefix}     {_HELP_RECO if from_reco else _HELP_REPL}")
        return False

def R_ECO3(args, log_fn):
    current_dir = Path(__file__).resolve().parent.parent

    session_rsa: dict = {"n": None, "e": None, "fp": None, "source": None}

    # 1. Clé DEFAULT hardcodée
    def_n, def_e, def_fp = _load_default_pubkey()
    if def_n is not None:
        session_rsa = {"n": def_n, "e": def_e, "fp": def_fp, "source": "DEFAULT"}

    # 2. DB (surcharge si pas de DEFAULT)
    if session_rsa["source"] != "DEFAULT":
        try:
            db    = _open_db(current_dir)
            n_hex = db.get("rsa_pub_n") if db.exists("rsa_pub_n") else None
            e_val = db.get("rsa_pub_e") if db.exists("rsa_pub_e") else None
            if n_hex and e_val:
                n = int(n_hex, 16)
                session_rsa = {"n": n, "e": int(e_val),
                               "fp": _make_fingerprint(n), "source": "DB"}
        except Exception:
            pass

    _banner(session_rsa.get("fp"))

    if session_rsa["source"]:
        _ok(f"RSA key loaded from {session_rsa['source']}  "
            f"(fp: {session_rsa['fp']})")
        print()

    while True:
        try:
            raw = input("r_eco> ").strip()
        except (EOFError, KeyboardInterrupt):
            print(); _ok("Session terminated."); break

        if not raw:
            continue

        verb  = raw.split()[0].lower()
        parts = raw.split()

        if verb == "install":
            packet_path = None
            if len(parts) >= 2:
                p = Path(parts[1])
                packet_path = p if p.is_absolute() else current_dir / p
            _cmd_install(current_dir, packet_path,
                         rsa_n=session_rsa["n"], rsa_e=session_rsa["e"])

        elif verb == "uninstall":
            _cmd_uninstall(current_dir)

        elif verb == "set_rsa_key":
            tail = raw.split(maxsplit=1)
            if len(tail) < 2:
                print("  Usage : set_rsa_key <passphrase> [bits]")
            else:
                sub  = tail[1].rsplit(maxsplit=1)
                pp   = sub[0]
                bits = int(sub[1]) if len(sub) > 1 and sub[1].isdigit() else 4096
                try:
                    n, e, _ = _set_key(pp, bits)
                    fp      = _make_fingerprint(n)
                    session_rsa = {"n": n, "e": e, "fp": fp, "source": "set_rsa_key"}
                    _ok(f"RSA key active  (fp: {fp})")
                    try:
                        db = _open_db(current_dir)
                        db.set("rsa_pub_n", hex(n))
                        db.set("rsa_pub_e", str(e))
                        _ok("Key persisted in database.")
                    except Exception:
                        _warn("DB not ready — key not persisted (lost on exit).")
                except Exception as exc:
                    _fail("E022", str(exc))

        elif verb == "load_pubkey":
            path = parts[1] if len(parts) > 1 else "pubkey.json"
            try:
                full = Path(path) if Path(path).is_absolute() else current_dir / path
                n, e, fp = _load_pubkey_from_file(str(full))
                session_rsa = {"n": n, "e": e, "fp": fp, "source": f"file:{path}"}
                _ok(f"RSA key loaded from '{path}'  (fp: {fp})")
                try:
                    db = _open_db(current_dir)
                    db.set("rsa_pub_n", hex(n))
                    db.set("rsa_pub_e", str(e))
                    _ok("Key persisted in database.")
                except Exception:
                    _warn("DB not ready — key not persisted.")
            except Exception as exc:
                _fail("E027", str(exc))

        elif verb == "rsa_status":
            if session_rsa["n"] is not None:
                _ok(f"RSA key active")
                print(f"     Fingerprint : {session_rsa['fp']}")
                print(f"     Bits        : {session_rsa['n'].bit_length()}")
                print(f"     Source      : {session_rsa['source']}")
            else:
                _warn("No RSA key in session.")
                print("     → use 'set_rsa_key <passphrase>' or 'load_pubkey <file>'")
                if R_ECO_DEFAULT_PUBKEY is None:
                    print("     → or set R_ECO_DEFAULT_PUBKEY in _start.py (run gen_default in reco_bldr)")

        elif verb in ("quit", "exit"):
            _ok("Goodbye."); break

        else:
            _dispatch(current_dir, raw, from_reco=False)

        print()

def R_ECO3dep():
    """Returns the minimal dependencies required for module initialization."""
    return (("3.5.1b",), (),)

def R_ECO3inf():
    """Returns the metadata and help dictionary for RAVEN."""
    return {
        "name": "_start",
        "desc": "Bootstrap initialisation utility — R-ECO3 Ant",
        "help": "System bootstrap utility. Manages the interactive REPL for installing module packets, deriving encryption keys, and initializing the internal hive database.",
        "version_mod": "3.5.1b",
        "L2Module": False,
        "manual": "_start [None]"
    }