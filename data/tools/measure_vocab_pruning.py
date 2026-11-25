"""Measure how many tokens of Tamil / Hindi text the pruned SMS vocabulary maps to unknown.

The shipped SMS model keeps only tokens seen in the training corpus (id_map.json). A token
outside that set is fed to the model as the unknown token, so text in an unseen script is
partly invisible to it. Run from the repo root with any Python that has `tokenizers`.
"""
import collections
import csv
import json
import sys

from tokenizers import Tokenizer

MODEL_DIR = sys.argv[1] if len(sys.argv) > 1 else "models/sms_v5d"


def main():
    tok = Tokenizer.from_file(f"{MODEL_DIR}/tokenizer/tokenizer.json")
    tok.no_padding()  # the saved tokenizer pads to 128; padding must not dilute the share
    tok.no_truncation()
    id_map = json.load(open(f"{MODEL_DIR}/id_map.json", encoding="utf-8"))
    unk = tok.token_to_id("<unk>")
    pruned_unk = id_map[unk]
    print(f"id_map entries {len(id_map)}, distinct kept ids {len(set(id_map))}, unk {unk} -> {pruned_unk}")

    def lost_share(texts):
        lost = total = 0
        for text in texts:
            ids = tok.encode(text, add_special_tokens=False).ids
            lost += sum(1 for i in ids if i != unk and id_map[i] == pruned_unk)
            total += len(ids)
        return lost, total

    groups = collections.defaultdict(list)
    for row in csv.DictReader(open("bench/heldout_ml/golden_ta_hi.csv", encoding="utf-8")):
        groups["golden " + row["language"]].append(row["text"])
    for row in csv.DictReader(open("bench/heldout/heldout_20261107.csv", encoding="utf-8")):
        if len(groups["heldout " + row["language"]]) < 300:
            groups["heldout " + row["language"]].append(row["text"])
    out = {}
    for name in sorted(groups):
        lost, total = lost_share(groups[name])
        out[name] = {"texts": len(groups[name]), "tokens": total, "mapped_to_unk": lost,
                     "share": round(lost / max(total, 1), 4)}
        print(f"{name:22s} texts {len(groups[name]):4d} tokens {total:6d} mapped to unk {lost:6d} share {lost / max(total, 1):.3f}")
    json.dump(out, open("docs/multilang/vocab_pruning_20261111.json", "w", encoding="utf-8"), indent=2)


if __name__ == "__main__":
    main()
