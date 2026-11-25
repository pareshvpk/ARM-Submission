"""Tests for deploy/android/write_models_manifest.py."""

import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "deploy" / "android" / "write_models_manifest.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("write_models_manifest", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestModelsManifest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "b.bin").write_bytes(b"second")
        (self.tmp / "a.bin").write_bytes(b"first")
        (self.tmp / "models.sha256").write_text("stale\n", encoding="utf-8")

    def _run(self, func_name="write_models_manifest"):
        module = _load_module()
        func = getattr(module, func_name)
        return func(str(self.tmp))

    def test_writes_exact_line_format(self):
        self._run()
        lines = (self.tmp / "models.sha256").read_text(encoding="utf-8").splitlines()
        # manifest itself must not be listed
        self.assertEqual(len(lines), 2)
        # sorted by file name
        self.assertTrue(lines[0].endswith("  a.bin"))
        self.assertTrue(lines[1].endswith("  b.bin"))

        for line in lines:
            # lowercase hex sha256, two spaces, file name
            self.assertRegex(line, r"^[0-9a-f]{64}  .+$")
            digest, name = line.split("  ", 1)
            actual = hashlib.sha256((self.tmp / name).read_bytes()).hexdigest()
            self.assertEqual(digest, actual)
            self.assertEqual(digest, digest.lower())

    def test_excludes_manifest_and_non_regular(self):
        subdir = self.tmp / "subdir"
        subdir.mkdir()
        self._run()
        content = (self.tmp / "models.sha256").read_text(encoding="utf-8")
        self.assertNotIn("models.sha256", content)
        self.assertNotIn("subdir", content)

    def test_function_aliases_and_main(self):
        module = _load_module()
        for alias in ("write_manifest", "generate_manifest", "create_manifest"):
            self.assertTrue(callable(getattr(module, alias)))
        # main with argv list
        rc = module.main([str(self.tmp)])
        self.assertEqual(rc, 0)

    def test_large_file_streamed(self):
        big = self.tmp / "big.bin"
        big.write_bytes(b"x" * (1024 * 1024 + 5))
        self._run()
        lines = (self.tmp / "models.sha256").read_text(encoding="utf-8").splitlines()
        big_line = [ln for ln in lines if ln.endswith("  big.bin")][0]
        digest = big_line.split("  ", 1)[0]
        self.assertEqual(digest, hashlib.sha256(big.read_bytes()).hexdigest())

    def _write_model_files(self, files):
        path = self.tmp / "model_files.json"
        path.write_text(json.dumps({"schema_version": 1, "files": files}), encoding="utf-8")
        return path

    def test_role_mode_dedupes_shared_phone_name_same_hash(self):
        module = _load_module()
        model_files = self._write_model_files({
            "sms_vocab": {"phone": "sms_vocab.txt"},
            "sms_tokenizer_dir": {"phone": "sms_vocab.txt"},
        })
        local = self.tmp / "vocab.txt"
        local.write_bytes(b"vocab")
        out = self.tmp / "out.sha256"
        module.write_manifest_from_roles(
            {"sms_vocab": str(local), "sms_tokenizer_dir": str(local)},
            str(model_files),
            str(out),
        )
        lines = out.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].endswith("  sms_vocab.txt"))

    def test_role_mode_fails_on_conflicting_hashes(self):
        module = _load_module()
        model_files = self._write_model_files({
            "sms_vocab": {"phone": "sms_vocab.txt"},
            "sms_tokenizer_dir": {"phone": "sms_vocab.txt"},
        })
        first = self.tmp / "first.txt"
        second = self.tmp / "second.txt"
        first.write_bytes(b"first")
        second.write_bytes(b"second")
        out = self.tmp / "out.sha256"
        with self.assertRaises(ValueError):
            module.write_manifest_from_roles(
                {"sms_vocab": str(first), "sms_tokenizer_dir": str(second)},
                str(model_files),
                str(out),
            )

    def test_role_mode_includes_sms_fp32_when_present(self):
        module = _load_module()
        model_files = self._write_model_files({
            "sms_model": {"phone": "sms_int8.pte"},
            "sms_fp32": {"phone": "sms_fp32.pte"},
        })
        int8 = self.tmp / "sms_int8.pte"
        fp32 = self.tmp / "sms_fp32.pte"
        int8.write_bytes(b"int8")
        fp32.write_bytes(b"fp32")
        out = self.tmp / "out.sha256"
        module.write_manifest_from_roles(
            {"sms_model": str(int8), "sms_fp32": str(fp32)},
            str(model_files),
            str(out),
        )
        content = out.read_text(encoding="utf-8")
        self.assertIn("  sms_int8.pte", content)
        self.assertIn("  sms_fp32.pte", content)
        self.assertEqual(len(content.splitlines()), 2)

    def test_pairs_mode_dedupes_and_fails_on_conflict(self):
        module = _load_module()
        local = self.tmp / "a.bin"
        local.write_bytes(b"same")
        out = self.tmp / "pairs.sha256"
        module.write_manifest_from_pairs(
            [(str(local), "sms_vocab.txt"), (str(local), "sms_vocab.txt")],
            str(out),
        )
        self.assertEqual(len(out.read_text(encoding="utf-8").splitlines()), 1)
        other = self.tmp / "b.bin"
        other.write_bytes(b"different")
        with self.assertRaises(ValueError):
            module.write_manifest_from_pairs(
                [(str(local), "sms_vocab.txt"), (str(other), "sms_vocab.txt")],
                str(out),
            )


if __name__ == "__main__":
    unittest.main()