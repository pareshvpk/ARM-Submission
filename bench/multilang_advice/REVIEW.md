# Multilang advice probe: Llama 3.2 1B, Hindi and Tamil

This probe called the model directly without the production advice guard and English prompt path, so it shows raw model behaviour for native-script prompts, not what the shipped app shows.

Measurement only. Each risky code-mixed SMS runs through the shipped advice prompt (EN) and the same prompt with the language phrase switched to the target language (NATIVE). Prompts and evidence are the real ones; no guard() or advisor.py change.

- Model: `models/llama32_et_community/Llama-3.2-1B-Instruct-SpinQuant_INT4_EO8.pte` (the phone model), run with executorch's portable binding.
- Generation: manual greedy loop (argmax) over the .pte `forward` method, one prompt prefill then one token per step, stopping on `<|eot_id|>`/`<|end_of_text|>`. The wheel's `TextLLMRunner` is not usable here: its token callback strict-decodes each piece as UTF-8 and raises `UnicodeDecodeError` on partial Tamil/Devanagari byte sequences. The tokenizer is rebuilt from `tokenizer.model` with the Llama 3 regex and special-token table; on the English check it produced the same 381 prompt tokens and the same generated text as `TextLLMRunner`. Timings are after a one-off warm-up (first forward pages in the weights).
- Settings: temperature 0, echo False, seq_len 1024, `num_bos=0` because `build_prompt` already starts with `<|begin_of_text|>`; adding a BOS would duplicate it. `max_new_tokens` is the CLI flag of the run that produced this file.
- Runtime: the executorch wheel does not register the llama custom kernels by itself, so the probe dlopens `libexecutorch_kernels_quantized.so`, `libexecutorch_kernels_optimized.so` and `custom_ops/libcustom_ops_aot_lib.so` before loading the model.
- NATIVE replacement: "plain simple English" -> "plain simple Hindi written in Devanagari script" (Hindi) or "plain simple Tamil written in Tamil script" (Tamil), asserted to occur exactly once.
- `projected M31 s` = generated tokens / 5.7 tok/s and `projected F14 s` = generated tokens / 10.0 tok/s. These are ESTIMATES from the token count, not measurements on those phones.

## Summary

| language | condition | n | median gen tok | max gen tok | median total s | median projected M31 s | hit_max | median script_share | has_1930 | leaks_link | leaks_phone | says_click |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Tamil | EN | 10 | 73.00 | 116 | 10.68 | 12.81 | 0 | 1.00 | 5 | 1 | 0 | 2 |
| Tamil | NATIVE | 10 | 300.00 | 300 | 39.57 | 52.63 | 9 | 1.00 | 0 | 0 | 0 | 0 |
| Hindi | EN | 10 | 73.00 | 111 | 10.86 | 12.81 | 0 | 1.00 | 5 | 0 | 0 | 2 |
| Hindi | NATIVE | 10 | 63.50 | 114 | 9.10 | 11.14 | 0 | 0.00 | 5 | 0 | 0 | 0 |

## Messages (EN and NATIVE side by side)

### ta-s01-01 (Tamil, template ta-s01)

Evidence: label `scam`, risk 0.83, level `high`

SMS text:

```
இறுதி நினைவூட்டல்: அன்புள்ள customer, உங்கள் bank account KYC expire ஆகிவிட்டது. இன்று update செய்யவில்லை என்றால் account block ஆகும். Verify செய்ய: https://bank-kyc-check.example
```

| EN (plain simple English) | NATIVE |
|---|---|
| The risk is that the user's bank account may be blocked due to a KYC (Know Your Customer) expiration. This is a common tactic used by scammers to gain unauthorized access to accounts. To verify the account, type https://bank-kyc-check.example in your browser. | இறுதி நினைவூட்டல் குறைவாக இருக்கும் என்றால் உங்கள் வருமான குறைவாக இருக்கும். உங்கள் வருமான குறைவாக இருக்கும் என்றால் உங்கள் வருமான குறைவாக இருக்கும். உங்கள் வருமான குறைவாக இருக்கும் என்றால் உங்கள் வருமான குறைவ�<br><br>Quality (good/ok/bad): |

### ta-s02-01 (Tamil, template ta-s02)

Evidence: label `scam`, risk 0.78, level `high`

SMS text:

```
Service update: SBI KYC pending என்று message வந்துள்ளது. Account active-ஆக இருக்க இந்த link-ல் Aadhaar details submit செய்யவும்: https://sbi-update.example
```

| EN (plain simple English) | NATIVE |
|---|---|
| The risk is that the message may be a scam, and clicking on the link may lead to unauthorized access to your account. The link appears to be legitimate, but it's untrusted, and there's no guarantee it's safe. It's recommended to verify the authenticity of the link by checking the official SBI website or contacting the bank directly. | இந்த செயல் முறை மற்ற தயாராக இருக்கும் என்று கூறாது. இந்த செயல் முறை மற்ற தயாராக இருக்கும் என்று கூறாது. இந்த செயல் முறை மற்ற தயாராக இருக்கும் என்று கூறாது. இந்த செயல் முறை மற்ற தயாராக இருக்கும் என்று கூறாது.<br><br>Quality (good/ok/bad): |

### ta-s03-01 (Tamil, template ta-s03)

Evidence: label `scam`, risk 0.81, level `high`

SMS text:

```
முக்கிய தகவல்: உங்கள் PAN-ஐ bank account-உடன் link செய்யவில்லை. இன்று 9 PMக்குள் update செய்யாவிட்டால் transaction stop ஆகும். Link: https://pan-link.example
```

| EN (plain simple English) | NATIVE |
|---|---|
| The risk is that you may be asked to link your bank account to a website, which could be a scam. This is likely because scammers may try to trick you into revealing your account information. To stay safe, do not click on any links or open any attachments from unknown sources. | உங்கள் பணம் குறைந்தது என்று கூறப்படுவது போல் உங்கள் பணம் குறைந்தது என்று கூறப்படுவது போல் உங்கள் பணம் குறைந்தது என்று கூறப்படுவது போல் உங்கள் பணம் குறைந்தது என்று கூறப்படுவது போல் உங்கள் பணம் குறைந்தது என்று கூறப்படுவ<br><br>Quality (good/ok/bad): |

### ta-s04-01 (Tamil, template ta-s04)

Evidence: label `scam`, risk 0.82, level `high`

SMS text:

```
TNEB bill pending. இன்று 10 AMக்கு power cut செய்யப்படும். Connection avoid செய்ய உடனே இந்த app install செய்யவும்: https://tneb-pay.example
```

| EN (plain simple English) | NATIVE |
|---|---|
| The risk is likely that the scammer is trying to trick the user into installing an app to access their TNEB bill information. The scammer may be trying to avoid a power cut by installing the app. To avoid this risk, the user should not install the app and should report the scam to the official TNEB website or 1930 for fraud. | இன்று 10 மணி க்கு போட்டி செய்யப்படும். இதன் மூலம் பெயர் மாற்றம் செய்யப்படும். இதன் மூலம் பெயர் மாற்றம் செய்யப்படும். இதன் மூலம் பெயர் மாற்றம் செய்யப்படும். இதன் மூலம் பெயர் மாற்றம் செய்யப்படும். இதன் மூலம் பெயர் மாற்ற<br><br>Quality (good/ok/bad): |

### ta-s05-01 (Tamil, template ta-s05)

Evidence: label `unwanted`, risk 0.47, level `medium`

SMS text:

```
உங்கள் EB service number-க்கு payment due உள்ளது. Late fee avoid செய்ய இந்த WhatsApp number-க்கு bill amount அனுப்பவும்: 9XXXXXX120
```

| EN (plain simple English) | NATIVE |
|---|---|
| The risk is that the user may be asked to pay a late fee by someone who is not the official EB service provider. This is likely a scammer trying to trick the user into paying a fake fee. To stay safe, the user should not respond to the message or click on any links. Instead, they should report the message to the official EB service provider or call 1930 for fraud. | உங்கள் எப்போக்கு செய்து பயணம் செய்து பயணம் செய்து பயணம் செய்து பயணம் செய்து பயணம் செய்து பயணம் செய்து பயணம் செய்து பயணம் செய்து பயணம் செய்து பயணம் செய்து பயணம் செய்து பயணம் செய்து பயணம் செய்து பயணம் செய்து பயணம் செய்த<br><br>Quality (good/ok/bad): |

### ta-s06-01 (Tamil, template ta-s06)

Evidence: label `scam`, risk 0.75, level `high`

SMS text:

```
அவசர அறிவிப்பு: Congratulations! உங்களுக்கு ₹4,800 cashback credit ஆக காத்திருக்கிறது. Amount receive செய்ய collect request accept செய்து UPI PIN enter செய்யவும்.
```

| EN (plain simple English) | NATIVE |
|---|---|
| The risk is that the message may be a scam, and the user may be asked to provide sensitive information, such as their UPI PIN, to receive the cashback credit. This is likely a phishing attempt. To stay safe, the user should not respond to the message or enter any sensitive information. | இது ஒரு சர்க்கரை தடுப்பு காரணமாக இருக்கும். இது செய்யவும் செய்து பயனுக்கு இடம் இல்லாத செய்தியாக இருக்கும். இது செய்து பயனுக்கு இடம் இல்லாத செய்தியாக இருக்கும். இது செய்து பயனுக்கு இடம் இல்லாத செய்தியாக இருக்கும். இது செய்த<br><br>Quality (good/ok/bad): |

### ta-s07-01 (Tamil, template ta-s07)

Evidence: label `scam`, risk 0.70, level `high`

SMS text:

```
அவசர அறிவிப்பு: Refund process செய்ய ₹1 மட்டும் pay செய்யுங்கள். அதன் பிறகு உங்கள் UPI account-க்கு ₹5,000 credit ஆகும். இந்த QR-ஐ scan செய்யவும்.
```

| EN (plain simple English) | NATIVE |
|---|---|
| The risk is that you may be asked to pay for a refund that may not be legitimate. This is likely because scammers may be trying to trick you into sending money. To stay safe, do not click on any links or open any attachments, and instead report the scam to the official app or website, or call 1930 for fraud, or Sanchar Saathi Chakshu for fraud SMS. | இந்த செயல் முறை அதிகமாக விகித்து விட்டது. இது பயனற்று என்று கண்டறியப்பட்டது. இதன் மூலம் உங்கள் உங்கள் பணம் பயன்படுத்தும் முறை மற்றும் உங்கள் பணம் பயன்படுத்தும் முறை மற்றும் உங்கள் பணம் பயன்படுத்தும் முறை மற்றும் உங்கள் பணம் பய�<br><br>Quality (good/ok/bad): |

### ta-s08-01 (Tamil, template ta-s08)

Evidence: label `scam`, risk 0.81, level `high`

SMS text:

```
அவசர அறிவிப்பு: தவறுதலாக உங்கள் account-க்கு ₹8,500 அனுப்பிவிட்டேன். உடனே இந்த UPI ID-க்கு return செய்யுங்கள்: refundhelp@ok-example
```

| EN (plain simple English) | NATIVE |
|---|---|
| The risk is that you may be scammed into sending money to someone who doesn't have the account you're trying to recover. This is likely because the scammer is trying to trick you into sending money to a fake account. To stay safe, you should not respond to the message or click on any links. Instead, you should report the incident to the official UPI website or call 1930 for fraud information. | தவறுதலாக உங்கள் account-க்கு ₹8,500 அனுப்பிவிட்டேன். உடனே இந்த UPI ID-க்கு return செய்யுங்கள்: refundhelp@ok-example. இது தவறான அறிவிப்புக்கு இடம் காட்டுகிறது. இது தவறான அறிவிப்புக்கு இடம் காட்டுகிறது. இது தவறான அறிவிப்புக்கு இடம் காட்டுகிறது. இது தவறான அறிவிப்புக்கு �<br><br>Quality (good/ok/bad): |

### ta-s09-01 (Tamil, template ta-s09)

Evidence: label `scam`, risk 0.79, level `high`

SMS text:

```
Service update: உங்கள் parcel address incomplete-ஆக உள்ளது. Delivery resume செய்ய ₹25 fee pay செய்து details update செய்யவும்: https://parcel-track.example
```

| EN (plain simple English) | NATIVE |
|---|---|
| The risk is that the user may be asked to pay a fee to update their parcel address, which may be a scam. The scammer may also ask for personal details to be updated, which is a risk. The user should be cautious and not click on any links or make any payments without verifying the authenticity of the request.<br><br>Safe steps:<br>1. Do not click on any links or make any payments.<br>2. Report the incident to the official app or website.<br>3. Contact 1930 for fraud or Sanchar Saathi Chakshu for fraud SMS. | உங்கள் பரிமாண வரிசை தொடர்ந்து செய்யப்பட்ட பரிமாண தொடர்கள் குறைவாக இருக்கும். பரிமாண தொடர்கள் தொடர்ந்து செய்யப்பட்ட பரிமாண தொடர்கள் குறைவாக இருக்கும். பரிமாண தொடர்கள் தொடர்ந்து செய்யப்பட்ட பரிமாண தொடர்கள் குறைவாக இர<br><br>Quality (good/ok/bad): |

### ta-s10-01 (Tamil, template ta-s10)

Evidence: label `scam`, risk 0.80, level `high`

SMS text:

```
உடனடி நடவடிக்கை: India Post parcel hold-ல் உள்ளது. Release செய்ய இந்த link-ல் card details மற்றும் OTP enter செய்யவும்: https://post-release.example
```

| EN (plain simple English) | NATIVE |
|---|---|
| The risk is that the user may be asked to enter their card details and OTP to release a parcel, which could be a scam. This is likely because the user is receiving a suspicious message from India Post. To stay safe, the user should not click on the link or enter any sensitive information. | இந்த செயல் மற்றும் தகவல் தொடர்பு மற்றும் தகவல் தொடர்பு மற்றும் தொடர்பு மற்றும் தொடர்பு மற்றும் தொடர்பு மற்றும் தொடர்பு மற்றும் தொடர்பு மற்றும் தொடர்பு மற்றும் தொடர்பு மற்றும் தொடர்பு மற்றும் தொடர்பு மற்றும் தொடர்பு மற்றும் தொ�<br><br>Quality (good/ok/bad): |

### hi-s01-01 (Hindi, template hi-s01)

Evidence: label `scam`, risk 0.83, level `high`

SMS text:

```
ज़रूरी जानकारी: प्रिय customer, आपके bank account की KYC expire हो गई है। आज update नहीं किया तो account block हो जाएगा। Verify करें: https://bank-kyc-check.example
```

| EN (plain simple English) | NATIVE |
|---|---|
| The risk is that the user's account may be blocked without their knowledge or consent. This is likely because the scammer may have obtained the user's account information through a KYC (Know Your Customer) process that was not properly secured. To avoid this risk, the user should verify the authenticity of the link by checking the official website or reporting the incident to the bank's customer support. | The risk is likely a scam, as the account is blocked without verification. The link provided may lead to phishing or malware. To stay safe, verify the link by typing the URL into the official app or website, or report the incident to cybercrime.gov.in or 1930 for fraud.<br><br>Quality (good/ok/bad): |

### hi-s02-01 (Hindi, template hi-s02)

Evidence: label `scam`, risk 0.82, level `high`

SMS text:

```
आखिरी चेतावनी: SBI KYC pending है। Account active रखने के लिए इस link पर Aadhaar details submit करें: https://sbi-update.example
```

| EN (plain simple English) | NATIVE |
|---|---|
| The risk is that the user may be asked to submit their Aadhaar details to the SBI website, which is a risk of identity theft. This is likely because the link provided is not a genuine SBI website. The risk is high because the link looks like it's from a legitimate website, but it's actually a scam. | This message may be a scam. The link provided looks like it's from the State Bank of India, but it's not a genuine link. It may lead to phishing or malware. It's likely that the link is designed to steal your personal data. Never click on suspicious links or submit sensitive information without verifying the authenticity of the website.<br><br>Safe steps:<br>1. Verify the link by typing the URL by hand on your phone's browser.<br>2. Report the incident to the SBI's official app or website.<br>3. Contact 1930 for fraud reporting.<br><br>Quality (good/ok/bad): |

### hi-s03-01 (Hindi, template hi-s03)

Evidence: label `scam`, risk 0.82, level `high`

SMS text:

```
महत्वपूर्ण सूचना: आपका PAN bank account से link नहीं है। 9 PM तक update नहीं किया तो transactions stop हो जाएँगे। Link: https://pan-link.example
```

| EN (plain simple English) | NATIVE |
|---|---|
| The risk is that the user's PAN bank account may be linked to a scam, and if the link is clicked, the transactions may stop. This is likely because the link is from a untrusted source. To stay safe, the user should not click on the link and should report the incident to the authorities. | This message looks like a scam. It may be a phishing attempt to steal your PAN (Pan Card) number. The link provided is likely to be a fake website that will ask for your PAN number and other sensitive information. It is recommended to report this to the authorities and not to click on any links or open any attachments.<br><br>Quality (good/ok/bad): |

### hi-s04-01 (Hindi, template hi-s04)

Evidence: label `scam`, risk 0.81, level `high`

SMS text:

```
आपका TNEB bill pending है। आज 10 AM पर power cut होगा। बचने के लिए यह app install करें: https://tneb-pay.example
```

| EN (plain simple English) | NATIVE |
|---|---|
| The risk is that the user may be scammed into installing a malicious app to access their TNEB bill information. The app may contain malware that could steal sensitive information. The user should be cautious and report the incident to the official TNEB website or 1930 for fraud. | This is a scam. The risk is high. The scammer is likely trying to trick you into installing a malicious app to steal your personal data.<br><br>Quality (good/ok/bad): |

### hi-s05-01 (Hindi, template hi-s05)

Evidence: label `scam`, risk 0.81, level `high`

SMS text:

```
महत्वपूर्ण सूचना: आपके EB service number का payment due है। Late fee से बचने के लिए इस WhatsApp number पर पैसे भेजें: 9XXXXXX120
```

| EN (plain simple English) | NATIVE |
|---|---|
| The risk is likely that the scammer is trying to trick you into sending money. This is a common tactic used by scammers to get you to pay for something you didn't order. It's also possible that the number is not a legitimate service number, but rather a number that looks like it. | This message may be a scam. The EB service number is not real, and the payment due is likely to be a scam. The fee is likely to be a charge, and the recipient may be asked to pay more than they need to.<br><br>Quality (good/ok/bad): |

### hi-s06-01 (Hindi, template hi-s06)

Evidence: label `scam`, risk 0.75, level `high`

SMS text:

```
Congratulations! आपको ₹4,800 cashback मिलने वाला है। Amount receive करने के लिए collect request accept करें और UPI PIN डालें।
```

| EN (plain simple English) | NATIVE |
|---|---|
| The risk is that the message may be a scam, and the user may be asked to provide sensitive information, such as their UPI PIN, which could be used for identity theft. The message may be a phishing attempt to trick the user into revealing their personal data. The user should be cautious and verify the authenticity of the message by contacting the official app or website, or reporting the incident to cybercrime.gov.in or calling 1930 for fraud. | This message may be a scam. The amount mentioned may not be genuine, and the link may lead to phishing or malware. It's likely that the scammer is trying to trick you into providing sensitive information. May you be cautious and verify the authenticity of the message before taking any action.<br><br>Quality (good/ok/bad): |

### hi-s07-01 (Hindi, template hi-s07)

Evidence: label `scam`, risk 0.70, level `high`

SMS text:

```
Refund process करने के लिए सिर्फ ₹1 pay करें। उसके बाद आपके UPI account में ₹5,000 credit होगा।
```

| EN (plain simple English) | NATIVE |
|---|---|
| The risk is that the message may be a scam, and the refund process may not actually work. It may look like a legitimate refund process, but it's likely to be a scam. It's also possible that the scammer is trying to trick you into paying for something you don't want.<br><br>Safe steps:<br>1. Don't click on any links or open any attachments.<br>2. Don't report the message to the official app or website.<br>3. Don't call 1930 or Sanchar Saathi Chakshu for fraud. | This message may be a scam. It looks like a refund claim, but the payment is likely to be for a fake service. The link provided is likely to lead to a phishing site. May you be cautious and verify the authenticity of the claim before taking any action.<br><br>Quality (good/ok/bad): |

### hi-s08-01 (Hindi, template hi-s08)

Evidence: label `scam`, risk 0.82, level `high`

SMS text:

```
तुरंत ध्यान दें: गलती से आपके account में ₹8,500 भेज दिए हैं। तुरंत इस UPI ID पर वापस भेज दें: refundhelp@ok-example
```

| EN (plain simple English) | NATIVE |
|---|---|
| The risk is that you may be scammed into sending money to someone who is not who they claim to be. This is likely because the message is asking you to send money to a UPI ID that looks like a legitimate service, but may be a fake account. To stay safe, do not respond to this message or click on any links. Instead, report the incident to the official Ok-Example app or website, or call 1930 for fraud reporting. | Risk: Unverified account information may be used to steal money. May be a phishing attempt. Likely to be a scammer's attempt to trick you into sending money.<br>Safe steps:<br>1. Report to cybercrime.gov.in or 1930 for fraud.<br>2. Check via the official app or website typed by hand.<br>3. Report to Sanchar Saathi Chakshu for fraud SMS.<br><br>Quality (good/ok/bad): |

### hi-s09-01 (Hindi, template hi-s09)

Evidence: label `scam`, risk 0.83, level `high`

SMS text:

```
Customer alert: आपका parcel गलत address की वजह से hold है। Delivery resume करने के लिए ₹25 fee pay करके details update करें: https://parcel-track.example
```

| EN (plain simple English) | NATIVE |
|---|---|
| The risk is that the customer's parcel may be held due to an incorrect address. The scammer may be asking the customer to pay a fee to update the delivery details. This is likely a scam, and the customer should not click on the link or pay the fee. Instead, they should report the incident to the official app or website, or call 1930 for fraud. | This may indicate a scam, as the customer's parcel is being held due to an incorrect address. The fee to update delivery details is ₹25, which may be a trap. It's recommended to verify the delivery status through the official app or website, or report the incident to cybercrime.gov.in or 1930 for fraud.<br><br>Quality (good/ok/bad): |

### hi-s10-01 (Hindi, template hi-s10)

Evidence: label `scam`, risk 0.84, level `high`

SMS text:

```
सावधान: India Post parcel hold पर है। Release करने के लिए इस link पर card details और OTP डालें: https://post-release.example
```

| EN (plain simple English) | NATIVE |
|---|---|
| The risk is that the link may be phishing for card details and OTP, which could lead to identity theft or financial loss. This is a common scam where scammers trick people into revealing sensitive information. It's best to avoid clicking on links from unknown sources, especially when it comes to sensitive information like card details and OTP. | Risk: Untrusted data may contain sensitive information, such as card details and OTP, which can be used for identity theft or financial loss. This is a likely scam, and the user should take action to protect themselves. Steps to take: Verify the link by typing the URL by hand, report to cybercrime.gov.in or 1930 for fraud, or Sanchar Saathi Chakshu for fraud SMS.<br><br>Quality (good/ok/bad): |

