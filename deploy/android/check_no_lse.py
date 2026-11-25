"""Scan .so/.aar/.apk files for inline Armv8.1 LSE atomic instructions (DT-9).

Usage:
    python check_no_lse.py <file.so|file.aar|file.apk>

Each arm64 ``.so`` found is parsed as an ELF and only its executable sections
(all ``SHF_EXECINSTR`` sections, found through the section headers, including
``.text`` and ``.text.*``) are scanned for 4-byte little-endian
instruction words matching::

    LDADD/SWP family: (word & 0x3f200c00) == 0x38200000
    CAS family:       (word & 0x3fa07c00) == 0x08a07c00

(same masks as used to count the ~188 inline LSE atomics in the stock Maven
AAR; the measured crash was word ``0xf8f60108`` == LDADDAL in
``libexecutorch_jni.so`` at offset ``0x1cff90`` on a Galaxy M31). Scanning
whole executable ``PT_LOAD`` segments instead would also count LSE-looking
byte patterns inside string/rodata data, so data outside executable sections
must not be scanned. When an ELF has no section headers at all, the executable
``PT_LOAD`` segments are used as a fallback so minimal synthetic files keep
working.

Words that fall inside outline-atomics helper functions (``.symtab``/``.dynsym``
symbols starting with ``__aarch64_cas``, ``__aarch64_swp``, ``__aarch64_ldadd``,
``__aarch64_ldclr``, ``__aarch64_ldeor`` or ``__aarch64_ldset``) are excluded
from the inline count and reported separately, because they run only after a
runtime CPU check. When a library is stripped (no symbol table), an LSE word
immediately followed by ``RET`` (``0xd65f03c0``) is treated as an
outline-atomic helper body for the same reason; any other LSE word in
``.text`` still counts as inline.

Non-ELF inputs are scanned as raw byte strings so tiny synthetic files can
be tested without a real ELF. Counts are printed per library. The exit code
is 1 if any LSE word is found in ``libexecutorch`` or ``libexecutorch_jni``,
0 otherwise.
"""

import argparse
import struct
import zipfile
from pathlib import Path

# (mask, value) per family; keep in sync with tests/test_check_no_lse.py.
LDADD_SWP_MASK = 0x3F200C00
LDADD_SWP_VALUE = 0x38200000
CAS_MASK = 0x3FA07C00
CAS_VALUE = 0x08A07C00

EM_AARCH64 = 183
PT_LOAD = 1
PF_X = 1
ELF_MAGIC = b"\x7fELF"

RET_WORD = 0xD65F03C0
SHF_EXECINSTR = 0x4

SHT_SYMTAB = 2
SHT_STRTAB = 3
SHT_DYNSYM = 11

HELPER_PREFIXES = (
    "__aarch64_cas",
    "__aarch64_swp",
    "__aarch64_ldadd",
    "__aarch64_ldclr",
    "__aarch64_ldeor",
    "__aarch64_ldset",
)

EXECUTORCH_BASENAMES = ("libexecutorch.so", "libexecutorch_jni.so")


def is_ldadd_swp_word(word):
    """True if *word* is an inline LDADD/SWP-family LSE atomic."""
    return (word & LDADD_SWP_MASK) == LDADD_SWP_VALUE


def is_cas_word(word):
    """True if *word* is an inline CAS-family LSE atomic."""
    return (word & CAS_MASK) == CAS_VALUE


def is_lse_word(word):
    """True if *word* is any inline LSE atomic covered by the masks."""
    return is_ldadd_swp_word(word) or is_cas_word(word)


def count_lse_words(data):
    """Count LSE words in raw little-endian bytes.

    Returns ``(total, ldadd_swp, cas)``. Trailing bytes that do not form a
    full 4-byte word are ignored.
    """
    total = ldadd_swp = cas = 0
    usable = len(data) - (len(data) % 4)
    for (word,) in struct.iter_unpack("<I", data[:usable]):
        if is_ldadd_swp_word(word):
            ldadd_swp += 1
        elif is_cas_word(word):
            cas += 1
        else:
            continue
        total += 1
    return total, ldadd_swp, cas


def _executable_pt_load_segments(data):
    """Return executable ``PT_LOAD`` ranges as ``(file_offset, vaddr, size)``."""
    (phoff,) = struct.unpack_from("<Q", data, 32)
    (phentsize,) = struct.unpack_from("<H", data, 54)
    (phnum,) = struct.unpack_from("<H", data, 56)
    if phentsize < 56 or phoff == 0:
        return None
    segments = []
    for i in range(phnum):
        offset = phoff + i * phentsize
        if offset + 56 > len(data):
            break
        p_type, p_flags = struct.unpack_from("<II", data, offset)
        if p_type != PT_LOAD or not (p_flags & PF_X):
            continue
        (p_offset,) = struct.unpack_from("<Q", data, offset + 8)
        (p_vaddr,) = struct.unpack_from("<Q", data, offset + 16)
        (p_filesz,) = struct.unpack_from("<Q", data, offset + 32)
        if p_offset >= len(data):
            continue
        size = min(p_offset + p_filesz, len(data)) - p_offset
        if size > 0:
            segments.append((p_offset, p_vaddr, size))
    return segments


def _section_names(data, sections):
    """Return section names aligned with *sections*, or ``[]`` if unavailable."""
    if not sections or len(data) < 64 or data[:4] != ELF_MAGIC:
        return []
    if data[4] != 2 or data[5] != 1:
        return []
    (shstrndx,) = struct.unpack_from("<H", data, 62)
    if shstrndx == 0xFFFF and sections:
        # SHN_XINDEX: real index is sh_link of section 0.
        shstrndx = sections[0][6]
    if shstrndx >= len(sections):
        return []
    str_off = sections[shstrndx][4]
    str_size = sections[shstrndx][5]
    if str_off >= len(data) or str_size == 0:
        return []
    table = data[str_off : str_off + str_size]
    return [_read_cstring(table, sh[0]) for sh in sections]


def _executable_segments_with_vaddr(data):
    """Return ranges to scan as ``(file_offset, vaddr, size)``.

    All ``SHF_EXECINSTR`` sections (found through the section headers,
    including ``.text`` and ``.text.*``) are returned when sections exist,
    so LSE code in any executable section is scanned while LSE-looking
    bytes in string/rodata data are never counted (R2C-12).
    Executable ``PT_LOAD`` segments are used when there are no section
    headers at all (minimal synthetic files).

    None means "not a little-endian 64-bit AArch64 ELF". For a non-AArch64
    ELF returns an empty list.
    """
    if len(data) < 64 or data[:4] != ELF_MAGIC:
        return None
    if data[4] != 2 or data[5] != 1:  # ELFCLASS64, ELFDATA2LSB
        return None
    (machine,) = struct.unpack_from("<H", data, 18)
    if machine != EM_AARCH64:
        return []
    sections = _elf64_section_headers(data)
    if sections:
        exec_sections = []
        for sh in sections:
            _name, _type, sh_flags, sh_addr, sh_offset, sh_size, _link, _info, _align, _entsize = sh
            if not (sh_flags & SHF_EXECINSTR):
                continue
            if sh_offset >= len(data):
                continue
            size = min(sh_offset + sh_size, len(data)) - sh_offset
            if size > 0:
                exec_sections.append((sh_offset, sh_addr if sh_addr else sh_offset, size))
        if exec_sections:
            return exec_sections
    segments = _executable_pt_load_segments(data)
    if segments is None:
        return None
    return segments


def executable_segment_ranges(data):
    """Return the ranges scanned for an arm64 ELF64, or None.

    Normally just the ``.text`` section bytes. None means "not a
    little-endian 64-bit AArch64 ELF" (caller may fall back to scanning the
    raw bytes). For a non-AArch64 ELF returns an empty list.
    """
    segments = _executable_segments_with_vaddr(data)
    if segments is None:
        return None
    return [data[off : off + size] for off, _vaddr, size in segments]


def _elf64_section_headers(data):
    """Return section header tuples for an ELF64, or [] if there are none."""
    if len(data) < 64 or data[:4] != ELF_MAGIC:
        return []
    if data[4] != 2 or data[5] != 1:
        return []
    (shoff,) = struct.unpack_from("<Q", data, 40)
    (shentsize,) = struct.unpack_from("<H", data, 58)
    (shnum,) = struct.unpack_from("<H", data, 60)
    if shentsize < 64 or shoff == 0:
        return []
    sections = []

    def read_at(index):
        offset = shoff + index * shentsize
        if offset + 64 > len(data):
            return None
        return struct.unpack_from("<IIQQQQIIQQ", data, offset)

    first = read_at(0)
    if first is None:
        return []
    count = shnum
    if count == 0:
        # Extended numbering: real count is sh_size of section 0.
        count = first[5]
    for i in range(count):
        entry = read_at(i)
        if entry is None:
            break
        sections.append(entry)
    return sections


def _read_cstring(table, offset):
    """Read a NUL-terminated string from a string table."""
    if offset < 0 or offset >= len(table):
        return ""
    end = table.find(b"\x00", offset)
    if end == -1:
        end = len(table)
    return table[offset:end].decode("utf-8", errors="ignore")


def _parse_helper_ranges(data):
    """Return ``(has_symbol_table, [(vaddr_start, vaddr_end, name)])``.

    Reads ``.symtab`` and ``.dynsym`` symbol names and keeps the
    outline-atomics helper functions. ``has_symbol_table`` is True when a
    SYMTAB or DYNSYM section exists, even if no helper was found.
    """
    segments = _executable_segments_with_vaddr(data)
    if segments is None:
        return False, []
    sections = _elf64_section_headers(data)
    if not sections:
        return False, []
    has_table = False
    helpers = []
    for sh in sections:
        _name, sh_type, _flags, _addr, sh_offset, sh_size, sh_link, _info, _align, sh_entsize = sh
        if sh_type not in (SHT_SYMTAB, SHT_DYNSYM):
            continue
        has_table = True
        if sh_link >= len(sections):
            continue
        str_off = sections[sh_link][4]
        str_size = sections[sh_link][5]
        table = data[str_off : str_off + str_size] if str_off < len(data) else b""
        entsize = sh_entsize if sh_entsize else 24
        if entsize < 24:
            continue
        count = sh_size // entsize
        for i in range(count):
            off = sh_offset + i * entsize
            if off + 24 > len(data):
                break
            st_name, _st_info, _st_other, _st_shndx, st_value, st_size = struct.unpack_from(
                "<IBBHQQ", data, off
            )
            if st_name == 0 or st_value == 0 or st_size == 0:
                continue
            name = _read_cstring(table, st_name)
            if name.startswith(HELPER_PREFIXES):
                helpers.append((st_value, st_value + st_size, name))
    return has_table, helpers


def _next_word_is_ret(data, file_off, delta, size):
    """True if the word after the one at *delta* in its range is ``RET``."""
    if delta + 8 > size:
        return False
    offset = file_off + delta + 4
    if offset + 4 > len(data):
        return False
    (next_word,) = struct.unpack_from("<I", data, offset)
    return next_word == RET_WORD


def count_lse_detailed(data):
    """Count LSE words in executable sections with outline-atomic helper exclusion.

    Returns ``(total, ldadd_swp, cas, helper_total, helper_ldadd, helper_cas,
    has_symbol_table)`` where the first three exclude helper hits. Helpers
    are excluded by symbol when a symbol table exists; when the library is
    stripped, an LSE word immediately followed by ``RET`` (``0xd65f03c0``)
    is treated as an outline-atomic helper body.
    """
    segments = _executable_segments_with_vaddr(data)
    if segments is None:
        total, ldadd_swp, cas = count_lse_words(data)
        return total, ldadd_swp, cas, 0, 0, 0, False
    has_table, helpers = _parse_helper_ranges(data)
    total = ldadd_swp = cas = 0
    helper_total = helper_ldadd = helper_cas = 0
    for file_off, vaddr, size in segments:
        for delta in range(0, size - (size % 4), 4):
            (word,) = struct.unpack_from("<I", data, file_off + delta)
            is_ldadd = is_ldadd_swp_word(word)
            is_cas = is_cas_word(word)
            if not (is_ldadd or is_cas):
                continue
            word_vaddr = vaddr + delta
            if has_table:
                in_helper = any(start <= word_vaddr < end for start, end, _name in helpers)
            else:
                in_helper = _next_word_is_ret(data, file_off, delta, size)
            if in_helper:
                helper_total += 1
                if is_ldadd:
                    helper_ldadd += 1
                else:
                    helper_cas += 1
            else:
                total += 1
                if is_ldadd:
                    ldadd_swp += 1
                else:
                    cas += 1
    return total, ldadd_swp, cas, helper_total, helper_ldadd, helper_cas, has_table


def count_lse_in_so_bytes(data):
    """Count LSE words in executable sections of one ``.so`` byte string.

    Non-ELF input is scanned as raw bytes. Words inside outline-atomics
    helper functions are excluded.
    """
    total, ldadd_swp, cas, _h_total, _h_ldadd, _h_cas, _has = count_lse_detailed(data)
    return total, ldadd_swp, cas


def is_executorch_lib(name):
    """True if finding LSE in *name* must fail the scan."""
    base = name.replace("\\", "/").rstrip("/").split("/")[-1]
    return base in EXECUTORCH_BASENAMES or base.startswith("libexecutorch")


def is_arm64_so_entry(name):
    """True if an archive entry is an arm64 ``.so`` (ABI path aware).

    Entries with an explicit non-arm64 ABI directory (x86, x86_64,
    armeabi-v7a) are skipped; entries with no ABI directory are kept, because
    a bare ``.so`` input can only be the library the caller meant.
    """
    normalized = name.replace("\\", "/").lower()
    if not normalized.endswith(".so"):
        return False
    if "arm64-v8a" in normalized or "aarch64" in normalized:
        return True
    if "x86" in normalized or "armeabi" in normalized or "armv7" in normalized:
        return False
    return True


def _zip_so_entries(path):
    """Yield ``(entry_name, bytes)`` for every arm64 ``.so`` in a zip archive."""
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            if is_arm64_so_entry(name):
                yield name, archive.read(name)


def scan_path_detailed(path):
    """Return ``[(name, total, ldadd, cas, helper_total, helper_ldadd, helper_cas, has_symtab)]``."""
    target = Path(path)
    suffix = target.suffix.lower()
    results = []
    if suffix == ".so":
        results.append((target.name, *count_lse_detailed(target.read_bytes())))
        return results
    if suffix in (".aar", ".apk"):
        for name, data in _zip_so_entries(target):
            results.append((name, *count_lse_detailed(data)))
        return results
    raise ValueError("unsupported file type (expected .so/.aar/.apk): {}".format(path))


def scan_path(path):
    """Return ``[(lib_name, total, ldadd_swp, cas)]`` for a ``.so/.aar/.apk`` path."""
    return [(name, total, ldadd_swp, cas) for name, total, ldadd_swp, cas, *_rest in scan_path_detailed(path)]


def find_lse_in_path(path, stream=None):
    """Print per-library counts; return True if any libexecutorch has LSE."""
    results = scan_path_detailed(path)
    failed = False
    for name, total, ldadd_swp, cas, helper_total, helper_ldadd, helper_cas, has_symtab in results:
        if has_symtab:
            print(
                "{}: {} LSE atomic word(s) (LDADD/SWP={}, CAS={}); outline-atomic helper hit(s)={} (LDADD/SWP={}, CAS={} excluded)".format(
                    name, total, ldadd_swp, cas, helper_total, helper_ldadd, helper_cas
                ),
                file=stream,
            )
        else:
            print(
                "{}: {} LSE atomic word(s) (LDADD/SWP={}, CAS={}); no symbol table (stripped); LSE word followed by RET counted as outline-atomic helper ({} excluded)".format(
                    name, total, ldadd_swp, cas, helper_total
                ),
                file=stream,
            )
        if total and is_executorch_lib(name):
            failed = True
    if not results:
        print("no .so libraries found in {}".format(path), file=stream)
    return failed


def main(argv=None):
    parser = argparse.ArgumentParser(description="Check for inline LSE atomics in an .so/.aar/.apk.")
    parser.add_argument("path", help="path to a .so, .aar, or .apk file")
    args = parser.parse_args(argv)
    target = Path(args.path)
    if not target.is_file():
        parser.error("file not found: {}".format(target))
    try:
        failed = find_lse_in_path(target)
    except (zipfile.BadZipFile, OSError, struct.error) as error:
        print("error scanning {}: {}".format(target, error), file=__import__("sys").stderr)
        return 2
    if failed:
        print("FAIL: inline LSE atomics found in libexecutorch/libexecutorch_jni")
        return 1
    print("OK: no inline LSE atomics in libexecutorch/libexecutorch_jni")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
