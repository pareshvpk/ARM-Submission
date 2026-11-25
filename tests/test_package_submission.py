"""Tests for scripts/package_submission.py: source filter, SHA256SUMS, wheel, dirty gate."""
import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.package_submission import (
    MODEL_ASSET_NAMES,
    OPTIONAL_MODEL_NAMES,
    REQUIRED_ASSET_NAMES,
    REQUIRED_MODEL_NAMES,
    collect_model_files,
    dirty_worktree_error,
    missing_required_assets,
    select_asset_files,
    sha256sums_text,
    should_include,
    wheel_command,
)


def _installer_names(pattern: str, text: str) -> set[str]:
    """Extract the quoted asset names from one installer asset list."""
    block = re.search(pattern, text, re.S)
    assert block is not None, f"asset list not found with {pattern!r}"
    return set(re.findall(r'"([^"]+)"', block.group(1)))


def test_required_assets_match_both_installers():
    sh_text = (ROOT / "scripts" / "install_phone.sh").read_text(encoding="utf-8")
    ps_text = (ROOT / "scripts" / "install_phone.ps1").read_text(encoding="utf-8")
    fetch_sh = (ROOT / "scripts" / "fetch_models.sh").read_text(encoding="utf-8")
    fetch_ps = (ROOT / "scripts" / "fetch_models.ps1").read_text(encoding="utf-8")

    sh_required = _installer_names(r"BASE_ASSETS=\((.*?)\)", sh_text)
    ps_required = _installer_names(r"\$baseAssets = @\((.*?)\)", ps_text)

    assert sh_required == ps_required
    assert set(REQUIRED_ASSET_NAMES) == sh_required | {"sms_tokenizer.zip"}
    assert "sms_tokenizer.zip" in fetch_sh
    assert "sms_tokenizer.zip" in fetch_ps
    # The optional SMS models are verified by both installers when present.
    for name in OPTIONAL_MODEL_NAMES:
        assert name in sh_text, f"{name} missing from install_phone.sh"
        assert name in ps_text, f"{name} missing from install_phone.ps1"


def test_required_asset_names_are_the_apk_plus_required_models():
    assert REQUIRED_ASSET_NAMES == ("ps3-sentinel-1.0.apk",) + REQUIRED_MODEL_NAMES
    assert set(MODEL_ASSET_NAMES) == set(REQUIRED_MODEL_NAMES) | set(OPTIONAL_MODEL_NAMES)


def test_sha256sums_lists_every_shipped_file(tmp_path):
    names = ["ps3-sentinel-source.zip", "ps3-sentinel-1.0.apk", "ps3_sentinel-1.0.0-py3-none-any.whl"]
    files = []
    for name in names:
        path = tmp_path / name
        path.write_bytes(name.encode("utf-8"))
        files.append(path)

    text = sha256sums_text(files)
    lines = text.splitlines()

    assert text.endswith("\n")
    assert len(lines) == len(files)
    for line, path in zip(lines, files):
        digest, separator, name = line.partition("  ")
        assert separator == "  ", f"line is not '<digest>  <name>': {line!r}"
        assert name == path.name
        assert digest == hashlib.sha256(path.read_bytes()).hexdigest()


def test_sha256sums_is_accepted_by_both_installer_parsers(tmp_path):
    """Both installers split on whitespace: first field digest, last field file name."""
    files = []
    for name in REQUIRED_ASSET_NAMES + OPTIONAL_MODEL_NAMES:
        path = tmp_path / name
        path.write_bytes(f"payload of {name}".encode("utf-8"))
        files.append(path)
    text = sha256sums_text(files)

    for path in files:
        # install_phone.sh: grep "[[:space:]]\*\{0,1\}$file_name$" | awk '{print $1}'
        sh_pattern = re.compile(r"[ \t]\*?" + re.escape(path.name) + r"$")
        sh_match = [line for line in text.splitlines() if sh_pattern.search(line)]
        assert len(sh_match) == 1, f"install_phone.sh would not find {path.name}"
        # install_phone.ps1: split on whitespace, first field digest, last field name.
        ps_fields = sh_match[0].split()
        assert ps_fields[-1].lstrip("*") == path.name
        assert ps_fields[0] == hashlib.sha256(path.read_bytes()).hexdigest()


def test_missing_required_assets_reports_every_gap():
    assert missing_required_assets(REQUIRED_ASSET_NAMES) == []
    missing = missing_required_assets(["ps3-sentinel-1.0.apk", "vocab.json"])
    assert missing == [
        "url_cnn_v2.pte",
        "id_map.json",
        "sms_vocab.txt",
        "llama.pte",
        "tokenizer.model",
        "sms_tokenizer.zip",
    ]


def test_collect_model_files_returns_present_assets_in_installer_order(tmp_path):
    (tmp_path / "vocab.json").write_text("{}", encoding="utf-8")
    (tmp_path / "sms_int8.pte").write_bytes(b"x")
    (tmp_path / "llama.pte").write_bytes(b"x")
    (tmp_path / "notes.txt").write_text("not an asset", encoding="utf-8")

    names = [path.name for path in collect_model_files(tmp_path)]

    assert names == ["vocab.json", "llama.pte", "sms_int8.pte"]


def test_select_asset_files_puts_known_assets_first_and_explicit_wins(tmp_path):
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    (models_dir / "vocab.json").write_text("dir", encoding="utf-8")
    (models_dir / "llama.pte").write_bytes(b"dir")
    override = tmp_path / "override" / "vocab.json"
    override.parent.mkdir()
    override.write_text("explicit", encoding="utf-8")
    extra = tmp_path / "sms_fp32.pte"
    extra.write_bytes(b"explicit extra")

    selected = select_asset_files(models_dir, [override, extra])

    assert [path.name for path in selected] == ["vocab.json", "llama.pte", "sms_fp32.pte"]
    assert selected[0] == override
    assert selected[1] == models_dir / "llama.pte"


def test_select_asset_files_without_models_dir_keeps_installer_order(tmp_path):
    llama = tmp_path / "llama.pte"
    url_model = tmp_path / "url_cnn_v2.pte"
    for path in (llama, url_model):
        path.write_bytes(b"x")

    selected = select_asset_files(None, [llama, url_model])

    # Known release assets keep the order both installers verify them in.
    assert selected == [url_model, llama]


def test_clean_worktree_passes():
    assert dirty_worktree_error("", allow_dirty=False) is None
    assert dirty_worktree_error("\n \n", allow_dirty=False) is None


def test_dirty_worktree_is_refused_with_the_changed_files_named():
    porcelain = " M sentinel/cli.py\n?? notes.txt\n"
    error = dirty_worktree_error(porcelain, allow_dirty=False)

    assert error is not None
    assert "sentinel/cli.py" in error
    assert "notes.txt" in error
    assert "--allow-dirty" in error


def test_dirty_worktree_allowed_with_flag():
    assert dirty_worktree_error(" M sentinel/cli.py\n", allow_dirty=True) is None


def test_dirty_worktree_error_truncates_long_lists():
    porcelain = "".join(f" M file{i}.py\n" for i in range(25))

    error = dirty_worktree_error(porcelain, allow_dirty=False)

    assert error is not None
    assert "file0.py" in error
    assert "file9.py" in error
    assert "file10.py" not in error
    assert "and 15 more" in error


def test_wheel_command_builds_the_documented_wheel(tmp_path):
    out_dir = tmp_path / "out"
    argv = wheel_command(tmp_path, out_dir)

    assert argv[1:4] == ["-m", "pip", "wheel"]
    assert argv[4] == str(tmp_path)
    assert "--no-deps" in argv
    assert argv[argv.index("-w") + 1] == str(out_dir)


def test_should_include_valid_paths():
    valid = [
        "README.md",
        "sentinel/rules.py",
        "android/app/src/main/AndroidManifest.xml",
        "android/app/src/main/java/org/ps3/sentinel/core/AppAccessReview.kt",
        "scripts/package_submission.py",
        "tests/test_package_submission.py",
        "models/README.md",
    ]
    for path in valid:
        assert should_include(path) is True, f"Expected {path} to be included"


def test_should_include_excluded_extensions():
    excluded_exts = [
        "model.pte",
        "android/app/build/app-release.apk",
        "app.apk",
        "keystore.jks",
        "release.keystore",
        "cert.pem",
        "id_rsa.key",
    ]
    for path in excluded_exts:
        assert should_include(path) is False, f"Expected {path} to be excluded"


def test_should_include_excluded_directories():
    excluded_dirs = [
        "tmp_work/teammate_Phase/AppReviewCollector.kt",
        "tmp_work/notes.txt",
        "android/app/build/outputs/apk/release/app-release.apk",
        "build/lib/something.py",
        "sentinel/__pycache__/rules.cpython-311.pyc",
        ".gradle/wrapper/dists/something",
    ]
    for path in excluded_dirs:
        assert should_include(path) is False, f"Expected {path} to be excluded"


def test_should_include_excluded_properties_and_env():
    excluded = [
        "local.properties",
        "keystore.properties",
        ".env",
        ".env.local",
        ".env.production",
    ]
    for path in excluded:
        assert should_include(path) is False, f"Expected {path} to be excluded"


def test_should_include_model_binaries():
    model_binaries = [
        "models/sms_int8.pte",
        "models/llama.bin",
        "models/sms.pt",
        "models/url.onnx",
        "models/model.safetensors",
        "models/model.tflite",
        "models/model.hef",
    ]
    for path in model_binaries:
        assert should_include(path) is False, f"Expected {path} to be excluded"


def test_should_include_empty_and_falsy():
    assert should_include("") is False
