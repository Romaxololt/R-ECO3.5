#!/usr/bin/env python3
"""
HiveFS - Ultra-performant single-file storage system
Hybrid: filesystem + key-value store + append-only engine
"""

import os
import struct
import threading
import time
import zlib
from typing import Optional, List, Dict, Tuple, Union
from pathlib import Path
from collections import OrderedDict
from dataclasses import dataclass
from enum import IntFlag

try:
    import lz4.frame
    HAS_LZ4 = True
except ImportError:
    HAS_LZ4 = False

try:
    import xxhash
    HAS_XXHASH = True
except ImportError:
    HAS_XXHASH = False


# ============================================================================
# CONSTANTS
# ============================================================================

MAGIC = b'HIVE'
VERSION = 1
SUPERBLOCK_SIZE = 4096
ENTRY_HEADER_SIZE = 48

# Type markers (1 byte)
TYPE_BYTES = b'\x00'
TYPE_STR   = b'\x01'
TYPE_INT   = b'\x02'
TYPE_FLOAT = b'\x03'


class EntryFlags(IntFlag):
    ACTIVE     = 0x00
    DELETED    = 0x01
    COMPRESSED = 0x02


# ============================================================================
# HASHING
# ============================================================================

def fast_hash(data: bytes) -> int:
    if HAS_XXHASH:
        return xxhash.xxh64(data).intdigest()
    return zlib.crc32(data) & 0xFFFFFFFFFFFFFFFF


def checksum(data: bytes) -> int:
    return zlib.crc32(data) & 0xFFFFFFFF


# ============================================================================
# DATA STRUCTURES
# ============================================================================

@dataclass
class Entry:
    key_hash: int
    timestamp: int
    offset: int
    size: int
    flags: int
    checksum: int

    def pack(self) -> bytes:
        return struct.pack('<QQQQQII',
                          self.key_hash,
                          self.timestamp,
                          self.offset,
                          self.size,
                          self.flags,
                          self.checksum,
                          0)  # padding

    @staticmethod
    def unpack(data: bytes) -> 'Entry':
        if len(data) < ENTRY_HEADER_SIZE:
            raise ValueError(f"Invalid entry data: expected {ENTRY_HEADER_SIZE} bytes, got {len(data)}")
        key_hash, timestamp, offset, size, flags, cksum, _ = struct.unpack('<QQQQQII', data[:ENTRY_HEADER_SIZE])
        return Entry(key_hash, timestamp, offset, size, flags, cksum)


@dataclass
class Superblock:
    magic: bytes
    version: int
    data_offset: int
    num_entries: int
    gc_count: int

    def pack(self) -> bytes:
        data = struct.pack('<4sIQQQ',
                          self.magic,
                          self.version,
                          self.data_offset,
                          self.num_entries,
                          self.gc_count)
        return data + b'\x00' * (SUPERBLOCK_SIZE - len(data))

    @staticmethod
    def unpack(data: bytes) -> 'Superblock':
        if len(data) < 32:
            raise ValueError(f"Invalid superblock: expected at least 32 bytes, got {len(data)}")
        magic, version, data_offset, num_entries, gc_count = struct.unpack('<4sIQQQ', data[:32])
        return Superblock(magic, version, data_offset, num_entries, gc_count)


# ============================================================================
# LRU CACHE
# ============================================================================

class LRUCache:
    def __init__(self, capacity: int = 1000):
        self.cache: OrderedDict = OrderedDict()
        self.capacity = capacity
        self.lock = threading.Lock()

    def get(self, key: int) -> Optional[bytes]:
        with self.lock:
            if key not in self.cache:
                return None
            self.cache.move_to_end(key)
            return self.cache[key]

    def put(self, key: int, value: bytes):
        with self.lock:
            if key in self.cache:
                self.cache.move_to_end(key)
            self.cache[key] = value
            if len(self.cache) > self.capacity:
                self.cache.popitem(last=False)

    def invalidate(self, key: int):
        with self.lock:
            self.cache.pop(key, None)

    def clear(self):
        with self.lock:
            self.cache.clear()


# ============================================================================
# HIVEFS MAIN CLASS
# ============================================================================

class HiveFS:
    """Ultra-performant single-file storage system"""

    def __init__(self, filepath: str = 'database.hive', cache_size: int = 1000,
                 auto_recover: bool = True):
        self.filepath = Path(filepath)
        self.auto_recover = auto_recover
        self.index: Dict[int, Entry] = {}
        self.key_map: Dict[int, str] = {}
        # dedup_index: content_hash -> (offset, refcount)
        # content_hash is computed on the *prefixed* data_bytes (after key prefix is added),
        # so two keys with the same value but different key names will never collide.
        self.dedup_index: Dict[int, Tuple[int, int]] = {}
        self.cache = LRUCache(cache_size)

        # FIX #3 / #7: use RLock for write_lock so compact() called from set() doesn't deadlock.
        # read_lock stays RLock for symmetry (nested reads are fine).
        self.read_lock = threading.RLock()
        self.write_lock = threading.RLock()

        self.file = None

        self.stats_reads = 0
        self.stats_writes = 0
        self.stats_cache_hits = 0
        self.stats_cache_misses = 0

        # Tracks gc_count so compact() can increment it properly (FIX #16)
        self._gc_count = 0

        # Flag used to trigger compaction outside the write-path hot spot
        self._compact_pending = False

        self._initialize()

    # -------------------------------------------------------------------------
    # TYPE SERIALIZATION
    # -------------------------------------------------------------------------

    def _to_bytes(self, data: Union[str, bytes, int, float]) -> bytes:
        if isinstance(data, bytes):
            return TYPE_BYTES + data
        elif isinstance(data, str):
            return TYPE_STR + data.encode('utf-8')
        elif isinstance(data, int):
            return TYPE_INT + str(data).encode('utf-8')
        elif isinstance(data, float):
            return TYPE_FLOAT + str(data).encode('utf-8')
        raise TypeError(f"Cannot convert {type(data)} to bytes")

    def _from_bytes(self, data: bytes, as_str: bool = False) -> Union[bytes, str, int, float]:
        if len(data) < 1:
            return data
        marker = data[:1]
        payload = data[1:]
        if marker == TYPE_INT:
            return int(payload.decode('utf-8'))
        elif marker == TYPE_FLOAT:
            return float(payload.decode('utf-8'))
        elif marker == TYPE_STR:
            return payload.decode('utf-8')
        elif marker == TYPE_BYTES:
            return payload
        # Legacy file without marker → fallback
        return data.decode('utf-8') if as_str else data

    # -------------------------------------------------------------------------
    # INITIALIZATION
    # -------------------------------------------------------------------------

    def _initialize(self):
        if self.filepath.exists():
            try:
                self._load_existing()
            except (ValueError, struct.error, OSError) as e:
                if self.auto_recover:
                    print(f"Warning: Invalid HiveFS file ({e}). Auto-recovering…")
                    self._recover_from_corruption()
                else:
                    raise ValueError(
                        f"Invalid HiveFS file: {e}\n"
                        f"Set auto_recover=True to recover automatically, or delete {self.filepath}"
                    )
        else:
            self._create_new()

    def _recover_from_corruption(self):
        if self.filepath.exists() and self.filepath.stat().st_size > 0:
            import shutil
            backup_path = self.filepath.with_suffix(f'.corrupted.{int(time.time())}.bak')
            shutil.copy2(self.filepath, backup_path)
        if self.filepath.exists():
            self.filepath.unlink()
        self._create_new()

    def _create_new(self):
        superblock = Superblock(
            magic=MAGIC, version=VERSION,
            data_offset=SUPERBLOCK_SIZE, num_entries=0, gc_count=0
        )
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(self.filepath, 'wb') as f:
            f.write(superblock.pack())
        self._open_file()

    def _load_existing(self):
        self._open_file()
        self.file.seek(0)
        sb_data = self.file.read(SUPERBLOCK_SIZE)
        if len(sb_data) < SUPERBLOCK_SIZE:
            raise ValueError(f"File too small: expected {SUPERBLOCK_SIZE} bytes")
        superblock = Superblock.unpack(sb_data)
        if superblock.magic != MAGIC:
            raise ValueError(f"Invalid magic: expected {MAGIC!r}, got {superblock.magic!r}")
        if superblock.version != VERSION:
            raise ValueError(f"Unsupported version: {superblock.version}")
        self._gc_count = superblock.gc_count
        self._rebuild_index()

    def _open_file(self):
        if self.file is not None:
            try:
                self.file.close()
            except Exception:
                pass
        self.file = open(self.filepath, 'r+b', buffering=65536)

    # -------------------------------------------------------------------------
    # INDEX REBUILD
    # FIX #11: skip truncated entries using CRC instead of crashing
    # -------------------------------------------------------------------------

    def _rebuild_index(self):
        self.index.clear()
        self.key_map.clear()
        self.dedup_index.clear()

        self.file.seek(SUPERBLOCK_SIZE)
        consecutive_errors = 0

        while True:
            pos = self.file.tell()
            header_data = self.file.read(ENTRY_HEADER_SIZE)
            if len(header_data) < ENTRY_HEADER_SIZE:
                break  # clean EOF

            try:
                entry = Entry.unpack(header_data)
            except (struct.error, ValueError):
                consecutive_errors += 1
                if consecutive_errors > 10:
                    print(f"Warning: Too many header errors; stopping rebuild at offset {pos}")
                    break
                continue

            consecutive_errors = 0

            # Read payload — FIX #11: if payload is truncated, skip the entry
            data = self.file.read(entry.size)
            if len(data) < entry.size:
                print(f"Warning: Truncated entry at offset {pos} (expected {entry.size} B, got {len(data)} B); skipping")
                break

            # Verify checksum — skip corrupted entries
            if entry.size > 0 and checksum(data) != entry.checksum:
                print(f"Warning: Checksum mismatch at offset {pos}; skipping entry")
                continue

            if entry.flags & EntryFlags.DELETED:
                self.index.pop(entry.key_hash, None)
                self.key_map.pop(entry.key_hash, None)
            else:
                self.index[entry.key_hash] = entry

                # Reconstruct key_map from the embedded key prefix
                if len(data) >= 2:
                    key_len = struct.unpack('<H', data[:2])[0]
                    if len(data) >= 2 + key_len:
                        self.key_map[entry.key_hash] = data[2:2 + key_len].decode('utf-8', errors='replace')

                # FIX #2: content_hash is computed on the full prefixed blob (already done here
                # since `data` is the stored bytes which include the key prefix).
                if entry.size > 0:
                    content_hash = fast_hash(data)
                    if content_hash in self.dedup_index:
                        off, refcount = self.dedup_index[content_hash]
                        self.dedup_index[content_hash] = (off, refcount + 1)
                    else:
                        self.dedup_index[content_hash] = (entry.offset, 1)

    # -------------------------------------------------------------------------
    # COMPRESSION
    # FIX #13: use zlib level=6 as fallback (not level=1)
    # -------------------------------------------------------------------------

    def _compress(self, data: bytes) -> Tuple[bytes, bool]:
        if len(data) < 128:
            return data, False
        try:
            if HAS_LZ4:
                compressed = lz4.frame.compress(data)
            else:
                compressed = zlib.compress(data, level=6)
            if len(compressed) < len(data) * 0.9:
                return compressed, True
            return data, False
        except Exception:
            return data, False

    def _decompress(self, data: bytes, is_compressed: bool) -> bytes:
        if not is_compressed:
            return data
        try:
            if HAS_LZ4:
                return lz4.frame.decompress(data)
            return zlib.decompress(data)
        except Exception as e:
            raise ValueError(f"Decompression failed: {e}")

    # -------------------------------------------------------------------------
    # WRITE
    # FIX #1: fsync removed from hot path
    # FIX #2: content_hash computed on fully prefixed data_bytes
    # FIX #6: dedup_index actually used to skip duplicate writes
    # FIX #7: write_lock is now RLock; auto-compact is safe
    # -------------------------------------------------------------------------

    def set(self, key: str, data: Union[str, bytes, int, float]) -> None:
        data_bytes = self._to_bytes(data)

        # Prefix with key: 2 bytes (length) + key bytes
        key_encoded = key.encode('utf-8')
        data_bytes = struct.pack('<H', len(key_encoded)) + key_encoded + data_bytes

        key_hash = fast_hash(key.encode('utf-8'))

        with self.write_lock:
            # FIX #2 / #6: hash the fully prefixed bytes so identical payloads
            # for *different* keys don't collide in dedup_index.
            content_hash = fast_hash(data_bytes)

            # FIX #6: if this exact content is already stored, reuse its offset.
            if content_hash in self.dedup_index:
                existing_offset, refcount = self.dedup_index[content_hash]
                # Find the entry that lives at that offset to clone its metadata.
                existing_entry = next(
                    (e for e in self.index.values() if e.offset == existing_offset),
                    None
                )
                if existing_entry is not None:
                    # Write a new header pointing to the existing data block.
                    self.file.seek(0, os.SEEK_END)
                    new_entry = Entry(
                        key_hash=key_hash,
                        timestamp=int(time.time() * 1000000),
                        offset=existing_entry.offset,
                        size=existing_entry.size,
                        flags=existing_entry.flags,
                        checksum=existing_entry.checksum,
                    )
                    self.file.write(new_entry.pack())
                    # No data written — dedup! Update refcount.
                    self.dedup_index[content_hash] = (existing_offset, refcount + 1)
                    self.index[key_hash] = new_entry
                    self.key_map[key_hash] = key
                    self.cache.invalidate(key_hash)
                    self.stats_writes += 1
                    self._maybe_update_superblock_and_compact()
                    return

            stored_data, is_compressed = self._compress(data_bytes)
            flags = EntryFlags.ACTIVE
            if is_compressed:
                flags |= EntryFlags.COMPRESSED

            self.file.seek(0, os.SEEK_END)
            data_offset = self.file.tell()

            entry = Entry(
                key_hash=key_hash,
                timestamp=int(time.time() * 1000000),
                offset=data_offset + ENTRY_HEADER_SIZE,
                size=len(stored_data),
                flags=flags,
                checksum=checksum(stored_data),
            )

            self.file.write(entry.pack())
            self.file.write(stored_data)
            # FIX #1: flush() without fsync() in the hot path; fsync only in close()/compact()
            self.file.flush()

            self.index[key_hash] = entry
            self.key_map[key_hash] = key

            self.dedup_index[content_hash] = (entry.offset, 1)

            self.cache.invalidate(key_hash)
            self.stats_writes += 1

            self._maybe_update_superblock_and_compact()

    def _maybe_update_superblock_and_compact(self):
        """Called inside write_lock. Because write_lock is RLock, compact() is safe to call here."""
        if self.stats_writes % 10 == 0:
            self._update_superblock()
            s = self.stats()
            if s['garbage_ratio'] > 0.4:
                self.compact()

    # -------------------------------------------------------------------------
    # READ
    # -------------------------------------------------------------------------

    def get(self, key: str, default=None, as_str: bool = False) -> Optional[Union[bytes, str]]:
        key_hash = fast_hash(key.encode('utf-8'))

        cached = self.cache.get(key_hash)
        if cached is not None:
            self.stats_cache_hits += 1
            self.stats_reads += 1
            return self._from_bytes(cached, as_str)

        self.stats_cache_misses += 1

        with self.read_lock:
            entry = self.index.get(key_hash)
            if entry is None:
                return default

            try:
                self.file.seek(entry.offset)
                data = self.file.read(entry.size)
                if len(data) < entry.size:
                    raise ValueError(f"Incomplete read: expected {entry.size} bytes, got {len(data)}")
            except OSError as e:
                raise ValueError(f"Failed to read data: {e}")

            if checksum(data) != entry.checksum:
                raise ValueError("Data corruption detected: checksum mismatch")

            data = self._decompress(data, bool(entry.flags & EntryFlags.COMPRESSED))

            # Strip key prefix
            key_len = struct.unpack('<H', data[:2])[0]
            data = data[2 + key_len:]

            self.cache.put(key_hash, data)
            self.stats_reads += 1
            return self._from_bytes(data, as_str)

    # -------------------------------------------------------------------------
    # DELETE
    # -------------------------------------------------------------------------

    def delete(self, key: str) -> bool:
        key_hash = fast_hash(key.encode('utf-8'))

        with self.write_lock:
            if key_hash not in self.index:
                return False

            self.file.seek(0, os.SEEK_END)
            data_offset = self.file.tell()

            entry = Entry(
                key_hash=key_hash,
                timestamp=int(time.time() * 1000000),
                offset=data_offset + ENTRY_HEADER_SIZE,
                size=0,
                flags=EntryFlags.DELETED,
                checksum=0,
            )

            self.file.write(entry.pack())
            self.file.flush()

            del self.index[key_hash]
            self.key_map.pop(key_hash, None)
            self.cache.invalidate(key_hash)
            self._update_superblock()
            return True

    # -------------------------------------------------------------------------
    # EXISTENCE / DICT-LIKE API
    # -------------------------------------------------------------------------

    def exists(self, key: str) -> bool:
        key_hash = fast_hash(key.encode('utf-8'))
        return key_hash in self.index

    def __contains__(self, key: str) -> bool:
        return self.exists(key)

    def __getitem__(self, key: str):
        result = self.get(key)
        if result is None:
            raise KeyError(key)
        return result

    def __setitem__(self, key: str, value: Union[str, bytes, int, float]):
        self.set(key, value)

    def __delitem__(self, key: str):
        if not self.delete(key):
            raise KeyError(key)

    def list(self) -> List[str]:
        with self.read_lock:
            return list(self.key_map.values())

    def keys(self) -> List[str]:
        return self.list()

    # -------------------------------------------------------------------------
    # SUPERBLOCK
    # -------------------------------------------------------------------------

    def _update_superblock(self):
        try:
            superblock = Superblock(
                magic=MAGIC,
                version=VERSION,
                data_offset=SUPERBLOCK_SIZE,
                num_entries=len(self.index),
                gc_count=self._gc_count,
            )
            self.file.seek(0)
            self.file.write(superblock.pack())
            self.file.flush()
        except OSError as e:
            print(f"Warning: Failed to update superblock: {e}")

    # -------------------------------------------------------------------------
    # COMPACTION
    # FIX #3: acquire both read_lock and write_lock
    # FIX #4: key_map explicitly rebuilt after compaction
    # FIX #16: gc_count incremented
    # -------------------------------------------------------------------------

    def compact(self) -> Dict[str, int]:
        # FIX #3: hold write_lock *and* read_lock so no concurrent get() can
        # race against the os.replace() / file reopen sequence.
        with self.write_lock:
            with self.read_lock:
                return self._do_compact()

    def _do_compact(self) -> Dict[str, int]:
        old_size = self.filepath.stat().st_size
        temp_path = self.filepath.with_suffix('.tmp')

        self._gc_count += 1  # FIX #16

        superblock = Superblock(
            magic=MAGIC,
            version=VERSION,
            data_offset=SUPERBLOCK_SIZE,
            num_entries=len(self.index),
            gc_count=self._gc_count,
        )

        entries_copied = 0
        new_index: Dict[int, Entry] = {}
        new_key_map: Dict[int, str] = {}  # FIX #4

        try:
            with open(temp_path, 'wb') as new_file:
                new_file.write(superblock.pack())

                for key_hash, entry in self.index.items():
                    try:
                        self.file.seek(entry.offset)
                        data = self.file.read(entry.size)
                        if len(data) < entry.size:
                            print(f"Warning: Skipping incomplete entry for key '{self.key_map.get(key_hash, hex(key_hash))}'")
                            continue
                        if checksum(data) != entry.checksum:
                            print(f"Warning: Skipping corrupted entry for key '{self.key_map.get(key_hash, hex(key_hash))}'")
                            continue

                        new_offset = new_file.tell()
                        new_entry = Entry(
                            key_hash=entry.key_hash,
                            timestamp=entry.timestamp,
                            offset=new_offset + ENTRY_HEADER_SIZE,
                            size=entry.size,
                            flags=entry.flags,
                            checksum=entry.checksum,
                        )
                        new_file.write(new_entry.pack())
                        new_file.write(data)

                        new_index[key_hash] = new_entry
                        if key_hash in self.key_map:
                            new_key_map[key_hash] = self.key_map[key_hash]  # FIX #4
                        entries_copied += 1

                    except Exception as e:
                        print(f"Warning: Error copying entry: {e}")
                        continue

                new_file.flush()
                os.fsync(new_file.fileno())

            self.file.close()
            os.replace(temp_path, self.filepath)
            self._open_file()

            self.index = new_index
            self.key_map = new_key_map  # FIX #4: replace entirely (no stale keys)
            self.cache.clear()
            self.dedup_index.clear()

            new_size = self.filepath.stat().st_size

            return {
                'entries_copied': entries_copied,
                'old_size': old_size,
                'new_size': new_size,
                'saved_bytes': old_size - new_size,
                'compression_ratio': new_size / old_size if old_size > 0 else 1.0,
            }

        except Exception as e:
            if temp_path.exists():
                temp_path.unlink()
            raise RuntimeError(f"Compaction failed: {e}")

    def gc(self) -> Dict[str, int]:
        return self.compact()

    # -------------------------------------------------------------------------
    # STATS
    # FIX #8: garbage_ratio uses (file_size - SUPERBLOCK_SIZE) as denominator
    # -------------------------------------------------------------------------

    def stats(self) -> Dict:
        with self.read_lock:
            file_size = self.filepath.stat().st_size if self.filepath.exists() else 0
            live_entries = len(self.index)

            cache_hit_rate = 0.0
            if self.stats_reads > 0:
                cache_hit_rate = self.stats_cache_hits / self.stats_reads

            live_size = sum(entry.size + ENTRY_HEADER_SIZE for entry in self.index.values())
            data_region = max(0, file_size - SUPERBLOCK_SIZE)
            garbage_size = max(0, data_region - live_size)

            # FIX #8: ratio relative to the data region, not the whole file
            garbage_ratio = garbage_size / data_region if data_region > 0 else 0.0

            return {
                'file_size': file_size,
                'live_entries': live_entries,
                'live_size': live_size,
                'garbage_size': garbage_size,
                'garbage_ratio': garbage_ratio,
                'total_reads': self.stats_reads,
                'total_writes': self.stats_writes,
                'cache_hits': self.stats_cache_hits,
                'cache_misses': self.stats_cache_misses,
                'cache_hit_rate': cache_hit_rate,
                'cache_size': len(self.cache.cache),
                'dedup_entries': len(self.dedup_index),
                'gc_count': self._gc_count,
            }

    # -------------------------------------------------------------------------
    # VERIFY
    # FIX #14: display real key strings instead of raw hashes
    # -------------------------------------------------------------------------

    def verify(self) -> Tuple[bool, List[str]]:
        errors = []

        with self.read_lock:
            for key_hash, entry in self.index.items():
                key_label = self.key_map.get(key_hash, hex(key_hash))  # FIX #14
                try:
                    self.file.seek(entry.offset)
                    data = self.file.read(entry.size)

                    if len(data) < entry.size:
                        errors.append(f"Incomplete data for key '{key_label}'")
                        continue

                    if checksum(data) != entry.checksum:
                        errors.append(f"Checksum mismatch for key '{key_label}'")

                except Exception as e:
                    errors.append(f"Error verifying key '{key_label}': {e}")

        return (len(errors) == 0, errors)

    # -------------------------------------------------------------------------
    # BACKUP / CLOSE / CONTEXT MANAGER
    # -------------------------------------------------------------------------

    def backup(self, backup_path: str) -> None:
        import shutil
        with self.read_lock:
            if self.file:
                self.file.flush()
                os.fsync(self.file.fileno())
            shutil.copy2(self.filepath, backup_path)

    def flush(self, force: bool = False) -> None:
        """Flush write buffer. Pass force=True to also fsync to disk."""
        with self.write_lock:
            if self.file:
                self.file.flush()
                if force:
                    os.fsync(self.file.fileno())

    def close(self):
        if self.file is not None:
            try:
                self._update_superblock()
                self.file.flush()
                os.fsync(self.file.fileno())
                self.file.close()
            except Exception:
                pass
            finally:
                self.file = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    # FIX #5: __del__ guarded so it never crashes during interpreter teardown
    def __del__(self):
        try:
            if self.file is not None:
                self.close()
        except Exception:
            pass


# Alias kept for internal use (no public backward-compat needed per spec)
FlatKV = HiveFS


# ============================================================================
# R-ECO3 MODULE INTERFACE
# FIX #15: R_ECO3() now exposes set/get/list/stats/compact commands
# ============================================================================

def R_ECO3(args: str, log_fn=print):
    """
    HiveFS shell interface for RAVEN.

    Commands:
      set <key> <value>   — store a value
      get <key>           — retrieve a value
      del <key>           — delete a key
      list                — list all keys
      stats               — show statistics
      compact / gc        — run garbage collection
      verify              — check data integrity
    """
    import shlex
    try:
        tokens = shlex.split(args.strip())
    except ValueError as e:
        log_fn(f"[hive] Parse error: {e}")
        return 1

    if not tokens:
        log_fn(__doc__.strip())
        return 0

    # Lazy-import trail to locate the database (mirrors the rest of the ecosystem)
    try:
        import core.trail as trail
        db_path = str(trail.DB_FILE)
    except Exception:
        db_path = 'data/data.hive'

    cmd = tokens[0].lower()

    try:
        with HiveFS(db_path) as db:
            if cmd == 'set':
                if len(tokens) < 3:
                    log_fn("[hive] Usage: set <key> <value>")
                    return 1
                db.set(tokens[1], tokens[2])
                log_fn(f"[hive] OK: '{tokens[1]}' stored")
                return 0

            elif cmd == 'get':
                if len(tokens) < 2:
                    log_fn("[hive] Usage: get <key>")
                    return 1
                value = db.get(tokens[1])
                if value is None:
                    log_fn(f"[hive] Key not found: '{tokens[1]}'")
                    return 1
                log_fn(str(value))
                return 0

            elif cmd == 'del':
                if len(tokens) < 2:
                    log_fn("[hive] Usage: del <key>")
                    return 1
                if db.delete(tokens[1]):
                    log_fn(f"[hive] OK: '{tokens[1]}' deleted")
                    return 0
                log_fn(f"[hive] Key not found: '{tokens[1]}'")
                return 1

            elif cmd == 'list':
                keys = db.list()
                if not keys:
                    log_fn("[hive] (no keys)")
                else:
                    for k in keys:
                        log_fn(k)
                return 0

            elif cmd == 'stats':
                s = db.stats()
                for k, v in s.items():
                    log_fn(f"  {k}: {v}")
                return 0

            elif cmd in ('compact', 'gc'):
                result = db.compact()
                log_fn(f"[hive] Compaction done: {result}")
                return 0

            elif cmd == 'verify':
                ok, errors = db.verify()
                if ok:
                    log_fn("[hive] Database integrity: OK")
                else:
                    for err in errors:
                        log_fn(f"[hive] ERROR: {err}")
                return 0 if ok else 1

            else:
                log_fn(f"[hive] Unknown command: '{cmd}'. Try: set get del list stats compact verify")
                return 1

    except Exception as e:
        log_fn(f"[hive] Error: {e}")
        return 1


def R_ECO3dep():
    return (("3.5.1b",), (("core.trail", ("1.1",)),))


def R_ECO3inf():
    return {
        "name": "hive",
        "desc": "HiveFS key-value database (set/get/del/list/stats/compact/verify)",
        "help": "hive set <key> <value> | get <key> | del <key> | list | stats | compact | verify",
        "version_mod": "1.2",
        "L2Module": True,
        "alias_rules": "/* = hive ||| * = hive /*",
    }