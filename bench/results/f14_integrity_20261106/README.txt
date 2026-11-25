Galaxy F14 model integrity check, 2026-11-06.
models.sha256: manifest pushed to the app models folder. Each hash was computed on the PC from the
trusted local model files and also matched sha256sum of the files already on the phone (7 of 7).
f14_verified.png: start-up with the good manifest (status line still says verifying: known UI bug,
the models did load and Llama answered, advice hash f512788f as before).
f14_tamper.png: manifest with the first 16 hex digits of the url_cnn_v2.pte hash replaced by zeros.
The app shows: MODEL ERRORS: SHA-256 mismatch for url_cnn_v2.pte; refusing to load.
The good manifest was pushed back afterwards.
