import pytest
import json
import yaml
import pandas as pd
import pyarrow.parquet as pq
from pathlib import Path

from data.build_corpus import (
    compute_text_hash,
    process_url_record,
    build_corpus,
    KNOWN_DOMAINS,
)

def test_malformed_url_is_dropped_not_raised():
    # a stray '[' makes urlparse raise "Invalid IPv6 URL"; the full build crashed on this once
    rec, err = process_url_record("http://[bad-host/login", "phishing", "0", "src", "f.csv")
    assert rec is None and err == "malformed_url"


def test_text_hash_normalization():
    t1 = "  Hello   World! 123  "
    t2 = "hello world! 123"
    assert compute_text_hash(t1) == compute_text_hash(t2)
    assert len(compute_text_hash(t1)) == 40
    assert compute_text_hash("") == ""
    assert compute_text_hash(None) == ""

def test_probable_inversion_flag(tmp_path):
    raw_dir = tmp_path / "raw"
    proc_dir = tmp_path / "processed"
    raw_dir.mkdir(parents=True)
    proc_dir.mkdir(parents=True)

    # Inverted feed: google.com given phishing label
    inverted_csv = raw_dir / "inverted_urls.csv"
    inverted_csv.write_text(
        "url,status\n"
        "https://www.google.com,1\n"
        "https://www.wikipedia.org,1\n"
        "https://www.badsite.com,0\n",
        encoding="utf-8"
    )

    # Normal feed: google.com given benign label
    normal_csv = raw_dir / "normal_urls.csv"
    normal_csv.write_text(
        "url,status\n"
        "https://www.google.com,0\n"
        "https://www.wikipedia.org,0\n"
        "https://www.badsite.com,1\n",
        encoding="utf-8"
    )
    # Hosted feed: phishing URLs hosted on trusted domains (docs.google.com, sites.google.com, google.com/url)
    hosted_csv = raw_dir / "hosted_urls.csv"
    hosted_csv.write_text(
        "url,status\n"
        "https://docs.google.com/forms/d/e/1FAIpQLSc,1\n"
        "https://sites.google.com/view/evilphish,1\n"
        "https://www.google.com/url?q=http://bad.com,1\n"
        "https://www.badsite.com,0\n",
        encoding="utf-8"
    )

    source_map = [
        {
            "id": "url_inverted_test",
            "corpus": "url",
            "path": "inverted_urls.csv",
            "format": "csv",
            "url_col": "url",
            "label_col": "status",
            "label_map": {0: "benign", 1: "phishing"},
            "channel": "web",
            "synthetic": False,
            "licence": "Test",
            "evidence": "Test inverted mapping where google gets phishing",
            "allow_inversion": True,
            "allow_inversion_reason": "Test fixture deliberately inverted to verify flag computation"
        },
        {
            "id": "url_hosted_test",
            "corpus": "url",
            "path": "hosted_urls.csv",
            "format": "csv",
            "url_col": "url",
            "label_col": "status",
            "label_map": {0: "benign", 1: "phishing"},
            "channel": "web",
            "synthetic": False,
            "licence": "Test",
            "evidence": "Test hosted phishing where phishing is on subdomains/paths"
        },
        {
            "id": "url_normal_test",
            "corpus": "url",
            "path": "normal_urls.csv",
            "format": "csv",
            "url_col": "url",
            "label_col": "status",
            "label_map": {0: "benign", 1: "phishing"},
            "channel": "web",
            "synthetic": False,
            "licence": "Test",
            "evidence": "Test normal mapping where google gets benign"
        }
    ]

    source_map_file = tmp_path / "source_map.yaml"
    with open(source_map_file, "w", encoding="utf-8") as f:
        yaml.dump(source_map, f)

    sms_stats, url_stats = build_corpus(
        source_map_path=str(source_map_file),
        raw_dir=str(raw_dir),
        processed_dir=str(proc_dir)
    )

    assert url_stats["sources"]["url_inverted_test"]["probable_inversion"] is True
    assert url_stats["sources"]["url_inverted_test"]["homepage_rows"]["phishing"] == 2
    assert "url_inverted_test" in url_stats["probable_inversion_sources"]

    assert url_stats["sources"]["url_hosted_test"]["probable_inversion"] is False
    assert url_stats["sources"]["url_hosted_test"]["hosted_rows"]["phishing"] == 3
    assert url_stats["sources"]["url_hosted_test"]["homepage_rows"] == {}
    assert "url_hosted_test" not in url_stats["probable_inversion_sources"]

    assert url_stats["sources"]["url_normal_test"]["probable_inversion"] is False
    assert url_stats["sources"]["url_normal_test"]["homepage_rows"]["benign"] == 2
    assert "url_normal_test" not in url_stats["probable_inversion_sources"]

def test_engine_fixtures(tmp_path):
    raw_dir = tmp_path / "raw"
    proc_dir = tmp_path / "processed"
    raw_dir.mkdir(parents=True)
    proc_dir.mkdir(parents=True)

    # 1. One CSV with label_map containing DROP and unmapped value
    csv_path = raw_dir / "sample_sms.csv"
    csv_path.write_text(
        "message,label\n"
        "Legit text 1,ham\n"
        "Scam offer claim now,scam\n"
        "Adult content to drop,adult\n"
        "Mysterious unmapped row,unexpected_code\n",
        encoding="utf-8"
    )

    # 2. One JSONL
    jsonl_path = raw_dir / "sample.jsonl"
    jsonl_content = (
        json.dumps({"msg": "Meeting at 3pm", "tag": "personal"}) + "\n" +
        json.dumps({"msg": "Win 1000 prize click here", "tag": "fraud"}) + "\n"
    )
    jsonl_path.write_text(jsonl_content, encoding="utf-8")

    # 3. One folder_docs
    docs_dir = raw_dir / "docs_folder"
    docs_dir.mkdir(parents=True)
    (docs_dir / "doc1.txt").write_text("Company memo for ham email", encoding="utf-8")
    (docs_dir / "doc2.txt").write_text("Quarterly financial report", encoding="utf-8")

    # 4. One fixed_label feed (txt_lines)
    feed_path = raw_dir / "phish_feed.txt"
    feed_path.write_text(
        "http://phish1.com/login\n"
        "https://phish2.org/secure\n",
        encoding="utf-8"
    )

    source_map = [
        {
            "id": "fixture_csv_sms",
            "corpus": "sms",
            "path": "sample_sms.csv",
            "format": "csv",
            "text_col": "message",
            "label_col": "label",
            "label_map": {"ham": "ham", "scam": "scam", "adult": "DROP"},
            "channel": "sms",
            "lang": "en",
            "synthetic": False,
            "licence": "MIT",
            "evidence": "CSV test fixture with DROP and unmapped"
        },
        {
            "id": "fixture_jsonl_sms",
            "corpus": "sms",
            "path": "sample.jsonl",
            "format": "jsonl",
            "text_col": "msg",
            "label_col": "tag",
            "label_map": {"personal": "ham", "fraud": "scam"},
            "channel": "sms",
            "lang": "en",
            "synthetic": False,
            "licence": "MIT",
            "evidence": "JSONL test fixture"
        },
        {
            "id": "fixture_folder_docs",
            "corpus": "sms",
            "path": "docs_folder",
            "format": "folder_docs",
            "fixed_label": "ham",
            "channel": "email",
            "lang": "en",
            "synthetic": False,
            "licence": "Public Domain",
            "evidence": "Folder docs fixture"
        },
        {
            "id": "fixture_fixed_feed",
            "corpus": "url",
            "path": "phish_feed.txt",
            "format": "txt_lines",
            "fixed_label": "phishing",
            "channel": "feed",
            "synthetic": False,
            "licence": "Open Source",
            "evidence": "Fixed label feed fixture"
        }
    ]

    source_map_file = tmp_path / "source_map.yaml"
    with open(source_map_file, "w", encoding="utf-8") as f:
        yaml.dump(source_map, f)

    sms_stats, url_stats = build_corpus(
        source_map_path=str(source_map_file),
        raw_dir=str(raw_dir),
        processed_dir=str(proc_dir)
    )

    # Verify CSV fixture stats (DROP and unmapped)
    csv_st = sms_stats["sources"]["fixture_csv_sms"]
    assert csv_st["rows_kept"] == 2  # ham and scam kept
    assert csv_st["label_counts"]["ham"] == 1
    assert csv_st["label_counts"]["scam"] == 1
    assert csv_st["drops"]["drop_label"] == 1  # adult dropped via DROP
    assert csv_st["drops"]["unmapped_label"] == 1  # unexpected_code unmapped
    assert "unexpected_code" in csv_st["unmapped_labels_top5"]

    # Verify JSONL fixture
    jsonl_st = sms_stats["sources"]["fixture_jsonl_sms"]
    assert jsonl_st["rows_kept"] == 2
    assert jsonl_st["label_counts"]["ham"] == 1
    assert jsonl_st["label_counts"]["scam"] == 1

    # Verify folder_docs fixture
    docs_st = sms_stats["sources"]["fixture_folder_docs"]
    assert docs_st["rows_kept"] == 2
    assert docs_st["label_counts"]["ham"] == 2

    # Verify fixed_label URL feed fixture
    feed_st = url_stats["sources"]["fixture_fixed_feed"]
    assert feed_st["rows_kept"] == 2
    assert feed_st["label_counts"]["phishing"] == 2

    # Verify output parquet files on disk
    p_csv = proc_dir / "sms/fixture_csv_sms.parquet"
    assert p_csv.exists()
    df_csv = pq.read_table(p_csv).to_pandas()
    assert len(df_csv) == 2
    assert set(df_csv["label"]) == {"ham", "scam"}
    assert "text_hash" in df_csv.columns

    p_url = proc_dir / "url/fixture_fixed_feed.parquet"
    assert p_url.exists()
    df_url = pq.read_table(p_url).to_pandas()
    assert len(df_url) == 2
    assert all(df_url["label"] == "phishing")
    assert "registered_domain" in df_url.columns

def test_nan_label_is_counted_as_drop(tmp_path):
    """F-10: raw NaN label rows must match float-NaN label_map keys and count as drop_label."""
    from data.build_corpus import map_label
    label_map = {float("nan"): "DROP", None: "DROP", "ham": "ham", "scam": "scam"}
    lbl, err = map_label(float("nan"), label_map)
    assert lbl == "DROP" and err is None

    lbl2, err2 = map_label(None, label_map)
    assert lbl2 == "DROP" and err2 is None


def test_build_fails_on_probable_inversion_without_allowlist(tmp_path):
    """F-11: corpus build must fail non-zero when probable_inversion is true and
    the source is not allowlisted via allow_inversion: true."""
    raw_dir = tmp_path / "raw"
    proc_dir = tmp_path / "processed"
    raw_dir.mkdir(parents=True)
    proc_dir.mkdir(parents=True)

    inverted_csv = raw_dir / "inverted_urls.csv"
    inverted_csv.write_text(
        "url,status\n"
        "https://www.google.com,1\n"
        "https://www.wikipedia.org,1\n"
        "https://www.badsite.com,0\n",
        encoding="utf-8"
    )

    source_map = [
        {
            "id": "url_inverted_no_allowlist",
            "corpus": "url",
            "path": "inverted_urls.csv",
            "format": "csv",
            "url_col": "url",
            "label_col": "status",
            "label_map": {0: "benign", 1: "phishing"},
            "channel": "web",
            "synthetic": False,
            "licence": "Test",
            "evidence": "Inverted source without allowlist must fail build"
        }
    ]

    source_map_file = tmp_path / "source_map.yaml"
    with open(source_map_file, "w", encoding="utf-8") as f:
        yaml.dump(source_map, f)

    try:
        build_corpus(
            source_map_path=str(source_map_file),
            raw_dir=str(raw_dir),
            processed_dir=str(proc_dir)
        )
        raise AssertionError("Expected SystemExit for probable_inversion without allowlist")
    except SystemExit as exc:
        assert exc.code != 0
        assert "F-11" in str(exc.code) or "probable inversion" in str(exc.code).lower()


def test_build_succeeds_on_probable_inversion_with_allowlist(tmp_path):
    """F-11: corpus build succeeds when probable_inversion is true and source is allowlisted."""
    raw_dir = tmp_path / "raw"
    proc_dir = tmp_path / "processed"
    raw_dir.mkdir(parents=True)
    proc_dir.mkdir(parents=True)

    inverted_csv = raw_dir / "inverted_urls.csv"
    inverted_csv.write_text(
        "url,status\n"
        "https://www.google.com,1\n"
        "https://www.wikipedia.org,1\n"
        "https://www.badsite.com,0\n",
        encoding="utf-8"
    )

    source_map = [
        {
            "id": "url_inverted_with_allowlist",
            "corpus": "url",
            "path": "inverted_urls.csv",
            "format": "csv",
            "url_col": "url",
            "label_col": "status",
            "label_map": {0: "benign", 1: "phishing"},
            "channel": "web",
            "synthetic": False,
            "licence": "Test",
            "evidence": "Inverted source with allowlist must succeed",
            "allow_inversion": True,
            "allow_inversion_reason": "Test fixture deliberately inverted"
        }
    ]

    source_map_file = tmp_path / "source_map.yaml"
    with open(source_map_file, "w", encoding="utf-8") as f:
        yaml.dump(source_map, f)

    sms_stats, url_stats = build_corpus(
        source_map_path=str(source_map_file),
        raw_dir=str(raw_dir),
        processed_dir=str(proc_dir)
    )
    assert url_stats["sources"]["url_inverted_with_allowlist"]["probable_inversion"] is True


def test_sms_map_label_rejects_unmapped_labels():
    """F-12: map_label must reject labels outside {ham, unwanted, spam, scam}."""
    from data.build_corpus import map_label
    label_map = {"ham": "ham", "unwanted": "unwanted", "spam": "unwanted", "scam": "scam"}
    assert map_label("ham", label_map) == ("ham", None)
    assert map_label("spam", label_map) == ("unwanted", None)
    assert map_label("scam", label_map) == ("scam", None)
    assert map_label("adult", label_map) == (None, "unmapped_label")
    assert map_label("unexpected_code", label_map) == (None, "unmapped_label")
