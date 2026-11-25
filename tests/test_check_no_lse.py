"""Tests for deploy/android/check_no_lse.py (DT-9).

The scanner is exercised with tiny synthetic inputs: raw little-endian
instruction words, a minimal hand-built ELF64/AArch64 file, and zip archives
standing in for an AAR. No real ExecuTorch binary is needed.
"""
from __future__ import annotations

import importlib.util
import io
import struct
import zipfile
from pathlib import Path

MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "deploy" / "android" / "check_no_lse.py"
)

_spec = importlib.util.spec_from_file_location("check_no_lse", MODULE_PATH)
check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check)

# Word seen in the Galaxy M31 crash: LDADDAL, SIGILL at libexecutorch_jni.so
# offset 0x1cff90.
MEASURED_LDADDAL = 0xF8F60108
CAS_WORD = 0x08A07C00
NOP = 0xD503201F
RET = 0xD65F03C0

ELF_HEADER_SIZE = 64
PHDR_SIZE = 56
PT_LOAD = 1
PF_X = 1
PF_R = 4


def word(value: int) -> bytes:
    return struct.pack("<I", value)


def build_elf64_aarch64(exec_payload: bytes, data_payload: bytes, machine: int = 183) -> bytes:
    """Minimal ELF64 with one executable and one read-only PT_LOAD segment."""
    ident = bytearray(16)
    ident[:4] = b"\x7fELF"
    ident[4] = 2  # ELFCLASS64
    ident[5] = 1  # ELFDATA2LSB
    ident[6] = 1  # EV_CURRENT
    header = bytes(ident) + struct.pack(
        "<HHIQQQIHHHHHH",
        2,  # e_type = ET_EXEC
        machine,
        1,  # e_version
        0,  # e_entry
        ELF_HEADER_SIZE,  # e_phoff
        0,  # e_shoff
        0,  # e_flags
        ELF_HEADER_SIZE,  # e_ehsize
        PHDR_SIZE,  # e_phentsize
        2,  # e_phnum
        0,  # e_shentsize
        0,  # e_shnum
        0,  # e_shstrndx
    )
    exec_offset = ELF_HEADER_SIZE + 2 * PHDR_SIZE
    data_offset = exec_offset + len(exec_payload)
    exec_phdr = struct.pack(
        "<IIQQQQQQ",
        PT_LOAD,
        PF_X,
        exec_offset,
        0,
        0,
        len(exec_payload),
        len(exec_payload),
        4,
    )
    data_phdr = struct.pack(
        "<IIQQQQQQ",
        PT_LOAD,
        PF_R,
        data_offset,
        0,
        0,
        len(data_payload),
        len(data_payload),
        4,
    )
    return header + exec_phdr + data_phdr + exec_payload + data_payload


SHDR_SIZE = 64
SHT_NULL = 0
SHT_SYMTAB = 2
SHT_STRTAB = 3
SHT_DYNSYM = 11


def _build_symtab_entries(entries, strtab):
    """Pack (st_name_offset, st_value, st_size) entries plus a null symbol."""
    blob = bytearray()
    blob += struct.pack("<IBBHQQ", 0, 0, 0, 0, 0, 0)
    for st_name, st_value, st_size in entries:
        blob += struct.pack("<IBBHQQ", st_name, 0, 0, 1, st_value, st_size)
    return bytes(blob)


def build_elf_with_symtab(
    exec_payload,
    helpers,
    sym_type=SHT_SYMTAB,
    machine=183,
):
    """ELF64 with one exec segment, a symtab (+strtab) and section headers.

    ``helpers`` is a list of ``(name, vaddr_offset_from_exec_start, size)``.
    The exec segment vaddr equals its file offset, so vaddr = exec_offset + offset.
    """
    ident = bytearray(16)
    ident[:4] = b"\x7fELF"
    ident[4] = 2  # ELFCLASS64
    ident[5] = 1  # ELFDATA2LSB
    ident[6] = 1  # EV_CURRENT
    exec_offset = ELF_HEADER_SIZE + PHDR_SIZE
    data_offset = exec_offset + len(exec_payload)

    strtab = bytearray(b"\x00")
    name_offsets = {}
    for name, _off, _size in helpers:
        name_offsets[name] = len(strtab)
        strtab += name.encode("utf-8") + b"\x00"
    strtab = bytes(strtab)

    entries = [(name_offsets[name], exec_offset + off, size) for name, off, size in helpers]
    symtab = _build_symtab_entries(entries, strtab)

    shstrtab = b"\x00.symtab\x00.strtab\x00.shstrtab\x00"
    symtab_name_off = shstrtab.index(b".symtab")
    strtab_name_off = shstrtab.index(b".strtab")
    shstrtab_name_off = shstrtab.index(b".shstrtab")

    symtab_offset = data_offset
    strtab_offset = symtab_offset + len(symtab)
    shstrtab_offset = strtab_offset + len(strtab)
    shoff = shstrtab_offset + len(shstrtab)
    e_shnum = 4

    header = bytes(ident) + struct.pack(
        "<HHIQQQIHHHHHH",
        2,  # e_type = ET_EXEC
        machine,
        1,  # e_version
        0,  # e_entry
        ELF_HEADER_SIZE,  # e_phoff
        shoff,  # e_shoff
        0,  # e_flags
        ELF_HEADER_SIZE,  # e_ehsize
        PHDR_SIZE,  # e_phentsize
        1,  # e_phnum
        SHDR_SIZE,  # e_shentsize
        e_shnum,  # e_shnum
        3,  # e_shstrndx
    )
    exec_phdr = struct.pack(
        "<IIQQQQQQ",
        PT_LOAD,
        PF_X,
        exec_offset,
        exec_offset,
        exec_offset,
        len(exec_payload),
        len(exec_payload),
        4,
    )

    def shdr(sh_name, sh_type, sh_flags, sh_addr, sh_offset, sh_size, sh_link, sh_info, sh_addralign, sh_entsize):
        return struct.pack("<IIQQQQIIQQ", sh_name, sh_type, sh_flags, sh_addr, sh_offset, sh_size, sh_link, sh_info, sh_addralign, sh_entsize)

    null_sh = shdr(0, SHT_NULL, 0, 0, 0, 0, 0, 0, 0, 0)
    sym_sh = shdr(symtab_name_off, sym_type, 0, 0, symtab_offset, len(symtab), 2, 1, 8, 24)
    str_sh = shdr(strtab_name_off, SHT_STRTAB, 0, 0, strtab_offset, len(strtab), 0, 0, 1, 0)
    shstr_sh = shdr(shstrtab_name_off, SHT_STRTAB, 0, 0, shstrtab_offset, len(shstrtab), 0, 0, 1, 0)
    return header + exec_phdr + exec_payload + symtab + strtab + shstrtab + null_sh + sym_sh + str_sh + shstr_sh


def build_elf_with_text(text_payload, rodata_payload=b"", helpers=None, sym_type=SHT_SYMTAB):
    """ELF64 with a ``.text`` section and an optional ``.rodata`` section.

    One executable ``PT_LOAD`` covers both sections, so LSE-looking bytes in
    ``.rodata`` sit inside an executable segment but outside ``.text``.

    ``helpers`` is None for a stripped library (no symbol table) or a list of
    ``(name, offset_in_text, size)`` for a library with a symbol table (an
    empty list still creates an empty symbol table).
    """
    ident = bytearray(16)
    ident[:4] = b"\x7fELF"
    ident[4] = 2  # ELFCLASS64
    ident[5] = 1  # ELFDATA2LSB
    ident[6] = 1  # EV_CURRENT
    text_offset = ELF_HEADER_SIZE + PHDR_SIZE
    rodata_offset = text_offset + len(text_payload)

    has_symtab = helpers is not None
    strtab = bytearray(b"\x00")
    name_offsets = {}
    if has_symtab:
        for name, _off, _size in helpers:
            name_offsets[name] = len(strtab)
            strtab += name.encode("utf-8") + b"\x00"
    strtab = bytes(strtab)
    entries = [(name_offsets[name], text_offset + off, size) for name, off, size in helpers] if has_symtab else []
    symtab = _build_symtab_entries(entries, strtab) if has_symtab else b""

    if has_symtab:
        shstrtab = b"\x00.text\x00.rodata\x00.symtab\x00.strtab\x00.shstrtab\x00"
    else:
        shstrtab = b"\x00.text\x00.rodata\x00.shstrtab\x00"
    text_name_off = shstrtab.index(b".text")
    rodata_name_off = shstrtab.index(b".rodata")
    shstrtab_name_off = shstrtab.index(b".shstrtab")

    cursor = rodata_offset + len(rodata_payload)
    symtab_offset = cursor
    cursor += len(symtab)
    strtab_offset = cursor
    cursor += len(strtab) if has_symtab else 0
    shstrtab_offset = cursor
    cursor += len(shstrtab)
    shoff = cursor

    if has_symtab:
        e_shnum = 6
        e_shstrndx = 5
        symtab_name_off = shstrtab.index(b".symtab")
        strtab_name_off = shstrtab.index(b".strtab")
    else:
        e_shnum = 4
        e_shstrndx = 3

    header = bytes(ident) + struct.pack(
        "<HHIQQQIHHHHHH",
        2,
        183,
        1,
        0,
        ELF_HEADER_SIZE,
        shoff,
        0,
        ELF_HEADER_SIZE,
        PHDR_SIZE,
        1,
        SHDR_SIZE,
        e_shnum,
        e_shstrndx,
    )
    exec_phdr = struct.pack(
        "<IIQQQQQQ",
        PT_LOAD,
        PF_X,
        text_offset,
        text_offset,
        text_offset,
        len(text_payload) + len(rodata_payload),
        len(text_payload) + len(rodata_payload),
        4,
    )

    def shdr(sh_name, sh_type, sh_flags, sh_addr, sh_offset, sh_size, sh_link, sh_info, sh_addralign, sh_entsize):
        return struct.pack("<IIQQQQIIQQ", sh_name, sh_type, sh_flags, sh_addr, sh_offset, sh_size, sh_link, sh_info, sh_addralign, sh_entsize)

    shdrs = b""
    shdrs += shdr(0, SHT_NULL, 0, 0, 0, 0, 0, 0, 0, 0)
    shdrs += shdr(text_name_off, 1, 0x6, text_offset, text_offset, len(text_payload), 0, 0, 4, 0)
    shdrs += shdr(rodata_name_off, 1, 0x2, rodata_offset, rodata_offset, len(rodata_payload), 0, 0, 1, 0)
    if has_symtab:
        shdrs += shdr(symtab_name_off, sym_type, 0, 0, symtab_offset, len(symtab), 4, 1, 8, 24)
        shdrs += shdr(strtab_name_off, SHT_STRTAB, 0, 0, strtab_offset, len(strtab), 0, 0, 1, 0)
    shdrs += shdr(shstrtab_name_off, SHT_STRTAB, 0, 0, shstrtab_offset, len(shstrtab), 0, 0, 1, 0)
    return header + exec_phdr + text_payload + rodata_payload + symtab + (strtab if has_symtab else b"") + shstrtab + shdrs


def test_masks_recognise_the_measured_instruction():
    assert check.is_ldadd_swp_word(MEASURED_LDADDAL)
    assert check.is_lse_word(MEASURED_LDADDAL)
    assert not check.is_cas_word(MEASURED_LDADDAL)


def test_cas_family_is_recognised():
    assert check.is_cas_word(CAS_WORD)
    assert check.is_lse_word(CAS_WORD)


def test_ordinary_instruction_is_not_lse():
    assert not check.is_lse_word(NOP)


def test_count_raw_words_and_trailing_bytes():
    data = word(NOP) + word(MEASURED_LDADDAL) + word(CAS_WORD) + b"\x01"
    total, ldadd_swp, cas = check.count_lse_words(data)
    assert (total, ldadd_swp, cas) == (2, 1, 1)


def test_count_lse_in_so_bytes_falls_back_to_raw_scan():
    # Not an ELF, so the whole byte string is scanned on 4-byte boundaries.
    assert check.count_lse_in_so_bytes(b"NOPE" + word(MEASURED_LDADDAL)) == (1, 1, 0)


def test_only_executable_segments_are_scanned():
    data = build_elf64_aarch64(word(MEASURED_LDADDAL), word(MEASURED_LDADDAL))
    ranges = check.executable_segment_ranges(data)
    assert ranges is not None
    assert len(ranges) == 1
    assert check.count_lse_in_so_bytes(data) == (1, 1, 0)


def test_non_aarch64_elf_is_ignored():
    data = build_elf64_aarch64(word(MEASURED_LDADDAL), b"", machine=62)
    assert check.executable_segment_ranges(data) == []
    assert check.count_lse_in_so_bytes(data) == (0, 0, 0)


def test_executorch_library_names_fail_the_scan(tmp_path):
    dirty = tmp_path / "libexecutorch_jni.so"
    dirty.write_bytes(word(MEASURED_LDADDAL))
    clean = tmp_path / "libother.so"
    clean.write_bytes(word(NOP))
    assert check.find_lse_in_path(dirty, stream=io.StringIO()) is True
    assert check.find_lse_in_path(clean, stream=io.StringIO()) is False


def test_scan_aar_keeps_only_arm64_entries(tmp_path):
    aar = tmp_path / "library.aar"
    with zipfile.ZipFile(aar, "w") as archive:
        archive.writestr("jni/arm64-v8a/libexecutorch.so", word(MEASURED_LDADDAL))
        archive.writestr("jni/x86_64/libexecutorch.so", word(MEASURED_LDADDAL))
        archive.writestr("classes.jar", b"")
    results = check.scan_path(aar)
    assert [name for name, *_ in results] == ["jni/arm64-v8a/libexecutorch.so"]
    assert check.find_lse_in_path(aar, stream=io.StringIO()) is True


def test_scan_aar_without_arm64_libraries_is_clean(tmp_path):
    aar = tmp_path / "library.aar"
    with zipfile.ZipFile(aar, "w") as archive:
        archive.writestr("jni/x86_64/libexecutorch.so", word(MEASURED_LDADDAL))
    assert check.scan_path(aar) == []
    assert check.find_lse_in_path(aar, stream=io.StringIO()) is False


def test_main_exit_codes(tmp_path):
    dirty = tmp_path / "libexecutorch.so"
    dirty.write_bytes(word(MEASURED_LDADDAL))
    clean_so = tmp_path / "clean" / "libexecutorch.so"
    clean_so.parent.mkdir()
    clean_so.write_bytes(word(NOP))
    assert check.main([str(dirty)]) == 1
    assert check.main([str(clean_so)]) == 0


def test_helper_words_are_excluded_and_reported_separately():
    # exec layout: [helper LDADD][helper CAS][inline LDADD][inline CAS]
    exec_payload = (
        word(MEASURED_LDADDAL) + word(CAS_WORD) + word(MEASURED_LDADDAL) + word(CAS_WORD)
    )
    helpers = [
        ("__aarch64_ldadd8_acq_rel", 0, 8),
        ("__aarch64_cas8_acq_rel", 4, 4),
    ]
    data = build_elf_with_symtab(exec_payload, helpers)
    total, ldadd, cas, h_total, h_ldadd, h_cas, has = check.count_lse_detailed(data)
    assert has is True
    assert (total, ldadd, cas) == (2, 1, 1)
    assert (h_total, h_ldadd, h_cas) == (2, 1, 1)
    assert check.count_lse_in_so_bytes(data) == (2, 1, 1)


def test_dynsym_helpers_are_excluded_too():
    exec_payload = word(MEASURED_LDADDAL) + word(MEASURED_LDADDAL)
    data = build_elf_with_symtab(
        exec_payload,
        [("__aarch64_swp8_acq_rel", 0, 4)],
        sym_type=SHT_DYNSYM,
    )
    total, _ldadd, _cas, h_total, _h_ldadd, _h_cas, has = check.count_lse_detailed(data)
    assert has is True
    assert total == 1
    assert h_total == 1


def test_helper_with_ldclr_ldset_ldeor_prefixes_is_excluded():
    exec_payload = word(MEASURED_LDADDAL) * 3
    data = build_elf_with_symtab(
        exec_payload,
        [
            ("__aarch64_ldclr8_acq_rel", 0, 4),
            ("__aarch64_ldset8_acq_rel", 4, 4),
            ("__aarch64_ldeor8_acq_rel", 8, 4),
        ],
    )
    total, _ldadd, _cas, h_total, _h_ldadd, _h_cas, has = check.count_lse_detailed(data)
    assert has is True
    assert total == 0
    assert h_total == 3


def test_non_helper_symbol_does_not_exclude():
    exec_payload = word(MEASURED_LDADDAL) + word(MEASURED_LDADDAL)
    data = build_elf_with_symtab(
        exec_payload,
        [("some_other_function", 0, 4)],
    )
    total, _ldadd, _cas, h_total, _h_ldadd, _h_cas, has = check.count_lse_detailed(data)
    assert has is True
    assert total == 2
    assert h_total == 0


def test_no_symbol_table_counts_all_and_is_reported(tmp_path):
    stream = io.StringIO()
    dirty = tmp_path / "libexecutorch.so"
    dirty.write_bytes(build_elf64_aarch64(word(MEASURED_LDADDAL), b""))
    failed = check.find_lse_in_path(dirty, stream=stream)
    assert failed is True
    assert "no symbol table" in stream.getvalue()


def test_text_scan_ignores_lse_bytes_in_rodata():
    # LSE-looking bytes in .rodata sit inside the executable PT_LOAD
    # segment but outside .text, so they must not be counted.
    text = word(NOP) + word(NOP)
    rodata = word(MEASURED_LDADDAL) * 3 + word(CAS_WORD)
    data = build_elf_with_text(text, rodata)
    total, ldadd, cas, h_total, _h_ldadd, _h_cas, has = check.count_lse_detailed(data)
    assert has is False
    assert (total, ldadd, cas) == (0, 0, 0)
    assert h_total == 0
    assert check.count_lse_in_so_bytes(data) == (0, 0, 0)


def test_stripped_helper_only_library_passes(tmp_path):
    # Stripped: LSE word immediately followed by RET is an outline helper.
    text = word(MEASURED_LDADDAL) + word(RET) + word(CAS_WORD) + word(RET)
    data = build_elf_with_text(text)
    total, ldadd, cas, h_total, h_ldadd, h_cas, has = check.count_lse_detailed(data)
    assert has is False
    assert (total, ldadd, cas) == (0, 0, 0)
    assert (h_total, h_ldadd, h_cas) == (2, 1, 1)
    lib = tmp_path / "libexecutorch.so"
    lib.write_bytes(data)
    assert check.find_lse_in_path(lib, stream=io.StringIO()) is False
    assert check.main([str(lib)]) == 0


def test_stripped_inline_lse_inside_other_code_fails(tmp_path):
    # LSE word followed by NOP (not RET) inside other code is inline.
    text = word(NOP) + word(MEASURED_LDADDAL) + word(NOP)
    data = build_elf_with_text(text)
    total, ldadd, cas, h_total, _h_ldadd, _h_cas, has = check.count_lse_detailed(data)
    assert has is False
    assert (total, ldadd, cas) == (1, 1, 0)
    assert h_total == 0
    lib = tmp_path / "libexecutorch.so"
    lib.write_bytes(data)
    assert check.find_lse_in_path(lib, stream=io.StringIO()) is True
    assert check.main([str(lib)]) == 1


def test_stripped_lse_at_end_of_text_without_ret_fails():
    # A trailing LSE word has no following RET inside .text, even when the
    # next section starts with RET bytes.
    text = word(NOP) + word(MEASURED_LDADDAL)
    data = build_elf_with_text(text, word(RET))
    total, _ldadd, _cas, h_total, _h_ldadd, _h_cas, has = check.count_lse_detailed(data)
    assert has is False
    assert total == 1
    assert h_total == 0


def test_symbol_helper_in_text_excluded_inline_still_fails(tmp_path):
    # First word is inside the helper symbol; second is inline (next NOP).
    text = word(MEASURED_LDADDAL) + word(RET) + word(MEASURED_LDADDAL) + word(NOP)
    data = build_elf_with_text(text, helpers=[("__aarch64_ldadd8_acq_rel", 0, 8)])
    total, ldadd, cas, h_total, h_ldadd, h_cas, has = check.count_lse_detailed(data)
    assert has is True
    assert (total, ldadd, cas) == (1, 1, 0)
    assert (h_total, h_ldadd, h_cas) == (1, 1, 0)
    lib = tmp_path / "libexecutorch_jni.so"
    lib.write_bytes(data)
    assert check.find_lse_in_path(lib, stream=io.StringIO()) is True


def test_ret_heuristic_not_applied_when_symbol_table_exists():
    # With a symbol table, LSE+RET outside a helper symbol is still inline.
    text = word(MEASURED_LDADDAL) + word(RET)
    data = build_elf_with_text(text, helpers=[])
    total, _ldadd, _cas, h_total, _h_ldadd, _h_cas, has = check.count_lse_detailed(data)
    assert has is True
    assert total == 1
    assert h_total == 0


def test_only_helper_hits_do_not_fail_executorch_scan(tmp_path):
    stream = io.StringIO()
    exec_payload = word(MEASURED_LDADDAL)
    data = build_elf_with_symtab(
        exec_payload,
        [("__aarch64_ldadd8_acq_rel", 0, 4)],
    )
    lib = tmp_path / "libexecutorch.so"
    lib.write_bytes(data)
    assert check.find_lse_in_path(lib, stream=stream) is False
    output = stream.getvalue()
    assert "helper hit" in output
