# Privacy evidence

## Network access

The Android manifest declares SMS, MMS, and notification permissions required by the app. It has no `INTERNET`, `ACCESS_NETWORK_STATE`, or `ACCESS_WIFI_STATE` permission, so the app cannot open network connections. The manifest test in `tests/test_android_manifest_privacy.py` checks that no network permission is introduced.

An airplane-mode run confirms that model loading and message analysis still work offline. Android packet capture was not performed because the test phones are not rooted.

## Local processing and logs

The SMS, URL, and advice models run locally. Android logs truncated SHA-256 values and timing fields rather than SMS or URL text. The Python CLI prints its scan result to standard output by design; redirected output can therefore contain the message text. The Llama fallback writes its prompt to a mode-0600 temporary file and removes it after inference.

## Optional screen check

The accessibility screen-check feature is off by default. It reads the active window only when the user taps the accessibility control, skips password fields and Sentinel's own package, and sends the selected text only to local analysis. It does not run in the background or log the screen text.

## Alert storage

Analyzed incoming messages may be retained in the alert list, encrypted with an Android Keystore key. Users can clear the list in the app; uninstalling also removes its stored data. Routine OTP and bank messages are excluded.
