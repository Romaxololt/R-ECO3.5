import os
import struct
import hashlib
import math

# ─────────────────────────────────────────────
#  CONSTANTES
# ─────────────────────────────────────────────

RSA_BITS          = 4096
HASH_LEN          = 32        # SHA-256
AES_KEY_LEN       = 32        # AES-256
AES_BLOCK         = 16
HEADER_MAGIC      = b"RCRYPT1"

PBKDF2_ITERATIONS  = 100_000
PBKDF2_SALT_PREFIX = b"RomaCrypt-setkey-v1-"


# ═══════════════════════════════════════════════════════════════
#  ARITHMÉTIQUE / PRIMAIRES RSA
# ═══════════════════════════════════════════════════════════════

def mod_pow(base: int, exp: int, mod: int) -> int:
    result = 1
    base %= mod
    while exp > 0:
        if exp & 1:
            result = result * base % mod
        base = base * base % mod
        exp >>= 1
    return result

def miller_rabin(n: int, rounds: int = 20) -> bool:
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
        x = mod_pow(a, d, n)
        if x == 1 or x == n - 1:
            continue
        for _ in range(r - 1):
            x = x * x % n
            if x == n - 1:
                break
        else:
            return False
    return True

def random_prime(bits: int) -> int:
    while True:
        candidate = int.from_bytes(os.urandom(bits // 8), 'big')
        candidate |= (1 << (bits - 1))
        candidate |= 1
        if miller_rabin(candidate):
            return candidate

def extended_gcd(a: int, b: int):
    if a == 0:
        return b, 0, 1
    g, x, y = extended_gcd(b % a, a)
    return g, y - (b // a) * x, x

def mod_inverse(a: int, m: int) -> int:
    g, x, _ = extended_gcd(a % m, m)
    if g != 1:
        raise ValueError("Pas d'inverse modulaire")
    return x % m


# ═══════════════════════════════════════════════════════════════
#  DÉRIVATION DÉTERMINISTE (SET_KEY)
# ═══════════════════════════════════════════════════════════════

def _derive_seed(passphrase: str, bits: int) -> bytes:
    salt = PBKDF2_SALT_PREFIX + str(bits).encode()
    return hashlib.pbkdf2_hmac(
        'sha256',
        passphrase.encode('utf-8'),
        salt,
        PBKDF2_ITERATIONS,
        dklen=64
    )

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
        if miller_rabin(candidate):
            return candidate


# ═══════════════════════════════════════════════════════════════
#  FINGERPRINT
# ═══════════════════════════════════════════════════════════════

def fingerprint(n: int) -> str:
    """SHA-256[:16] de n en big-endian."""
    nb = n.to_bytes((n.bit_length() + 7) // 8, 'big')
    return hashlib.sha256(nb).hexdigest()[:16]


# ═══════════════════════════════════════════════════════════════
#  GÉNÉRATION DE CLÉS
# ═══════════════════════════════════════════════════════════════

def generate_rsa_keypair(bits: int = RSA_BITS, log_fn=print):
    log_fn(f"[*] Génération RSA-{bits} aléatoire en cours...")
    log_fn(f"[*] Recherche de deux premiers de {bits//2} bits (Miller-Rabin, 20 rondes)")
    log_fn(f"[*] Patience — l'entropie ne se précipite pas.")
    e       = 65537
    half    = bits // 2
    attempt = 0
    while True:
        attempt += 1
        if attempt > 1:
            log_fn(f"[*] Tentative {attempt} (φ(n) incompatible avec e=65537, on recommence...)")
        p = random_prime(half)
        q = random_prime(half)
        if p == q:
            continue
        n   = p * q
        phi = (p - 1) * (q - 1)
        if math.gcd(e, phi) == 1:
            d  = mod_inverse(e, phi)
            fp = fingerprint(n)
            log_fn(f"[+] Paire RSA-{bits} générée en {attempt} tentative(s).")
            log_fn(f"[+] n  = {hex(n)[:18]}...  ({n.bit_length()} bits effectifs)")
            log_fn(f"[+] Fingerprint : {fp}")
            return n, e, d

def set_key(passphrase: str, bits: int = RSA_BITS, log_fn=print):
    """
    Dérive une paire RSA de façon procédurale et déterministe.
    La même passphrase + bits produit TOUJOURS les mêmes clés.
    Retourne (n, e, d).
    """
    log_fn(f"[*] Dérivation PBKDF2-SHA256 ({PBKDF2_ITERATIONS:,} itérations, sel fixe RomaCrypt-v1)...")
    log_fn(f"[*] Ce calcul est intentionnellement lent — c'est le coût de la sécurité.")
    seed = _derive_seed(passphrase, bits)
    log_fn(f"[*] Graine 512 bits obtenue. Expansion RSA-{bits} procédurale...")
    log_fn(f"[*] Même passphrase + même bits → mêmes clés, toujours.")

    rng     = _make_det_rng(seed)
    e       = 65537
    half    = bits // 2
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
            d  = mod_inverse(e, phi)
            fp = fingerprint(n)
            log_fn(f"[+] Clés dérivées en {attempt} tentative(s).  RSA-{bits}")
            log_fn(f"[+] Fingerprint : {fp}")
            log_fn(f"[+] Ce fingerprint est reproductible : même passphrase → même fingerprint.")
            return n, e, d


# ═══════════════════════════════════════════════════════════════
#  AES-256 CBC (stdlib seulement)
# ═══════════════════════════════════════════════════════════════

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

def _sub_bytes(state):
    for r in range(4):
        for c in range(4):
            state[r][c] = _SBOX[state[r][c]]

def _inv_sub_bytes(state):
    for r in range(4):
        for c in range(4):
            state[r][c] = _INV_SBOX[state[r][c]]

def _shift_rows(state):
    for r in range(1, 4):
        state[r] = state[r][r:] + state[r][:r]

def _inv_shift_rows(state):
    for r in range(1, 4):
        state[r] = state[r][-r:] + state[r][:-r]

def _mix_columns(state):
    for c in range(4):
        s = [state[r][c] for r in range(4)]
        state[0][c] = _gmul(s[0],2) ^ _gmul(s[1],3) ^ s[2]          ^ s[3]
        state[1][c] = s[0]          ^ _gmul(s[1],2) ^ _gmul(s[2],3) ^ s[3]
        state[2][c] = s[0]          ^ s[1]          ^ _gmul(s[2],2) ^ _gmul(s[3],3)
        state[3][c] = _gmul(s[0],3) ^ s[1]          ^ s[2]          ^ _gmul(s[3],2)

def _inv_mix_columns(state):
    for c in range(4):
        s = [state[r][c] for r in range(4)]
        state[0][c] = _gmul(s[0],0x0e)^_gmul(s[1],0x0b)^_gmul(s[2],0x0d)^_gmul(s[3],0x09)
        state[1][c] = _gmul(s[0],0x09)^_gmul(s[1],0x0e)^_gmul(s[2],0x0b)^_gmul(s[3],0x0d)
        state[2][c] = _gmul(s[0],0x0d)^_gmul(s[1],0x09)^_gmul(s[2],0x0e)^_gmul(s[3],0x0b)
        state[3][c] = _gmul(s[0],0x0b)^_gmul(s[1],0x0d)^_gmul(s[2],0x09)^_gmul(s[3],0x0e)

def _aes_block_encrypt(block: bytes, w, Nr: int) -> bytes:
    state = [[block[r + 4*c] for c in range(4)] for r in range(4)]
    _add_round_key(state, w[:4])
    for rnd in range(1, Nr):
        _sub_bytes(state)
        _shift_rows(state)
        _mix_columns(state)
        _add_round_key(state, w[4*rnd:4*rnd+4])
    _sub_bytes(state)
    _shift_rows(state)
    _add_round_key(state, w[4*Nr:4*Nr+4])
    return bytes(state[r][c] for c in range(4) for r in range(4))

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

def aes_cbc_encrypt(key: bytes, iv: bytes, plaintext: bytes) -> bytes:
    pad       = AES_BLOCK - len(plaintext) % AES_BLOCK
    plaintext += bytes([pad] * pad)
    w, Nr     = _key_expansion(key)
    ct, prev  = b"", iv
    for i in range(0, len(plaintext), AES_BLOCK):
        blk  = bytes(a ^ b for a, b in zip(plaintext[i:i+AES_BLOCK], prev))
        prev = _aes_block_encrypt(blk, w, Nr)
        ct  += prev
    return ct

def aes_cbc_decrypt(key: bytes, iv: bytes, ciphertext: bytes) -> bytes:
    if len(ciphertext) == 0 or len(ciphertext) % AES_BLOCK != 0:
        raise ValueError(
            f"Longueur du ciphertext invalide ({len(ciphertext)} octets) — "
            f"doit être un multiple de {AES_BLOCK}"
        )
    w, Nr    = _key_expansion(key)
    pt, prev = b"", iv
    for i in range(0, len(ciphertext), AES_BLOCK):
        blk  = ciphertext[i:i+AES_BLOCK]
        dec  = _aes_block_decrypt(blk, w, Nr)
        pt  += bytes(a ^ b for a, b in zip(dec, prev))
        prev = blk
    pad = pt[-1]
    if not (1 <= pad <= AES_BLOCK) or pt[-pad:] != bytes([pad]*pad):
        raise ValueError("Padding PKCS#7 invalide — données corrompues ou clé incorrecte")
    return pt[:-pad]


# ═══════════════════════════════════════════════════════════════
#  OAEP
# ═══════════════════════════════════════════════════════════════

def mgf1(seed: bytes, length: int) -> bytes:
    out     = b""
    counter = 0
    while len(out) < length:
        c    = struct.pack(">I", counter)
        out += hashlib.sha256(seed + c).digest()
        counter += 1
    return out[:length]

def oaep_encode(message: bytes, k: int, label: bytes = b"RomaCrypt") -> bytes:
    hLen     = HASH_LEN
    mLen     = len(message)
    max_mLen = k - 2 * hLen - 2
    if mLen > max_mLen:
        raise ValueError(f"Message trop long pour OAEP ({mLen} > {max_mLen})")

    lHash  = hashlib.sha256(label).digest()
    PS     = b"\x00" * (k - mLen - 2 * hLen - 2)
    DB     = lHash + PS + b"\x01" + message

    seed       = os.urandom(hLen)
    dbMask     = mgf1(seed, k - hLen - 1)
    maskedDB   = bytes(a ^ b for a, b in zip(DB, dbMask))
    seedMask   = mgf1(maskedDB, hLen)
    maskedSeed = bytes(a ^ b for a, b in zip(seed, seedMask))

    return b"\x00" + maskedSeed + maskedDB

def oaep_decode(em: bytes, k: int, label: bytes = b"RomaCrypt") -> bytes:
    hLen = HASH_LEN
    if len(em) != k:
        raise ValueError("Longueur EM incorrecte")
    if em[0] != 0:
        raise ValueError("Premier octet EM invalide")

    maskedSeed = em[1 : 1 + hLen]
    maskedDB   = em[1 + hLen:]

    seedMask = mgf1(maskedDB, hLen)
    seed     = bytes(a ^ b for a, b in zip(maskedSeed, seedMask))

    dbMask = mgf1(seed, k - hLen - 1)
    DB     = bytes(a ^ b for a, b in zip(maskedDB, dbMask))

    lHash_expected = hashlib.sha256(label).digest()
    lHash_actual   = DB[:hLen]
    if lHash_actual != lHash_expected:
        raise ValueError("Échec vérification label OAEP (données corrompues ou mauvaise clé)")

    rest = DB[hLen:]
    idx  = -1
    for i, byte in enumerate(rest):
        if byte == 0x01:
            idx = i
            break
        if byte != 0x00:
            raise ValueError("OAEP : octet inattendu dans le padding (données corrompues)")
    if idx == -1:
        raise ValueError("OAEP : séparateur 0x01 introuvable (données corrompues)")
    return rest[idx + 1:]


# ═══════════════════════════════════════════════════════════════
#  CHIFFREMENT HYBRIDE RSA + AES
# ═══════════════════════════════════════════════════════════════

def _const_eq(a: bytes, b: bytes) -> bool:
    if len(a) != len(b):
        return False
    result = 0
    for x, y in zip(a, b):
        result |= x ^ y
    return result == 0

def rsa_raw(val: int, exp: int, mod: int) -> int:
    return mod_pow(val, exp, mod)

def rsa_oaep_encrypt_key(aes_key: bytes, n: int, d: int) -> bytes:
    k  = (n.bit_length() + 7) // 8
    em = oaep_encode(aes_key, k)
    m  = int.from_bytes(em, 'big')
    if m >= n:
        raise ValueError("Valeur OAEP >= n")
    c  = rsa_raw(m, d, n)
    return c.to_bytes(k, 'big')

def rsa_oaep_decrypt_key(ciphertext: bytes, n: int, e: int) -> bytes:
    k  = (n.bit_length() + 7) // 8
    c  = int.from_bytes(ciphertext, 'big')
    m  = rsa_raw(c, e, n)
    em = m.to_bytes(k, 'big')
    return oaep_decode(em, k)

def encrypt_message(plaintext: bytes, n: int, d: int) -> bytes:
    """Chiffrement avec clé PRIVÉE (n, d)."""
    aes_key  = os.urandom(AES_KEY_LEN)
    iv       = os.urandom(AES_BLOCK)
    ct       = aes_cbc_encrypt(aes_key, iv, plaintext)
    enc_key  = rsa_oaep_encrypt_key(aes_key, n, d)

    hmac_key = hashlib.sha256(aes_key + b"hmac").digest()
    hmac_val = hashlib.sha256(hmac_key + enc_key + iv + ct).digest()

    k = (n.bit_length() + 7) // 8
    return (HEADER_MAGIC
            + struct.pack(">I", k)
            + enc_key
            + iv
            + hmac_val
            + ct)

def decrypt_message(blob: bytes, n: int, e: int) -> bytes:
    """Déchiffrement avec clé PUBLIQUE (n, e)."""
    if not blob.startswith(HEADER_MAGIC):
        raise ValueError(
            "Magic RCRYPT1 absent — fichier tronqué, corrompu, "
            "ou pas un paquet RomaCrypt"
        )
    pos = len(HEADER_MAGIC)

    k        = struct.unpack(">I", blob[pos:pos+4])[0]; pos += 4
    enc_key  = blob[pos:pos+k];                          pos += k
    iv       = blob[pos:pos+AES_BLOCK];                  pos += AES_BLOCK
    hmac_val = blob[pos:pos+HASH_LEN];                   pos += HASH_LEN
    ct       = blob[pos:]

    aes_key  = rsa_oaep_decrypt_key(enc_key, n, e)

    hmac_key = hashlib.sha256(aes_key + b"hmac").digest()
    expected = hashlib.sha256(hmac_key + enc_key + iv + ct).digest()
    if not _const_eq(hmac_val, expected):
        raise ValueError(
            "HMAC invalide — données altérées en transit "
            "ou clé publique incorrecte"
        )

    return aes_cbc_decrypt(aes_key, iv, ct)


# ═══════════════════════════════════════════════════════════════
#  R_ECO3 — interface apix
# ═══════════════════════════════════════════════════════════════

_COMMANDS = {
    "fingerprint": "fingerprint <n_int>          — SHA-256[:16] du modulus",
    "keygen":      "keygen [bits]                 — génère une paire RSA aléatoire",
    "set_key":     "set_key <passphrase> [bits]   — dérive une paire RSA déterministe",
    "encrypt":     "encrypt <n> <d> <hex_data>    — chiffre des données (clé privée)",
    "decrypt":     "decrypt <n> <e> <hex_blob>    — déchiffre un blob (clé publique)",
    "aes_enc":     "aes_enc <hex_key> <hex_iv> <hex_data>   — AES-256-CBC chiffrement",
    "aes_dec":     "aes_dec <hex_key> <hex_iv> <hex_ct>     — AES-256-CBC déchiffrement",
}

def R_ECO3(args: str, log_fn=print):
    """
    Interface apix du module crypto.

    Retourne (code, (status, valeur)) :
        (0, (0, valeur))   — succès
        (0, (1, msg))      — erreur applicative
        (1, (1, msg))      — erreur fatale / commande inconnue
    """
    parts = args.strip().split()

    # apix passe "run <module> <cmd> [args...]"
    # Si appelé via "run crypto <cmd>", parts[0]=="run", parts[1]=="crypto"
    # On normalise pour accepter les deux formes.
    if len(parts) >= 2 and parts[0] == "run":
        parts = parts[1:]           # retire "run"
    if len(parts) >= 1 and parts[0] == "crypto":
        parts = parts[1:]           # retire le nom du module

    if not parts:
        log_fn("[crypto] Commandes : " + "  |  ".join(_COMMANDS))
        return 0, (0, None)

    cmd  = parts[0].lower()
    rest = parts[1:]

    # ── fingerprint ────────────────────────────────────────────
    if cmd == "fingerprint":
        if not rest:
            log_fn("[crypto] Usage : fingerprint <n_int>")
            return 0, (1, "missing arg")
        try:
            n  = int(rest[0])
            fp = fingerprint(n)
            log_fn(fp)
            return 0, (0, fp)
        except Exception as ex:
            log_fn(f"[crypto] fingerprint error : {ex}")
            return 0, (1, str(ex))

    # ── keygen ─────────────────────────────────────────────────
    elif cmd == "keygen":
        bits = int(rest[0]) if rest and rest[0].isdigit() else RSA_BITS
        try:
            n, e, d = generate_rsa_keypair(bits, log_fn)
            return 0, (0, (n, e, d))
        except Exception as ex:
            log_fn(f"[crypto] keygen error : {ex}")
            return 0, (1, str(ex))

    # ── set_key ────────────────────────────────────────────────
    elif cmd == "set_key":
        if not rest:
            log_fn("[crypto] Usage : set_key <passphrase> [bits]")
            return 0, (1, "missing passphrase")
        passphrase = rest[0]
        bits       = int(rest[1]) if len(rest) > 1 and rest[1].isdigit() else RSA_BITS
        try:
            n, e, d = set_key(passphrase, bits, log_fn)
            return 0, (0, (n, e, d))
        except Exception as ex:
            log_fn(f"[crypto] set_key error : {ex}")
            return 0, (1, str(ex))

    # ── encrypt ────────────────────────────────────────────────
    elif cmd == "encrypt":
        if len(rest) < 3:
            log_fn("[crypto] Usage : encrypt <n> <d> <hex_data>")
            return 0, (1, "missing args")
        try:
            n        = int(rest[0])
            d        = int(rest[1])
            data     = bytes.fromhex(rest[2])
            blob     = encrypt_message(data, n, d)
            log_fn(blob.hex())
            return 0, (0, blob)
        except Exception as ex:
            log_fn(f"[crypto] encrypt error : {ex}")
            return 0, (1, str(ex))

    # ── decrypt ────────────────────────────────────────────────
    elif cmd == "decrypt":
        if len(rest) < 3:
            log_fn("[crypto] Usage : decrypt <n> <e> <hex_blob>")
            return 0, (1, "missing args")
        try:
            n        = int(rest[0])
            e        = int(rest[1])
            blob     = bytes.fromhex(rest[2])
            plain    = decrypt_message(blob, n, e)
            log_fn(plain.hex())
            return 0, (0, plain)
        except Exception as ex:
            log_fn(f"[crypto] decrypt error : {ex}")
            return 0, (1, str(ex))

    # ── aes_enc ────────────────────────────────────────────────
    elif cmd == "aes_enc":
        if len(rest) < 3:
            log_fn("[crypto] Usage : aes_enc <hex_key> <hex_iv> <hex_data>")
            return 0, (1, "missing args")
        try:
            key  = bytes.fromhex(rest[0])
            iv   = bytes.fromhex(rest[1])
            data = bytes.fromhex(rest[2])
            ct   = aes_cbc_encrypt(key, iv, data)
            log_fn(ct.hex())
            return 0, (0, ct)
        except Exception as ex:
            log_fn(f"[crypto] aes_enc error : {ex}")
            return 0, (1, str(ex))

    # ── aes_dec ────────────────────────────────────────────────
    elif cmd == "aes_dec":
        if len(rest) < 3:
            log_fn("[crypto] Usage : aes_dec <hex_key> <hex_iv> <hex_ct>")
            return 0, (1, "missing args")
        try:
            key = bytes.fromhex(rest[0])
            iv  = bytes.fromhex(rest[1])
            ct  = bytes.fromhex(rest[2])
            pt  = aes_cbc_decrypt(key, iv, ct)
            log_fn(pt.hex())
            return 0, (0, pt)
        except Exception as ex:
            log_fn(f"[crypto] aes_dec error : {ex}")
            return 0, (1, str(ex))

    # ── help ───────────────────────────────────────────────────
    elif cmd in ("help", "?"):
        for line in _COMMANDS.values():
            log_fn("  " + line)
        return 0, (0, None)

    # ── commande inconnue ──────────────────────────────────────
    else:
        log_fn(f"[crypto] Commande inconnue : '{cmd}'. Tape 'help' pour la liste.")
        return 1, (1, f"unknown command: {cmd}")


def R_ECO3dep():
    return (("3.5.1b",), ((),))


def R_ECO3inf():
    return {
        "name":        "crypto",
        "desc":        "Pure-Python RSA+AES+OAEP cryptographic primitives — no external dependencies",
        "help":        "Provides RSA key generation (random or deterministic), hybrid RSA+AES-256-CBC encryption/decryption, standalone AES-CBC operations, OAEP padding, and key fingerprinting. All ops available via core.apix.",
        "version_mod": "1.0",
        "L2Module":    True,
        "manual": (
            "crypto <command> [args]\n\n"
            "AVAILABLE COMMANDS & ARGUMENTS:\n"
            "  fingerprint <n>\n"
            "    Returns the SHA-256[:16] fingerprint of a RSA modulus.\n\n"
            "  keygen [bits]\n"
            "    Generates a random RSA key pair. Defaults to 4096 bits.\n"
            "    Returns (n, e, d).\n\n"
            "  set_key <passphrase> [bits]\n"
            "    Derives a deterministic RSA key pair from a passphrase via PBKDF2-SHA256.\n"
            "    Same passphrase + same bits always produces the same key pair.\n"
            "    Returns (n, e, d).\n\n"
            "  encrypt <n> <d> <hex_data>\n"
            "    Hybrid RSA+AES-256-CBC encryption using the private key (n, d).\n"
            "    Returns encrypted blob as hex.\n\n"
            "  decrypt <n> <e> <hex_blob>\n"
            "    Hybrid decryption using the public key (n, e).\n"
            "    Returns plaintext as hex.\n\n"
            "  aes_enc <hex_key> <hex_iv> <hex_data>\n"
            "    Standalone AES-256-CBC encryption with PKCS#7 padding.\n\n"
            "  aes_dec <hex_key> <hex_iv> <hex_ct>\n"
            "    Standalone AES-256-CBC decryption with PKCS#7 padding validation.\n"
        )
    }