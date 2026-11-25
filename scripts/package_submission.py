# Adapted from pareshvpk/Phase package_submission.py (MIT licence).
"""Package the current source, built APK, Python wheel and model assets for submission.

Creates a zip archive of clean tracked source files and pairs it with the built
release APK, the built Python wheel, the model assets the phone installers verify,
and a SHA256SUMS file both installers accept. Filters credentials, temporary build
caches, and large binary models out of the source archive.

The archive is zipped from the working tree, so packaging refuses to run while
`git status --porcelain` reports changes unless `--allow-dirty` is given.
"""
import argparse
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile
from collections.abc import Iterable

ROOT = Path(__file__).resolve().parents[1]

EXCLUDED_EXTENSIONS = {
    ".pte",
    ".apk",
    ".jks",
    ".keystore",
    ".pem",
    ".key",
    ".mp4",
    ".webm",
}

EXCLUDED_FILENAMES = {
    "local.properties",
    "keystore.properties",
}

EXCLUDED_DIR_NAMES = {
    "tmp_work",
    "build",
    "__pycache__",
    ".gradle",
}

MODEL_BINARY_EXTENSIONS = {
    ".pte",
    ".bin",
    ".pt",
    ".onnx",
    ".safetensors",
    ".tflite",
    ".hef",
    ".pkl",
    ".weights",
}

APK_ASSET_NAME = "ps3-sentinel-1.0.apk"
APK_BUILD_PATH = Path("android") / "app" / "build" / "outputs" / "apk" / "release" / "app-release.apk"
SOURCE_ARCHIVE_NAME = "ps3-sentinel-source.zip"
SUMS_FILE_NAME = "SHA256SUMS"

# Model assets in the order the phone installers check them. The first block is
# required: scripts/install_phone.ps1 ($baseAssets) and scripts/install_phone.sh
# (BASE_ASSETS) verify every one of these against SHA256SUMS and abort when one is
# missing or unlisted, so the packager must ship and hash them all.
REQUIRED_MODEL_NAMES = (
    "url_cnn_v2.pte",
    "vocab.json",
    "id_map.json",
    "sms_vocab.txt",
    "llama.pte",
    "tokenizer.model",
    "sms_tokenizer.zip",
)
# Optional: the installers verify whichever of these the phone needs and is present.
OPTIONAL_MODEL_NAMES = (
    "sms_int8.pte",
    "sms_fp32.pte",
)
MODEL_ASSET_NAMES = REQUIRED_MODEL_NAMES + OPTIONAL_MODEL_NAMES
# Everything the installers refuse to install without, APK included.
REQUIRED_ASSET_NAMES = (APK_ASSET_NAME,) + REQUIRED_MODEL_NAMES


def should_include(rel_path: str | Path) -> bool:
    """Pure filter function determining if a tracked file path should be included in the submission source zip.

    Args:
        rel_path: Relative path to check.

    Returns:
        True if file is suitable for distribution, False if excluded by rule or extension.
    """
    if not rel_path:
        return False
    path = Path(rel_path)
    parts = path.parts
    if not parts:
        return False

    if any(part in EXCLUDED_DIR_NAMES for part in parts):
        return False

    if path.name.startswith(".env"):
        return False

    if path.name in EXCLUDED_FILENAMES:
        return False

    suffix = path.suffix.lower()
    if suffix in EXCLUDED_EXTENSIONS:
        return False

    if "models" in parts and suffix in MODEL_BINARY_EXTENSIONS:
        return False

    return True


def sha256_file(path: Path) -> str:
    """Compute the SHA-256 hex digest of a file in 1 MiB chunks.

    Args:
        path: Path to the target file.

    Returns:
        Hexadecimal SHA-256 digest string.
    """
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256sums_text(files: list[Path]) -> str:
    """Format files the way both phone installers parse SHA256SUMS.

    Both parsers split each line on whitespace and take the first field as the
    digest and the last field (optionally preceded by a `*` binary marker) as the
    file name, so `<digest>  <name>` is the format they accept.

    Args:
        files: Files to list, in the order they should appear.

    Returns:
        One `<digest>  <file name>` line per file, newline terminated.
    """
    return "".join(f"{sha256_file(path)}  {path.name}\n" for path in files)


def collect_model_files(models_dir: Path) -> list[Path]:
    """Model assets present in [models_dir], in installer order.

    Args:
        models_dir: Folder holding the flat release model assets.

    Returns:
        Paths of the known release model assets that exist in [models_dir].
    """
    return [models_dir / name for name in MODEL_ASSET_NAMES if (models_dir / name).is_file()]


def select_asset_files(models_dir: Path | None, explicit: list[Path]) -> list[Path]:
    """Pick the model assets to ship, one per file name, in installer order.

    Args:
        models_dir: Optional folder of flat release model assets.
        explicit: Files passed on the command line; these win over [models_dir].

    Returns:
        Model asset paths, known release assets first in installer order, then any
        extra explicitly passed files.
    """
    chosen: dict[str, Path] = {}
    if models_dir is not None:
        for path in collect_model_files(models_dir):
            chosen[path.name] = path
    for path in explicit:
        chosen[path.name] = path
    ordered = [chosen[name] for name in MODEL_ASSET_NAMES if name in chosen]
    ordered += [path for name, path in chosen.items() if name not in MODEL_ASSET_NAMES]
    return ordered


def missing_required_assets(shipped_names: Iterable[str]) -> list[str]:
    """Return the assets the installers verify but the package would not ship.

    Args:
        shipped_names: File names that will be written next to SHA256SUMS.

    Returns:
        Required asset names missing from [shipped_names], in installer order.
    """
    present = set(shipped_names)
    return [name for name in REQUIRED_ASSET_NAMES if name not in present]


def git_porcelain(root: Path) -> str:
    """Return `git status --porcelain` output for [root].

    Args:
        root: Repository root directory path.

    Returns:
        The raw porcelain output, empty when the worktree is clean.
    """
    try:
        raw = subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=root, stderr=subprocess.STDOUT
        )
    except subprocess.CalledProcessError as exc:
        sys.exit(
            "Error: git status --porcelain failed:\n"
            + exc.output.decode("utf-8", "replace").strip()
        )
    except OSError as exc:
        sys.exit(f"Error: git is required to package a submission: {exc}")
    return raw.decode("utf-8", "replace")


def dirty_worktree_error(porcelain: str, allow_dirty: bool) -> str | None:
    """Decide whether a dirty worktree blocks packaging.

    The source archive is built from working-tree bytes of tracked file names, so
    uncommitted changes would put code in the archive that the repository does not
    contain.

    Args:
        porcelain: Output of `git status --porcelain`.
        allow_dirty: True when the caller passed --allow-dirty.

    Returns:
        An error message to report, or None when packaging may proceed.
    """
    if allow_dirty:
        return None
    lines = [line for line in porcelain.splitlines() if line.strip()]
    if not lines:
        return None
    shown = "\n".join(f"  {line}" for line in lines[:10])
    more = "" if len(lines) <= 10 else f"\n  ... and {len(lines) - 10} more"
    return (
        "git status --porcelain is not empty, so the archive would mix committed and "
        "uncommitted bytes.\n"
        f"{shown}{more}\n"
        "Commit or stash the changes first, or pass --allow-dirty to package the "
        "working tree anyway."
    )


def wheel_command(root: Path, out_dir: Path) -> list[str]:
    """Return the argv that builds the deliverable wheel with pip.

    Args:
        root: Repository root holding pyproject.toml.
        out_dir: Directory the wheel is written to.

    Returns:
        Command line list for `python -m pip wheel . --no-deps -w <out dir>`.
    """
    return [
        sys.executable,
        "-m",
        "pip",
        "wheel",
        str(root),
        "--no-deps",
        "-w",
        str(out_dir),
    ]


def build_wheel(root: Path, out_dir: Path) -> Path:
    """Build the ps3-sentinel wheel into [out_dir] and return its path.

    Args:
        root: Repository root holding pyproject.toml.
        out_dir: Directory the wheel is written to.

    Returns:
        Path of the newest wheel in [out_dir].
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(wheel_command(root, out_dir), capture_output=True, text=True)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        sys.exit(f"Error: building the Python wheel failed:\n{detail}")
    wheels = sorted(out_dir.glob("*.whl"), key=lambda p: p.stat().st_mtime_ns)
    if not wheels:
        sys.exit(f"Error: pip produced no wheel in {out_dir}")
    return wheels[-1]


def get_source_files(root: Path) -> list[tuple[str, Path]]:
    """List tracked files from git ls-files filtered by should_include.

    Args:
        root: Repository root directory path.

    Returns:
        List of (relative_name, absolute_path) tuples for included tracked files.
    """
    raw = subprocess.check_output(["git", "ls-files", "-z"], cwd=root)
    lines = raw.decode("utf-8").split("\0")
    files = []
    for line in sorted(set(lines)):
        name = line.strip()
        if not name or not should_include(name):
            continue
        abs_path = root / name
        if abs_path.is_file():
            files.append((name, abs_path))
    return files


def main() -> None:
    """Entry point to build the submission archive, APK, wheel, assets and SHA256SUMS."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "artifacts" / "submission",
        help="Output directory (must be inside artifacts/)",
    )
    parser.add_argument(
        "--models-dir",
        type=Path,
        default=None,
        help="Folder holding the flat release model assets (url_cnn_v2.pte, llama.pte, ...)",
    )
    parser.add_argument(
        "--model-file",
        type=Path,
        action="append",
        default=[],
        help="Model asset to ship and hash, repeatable; overrides --models-dir for the same name",
    )
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Package the working tree even when git status --porcelain is not empty",
    )
    args = parser.parse_args()

    dirty = dirty_worktree_error(git_porcelain(ROOT), args.allow_dirty)
    if dirty is not None:
        sys.exit(f"Error: {dirty}")

    artifacts_dir = (ROOT / "artifacts").resolve()
    output = args.output_dir.resolve()
    # Prevent path traversal outside the project artifacts folder
    try:
        output.relative_to(artifacts_dir)
    except ValueError:
        parser.error(f"output-dir must be within this project's artifacts directory ({artifacts_dir})")

    apk_source = ROOT / APK_BUILD_PATH
    if not apk_source.is_file():
        sys.exit(
            f"Error: release APK not found at '{apk_source}'. "
            "Please build the release APK first (e.g. cd android && ./gradlew assembleRelease)."
        )

    model_sources = select_asset_files(args.models_dir, args.model_file)
    for path in model_sources:
        if not path.is_file():
            sys.exit(f"Error: model asset not found: {path}")
    missing = missing_required_assets([APK_ASSET_NAME] + [path.name for path in model_sources])
    if missing:
        sys.exit(
            "Error: SHA256SUMS would be rejected by scripts/install_phone.ps1 and "
            "scripts/install_phone.sh, which verify every required asset. Missing: "
            + ", ".join(missing)
            + ". Pass --models-dir <release asset folder> or one --model-file per asset."
        )

    output.mkdir(parents=True, exist_ok=True)

    archive_path = output / SOURCE_ARCHIVE_NAME
    source_files = get_source_files(ROOT)
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel_name, abs_path in source_files:
            zf.write(abs_path, arcname=Path(rel_name).as_posix())

    with zipfile.ZipFile(archive_path) as check:
        corrupt = check.testzip()
        if corrupt is not None:
            raise RuntimeError(f"source archive failed CRC check on file: {corrupt}")

    packaged_apk = output / APK_ASSET_NAME
    shutil.copy2(apk_source, packaged_apk)

    packaged_models = []
    for source in model_sources:
        destination = output / source.name
        if source.resolve() != destination.resolve():
            shutil.copy2(source, destination)
        packaged_models.append(destination)

    wheel_path = build_wheel(ROOT, output)

    shipped_files = [archive_path, packaged_apk, wheel_path] + packaged_models
    sums_file = output / SUMS_FILE_NAME
    sums_file.write_text(sha256sums_text(shipped_files), encoding="utf-8")

    print(f"Packaged source archive: {archive_path}")
    print(f"Packaged release APK:   {packaged_apk}")
    print(f"Packaged Python wheel:  {wheel_path}")
    for model in packaged_models:
        print(f"Packaged model asset:   {model}")
    print(f"Wrote SHA256SUMS:       {sums_file}")


if __name__ == "__main__":
    main()
