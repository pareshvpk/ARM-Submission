"""CPU feature detection and hardware acceleration routing for Arm platforms.

Parses /proc/cpuinfo and sysfs cpuinfo frequencies on Linux aarch64 to identify
available SIMD extensions (NEON, DOTPROD, I8MM, SME2) and big.LITTLE core topologies.
Mirrored on Android by org.ps3.sentinel.ml.CpuFeatures.
"""
from __future__ import annotations

import platform
import sys
from pathlib import Path


def parse_features_line(line: str | None) -> dict[str, bool]:
    """Parse an Arm Linux /proc/cpuinfo Features line into CPU capability flags.

    Args:
        line: The string following 'Features :' in /proc/cpuinfo, or None.

    Returns:
        Dictionary mapping feature names (atomics, asimddp, fphp, etc.) to booleans.
    """
    tokens = set(line.lower().split()) if line else set()
    return {
        "atomics": "atomics" in tokens,
        "asimddp": "asimddp" in tokens,
        "fphp": "fphp" in tokens,
        "bf16": "bf16" in tokens,
        "i8mm": "i8mm" in tokens,
        "sve": "sve" in tokens,
        "sve2": "sve2" in tokens,
        "sme": "sme" in tokens,
        "sme2": "sme2" in tokens,
    }


def parse_cpuinfo(content: str | None) -> dict[str, bool]:
    """Extract CPU architecture features from /proc/cpuinfo content.

    Args:
        content: Full text of /proc/cpuinfo, or None.

    Returns:
        Feature flag dictionary; falls back to all-False defaults if empty or unparseable.
    """
    if not content:
        return fallback_flags()
    for line in content.splitlines():
        if line.lstrip().startswith("Features"):
            value = line.split(":", 1)[1] if ":" in line else line
            return parse_features_line(value)
    return fallback_flags()


def fallback_flags() -> dict[str, bool]:
    """Return a default feature map with all acceleration flags disabled.

    Returns:
        Dictionary where all supported Arm feature flags are set to False.
    """
    return {
        "atomics": False,
        "asimddp": False,
        "fphp": False,
        "bf16": False,
        "i8mm": False,
        "sve": False,
        "sve2": False,
        "sme": False,
        "sme2": False,
    }


def best_kernel_path(flags: dict[str, bool]) -> str:
    """Select the highest-performance ExecuTorch kernel path available for the hardware.

    Args:
        flags: Feature flag dictionary from parse_cpuinfo or parse_features_line.

    Returns:
        Kernel name string: 'SME2', 'I8MM', 'DOTPROD', or baseline 'NEON'.
    """
    # Hierarchy matches compiler support: SME2 > I8MM > DOTPROD > NEON baseline
    if flags.get("sme2"):
        return "SME2"
    if flags.get("i8mm"):
        return "I8MM"
    if flags.get("asimddp"):
        return "DOTPROD"
    return "NEON"


def parse_clusters(freq_by_cpu: dict[int, int]) -> list[tuple[int, int]]:
    """Return (freq_khz, count) tuples sorted by frequency descending."""
    if not freq_by_cpu:
        return []
    freq_counts: dict[int, int] = {}
    for freq_khz in freq_by_cpu.values():
        freq_counts[freq_khz] = freq_counts.get(freq_khz, 0) + 1
    return sorted(freq_counts.items(), key=lambda kv: kv[0], reverse=True)


def format_clusters(clusters: list[tuple[int, int]]) -> str:
    """Format (freq_khz, count) tuples as count@MHz in bench logs."""
    if not clusters:
        return "unknown"
    return "+".join(f"{count}@{freq_khz // 1000}" for freq_khz, count in clusters)


def current_clusters() -> list[tuple[int, int]]:
    """Inspect sysfs CPU frequencies to identify big.LITTLE core clusters.

    Returns:
        List of (frequency_khz, core_count) tuples sorted by frequency descending.
        Returns empty list on non-Linux systems or if sysfs is inaccessible.
    """
    try:
        base = Path("/sys/devices/system/cpu")
        freq_by_cpu: dict[int, int] = {}
        for cpu_dir in base.iterdir():
            name = cpu_dir.name
            if not name.startswith("cpu"):
                continue
            suffix = name[3:]
            try:
                cid = int(suffix)
            except ValueError:
                continue
            freq_file = cpu_dir / "cpufreq" / "cpuinfo_max_freq"
            if not freq_file.is_file():
                continue
            try:
                text = freq_file.read_text(encoding="utf-8").strip()
                freq = int(text)
            except Exception:
                continue
            freq_by_cpu[cid] = freq
        return parse_clusters(freq_by_cpu)
    except Exception:
        return []


def propose_thread_count(clusters: list[tuple[int, int]]) -> int:
    """Propose an optimal thread count based on big core cluster sizing.

    Args:
        clusters: List of (frequency_khz, core_count) tuples from parse_clusters.

    Returns:
        Recommended thread count between 2 and 4, matching the fastest cluster size.
    """
    if not clusters:
        return 2
    # Cap to big core count (up to 4) to prevent thermal throttling on LITTLE cores
    fastest = max(clusters, key=lambda kv: kv[0])
    fastest_count = fastest[1]
    return max(2, min(4, fastest_count))


def _is_linux_aarch64() -> bool:
    try:
        if not sys.platform.startswith("linux"):
            return False
        return platform.machine() == "aarch64"
    except Exception:
        return False


_logged = False


def _has_features_line(content: str | None) -> bool:
    if not content:
        return False
    return any(line.lstrip().startswith("Features") for line in content.splitlines())


def log_once() -> None:
    """Log detected CPU acceleration path and cluster topology to stderr once per process.

    Edge cases:
        No-op on non-aarch64 Linux systems or on subsequent invocations.
    """
    global _logged
    if _logged:
        return
    _logged = True
    if not _is_linux_aarch64():
        return
    try:
        content = Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="ignore")
        flags = parse_cpuinfo(content)
        clusters = current_clusters()
        path = best_kernel_path(flags)
        cluster_str = format_clusters(clusters)
        if not _has_features_line(content):
            print(
                f"accel_path={path} clusters={cluster_str} features=unknown fallback={path} tier=LIGHT",
                file=sys.stderr,
            )
        else:
            print(f"accel_path={path} clusters={cluster_str}", file=sys.stderr)
    except Exception:
        try:
            cluster_str = format_clusters(current_clusters())
        except Exception:
            cluster_str = "unknown"
        print(
            f"accel_path=NEON clusters={cluster_str} features=unknown fallback=NEON tier=LIGHT",
            file=sys.stderr,
        )
