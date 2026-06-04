#!/usr/bin/env python3
"""
HiveFS - Ultra-performant single-file storage system
Hybrid: filesystem + key-value store + append-only engine
OPTIMIZED VERSION with auto-recovery and type conversion
"""

import os
import mmap
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
ENTRY_HEADER_SIZE = 48  # struct format size

# Type markers (1 octet)
TYPE_BYTES = b'\x00'
TYPE_STR   = b'\x01'
TYPE_INT   = b'\x02'
TYPE_FLOAT = b'\x03'

# Flags
class EntryFlags(IntFlag):
    ACTIVE = 0x00
    DELETED = 0x01
    COMPRESSED = 0x02


# ============================================================================
# HASHING
# ============================================================================

def fast_hash(data: bytes) -> int:
    """Fast hash using xxhash if available, fallback to builtin hash"""
    if HAS_XXHASH:
        return xxhash.xxh64(data).intdigest()
    else:
        # Fallback to zlib.crc32 for deterministic hashing
        return zlib.crc32(data) & 0xFFFFFFFFFFFFFFFF


def checksum(data: bytes) -> int:
    """Compute checksum for data integrity"""
    return zlib.crc32(data) & 0xFFFFFFFF


# ============================================================================
# DATA STRUCTURES
# ============================================================================

@dataclass
class Entry:
    """Entry metadata"""
    key_hash: int
    timestamp: int
    offset: int
    size: int
    flags: int
    checksum: int
    
    def pack(self) -> bytes:
        """Pack entry to binary format"""
        # Format: Q Q Q Q I I (48 bytes)
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
        """Unpack entry from binary format"""
        if len(data) < ENTRY_HEADER_SIZE:
            raise ValueError(f"Invalid entry data: expected {ENTRY_HEADER_SIZE} bytes, got {len(data)}")
        key_hash, timestamp, offset, size, flags, cksum, _ = struct.unpack('<QQQQQII', data[:ENTRY_HEADER_SIZE])
        return Entry(key_hash, timestamp, offset, size, flags, cksum)


@dataclass
class Superblock:
    """File superblock metadata"""
    magic: bytes
    version: int
    data_offset: int
    num_entries: int
    gc_count: int
    
    def pack(self) -> bytes:
        """Pack superblock to binary"""
        data = struct.pack('<4sIQQQ', 
                          self.magic,
                          self.version,
                          self.data_offset,
                          self.num_entries,
                          self.gc_count)
        # Pad to SUPERBLOCK_SIZE
        return data + b'\x00' * (SUPERBLOCK_SIZE - len(data))
    
    @staticmethod
    def unpack(data: bytes) -> 'Superblock':
        """Unpack superblock from binary"""
        if len(data) < 32:
            raise ValueError(f"Invalid superblock data: expected at least 32 bytes, got {len(data)}")
        magic, version, data_offset, num_entries, gc_count = struct.unpack(
            '<4sIQQQ', data[:32])
        return Superblock(magic, version, data_offset, num_entries, gc_count)


# ============================================================================
# LRU CACHE
# ============================================================================

class LRUCache:
    """Simple LRU cache for get() operations"""
    
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
        """
        Initialize HiveFS
        
        Args:
            filepath: Path to database file
            cache_size: LRU cache capacity
            auto_recover: Automatically recover from corrupted files by recreating
        """
        self.filepath = Path(filepath)
        self.auto_recover = auto_recover
        self.index: Dict[int, Entry] = {}  # key_hash -> latest Entry
        self.key_map: Dict[int, str] = {}  # key_hash -> original key string  # ← AJOUT
        self.dedup_index: Dict[int, Tuple[int, int]] = {}  # content_hash -> (offset, refcount)
        self.cache = LRUCache(cache_size)
        
        # Locks
        self.read_lock = threading.RLock()
        self.write_lock = threading.Lock()
        
        # File handle
        self.file = None
        self.mmap_obj = None
        
        # Statistics
        self.stats_reads = 0
        self.stats_writes = 0
        self.stats_cache_hits = 0
        self.stats_cache_misses = 0
        
        # Initialize or load
        self._initialize()
    
    def _to_bytes(self, data: Union[str, bytes, int, float]) -> bytes:
        """Sérialise la donnée avec son type marker en préfixe"""
        if isinstance(data, bytes):
            return TYPE_BYTES + data
        elif isinstance(data, str):
            return TYPE_STR + data.encode('utf-8')
        elif isinstance(data, int):
            return TYPE_INT + str(data).encode('utf-8')
        elif isinstance(data, float):
            return TYPE_FLOAT + str(data).encode('utf-8')
        else:
            raise TypeError(f"Cannot convert {type(data)} to bytes")
    
    def _from_bytes(self, data: bytes, as_str: bool = False) -> Union[bytes, str, int, float]:
        """Désérialise la donnée selon son type marker"""
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
        else:
            # Fichier ancien sans marker → fallback
            return data.decode('utf-8') if as_str else data
    
    def _initialize(self):
        """Initialize or load existing database"""
        if self.filepath.exists():
            try:
                self._load_existing()
            except (ValueError, struct.error, OSError) as e:
                if self.auto_recover:
                    print(f"Warning: Invalid HiveFS file detected ({e})")
                    print(f"Auto-recovering: backing up and creating new database...")
                    self._recover_from_corruption()
                else:
                    raise ValueError(
                        f"Invalid HiveFS file: {e}\n"
                        f"Set auto_recover=True to automatically recover, or delete {self.filepath}"
                    )
        else:
            self._create_new()
    
    def _recover_from_corruption(self):
        """Recover from corrupted database by creating backup and new file"""
        # Create backup if file exists and has content
        if self.filepath.exists() and self.filepath.stat().st_size > 0:
            backup_path = self.filepath.with_suffix(f'.corrupted.{int(time.time())}.bak')
            import shutil
            shutil.copy2(self.filepath, backup_path)
        
        # Remove corrupted file
        if self.filepath.exists():
            self.filepath.unlink()
        
        # Create new database
        self._create_new()
    
    def _create_new(self):
        """Create new database file"""
        superblock = Superblock(
            magic=MAGIC,
            version=VERSION,
            data_offset=SUPERBLOCK_SIZE,
            num_entries=0,
            gc_count=0
        )
        
        # Ensure directory exists
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        
        with open(self.filepath, 'wb') as f:
            f.write(superblock.pack())
        
        self._open_file()
    
    def _load_existing(self):
        """Load existing database and rebuild index"""
        self._open_file()
        
        # Read superblock
        self.file.seek(0)
        sb_data = self.file.read(SUPERBLOCK_SIZE)
        
        if len(sb_data) < SUPERBLOCK_SIZE:
            raise ValueError(f"File too small: expected at least {SUPERBLOCK_SIZE} bytes")
        
        superblock = Superblock.unpack(sb_data)
        
        if superblock.magic != MAGIC:
            raise ValueError(f"Invalid magic header: expected {MAGIC}, got {superblock.magic}")
        
        if superblock.version != VERSION:
            raise ValueError(f"Unsupported version: {superblock.version}")
        
        # Rebuild index from file
        self._rebuild_index()
    
    def _open_file(self):
        """Open file handle"""
        if self.file is not None:
            self.file.close()
        self.file = open(self.filepath, 'r+b', buffering=65536)  # 64KB buffer
    
    def _rebuild_index(self):
        """Rebuild in-memory index from file (recovery)"""
        self.index.clear()
        self.dedup_index.clear()
        
        self.file.seek(SUPERBLOCK_SIZE)
        
        entries_processed = 0
        errors = 0
        
        while True:
            pos = self.file.tell()
            header_data = self.file.read(ENTRY_HEADER_SIZE)
            
            if len(header_data) < ENTRY_HEADER_SIZE:
                break
            
            try:
                entry = Entry.unpack(header_data)
            except (struct.error, ValueError) as e:
                errors += 1
                if errors > 10:  # Too many errors, stop
                    print(f"Warning: Stopped rebuilding index after {errors} errors")
                    break
                continue
            
            # Read actual data to verify checksum
            try:
                data = self.file.read(entry.size)
                if len(data) < entry.size:
                    break
            except OSError:
                break
            
            # Verify checksum
            if entry.size > 0 and checksum(data) != entry.checksum:
                print(f"Warning: Checksum mismatch at offset {pos}, skipping entry")
                continue
            
            # Update index with latest entry for each key
            if entry.flags & EntryFlags.DELETED:
                # Remove from index
                self.index.pop(entry.key_hash, None)
            else:
                # Update with latest version
                self.index[entry.key_hash] = entry
                
                # Reconstruire key_map depuis le préfixe
                if len(data) >= 2:
                    key_len = struct.unpack('<H', data[:2])[0]
                    if len(data) >= 2 + key_len:
                        self.key_map[entry.key_hash] = data[2:2 + key_len].decode('utf-8', errors='replace')  # ← AJOUT
                
                # Update dedup index
                if entry.size > 0:
                    content_hash = fast_hash(data)
                    if content_hash in self.dedup_index:
                        offset, refcount = self.dedup_index[content_hash]
                        self.dedup_index[content_hash] = (offset, refcount + 1)
                    else:
                        self.dedup_index[content_hash] = (entry.offset, 1)
            
            entries_processed += 1
    
    def _compress(self, data: bytes) -> Tuple[bytes, bool]:
        """Compress data if beneficial"""
        if len(data) < 128:
            return data, False
        
        try:
            if HAS_LZ4:
                compressed = lz4.frame.compress(data)
            else:
                compressed = zlib.compress(data, level=1)
            
            # Only use compression if it saves space
            if len(compressed) < len(data) * 0.9:
                return compressed, True
            else:
                return data, False
        except Exception:
            return data, False
    
    def _decompress(self, data: bytes, is_compressed: bool) -> bytes:
        """Decompress data if needed"""
        if not is_compressed:
            return data
        
        try:
            if HAS_LZ4:
                return lz4.frame.decompress(data)
            else:
                return zlib.decompress(data)
        except Exception as e:
            raise ValueError(f"Decompression failed: {e}")
    
    def set(self, key: str, data: Union[str, bytes, int, float]) -> None:
        """
        Store or update key-value pair
        Append-only: creates new entry, old becomes garbage
        
        Args:
            key: String key
            data: Value (will be auto-converted to bytes)
        """
        # Auto-convert to bytes
        data_bytes = self._to_bytes(data)

        # Préfixer avec la clé : 2 octets (longueur) + clé encodée
        key_encoded = key.encode('utf-8')
        data_bytes = struct.pack('<H', len(key_encoded)) + key_encoded + data_bytes
        
        key_hash = fast_hash(key.encode('utf-8'))
        
        with self.write_lock:
            # Check deduplication
            content_hash = fast_hash(data_bytes)
            
            # Compress if beneficial
            stored_data, is_compressed = self._compress(data_bytes)
            flags = EntryFlags.ACTIVE
            if is_compressed:
                flags |= EntryFlags.COMPRESSED
            
            # Append to file
            self.file.seek(0, os.SEEK_END)
            data_offset = self.file.tell()
            
            # Create entry
            entry = Entry(
                key_hash=key_hash,
                timestamp=int(time.time() * 1000000),  # microseconds
                offset=data_offset + ENTRY_HEADER_SIZE,
                size=len(stored_data),
                flags=flags,
                checksum=checksum(stored_data)
            )
            
            # Write entry header + data
            self.file.write(entry.pack())
            self.file.write(stored_data)
            self.file.flush()
            os.fsync(self.file.fileno())  # Ensure data is written to disk
            
            # Update index
            old_entry = self.index.get(key_hash)
            self.index[key_hash] = entry
            self.key_map[key_hash] = key  # ← AJOUT
            
            # Update dedup index
            if content_hash in self.dedup_index:
                offset, refcount = self.dedup_index[content_hash]
                self.dedup_index[content_hash] = (offset, refcount + 1)
            else:
                self.dedup_index[content_hash] = (entry.offset, 1)
            
            # Invalidate cache
            self.cache.invalidate(key_hash)
            
            self.stats_writes += 1
            
            # Update superblock periodically (every 10 writes)
            if self.stats_writes % 10 == 0:
                self._update_superblock()
                # Auto-compact si plus de 40% de garbage
                s = self.stats()
                if s['garbage_ratio'] > 0.4:
                    self.compact()
    
    def get(self, key: str, default=None, as_str: bool = False) -> Optional[Union[bytes, str]]:
        """
        Retrieve value for key
        
        Args:
            key: String key
            as_str: If True, decode bytes to string
            
        Returns:
            Value as bytes or string, or None if not found
        """
        key_hash = fast_hash(key.encode('utf-8'))
        
        # Check cache first
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
            
            # Read data from file
            try:
                self.file.seek(entry.offset)
                data = self.file.read(entry.size)
                
                if len(data) < entry.size:
                    raise ValueError(f"Incomplete read: expected {entry.size} bytes, got {len(data)}")
            except OSError as e:
                raise ValueError(f"Failed to read data: {e}")
            
            # Verify checksum
            if checksum(data) != entry.checksum:
                raise ValueError("Data corruption detected: checksum mismatch")
            
            data = self._decompress(data, bool(entry.flags & EntryFlags.COMPRESSED))

            # Extraire le préfixe clé avant de désérialiser
            key_len = struct.unpack('<H', data[:2])[0]
            data = data[2 + key_len:]  # ← AJOUT

            self.cache.put(key_hash, data)
            return self._from_bytes(data, as_str)
    
    def delete(self, key: str) -> bool:
        """
        Mark key as deleted (soft delete)
        
        Returns:
            True if key was deleted, False if key didn't exist
        """
        key_hash = fast_hash(key.encode('utf-8'))
        
        with self.write_lock:
            if key_hash not in self.index:
                return False
            
            # Append tombstone entry
            self.file.seek(0, os.SEEK_END)
            data_offset = self.file.tell()
            
            entry = Entry(
                key_hash=key_hash,
                timestamp=int(time.time() * 1000000),
                offset=data_offset + ENTRY_HEADER_SIZE,
                size=0,
                flags=EntryFlags.DELETED,
                checksum=0
            )
            
            self.file.write(entry.pack())
            self.file.flush()
            
            # Remove from index
            del self.index[key_hash]
            self.key_map.pop(key_hash, None)  # ← AJOUT
            
            # Invalidate cache
            self.cache.invalidate(key_hash)
            
            # Update superblock
            self._update_superblock()
            
            return True
    
    def exists(self, key: str) -> bool:
        """Check if key exists (pythonic alias for exist)"""
        key_hash = fast_hash(key.encode('utf-8'))
        return key_hash in self.index
    
    def exist(self, key: str) -> bool:
        """Check if key exists (backward compatibility)"""
        return self.exists(key)
    
    def __contains__(self, key: str) -> bool:
        """Support 'key in db' syntax"""
        return self.exists(key)
    
    def __getitem__(self, key: str) -> bytes:
        """Support db[key] syntax"""
        result = self.get(key)
        if result is None:
            raise KeyError(key)
        return result
    
    def __setitem__(self, key: str, value: Union[str, bytes, int, float]):
        """Support db[key] = value syntax"""
        self.set(key, value)
    
    def __delitem__(self, key: str):
        """Support del db[key] syntax"""
        if not self.delete(key):
            raise KeyError(key)
    
    def list(self) -> List[str]:
        """List all keys (original key strings)"""
        with self.read_lock:
            return list(self.key_map.values())

    def keys(self) -> List[str]:
        """Alias for list() - more pythonic"""
        return self.list()
    
    def _update_superblock(self):
        """Update superblock metadata"""
        try:
            superblock = Superblock(
                magic=MAGIC,
                version=VERSION,
                data_offset=SUPERBLOCK_SIZE,
                num_entries=len(self.index),
                gc_count=0
            )
            
            self.file.seek(0)
            self.file.write(superblock.pack())
            self.file.flush()
        except OSError as e:
            print(f"Warning: Failed to update superblock: {e}")
    
    def compact(self) -> Dict[str, int]:
        """
        Garbage collection: compact file by removing dead entries
        Rewrites only live data
        
        Returns:
            Statistics about the compaction
        """
        with self.write_lock:
            old_size = self.filepath.stat().st_size
            
            # Create temporary file
            temp_path = self.filepath.with_suffix('.tmp')
            
            # Write new superblock
            superblock = Superblock(
                magic=MAGIC,
                version=VERSION,
                data_offset=SUPERBLOCK_SIZE,
                num_entries=len(self.index),
                gc_count=0
            )
            
            entries_copied = 0
            
            try:
                with open(temp_path, 'wb') as new_file:
                    new_file.write(superblock.pack())
                    
                    # Copy live entries
                    new_index = {}
                    for key_hash, entry in self.index.items():
                        try:
                            # Read original data
                            self.file.seek(entry.offset)
                            data = self.file.read(entry.size)
                            
                            if len(data) < entry.size:
                                print(f"Warning: Skipping incomplete entry {hex(key_hash)}")
                                continue
                            
                            # Verify checksum
                            if checksum(data) != entry.checksum:
                                print(f"Warning: Skipping corrupted entry {hex(key_hash)}")
                                continue
                            
                            # Write to new file
                            new_offset = new_file.tell()
                            new_entry = Entry(
                                key_hash=entry.key_hash,
                                timestamp=entry.timestamp,
                                offset=new_offset + ENTRY_HEADER_SIZE,
                                size=entry.size,
                                flags=entry.flags,
                                checksum=entry.checksum
                            )
                            
                            new_file.write(new_entry.pack())
                            new_file.write(data)
                            
                            new_index[key_hash] = new_entry
                            entries_copied += 1
                            
                        except Exception as e:
                            print(f"Warning: Error copying entry {hex(key_hash)}: {e}")
                            continue
                    
                    new_file.flush()
                    os.fsync(new_file.fileno())
                
                # Close old file
                self.file.close()
                
                # Replace with new file
                os.replace(temp_path, self.filepath)
                
                # Reopen and update index
                self._open_file()
                self.index = new_index
                self.cache.clear()
                
                # Rebuild dedup index
                self.dedup_index.clear()
                
                new_size = self.filepath.stat().st_size
                
                return {
                    'entries_copied': entries_copied,
                    'old_size': old_size,
                    'new_size': new_size,
                    'saved_bytes': old_size - new_size,
                    'compression_ratio': new_size / old_size if old_size > 0 else 1.0
                }
                
            except Exception as e:
                # Clean up temp file on error
                if temp_path.exists():
                    temp_path.unlink()
                raise RuntimeError(f"Compaction failed: {e}")
    
    def gc(self) -> Dict[str, int]:
        """Run garbage collector (alias for compact)"""
        return self.compact()
    
    def stats(self) -> Dict:
        """Return statistics"""
        with self.read_lock:
            file_size = self.filepath.stat().st_size if self.filepath.exists() else 0
            live_entries = len(self.index)
            
            # Calculate garbage
            try:
                self.file.seek(0, os.SEEK_END)
                total_size = self.file.tell()
            except:
                total_size = file_size
            
            cache_hit_rate = 0.0
            if self.stats_reads > 0:
                cache_hit_rate = self.stats_cache_hits / self.stats_reads
            
            # Calculate space used by live entries
            live_size = sum(entry.size + ENTRY_HEADER_SIZE for entry in self.index.values())
            garbage_size = file_size - SUPERBLOCK_SIZE - live_size
            
            return {
                'file_size': file_size,
                'live_entries': live_entries,
                'live_size': live_size,
                'garbage_size': max(0, garbage_size),
                'garbage_ratio': garbage_size / file_size if file_size > 0 else 0.0,
                'total_reads': self.stats_reads,
                'total_writes': self.stats_writes,
                'cache_hits': self.stats_cache_hits,
                'cache_misses': self.stats_cache_misses,
                'cache_hit_rate': cache_hit_rate,
                'cache_size': len(self.cache.cache),
                'dedup_entries': len(self.dedup_index)
            }
    
    def verify(self) -> Tuple[bool, List[str]]:
        """
        Verify data integrity
        
        Returns:
            (success, list of errors)
        """
        errors = []
        
        with self.read_lock:
            for key_hash, entry in self.index.items():
                try:
                    self.file.seek(entry.offset)
                    data = self.file.read(entry.size)
                    
                    if len(data) < entry.size:
                        errors.append(f"Incomplete data for key {hex(key_hash)}")
                        continue
                    
                    if checksum(data) != entry.checksum:
                        errors.append(f"Checksum mismatch for key {hex(key_hash)}")
                        
                except Exception as e:
                    errors.append(f"Error verifying key {hex(key_hash)}: {e}")
        
        return (len(errors) == 0, errors)
    
    def backup(self, backup_path: str) -> None:
        """Create backup of database file"""
        import shutil
        with self.read_lock:
            if self.file:
                self.file.flush()
                os.fsync(self.file.fileno())
            shutil.copy2(self.filepath, backup_path)
    
    def close(self):
        """Close database file"""
        if self.file:
            try:
                self._update_superblock()
                self.file.flush()
                os.fsync(self.file.fileno())
                self.file.close()
            except:
                pass
            finally:
                self.file = None
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
    
    def __del__(self):
        self.close()


# Backward compatibility alias
FlatKV = HiveFS


# ============================================================================
# EXAMPLE USAGE
# ============================================================================

if __name__ == '__main__':
    # Create or open database (with auto-recovery)
    db = HiveFS('database.hive', cache_size=500, auto_recover=True)
    
    # Store data - now accepts strings, bytes, int, float
    db.set('user:1', 'Alice')  # String
    db.set('user:2', b'Bob')   # Bytes
    db.set('config:timeout', 30)  # Int
    db.set('config:version', 1.0)  # Float
    
    # Retrieve data
    print(db.get('user:1'))  # b'Alice'
    print(db.get('user:1', as_str=True))  # 'Alice' (decoded)
    print(db.get('config:timeout', as_str=True))  # '30'
    
    # Dict-like syntax
    db['user:3'] = 'Charlie'
    print(db['user:3'])
    print('user:3' in db)  # True
    
    # Update (creates new version, old becomes garbage)
    db.set('user:1', 'Alice Smith')
    print(db.get('user:1', as_str=True))  # 'Alice Smith'
    
    # Check existence
    print(db.exists('user:1'))  # True
    print(db.exists('user:999'))  # False
    
    # Delete
    db.delete('user:2')
    print(db.exists('user:2'))  # False
    
    # List all keys (as hashes)
    print(db.list())
    
    # Statistics
    stats = db.stats()
    print(f"File size: {stats['file_size']} bytes")
    print(f"Live entries: {stats['live_entries']}")
    print(f"Cache hit rate: {stats['cache_hit_rate']:.2%}")
    print(f"Garbage ratio: {stats['garbage_ratio']:.2%}")
    
    # Verify integrity
    is_valid, errors = db.verify()
    print(f"Database valid: {is_valid}")
    if errors:
        print("Errors:", errors)
    
    # Compact (garbage collection)
    if stats['garbage_ratio'] > 0.3:  # More than 30% garbage
        print("Running garbage collection...")
        gc_stats = db.compact()
        print(f"Saved {gc_stats['saved_bytes']} bytes")
    
    # Backup
    db.backup('database.hive.backup')
    
    # Close
    db.close()

def R_ECO3(args, log_fn=print):
    log_fn("HiveFS is a key-value database. It supports string, bytes, int, and float values.")
    
def R_ECO3dep():
    return (("3.5.1b",), (("core.trail", ("1.1",)),))

def R_ECO3inf():
    return {
        "name": "hive",
        "desc": "Hive, is a key-value database",
        "help": "No argument, it's an API",
        "version_mod": "1.1",
    }
