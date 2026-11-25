Galaxy F14, APK from bdcc10e, 2026-11-07. Cold start each run: HOME, am kill, then
am start -f 0x10008000 (NEW_TASK|CLEAR_TASK) with ACTION_SEND text/plain. Run 1 used a
KYC scam text; runs 2-5 an electricity-disconnection scam text with a different ref number.
Without the CLEAR_TASK flag, am start only brought the old task to the front (intent
extras are not part of intent matching), so those attempts were discarded.
Before bdcc10e (bench/results/f14_final_sms_20261107_run2): first advice after a cold
open used prompt_path=full_prompt, 301 prompt tokens, TTFT 4797 ms.
