import argparse
import copy
import glob
import json
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path
import numpy as np
import torch
import torch.nn as nn
from transformers import AutoTokenizer, AutoModelForSequenceClassification
from executorch.exir import to_edge_transform_and_lower
from executorch.backends.xnnpack.partition.xnnpack_partitioner import XnnpackPartitioner
from executorch.runtime import Runtime
import executorch.kernels.quantized


def build_parser():
    parser = argparse.ArgumentParser(description="Export pruned and quantized SMS model for ExecuTorch")
    parser.add_argument("--model-dir", default="models/sms_v5/sms_model")
    parser.add_argument("--tokenizer-dir", default="models/sms_v5/tokenizer")
    parser.add_argument("--parity-path", default="models/sms_v5/parity_inputs.pt")
    parser.add_argument("--corpus-dir", default="data/processed/sms")
    parser.add_argument("--out-dir", default="models/sms_v5d")
    parser.add_argument("--id-map", default=None, help="Input id_map.json for an already-pruned --model-dir (a v5d-style pruned checkpoint, e.g. a DT-2 fine-tuned model). Without it, id_map.json next to --model-dir is used. No error when unset for full-vocab models. The input id_map translates old (full-vocab) token ids into the pruned model's rows; the exported id_map is written to --out-dir/id_map.json.")
    parser.add_argument("--python", default=sys.executable, help="Python interpreter used to run the corpus-text extraction script (defaults to the running interpreter). No hard-coded machine path.")
    parser.add_argument("--dynamic-seq", action="store_true", help="Export with dynamic sequence length (Dim min 2, max 128)")
    parser.add_argument("--hybrid-fp32", action="store_true", help="Also export hybrid pruned FP32 model with Int8Embedding (sms_fp32_int8emb.pte)")
    return parser


def translate_prune(input_id_map, kept_old_ids, unk_old_id, special_old_ids, old_vocab_size):
    """Translate a prune in old (full-vocab) space into pruned-model row selection.

    kept_old_ids: old-space token ids that survived pruning (corpus + specials + parity).
    Returns (kept_pruned_rows, output_id_map) where kept_pruned_rows are indices
    into the input (already pruned) model's embedding and output_id_map maps
    old ids to new indices in the re-pruned embedding. Pure, so it can be tested
    without torch/ExecuTorch.
    """
    pruned_unk = input_id_map[unk_old_id] if unk_old_id < len(input_id_map) else input_id_map[0]
    kept_pruned = {input_id_map[t] for t in kept_old_ids if 0 <= t < len(input_id_map)}
    kept_pruned.add(pruned_unk)
    for s in special_old_ids:
        if 0 <= s < len(input_id_map):
            kept_pruned.add(input_id_map[s])
    kept_rows = sorted(kept_pruned)
    pos = {p: i for i, p in enumerate(kept_rows)}
    unk_pos = pos[pruned_unk]
    output_id_map = []
    for old_id in range(old_vocab_size):
        p = input_id_map[old_id] if old_id < len(input_id_map) else pruned_unk
        output_id_map.append(pos.get(p, unk_pos))
    return kept_rows, output_id_map


def main():
    parser = build_parser()
    args = parser.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    print(f"Starting SMS export script. model_dir={args.model_dir}, out_dir={args.out_dir}")

    kept_tokens_path = os.path.join(args.out_dir, "kept_tokens.json")
    if os.path.exists(kept_tokens_path):
        print(f"Loading cached kept_tokens from {kept_tokens_path}")
        with open(kept_tokens_path, "r", encoding="utf-8") as f:
            kept_tokens = json.load(f)
    else:
        corpus_texts_path = os.path.join(args.out_dir, "corpus_texts.json")
        if not os.path.exists(corpus_texts_path):
            print("corpus_texts.json not found. Generating corpus texts via --python interpreter...")
            win_py = args.python
            args_corpus_dir = args.corpus_dir.replace("\\", "/")
            args_out_dir = args.out_dir.replace("\\", "/")
            corpus_texts_path_str = corpus_texts_path.replace("\\", "/")
            extract_script = textwrap.dedent('''
                import glob
                import json
                import os
                import sys
                import pandas as pd
                import pyarrow.parquet as pq

                corpus_dir = sys.argv[1]
                out_dir = sys.argv[2]
                corpus_texts_path = sys.argv[3]

                sys.path.insert(0, ".")
                try:
                    from training.sms.train_sms import fix_mojibake
                except Exception as e:
                    # Source: fix_mojibake from training/sms/train_sms.py
                    def fix_mojibake(text: str) -> str:
                        """Repair mojibake (up to 3 passes, checking character count reduction from moji set)."""
                        if not isinstance(text, str):
                            return text
                        moji_set = {chr(0xC3), chr(0xC2), chr(0xE2), chr(0xF0)}
                        current = text
                        for _ in range(3):
                            try:
                                repaired = current.encode("cp1252").decode("utf-8")
                            except UnicodeError:
                                try:
                                    repaired = current.encode("latin-1").decode("utf-8")
                                except UnicodeError:
                                    break
                            if repaired == current:
                                break
                            orig_count = sum(1 for c in current if c in moji_set)
                            rep_count = sum(1 for c in repaired if c in moji_set)
                            if rep_count < orig_count:
                                current = repaired
                            else:
                                break
                        return current

                parquet_files = sorted(glob.glob(os.path.join(corpus_dir, '*.parquet')))
                all_texts = []
                repaired_count = 0
                for pf in parquet_files:
                    try:
                        tbl = pq.read_table(pf, columns=['text'])
                        df = tbl.to_pandas()
                        texts = [t for t in df['text'].dropna() if isinstance(t, str) and t.strip()]
                        for t in texts:
                            all_texts.append(t)
                            rep = fix_mojibake(t)
                            if rep != t:
                                all_texts.append(rep)
                                repaired_count += 1
                    except Exception as e:
                        print(f'Error reading {pf}: {e}')

                os.makedirs(out_dir, exist_ok=True)
                with open(corpus_texts_path, 'w', encoding='utf-8') as f:
                    json.dump(all_texts, f)
                print(f'Repaired {repaired_count} texts.')
                print(f'Saved {len(all_texts)} corpus texts ({repaired_count} repaired).')
            ''')
            cmd = [
                win_py, "-c",
                extract_script,
                args_corpus_dir,
                args_out_dir,
                corpus_texts_path_str,
            ]
            res = subprocess.run(cmd, capture_output=True, text=True)
            print(f"Windows python extraction stdout:\n{res.stdout}\nstderr:\n{res.stderr}")
            if res.returncode != 0:
                raise RuntimeError(f"Failed to extract corpus texts via Windows python: {res.stderr}")

        # 1. Token set
        print("Loading tokenizer and tokenizing corpus texts in batches (batch_size=50000)...")
        tokenizer = AutoTokenizer.from_pretrained(args.tokenizer_dir)
        with open(corpus_texts_path, "r", encoding="utf-8") as f:
            corpus_texts = json.load(f)

        all_token_ids = set()
        batch_size = 50000
        for i in range(0, len(corpus_texts), batch_size):
            batch = corpus_texts[i:i+batch_size]
            encoded = tokenizer(batch, truncation=True, max_length=128, add_special_tokens=True, verbose=False)
            for ids in encoded["input_ids"]:
                all_token_ids.update(ids)

        # Union special tokens and parity input ids
        all_token_ids.update(tokenizer.all_special_ids)
        parity = torch.load(args.parity_path, weights_only=True)  # parity_inputs.pt holds tensors only (input_ids, attention_mask, logits): safe to load with weights_only=True
        parity_ids = parity["input_ids"]
        all_token_ids.update(parity_ids.flatten().tolist())

        kept_tokens = sorted(list(all_token_ids))
        with open(kept_tokens_path, "w", encoding="utf-8") as f:
            json.dump(kept_tokens, f)
        print(f"Saved kept_tokens to {kept_tokens_path}")

    corpus_texts_path = os.path.join(args.out_dir, "corpus_texts.json")
    if os.path.exists(corpus_texts_path):
        print(f"Deleting scratch dump {corpus_texts_path}...")
        try:
            os.remove(corpus_texts_path)
        except Exception as e:
            print(f"Warning: could not remove {corpus_texts_path}: {e}")

    tokenizer = AutoTokenizer.from_pretrained(args.tokenizer_dir)

    # 2. id_map
    old_vocab_size = len(tokenizer)
    unk_id = tokenizer.unk_token_id

    # Already-pruned input (a v5d-style checkpoint, e.g. a DT-2 fine-tuned
    # model): its embedding has fewer rows than the full-vocab tokenizer, and
    # kept_tokens (old ids) cannot index it directly. Translate the prune
    # through the input id_map instead. config.json's vocab_size is the
    # checkpoint's embedding size.
    model_vocab_size = None
    try:
        with open(os.path.join(args.model_dir, "config.json"), "r", encoding="utf-8") as f:
            model_vocab_size = json.load(f).get("vocab_size")
    except Exception:
        model_vocab_size = None
    is_pruned_input = model_vocab_size is not None and model_vocab_size < old_vocab_size

    prune_rows = kept_tokens
    if is_pruned_input:
        input_id_map_path = args.id_map
        if input_id_map_path is None:
            sibling = os.path.normpath(os.path.join(str(args.model_dir), "..", "id_map.json"))
            if os.path.isfile(sibling):
                input_id_map_path = sibling
        if input_id_map_path is None:
            raise RuntimeError(
                "--model-dir looks already pruned (vocab_size "
                f"{model_vocab_size} < tokenizer {old_vocab_size}) but no input id_map "
                "could be found; pass --id-map <id_map.json> (e.g. models/sms_v5d/id_map.json) "
                "so old token ids can be translated into the pruned model's rows."
            )
        with open(input_id_map_path, "r", encoding="utf-8") as f:
            input_id_map = json.load(f)
        prune_rows, id_map = translate_prune(
            input_id_map, kept_tokens, unk_id, list(tokenizer.all_special_ids), old_vocab_size
        )
        print(f"Already-pruned input (vocab {model_vocab_size}): input id_map {input_id_map_path}, "
              f"kept {len(prune_rows)} pruned rows")
    else:
        new_unk_idx = kept_tokens.index(unk_id) if unk_id in kept_tokens else 0
        old_to_new = {old_id: new_idx for new_idx, old_id in enumerate(kept_tokens)}
        id_map = []
        for old_id in range(old_vocab_size):
            if old_id in old_to_new:
                id_map.append(old_to_new[old_id])
            else:
                id_map.append(new_unk_idx)

    kept_vocab_size = len(prune_rows)
    print(f"Kept vocab size: {kept_vocab_size} (from old vocab size {len(tokenizer)})")

    id_map_path = os.path.join(args.out_dir, "id_map.json")
    with open(id_map_path, "w", encoding="utf-8") as f:
        json.dump(id_map, f)
    print(f"Saved id_map.json to {id_map_path}")

    # 3. Prune
    print("Pruning model embeddings...")
    model = AutoModelForSequenceClassification.from_pretrained(args.model_dir)
    old_emb = model.get_input_embeddings()
    new_weight = old_emb.weight[prune_rows].clone().detach()
    new_emb = nn.Embedding(len(prune_rows), old_emb.embedding_dim, padding_idx=old_emb.padding_idx)
    new_emb.weight.data.copy_(new_weight)
    model.set_input_embeddings(new_emb)
    model.config.vocab_size = len(prune_rows)

    pruned_model_dir = os.path.join(args.out_dir, "sms_model")
    pruned_tokenizer_dir = os.path.join(args.out_dir, "tokenizer")
    os.makedirs(pruned_model_dir, exist_ok=True)
    os.makedirs(pruned_tokenizer_dir, exist_ok=True)
    model.save_pretrained(pruned_model_dir)
    tokenizer.save_pretrained(pruned_tokenizer_dir)
    print(f"Saved pruned model to {pruned_model_dir} and tokenizer to {pruned_tokenizer_dir}")

    # 4. Wrapper module & export fp32 pruned
    class Int8Embedding(nn.Module):
        def __init__(self, W: torch.Tensor):
            super().__init__()
            scale = W.abs().amax(dim=1, keepdim=True).clamp(min=1e-8) / 127.0
            weight_q = torch.round(W / scale).clamp(-127, 127).to(torch.int8)
            self.register_buffer("weight_q", weight_q)
            self.register_buffer("scale", scale)

        def forward(self, input_ids: torch.Tensor) -> torch.Tensor:
            return self.weight_q[input_ids].to(torch.float32) * self.scale[input_ids]

    class SMSExportWrapper(nn.Module):
        def __init__(self, mod):
            super().__init__()
            self.model = mod
        def forward(self, input_ids, attention_mask):
            outputs = self.model(input_ids=input_ids, attention_mask=attention_mask)
            return outputs.logits

    wrapper = SMSExportWrapper(model).eval()
    parity = torch.load(args.parity_path, weights_only=True)  # parity_inputs.pt holds tensors only (input_ids, attention_mask, logits): safe to load with weights_only=True
    # Parity ids are old (full-vocab) space; remap them into this export's
    # pruned space so tracing never indexes past the pruned embedding.
    parity_ids = parity["input_ids"].long()
    parity_pruned_ids = torch.tensor(
        [[id_map[int(v)] for v in row] for row in parity_ids.tolist()], dtype=torch.long
    )
    if args.dynamic_seq:
        seq_dim = torch.export.Dim("seq_len", min=2, max=128)
        dynamic_shapes = ({1: seq_dim}, {1: seq_dim})
        x_ids = parity_pruned_ids[:1, :64].long()
        x_att = torch.ones((1, 64), dtype=torch.long)
    else:
        dynamic_shapes = None
        x_ids = parity_pruned_ids[:1].long()
        x_att = parity["attention_mask"][:1].long()

    print("Exporting FP32 pruned model...")
    if dynamic_shapes is not None:
        ep_fp32 = torch.export.export(wrapper, (x_ids, x_att), dynamic_shapes=dynamic_shapes)
    else:
        ep_fp32 = torch.export.export(wrapper, (x_ids, x_att))
    prog_fp32 = to_edge_transform_and_lower(ep_fp32, partitioner=[XnnpackPartitioner()]).to_executorch()
    fp32_pte_path = os.path.join(args.out_dir, "sms_fp32.pte")
    with open(fp32_pte_path, "wb") as f:
        f.write(prog_fp32.buffer)
    print(f"Saved FP32 PTE to {fp32_pte_path}")

    if args.hybrid_fp32:
        print("Exporting hybrid FP32+Int8Embedding model...")
        model_hybrid = copy.deepcopy(model).eval()
        W = model_hybrid.get_input_embeddings().weight.detach()
        hybrid_emb = Int8Embedding(W)
        model_hybrid.set_input_embeddings(hybrid_emb)
        wrapper_hybrid = SMSExportWrapper(model_hybrid).eval()
        if dynamic_shapes is not None:
            ep_hybrid = torch.export.export(wrapper_hybrid, (x_ids, x_att), dynamic_shapes=dynamic_shapes)
        else:
            ep_hybrid = torch.export.export(wrapper_hybrid, (x_ids, x_att))
        prog_hybrid = to_edge_transform_and_lower(ep_hybrid, partitioner=[XnnpackPartitioner()]).to_executorch()
        hybrid_pte_path = os.path.join(args.out_dir, "sms_fp32_int8emb.pte")
        tmp_hybrid_pte = hybrid_pte_path + ".tmp"
        with open(tmp_hybrid_pte, "wb") as f:
            f.write(prog_hybrid.buffer)
        os.replace(tmp_hybrid_pte, hybrid_pte_path)
        print(f"Saved hybrid FP32+Int8Embedding PTE to {hybrid_pte_path}")

    from training.sms.int8_route import choose_int8_route
    int8_success = False
    int8_errors = []
    int8_pte_path = os.path.join(args.out_dir, "sms_int8.pte")
    route_used = None
    embedding_dtype = str(model.get_input_embeddings().weight.dtype)

    import traceback
    from torchao.quantization import quantize_, Int8DynamicActivationIntxWeightConfig
    from torchao.quantization.granularity import PerAxis
    from torchao.utils import unwrap_tensor_subclass

    # Route decision: route_b_ok means manual int8 embedding succeeded — the only
    # acceptable shipped route. Route A is diagnostic only.
    # A. Linear only — diagnostic attempt only, NEVER shipped as the int8 file.
    route_a_ok = False
    try:
        print("Attempting Route A: Linear-only int8 quantization (diagnostic only)...")
        model_a = copy.deepcopy(model).eval()
        wrapper_a = SMSExportWrapper(model_a).eval()
        quantize_(wrapper_a, Int8DynamicActivationIntxWeightConfig(weight_dtype=torch.int8, weight_granularity=PerAxis(0)))
        wrapper_a = unwrap_tensor_subclass(wrapper_a)
        if dynamic_shapes is not None:
            ep_a = torch.export.export(wrapper_a, (x_ids, x_att), dynamic_shapes=dynamic_shapes)
        else:
            ep_a = torch.export.export(wrapper_a, (x_ids, x_att))
        _ = to_edge_transform_and_lower(ep_a, partitioner=[XnnpackPartitioner()]).to_executorch()
        route_a_ok = True
        print("Route A export succeeded (not shipped as int8).")
    except Exception as e:
        err_msg = traceback.format_exc()
        print(f"Route A failed: {e}\n{err_msg}")
        int8_errors.append(err_msg)

    # B. Manual int8 embedding — the only acceptable route for the shipped int8 file.
    prog_b = None
    route_b_ok = False
    try:
        print("Attempting Route B: Manual int8 embedding + Linear quantize_...")
        model_b = copy.deepcopy(model).eval()
        W = model_b.get_input_embeddings().weight.detach()
        int8_emb = Int8Embedding(W)
        model_b.set_input_embeddings(int8_emb)
        wrapper_b = SMSExportWrapper(model_b).eval()
        quantize_(wrapper_b, Int8DynamicActivationIntxWeightConfig(weight_dtype=torch.int8, weight_granularity=PerAxis(0)))
        wrapper_b = unwrap_tensor_subclass(wrapper_b)
        if dynamic_shapes is not None:
            ep_b = torch.export.export(wrapper_b, (x_ids, x_att), dynamic_shapes=dynamic_shapes)
        else:
            ep_b = torch.export.export(wrapper_b, (x_ids, x_att))
        prog_b = to_edge_transform_and_lower(ep_b, partitioner=[XnnpackPartitioner()]).to_executorch()
        route_b_ok = True
    except Exception as e:
        err_msg = traceback.format_exc()
        print(f"Route B failed: {e}\n{err_msg}")
        int8_errors.append(err_msg)

    route_used = choose_int8_route(route_a_ok, route_b_ok)
    int8_success = (route_used != "none")

    if route_b_ok:
        tmp_pte = int8_pte_path + ".tmp"
        with open(tmp_pte, "wb") as f:
            f.write(prog_b.buffer)
        os.replace(tmp_pte, int8_pte_path)
        embedding_dtype = str(int8_emb.weight_q.dtype)
        print(f"Saved INT8 PTE via {route_used} to {int8_pte_path}")
    else:
        # Never fall back to Route A: it produces an unrunnable .pte on Linux.
        fatal = ("INT8 export failed: Route B (manual int8 embedding) did not succeed. "
                 "Route A (torchao linear-only) is not a valid substitute — it leaves a "
                 "dequantize_affine op with no ExecuTorch kernel on the Arm Linux, so the "
                 "shipped sms_int8.pte would crash on-device. Exiting non-zero.")
        print(f"[FATAL] {fatal}")
        int8_errors.append(fatal)
        if os.path.exists(int8_pte_path):
            try:
                os.remove(int8_pte_path)
            except Exception as remove_exc:
                print(f"[FATAL] failed to remove stale {int8_pte_path}: {remove_exc}")
        fail_q = {
            "kept_vocab": kept_vocab_size,
            "fp32": None,
            "int8": {"success": False, "route": route_used or "none", "errors": int8_errors},
        }
        if args.hybrid_fp32:
            fail_q["fp32_int8emb"] = None
        try:
            with open(os.path.join(args.out_dir, "export_q.json"), "w", encoding="utf-8") as fail_f:
                json.dump(fail_q, fail_f, indent=2, default=str)
        except Exception as write_exc:
            print(f"[FATAL] failed to write {os.path.join(args.out_dir, 'export_q.json')}: {write_exc}")
        sys.exit(1)
    # 6. Parity evaluation function
    def evaluate_pte(pte_path, parity_data, id_map_list, is_dynamic=False, is_int8=False):
        if not os.path.exists(pte_path):
            return None
        size_mb = os.path.getsize(pte_path) / (1024 * 1024)
        
        def get_method():
            try:
                return Runtime.get().load_program(pte_path).load_method("forward")
            except Exception as e:
                if "operator" in str(e).lower() or "op" in str(e).lower() or "kernel" in str(e).lower() or "missing" in str(e).lower():
                    try:
                        import executorch.kernels.quantized
                        return Runtime.get().load_program(pte_path).load_method("forward")
                    except Exception:
                        pass
                raise e

        meth = get_method()
        
        orig_ids = parity_data["input_ids"][:200]
        att_mask = parity_data["attention_mask"][:200].long()
        true_logits = parity_data["logits"][:200]
        
        remapped_ids = torch.tensor([[id_map_list[int(x)] for x in row] for row in orig_ids], dtype=torch.long)
        
        # 1. Padded-128 parity
        et_logits_list = []
        for i in range(len(remapped_ids)):
            try:
                out = meth.execute([remapped_ids[i:i+1], att_mask[i:i+1]])
            except Exception as exec_e:
                if "operator" in str(exec_e).lower() or "op" in str(exec_e).lower() or "kernel" in str(exec_e).lower() or "missing" in str(exec_e).lower():
                    import executorch.kernels.quantized
                    out = meth.execute([remapped_ids[i:i+1], att_mask[i:i+1]])
                else:
                    raise exec_e
            et_logits_list.append(out[0])
        et_logits = torch.cat(et_logits_list, dim=0)
        
        max_abs_diff = (et_logits - true_logits).abs().max().item()
        argmax_agree = int((et_logits.argmax(dim=-1) == true_logits.argmax(dim=-1)).sum().item())
        
        res = {
            "size_mb": float(size_mb),
            "max_abs_logit_diff": float(max_abs_diff),
            "argmax_agree": int(argmax_agree),
        }

        # 2. Dynamic parity (strip to real length)
        if is_dynamic:
            et_dynamic_logits_list = []
            for i in range(len(remapped_ids)):
                real_len = int(att_mask[i].sum().item())
                r_id = remapped_ids[i:i+1, :real_len]
                r_att = torch.ones((1, real_len), dtype=torch.long)
                try:
                    out = meth.execute([r_id, r_att])
                except Exception as exec_e:
                    if "operator" in str(exec_e).lower() or "op" in str(exec_e).lower() or "kernel" in str(exec_e).lower() or "missing" in str(exec_e).lower():
                        import executorch.kernels.quantized
                        out = meth.execute([r_id, r_att])
                    else:
                        raise exec_e
                et_dynamic_logits_list.append(out[0])
            et_dynamic_logits = torch.cat(et_dynamic_logits_list, dim=0)

            dyn_max_abs_diff = (et_dynamic_logits - true_logits).abs().max().item()
            dyn_argmax_agree = int((et_dynamic_logits.argmax(dim=-1) == true_logits.argmax(dim=-1)).sum().item())

            res["padded_parity"] = {
                "max_abs_logit_diff": float(max_abs_diff),
                "argmax_agree": int(argmax_agree),
            }
            res["dynamic_parity"] = {
                "max_abs_logit_diff": float(dyn_max_abs_diff),
                "argmax_agree": int(dyn_argmax_agree),
            }
            res["dynamic_max_abs_logit_diff"] = float(dyn_max_abs_diff)
            res["dynamic_argmax_agree"] = int(dyn_argmax_agree)

        # 3. Latency timing
        if is_dynamic and is_int8:
            latency_by_length = {}
            for L in [16, 32, 64, 128]:
                t_id = remapped_ids[0:1, :L]
                t_att = torch.ones((1, L), dtype=torch.long)
                for _ in range(5):
                    try:
                        meth.execute([t_id, t_att])
                    except Exception:
                        import executorch.kernels.quantized
                        meth.execute([t_id, t_att])
                lat_L = []
                for _ in range(50):
                    t0 = time.perf_counter()
                    try:
                        meth.execute([t_id, t_att])
                    except Exception:
                        import executorch.kernels.quantized
                        meth.execute([t_id, t_att])
                    lat_L.append((time.perf_counter() - t0) * 1e3)
                latency_by_length[str(L)] = float(np.median(lat_L))
            res["latency_by_length_ms"] = latency_by_length
            res["p50_ms"] = latency_by_length["128"]
        else:
            lat = []
            r_id = remapped_ids[0:1]
            r_att = att_mask[0:1]
            for _ in range(5):
                try:
                    meth.execute([r_id, r_att])
                except Exception:
                    import executorch.kernels.quantized
                    meth.execute([r_id, r_att])
            for _ in range(50):
                t0 = time.perf_counter()
                try:
                    meth.execute([r_id, r_att])
                except Exception:
                    import executorch.kernels.quantized
                    meth.execute([r_id, r_att])
                lat.append((time.perf_counter() - t0) * 1e3)
            p50_ms = float(np.percentile(lat, 50))
            res["p50_ms"] = float(p50_ms)

        return res

    print("Evaluating FP32 PTE parity...")
    fp32_eval = evaluate_pte(fp32_pte_path, parity, id_map, is_dynamic=args.dynamic_seq, is_int8=False)
    print(f"FP32 eval: {fp32_eval}")

    hybrid_eval = None
    if args.hybrid_fp32:
        print("Evaluating hybrid FP32+Int8Embedding PTE parity...")
        hybrid_pte_path = os.path.join(args.out_dir, "sms_fp32_int8emb.pte")
        hybrid_eval = evaluate_pte(hybrid_pte_path, parity, id_map, is_dynamic=args.dynamic_seq, is_int8=False)
        print(f"Hybrid eval: {hybrid_eval}")

    int8_eval = None
    if int8_success:
        print("Evaluating INT8 PTE parity...")
        int8_eval = evaluate_pte(int8_pte_path, parity, id_map, is_dynamic=args.dynamic_seq, is_int8=True)
        if int8_eval is not None:
            int8_eval["route"] = route_used
            int8_eval["embedding_dtype"] = embedding_dtype
            int8_eval["errors"] = int8_errors
        print(f"INT8 eval: {int8_eval}")
    else:
        int8_eval = {
            "size_mb": 0.0,
            "max_abs_logit_diff": None,
            "argmax_agree": 0,
            "p50_ms": 0.0,
            "route": route_used,
            "embedding_dtype": embedding_dtype,
            "errors": int8_errors
        }

    # 7. Write export_q.json
    export_q_data = {
        "kept_vocab": kept_vocab_size,
        "fp32": fp32_eval,
        "int8": int8_eval
    }
    if args.hybrid_fp32:
        export_q_data["fp32_int8emb"] = hybrid_eval
    export_q_path = os.path.join(args.out_dir, "export_q.json")
    with open(export_q_path, "w", encoding="utf-8") as f:
        json.dump(export_q_data, f, indent=2, default=float)
    print(f"Saved export_q.json to {export_q_path}")
    print("Export process completed successfully.")

if __name__ == "__main__":
    main()
