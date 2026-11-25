# PS3 URL Classifier v2

Unified multi-source phishing URL classifier for Bharat AI-SoC PS3.

## Kaggle Commands

- **Push**: `kaggle kernels push -p training/url_v2`
- **Status**: `kaggle kernels status <kaggle-user>/ps3-url-classifier-v2`
- **Output**: `kaggle kernels output <kaggle-user>/ps3-url-classifier-v2 -p training/url_v2`

## Output Files

- `url_cnn_v2.pt`: PyTorch model state dict
- `url_cnn_v2.pte`: ExecuTorch serialized program (XNNPACK backend)
- `vocab.json`: Character vocabulary mapping (`pad: 0`, `unk: 1`, printable ASCII `32-126`)
- `metrics.json`: Comprehensive evaluation metrics (overall, per-source, per-label, subsets, Indian URLs, latency)
- `errors.csv`: Hardest errors (200 highest-scoring benign test URLs, 200 lowest-scoring bad test URLs)
- `export.json`: ExecuTorch export metadata and parity verification report
- `train_log.txt`: Complete training and evaluation transcript

## Environment Variables

- `PS3_INPUT_DIR`: Directory containing parquet corpus files (default `/kaggle/input`).
- `PS3_OUT_DIR`: Directory where output artifacts (`metrics.json`, `url_cnn_v2.pt`, etc.) are written (default `/kaggle/working`).
- `PS3_SKIP_EXPORT`: Set to `1` to skip the ExecuTorch export and parity verification step.

## Data Policy

- **Target**: `1` = any bad label (`phishing`, `malicious`, `defacement`, `malware`), `0` = `benign`.
- **Source Reading**: Parquet files read from `<kaggle-user>/ps3-corpus` under `/kaggle/input`.
- **Deduplication**: Deduplicated on `norm_url`. Any `norm_url` appearing with both target `0` and `1` (conflict) is dropped entirely.
- **Per-Source Capping**: At most 400,000 unique rows per source file (random, seed 42) to prevent dominant large datasets.
- **Group Splitting**: 80/10/10 split by `registered_domain` so no domain is in two splits. Exception: hosting list domains (`google.com`, `googleusercontent.com`, `firebaseapp.com`, `web.app`, `blogspot.com`, `github.io`, `weebly.com`, `wixsite.com`, `000webhostapp.com`, `sharepoint.com`, `microsoft.com`, `live.com`, `dropbox.com`, `ipfs.io`, `pages.dev`, `vercel.app`, `netlify.app`, `herokuapp.com`) are split by full `host` instead.
- **Batch Balancing**: Training batches balanced to roughly 1:1 using a weighted sampler.
