"""Generate a models.sha256 manifest for model files.

Usage:
    python write_models_manifest.py <models_folder>

    python write_models_manifest.py --model-files sentinel/data/model_files.json \\
        --out <manifest_path> --role url_model=<local_path> ...

The manifest contains one line per file, formatted as::

    <lowercase hex sha256>  <file name>

Files are hashed in 1 MiB chunks so large model files never need to be
read into memory, and entries are sorted by file name. The folder mode
writes ``models.sha256`` inside the given folder. The role mode maps each
local path to the phone file name from the shared model_files.json file
and writes the manifest to the given output path.
"""

import argparse
import hashlib
import json
import re
import stat
from pathlib import Path

MANIFEST_NAME = "models.sha256"
CHUNK_SIZE = 1024 * 1024


def _sha256_file(path):
    """Return the lowercase hex SHA-256 of *path*, streaming in 1 MiB chunks."""
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        while True:
            chunk = stream.read(CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def write_models_manifest(models_dir):
    """Write ``models.sha256`` for every regular file in *models_dir*.

    Returns the path to the written manifest.
    """
    directory = Path(models_dir)
    if not directory.is_dir():
        raise ValueError("models folder does not exist: {}".format(directory))

    entries = []
    for entry in directory.iterdir():
        try:
            mode = entry.stat().st_mode
        except OSError:
            continue
        if not stat.S_ISREG(mode):
            continue
        if entry.name == MANIFEST_NAME:
            continue
        entries.append((entry.name, _sha256_file(entry)))

    entries.sort(key=lambda item: item[0])

    manifest_path = directory / MANIFEST_NAME
    with open(manifest_path, "w", encoding="utf-8", newline="\n") as output:
        for name, digest in entries:
            output.write("{}  {}\n".format(digest, name))
    return manifest_path


def load_phone_names(model_files_path):
    """Read phone file names per role from model_files.json."""
    path = Path(model_files_path)
    if not path.is_file():
        raise ValueError("model files manifest not found: {}".format(path))
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError("model files manifest {} is not valid JSON: {}".format(path, error)) from error
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise ValueError("model files manifest {} has unsupported schema_version".format(path))
    files = raw.get("files")
    if not isinstance(files, dict):
        raise ValueError("model files manifest {} must have a files object".format(path))
    result = {}
    phone_re = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    for role, entry in files.items():
        if not isinstance(entry, dict):
            raise ValueError("model files manifest {}: role {} must be an object".format(path, role))
        phone = entry.get("phone")
        if not isinstance(phone, str) or not phone or not phone_re.match(phone) or ".." in phone:
            raise ValueError("model files manifest {}: role {} needs a safe phone name".format(path, role))
        result[role] = phone
    return result


def _dedupe_entries(entries):
    """Return sorted unique ``(phone_name, digest)`` entries (C-16).

    Two roles can map to the same phone file name (for example
    ``sms_vocab`` and ``sms_tokenizer_dir`` both map to ``sms_vocab.txt``).
    A repeated name with the same hash is written once; a repeated name
    with a conflicting hash raises ``ValueError`` instead of writing an
    ambiguous duplicate manifest line.
    """
    seen = {}
    for name, digest in entries:
        if name in seen:
            if seen[name] != digest:
                raise ValueError(
                    "conflicting hashes for phone file {}: {} vs {}".format(name, seen[name], digest)
                )
            continue
        seen[name] = digest
    return sorted(seen.items())


def write_manifest_from_roles(role_files, model_files_path, out_path):
    """Write a manifest mapping local paths to phone names from model_files.json.

    role_files maps each model role to the local file path to hash. The
    phone name written in the manifest comes from model_files.json, so a
    rename there changes the manifest without touching the caller.

    Returns the path to the written manifest.
    """
    phones = load_phone_names(model_files_path)
    entries = []
    for role in role_files:
        if role not in phones:
            raise ValueError("unknown model role: {}".format(role))
        local = Path(role_files[role])
        if not local.is_file():
            raise ValueError("model file not found: {}".format(local))
        entries.append((phones[role], _sha256_file(local)))
    entries = _dedupe_entries(entries)
    manifest_path = Path(out_path)
    if manifest_path.parent and str(manifest_path.parent) not in ("", "."):
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(manifest_path, "w", encoding="utf-8", newline="\n") as output:
        for name, digest in entries:
            output.write("{}  {}\n".format(digest, name))
    return manifest_path


def write_manifest_from_pairs(pairs, out_path):
    """Write a manifest from explicit local-path/phone-name pairs.

    Returns the path to the written manifest.
    """
    entries = []
    phone_re = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    for local, phone in pairs:
        local_path = Path(local)
        if not local_path.is_file():
            raise ValueError("model file not found: {}".format(local_path))
        if not phone or not phone_re.match(phone) or ".." in phone:
            raise ValueError("unsafe phone file name: {}".format(phone))
        entries.append((phone, _sha256_file(local_path)))
    entries = _dedupe_entries(entries)
    manifest_path = Path(out_path)
    if manifest_path.parent and str(manifest_path.parent) not in ("", "."):
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(manifest_path, "w", encoding="utf-8", newline="\n") as output:
        for name, digest in entries:
            output.write("{}  {}\n".format(digest, name))
    return manifest_path


# Convenient aliases for callers that expect a different function name.
write_manifest = write_models_manifest
generate_manifest = write_models_manifest
create_manifest = write_models_manifest


def _parse_role_arg(value):
    if "=" not in value:
        raise argparse.ArgumentTypeError("role argument must be role=path: {}".format(value))
    role, path = value.split("=", 1)
    if not role or not path:
        raise argparse.ArgumentTypeError("role argument must be role=path: {}".format(value))
    return (role, path)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Write models.sha256 for model files.")
    parser.add_argument("models_dir", nargs="?", help="path to the models folder (folder mode)")
    parser.add_argument(
        "--model-files",
        default=None,
        help="path to sentinel/data/model_files.json (role mode)",
    )
    parser.add_argument("--out", default=None, help="output manifest path (role mode)")
    parser.add_argument(
        "--role",
        action="append",
        type=_parse_role_arg,
        default=None,
        help="model role to local path, repeated per file (role mode)",
    )
    args = parser.parse_args(argv)
    if args.role:
        if not args.model_files or not args.out:
            parser.error("role mode requires --model-files and --out")
        role_files = dict(args.role)
        write_manifest_from_roles(role_files, args.model_files, args.out)
        return 0
    if args.models_dir:
        write_models_manifest(args.models_dir)
        return 0
    parser.error("provide a models folder or role entries")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
