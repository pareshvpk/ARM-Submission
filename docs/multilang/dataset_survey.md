# Multilingual dataset survey (brief B1, 2026-11-10)

Published to main on 2026-11-15. This survey
only reads the public Kaggle and Hugging Face listing/download APIs; no personal information
was sent. Candidate files are in `data/raw_ml/<source>__<name>/`. Measurements were produced
by `data/tools/survey_ml_datasets.py`, which reuses `dominant_script` from
`bench/heldout/sim_script_gate.py`. "Tamil-script rows" and "Devanagari rows" mean the
dominant script holds at least 50 % of letters in the row.

Question asked: are there public SMS-like or chat-like messages written in **Tamil script** or
**Hindi Devanagari script** with a label mappable to ham / unwanted / scam? Romanised text was
explicitly out of scope.

**Headline:** the Hindi side has usable Devanagari material (about 23 k rows). The Tamil side
has almost nothing: the only Tamil-script dataset found is a fake-news/sentiment set with no
fraud or SMS rows, and every Tamil spam/scam dataset on either hub is romanised or is part of
the held-out test set.

## Search queries used

Kaggle (`kaggle datasets list -s`):
`tamil sms`, `tamil spam`, `tamil scam`, `tamil fraud message`, `hindi sms spam`,
`hindi scam message`, `indian multilingual spam`, `indic sms`, `smishing india`,
`multilingual phishing sms`, plus the follow-up queries `tamil`, `tamil nlp`,
`tamil text classification`, `devanagari sms`, `hindi text classification`, `hindi whatsapp`,
`smishing`, `indian sms`, `hindi spam`, `upi fraud`, `indian scam`, `multilingual spam`,
`sms fraud`, `tamil fraud`, `tamil fake`, `tamil whatsapp`, `tamil message`, `tamil scam sms`,
`hindi fraud`, `hindi cyber`, `anmolshrivastav`, `carnageiron`.

Hugging Face (`HfApi().list_datasets(search=...)`):
`tamil spam`, `tamil sms`, `hindi spam`, `hindi sms`, `indic spam`,
`multilingual sms scam`, `smishing`, `tamil scam`, `hindi scam`, `tamil smishing`,
`devanagari spam`, `india scam sms`, plus broad scans for `tamil`, `hindi`, `indic`,
`devanagari`, `anmolshrivastav`, `carnageiron`, `tamil fake news`, `hindi fake news`,
`india sms`, `indian sms`, and full-text scans of `spam`, `scam`, `fraud`, `phishing`,
`smishing`, `sms` filtered for Indic keywords.

## Candidate table

| Source id | URL | Licence | Total rows | Tamil-script rows | Devanagari rows | Label values and counts | Proposed mapping | Synthetic | Usable | Why |
|---|---|---|---:|---:|---:|---|---|---|---|---|
| `kaggle_yasmeenahmadabadwala_hindi-spam-dataset` | https://www.kaggle.com/datasets/yasmeenahmadabadwala/hindi-spam-dataset | MIT | 6,500 | 0 | 6,026 | `0`=3650, `1`=2850 | `0`→ham, `1`→scam | Likely yes (not stated; templated bodies, `example.net` URLs) | Yes | 3,634 genuine Devanagari rows and 2,392 fraud rows (refund, KYC, delivery-fee, prize); clean phrasing and a balanced fraud class. |
| `kaggle_onkarbhanarkar_hindi-spam-dataset` | https://www.kaggle.com/datasets/onkarbhanarkar/hindi-spam-dataset | Unknown | 5,572 | 0 | 5,348 | `ham`=4825, `spam`=747 | `ham`→ham, `spam`→unwanted | Yes (machine-translated UCI SMS; UK dogging/ringtone text in Hindi) | Yes | Large Devanagari ham block; spam is promotional, so it adds unwanted but no scam. |
| `kaggle_adithyanits_2000spam-ham-labeleddataset-hindi` | https://www.kaggle.com/datasets/adithyanits/2000spam-ham-labeleddataset-hindi | Unknown | 2,000 | 0 | 1,896 | `ham`=1237, `spam`=763 | `ham`→ham, `spam`→unwanted | Yes (translated UCI-style offers; FA Cup/5G promos) | Yes (with label noise) | Useful ham; spam is mostly promotional. One labelled-spam Diwali greeting shows noise, so keep the class as unwanted, not scam. |
| `kaggle_debapampal2002_sms-dataset1` | https://www.kaggle.com/datasets/debapampal2002/sms-dataset1 | MIT | 22,287 | 0 | 5,305 | `ham`=19299, `spam`=2988 | `ham`→ham, `spam`→unwanted | Yes (English/German/French SMS machine-translated into Hindi) | Yes | 4,625 Devanagari ham and 680 spam; translation is rough but the ham/spam split is usable. |
| `kaggle_nikhil7g_multilingual-cross-market-financial-fraud-dataset` | https://www.kaggle.com/datasets/nikhil7g/multilingual-cross-market-financial-fraud-dataset | CC BY-SA 4.0 | 22,500 | 0 | 4,560 | `0`=10809, `1`=11691 | `0`→ham, `1`→scam | Yes (says generated from public sources; templated bank/UPI alerts) | Yes | The best scam source: 2,305 Devanagari fraud rows (prize, work-from-home, KYC/AnyDesk, refund) and 2,255 genuine transaction alerts. No Tamil. |
| `kaggle_muthumarii_tamil-nlp-sentiment-and-fake-news-dataset` | https://www.kaggle.com/datasets/muthumarii/tamil-nlp-sentiment-and-fake-news-dataset | CC BY-SA 4.0 | 1,006 | 1,006 | 0 | `fake`=215, `negative`=285, `positive`=301, `real`=205 | `fake`→unwanted, `positive`/`negative`/`real`→ham | Unknown (no statement; short curated sentences) | Yes (limited) | The only Tamil-script dataset found. It is news/sentiment text, not SMS: 791 ham rows and 215 misinformation/chain-forward rows, and **zero** scam rows. |
| `kaggle_muhammadhumyun_pakistan-sms-classification-dataset` | https://www.kaggle.com/datasets/muhammadhumyun/pakistan-sms-classification-dataset | CC0: Public Domain | 4,895 | 0 | 0 | `Normal`=2504, `Promotional`=1280, `fraud`=1111 | n/a | Unknown | No | Valuable labels, but all text is English/Roman Urdu, not Devanagari. |
| `hf_AnudeepRao_Hinglish-Everyday-Conversations-1M-Devanagari` | https://huggingface.co/datasets/AnudeepRao/Hinglish-Everyday-Conversations-1M-Devanagari | Unknown | 1,001,323 | 0 | 642,788 | unlabeled=1001323 | all→ham | Yes (Hinglish→Devanagari translation pairs) | Conditional | Huge Devanagari conversation pool (642,788 rows) usable as ham, but the card states no licence, so the plan's licence rule blocks it unless the manager approves. |
| `hf_TokenBender_Tamil_chat_dataset` | https://huggingface.co/datasets/TokenBender/Tamil_chat_dataset | Apache-2.0 | 1,388 | 0 | 0 | unlabeled=1388 | n/a | Unknown | No | Despite the name, these are English LLM conversations; 0 Tamil-script rows. |
| `hf_karanverma19_tri-fraud-alerts-india` | https://huggingface.co/datasets/karanverma19/tri-fraud-alerts-india | MIT | 150 | 0 | 4 | `safe`=87, `scam`=63 | `safe`→ham, `scam`→scam | Unknown | No | Only 4 Devanagari rows and all scam rows are Latin; it is the v1 of the trilingual set already in `source_map.yaml` (v2). |

## Label evidence (one sentence each)

- `yasmeen`: label 0 rows are meetings, bills and delivery confirmations while label 1 rows ask for a refund, KYC update, delivery fee, investment or credit-card login, so 0 = ham and 1 = scam.
- `onkarbhanarkar`: label `spam` rows are ringtone, prize and dating adverts and label `ham` rows are ordinary conversation, so `spam` = unwanted, not scam.
- `adithyanits`: label `spam` rows are free-token, 5G and FA-Cup promotional offers while `ham` rows are train tickets and personal messages, so `spam` = unwanted (with at least one mislabelled Diwali greeting).
- `debapampal2002`: label `spam` rows are marketing, ringtone and account-verification messages and `ham` rows are personal conversation, so `spam` = unwanted; a few read like phishing but the corpus is mostly promotional.
- `nikhil7g`: label 1 rows are prize, work-from-home, KYC/AnyDesk and UPI refund fraud while label 0 rows are genuine bank debit and ITR alerts, so 0 = ham and 1 = scam.
- `muthumarii`: label `fake` rows are health misinformation, chain forwards and "share for luck" messages while the other labels are sentiment/news, so `fake` = unwanted and the rest = ham, with no fraud class.
- `muhammadhumyun`: labels Normal/Promotional/fraud are clear, but every sample is Latin/Roman Urdu.
- `AnudeepRao`: every row is an unlabelled everyday Devanagari conversation (food, money, family), so it can only be ham.
- `TokenBender`: every conversation is an English instruction-following exchange, so it has no usable Tamil-script rows.
- `karanverma19/tri-fraud-alerts-india`: `safe` rows are fraud advisories and `scam` rows are visa/job fraud in Latin script, so only 4 Devanagari rows could map to ham.

## Skipped list

Already in `data/source_map.yaml` (compared by Kaggle slug / HF repo id in `path`):

| Source | Reason |
|---|---|
| `roberto2057/hindi-sms` | `sms_roberto2057_hindi_sms` already mapped. |
| `siddharthrane07/scamshield-multilingual-smishing-social-engn` | Already mapped (train/val/test entries). |
| `kritikgianta/multilanguage-sms-classification-dataset` | Already mapped. |
| `spamdetectorssms/combined-multilingual-spam-dataset-25k` | Already mapped. |
| `rajnathpatel/multilingual-spam-data` | Already mapped. |
| `karanverma/punjab-fraud-intent-benchmark-trilingual` (Kaggle) and `karanverma19/Indian_Multilingual_Scam_Message_Dataset` (HF) | Already mapped. |
| `Ridham115/indian-scam-sms-synthetic-audited` | Already mapped. |
| `dbarbedillo/SMS_Spam_Multilingual_Collection_Dataset` | Already mapped. |

Held-out test sources (never for training):

| Source | Reason |
|---|---|
| `anmolshrivastav/scam-ham-india` | Held-out test source. |
| `anmolshrivastav/scam_ham_india_14_languages` | Held-out test source (also the only public source with Tamil-script scam rows). |
| `carnageiron/scam-ham-india` | Held-out test source. |
| `sujithhhhhhhh/scam-ham-india` | Byte-identical copy/mirror of the held-out `carnageiron`/`anmolshrivastav` file (same 260,040-byte `scam_hum_india.csv`). |
| `ganesh9353/Indian_Multilingual_Scam_Message_Dataset` | Copy of `karanverma19/Indian_Multilingual_Scam_Message_Dataset`, already mapped. |
| `bhavya2910/indian-scam-sms-synthetic-audited` | Copy of `Ridham115/indian-scam-sms-synthetic-audited`, already mapped. |
| `MaloRaj/india-spam-sms`, `sahil456838/india-spam-sms` | Copies of `CloveAI/india-spam-sms`, already mapped. |

Screened out without download (not SMS, wrong script, too large, or unavailable):

| Source | Reason |
|---|---|
| `kumarperiya/comprehensive-indian-online-fraud-dataset` | Downloaded but rejected: transaction-level fraud table (amount, card type, location); no message text. |
| `vnovaai/INDIA_FRAUD_DETECTION_JSONL_V1` | Downloaded but rejected: 99 synthetic English fraud scenarios/advice, no Indic-script message rows. |
| `shivamsiddhant/adaption-devnagri-script-language-dataset-for-fina` | 335 MB, above the 300 MB limit; listing shows question-answer finance pairs, not SMS. |
| `shivamsiddhant/adaption-financial-fraud-topics-and-terms-in-devan` | Devanagari fraud question-answer prompts, not SMS messages. |
| `shivamsiddhant/adaption-fraud-and-cyber-safety` | 14-language fraud/cyber-safety fine-tuning Q&A pairs, not SMS; prompts describe scams instead of being scam messages. |
| `gouravkimarif/spam-ham-500000-rows-38-3-mb` | File is `email_dataset_500k.csv` (email, not SMS). |
| `animeshdinda12/indian-scam-detection` | Kaggle API returned `403 Client Error: Forbidden` (restricted or deleted). |
| Tamil/Hindi corpora such as `sudalairajkumar/tamil-nlp`, `praveengovi/tamil-language-corpus-for-nlp`, `Achitha/tamildata`, `abhinand/tamil-alpaca` | Tamil-script text but no ham/unwanted/scam labels (or > 300 MB). |

## Totals by proposed class (usable rows only)

"Usable" = candidates marked Yes (not Conditional/No). Only the Devanagari and Tamil-script
rows are counted, using the per-label script cross-tab from the script.

| Script | ham | unwanted | scam | Total |
|---|---:|---:|---:|---:|
| Devanagari | 16,404 | 2,034 | 4,697 | 23,135 |
| Tamil | 791 | 215 | 0 | 1,006 |

Conditional additions if the manager accepts an unstated licence: `hf_AnudeepRao` adds
642,788 Devanagari ham rows. Nothing adds Tamil scam rows.

Per-source contributions (Devanagari ham / unwanted / scam):

| Source | ham | unwanted | scam |
|---|---:|---:|---:|
| yasmeen | 3,634 | 0 | 2,392 |
| onkarbhanarkar | 4,659 | 689 | 0 |
| adithyanits | 1,231 | 665 | 0 |
| debapampal2002 | 4,625 | 680 | 0 |
| nikhil7g | 2,255 | 0 | 2,305 |
| muthumarii (Tamil) | 791 | 215 | 0 |

## Samples (seed 20261110, truncated to 160 characters)

### `kaggle_yasmeenahmadabadwala_hindi-spam-dataset`

- **0 / Devanagari**: नमस्ते सुनीता, इस सप्ताह के अंत तक हमें डेटा एनालिसिस का काम पूरा करना है। कृपया अपनी टीम के साथ मिलकर सभी टास्क समय पर फिनिश करें। सादर, ग्लोबल सिस्टम्स टीम
- **0 / Devanagari**: प्रिय निधि, हमें आपकी शिकायत प्राप्त हुई थी और हमारी technical team ने उसका समाधान कर दिया है। यदि आपको अभी भी कोई issue है, तो आप इस email का reply कर सकते हैं
- **0 / Devanagari**: प्रिय साथियों, आज हुई मीटिंग के मुख्य बिंदुओं को अटैचमेंट में शेयर किया गया है। अगले चरण के लिए सभी लोग अपने टास्क नोट कर लें। धन्यवाद, सिद्धार्थ (मैनेजर)
- **0 / Devanagari**: प्रिय आकाश, हमें आपकी शिकायत प्राप्त हुई थी और हमारी technical team ने उसका समाधान कर दिया है। यदि आपको अभी भी कोई issue है, तो आप इस email का reply कर सकते हैं
- **0 / Devanagari**: प्रिय कविता, आपका हेल्पडेस्क टिकट हमारी तकनीकी टीम द्वारा जांचा जा रहा है। जल्द ही आपको अपडेट दिया जाएगा। सपोर्ट डेस्क सपोर्ट
- **1 / Devanagari**: प्रिय यूजर, तकनीकी गलती के कारण ₹110,118 आपके बैंक खाते में गलती से जमा हो गए हैं। कृपया तुरंत इन पैसों को हमारे वेरीफाइड खाते में वापस भेजें: https://transfer-
- **1 / Devanagari**: नमस्ते अमित, गलत address होने की वजह से आपका delivery box रोक लिया गया है। कूरियर दोबारा भेजने के लिए यहाँ click करें: https://promo-claim.example.net/110b0b82d
- **1 / Devanagari**: नमस्ते पूजा, क्या आप अपने पैसों को तेजी से बढ़ाना चाहते हैं? हमारा नया पोर्टफोलियो प्लान आपके लिए बेहतरीन मौका लेकर आया है। क्लिक करें: https://stock-tips.examp
- **1 / Devanagari**: चेतावनी! हमने आपके क्रेडिट कार्ड रिवार्ड्स पोर्टल पर किसी अन्य स्थान से लॉगिन का प्रयास देखा है। अपने पासवर्ड को तुरंत रीसेट करने के लिए यहाँ क्लिक करें: https:
- **1 / Devanagari**: प्रिय मित्र, मैं एक गुप्त बैंक अधिकारी हूँ। आपके पूर्वज की एक लावारिस संपत्ति और भारी खजाना हमारे पास है। अपने बैंक खाते में ₹2,761,604 ट्रांसफर करवाने के लिए अ

### `kaggle_onkarbhanarkar_hindi-spam-dataset`

- **ham / Devanagari**: मेरे पर्यवेक्षक ने मुझे 4 एक लोर पाया, मैं उसके छात्रों को thk करता हूं। मैं अभी तक उससे पूछता हूं। बताओ यू पिछाड़ी मैं उससे पूछता हूँ।
- **ham / Devanagari**: के, क्या यह आज रात हो सकता है?
- **ham / Devanagari**: नहीं, मैं इसे पूरे सप्ताहांत में आज़मा रहा था; v
- **ham / Devanagari**: केवल शनिवार और रविवार की छुट्टी इतनी मुश्किल :)
- **ham / Devanagari**: हे बेब, मेरे दोस्त को रद्द करना था, अभी भी एक यात्रा के लिए?
- **spam / Devanagari**: यूके की हॉर्नीस्ट डॉगिंग सेवा में शामिल हों और यू सेक्स 2nite कर सकते हैं! बस साइन अप करें और निर्देशों का पालन करें। अब 69888 के लिए txt प्रविष्टि! Nyt.ec2a.3l
- **spam / Devanagari**: नवीनतम andharry पॉटर और द ऑर्डर ऑफ द फीनिक्स (बुक 5) उत्तर दें हैरी को जीतें, 5 सवालों के जवाब दें - पाठकों के बीच पहला होने का मौका!
- **spam / Devanagari**: यू एक गुप्त प्रशंसक है, जो 2 देख रहा है कि वे यू-फिंड के साथ संपर्क करते हैं, जो वे आर*प्रकट करते हैं कि कौन सोचता है कि 09065171142-stopsms-087187277870150pm प
- **spam / Devanagari**: 2nite को बिछाना चाहते हैं? उर मोबाइल को सीधे भेजे गए असली डॉगिंग स्थानों को चाहते हैं? यूके के सबसे बड़े डॉगिंग नेटवर्क में शामिल हों। TXT पार्क अब 69696 तक! Ny
- **spam / Devanagari**: अंतरिक्ष आक्रमणकारियों 4 एक मौका 2 जीत मूल आर्केड गेम कंसोल खरीदें। गेम आर्केड के लिए 0 दबाएं (STD WAP चार्ज) O2.co.uk/games 4 शर्तें + सेटिंग्स देखें। कोई खरीद

### `kaggle_adithyanits_2000spam-ham-labeleddataset-hindi`

- **ham / Devanagari**: मिनिट्रा से लोगे एम साइज में लोकल ब्रांड हो तो एल
- **ham / Devanagari**: आपकी यात्रा की पुष्टि हो चुकी है। प्रिय ग्राहक, आपकी ट्रेन टिकट बुकिंग सफलतापूर्वक हो गई है। यात्रा की तारीख और समय की पुष्टि इस ईमेल में दी गई है। धन्यवाद, यात
- **ham / Devanagari**: आपका मैसेज मिला, धन्यवाद!
- **ham / Devanagari**: आपके फोक्स के अनुसार 'मेले मेले (ओरु मिन्नामिनुंगिन्ते नुरुंगु वेट्टम)' के लिए सभी कॉल्स के लिए आपके कॉल्स ट्यून के रूप में सेट किया गया है। अपने दोस्तों के साथ
- **ham / Devanagari**: आपका दिन शुभ हो
- **spam / Devanagari**: प्रिय xxxxxxxxxxxx, आपको और आपके परिवार को दिवाली की हार्दिक शुभकामनाएँ! हवा मिठाई की खुशबू से भर जाती है, घरों को जगमगाती रोशनी से सजाया जाता है और दिल खुशी से
- **spam / Devanagari**: फ्री टोकन ऑफर! एक सीमित समय के लिए, फ्री टोकन पाएं! यहाँ क्लिक करें: [http://claim-free-token-now.com]।
- **spam / Devanagari**: 21 मई 2005 को एफए कप फाइनल जीतने के लिए 2 में मुफ्त प्रवेश। प्रवेश प्रश्न प्राप्त करने के लिए 87121 पर पाठ FA (std txt दर)T&C लागू करें 08452810075over18's
- **spam / Devanagari**: हमने देखा है कि किसी अज्ञात कारण से आपने एथनिक प्लस पर निम्नलिखित वस्तुओं के साथ अपना कार्ट छोड़ दिया था: CHECKOUT
- **spam / Devanagari**: आप असीमित 5G डेटा के लाभों से चूक रहे हैं!! आपका मौजूदा प्लान आपके 5G फोन पर सही मायने में असीमित 5G डेटा नहीं देता। बस Rs.151 ऐड-ऑन से रिचार्ज करें और अपने प्ल

### `kaggle_debapampal2002_sms-dataset1`

- **ham / Devanagari**: हाँ, लेकिन यह अब मुझे समस्या नहीं दे रहा है तो मैं इसे छोड़ देंगे...
- **ham / Devanagari**: इसकी जाँच आईQ का एक भाग
- **ham / Devanagari**: क्या तुम बच्चे को खुश कर रहे हो? क्या तुम ठीक हो? मुझे आशा है कि वह नौकरी ले? मैं तुम्हें एक चुंबन भेजने के लिए समुद्र के पार से आप मुस्कान बनाने के लिए... *ks
- **ham / Devanagari**: पहले मेरे सवाल का जवाब दीजिए ।
- **ham / Devanagari**: आप के लिए सूचना के लिए, मैं SEA सभी स्वास के साथ जादू किया जाता है. वह नहीं है. जब आप मुझे लगता था कि मैं तुम्हें छोड़ दिया था, आप मुसीबत के बीच बिस्तर पर बैठे
- **spam / Devanagari**: IMPCANTES MESM. यह एक अंतिम संपर्क प्रयास है. आप महत्वपूर्ण संदेश हमारे ग्राहक दावा कर रहे हैं डेप्टा. खत्म 13/4.
- **spam / Devanagari**: स्टेटAVAT! आपके 2003 खाता स्टेटमेंट के लिए 800 गैर-द्ड एस.आई.एम. का कहना है. का नाम 0. 0855585 पहचानकर्ता कोड: 4x26 समाप्त होता है 13/10/04/044/0
- **spam / Devanagari**: वेव के लिए मासिक पासवर्ड. भीड़. कॉम है 391784. अपना परियोजना फोन पीसी नहीं इस्तेमाल करें.
- **spam / Devanagari**: मुद्रा आई 946 तक जीता है.....
- **spam / Devanagari**: <20600 से जारी किया गया है - यह आपका मेल चेतावनी है. आपके पास 4 संदेश है. आपके पास 4 मिलान है. कृपया अपने संदेश को पुनः प्राप्त करने के लिए वापस बुलाओ.

### `kaggle_nikhil7g_multilingual-cross-market-financial-fraud-dataset`

- **0 / Devanagari**: आपके Union Bank खाते XXXX9022 से ₹45,000 का भुगतान Myntra को सफलतापूर्वक संपन्न हुआ। कुल शेष: ₹291,625। सहायता के लिए 1930 डायल करें।
- **0 / Devanagari**: आयकर विभाग: आपके पैन कार्ड से संबंधित निर्धारण वर्ष 2026-27 की आईटीआर सफलतापूर्वक प्रोसेस हो गई है। पावती संख्या #572972762। स्थिति eportal पर जांचें।
- **0 / Devanagari**: आपके SBI खाते XXXX3314 से ₹1,200 का भुगतान BigBasket को सफलतापूर्वक संपन्न हुआ। कुल शेष: ₹306,209। सहायता के लिए 1930 डायल करें।
- **0 / Devanagari**: आपके HDFC Bank खाते XXXX1690 से ₹15,000 का भुगतान Amazon को सफलतापूर्वक संपन्न हुआ। कुल शेष: ₹334,054। सहायता के लिए 1930 डायल करें।
- **0 / Devanagari**: आपके Axis Bank खाते XXXX3480 से ₹1,200 का भुगतान Blinkit को सफलतापूर्वक संपन्न हुआ। कुल शेष: ₹348,742। सहायता के लिए 1930 डायल करें।
- **1 / Devanagari**: जियो 10वीं वर्षगांठ धमाका: आपने जीती है नई महिंद्रा थार गाड़ी। गाड़ी की डिलीवरी और टैक्स क्लीयरेंस हेतु ₹3,500 तुरंत ट्रांसफर करें: 7464258627.
- **1 / Devanagari**: वर्क फ्रॉम होम टास्क: साधारण AI डेटा रिव्यू कार्य करके बिना किसी निवेश के रोज ₹28,000 तुरंत UPI पर पाएं। व्हाट्सएप पर संपर्क करें: http://secure-kyc-update.in/0
- **1 / Devanagari**: घर बैठे कमाई का मौका! यूट्यूब वीडियो लाइक करके और चैनल सब्सक्राइब करके रोजाना 1 घंटा काम करके ₹7,500 प्राप्त करें। फ्री रजिस्ट्रेशन के लिए लिंक खोलें: http://t.
- **1 / Devanagari**: कोटक महिंद्रा बैंक तकनीकी सहायता: आपके खाते में संदिग्ध डिवाइस लॉगिन देखा गया है। सुरक्षा जांच हेतु तुरंत प्ले स्टोर से AnyDesk डाउनलोड करें और 9-अंकीय कोड हमार
- **1 / Devanagari**: बधाई हो! आपके खाते में ₹3,500 का पेंडिंग रिफंड ट्रांसफर होना है। रिवॉर्ड समाप्त होने से पहले क्लेम करने हेतु कलेक्ट रिक्वेस्ट को तुरंत अप्रूव करें: http://t.me/

### `kaggle_muthumarii_tamil-nlp-sentiment-and-fake-news-dataset`

- **fake / Tamil**: ஆர்கோன் கதிர் தெரபி மட்டுமே புற்றுநோயை குணப்படுத்தும்.
- **fake / Tamil**: தினமும் ஒரு கிளாஸ் கோமூத்ரம் குடித்தால் ஆரோக்கியமாக இருக்கலாம்.
- **fake / Tamil**: இஞ்சி பூண்டு கலவை குடிப்பவர்களுக்கு கொரோனா வராது என்று ஆய்வு தெரிவிக்கிறது.
- **fake / Tamil**: குறிப்பிட்ட நடிகர் ஒரு அரசியல் கட்சியில் சேர்ந்தார் என்று வரும் செய்தி தவறானது.
- **fake / Tamil**: சிப்பி உடையின் சாறு புற்றுநோயை 100% குணப்படுத்தும்.
- **negative / Tamil**: வாழ்க்கையில் நம்பிக்கை இழந்துவிட்டேன்.
- **negative / Tamil**: என் வாழ்க்கை வழிதடுமாறுகிறது.
- **negative / Tamil**: என்னுடைய கஷ்டங்கள் தீரும் நாள் வருமா?
- **negative / Tamil**: என்னை நம்பி ஏமாறாதீர்கள் என்று சொன்னவரே ஏமாற்றிவிட்டார்.
- **negative / Tamil**: என் வாழ்க்கையில் மகிழ்ச்சி குறைந்துவிட்டது.
- **positive / Tamil**: கோயில் பிரசாதம் சாப்பிட்டால் மனசு நிம்மதி பெறும்.
- **positive / Tamil**: இன்று ஒரு முதியவருக்கு உதவி செய்தேன், மனம் நிறைந்தது.
- **positive / Tamil**: என் ஆசிரியர் என்னை நல்ல வழியில் வழிநடத்தினார்.
- **positive / Tamil**: ஆராய்ச்சி செய்வது புதிய உலகை திறந்துவிடுகிறது.
- **positive / Tamil**: சவால் எடுத்தேன், வென்றேன், இது என் வாழ்க்கையின் திருப்புமுனை.
- **real / Tamil**: தமிழ்நாட்டு பட்ஜெட்டில் உள்கட்டமைப்புக்கு பெரும் தொகை ஒதுக்கப்பட்டது.
- **real / Tamil**: சட்டமன்ற குழு பள்ளி கட்டுமான மோசடியை விசாரிக்கிறது.
- **real / Tamil**: சட்டப்பிரிவின்படி தண்டனை வழங்கப்பட்டது.
- **real / Tamil**: தமிழ்நாட்டில் உழவர்களுக்கு சிறப்பு பயிற்சி நிலையம் தொடங்கியது.
- **real / Tamil**: விவசாயிகளுக்கு உதவும் புதிய தொழில்நுட்பம் கண்டுபிடிக்கப்பட்டது.

### `kaggle_muhammadhumyun_pakistan-sms-classification-dataset`

No Tamil-script or Devanagari rows. Every sample is Latin/Roman Urdu, so no target-script
samples are printed.

### `hf_AnudeepRao_Hinglish-Everyday-Conversations-1M-Devanagari`

- **unlabeled / Devanagari**: मैं सोचती हूँ, अगर हम एक बच्चा adopt karein, toh ज़िन्दगी का मकसद बदल जायेगा।
- **unlabeled / Devanagari**: मैं सोच रहा हूँ कि mutual funds में invest करना शुरू करूँ, क्या खयाल है?
- **unlabeled / Devanagari**: मैं तोह सोच रही थी कि एक DIY project शुरू करूँ, क्या तुम मेरी मदद करोगी?
- **unlabeled / Devanagari**: यार, वो चाट वाला, उसकी दही पूरी तो आज भी याद है, अब तो कुछ नहीं है।
- **unlabeled / Devanagari**: घर खरीदने की सोच कभी नहीं छोडी, लेकिन travel का मज़ा भी तो है।

### `hf_TokenBender_Tamil_chat_dataset`

No Tamil-script rows (0 of 1,388); the conversations are English instruction-following text,
so no target-script samples are printed.

### `hf_karanverma19_tri-fraud-alerts-india`

- **safe / Devanagari**: सही सलाहकार कभी भी risk khatam hone ka दावा नहीं करेगा, केवल प्रक्रिया समझाएगा।
- **safe / Devanagari**: जन सूचना: विदेश नौकरी के नाम पर chat में तुरंत token payment माँगने वाले ads से सावधान रहें।
- **safe / Devanagari**: कोई भी एजेंट Canada work permit पक्का नहीं कर सकता। केवल आधिकारिक प्रक्रिया पर भरोसा करें।
- **safe / Devanagari**: पासपोर्ट कॉपी या पैसे केवल इसलिए न भेजें क्योंकि कोई slot block होने का दावा कर रहा है।

(Covers 5 samples per label per script; the 4th row is the last Devanagari row, so only 4 are
printed. No scam/Devanagari rows exist.)

## Failures and notes

- `animeshdinda12/indian-scam-detection`: `403 Client Error: Forbidden` from the Kaggle files API.
- Kaggle CLI warns that version 2.2.4 is outdated; downloads still worked.
- The Kaggle API `datasets/view` endpoint returned 404 without credentials and `licenseName`
  with the stored CLI credentials, so licences were read from that authenticated endpoint.
- No dataset was larger than 300 MB except `shivamsiddhant/adaption-devnagri-script-language-dataset-for-fina`
  (335 MB), which was not downloaded.
- `muthumarii`: the script measured `tamil_data.csv`, which has 1,006 rows; the README's
  train/validation/test split counts total 820, so `tamil_data.csv` is a larger union than the
  documented splits.
- No Tamil-script scam/fraud SMS dataset exists in the public listings outside the held-out
  `anmolshrivastav` / `carnageiron` test set. Training rows for Tamil fraud must come from
  translation (Track B) or from a new source the manager finds.
