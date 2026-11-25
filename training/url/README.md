# Phishing URL classifier (Kaggle)

Character-level CNN (about 34k parameters) trained on PhiUSIIL. All training runs on Kaggle.

```
python training/sync_shared.py                      # after editing sentinel/url_features.py
kaggle kernels push -p training/url
kaggle kernels status <kaggle-user>/ps3-url-classifier
kaggle kernels output <kaggle-user>/ps3-url-classifier -p models/url
```

| Output | Content |
|---|---|
| `url_cnn.pt` | PyTorch state dict (best validation F1 epoch) |
| `url_cnn.pte` | ExecuTorch program, XNNPACK, fp32, input int64 [1, 200] |
| `vocab.json` | Printable-ASCII vocab: 0 pad, 1 unknown, max_len 200 |
| `metrics.json` | Test precision/recall/F1/FPR/ROC-AUC, path-only subset, threshold, row counts, versions |
| `export.json` | ExecuTorch version, PyTorch vs .pte parity (max logit diff, label mismatches) |
| `train_log.txt` | Full run log |

Notes
- URLs are normalised (scheme, `www.`, trailing slash removed) and deduplicated before the split, so the
  model cannot learn the PhiUSIIL homepage-vs-path shortcut. The path-only subset metric checks this.
- Threshold = best validation F1 with validation FPR at most 2 %.
- Latency in `metrics.json` is Kaggle CPU; target-device numbers come from `bench/`.
