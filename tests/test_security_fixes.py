"""Regression tests for the 2026-11-08 security fixes S-3, S-4, S-11, S-12, S-13."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent


def test_safe_dest_rejects_path_traversal(tmp_path):
    from data.fetch_external import safe_dest

    for bad in ("../evil.txt", "..\\evil.txt", "sub/evil.txt", "sub\\evil.txt",
                "/abs/evil.txt", "..", ".", ""):
        with pytest.raises(ValueError):
            safe_dest(tmp_path, bad)


def test_safe_dest_accepts_plain_filename_inside_dest(tmp_path):
    from data.fetch_external import safe_dest

    target = safe_dest(tmp_path, "Dataset_5971.csv")
    assert target == (tmp_path.resolve() / "Dataset_5971.csv")
    assert target.is_relative_to(tmp_path.resolve())


def test_feed_manifest_written_next_to_feeds(tmp_path):
    from data.fetch_external import write_feed_manifest

    data = b"http://example.test/login\n"
    digest = hashlib.sha256(data).hexdigest()
    manifest = write_feed_manifest({"openphish_feed_x.txt": digest}, tmp_path / "feeds")
    assert manifest.parent == tmp_path / "feeds"
    assert manifest.name == "sha256_manifest.txt"
    assert digest in manifest.read_text(encoding="utf-8")
    assert "openphish_feed_x.txt" in manifest.read_text(encoding="utf-8")


def test_hf_snapshot_download_is_revision_pinned():
    text = (ROOT / "data" / "fetch_external.py").read_text(encoding="utf-8")
    assert "revision=HF_REVISIONS" in text
    assert "HF_REVISION" in text
    assert "TODO" in text
    from data.fetch_external import HF, HF_REVISIONS

    assert set(HF_REVISIONS) == set(HF)


def test_source_map_whatsapp_paths_are_anonymised():
    raw = (ROOT / "data" / "source_map.yaml").read_text(encoding="utf-8")
    assert "chat_1" in raw and "chat_2" in raw
    entries = yaml.safe_load(raw)
    chats = [e for e in entries if e.get("id", "").startswith("sms_wa1618i_whatsapp_chat_")]
    assert [e["id"] for e in chats] == [
        "sms_wa1618i_whatsapp_chat_1", "sms_wa1618i_whatsapp_chat_2"]
    assert chats[0]["path"].endswith("WhatsApp Chat with chat_1.txt")
    assert chats[1]["path"].endswith("WhatsApp Chat with chat_2.txt")


def test_build_corpus_maps_legacy_whatsapp_filenames(tmp_path):
    from data.build_corpus import resolve_legacy_chat_file, build_corpus

    raw_dir = tmp_path / "raw"
    proc_dir = tmp_path / "processed"
    chat_dir = raw_dir / "sms" / "wa1618i__whatsapp-scam-dataset"
    chat_dir.mkdir(parents=True)
    (chat_dir / "WhatsApp Chat with 111 111 1111.txt").write_text(
        "first legacy chat line\nsecond legacy chat line\n", encoding="utf-8")
    (chat_dir / "WhatsApp Chat with 222 222 2222.txt").write_text(
        "other legacy chat line\n", encoding="utf-8")
    (chat_dir / "WhatsApp Chat with Violine (1).txt").write_text(
        "named chat line\n", encoding="utf-8")

    canonical1 = chat_dir / "WhatsApp Chat with chat_1.txt"
    canonical2 = chat_dir / "WhatsApp Chat with chat_2.txt"
    assert resolve_legacy_chat_file(canonical1).name == "WhatsApp Chat with 111 111 1111.txt"
    assert resolve_legacy_chat_file(canonical2).name == "WhatsApp Chat with 222 222 2222.txt"

    source_map = [
        {"id": "chat_1", "corpus": "sms",
         "path": "sms/wa1618i__whatsapp-scam-dataset/WhatsApp Chat with chat_1.txt",
         "format": "txt_lines", "fixed_label": "scam", "channel": "whatsapp",
         "lang": "en", "synthetic": False, "licence": "CC0-1.0",
         "evidence": "test"},
        {"id": "chat_2", "corpus": "sms",
         "path": "sms/wa1618i__whatsapp-scam-dataset/WhatsApp Chat with chat_2.txt",
         "format": "txt_lines", "fixed_label": "scam", "channel": "whatsapp",
         "lang": "en", "synthetic": False, "licence": "CC0-1.0",
         "evidence": "test"},
    ]
    (tmp_path / "source_map.yaml").write_text(yaml.dump(source_map), encoding="utf-8")
    sms_stats, _ = build_corpus(source_map_path=str(tmp_path / "source_map.yaml"),
                                raw_dir=str(raw_dir), processed_dir=str(proc_dir))
    assert sms_stats["sources"]["chat_1"]["rows_kept"] == 2
    assert sms_stats["sources"]["chat_2"]["rows_kept"] == 1


def _gather_args(text=None, file=None):
    return argparse.Namespace(file=file, text_option=None, text=text)


def test_gather_messages_truncates_overlong_message(capsys):
    from sentinel.cli import gather_messages

    messages = gather_messages(_gather_args(text="x" * 2500), None)
    assert len(messages) == 1
    assert len(messages[0]) == 2000
    assert "2000" in capsys.readouterr().err.lower()


def test_gather_messages_caps_run_at_10000(tmp_path, capsys):
    from sentinel.cli import gather_messages

    f = tmp_path / "msgs.txt"
    f.write_text("\n".join(f"msg {i}" for i in range(10005)), encoding="utf-8")
    messages = gather_messages(_gather_args(file=str(f)), None)
    assert len(messages) == 10000
    assert "10000" in capsys.readouterr().err.lower()


@pytest.mark.parametrize("rel", ["training/url/train_url.py", "training/url_v2/train_url_v2.py"])
def test_training_parity_load_uses_weights_only_and_tensor_payload(rel):
    text = (ROOT / rel).read_text(encoding="utf-8")
    assert "torch.load('{OUT}/parity_inputs.pt', weights_only=True)" in text
    assert '"th": torch.tensor(th)' in text


@pytest.mark.parametrize("rel", ["training/url/train_url.py", "training/url_v2/train_url_v2.py"])
def test_training_runtime_pip_install_is_pinned_and_index_documented(rel):
    text = (ROOT / rel).read_text(encoding="utf-8")
    assert "executorch==1.5.1" in text
    assert "torch==2.15.0+cpu" in text
    assert "PIP_INDEX_URL" in text
    assert "https://pypi.org/simple" in text
    assert "https://download.pytorch.org/whl/cpu" in text
