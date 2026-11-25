"""Kaggle script kernel: Tamil + Hindi fine-tune of the UNPRUNED v5 SMS checkpoint.

Multilang experiment (docs/multilang/PLAN_PREREGISTERED.md). Inputs are two private datasets:
  ps3-sms-corpus          the shipped training corpus (sms/*.parquet + source_map.yaml)
  ps3-sms-multilang-data  code/ (training/sms/*.py), sms_v5/ (unpruned checkpoint + tokenizer),
                          ml/ (Hindi public rows and machine-translated Tamil and Hindi rows)
The run itself is training/sms/finetune_sms.py, unchanged logic, called with arguments.
"""
import glob
import os
import shutil
import sys

INPUT = "/kaggle/input"
OUT = "/kaggle/working/sms_v6ml"
SAMPLE_SIZE = int(os.environ.get("FT_SAMPLE_SIZE", "120000"))  # rows of the original corpus kept in the mix (round 3: was 60000)
# The one knob a second run may change. Run 1 used 1.0 and failed the English false-alarm line
# (1.5 % against a 0.5 % limit); run 2 halves the weight of the added rows.
EXTRA_WEIGHT = float(os.environ.get("FT_EXTRA_WEIGHT", "0.5"))


def find(pattern):
    hits = sorted(glob.glob(f"{INPUT}/**/{pattern}", recursive=True))
    if not hits:
        raise RuntimeError(f"{pattern} not found under {INPUT}")
    return hits[0]


def main():
    code_root = os.path.dirname(os.path.dirname(os.path.dirname(find("code/training/sms/finetune_sms.py"))))
    sys.path.insert(0, code_root)
    from training.sms import finetune_sms

    source_map = find("source_map.yaml")
    corpus_dir = os.path.dirname(next(p for p in sorted(glob.glob(f"{INPUT}/**/*.parquet", recursive=True))
                                      if os.path.basename(os.path.dirname(p)) == "sms"))
    model_dir = os.path.dirname(find("sms_v5/sms_model/config.json"))
    tokenizer_dir = os.path.dirname(find("sms_v5/tokenizer/tokenizer.json"))
    extra = sorted(glob.glob(os.path.join(os.path.dirname(find("ml/*.parquet")), "*.parquet")))
    # Round 3: redacted real messages from the owner's inbox (development half), private dataset.
    extra += sorted(glob.glob(f"{INPUT}/**/real_dev_x*.parquet", recursive=True))
    print("code", code_root, "\ncorpus", corpus_dir, "\nmodel", model_dir, "\nextra", extra, flush=True)

    code = finetune_sms.main([
        "--model-dir", model_dir, "--tokenizer-dir", tokenizer_dir, "--id-map", "identity",
        "--corpus-dir", corpus_dir, "--source-map", source_map,
        "--hard-negatives", "", "--sample-size", str(SAMPLE_SIZE), "--val-size", "4000",
        "--extra-rows", *extra, "--extra-weight", str(EXTRA_WEIGHT),
        "--lr", "1e-5", "--epochs", "1", "--batch-size", "64", "--out-dir", OUT,
    ])
    shutil.copyfile(os.path.join(OUT, "training_log.json"), "/kaggle/working/training_log.json")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
