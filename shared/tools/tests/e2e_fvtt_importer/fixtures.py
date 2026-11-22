"""Synthetic FVTT v9 NeDB & v14 Snappy LevelDB fixture builders + `bgdia` locators.

Pure-Python zero-external-dependency implementation:
- Valid 1x1 / WxH PNG & 1x1 lossless VP8L WebP image generators.
- Genuine FVTT v9-v10 NeDB (`data/*.db`) builders (with tombstones & duplicate `_id`s).
- Genuine FVTT v11-v14 LevelDB (`CURRENT`, `LOCK`, `MANIFEST-*`, Snappy-compressed `.ldb`
  SSTables, and 32 KiB-blocked `WriteBatch` `.log` WAL with Put & Delete tombstones).
- Depth-0 / depth-1 / depth-2 / junk-polluted / non-ASCII `.zip` archive builders.
- Read-only ground-truth locators for `bgdia` directory and `.zip`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import struct
import sys
from typing import Any, Iterable, Mapping, Sequence
import zipfile
import zlib

_TOOLS_DIR = Path(__file__).resolve().parents[2]
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from fuvtt_devtools.env_config import DEFAULT_WORKSPACE_ROOT, parse_dotenv_file, redact_path  # noqa: E402


REDACTED_BGDIA_DIR_PLACEHOLDER = "<FUVTT_BGDIA_DIR>"
REDACTED_BGDIA_ZIP_PLACEHOLDER = "<FUVTT_BGDIA_ZIP>"

_BGDIA_ENV_KEYS = (
    "FUVTT_BGDIA_DIR",
    "FVTT_BGDIA_DIR",
    "FUVTT_BGDIA_ZIP",
    "FVTT_BGDIA_ZIP",
    "LOCALAPPDATA",
)


def _strip_env_quotes(raw: str) -> str:
    val = raw.strip()
    if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
        val = val[1:-1].strip()
    return val


def _safe_expanduser(path: Path) -> Path | None:
    try:
        return path.expanduser()
    except (OSError, RuntimeError):
        return None


def _safe_resolve(path: Path) -> Path | None:
    try:
        return path.resolve()
    except OSError:
        return None


def _safe_is_dir(path: Path) -> bool:
    try:
        return path.is_dir()
    except OSError:
        return False


def _safe_is_file(path: Path) -> bool:
    try:
        return path.is_file()
    except OSError:
        return False


def _safe_glob(path: Path, pattern: str) -> list[Path]:
    try:
        return sorted(path.glob(pattern), key=lambda p: p.name)
    except OSError:
        return []


def _load_bgdia_env(
    workspace_root: Path | None = None,
    env_file: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    ws_root = workspace_root if workspace_root is not None else DEFAULT_WORKSPACE_ROOT
    dotenv_path = env_file if env_file is not None else (ws_root / ".env.local")
    try:
        dotenv_items = parse_dotenv_file(dotenv_path)
    except OSError:
        dotenv_items = {}
    merged = {k: _strip_env_quotes(v) for k, v in dotenv_items.items() if v is not None}
    src_env = os.environ if environ is None else environ
    for key in _BGDIA_ENV_KEYS:
        if key in src_env:
            val = _strip_env_quotes(src_env[key])
            if val:
                merged[key] = val
    return merged


def _standard_foundry_worlds_dirs(env_map: Mapping[str, str]) -> list[Path]:
    candidates: list[Path] = []
    local_appdata = env_map.get("LOCALAPPDATA", "").strip()
    if local_appdata:
        expanded = _safe_expanduser(Path(local_appdata))
        if expanded is not None:
            candidates.append(expanded / "FoundryVTT" / "Data" / "worlds")
    try:
        home: Path | None = Path.home()
    except (OSError, RuntimeError):
        home = None
    if home is not None:
        candidates.extend(
            [
                home / "AppData" / "Local" / "FoundryVTT" / "Data" / "worlds",
                home / ".local" / "share" / "FoundryVTT" / "Data" / "worlds",
                home / "Library" / "Application Support" / "FoundryVTT" / "Data" / "worlds",
            ]
        )
    deduped: list[Path] = []
    seen: set[str] = set()
    for cand in candidates:
        norm = os.path.normcase(str(cand))
        if norm not in seen:
            seen.add(norm)
            deduped.append(cand)
    return deduped


def resolve_bgdia_dir_world_json(
    *,
    workspace_root: Path | None = None,
    env_file: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> Path | None:
    env_map = _load_bgdia_env(workspace_root=workspace_root, env_file=env_file, environ=environ)
    for key in ("FUVTT_BGDIA_DIR", "FVTT_BGDIA_DIR"):
        raw = env_map.get(key, "").strip()
        if raw:
            p = _safe_expanduser(Path(raw))
            if p is None:
                continue
            target = p if p.name.lower() == "world.json" else (p / "world.json")
            resolved = _safe_resolve(target)
            if resolved is not None:
                return resolved
            continue
    for wdir in _standard_foundry_worlds_dirs(env_map):
        cand = wdir / "bgdia" / "world.json"
        if _safe_is_file(cand):
            resolved = _safe_resolve(cand)
            if resolved is not None:
                return resolved
    return None


def resolve_bgdia_zip_path(
    *,
    workspace_root: Path | None = None,
    env_file: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> Path | None:
    env_map = _load_bgdia_env(workspace_root=workspace_root, env_file=env_file, environ=environ)
    for key in ("FUVTT_BGDIA_ZIP", "FVTT_BGDIA_ZIP"):
        raw = env_map.get(key, "").strip()
        if raw:
            p = _safe_expanduser(Path(raw))
            if p is None:
                continue
            resolved = _safe_resolve(p)
            if resolved is not None:
                return resolved
            continue
    for wdir in _standard_foundry_worlds_dirs(env_map):
        if not _safe_is_dir(wdir):
            continue
        direct = wdir / "bgdia.zip"
        if _safe_is_file(direct):
            resolved = _safe_resolve(direct)
            if resolved is not None:
                return resolved
        for cand in _safe_glob(wdir, "*bgdia*.zip"):
            if _safe_is_file(cand):
                resolved = _safe_resolve(cand)
                if resolved is not None:
                    return resolved
    return None


def redact_bgdia_path(
    text: str | Path,
    *,
    bgdia_dir_world_json: Path | None = None,
    bgdia_zip_path: Path | None = None,
) -> str:
    rendered = str(text)
    if bgdia_zip_path is not None:
        rendered = redact_path(rendered, bgdia_zip_path, REDACTED_BGDIA_ZIP_PLACEHOLDER)
    if bgdia_dir_world_json is not None:
        if bgdia_dir_world_json.name.lower() == "world.json":
            rendered = redact_path(
                rendered,
                bgdia_dir_world_json,
                f"{REDACTED_BGDIA_DIR_PLACEHOLDER}/world.json",
            )
            rendered = redact_path(rendered, bgdia_dir_world_json.parent, REDACTED_BGDIA_DIR_PLACEHOLDER)
        else:
            rendered = redact_path(rendered, bgdia_dir_world_json, REDACTED_BGDIA_DIR_PLACEHOLDER)
    for env_key, placeholder in (("LOCALAPPDATA", "<LOCALAPPDATA>"), ("USERPROFILE", "<USERPROFILE>")):
        raw_val = os.environ.get(env_key, "").strip()
        if raw_val:
            rendered = redact_path(rendered, raw_val, placeholder)
    try:
        rendered = redact_path(rendered, Path.home(), "<USER_HOME>")
    except (OSError, RuntimeError):
        pass
    return rendered


BGDIA_DIR_WORLD_JSON: Path | None = resolve_bgdia_dir_world_json()
BGDIA_ZIP_PATH: Path | None = resolve_bgdia_zip_path()

_LEVELDB_FOOTER_MAGIC = 0xDB4775248B80FB57
_WAL_BLOCK_SIZE = 32768
_WAL_HEADER_SIZE = 7


# ---------------------------------------------------------------------------
# Minimal Valid PNG & WebP Generators
# ---------------------------------------------------------------------------

def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", crc)


def make_png_bytes(width: int = 1, height: int = 1, rgba: tuple[int, int, int, int] = (64, 160, 224, 255)) -> bytes:
    """Return minimal valid RGBA PNG bytes."""
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    pixel = bytes(rgba)
    row = b"\x00" + (pixel * width)
    raw_scanlines = row * height
    idat = zlib.compress(raw_scanlines, level=6)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", idat)
        + _png_chunk(b"IEND", b"")
    )


class _LsbBitWriter:
    def __init__(self) -> None:
        self._buf = bytearray()
        self._acc = 0
        self._bits = 0

    def write_bits(self, value: int, num_bits: int) -> None:
        for i in range(num_bits):
            bit = (value >> i) & 1
            self._acc |= bit << self._bits
            self._bits += 1
            if self._bits == 8:
                self._buf.append(self._acc)
                self._acc = 0
                self._bits = 0

    def finish(self) -> bytes:
        if self._bits > 0:
            self._buf.append(self._acc)
            self._acc = 0
            self._bits = 0
        return bytes(self._buf)


def make_webp_bytes(rgba: tuple[int, int, int, int] = (200, 96, 48, 255)) -> bytes:
    """Return minimal valid 1x1 lossless VP8L WebP bytes."""
    r, g, b, a = rgba
    bw = _LsbBitWriter()
    # 1x1 image header: signature(0x2f) + 32-bit (w-1=0, h-1=0, alpha=1, version=0)
    header = bytes([0x2F]) + struct.pack("<I", 0x10000000)
    # Transform present = 0
    bw.write_bits(0, 1)
    # Color cache used = 0
    bw.write_bits(0, 1)
    # Meta prefix codes used = 0
    bw.write_bits(0, 1)
    # 5 single-symbol prefix code trees: Green, Red, Blue, Alpha, Distance
    for sym in (g, r, b, a, 0):
        bw.write_bits(1, 1)    # simple_code_length_code = 1
        bw.write_bits(0, 1)    # num_symbols - 1 = 0 (1 symbol)
        bw.write_bits(1, 1)    # is_first_8bits = 1
        bw.write_bits(sym & 0xFF, 8)
    # 1 pixel with 0-bit Huffman codes -> no pixel bits needed!
    vp8l_payload = header + bw.finish()
    pad = b"\x00" if (len(vp8l_payload) % 2 == 1) else b""
    riff_size = 4 + 8 + len(vp8l_payload) + len(pad)
    return b"RIFF" + struct.pack("<I", riff_size) + b"WEBP" + b"VP8L" + struct.pack("<I", len(vp8l_payload)) + vp8l_payload + pad


# ---------------------------------------------------------------------------
# Pure-Python CRC32C, Snappy, LevelDB SSTable (.ldb), & WAL (.log)
# ---------------------------------------------------------------------------

def _build_crc32c_table() -> list[int]:
    poly = 0x82F63B78
    table: list[int] = []
    for i in range(256):
        crc = i
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ poly
            else:
                crc >>= 1
        table.append(crc)
    return table


_CRC32C_TABLE = _build_crc32c_table()


def crc32c(data: bytes) -> int:
    crc = 0xFFFFFFFF
    table = _CRC32C_TABLE
    for b in data:
        crc = table[(crc ^ b) & 0xFF] ^ (crc >> 8)
    return crc ^ 0xFFFFFFFF


def leveldb_masked_crc32c(data: bytes) -> int:
    c = crc32c(data)
    return (((c >> 15) | (c << 17)) + 0xA282EAD8) & 0xFFFFFFFF


def _encode_varint32(n: int) -> bytes:
    out = bytearray()
    while n >= 0x80:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    out.append(n & 0x7F)
    return bytes(out)


def _decode_varint(buf: bytes, pos: int) -> tuple[int, int]:
    shift = 0
    result = 0
    while True:
        b = buf[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            return result, pos
        shift += 7


def _emit_snappy_literal(out: bytearray, lit: bytes) -> None:
    if not lit:
        return
    n = len(lit) - 1
    if n < 60:
        out.append(n << 2)
    elif n < 256:
        out.append(60 << 2)
        out.append(n)
    elif n < 65536:
        out.append(61 << 2)
        out.extend(struct.pack("<H", n))
    elif n < 16777216:
        out.append(62 << 2)
        out.extend(struct.pack("<I", n)[:3])
    else:
        out.append(63 << 2)
        out.extend(struct.pack("<I", n))
    out.extend(lit)


def snappy_compress(data: bytes) -> bytes:
    """Pure-Python Snappy block compressor emitting literals and copy-1 / copy-2 tags."""
    out = bytearray(_encode_varint32(len(data)))
    n = len(data)
    if n == 0:
        return bytes(out)
    if n < 15:
        _emit_snappy_literal(out, data)
        return bytes(out)

    htable: dict[bytes, int] = {}
    lit_start = 0
    ip = 0
    limit = n - 4

    while ip <= limit:
        key = data[ip : ip + 4]
        candidate = htable.get(key, -1)
        htable[key] = ip
        if candidate >= 0 and (ip - candidate) <= 65535 and data[candidate : candidate + 4] == key:
            _emit_snappy_literal(out, data[lit_start:ip])
            match_len = 4
            max_match = min(64, n - ip)
            while match_len < max_match and data[candidate + match_len] == data[ip + match_len]:
                match_len += 1
            offset = ip - candidate
            if match_len <= 11 and offset < 2048:
                out.append((((offset >> 8) & 0x07) << 5) | ((match_len - 4) << 2) | 1)
                out.append(offset & 0xFF)
            else:
                out.append(((match_len - 1) << 2) | 2)
                out.extend(struct.pack("<H", offset))
            ip += match_len
            lit_start = ip
        else:
            ip += 1

    if lit_start < n:
        _emit_snappy_literal(out, data[lit_start:])
    return bytes(out)


def snappy_decompress(data: bytes) -> bytes:
    """Pure-Python Snappy block decompressor for fixture verification."""
    ulen, pos = _decode_varint(data, 0)
    out = bytearray()
    while pos < len(data):
        tag = data[pos]
        pos += 1
        kind = tag & 0x03
        if kind == 0:
            length = (tag >> 2) + 1
            if length > 60:
                extra = length - 60
                length = int.from_bytes(data[pos : pos + extra], "little") + 1
                pos += extra
            out.extend(data[pos : pos + length])
            pos += length
        elif kind == 1:
            length = ((tag >> 2) & 0x07) + 4
            offset = ((tag & 0xE0) << 3) | data[pos]
            pos += 1
            for _ in range(length):
                out.append(out[-offset])
        elif kind == 2:
            length = (tag >> 2) + 1
            offset = struct.unpack_from("<H", data, pos)[0]
            pos += 2
            for _ in range(length):
                out.append(out[-offset])
        else:
            length = (tag >> 2) + 1
            offset = struct.unpack_from("<I", data, pos)[0]
            pos += 4
            for _ in range(length):
                out.append(out[-offset])
    if len(out) != ulen:
        raise ValueError(f"Snappy length mismatch: expected {ulen}, got {len(out)}")
    return bytes(out)


def _encode_block_handle(offset: int, size: int) -> bytes:
    return _encode_varint32(offset) + _encode_varint32(size)


def _build_leveldb_block(entries: Sequence[tuple[bytes, bytes]], restart_interval: int = 16) -> bytes:
    buf = bytearray()
    restarts: list[int] = [0]
    last_key = b""
    counter = 0

    for idx, (key, value) in enumerate(entries):
        if idx > 0 and counter >= restart_interval:
            restarts.append(len(buf))
            counter = 0
            shared = 0
        elif idx == 0:
            shared = 0
        else:
            shared = 0
            lim = min(len(last_key), len(key))
            while shared < lim and last_key[shared] == key[shared]:
                shared += 1
        non_shared = len(key) - shared
        buf.extend(_encode_varint32(shared))
        buf.extend(_encode_varint32(non_shared))
        buf.extend(_encode_varint32(len(value)))
        buf.extend(key[shared:])
        buf.extend(value)
        last_key = key
        counter += 1

    for r in restarts:
        buf.extend(struct.pack("<I", r))
    buf.extend(struct.pack("<I", len(restarts)))
    return bytes(buf)


def _wrap_block_with_trailer(raw_block: bytes, *, compress_snappy: bool) -> bytes:
    if compress_snappy:
        payload = snappy_compress(raw_block)
        btype = 1
    else:
        payload = raw_block
        btype = 0
    crc = leveldb_masked_crc32c(payload + bytes([btype]))
    return payload + bytes([btype]) + struct.pack("<I", crc)


def build_sstable_bytes(
    records: Sequence[tuple[bytes, int, int, bytes]],
    *,
    compress_snappy: bool = True,
    block_size: int = 4096,
) -> tuple[bytes, bytes, bytes]:
    """Build a genuine LevelDB `.ldb` SSTable.

    `records`: sequence of `(user_key, seq, val_type, value)` where `val_type` is 1 (Put) or 0 (Delete).
    Returns `(sst_bytes, smallest_internal_key, largest_internal_key)`.
    """
    sorted_recs = sorted(records, key=lambda r: (r[0], -((r[1] << 8) | (r[2] & 0xFF))))
    if not sorted_recs:
        raise ValueError("build_sstable_bytes requires at least one record")

    internal_entries: list[tuple[bytes, bytes]] = []
    for ukey, seq, vtype, val in sorted_recs:
        ikey = ukey + struct.pack("<Q", (seq << 8) | (vtype & 0xFF))
        internal_entries.append((ikey, val))

    out = bytearray()
    index_entries: list[tuple[bytes, bytes]] = []

    current_chunk: list[tuple[bytes, bytes]] = []
    current_approx = 0
    for ikey, val in internal_entries:
        current_chunk.append((ikey, val))
        current_approx += len(ikey) + len(val) + 12
        if current_approx >= block_size:
            raw_blk = _build_leveldb_block(current_chunk)
            framed = _wrap_block_with_trailer(raw_blk, compress_snappy=compress_snappy)
            offset = len(out)
            payload_size = len(framed) - 5
            out.extend(framed)
            index_entries.append((current_chunk[-1][0], _encode_block_handle(offset, payload_size)))
            current_chunk = []
            current_approx = 0

    if current_chunk:
        raw_blk = _build_leveldb_block(current_chunk)
        framed = _wrap_block_with_trailer(raw_blk, compress_snappy=compress_snappy)
        offset = len(out)
        payload_size = len(framed) - 5
        out.extend(framed)
        index_entries.append((current_chunk[-1][0], _encode_block_handle(offset, payload_size)))

    # MetaIndex block (empty)
    meta_raw = _build_leveldb_block([])
    meta_framed = _wrap_block_with_trailer(meta_raw, compress_snappy=False)
    meta_offset = len(out)
    meta_size = len(meta_framed) - 5
    out.extend(meta_framed)

    # Index block
    index_raw = _build_leveldb_block(index_entries, restart_interval=1)
    index_framed = _wrap_block_with_trailer(index_raw, compress_snappy=compress_snappy)
    index_offset = len(out)
    index_size = len(index_framed) - 5
    out.extend(index_framed)

    # 48-byte Footer
    handles = _encode_block_handle(meta_offset, meta_size) + _encode_block_handle(index_offset, index_size)
    if len(handles) > 40:
        raise ValueError("LevelDB footer handles exceed 40 bytes")
    footer = handles + (b"\x00" * (40 - len(handles))) + struct.pack("<Q", _LEVELDB_FOOTER_MAGIC)
    out.extend(footer)
    return bytes(out), internal_entries[0][0], internal_entries[-1][0]


def build_wal_bytes(records: Sequence[bytes]) -> bytes:
    """Encode logical WAL records into standard LevelDB 32 KiB physical blocks."""
    out = bytearray()
    block_offset = 0

    for rec in records:
        pos = 0
        begin = True
        while True:
            leftover = _WAL_BLOCK_SIZE - block_offset
            if leftover < _WAL_HEADER_SIZE:
                if leftover > 0:
                    out.extend(b"\x00" * leftover)
                block_offset = 0
                leftover = _WAL_BLOCK_SIZE

            avail = leftover - _WAL_HEADER_SIZE
            fragment_len = min(len(rec) - pos, avail)
            end = (pos + fragment_len) == len(rec)
            if begin and end:
                rtype = 1  # kFullType
            elif begin:
                rtype = 2  # kFirstType
            elif end:
                rtype = 4  # kLastType
            else:
                rtype = 3  # kMiddleType

            frag = rec[pos : pos + fragment_len]
            crc = leveldb_masked_crc32c(bytes([rtype]) + frag)
            out.extend(struct.pack("<IHB", crc, fragment_len, rtype))
            out.extend(frag)
            block_offset += _WAL_HEADER_SIZE + fragment_len
            pos += fragment_len
            begin = False
            if end:
                break

    return bytes(out)


def encode_write_batch(seq: int, ops: Sequence[tuple[str, bytes, bytes]]) -> bytes:
    """Build a LevelDB WriteBatch payload (`ops` of `("put", k, v)` or `("delete", k, b"")`)."""
    buf = bytearray(struct.pack("<QI", seq, len(ops)))
    for op, key, val in ops:
        if op == "put":
            buf.append(1)
            buf.extend(_encode_varint32(len(key)))
            buf.extend(key)
            buf.extend(_encode_varint32(len(val)))
            buf.extend(val)
        elif op == "delete":
            buf.append(0)
            buf.extend(_encode_varint32(len(key)))
            buf.extend(key)
        else:
            raise ValueError(f"Unsupported WriteBatch op: {op!r}")
    return bytes(buf)


def build_manifest_bytes(
    *,
    ldb_files: Sequence[tuple[int, int, bytes, bytes]] = (),
    log_number: int = 6,
    next_file_number: int = 7,
    last_sequence: int = 100,
) -> bytes:
    """Build a valid LevelDB MANIFEST VersionEdit wrapped in a WAL record."""
    edit = bytearray()
    # Tag 1: kComparator
    comp = b"leveldb.BytewiseComparator"
    edit.extend(_encode_varint32(1) + _encode_varint32(len(comp)) + comp)
    # Tag 2: kLogNumber
    edit.extend(_encode_varint32(2) + _encode_varint32(log_number))
    # Tag 3: kNextFileNumber
    edit.extend(_encode_varint32(3) + _encode_varint32(next_file_number))
    # Tag 4: kLastSequence
    edit.extend(_encode_varint32(4) + _encode_varint32(last_sequence))
    # Tag 7: kNewFile (level=0, number, file_size, smallest, largest)
    for fnum, fsize, smallest, largest in ldb_files:
        edit.extend(_encode_varint32(7))
        edit.extend(_encode_varint32(0))
        edit.extend(_encode_varint32(fnum))
        edit.extend(_encode_varint32(fsize))
        edit.extend(_encode_varint32(len(smallest)) + smallest)
        edit.extend(_encode_varint32(len(largest)) + largest)
    return build_wal_bytes([bytes(edit)])


def write_leveldb_collection(
    coll_dir: Path,
    *,
    ldb_records: Sequence[tuple[bytes, int, int, bytes]] = (),
    wal_batches: Sequence[tuple[int, Sequence[tuple[str, bytes, bytes]]]] = (),
    compress_snappy: bool = True,
) -> None:
    """Materialize a complete LevelDB collection directory (`.ldb`, `.log`, `MANIFEST`, `CURRENT`, `LOCK`)."""
    coll_dir.mkdir(parents=True, exist_ok=True)
    ldb_meta: list[tuple[int, int, bytes, bytes]] = []
    max_seq = 1

    if ldb_records:
        sst_bytes, smallest, largest = build_sstable_bytes(ldb_records, compress_snappy=compress_snappy)
        ldb_path = coll_dir / "000005.ldb"
        ldb_path.write_bytes(sst_bytes)
        ldb_meta.append((5, len(sst_bytes), smallest, largest))
        max_seq = max(max_seq, max(r[1] for r in ldb_records))

    wal_records: list[bytes] = []
    for seq, ops in wal_batches:
        wal_records.append(encode_write_batch(seq, ops))
        max_seq = max(max_seq, seq + max(0, len(ops) - 1))
    (coll_dir / "000006.log").write_bytes(build_wal_bytes(wal_records) if wal_records else b"")

    manifest_bytes = build_manifest_bytes(
        ldb_files=ldb_meta,
        log_number=6,
        next_file_number=7,
        last_sequence=max_seq,
    )
    (coll_dir / "MANIFEST-000001").write_bytes(manifest_bytes)
    (coll_dir / "CURRENT").write_bytes(b"MANIFEST-000001\n")
    (coll_dir / "LOCK").write_bytes(b"")


def _parse_leveldb_block(raw_block: bytes) -> list[tuple[bytes, bytes]]:
    if len(raw_block) < 4:
        return []
    num_restarts = struct.unpack_from("<I", raw_block, len(raw_block) - 4)[0]
    data_end = len(raw_block) - 4 - (num_restarts * 4)
    pos = 0
    last_key = b""
    out: list[tuple[bytes, bytes]] = []
    while pos < data_end:
        shared, pos = _decode_varint(raw_block, pos)
        non_shared, pos = _decode_varint(raw_block, pos)
        vlen, pos = _decode_varint(raw_block, pos)
        key = last_key[:shared] + raw_block[pos : pos + non_shared]
        pos += non_shared
        val = raw_block[pos : pos + vlen]
        pos += vlen
        last_key = key
        out.append((key, val))
    return out


def _read_framed_block(data: bytes, offset: int, size: int) -> bytes:
    payload = data[offset : offset + size]
    btype = data[offset + size]
    stored_crc = struct.unpack_from("<I", data, offset + size + 1)[0]
    calc_crc = leveldb_masked_crc32c(payload + bytes([btype]))
    if stored_crc != calc_crc:
        raise ValueError(f"LevelDB block CRC mismatch: {stored_crc:#x} != {calc_crc:#x}")
    if btype == 0:
        return payload
    if btype == 1:
        return snappy_decompress(payload)
    raise ValueError(f"Unsupported LevelDB compression type: {btype}")


def decode_leveldb_collection(coll_dir: Path) -> dict[bytes, bytes]:
    """Self-verification decoder for LevelDB `.ldb` + `.log` WAL directories."""
    state: dict[bytes, tuple[int, int, bytes]] = {}  # user_key -> (seq, vtype, val)

    for ldb_path in sorted(coll_dir.glob("*.ldb")):
        data = ldb_path.read_bytes()
        magic = struct.unpack_from("<Q", data, len(data) - 8)[0]
        if magic != _LEVELDB_FOOTER_MAGIC:
            raise ValueError(f"Invalid SSTable footer magic in {ldb_path}")
        footer_handles = data[len(data) - 48 : len(data) - 8]
        _, p = _decode_varint(footer_handles, 0)
        _, p = _decode_varint(footer_handles, p)
        idx_off, p = _decode_varint(footer_handles, p)
        idx_sz, _ = _decode_varint(footer_handles, p)
        idx_raw = _read_framed_block(data, idx_off, idx_sz)
        for _, handle_bytes in _parse_leveldb_block(idx_raw):
            blk_off, hp = _decode_varint(handle_bytes, 0)
            blk_sz, _ = _decode_varint(handle_bytes, hp)
            blk_raw = _read_framed_block(data, blk_off, blk_sz)
            for ikey, val in _parse_leveldb_block(blk_raw):
                ukey = ikey[:-8]
                tag = struct.unpack_from("<Q", ikey, len(ikey) - 8)[0]
                seq = tag >> 8
                vtype = tag & 0xFF
                prev = state.get(ukey)
                if prev is None or seq > prev[0]:
                    state[ukey] = (seq, vtype, val)

    for log_path in sorted(coll_dir.glob("*.log")):
        raw = log_path.read_bytes()
        if not raw:
            continue
        logical_records: list[bytes] = []
        frag_buf = bytearray()
        offset = 0
        while offset < len(raw):
            block = raw[offset : offset + _WAL_BLOCK_SIZE]
            offset += _WAL_BLOCK_SIZE
            bpos = 0
            while bpos + _WAL_HEADER_SIZE <= len(block):
                stored_crc, flen, rtype = struct.unpack_from("<IHB", block, bpos)
                if flen == 0 and rtype == 0:
                    break
                bpos += _WAL_HEADER_SIZE
                frag = block[bpos : bpos + flen]
                bpos += flen
                if leveldb_masked_crc32c(bytes([rtype]) + frag) != stored_crc:
                    raise ValueError(f"WAL CRC mismatch in {log_path}")
                if rtype == 1:
                    logical_records.append(frag)
                elif rtype == 2:
                    frag_buf = bytearray(frag)
                elif rtype == 3:
                    frag_buf.extend(frag)
                elif rtype == 4:
                    frag_buf.extend(frag)
                    logical_records.append(bytes(frag_buf))
                    frag_buf = bytearray()

        for wb in logical_records:
            seq, count = struct.unpack_from("<QI", wb, 0)
            pos = 12
            for idx in range(count):
                op = wb[pos]
                pos += 1
                klen, pos = _decode_varint(wb, pos)
                ukey = wb[pos : pos + klen]
                pos += klen
                if op == 1:
                    vlen, pos = _decode_varint(wb, pos)
                    val = wb[pos : pos + vlen]
                    pos += vlen
                else:
                    val = b""
                cur_seq = seq + idx
                prev = state.get(ukey)
                if prev is None or cur_seq >= prev[0]:
                    state[ukey] = (cur_seq, op, val)

    return {k: v for k, (_, vt, v) in state.items() if vt == 1}


# ---------------------------------------------------------------------------
# FVTT World JSON, NeDB, LevelDB, and ZIP Fixture Builders
# ---------------------------------------------------------------------------

def write_json_file(path: Path, data: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").replace("\r\n", "\n")
    path.write_bytes(text.encode("utf-8"))
    return path


def write_nedb_file(path: Path, records: Iterable[dict[str, Any]], raw_lines: Iterable[bytes] | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    chunks: list[bytes] = []
    for rec in records:
        chunks.append((json.dumps(rec, ensure_ascii=False) + "\n").encode("utf-8"))
    if raw_lines is not None:
        for line in raw_lines:
            chunks.append(line if line.endswith(b"\n") else (line + b"\n"))
    path.write_bytes(b"".join(chunks))
    return path


def make_v9_world_json(
    *,
    name: str = "test_world",
    title: str = "Test World",
    core_version: str = "9.269",
    system: str = "dnd5e",
    system_version: str = "1.6.3",
    background: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "name": name,
        "title": title,
        "description": "Synthetic FVTT v9 test world",
        "version": "1.0.0",
        "minimumCoreVersion": "9.238",
        "compatibleCoreVersion": core_version,
        "coreVersion": core_version,
        "system": system,
        "systemVersion": system_version,
        "packs": [],
        "scripts": [],
        "styles": [],
    }
    if background is not None:
        doc["background"] = background
    if extra:
        doc.update(extra)
    return doc


def make_v14_world_json(
    *,
    world_id: str = "test_v14",
    title: str = "Test v14 World",
    core_version: str = "14.369",
    system: str = "dnd5e",
    system_version: str = "6.0.6",
    background: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "id": world_id,
        "name": world_id,
        "title": title,
        "coreVersion": core_version,
        "compatibility": {"minimum": "14", "verified": core_version},
        "system": system,
        "systemVersion": system_version,
        "packs": [],
    }
    if background is not None:
        doc["background"] = background
    if extra:
        doc.update(extra)
    return doc


def make_wall(
    wall_id: str,
    c: list[int | float],
    *,
    move: int = 20,
    sight: int = 20,
    light: int = 20,
    sound: int = 20,
    door: int = 0,
    ds: int = 0,
) -> dict[str, Any]:
    return {
        "_id": wall_id,
        "c": c,
        "move": move,
        "sight": sight,
        "light": light,
        "sound": sound,
        "door": door,
        "ds": ds,
        "dir": 0,
    }


def make_light(
    light_id: str,
    x: float,
    y: float,
    *,
    bright: float = 20,
    dim: float = 40,
    angle: float = 360,
    hidden: bool = False,
    color: str = "#ffddaa",
) -> dict[str, Any]:
    return {
        "_id": light_id,
        "x": x,
        "y": y,
        "rotation": 0,
        "hidden": hidden,
        "walls": True,
        "vision": False,
        "config": {
            "bright": bright,
            "dim": dim,
            "angle": angle,
            "color": color,
            "alpha": 0.5,
        },
    }


def make_tile(
    tile_id: str,
    img: str,
    *,
    x: float = 0,
    y: float = 0,
    width: float = 150,
    height: float = 150,
    rotation: float = 0,
    z: int = 100,
    hidden: bool = False,
) -> dict[str, Any]:
    return {
        "_id": tile_id,
        "img": img,
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "rotation": rotation,
        "z": z,
        "hidden": hidden,
        "locked": False,
        "alpha": 1.0,
    }


def make_v9_token(
    token_id: str,
    name: str,
    *,
    actor_id: str | None,
    img: str = "",
    x: float = 300,
    y: float = 300,
    width: float = 1,
    height: float = 1,
    scale: float = 1.0,
    rotation: float = 0.0,
    hidden: bool = False,
    disposition: int = -1,
    vision: bool = False,
    dim_sight: float = 0.0,
    bright_sight: float = 0.0,
    sight_angle: float = 360.0,
) -> dict[str, Any]:
    return {
        "_id": token_id,
        "name": name,
        "actorId": actor_id,
        "actorLink": False,
        "img": img,
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "scale": scale,
        "rotation": rotation,
        "hidden": hidden,
        "disposition": disposition,
        "vision": vision,
        "dimSight": dim_sight,
        "brightSight": bright_sight,
        "sightAngle": sight_angle,
    }


def make_v9_scene(
    scene_id: str,
    name: str,
    *,
    active: bool = True,
    width: int = 3000,
    height: int = 2100,
    grid: int = 150,
    grid_type: int = 1,
    grid_distance: float = 5,
    grid_units: str = "ft",
    grid_color: str = "#000000",
    grid_alpha: float = 0.2,
    shift_x: int = 0,
    shift_y: int = 0,
    img: str | None = None,
    foreground: str | None = None,
    folder: str | None = None,
    tokens: list[dict[str, Any]] | None = None,
    walls: list[dict[str, Any]] | None = None,
    lights: list[dict[str, Any]] | None = None,
    tiles: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "_id": scene_id,
        "name": name,
        "active": active,
        "navigation": True,
        "width": width,
        "height": height,
        "padding": 0.0,
        "shiftX": shift_x,
        "shiftY": shift_y,
        "grid": grid,
        "gridType": grid_type,
        "gridDistance": grid_distance,
        "gridUnits": grid_units,
        "gridColor": grid_color,
        "gridAlpha": grid_alpha,
        "img": img,
        "foreground": foreground,
        "folder": folder,
        "tokenVision": True,
        "globalLight": False,
        "tokens": tokens or [],
        "walls": walls or [],
        "lights": lights or [],
        "tiles": tiles or [],
        "notes": [],
        "sounds": [],
        "drawings": [],
        "templates": [],
    }
    return doc


def make_armor_item(
    item_id: str,
    name: str,
    *,
    armor_type: str = "medium",
    armor_value: int = 15,
    dex_cap: int | None = 2,
    equipped: bool = True,
    v14: bool = False,
) -> dict[str, Any]:
    if v14:
        return {
            "_id": item_id,
            "name": name,
            "type": "equipment",
            "system": {
                "equipped": equipped,
                "armor": {"type": armor_type, "value": armor_value, "dex": dex_cap},
                "type": {"value": armor_type},
            },
        }
    return {
        "_id": item_id,
        "name": name,
        "type": "equipment",
        "data": {
            "equipped": equipped,
            "armor": {"type": armor_type, "value": armor_value, "dex": dex_cap},
        },
    }


def make_v9_actor(
    actor_id: str,
    name: str,
    *,
    actor_type: str = "character",
    img: str = "",
    token_img: str = "",
    token_width: float = 1,
    token_height: float = 1,
    token_scale: float = 1.0,
    ac_flat: int | None = 15,
    ac_calc: str = "flat",
    hp_value: int | None = 30,
    hp_max: int | None = 30,
    level: int | None = 3,
    cr: float | str | None = 1,
    abilities: dict[str, int] | None = None,
    biography: str = "",
    folder: str | None = None,
    items: list[dict[str, Any]] | None = None,
    extra_details: dict[str, Any] | None = None,
    extra_token: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ab_vals = abilities or {"str": 10, "dex": 14, "con": 12, "int": 10, "wis": 12, "cha": 10}
    ab_block = {k: {"value": v, "mod": (v - 10) // 2} for k, v in ab_vals.items()}
    details: dict[str, Any] = {"biography": {"value": biography}}
    if actor_type == "character" and level is not None:
        details["level"] = level
    if actor_type == "npc" and cr is not None:
        details["cr"] = cr
    if extra_details:
        details.update(extra_details)

    token_cfg: dict[str, Any] = {
        "name": name,
        "img": token_img or img,
        "width": token_width,
        "height": token_height,
        "scale": token_scale,
        "actorLink": actor_type == "character",
        "disposition": 1 if actor_type == "character" else -1,
    }
    if extra_token:
        token_cfg.update(extra_token)

    return {
        "_id": actor_id,
        "name": name,
        "type": actor_type,
        "img": img,
        "folder": folder,
        "data": {
            "abilities": ab_block,
            "attributes": {
                "hp": {"value": hp_value, "max": hp_max},
                "ac": {"flat": ac_flat, "calc": ac_calc},
            },
            "details": details,
        },
        "token": token_cfg,
        "items": items or [],
    }


def make_folder(folder_id: str, name: str, folder_type: str = "Actor", parent: str | None = None) -> dict[str, Any]:
    return {
        "_id": folder_id,
        "name": name,
        "type": folder_type,
        "parent": parent,
        "folder": parent,
        "sorting": "a",
    }


def build_v9_world(
    target_dir: Path,
    *,
    world_json: dict[str, Any] | None = None,
    scenes: Sequence[dict[str, Any]] = (),
    actors: Sequence[dict[str, Any]] = (),
    folders: Sequence[dict[str, Any]] | None = None,
    items: Sequence[dict[str, Any]] | None = None,
    extra_dbs: dict[str, Sequence[dict[str, Any]]] | None = None,
    raw_db_lines: dict[str, Sequence[bytes]] | None = None,
    assets: dict[str, bytes] | None = None,
    create_data_dir: bool = True,
) -> Path:
    """Create an unpacked FVTT v9 world directory and return the path to `world.json`."""
    target_dir.mkdir(parents=True, exist_ok=True)
    wj_path = target_dir / "world.json"
    if world_json is not None:
        write_json_file(wj_path, world_json)

    if create_data_dir:
        data_dir = target_dir / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        write_nedb_file(
            data_dir / "scenes.db",
            scenes,
            raw_lines=raw_db_lines.get("scenes.db") if raw_db_lines else None,
        )
        write_nedb_file(
            data_dir / "actors.db",
            actors,
            raw_lines=raw_db_lines.get("actors.db") if raw_db_lines else None,
        )
        if folders is not None:
            write_nedb_file(data_dir / "folders.db", folders)
        if items is not None:
            write_nedb_file(data_dir / "items.db", items)
        if extra_dbs:
            for db_name, recs in extra_dbs.items():
                write_nedb_file(data_dir / db_name, recs)

    if assets:
        for rel, payload in assets.items():
            ap = target_dir / rel
            ap.parent.mkdir(parents=True, exist_ok=True)
            ap.write_bytes(payload)

    return wj_path


def _v14_level_from_scene(scene: dict[str, Any], level_id: str = "defaultLevel0000") -> tuple[dict[str, Any], dict[str, Any]]:
    """Split a v9-like scene dict into v14 `!scenes!` doc + `!scenes.levels!` doc."""
    sid = scene["_id"]
    fg = scene.get("foreground")
    fg_val = {"src": fg} if isinstance(fg, str) and fg else fg
    level_doc = {
        "_id": level_id,
        "name": "Level 1",
        "background": {"src": scene.get("img")},
        "foreground": fg_val,
        "width": scene.get("width", 3000),
        "height": scene.get("height", 2100),
    }
    scene_doc = {
        "_id": sid,
        "name": scene.get("name", "Scene"),
        "active": scene.get("active", True),
        "navigation": scene.get("navigation", True),
        "width": scene.get("width", 3000),
        "height": scene.get("height", 2100),
        "padding": scene.get("padding", 0.0),
        "shiftX": scene.get("shiftX", 0),
        "shiftY": scene.get("shiftY", 0),
        "grid": {
            "size": scene.get("grid", 150),
            "type": scene.get("gridType", 1),
            "distance": scene.get("gridDistance", 5),
            "units": scene.get("gridUnits", "ft"),
            "color": scene.get("gridColor", "#000000"),
            "alpha": scene.get("gridAlpha", 0.2),
        },
        "folder": scene.get("folder"),
        "levels": [level_id],
        "initialLevel": level_id,
        "tokenVision": scene.get("tokenVision", True),
        "globalLight": scene.get("globalLight", False),
    }
    return scene_doc, level_doc


def _v14_token_from_token(tok: dict[str, Any]) -> dict[str, Any]:
    out = dict(tok)
    img = out.pop("img", "")
    out["texture"] = {"src": img, "scaleX": out.get("scale", 1.0), "scaleY": out.get("scale", 1.0)}
    if "vision" in out or "dimSight" in out or "brightSight" in out:
        sight_range = max(float(out.get("dimSight", 0)), float(out.get("brightSight", 0)))
        out["sight"] = {
            "enabled": bool(out.get("vision", False)),
            "range": sight_range,
            "angle": float(out.get("sightAngle", 360.0)),
        }
    return out


def build_v14_world(
    target_dir: Path,
    *,
    world_json: dict[str, Any],
    scenes: Sequence[dict[str, Any]] = (),
    actors: Sequence[dict[str, Any]] = (),
    folders: Sequence[dict[str, Any]] = (),
    scene_wal_ops: Sequence[tuple[int, Sequence[tuple[str, bytes, bytes]]]] = (),
    actor_wal_ops: Sequence[tuple[int, Sequence[tuple[str, bytes, bytes]]]] = (),
    assets: dict[str, bytes] | None = None,
    also_nedb: bool = False,
) -> Path:
    """Create an unpacked FVTT v14 world directory with genuine LevelDB SSTables + optional WAL."""
    target_dir.mkdir(parents=True, exist_ok=True)
    wj_path = write_json_file(target_dir / "world.json", world_json)
    data_dir = target_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    seq = 1
    scene_recs: list[tuple[bytes, int, int, bytes]] = []
    for sc in scenes:
        sid = sc["_id"]
        sdoc, ldoc = _v14_level_from_scene(sc)
        scene_recs.append((f"!scenes!{sid}".encode("utf-8"), seq, 1, json.dumps(sdoc, ensure_ascii=False).encode("utf-8")))
        seq += 1
        scene_recs.append((f"!scenes.levels!{sid}.{ldoc['_id']}".encode("utf-8"), seq, 1, json.dumps(ldoc, ensure_ascii=False).encode("utf-8")))
        seq += 1
        for tok in sc.get("tokens", []):
            v14_tok = _v14_token_from_token(tok)
            scene_recs.append((f"!scenes.tokens!{sid}.{tok['_id']}".encode("utf-8"), seq, 1, json.dumps(v14_tok, ensure_ascii=False).encode("utf-8")))
            seq += 1
        for w in sc.get("walls", []):
            scene_recs.append((f"!scenes.walls!{sid}.{w['_id']}".encode("utf-8"), seq, 1, json.dumps(w, ensure_ascii=False).encode("utf-8")))
            seq += 1
        for t in sc.get("tiles", []):
            v14_tile = dict(t)
            if "img" in v14_tile and "texture" not in v14_tile:
                v14_tile["texture"] = {"src": v14_tile["img"]}
            scene_recs.append((f"!scenes.tiles!{sid}.{t['_id']}".encode("utf-8"), seq, 1, json.dumps(v14_tile, ensure_ascii=False).encode("utf-8")))
            seq += 1
        for lt in sc.get("lights", []):
            scene_recs.append((f"!scenes.lights!{sid}.{lt['_id']}".encode("utf-8"), seq, 1, json.dumps(lt, ensure_ascii=False).encode("utf-8")))
            seq += 1

    write_leveldb_collection(data_dir / "scenes", ldb_records=scene_recs, wal_batches=scene_wal_ops)

    actor_recs: list[tuple[bytes, int, int, bytes]] = []
    for act in actors:
        aid = act["_id"]
        # Accept either pre-built v14 schema (`system`/`prototypeToken`) or convert v9-style
        if "system" in act or "prototypeToken" in act:
            adoc = dict(act)
            items = adoc.pop("items", [])
        else:
            adoc = {
                "_id": aid,
                "name": act["name"],
                "type": act["type"],
                "img": act.get("img", ""),
                "folder": act.get("folder"),
                "system": act.get("data", {}),
                "prototypeToken": _v14_token_from_token(act.get("token", {})),
            }
            items = act.get("items", [])
        actor_recs.append((f"!actors!{aid}".encode("utf-8"), seq, 1, json.dumps(adoc, ensure_ascii=False).encode("utf-8")))
        seq += 1
        for item in items:
            iid = item["_id"]
            actor_recs.append((f"!actors.items!{aid}.{iid}".encode("utf-8"), seq, 1, json.dumps(item, ensure_ascii=False).encode("utf-8")))
            seq += 1

    write_leveldb_collection(data_dir / "actors", ldb_records=actor_recs, wal_batches=actor_wal_ops)

    if folders:
        folder_recs = [
            (f"!folders!{f['_id']}".encode("utf-8"), idx + 1, 1, json.dumps(f, ensure_ascii=False).encode("utf-8"))
            for idx, f in enumerate(folders)
        ]
        write_leveldb_collection(data_dir / "folders", ldb_records=folder_recs)

    if also_nedb:
        write_nedb_file(data_dir / "scenes.db", scenes)
        write_nedb_file(data_dir / "actors.db", actors)

    if assets:
        for rel, payload in assets.items():
            ap = target_dir / rel
            ap.parent.mkdir(parents=True, exist_ok=True)
            ap.write_bytes(payload)

    return wj_path


def pack_world_zip(
    src_dir: Path,
    zip_path: Path,
    *,
    depth: int = 0,
    root_name: str | None = None,
    macosx_junk: bool = False,
    ds_store: bool = False,
    extra_entries: dict[str, bytes] | None = None,
) -> Path:
    """Package an unpacked FVTT world directory into a `.zip` at depth 0, 1, or 2."""
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    prefix = ""
    if depth == 1:
        prefix = f"{root_name or src_dir.name}/"
    elif depth == 2:
        prefix = f"{root_name or 'outer/inner'}/"
        if "/" not in prefix.rstrip("/"):
            prefix = f"outer/{root_name or src_dir.name}/"

    with zipfile.ZipFile(zip_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for item in sorted(src_dir.rglob("*"), key=lambda p: p.as_posix()):
            if not item.is_file():
                continue
            rel = item.relative_to(src_dir).as_posix()
            zf.write(item, arcname=prefix + rel)

        if macosx_junk:
            zf.writestr("__MACOSX/._world.json", b"\x00\x05\x16\x07AppleDoubleJunk\xff\xfe")
            zf.writestr(f"__MACOSX/{prefix}data/._scenes.db", b"\x00\x05\x16\x07AppleDoubleJunk\xff\xfe")
        if ds_store:
            zf.writestr(".DS_Store", b"\x00\x00\x00\x01Bud1")
            if prefix:
                zf.writestr(f"{prefix}.DS_Store", b"\x00\x00\x00\x01Bud1")
        if extra_entries:
            for arc, payload in extra_entries.items():
                zf.writestr(arc, payload)

    return zip_path
