import importlib
import subprocess
import sys
from pathlib import Path

import sentinel.cpu_features as cpu_features
from sentinel.cpu_features import (
    best_kernel_path,
    format_clusters,
    parse_clusters,
    parse_cpuinfo,
    parse_features_line,
    propose_thread_count,
)


def test_parse_m31_no_atomics_no_dotproduct():
    line = "Features\t\t: fp asimd evtstrm aes pmull sha1 sha2 crc32 cpuid"
    flags = parse_cpuinfo(f"processor\t: 0\n{line}\n")
    assert flags["atomics"] is False
    assert flags["asimddp"] is False
    assert flags["fphp"] is False
    assert flags["bf16"] is False
    assert flags["i8mm"] is False
    assert flags["sve"] is False
    assert flags["sve2"] is False
    assert flags["sme"] is False
    assert flags["sme2"] is False
    assert best_kernel_path(flags) == "NEON"


def test_parse_f12_atomics_no_dotproduct():
    line = "Features\t\t: fp asimd evtstrm aes pmull sha1 sha2 crc32 atomics fphp asimdhp cpuid asimdrdm lrcpc dcpop"
    flags = parse_cpuinfo(f"processor\t: 0\n{line}\n")
    assert flags["atomics"] is True
    assert flags["asimddp"] is False
    assert flags["fphp"] is True
    assert flags["bf16"] is False
    assert flags["i8mm"] is False
    assert flags["sve"] is False
    assert flags["sve2"] is False
    assert best_kernel_path(flags) == "NEON"


def test_parse_moto_g73_has_dotproduct():
    line = "Features\t\t: fp asimd evtstrm aes pmull sha1 sha2 crc32 atomics fphp asimdhp cpuid asimdrdm lrcpc dcpop asimddp"
    flags = parse_cpuinfo(f"processor\t: 0\n{line}\n")
    assert flags["atomics"] is True
    assert flags["asimddp"] is True
    assert best_kernel_path(flags) == "DOTPROD"


def test_parse_m32_has_dotproduct():
    line = "Features\t\t: fp asimd evtstrm aes pmull sha1 sha2 crc32 atomics fphp asimdhp cpuid asimdrdm lrcpc dcpop asimddp"
    flags = parse_cpuinfo(f"processor\t: 0\n{line}\n")
    assert flags["atomics"] is True
    assert flags["asimddp"] is True
    assert best_kernel_path(flags) == "DOTPROD"


def test_parse_f14_has_dotproduct_and_fp16():
    line = "Features\t\t: fp asimd evtstrm aes pmull sha1 sha2 crc32 atomics fphp asimdhp cpuid asimdrdm lrcpc dcpop asimddp"
    flags = parse_cpuinfo(f"processor\t: 0\n{line}\n")
    assert flags["atomics"] is True
    assert flags["asimddp"] is True
    assert flags["fphp"] is True
    assert flags["i8mm"] is False
    assert flags["sme2"] is False
    assert best_kernel_path(flags) == "DOTPROD"


def test_parse_synthetic_armv9_sme2_and_i8mm():
    line = "Features\t\t: fp asimd evtstrm aes pmull sha1 sha2 crc32 atomics fphp asimdhp cpuid asimdrdm lrcpc dcpop asimddp bf16 sve sve2 sme sme2 i8mm"
    flags = parse_cpuinfo(f"processor\t: 0\n{line}\n")
    assert flags["atomics"] is True
    assert flags["asimddp"] is True
    assert flags["fphp"] is True
    assert flags["bf16"] is True
    assert flags["i8mm"] is True
    assert flags["sve"] is True
    assert flags["sve2"] is True
    assert flags["sme"] is True
    assert flags["sme2"] is True
    assert best_kernel_path(flags) == "SME2"


def test_parse_flags_line_direct():
    flags = parse_features_line("fp asimd atomics asimddp fphp bf16 i8mm sve sve2 sme sme2")
    assert flags["atomics"] is True
    assert flags["asimddp"] is True
    assert flags["fphp"] is True
    assert flags["bf16"] is True
    assert flags["i8mm"] is True
    assert flags["sve"] is True
    assert flags["sve2"] is True
    assert flags["sme"] is True
    assert flags["sme2"] is True
    assert best_kernel_path(flags) == "SME2"


def test_best_kernel_path_order():
    assert best_kernel_path({"sme2": True, "i8mm": True, "asimddp": True}) == "SME2"
    assert best_kernel_path({"i8mm": True, "asimddp": True}) == "I8MM"
    assert best_kernel_path({"asimddp": True}) == "DOTPROD"
    assert best_kernel_path({}) == "NEON"


def test_parse_clusters_groups_by_freq():
    freq_by_cpu = {
        0: 2200000, 1: 2200000,
        2: 2000000, 3: 2000000, 4: 2000000,
        5: 2000000, 6: 2000000, 7: 2000000,
    }
    clusters = parse_clusters(freq_by_cpu)
    assert len(clusters) == 2
    assert clusters[0] == (2200000, 2)
    assert clusters[1] == (2000000, 6)
    assert format_clusters(clusters) == "2@2200+6@2000"


def test_parse_clusters_empty():
    assert parse_clusters({}) == []
    assert format_clusters([]) == "unknown"


def test_propose_thread_count():
    assert propose_thread_count([(2200000, 2), (2000000, 6)]) == 2
    assert propose_thread_count([(2310000, 4), (1740000, 4)]) == 4
    assert propose_thread_count([(2000000, 8)]) == 4
    assert propose_thread_count([]) == 2


class _FakeCpuinfoPath:
    """Fake Path that serves a simulated aarch64 /proc/cpuinfo."""

    def __init__(self, *args):
        self._path = str(args[0]) if args else ""

    def read_text(self, *args, **kwargs):
        return "Features\t: fp asimd evtstrm aes pmull sha1 sha2 crc32 atomics fphp asimdhp cpuid asimdrdm lrcpc dcpop asimddp\n"

    def iterdir(self):
        return []

    def is_file(self):
        return False


def _simulate_aarch64(monkeypatch):
    monkeypatch.setattr(cpu_features, "_is_linux_aarch64", lambda: True)
    monkeypatch.setattr(cpu_features, "Path", _FakeCpuinfoPath)
    monkeypatch.setattr(cpu_features, "_logged", False)


def test_import_sentinel_prints_nothing_on_stdout_subprocess():
    repo_root = str(Path(__file__).resolve().parent.parent)
    result = subprocess.run(
        [sys.executable, "-c", "import sentinel; import sentinel.cli; import sentinel.cpu_features"],
        capture_output=True,
        text=True,
        cwd=repo_root,
    )
    assert result.returncode == 0
    assert result.stdout == ""


def test_import_sentinel_prints_nothing_on_simulated_aarch64(monkeypatch, capsys):
    import sentinel

    _simulate_aarch64(monkeypatch)
    capsys.readouterr()
    importlib.reload(sentinel)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_fallback_flags_all_false_and_neon():
    from sentinel.cpu_features import fallback_flags

    flags = fallback_flags()
    assert all(value is False for value in flags.values())
    assert best_kernel_path(flags) == "NEON"


def test_parse_cpuinfo_unknown_falls_back_conservative():
    for content in (None, "", "processor\t: 0\nmodel name\t: ARM\n"):
        flags = parse_cpuinfo(content)
        assert all(value is False for value in flags.values())
        assert best_kernel_path(flags) == "NEON"


def test_log_once_logs_unknown_on_empty_cpuinfo(monkeypatch, capsys):
    class _EmptyCpuinfoPath:
        def __init__(self, *args):
            self._path = str(args[0]) if args else ""

        def read_text(self, *args, **kwargs):
            return ""

        def iterdir(self):
            return []

        def is_file(self):
            return False

    monkeypatch.setattr(cpu_features, "_is_linux_aarch64", lambda: True)
    monkeypatch.setattr(cpu_features, "Path", _EmptyCpuinfoPath)
    monkeypatch.setattr(cpu_features, "_logged", False)
    capsys.readouterr()
    cpu_features.log_once()
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "features=unknown" in captured.err
    assert "accel_path=NEON" in captured.err


def test_log_once_writes_to_stderr_not_stdout(monkeypatch, capsys):
    _simulate_aarch64(monkeypatch)
    capsys.readouterr()
    cpu_features.log_once()
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "accel_path=DOTPROD" in captured.err
    cpu_features.log_once()
    second = capsys.readouterr()
    assert second.out == ""
    assert second.err == ""
