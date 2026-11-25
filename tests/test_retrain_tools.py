"""DT-2 retraining tooling tests: mining, mixing, CLI, fine-tune loop.

Uses only tiny fakes (no real model download): a fake tokenizer/model pair and
small parquet files. Pure-logic tests run without torch; torch-dependent tests
are skipped when torch is unavailable.
"""

import csv
import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from training.sms.finetune_sms import (  # noqa: E402
    build_parser as ft_parser,
    classification_metrics,
    mix_hard_negatives,
    stratified_sample,
)
from training.sms.mine_hard_negatives import (  # noqa: E402
    build_parser as mine_parser,
    compute_text_hash,
    load_heldout_hashes,
)


def _write_parquet(path, rows):
    import pyarrow as pa
    import pyarrow.parquet as pq

    table = pa.Table.from_pylist(rows)
    pq.write_table(table, str(path))


def _write_heldout_csv(path, texts):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["text", "truth", "source", "language"])
        w.writeheader()
        for t in texts:
            w.writerow({"text": t, "truth": "ham", "source": "s", "language": "English"})


# --- pure logic (no torch needed) -------------------------------------------


def test_compute_text_hash_matches_eval_heldout():
    from bench.heldout.eval_heldout import compute_text_hash as heldout_hash

    samples = ["Hello   WORLD", "  padded\ntext  ", "no-change", "", "₹ price 123"]
    for s in samples:
        assert compute_text_hash(s) == heldout_hash(s)


def test_load_heldout_hashes_roundtrip(tmp_path):
    heldout = tmp_path / "heldout.csv"
    texts = ["Hello   WORLD", "another SMS", "another SMS"]
    _write_heldout_csv(heldout, texts)
    hashes = load_heldout_hashes(heldout)
    assert compute_text_hash(" hello world ") in hashes
    assert compute_text_hash("another sms") in hashes
    assert compute_text_hash("not there") not in hashes
    assert len(hashes) == 2


def test_mix_hard_negatives_weighting():
    import pandas as pd

    train = pd.DataFrame({"text": [f"t{i}" for i in range(10)], "class_id": [0, 1, 2] * 3 + [0]})
    hn = pd.DataFrame({
        "text": ["hn1", "hn2", "hn3", "hn4"],
        "class_id": [0, 1, 0, 1],
    })
    mixed, eff = mix_hard_negatives(train, hn, weight=3.0, seed=7)
    assert eff == 12
    assert len(mixed) == 22
    mixed2, eff2 = mix_hard_negatives(train, hn, weight=1.0, seed=7)
    assert eff2 == 4 and len(mixed2) == 14
    mixed0, eff0 = mix_hard_negatives(train, hn, weight=0.0, seed=7)
    assert eff0 == 0 and len(mixed0) == 10
    mixed25, eff25 = mix_hard_negatives(train, hn, weight=2.5, seed=7)
    assert eff25 == 10 and len(mixed25) == 20
    again, _ = mix_hard_negatives(train, hn, weight=3.0, seed=7)
    assert mixed["text"].tolist() == again["text"].tolist()


def test_stratified_sample_proportions_and_size():
    import pandas as pd

    df = pd.DataFrame({
        "text": [f"t{i}" for i in range(100)],
        "class_id": [0] * 60 + [1] * 30 + [2] * 10,
    })
    out = stratified_sample(df, 50, seed=3)
    assert len(out) == 50
    counts = out["class_id"].value_counts().sort_index().to_dict()
    assert counts[0] == 30 and counts[1] == 15 and counts[2] == 5


def test_classification_metrics():
    m = classification_metrics([0, 1, 2], [0, 1, 2])
    assert m["macro_f1"] == 1.0
    m = classification_metrics([0, 0, 1, 1, 2, 2], [0, 1, 1, 1, 2, 0])
    assert set(m["per_class"]) == {"ham", "unwanted", "scam"}
    assert 0.0 <= m["macro_f1"] <= 1.0
    assert m["per_class"]["ham"]["support"] == 2


def test_cli_parsing():
    args = mine_parser().parse_args([
        "--out-dir", "out", "--batch-size", "32", "--limit", "100",
        "--model-dir", "m", "--tokenizer-dir", "t", "--id-map", "im",
        "--corpus-dir", "c", "--heldout-csv", "h",
    ])
    assert args.batch_size == 32 and args.limit == 100 and args.out_dir == "out"
    d = mine_parser().parse_args([])
    assert d.model_dir == "models/sms_v5d/sms_model"
    assert d.tokenizer_dir == "models/sms_v5d/tokenizer"
    assert d.id_map == "models/sms_v5d/id_map.json"
    assert d.heldout_csv == "bench/heldout/heldout_20261107.csv"

    fargs = ft_parser().parse_args([
        "--hn-weight", "4", "--lr", "5e-6", "--max-steps", "10",
        "--hard-negatives", "hn.parquet", "--out-dir", "o",
    ])
    assert fargs.lr == 5e-6 and fargs.max_steps == 10 and fargs.hn_weight == 4.0
    fd = ft_parser().parse_args([])
    assert fd.lr == 1e-5 and fd.epochs == 1 and fd.model_dir == "models/sms_v5d/sms_model"


def _stubbed_export_module(monkeypatch):
    """Import training.sms.export_sms with heavy deps stubbed (cleaned up by monkeypatch)."""
    for name in list(sys.modules):
        if name == "training.sms.export_sms":
            del sys.modules[name]
    torch = types.ModuleType("torch")
    torch_nn = types.ModuleType("torch.nn")

    class _Module:
        pass

    torch_nn.Module = _Module
    torch.nn = torch_nn
    transformers = types.ModuleType("transformers")
    transformers.AutoTokenizer = object
    transformers.AutoModelForSequenceClassification = object
    executorch = types.ModuleType("executorch")
    executorch.__path__ = []
    exir = types.ModuleType("executorch.exir")
    exir.to_edge_transform_and_lower = lambda *a, **k: None
    xnn = types.ModuleType("executorch.backends.xnnpack.partition.xnnpack_partitioner")
    xnn.XnnpackPartitioner = object
    runtime = types.ModuleType("executorch.runtime")
    runtime.Runtime = object
    kernels = types.ModuleType("executorch.kernels.quantized")
    for name, mod in [("torch", torch), ("torch.nn", torch_nn),
                      ("transformers", transformers), ("executorch", executorch),
                      ("executorch.exir", exir), ("executorch.backends", types.ModuleType("b")),
                      ("executorch.backends.xnnpack", types.ModuleType("x")),
                      ("executorch.backends.xnnpack.partition", types.ModuleType("p")),
                      ("executorch.backends.xnnpack.partition.xnnpack_partitioner", xnn),
                      ("executorch.runtime", runtime), ("executorch.kernels", types.ModuleType("k")),
                      ("executorch.kernels.quantized", kernels)]:
        monkeypatch.setitem(sys.modules, name, mod)
    import training.sms.export_sms as export_sms

    return export_sms


def test_export_cli_and_translate_prune(monkeypatch):
    export_sms = _stubbed_export_module(monkeypatch)
    args = export_sms.build_parser().parse_args([
        "--model-dir", "/tmp/ft/sms_model", "--out-dir", "/tmp/ft_out",
        "--id-map", "/tmp/ft/id_map.json", "--parity-path", "/tmp/ft/parity_inputs.pt",
    ])
    assert args.model_dir == "/tmp/ft/sms_model" and args.out_dir == "/tmp/ft_out"
    assert args.id_map == "/tmp/ft/id_map.json"
    defaults = export_sms.build_parser().parse_args([])
    assert defaults.model_dir == "models/sms_v5/sms_model"
    assert defaults.out_dir == "models/sms_v5d"

    # full-vocab ids 0..7 pruned as kept old ids {1,3,7} -> rows [1,3,7]; unk old 2 -> row 1
    input_id_map = [0, 1, 2, 3, 4, 5, 6, 7]
    kept_rows, out_map = export_sms.translate_prune(
        input_id_map, kept_old_ids=[1, 3, 7], unk_old_id=2, special_old_ids=[0, 2], old_vocab_size=8
    )
    # kept pruned rows: {1,3,7} + unk pruned (id_map[2]=2) + specials (0,2) -> [0,1,2,3,7]
    assert kept_rows == [0, 1, 2, 3, 7]
    assert out_map[1] == 1 and out_map[7] == 4 and out_map[0] == 0
    # dropped old ids (4,5,6) map to the unk position
    assert out_map[4] == 2 and out_map[5] == 2
    assert len(out_map) == 8


def test_build_train_val_split_tiny_corpus(tmp_path):
    import pandas as pd

    from training.sms.finetune_sms import build_train_val_split, load_source_info

    corpus = tmp_path / "sms"
    corpus.mkdir()
    words = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel",
             "india", "juliett", "kilo", "lima", "mike", "november", "oscar", "papa",
             "quebec", "romeo", "sierra", "tango", "uniform", "victor", "whiskey", "xray"]
    rows = []
    for i in range(300):
        cls = ["ham", "unwanted", "scam"][i % 3]
        rows.append({"text": f"unique message {words[i % 24]} number {i} says hello everyone",
                     "label": cls, "source": "src1", "text_hash": f"h{i}"})
    _write_parquet(corpus / "src1.parquet", rows)
    smap = tmp_path / "source_map.yaml"
    smap.write_text("- id: src1\n  corpus: sms\n", encoding="utf-8")
    info = load_source_info(str(smap))
    train, val, stats = build_train_val_split([str(corpus / "src1.parquet")], info, sample_size=1000, val_size=1000)
    assert len(train) + len(val) == 288  # 80/10 split; the 10% test part is unused here
    assert len(val) > 0
    assert set(train["label"].unique()) <= {"ham", "unwanted", "scam", "spam"}
    # held-out CSV is never read: no argument for it exists in this call path.
    assert set(val["class_id"].unique()) <= {0, 1, 2}


# --- torch-dependent tests (fake model/tokenizer) ----------------------------


class _FakeTokenizer:
    """Tiny deterministic tokenizer: marker token SCAMWORD -> id 99."""

    def __init__(self, vocab_size=128):
        self.vocab_size = vocab_size

    def __call__(self, texts, padding=None, truncation=None, max_length=128, return_tensors=None):
        import torch

        rows = []
        masks = []
        for text in texts:
            ids = [2] + [(ord(c) % 90) + 5 for c in str(text)[: max_length - 2]]
            if "SCAMWORD" in str(text):
                ids.append(99)
            ids = ids[:max_length]
            mask = [1] * len(ids)
            while len(ids) < max_length:
                ids.append(0)
                mask.append(0)
            rows.append(ids[:max_length])
            masks.append(mask[:max_length])
        return {
            "input_ids": torch.tensor(rows, dtype=torch.long),
            "attention_mask": torch.tensor(masks, dtype=torch.long),
        }


def _fake_mine_model(torch):
    class FakeModel(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.dummy = torch.nn.Parameter(torch.zeros(1))

        def forward(self, input_ids=None, attention_mask=None):
            import torch.nn.functional as F

            hit = (input_ids == 99).any(dim=1)
            logits = torch.zeros(input_ids.shape[0], 3)
            logits[hit] = torch.tensor([0.0, 0.0, 10.0])
            logits[~hit] = torch.tensor([5.0, 0.0, 0.0])
            return types.SimpleNamespace(logits=logits)

    return FakeModel()


def _fake_train_model(torch):
    class FakeModel(torch.nn.Module):
        def __init__(self, vocab_size=128):
            super().__init__()
            self.emb = torch.nn.Embedding(vocab_size, 8)
            self.fc = torch.nn.Linear(8, 3)

        def forward(self, input_ids=None, attention_mask=None):
            e = self.emb(input_ids) * attention_mask.unsqueeze(-1)
            denom = attention_mask.sum(dim=1, keepdim=True).clamp(min=1)
            pooled = e.sum(dim=1) / denom
            return types.SimpleNamespace(logits=self.fc(pooled))

    return FakeModel()


def test_mine_hard_negatives_with_fakes(tmp_path):
    torch = pytest.importorskip("torch")
    import pandas as pd

    from training.sms.mine_hard_negatives import mine_hard_negatives

    corpus = tmp_path / "sms"
    corpus.mkdir()
    rows = [
        {"text": "hello SCAMWORD promo", "label": "ham", "source": "src1"},
        {"text": "totally normal ham text", "label": "ham", "source": "src1"},
        {"text": "another SCAMWORD deal", "label": "unwanted", "source": "src1"},
        {"text": "real scam SCAMWORD", "label": "scam", "source": "src1"},
        {"text": "heldout SCAMWORD row", "label": "ham", "source": "src1"},
    ]
    parquet_path = corpus / "src1.parquet"
    _write_parquet(parquet_path, rows)
    heldout = tmp_path / "heldout.csv"
    _write_heldout_csv(heldout, ["heldout SCAMWORD row"])
    heldout_hashes = load_heldout_hashes(heldout)

    tokenizer = _FakeTokenizer()
    model = _fake_mine_model(torch)
    id_map = list(range(tokenizer.vocab_size))
    hard_df, summary = mine_hard_negatives(
        model, tokenizer, id_map, [str(parquet_path)], heldout_hashes,
        batch_size=2, device=torch.device("cpu"),
    )
    assert set(hard_df["text"]) == {"hello SCAMWORD promo", "another SCAMWORD deal"}
    assert summary["excluded_heldout"] == 1
    assert summary["rows_scanned"] == 3
    assert summary["by_label"] == {"ham": 1, "unwanted": 1}
    assert hard_df["p_scam"].gt(0.99).all()
    assert set(hard_df.columns) == {"text", "label", "source_file", "p_scam"}


def test_mine_limit_smoke(tmp_path):
    torch = pytest.importorskip("torch")

    from training.sms.mine_hard_negatives import mine_hard_negatives  # noqa: F401

    corpus = tmp_path / "sms"
    corpus.mkdir()
    rows = [{"text": f"text {i} SCAMWORD", "label": "ham", "source": "src1"} for i in range(10)]
    _write_parquet(corpus / "src1.parquet", rows)
    tokenizer = _FakeTokenizer()
    model = _fake_mine_model(torch)
    _, summary = mine_hard_negatives(
        model, tokenizer, list(range(tokenizer.vocab_size)), [str(corpus / "src1.parquet")], set(),
        batch_size=4, device=torch.device("cpu"), limit=3,
    )
    assert summary["rows_scanned"] == 3
    assert summary["hard_negatives"] == 3


def test_finetune_loop_runs_on_cpu(tmp_path):
    import pandas as pd

    torch = pytest.importorskip("torch")

    from training.sms.finetune_sms import run_training

    train = pd.DataFrame({
        "text": [f"train message {i} " + ("SCAMWORD" if i % 3 == 2 else "") for i in range(12)],
        "class_id": [i % 3 for i in range(12)],
    })
    val = pd.DataFrame({
        "text": [f"val message {i}" for i in range(6)],
        "class_id": [i % 3 for i in range(6)],
    })
    tokenizer = _FakeTokenizer()
    model = _fake_train_model(torch)
    id_map = list(range(tokenizer.vocab_size))
    log, parity = run_training(
        model, tokenizer, id_map, train, val, hn_count=4, hn_weight=3.0,
        lr=0.01, epochs=1, batch_size=4, seed=3, max_steps=3, log_interval=1,
        device=torch.device("cpu"),
    )
    assert log["steps_run"] == 3
    assert log["loss_log"] and len(log["loss_log"]) == 3
    assert log["rows_used"] == 12
    assert log["hard_negative_count"] == 4 and log["hard_negative_weight"] == 3.0
    assert 0.0 <= log["validation"]["macro_f1"] <= 1.0
    assert set(log["validation"]["per_class"]["ham"]) == {"precision", "recall", "f1", "support"}
    assert parity is not None and tuple(parity["input_ids"].shape) == (6, 128)
    assert parity["logits"].shape == (6, 3)
    # old-space parity ids: marker rows keep id 99 (no remap needed for identity id_map)
    assert torch.is_tensor(parity["input_ids"])
    json.dumps(log, default=str)  # JSON-serialisable


def test_finetune_full_epoch_small(tmp_path):
    import pandas as pd

    torch = pytest.importorskip("torch")

    from training.sms.finetune_sms import run_training

    train = pd.DataFrame({"text": [f"message {i}" for i in range(8)], "class_id": [i % 3 for i in range(8)]})
    val = pd.DataFrame({"text": [f"message {i}" for i in range(4)], "class_id": [i % 3 for i in range(4)]})
    tokenizer = _FakeTokenizer()
    model = _fake_train_model(torch)
    log, _ = run_training(
        model, tokenizer, list(range(tokenizer.vocab_size)), train, val,
        lr=0.01, epochs=1, batch_size=4, seed=1, log_interval=1,
        device=torch.device("cpu"),
    )
    assert log["steps_run"] == 2  # ceil(8/4)
    assert log["validation_rows"] == 4
