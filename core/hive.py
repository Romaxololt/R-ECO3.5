"""
Hive.py — KVEco v2.1 : store clé/valeur fichier-unique avec index embarqué.

Format sur disque (tout dans un seul fichier) :
┌─────────────────────────────────────────────────────────────────────────────┐
│ HEADER  (64 octets, fixe)                                                   │
│   magic       4B  b"HIVE"                                                   │
│   version     2B  uint16                                                    │
│   flags       2B  réservé                                                   │
│   next_write  8B  uint64  offset de la prochaine écriture dans le data log  │
│   visit_ctr   8B  uint64  compteur global de visites (get+set)              │
│   maint_every 4B  uint32  fréquence de maintenance                          │
│   idx_offset  8B  uint64  offset de la section INDEX (0 si pas encore écrit)│
│   idx_size    8B  uint64  taille en octets de la section INDEX              │
│   _pad       20B  réservé                                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│ DATA LOG  (append-only, records de taille variable)                         │
│   rec_magic  4B  b"REC\x01"                                                 │
│   name_len   2B  uint16                                                     │
│   data_len   4B  uint32                                                     │
│   flags      1B  0x00=alive 0x01=tombstone 0x02=pinned 0x04=aposet          │
│   _pad       1B                                                             │
│   visit_cnt  8B  uint64                                                     │
│   death_idx  8B  int64   (-1 = immortel)                                    │
│   name       name_len B  UTF-8                                              │
│   data       data_len B  UTF-8  "<type_tag>\n<str_value>"                   │
├─────────────────────────────────────────────────────────────────────────────┤
│ INDEX SECTION  (en fin de fichier, réécrite à chaque flush dirty)           │
│   idx_magic   4B  b"HIDX"                                                   │
│   payload_sz  4B  uint32                                                    │
│   payload     NB  pickle({name -> HiveEntry})                               │
└─────────────────────────────────────────────────────────────────────────────┘

Changements v2.1 vs v2 :
  • Robustesse totale : tous les chemins de lecture ont un try/except ;
    un record corrompu est sauté au lieu de faire crasher l'ouverture.
  • _decode_value tolère les bytes non-UTF-8 (retourne les bytes bruts).
  • Support natif du type bytes dans _encode_value / _decode_value (hex).
  • delete() retourne bool (True=supprimé, False=absent) pour rester
    cohérent avec l'usage dans _start.py ; KeyError supprimé.
  • _encode_value : dispatch O(1) par dict, name.encode() appelé une fois.
  • _compact : lecture de tous les raw avant truncate → évite les seeks
    aller-retour après troncature.
  • stats() : comptage en une seule passe sur _index.values().
  • _rebuild_index_from_log : skip des data via buf.read() (pas seek).
  • Ajout de __slots__ sur HiveEntry pour réduire l'empreinte mémoire.
"""

import os
import io
import struct
import pickle
import threading
from dataclasses import dataclass
from collections import OrderedDict
from typing import Any

# ─── Constantes ──────────────────────────────────────────────────────────────

MAGIC        = b"HIVE"
VERSION      = 2
HEADER_SIZE  = 64

# >4sHHQQIQQ20s
HEADER_FMT   = ">4sHHQQIQQ20s"
assert struct.calcsize(HEADER_FMT) == HEADER_SIZE

REC_MAGIC    = b"REC\x01"
REC_HDR_FMT  = ">4sHIBBQq"   # rec_magic, name_len, data_len, flags, pad, visit_cnt, death_idx
REC_HDR_SIZE = struct.calcsize(REC_HDR_FMT)   # 28 octets

# flags record (bits)
FLAG_TOMBSTONE = 0x01
FLAG_PINNED    = 0x02
FLAG_APOSET    = 0x04
# NB : FLAG_ALIVE n'existe pas en tant que bit — un record est vivant quand
#      le bit TOMBSTONE est absent. L'ancien FLAG_ALIVE = 0 était trompeur.

HOT_CACHE_SIZE     = 256
VISIT_DECAY_FACTOR = 2
MAINT_DEFAULT      = 100
INDEX_PICKLE_MAGIC = b"HIDX"

# ─── Sérialisation des valeurs ────────────────────────────────────────────────

# Table de (type Python, encodeur str, décodeur str)
# encodeur : value → str   (pour f"{tag}\n{encodeur(value)}")
# décodeur : str   → value
_SUPPORTED_TYPES: dict[str, tuple[type, Any, Any]] = {
    "str":      (str,        str,              str),
    "int":      (int,        str,              int),
    "float":    (float,      str,              float),
    "bool":     (bool,       str,              lambda s: s == "True"),
    "NoneType": (type(None), lambda _: "",     lambda _: None),
    "bytes":    (bytes,      bytes.hex,        bytes.fromhex),
}

# type Python → tag
_TYPE_TO_TAG: dict[type, str] = {v[0]: k for k, v in _SUPPORTED_TYPES.items()}

# tag → décodeur (accès O(1) à la lecture)
_TAG_TO_DECODER: dict[str, Any] = {k: v[2] for k, v in _SUPPORTED_TYPES.items()}

# tag → encodeur (accès O(1) à l'écriture)
_TAG_TO_ENCODER: dict[str, Any] = {k: v[1] for k, v in _SUPPORTED_TYPES.items()}


def _encode_value(value: Any) -> bytes:
    t   = type(value)
    tag = _TYPE_TO_TAG.get(t)
    if tag is None:
        raise TypeError(
            f"Type non supporté : {t.__name__!r}. "
            f"Types acceptés : {', '.join(_TYPE_TO_TAG)}" #type: ignore
        )
    enc = _TAG_TO_ENCODER[tag]
    return f"{tag}\n{enc(value)}".encode("utf-8")


def _decode_value(raw: bytes) -> Any:
    """Décode une valeur stockée. Ne lève jamais d'exception — retourne
    les bytes bruts en dernier recours si les données sont corrompues."""
    try:
        text = raw.decode("utf-8")
    except (UnicodeDecodeError, ValueError):
        return raw          # bytes corrompus → on retourne tel quel

    tag, sep, str_val = text.partition("\n")
    if not sep:             # pas de séparateur → données malformées
        return raw

    decoder = _TAG_TO_DECODER.get(tag)
    if decoder is None:
        return str_val      # tag inconnu → retour str brut

    try:
        return decoder(str_val)
    except (ValueError, TypeError):
        return str_val      # échec de conversion → str brut


def _decode_type_tag(raw: bytes) -> type:
    """Retourne le type Python associé au tag, sans décoder la valeur."""
    try:
        tag = raw.split(b"\n", 1)[0].decode("utf-8")
        entry = _SUPPORTED_TYPES.get(tag)
        return entry[0] if entry else str
    except (UnicodeDecodeError, ValueError):
        return bytes


# ─── Structures en mémoire ───────────────────────────────────────────────────

@dataclass
class HiveEntry:
    __slots__ = ("offset", "visit_cnt", "death_idx", "flags", "name_len", "data_len")

    offset:    int
    visit_cnt: float
    death_idx: int
    flags:     int
    name_len:  int
    data_len:  int

    @property
    def alive(self)     -> bool: return not (self.flags & FLAG_TOMBSTONE)
    @property
    def pinned(self)    -> bool: return bool(self.flags & FLAG_PINNED)
    @property
    def is_aposet(self) -> bool: return bool(self.flags & FLAG_APOSET)


# ─── Cache LRU simple ────────────────────────────────────────────────────────

class _LRUCache:
    __slots__ = ("_d", "_max", "hits", "misses")

    def __init__(self, maxsize: int):
        self._d: OrderedDict = OrderedDict()
        self._max   = maxsize
        self.hits   = 0
        self.misses = 0

    def get(self, key):
        node = self._d.get(key)
        if node is None:
            self.misses += 1
            return None
        self._d.move_to_end(key)
        self.hits += 1
        return node

    def put(self, key, value):
        if key in self._d:
            self._d.move_to_end(key)
        self._d[key] = value
        if len(self._d) > self._max:
            self._d.popitem(last=False)

    def evict(self, key):
        self._d.pop(key, None)

    def clear(self):
        self._d.clear()

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total else 0.0


# ─── Sentinel ────────────────────────────────────────────────────────────────

_SENTINEL = object()

# os.writev disponible sur Linux/macOS, absent sous Windows
_HAS_WRITEV = hasattr(os, "writev")

# Offsets précalculés dans le header d'un record (évite struct.calcsize répété)
_REC_FLAGS_OFFSET = struct.calcsize(">4sHI")          # offset du byte flags
_REC_VC_OFFSET    = struct.calcsize(">4sHIBB")        # offset du uint64 visit_cnt


# ══════════════════════════════════════════════════════════════════════════════
#  Hive
# ══════════════════════════════════════════════════════════════════════════════

class Hive:
    """
    Store KV persistant append-only, fichier unique (.hive).
    L'index est sérialisé (pickle) dans une section dédiée en fin de fichier.
    Thread-safe via RLock.
    """

    def __init__(
        self,
        path:        str,
        maint_every: int = MAINT_DEFAULT,
        cache_size:  int = HOT_CACHE_SIZE,
    ):
        self._path         = path
        self._lock         = threading.RLock()
        self._cache        = _LRUCache(cache_size)
        self._index:       dict[str, HiveEntry] = {}
        self._names:       set[str]             = set()
        self._visit_ctr:   int                  = 0
        self._maint_every: int                  = maint_every
        self._idx_dirty:   bool                 = False

        self._open()

    # ── Ouverture ─────────────────────────────────────────────────────────────

    def _open(self):
        if os.path.exists(self._path):
            self._fh = open(self._path, "r+b")
            try:
                self._load_header()
                self._load_index()
            except Exception as exc:
                # Fichier présent mais illisible → on repart de zéro
                self._fh.close()
                self._fh = open(self._path, "w+b")
                self._reset_state()
                self._write_header()
        else:
            self._fh = open(self._path, "w+b")
            self._reset_state()
            self._write_header()

    def _reset_state(self):
        self._visit_ctr  = 0
        self._next_write = HEADER_SIZE
        self._idx_offset = 0
        self._idx_size   = 0
        self._index      = {}
        self._names      = set()
        self._idx_dirty  = False

    # ── Header ────────────────────────────────────────────────────────────────

    def _pack_header(self) -> bytes:
        return struct.pack(
            HEADER_FMT,
            MAGIC, VERSION, 0,
            self._next_write,
            self._visit_ctr,
            self._maint_every,
            self._idx_offset,
            self._idx_size,
            b"\x00" * 20,
        )

    def _write_header(self):
        self._fh.seek(0)
        self._fh.write(self._pack_header())

    def _load_header(self):
        self._fh.seek(0)
        raw = self._fh.read(HEADER_SIZE)
        if len(raw) < HEADER_SIZE:
            raise ValueError("Header tronqué")
        magic, version, _flags, nw, vc, me, idx_off, idx_sz, _pad = \
            struct.unpack(HEADER_FMT, raw)
        if magic != MAGIC:
            raise ValueError(f"Magic invalide : {magic!r}")
        self._next_write  = nw
        self._visit_ctr   = vc
        self._maint_every = me
        self._idx_offset  = idx_off
        self._idx_size    = idx_sz

    # ── Index embarqué ────────────────────────────────────────────────────────

    def _save_index(self):
        """Sérialise l'index et l'écrit dans le fichier. No-op si pas dirty."""
        if not self._idx_dirty:
            return
        payload  = pickle.dumps(self._index)
        idx_data = INDEX_PICKLE_MAGIC + struct.pack(">I", len(payload)) + payload
        self._idx_offset = self._next_write
        self._idx_size   = len(idx_data)
        self._fh.seek(self._idx_offset)
        self._fh.write(idx_data)
        self._idx_dirty  = False

    def _load_index(self):
        """Charge l'index depuis la section embarquée ; reconstruit depuis le
        log en cas d'échec (index absent, corrompu, ou pickle incompatible)."""
        if self._idx_offset >= HEADER_SIZE and self._idx_size > 0:
            try:
                self._fh.seek(self._idx_offset)
                raw = self._fh.read(self._idx_size)
                if raw[:4] != INDEX_PICKLE_MAGIC:
                    raise ValueError("Magic INDEX invalide")
                size        = struct.unpack(">I", raw[4:8])[0]
                self._index = pickle.loads(raw[8: 8 + size])
                self._names = {k for k, e in self._index.items() if e.alive}
                return
            except Exception:
                pass   # on tombe dans le rebuild
        self._rebuild_index_from_log()

    def _rebuild_index_from_log(self):
        """Scan séquentiel du data log. Les records corrompus sont sautés."""
        self._index = {}
        pos = HEADER_SIZE
        end = self._idx_offset if self._idx_offset > HEADER_SIZE else self._next_write
        self._fh.seek(pos)
        buf = io.BytesIO(self._fh.read(max(0, end - pos)))

        while True:
            hdr_raw = buf.read(REC_HDR_SIZE)
            if len(hdr_raw) < REC_HDR_SIZE:
                break
            try:
                rec_magic, name_len, data_len, flags, _pad, visit_cnt, death_idx = \
                    struct.unpack(REC_HDR_FMT, hdr_raw)
            except struct.error:
                break

            if rec_magic != REC_MAGIC:
                break

            name_raw = buf.read(name_len)
            buf.read(data_len)          # skip data — pas de seek() pour rester portable

            if len(name_raw) < name_len:
                break                   # record tronqué → on s'arrête

            try:
                name = name_raw.decode("utf-8")
            except (UnicodeDecodeError, ValueError):
                pos += REC_HDR_SIZE + name_len + data_len
                continue                # nom corrompu → on saute ce record

            self._index[name] = HiveEntry(
                offset=pos,
                visit_cnt=float(visit_cnt),
                death_idx=death_idx,
                flags=flags,
                name_len=name_len,
                data_len=data_len,
            )
            pos += REC_HDR_SIZE + name_len + data_len

        self._names     = {k for k, e in self._index.items() if e.alive}
        self._idx_dirty = True

    # ── Fermeture ─────────────────────────────────────────────────────────────

    def close(self):
        with self._lock:
            self._flush()
            self._fh.close()

    def _flush(self):
        self._save_index()
        self._write_header()
        self._fh.flush()

    def __enter__(self):    return self
    def __exit__(self, *_): self.close()

    # ── Primitives disque ─────────────────────────────────────────────────────

    def _read_raw_at(self, entry: HiveEntry) -> bytes:
        self._fh.seek(entry.offset + REC_HDR_SIZE + entry.name_len)
        return self._fh.read(entry.data_len)

    def _append_record(
        self,
        name_b:    bytes,       # nom déjà encodé UTF-8 (évite le double encode)
        raw:       bytes,
        flags:     int   = 0,
        visit_cnt: float = 1.0,
        death_idx: int   = -1,
    ) -> int:
        name_len = len(name_b)
        data_len = len(raw)
        hdr = struct.pack(
            REC_HDR_FMT,
            REC_MAGIC, name_len, data_len, flags, 0,
            int(visit_cnt), death_idx,
        )
        offset = self._next_write
        self._fh.seek(offset)
        if _HAS_WRITEV:
            written = os.writev(self._fh.fileno(), [hdr, name_b, raw])
            self._next_write += written
        else:
            self._fh.write(hdr + name_b + raw)
            self._next_write = self._fh.tell()
        self._idx_dirty = True
        return offset

    def _mark_tombstone_at(self, offset: int):
        self._fh.seek(offset + _REC_FLAGS_OFFSET)
        self._fh.write(bytes([FLAG_TOMBSTONE]))

    def _update_visit_on_disk(self, offset: int, visit_cnt: float):
        self._fh.seek(offset + _REC_VC_OFFSET)
        self._fh.write(struct.pack(">Q", int(visit_cnt)))

    # ── Tick + maintenance ────────────────────────────────────────────────────

    def _tick(self, n: int = 1):
        prev = self._visit_ctr % self._maint_every
        self._visit_ctr += n
        if prev + n >= self._maint_every:
            self._maintenance()

    # ── Expiration aposet (interne) ───────────────────────────────────────────

    def _is_expired(self, entry: HiveEntry) -> bool:
        return (entry.is_aposet
                and entry.death_idx >= 0
                and self._visit_ctr >= entry.death_idx)

    def _kill_entry(self, name: str, entry: HiveEntry):
        """Pose un tombstone sur disque et met à jour les structures en mémoire."""
        self._mark_tombstone_at(entry.offset)
        entry.flags |= FLAG_TOMBSTONE
        self._names.discard(name)
        self._cache.evict(name)
        self._idx_dirty = True

    # ══════════════════════════════════════════════════════════════════════════
    #  API publique
    # ══════════════════════════════════════════════════════════════════════════

    def get(self, name: str, default: Any = None) -> Any:
        with self._lock:
            entry = self._index.get(name)
            if entry is None or not entry.alive:
                self._tick()
                return default

            if self._is_expired(entry):
                self._kill_entry(name, entry)
                self._tick()
                return default

            cached = self._cache.get(name)
            if cached is not None:
                entry.visit_cnt += 1
                self._update_visit_on_disk(entry.offset, entry.visit_cnt)
                self._tick()
                return cached

            raw   = self._read_raw_at(entry)
            value = _decode_value(raw)
            entry.visit_cnt += 1
            self._update_visit_on_disk(entry.offset, entry.visit_cnt)
            self._cache.put(name, value)
            self._tick()
            return value

    def set(self, name: str, value: Any, *, pinned: bool = False):
        with self._lock:
            raw    = _encode_value(value)
            name_b = name.encode("utf-8")           # encodé une seule fois
            flags  = FLAG_PINNED if pinned else 0

            existing  = self._index.get(name)
            visit_cnt = 1.0
            if existing and existing.alive:
                visit_cnt = existing.visit_cnt + 1
                self._mark_tombstone_at(existing.offset)

            offset = self._append_record(name_b, raw, flags=flags, visit_cnt=visit_cnt)
            self._index[name] = HiveEntry(
                offset=offset, visit_cnt=visit_cnt, death_idx=-1,
                flags=flags, name_len=len(name_b), data_len=len(raw),
            )
            self._names.add(name)
            self._cache.put(name, value)
            self._tick()

    def aposet(self, name: str, value: Any, death_in: int = 50):
        """Stocke une valeur qui s'auto-supprimera après `death_in` visites."""
        with self._lock:
            raw       = _encode_value(value)
            name_b    = name.encode("utf-8")
            death_idx = self._visit_ctr + death_in
            flags     = FLAG_APOSET

            existing  = self._index.get(name)
            visit_cnt = 1.0
            if existing and existing.alive:
                visit_cnt = existing.visit_cnt + 1
                self._mark_tombstone_at(existing.offset)

            offset = self._append_record(
                name_b, raw, flags=flags, visit_cnt=visit_cnt, death_idx=death_idx
            )
            self._index[name] = HiveEntry(
                offset=offset, visit_cnt=visit_cnt, death_idx=death_idx,
                flags=flags, name_len=len(name_b), data_len=len(raw),
            )
            self._names.add(name)
            self._cache.put(name, value)
            self._tick()

    def delete(self, name: str) -> bool:
        """Supprime une clé. Retourne True si supprimée, False si absente.
        (ne lève plus KeyError — cohérent avec l'usage dans _start.py)"""
        with self._lock:
            entry = self._index.get(name)
            if entry is None or not entry.alive:
                return False
            self._kill_entry(name, entry)
            self._tick()
            return True

    def exists(self, name: str) -> bool:
        with self._lock:
            entry = self._index.get(name)
            if entry is None or not entry.alive:
                return False
            if self._is_expired(entry):
                self._kill_entry(name, entry)
                return False
            return True

    def type(self, name: str) -> type:
        with self._lock:
            entry = self._index.get(name)
            if entry is None or not entry.alive:
                raise KeyError(name)
            if self._is_expired(entry):
                self._kill_entry(name, entry)
                raise KeyError(name)
            raw = self._read_raw_at(entry)
            return _decode_type_tag(raw)

    # ── Batch ─────────────────────────────────────────────────────────────────

    def get_many(self, names: list[str], default: Any = None) -> dict[str, Any]:
        """Lecture batch sous un seul lock."""
        with self._lock:
            result: dict[str, Any] = {}
            for name in names:
                entry = self._index.get(name)
                if entry is None or not entry.alive:
                    result[name] = default
                    continue
                if self._is_expired(entry):
                    self._kill_entry(name, entry)
                    result[name] = default
                    continue
                cached = self._cache.get(name)
                if cached is not None:
                    entry.visit_cnt += 1
                    self._update_visit_on_disk(entry.offset, entry.visit_cnt)
                    result[name] = cached
                else:
                    raw   = self._read_raw_at(entry)
                    value = _decode_value(raw)
                    entry.visit_cnt += 1
                    self._update_visit_on_disk(entry.offset, entry.visit_cnt)
                    self._cache.put(name, value)
                    result[name] = value
            self._tick(len(names))
            return result

    def set_many(self, mapping: dict[str, Any], *, pinned: bool = False):
        """Écriture batch sous un seul lock."""
        with self._lock:
            flags = FLAG_PINNED if pinned else 0
            for name, value in mapping.items():
                raw    = _encode_value(value)
                name_b = name.encode("utf-8")
                existing  = self._index.get(name)
                visit_cnt = 1.0
                if existing and existing.alive:
                    visit_cnt = existing.visit_cnt + 1
                    self._mark_tombstone_at(existing.offset)
                offset = self._append_record(name_b, raw, flags=flags, visit_cnt=visit_cnt)
                self._index[name] = HiveEntry(
                    offset=offset, visit_cnt=visit_cnt, death_idx=-1,
                    flags=flags, name_len=len(name_b), data_len=len(raw),
                )
                self._names.add(name)
                self._cache.put(name, value)
            self._tick(len(mapping))

    # ── Maintenance ───────────────────────────────────────────────────────────

    def pin(self, name: str):
        with self._lock:
            entry = self._index.get(name)
            if entry is None or not entry.alive:
                raise KeyError(name)
            entry.flags |= FLAG_PINNED
            self._fh.seek(entry.offset + _REC_FLAGS_OFFSET)
            self._fh.write(bytes([entry.flags]))
            self._idx_dirty = True

    def list_keys(self) -> list[str]:
        with self._lock:
            return list(self._names)

    def stats(self) -> dict:
        with self._lock:
            # Une seule passe sur les valeurs de l'index
            alive = pinned = aposets = dead = 0
            for e in self._index.values():
                if e.alive:
                    alive += 1
                    if e.pinned:    pinned  += 1
                    if e.is_aposet: aposets += 1
                else:
                    dead += 1
            total = alive + dead
            frag  = dead / total if total else 0.0
            fsize = os.path.getsize(self._path)
            return {
                "path":           self._path,
                "file_bytes":     fsize,
                "log_bytes":      self._next_write,
                "visit_ctr":      self._visit_ctr,
                "keys_alive":     alive,
                "keys_dead":      dead,
                "keys_pinned":    pinned,
                "keys_aposet":    aposets,
                "fragmentation":  f"{frag:.1%}",
                "maint_every":    self._maint_every,
                "cache_size":     len(self._cache._d),
                "cache_hit_rate": f"{self._cache.hit_rate:.1%}",
                "idx_embedded":   True,
                "idx_offset":     self._idx_offset,
            }

    def _maintenance(self):
        # 1. Expiration des aposets
        to_kill = [
            (k, e) for k, e in self._index.items()
            if e.alive and self._is_expired(e)
        ]
        for name, entry in to_kill:
            self._kill_entry(name, entry)

        # 2. Décroissance des scores de visite
        for entry in self._index.values():
            if entry.alive and not entry.pinned:
                entry.visit_cnt = max(0.0, entry.visit_cnt / VISIT_DECAY_FACTOR)
                self._update_visit_on_disk(entry.offset, entry.visit_cnt)

        # 3. Compaction
        self._compact()

        # 4. Flush
        self._flush()

    def _compact(self):
        """Réécrit le fichier en ne gardant que les records vivants,
        triés par (pinned desc, visit_cnt desc).
        Lit toutes les data avant de tronquer → pas de seek aller-retour."""
        alive_entries = [
            (name, entry) for name, entry in self._index.items()
            if entry.alive
        ]
        alive_entries.sort(key=lambda x: (not x[1].pinned, -x[1].visit_cnt))

        # Lecture de toutes les data EN AVANCE (avant truncate)
        records: list[tuple[bytes, bytes, HiveEntry]] = []
        for name, entry in alive_entries:
            name_b = name.encode("utf-8")
            raw    = self._read_raw_at(entry)
            records.append((name_b, raw, entry))

        # Maintenant on peut tronquer et réécrire
        self._fh.seek(HEADER_SIZE)
        self._fh.truncate()
        self._next_write = HEADER_SIZE
        self._idx_offset = 0
        self._idx_size   = 0

        new_index: dict[str, HiveEntry] = {}
        for name_b, raw, entry in records:
            name   = name_b.decode("utf-8")
            offset = self._append_record(
                name_b, raw,
                flags=entry.flags,
                visit_cnt=entry.visit_cnt,
                death_idx=entry.death_idx,
            )
            new_index[name] = HiveEntry(
                offset=offset,
                visit_cnt=entry.visit_cnt,
                death_idx=entry.death_idx,
                flags=entry.flags,
                name_len=len(name_b),
                data_len=len(raw),
            )

        self._index = new_index
        self._names = {k for k, e in self._index.items() if e.alive}
        self._cache.clear()
        self._idx_dirty = True

    # ── Interface dict-like ───────────────────────────────────────────────────

    def __getitem__(self, name: str) -> Any:
        val = self.get(name, _SENTINEL)
        if val is _SENTINEL:
            raise KeyError(name)
        return val

    def __setitem__(self, name: str, value: Any):
        self.set(name, value)

    def __delitem__(self, name: str):
        if not self.delete(name):
            raise KeyError(name)

    def __contains__(self, name: str) -> bool:
        return self.exists(name)

    def __iter__(self):
        return iter(self.list_keys())

    def __len__(self) -> int:
        return len(self._names)

    def __repr__(self) -> str:
        s = self.stats()
        return (
            f"<Hive '{self._path}' "
            f"alive={s['keys_alive']} dead={s['keys_dead']} "
            f"frag={s['fragmentation']} bytes={s['file_bytes']} "
            f"visits={s['visit_ctr']} cache={s['cache_hit_rate']}>"
        )


# ─── Alias R-ECO ─────────────────────────────────────────────────────────────

HiveFS = Hive


# ─── Démonstration ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import glob

    for f in glob.glob("demo.hive*"):
        os.remove(f)

    print("=== Hive v2.1 — fichier unique, index embarqué ===\n")

    with Hive("demo.hive", maint_every=1000) as h:
        h["message"] = "hello world"
        h["pi"]      = 3.14
        h["count"]   = 42
        h["active"]  = True
        h["nothing"] = None
        h["data"]    = b"\xff\xfe\xfd"   # bytes bruts — nouveau type supporté

        print("=== Lecture individuelle ===")
        for k in ("message", "pi", "count", "active", "nothing", "data"):
            print(f"  {k:10s}: {h[k]!r:20}  type={h.type(k).__name__}")

        print("\n=== Batch get / set ===")
        h.set_many({"x": 10, "y": 20, "z": 30})
        batch = h.get_many(["x", "y", "z", "missing"])
        print(f"  get_many → {batch}")

        print("\n=== Assertions types ===")
        assert h["pi"]     == 3.14,        "float KO"
        assert h["count"]  == 42,          "int KO"
        assert h["active"] is True,        "bool KO"
        assert h["nothing"] is None,       "None KO"
        assert h["data"]   == b"\xff\xfe\xfd", "bytes KO"
        assert type(h["pi"])     is float
        assert type(h["count"])  is int
        assert type(h["active"]) is bool
        print("  Tous les types sont corrects ✓")

        print("\n=== delete() retourne bool ===")
        h["tmp"] = "temporaire"
        assert h.delete("tmp")      is True,  "delete existant KO"
        assert h.delete("tmp")      is False, "delete absent KO"
        assert h.delete("fantôme")  is False, "delete inconnu KO"
        print("  delete() bool ✓")

        print("\n=== Un seul fichier sur disque ===")
        files = glob.glob("demo.hive*")
        assert files == ["demo.hive"], f"Attendu 1 fichier, trouvé : {files}"
        print("  ✓ Un seul fichier .hive")

        print("\n=== Stats ===")
        for k, v in h.stats().items():
            print(f"  {k:20s}: {v}")

    print("\n=== Réouverture + vérif persistance ===")
    with Hive("demo.hive") as h2:
        assert h2["pi"]    == 3.14
        assert h2["count"] == 42
        assert h2["x"]     == 10
        assert h2["data"]  == b"\xff\xfe\xfd"
        print(f"  pi={h2['pi']}  count={h2['count']}  x={h2['x']}  data={h2['data']!r}  ✓")
        print(f"  {h2}")

    for f in glob.glob("demo.hive*"):
        os.remove(f)
    print("\n=== Nettoyage OK ===")


# ══════════════════════════════════════════════════════════════════════════════
#  Interface module R-ECO3
# ══════════════════════════════════════════════════════════════════════════════

def R_ECO3(args: str, log_fn=print):
    log_fn("HIVE > Hive est un module L1 (infrastructure, pas d'API REPL directe)")

def R_ECO3dep():
    return {"reco": ["3.5.2b"], "module": []}

def R_ECO3inf():
    return {
        "name":        "hive",
        "desc":        "HiveFS — store KV persistant, fichier unique, index embarqué",
        "help":        "",
        "version_mod": "2.1",
        "L2Module":    False,
    }