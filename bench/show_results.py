import json, sys
if len(sys.argv) < 2:
    print("usage: show_results.py <bench-json>", file=sys.stderr)
    sys.exit(2)
with open(sys.argv[1], encoding="utf-8") as fh:
    raw = fh.read()
dec = json.JSONDecoder(); i = 0
while True:
    while i < len(raw) and raw[i].isspace(): i += 1
    if i >= len(raw): break
    r, i = dec.raw_decode(raw, i)
    if "evidence" in r:
        e = r["evidence"]
        timings = r.get("timings_ms", {})
        if not isinstance(timings, dict):
            timings = {}
        print("==", e["level"], e["label"], e["risk"], r.get("advice_source"), {k: (round(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v) for k, v in timings.items()} or [k for k in r])
        print("  ", r.get("advice", "").replace("\n", " | ")[:430])
    elif "mode" in r:
        mode = r.get("mode")
        rec = r.get("record", {})
        dev = rec.get("device", "unknown")
        print(f"== [BENCHMARK: {mode.upper()}] on {dev} ({rec.get('os', '')}) ==")
        if "nfr" in r:
            nfr = r["nfr"]
            print(f"   NFR Result: {nfr}")
        if mode == "detectors":
            t = r.get("timings_ms", {}).get("total", {})
            print(f"   Detector Total Latency: p50={t.get('p50_ms')}ms, p95={t.get('p95_ms')}ms, p99={t.get('p99_ms')}ms, max={t.get('max_ms')}ms (count={t.get('count')})")
            print(f"   Memory: {r.get('memory', {})}")
        elif mode == "llm":
            m = r.get("metrics", {})
            ttft = m.get("ttft_seconds", {})
            dec = m.get("decode_tokens_per_sec", {})
            adv = m.get("total_advice_time_seconds", {})
            print(f"   Llama TTFT: p50={ttft.get('p50_s')}s, p95={ttft.get('p95_s')}s")
            print(f"   Decode tok/s: p50={dec.get('p50_tps')}, p95={dec.get('p95_tps')}")
            print(f"   Advice Time: p50={adv.get('p50_s')}s, p95={adv.get('p95_s')}s")
        elif mode == "soak":
            print(f"   Messages: {r.get('messages_processed')}, Peak RSS: {r.get('peak_rss_mb')} MB, RSS Growth: {r.get('rss_growth_percent')} %")
    else:
        print("==", [k for k in r])
