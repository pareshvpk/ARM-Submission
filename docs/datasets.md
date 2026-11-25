# PS3 Unified Threat Intelligence Datasets Catalogue

Bharat AI-SoC Challenge 2026-27, Problem Statement 3: On-Device Threat, Phishing and Scam Detection.

> **Note:** All counts and row statistics below are marked **LIMIT RUN** (`--limit 3000` rows per file/entry). The full-scale production run processes all available records (~3.5 GB raw).

> **Licence note (D1-13):** This catalogue lists research sources under their original terms, including CC-BY-NC-SA-4.0 and GPL-2.0 sources (rows marked with those licences below). NC and GPL-sharealike terms restrict commercial use and redistribution of derived weights, so those sources must be excluded from any shipped training set (or covered by a recorded legal review and attribution) before claiming MIT/Apache-2.0 for the shipped `.pte` models. The shipped model's actual training sources and derivation are recorded in the engineering report; the catalogue alone does not prove licence compliance.

---

## 1. Unified SMS Corpus (`data/processed/sms/`)

| Source ID | Path | Rows Kept (LIMIT RUN) | Label Counts (Ham / Scam / Unwanted) | Lang | Channel | Synthetic | Licence |
|---|---|---:|---|---|---|---|---|
| `sms_abdelrahmanmahmoud22_english_sms` | `sms/abdelrahmanmahmoud22__phishing-credit-card-smss/raw_intelligent_english_sms_dataset.csv` | 3,000 | Ham: 1,550, Scam: 1,450 | en | sms | False | CC0-1.0 |
| `sms_aditsawhney_indian_jobs` | `sms/aditsawhney__indian-job-fraud-dataset/synthetic_indian_jobs.csv` | 747 | Ham: 447, Scam: 300 | en | job_post | True | CC0-1.0 |
| `sms_ahmadtijjani_urgency_phishing` | `sms/ahmadtijjani__phishing-urgency-authority-persuasion/phishing_dataset_with_category.csv` | 1,000 | Scam: 1,000 | en | sms | False | MIT |
| `sms_ameenhasan_fake_fraud` | `sms/ameenhasan__fake-fraud-message-detection-dataset/SMS fraud Dataset.csv` | 3,000 | Ham: 2,591, Scam: 409 | en | sms | False | Other |
| `sms_atherionsystems_indian_scam_30k` | `sms/atherionsystems__indian-scam-sms-30k/dataset_30k_pure.jsonl` | 3,000 | Ham: 883, Scam: 2,117 | en | sms | True | CC0-1.0 |
| `sms_bwandowando_philippine_spam` | `sms/bwandowando__philippine-spam-sms-messages/SPAM_SMS.csv` | 1,023 | Unwanted: 1,023 | en | sms | False | CC-BY-NC-SA-4.0 |
| `sms_dharshiyanacc_spam_ham_phishing` | `sms/dharshiyanacc__spam-ham-and-phishing-message-dataset-for-nlp/final_dataset.csv` | 3,000 | Ham: 1,076, Scam: 1,428, Unwanted: 496 | en | sms | False | MIT |
| `sms_fadlifatih_sms_phishing` | `sms/fadlifatih__sms-phishing-dataset/Dataset_5971.csv` | 3,000 | Ham: 2,441, Scam: 319, Unwanted: 240 | en | sms | False | CC0-1.0 |
| `sms_galactus007_smssmishcollection` | `sms/galactus007__sms-smishing-collection-data-set/smssmishcollection/SMSSmishCollection.txt` | 3,000 | Ham: 2,591, Scam: 409 | en | sms | False | DbCL-1.0 |
| `sms_gokhansoyturk_combined_sms` | `sms/gokhansoyturk__smishing-sms-dataset/combined_sms.csv` | 3,000 | Ham: 3,000 | en | sms | False | MIT |
| `sms_junioralive_india_spam` | `sms/junioralive__india-spam-sms-classification/spam_ham_india.csv` | 2,266 | Ham: 1,521, Unwanted: 745 | en | sms | False | MIT |
| `sms_karanverma_punjab_fraud` | `sms/karanverma__punjab-fraud-intent-benchmark-trilingual/trilingual_fraud_consumer_protection_v2.csv` | 159 | Ham: 90, Scam: 69 | mixed | sms | False | MIT |
| `sms_kritikgianta_merged_sms` | `sms/kritikgianta__multilanguage-sms-classification-dataset/FINAL_MERGED_SMS_DATASET.csv` | 3,000 | Ham: 1,467, Unwanted: 1,533 | mixed | sms | False | Unknown |
| `sms_mexwell_telegram_spam_ham` | `sms/mexwell__telegram-spam-or-ham/dataset.csv` | 3,000 | Ham: 1,636, Unwanted: 1,364 | en | telegram | False | CC0-1.0 |
| `sms_msubhansiddiqui_financial_scam` | `sms/msubhansiddiqui__financial-scam-and-deceptive-text-meta-dataset/master_cleaned_dataset_with_synthetic.csv` | 3,000 | Ham: 1,520, Scam: 1,480 | en | sms | True | CC-BY-NC-SA-4.0 |
| `sms_rajnathpatel_multilingual_spam` | `sms/rajnathpatel__multilingual-spam-data/data-en-hi-de-fr.csv` | 3,000 | Ham: 2,591, Unwanted: 409 | en | sms | False | GPL-2.0 |
| `sms_rithikkumar802_adaption_fraud` | `sms/rithikkumar802__adaption-sms-fraud-classification/data.jsonl` | 578 | Ham: 449, Scam: 129 | en | sms | False | CC0-1.0 |
| `sms_roberto2057_hindi_sms` | `sms/roberto2057__hindi-sms/hindi_sms_spam_ham_15000.csv` | 3,000 | Ham: 1,502, Unwanted: 1,498 | hi | sms | False | Unknown |
| `sms_siddharthrane07_scamshield_test` | `sms/siddharthrane07__scamshield-multilingual-smishing-social-engn/test.jsonl` | 3,000 | Ham: 3,000 | language | sms | False | MIT |
| `sms_siddharthrane07_scamshield_train` | `sms/siddharthrane07__scamshield-multilingual-smishing-social-engn/train.jsonl` | 3,000 | Ham: 1,923, Scam: 1,077 | language | sms | False | MIT |
| `sms_siddharthrane07_scamshield_val` | `sms/siddharthrane07__scamshield-multilingual-smishing-social-engn/val.jsonl` | 3,000 | Ham: 3,000 | language | sms | False | MIT |
| `sms_sngmyd_india_cyber_scam` | `sms/sngmyd__india-cyber-scam-hinglish-dataset/India_Cyber_Scam_Hinglish_Dataset.csv` | 3,000 | Ham: 1,506, Scam: 1,494 | hinglish | call_transcript | False | Apache-2.0 |
| `sms_spamdetectorssms_combined_multilingual` | `sms/spamdetectorssms__combined-multilingual-spam-dataset-25k/Combined_Multilingual_Spam_Dataset_25k.csv` | 3,000 | Ham: 1,640, Unwanted: 1,360 | language | sms | False | ODbL-1.0 |
| `sms_tapakah68_spam_texts` | `sms/tapakah68__spam-text-messages-dataset/spam_texts.csv` | 25 | Unwanted: 25 | en | sms | False | Unknown |
| `sms_teeconnie_english_nonscam` | `sms/teeconnie__scam-and-non-scam-call-conversation-dataset/English_NonScam.txt` | 400 | Ham: 400 | en | call_transcript | False | CC BY-NC-ND 4.0 |
| `sms_teeconnie_english_scam` | `sms/teeconnie__scam-and-non-scam-call-conversation-dataset/English_Scam.txt` | 400 | Scam: 400 | en | call_transcript | False | CC BY-NC-ND 4.0 |
| `sms_uciml_spam` | `sms/uciml__sms-spam-collection-dataset/spam.csv` | 3,000 | Ham: 2,591, Unwanted: 409 | en | sms | False | CC0-1.0 |
| `sms_vinit119_sms_scam` | `sms/vinit119__sms-scam-detection-dataset-merged/sms_scam_detection_dataset_merged_with_lang.csv` | 3,000 | Ham: 2,444, Unwanted: 556 | lang | sms | False | Other |
| `sms_wa1618i_whatsapp_chat_1` | `sms/wa1618i__whatsapp-scam-dataset/WhatsApp Chat with chat_1.txt` | 335 | Scam: 335 | en | whatsapp | False | CC0-1.0 |
| `sms_wa1618i_whatsapp_chat_2` | `sms/wa1618i__whatsapp-scam-dataset/WhatsApp Chat with chat_2.txt` | 3,000 | Scam: 3,000 | en | whatsapp | False | CC0-1.0 |
| `sms_wa1618i_whatsapp_violine_1` | `sms/wa1618i__whatsapp-scam-dataset/WhatsApp Chat with Violine (1).txt` | 3,000 | Scam: 3,000 | en | whatsapp | False | CC0-1.0 |
| `sms_wa1618i_whatsapp_zevanca_1` | `sms/wa1618i__whatsapp-scam-dataset/WhatsApp Chat with Zevanca (1).txt` | 192 | Scam: 192 | en | whatsapp | False | CC0-1.0 |
| `sms_yatinaggarwal033_whatsapp_scam` | `sms/yatinaggarwal033__whatsapp-scam-dataset/whatsapp_scam_dataset.csv` | 3,000 | Scam: 3,000 | en | whatsapp | False | Apache-2.0 |
| `sms_mendeley_mishra_soni` | `ext/mendeley/mishra_soni_smishing/Dataset_5971.zip` | 3,000 | Ham: 2,441, Scam: 319, Unwanted: 240 | en | sms | False | CC-BY-4.0 |
| `sms_hf_alusci_sms_otp` | `ext/hf/alusci__sms-otp-spam-dataset/SMS_OTP_10000_samples.csv` | 3,000 | Ham: 2,411, Unwanted: 589 | en | sms | False | Apache-2.0 |
| `sms_hf_bolewara_hinglish_scam` | `ext/hf/bolewara__hinglish-scam-text-dataset/data.json` | 3,000 | Ham: 2,418, Scam: 582 | hinglish | sms | False | Apache-2.0 |
| `sms_hf_cloveai_india_spam` | `ext/hf/CloveAI__india-spam-sms/data/train-00000-of-00001.parquet` | 3,000 | Ham: 2,079, Unwanted: 921 | en | sms | False | Apache-2.0 |
| `sms_hf_dbarbedillo_sms_spam_multilingual` | `ext/hf/dbarbedillo__SMS_Spam_Multilingual_Collection_Dataset/data-augmented.csv` | 3,000 | Ham: 2,591, Unwanted: 409 | en | sms | False | CC-BY-SA-4.0 |
| `sms_hf_karanverma19_indian_scam` | `ext/hf/karanverma19__Indian_Multilingual_Scam_Message_Dataset/ultra_premium_scam_dataset.csv` | 120 | Ham: 60, Scam: 60 | language | sms | False | MIT |
| `sms_hf_moznlp_moz_smishing` | `ext/hf/MOZNLP__MOZ-Smishing/test.csv` | 2,561 | Ham: 2,009, Scam: 552 | en | sms | False | Apache-2.0 |
| `sms_hf_ridham115_synthetic_audited` | `ext/hf/Ridham115__indian-scam-sms-synthetic-audited/data/synthetic_audited.csv` | 1,580 | Ham: 783, Scam: 797 | language | sms | True | Apache-2.0 |
| `sms_hf_ucirvine_sms_spam` | `ext/hf/ucirvine__sms_spam/plain_text/train-00000-of-00001.parquet` | 3,000 | Ham: 2,591, Unwanted: 409 | en | sms | False | CC0-1.0 |
| `sms_hf_ysangam_phonecall_hinglish` | `ext/hf/ysangam__Indian_Cyber_Scam_PhoneCall_Hinglish_Dataset/India_Cyber_Scam_Hinglish_Dataset.csv` | 3,000 | Ham: 1,506, Scam: 1,494 | hinglish | call_transcript | False | Apache-2.0 |
| `sms_smish_dt_banglabarta` | `ext/git/SMISH_DT/Dataset/BangalaBarta bangla_spam_sms smishing.csv` | 2,772 | Ham: 924, Scam: 924, Unwanted: 924 | bn | sms | False | CC-BY-4.0 |
| `sms_smish_dt_bangla_spam` | `ext/git/SMISH_DT/Dataset/bangla_spam.csv` | 2,602 | Ham: 1,199, Unwanted: 1,403 | bn | sms | False | CC-BY-4.0 |
| `sms_smish_dt_revised_indian` | `ext/git/SMISH_DT/Dataset/revisedindiandataset.xls` | 3,000 | Ham: 2,035, Unwanted: 965 | en | sms | False | CC-BY-4.0 |
| `sms_smish_dt_singapore_sms` | `ext/git/SMISH_DT/Dataset/Singapore_smsCorpus_en_2015.03.09_all.json` | 2,997 | Ham: 2,997 | en | sms | False | CC-BY-4.0 |
| `sms_smish_dt_smishtank` | `ext/git/SMISH_DT/Dataset/smishtank.csv` | 1,062 | Scam: 1,062 | en | sms | False | CC-BY-4.0 |
| `sms_smish_dt_spam_hunter` | `ext/git/SMISH_DT/Dataset/SPAM-Hunter_full_dataset_messages.csv` | 46 | Unwanted: 46 | en | sms | False | CC-BY-4.0 |
| `sms_smish_dt_super_sms` | `ext/git/SMISH_DT/Dataset/super_sms_dataset.csv` | 2,998 | Ham: 1,847, Scam: 1,151 | en | sms | False | CC-BY-4.0 |
| `sms_smish_dt_sp24_messages` | `ext/git/SMISH_DT/Dataset/sp24-smishing/phishing_messages.csv` | 3,000 | Scam: 3,000 | en | sms | False | CC-BY-4.0 |
| `sms_smish_dt_exais_cleaned` | `ext/git/SMISH_DT/Dataset/ExAIS_SMS Spam Dataset/cleaned_all_ExAIS_SPAM_Dataset.csv` | 3,000 | Ham: 1,505, Unwanted: 1,495 | en | sms | False | CC-BY-4.0 |
| `sms_smish_dt_kor_phishing` | `ext/git/SMISH_DT/Dataset/KOR_smishing_data_raw/KOR_phishing_data_raw.csv` | 3,000 | Ham: 2,385, Scam: 615 | ko | sms | False | CC-BY-4.0 |
| `sms_smish_dt_enron1_ham` | `ext/git/SMISH_DT/Dataset/ENRON Spam Dataset/enron1/ham` | 3,000 | Ham: 3,000 | en | email | False | Public Domain |
| `sms_smish_dt_enron1_spam` | `ext/git/SMISH_DT/Dataset/ENRON Spam Dataset/enron1/spam` | 1,500 | Unwanted: 1,500 | en | email | False | Public Domain |
| `sms_smish_dt_enron2_ham` | `ext/git/SMISH_DT/Dataset/ENRON Spam Dataset/enron2/ham` | 3,000 | Ham: 3,000 | en | email | False | Public Domain |
| `sms_smish_dt_enron2_spam` | `ext/git/SMISH_DT/Dataset/ENRON Spam Dataset/enron2/spam` | 1,496 | Unwanted: 1,496 | en | email | False | Public Domain |
| `sms_smish_dt_enron3_ham` | `ext/git/SMISH_DT/Dataset/ENRON Spam Dataset/enron3/ham` | 3,000 | Ham: 3,000 | en | email | False | Public Domain |
| `sms_smish_dt_enron3_spam` | `ext/git/SMISH_DT/Dataset/ENRON Spam Dataset/enron3/spam` | 1,500 | Unwanted: 1,500 | en | email | False | Public Domain |
| `sms_smish_dt_enron4_ham` | `ext/git/SMISH_DT/Dataset/ENRON Spam Dataset/enron4/ham` | 1,500 | Ham: 1,500 | en | email | False | Public Domain |
| `sms_smish_dt_enron4_spam` | `ext/git/SMISH_DT/Dataset/ENRON Spam Dataset/enron4/spam` | 3,000 | Unwanted: 3,000 | en | email | False | Public Domain |
| `sms_smish_dt_enron5_ham` | `ext/git/SMISH_DT/Dataset/ENRON Spam Dataset/enron5/ham` | 1,500 | Ham: 1,500 | en | email | False | Public Domain |
| `sms_smish_dt_enron5_spam` | `ext/git/SMISH_DT/Dataset/ENRON Spam Dataset/enron5/spam` | 3,000 | Unwanted: 3,000 | en | email | False | Public Domain |
| `sms_smish_dt_enron6_ham` | `ext/git/SMISH_DT/Dataset/ENRON Spam Dataset/enron6/ham` | 1,500 | Ham: 1,500 | en | email | False | Public Domain |
| `sms_smish_dt_enron6_spam` | `ext/git/SMISH_DT/Dataset/ENRON Spam Dataset/enron6/spam` | 3,000 | Unwanted: 3,000 | en | email | False | Public Domain |

**SMS LIMIT RUN Totals:**
- Total rows kept: **149,859**
- Unique message hashes (`text_hash`): **101,187**
- Cross-source label conflicts: **889**

---

## 2. Unified URL Corpus (`data/processed/url/`)

| Source ID | Path | Rows Kept (LIMIT RUN) | Label Counts (Benign / Phishing / Malware / Defacement / Malicious) | Channel | Synthetic | Licence | Probable Inversion |
|---|---|---:|---|---|---|---|---|
| `url_alishan07_homograph_phishing` | `url/alishan07__adversarial-homograph-detection/adversarial-homograph-detection/Adversarial Homograph Detection.csv` | 3,000 | Benign: 1,479, Phishing: 1,521 | web | False | Apache-2.0 | No |
| `url_antonyj453_urldataset` | `url/antonyj453__urldataset/data.csv` | 3,000 | Malicious: 3,000 | web | False | Unknown | No |
| `url_dhrubangtalukdar_phishing_unique` | `url/dhrubangtalukdar__real-world-phishing-url-classification-data/phishing_url_dataset_unique.csv` | 3,000 | Benign: 1,536, Malicious: 1,464 | web | False | CC0-1.0 | No |
| `url_golner_phishing_domains` | `url/golner__phishing-domains/dataset_202402231320.csv` | 3,000 | Phishing: 3,000 | web | False | CC0-1.0 | No |
| `url_harisudhan411_new_data_urls` | `url/harisudhan411__phishing-and-legitimate-urls/new_data_urls.csv` | 3,000 | Phishing: 3,000 | web | False | CC0-1.0 | No |
| `url_harshsinghal_common_crawl_domains` | `url/harshsinghal__random-sample-of-common-crawl-domains-from-2021/b7b9b3f1-762f-41c4-9899-bcee33740c64.csv` | 3,000 | Benign: 3,000 | web | False | CC0-1.0 | No |
| `url_hassaanmustafavi_phishing_urls` | `url/hassaanmustafavi__phishing-urls-dataset/url_dataset.csv` | 3,000 | Benign: 3,000 | web | False | Unknown | No |
| `url_joebeachcapital_phishing_urls` | `url/joebeachcapital__phishing-urls/urlset.csv` | 3,000 | Phishing: 3,000 | web | False | CC0-1.0 | No |
| `url_joebeachcapital_phiusiil` | `url/joebeachcapital__phiusiil-phishing-url/PhiUSIIL_Phishing_URL_Dataset.csv` | 3,000 | Benign: 2,127, Phishing: 873 | web | False | CC BY 4.0 | No |
| `url_marryjanety_phishing_simple` | `url/marryjanety__phishing-url-dataset-url-and-label/phishing_simple (1).csv` | 3,000 | Benign: 2,127, Phishing: 873 | web | False | CC0-1.0 | No |
| `url_moutasmtamimi_mud_2026` | `url/moutasmtamimi__malicious-url-detection-dataset-enhanced-2026/MUD_malicious_urls_2026_V2.csv` | 3,000 | Benign: 2,210, Defacement: 546, Malware: 73, Phishing: 171 | web | False | Apache-2.0 | No |
| `url_nhutrinhanna_merged_urls` | `url/nhutrinhanna__malicious-and-benign-urls-datasets/merged_urls_dataset.csv` | 3,000 | Phishing: 3,000 | web | False | Unknown | No |
| `url_pilarpieiro_alexa` | `url/pilarpieiro__malicious-and-benign-url-dataset/alexatop1m_20220202_benign.csv` | 3,000 | Benign: 3,000 | web | False | Unknown | No |
| `url_pilarpieiro_dmoz` | `url/pilarpieiro__malicious-and-benign-url-dataset/dmoz_domain_category_20220202_benign.csv` | 3,000 | Benign: 3,000 | web | False | Unknown | No |
| `url_pilarpieiro_domcop` | `url/pilarpieiro__malicious-and-benign-url-dataset/domcop_20220202_benign.csv` | 3,000 | Benign: 3,000 | web | False | Unknown | No |
| `url_pilarpieiro_majestic` | `url/pilarpieiro__malicious-and-benign-url-dataset/majestic_million_20220202_benign.csv` | 3,000 | Benign: 3,000 | web | False | Unknown | No |
| `url_pilarpieiro_manual_data` | `url/pilarpieiro__malicious-and-benign-url-dataset/manual_data.csv` | 19 | Benign: 19 | web | False | Unknown | No |
| `url_pilarpieiro_manual_j` | `url/pilarpieiro__malicious-and-benign-url-dataset/manual_j.csv` | 994 | Benign: 994 | web | False | Unknown | No |
| `url_pilarpieiro_manual_plugin` | `url/pilarpieiro__malicious-and-benign-url-dataset/manual_plugin_benign.csv` | 3,000 | Benign: 3,000 | web | False | Unknown | No |
| `url_pilarpieiro_parsed_new` | `url/pilarpieiro__malicious-and-benign-url-dataset/parsed-new_20220202_benign.csv` | 3,000 | Benign: 3,000 | web | False | Unknown | No |
| `url_pilarpieiro_parsed_subdomain` | `url/pilarpieiro__malicious-and-benign-url-dataset/parsed-subdomain_20220202_benign.csv` | 3,000 | Benign: 3,000 | web | False | Unknown | No |
| `url_pilarpieiro_top500` | `url/pilarpieiro__malicious-and-benign-url-dataset/top500Domains_20220202_benign.csv` | 500 | Benign: 500 | web | False | Unknown | No |
| `url_pilarpieiro_tranco` | `url/pilarpieiro__malicious-and-benign-url-dataset/tranco_K2K4W_20220202_benign.csv` | 3,000 | Benign: 3,000 | web | False | Unknown | No |
| `url_pilarpieiro_gmail` | `url/pilarpieiro__malicious-and-benign-url-dataset/urls_20220201_gmail.csv` | 904 | Benign: 904 | web | False | Unknown | No |
| `url_pilarpieiro_outlook` | `url/pilarpieiro__malicious-and-benign-url-dataset/urls_20220201_outlook.csv` | 569 | Benign: 569 | web | False | Unknown | No |
| `url_pilarpieiro_gmail_j` | `url/pilarpieiro__malicious-and-benign-url-dataset/urls_20220202_gmail_j.csv` | 419 | Benign: 419 | web | False | Unknown | No |
| `url_pilarpieiro_419_fakeurls_0323` | `url/pilarpieiro__malicious-and-benign-url-dataset/419_fakeurls_325_0323.csv` | 3,000 | Phishing: 3,000 | web | False | Unknown | No |
| `url_pilarpieiro_419_fakeurls_clean` | `url/pilarpieiro__malicious-and-benign-url-dataset/419_fakeurls_325_clean.csv` | 3,000 | Phishing: 3,000 | web | False | Unknown | No |
| `url_pilarpieiro_all_phishing_domains` | `url/pilarpieiro__malicious-and-benign-url-dataset/ALL-phishing-domains_20220207_malicious.csv` | 3,000 | Phishing: 3,000 | web | False | Unknown | No |
| `url_pilarpieiro_all_phishing_links` | `url/pilarpieiro__malicious-and-benign-url-dataset/ALL-phishing-links_20220207_malicious.csv` | 3,000 | Phishing: 3,000 | web | False | Unknown | No |
| `url_pilarpieiro_cryptoscan` | `url/pilarpieiro__malicious-and-benign-url-dataset/CryptoScanDB_malicious_git.csv` | 3,000 | Phishing: 3,000 | web | False | Unknown | No |
| `url_pilarpieiro_openphish` | `url/pilarpieiro__malicious-and-benign-url-dataset/openphish.csv` | 500 | Phishing: 500 | web | False | Unknown | No |
| `url_pilarpieiro_openphish_2` | `url/pilarpieiro__malicious-and-benign-url-dataset/openphish_2.csv` | 499 | Phishing: 499 | web | False | Unknown | No |
| `url_pilarpieiro_data_clean_test` | `url/pilarpieiro__malicious-and-benign-url-dataset/data_clean_test_mendel.csv` | 3,000 | Benign: 2,948, Phishing: 52 | web | False | Unknown | No |
| `url_pilarpieiro_data_clean_train` | `url/pilarpieiro__malicious-and-benign-url-dataset/data_clean_train_mendel.csv` | 3,000 | Benign: 2,931, Phishing: 69 | web | False | Unknown | No |
| `url_pilarpieiro_manual_samples` | `url/pilarpieiro__malicious-and-benign-url-dataset/manual_samples.csv` | 38 | Benign: 30, Phishing: 8 | web | False | Unknown | No |
| `url_pilarpieiro_phishtank` | `url/pilarpieiro__malicious-and-benign-url-dataset/phishtank_*.csv` | 3,000 | Phishing: 3,000 | web | False | Unknown | No |
| `url_quangnguynv_phishtank` | `url/quangnguynv__phishtank-phishingurl-valid-dataset/PhishTank_2026.csv` | 3,000 | Phishing: 3,000 | web | False | CC0-1.0 | No |
| `url_sahandnamvar_dataset` | `url/sahandnamvar__phishing-url-detection-111k-urls-22-features/Dataset.csv` | 3,000 | Benign: 3,000 | web | False | CC0-1.0 | No |
| `url_samahsadiq_balanced_urls` | `url/samahsadiq__benign-and-malicious-urls/balanced_urls.csv` | 3,000 | Benign: 3,000 | web | False | CC0-1.0 | No |
| `url_shawon10_dmoz_classification` | `url/shawon10__url-classification-dataset-dmoz/URL Classification.csv` | 3,000 | Benign: 3,000 | web | False | Other | No |
| `url_sid321axn_malicious_phish` | `url/sid321axn__malicious-urls-dataset/malicious_phish.csv` | 3,000 | Benign: 2,205, Defacement: 547, Malware: 77, Phishing: 171 | web | False | CC0-1.0 | No |
| `url_siddharthkumar25_urldata` | `url/siddharthkumar25__malicious-and-benign-urls/urldata.csv` | 3,000 | Benign: 3,000 | web | False | Unknown | No |
| `url_somanshumahajan_65lakh_urls` | `url/somanshumahajan__65-lakh-urls-labelled-as-1-and-0/urls_*.csv` | 3,000 | Benign: 1,632, Malicious: 1,368 | web | False | Unknown | No |
| `url_taruntiwarihp_phishing_site_urls` | `url/taruntiwarihp__phishing-site-urls/phishing_site_urls.csv` | 3,000 | Phishing: 3,000 | web | False | CC0-1.0 | No |
| `url_vibhuyadav0_stealthphisher` | `url/vibhuyadav0__stealthphisher-phishing-attack-dataset/StealthPhisher.csv` | 3,000 | Benign: 1,419, Phishing: 1,581 | web | False | CC0-1.0 | No |
| `url_victusadi_phishing_features` | `url/victusadi__phishing-urls-dataset-with-extracted-features/phishing_features.csv` | 3,000 | Phishing: 3,000 | web | False | CC0-1.0 | No |
| `url_vishalxtyagi_verified_online` | `url/vishalxtyagi__phishing-website-detector-based-on-url/verified_online.csv` | 3,000 | Phishing: 3,000 | web | False | Unknown | No |
| `url_zishnusarker_4class_final` | `url/zishnusarker__malicious-url-classification-706k/dataset_4class_final.csv` | 3,000 | Benign: 2,210, Defacement: 546, Malware: 73, Phishing: 171 | web | False | CC0-1.0 | No |
| `url_openphish_feed` | `ext/feeds/openphish_feed_2026-11-02.txt` | 300 | Phishing: 300 | feed | False | Open Source | No |
| `url_tranco_feed` | `ext/feeds/tranco_top1m_2026-11-02.zip` | 3,000 | Benign: 3,000 | feed | False | Open Source | No |
| `url_mendeley_phishing_urls` | `ext/mendeley/url_phish_2025/Phishing URLs.csv` | 3,000 | Phishing: 3,000 | web | False | CC-BY-4.0 | No |
| `url_mendeley_url_dataset` | `ext/mendeley/url_phish_2025/URL dataset.csv` | 3,000 | Benign: 3,000 | web | False | CC-BY-4.0 | No |
| `url_hf_mitake_phishing_urls` | `ext/hf/Mitake__PhishingURLsANDBenignURLs/PhishBenignDataset.csv` | 3,000 | Benign: 2,052, Phishing: 948 | web | False | Apache-2.0 | No |
| `url_hf_pirocheto_phishing_url_train` | `ext/hf/pirocheto__phishing-url/data/train.parquet` | 3,000 | Benign: 1,493, Phishing: 1,507 | web | False | Apache-2.0 | No |
| `url_hf_pirocheto_phishing_url_test` | `ext/hf/pirocheto__phishing-url/data/test.parquet` | 3,000 | Benign: 1,494, Phishing: 1,506 | web | False | Apache-2.0 | No |

**URL LIMIT RUN Totals:**
- Total rows kept: **142,742**
- Unique normalized URLs (`norm_url`): **107,201**
- Cross-source label conflicts: **176**

---

## 3. Phishing on Trusted Hosts

Real-world phishing campaigns frequently abuse high-reputation shared infrastructure (e.g. `docs.google.com/forms`, `sites.google.com`, `drive.google.com`, `google.com/url` open redirects) to evade domain blocklists and deceive users. Rather than reflecting label inversion or dataset noise, these entries represent authentic threat telemetry where malicious pages are hosted under reputable domains.

When evaluated strictly against bare homepages (records having no path and whose host minus a leading `www.` equals a known trusted domain), no feed exhibits label inversion (`probable_inversion_sources = []`).

The table below details all URL sources containing non-benign `hosted_rows` (records sharing a registered domain with a known trusted site, but possessing a subdomain or a path):

| URL Source ID | Non-Benign Hosted Rows | Non-Benign Labels Breakdown | Abused Host Examples |
|---|---:|---|---|
| `url_dhrubangtalukdar_phishing_unique` | 2 | Malicious: 2 | `drive.google.com`, `sites.google.com` |
| `url_hf_mitake_phishing_urls` | 3 | Phishing: 3 | `docs.google.com`, `sites.google.com` |
| `url_hf_pirocheto_phishing_url_test` | 33 | Phishing: 33 | `docs.google.com`, `sites.google.com` |
| `url_hf_pirocheto_phishing_url_train` | 33 | Phishing: 33 | `docs.google.com`, `sites.google.com` |
| `url_joebeachcapital_phishing_urls` | 19 | Phishing: 19 | `docs.google.com` |
| `url_joebeachcapital_phiusiil` | 8 | Phishing: 8 | `docs.google.com`, `drive.google.com`, `google.com/url` |
| `url_marryjanety_phishing_simple` | 8 | Phishing: 8 | `docs.google.com`, `drive.google.com`, `google.com/url` |
| `url_mendeley_phishing_urls` | 71 | Phishing: 71 | `docs.google.com`, `sites.google.com` |
| `url_moutasmtamimi_mud_2026` | 1 | Phishing: 1 | `sites.google.com` |
| `url_nhutrinhanna_merged_urls` | 250 | Phishing: 250 | `docs.google.com` |
| `url_pilarpieiro_cryptoscan` | 2 | Phishing: 2 | `play.google.com`, `docs.google.com` |
| `url_pilarpieiro_data_clean_test` | 1 | Phishing: 1 | `docs.google.com` |
| `url_pilarpieiro_phishtank` | 3 | Phishing: 3 | `sites.google.com` |
| `url_quangnguynv_phishtank` | 115 | Phishing: 115 | `docs.google.com` |
| `url_sid321axn_malicious_phish` | 1 | Phishing: 1 | `sites.google.com` |
| `url_somanshumahajan_65lakh_urls` | 4 | Malicious: 4 | `drive.google.com`, `sites.google.com` |
| `url_taruntiwarihp_phishing_site_urls` | 19 | Phishing: 19 | `docs.google.com` |
| `url_vibhuyadav0_stealthphisher` | 93 | Phishing: 93 | `docs.google.com`, `google.com/url` |
| `url_victusadi_phishing_features` | 2 | Phishing: 2 | `drive.google.com` |
| `url_vishalxtyagi_verified_online` | 3 | Phishing: 3 | `sites.google.com` |
| `url_zishnusarker_4class_final` | 1 | Phishing: 1 | `sites.google.com` |
| **Total** | **672** | **Phishing: 666, Malicious: 6** | |

---

## 4. Skipped Files with Reasons
Files consciously excluded from processing with justification:

| Entry ID | Path / Glob | Reason |
|---|---|---|
| `sms_dahalea_calls` | `sms/dahalea__banking-sms-fraud-datasets/Kaggle_Example/Calls.xlsx` | 9-row toy example of phone call strings ('call1', 'call2'), not SMS corpus |
| `sms_dahalea_sms` | `sms/dahalea__banking-sms-fraud-datasets/Kaggle_Example/SMS.xlsx` | 9-row toy synthetic placeholder with dummy text ('sms1', 'sms2'), not real SMS corpus |
| `sms_nickgabriel100_sms_fraud` | `sms/nickgabriel100__sms-fraud-detection-dataset/SMS-Fraud-Data.csv` | Engineered feature dataset containing template and metadata columns without raw message text |
| `sms_wa1618i_whatsapp_violine` | `sms/wa1618i__whatsapp-scam-dataset/WhatsApp Chat with Violine.txt` | Duplicate chat export of WhatsApp Chat with Violine (1).txt |
| `sms_wa1618i_whatsapp_zevanca` | `sms/wa1618i__whatsapp-scam-dataset/WhatsApp Chat with Zevanca.txt` | Duplicate earlier export of WhatsApp Chat with Zevanca (1).txt |
| `url_alishan07_homograph_splits` | `url/alishan07__adversarial-homograph-detection/adversarial-homograph-detection/homograph_phishing_*.csv` | Train/val/test splits of combined Adversarial Homograph Detection.csv |
| `url_alishan07_metadata_json` | `url/alishan07__adversarial-homograph-detection/adversarial-homograph-detection/homograph-dataset-metadata.json` | Dataset metadata description JSON, not tabular URL data |
| `url_moutasmtamimi_dataset_v2` | `url/moutasmtamimi__malicious-url-detection-dataset-enhanced-2026/dataset_with_all_features v2.csv` | Intermediate release subset superseded by MUD_malicious_urls_2026_V2.csv |
| `url_moutasmtamimi_final_features` | `url/moutasmtamimi__malicious-url-detection-dataset-enhanced-2026/final_dataset_with_all_features.csv` | Feature-only dataset without raw URL column |
| `url_moutasmtamimi_final_features_v3` | `url/moutasmtamimi__malicious-url-detection-dataset-enhanced-2026/final_dataset_with_all_features_v3.1.csv` | Intermediate release subset superseded by MUD_malicious_urls_2026_V2.csv |
| `url_sarrazer_iscx_2016` | `url/sarrazer__url-dataset-iscx-url2016/*.csv` | Feature-only ISCX URL 2016 dataset without raw URL text |
| `url_shawon10_dmoz_descriptions` | `url/shawon10__url-classification-dataset-dmoz/dmoz.csv` | Website descriptions and categories only without raw URL column |
| `url_zishnusarker_binary` | `url/zishnusarker__malicious-url-classification-706k/dataset_binary.csv` | Binary rollup view of the same rows in dataset_4class_final.csv |
| `ext_reportsmishing_license` | `ext/git/reportsmishing/LICENSE-free.txt` | Repository license text, not tabular data |
| `sms_hf_nini654_hinglish_scam` | `ext/hf/nini654__hinglish-scam-text-dataset/data.json` | Duplicate copy of bolewara/hinglish-scam-text-dataset data.json |
| `ext_hf_ridham115_audit_decisions` | `ext/hf/Ridham115__indian-scam-sms-synthetic-audited/audit_decisions.csv` | Audit decision log, not message corpus |
| `ext_hf_ridham115_stats` | `ext/hf/Ridham115__indian-scam-sms-synthetic-audited/stats.json` | Summary statistics metadata |
| `ext_hf_cache_metadata` | `ext/hf/*/.cache/**/*` | HuggingFace cache and tree metadata files |
| `ext_smish_dt_papers` | `ext/git/SMISH_DT/papers.xlsx` | Research papers bibliography, not corpus |
| `sms_smish_dt_mendeley_5971` | `ext/git/SMISH_DT/Dataset/Mendeley_Dataset_5971.csv` | Duplicate copy of fadlifatih/sms-phishing-dataset Dataset_5971.csv |
| `ext_smish_dt_tld_list` | `ext/git/SMISH_DT/Dataset/tld-list-basic.csv` | TLD reference list, not corpus |
| `ext_smish_dt_uci_copy` | `ext/git/SMISH_DT/Dataset/UCI_SMSSpamCollection` | Duplicate copy of uciml/sms-spam-collection-dataset |
| `sms_smish_dt_sp24_campaigns` | `ext/git/SMISH_DT/Dataset/sp24-smishing/phishing_campaigns.csv` | Campaign summary view of phishing_messages.csv |
| `sms_smish_dt_exais_raw` | `ext/git/SMISH_DT/Dataset/ExAIS_SMS Spam Dataset/all_ExAIS_SPAM_Dataset.csv` | Uncleaned raw version of cleaned_all_ExAIS_SPAM_Dataset.csv |
| `sms_smish_dt_exais_user_splits` | `ext/git/SMISH_DT/Dataset/ExAIS_SMS Spam Dataset/ExAIS_SMS Spam Dataset/*.csv` | Per-user splits merged into cleaned_all_ExAIS_SPAM_Dataset.csv |
| `ext_smish_dt_enron1_summary` | `ext/git/SMISH_DT/Dataset/ENRON Spam Dataset/enron1/Summary.txt` | Enron dataset partition summary notes |
| `ext_smish_dt_enron2_summary` | `ext/git/SMISH_DT/Dataset/ENRON Spam Dataset/enron2/Summary.txt` | Enron dataset partition summary notes |
| `ext_smish_dt_enron3_summary` | `ext/git/SMISH_DT/Dataset/ENRON Spam Dataset/enron3/Summary.txt` | Enron dataset partition summary notes |
| `ext_smish_dt_enron4_summary` | `ext/git/SMISH_DT/Dataset/ENRON Spam Dataset/enron4/Summary.txt` | Enron dataset partition summary notes |
| `ext_smish_dt_enron5_summary` | `ext/git/SMISH_DT/Dataset/ENRON Spam Dataset/enron5/Summary.txt` | Enron dataset partition summary notes |
| `ext_smish_dt_enron6_summary` | `ext/git/SMISH_DT/Dataset/ENRON Spam Dataset/enron6/Summary.txt` | Enron dataset partition summary notes |
| `ext_smish_dt_email_data` | `ext/git/SMISH_DT/Email Data/*.csv` | Extracted email address lists without message body |
| `ext_smish_dt_phone_data` | `ext/git/SMISH_DT/Phone Data/*.csv` | Extracted phone number lists without message body |
| `ext_smish_dt_refined_datasets` | `ext/git/SMISH_DT/Refined Datasets/*.csv` | Derived refined copies of datasets in Dataset/ directory |
| `ext_smish_dt_url_data` | `ext/git/SMISH_DT/URL Data/*.csv` | Extracted URL and website analysis tables without message body |

---

## 5. Label Mapping Decisions

Every source mapping is backed by explicit evidence quoting the dataset schema, metadata card, or known-site verification:

| Source ID | Evidence Justifying Label Mapping |
|---|---|
| `sms_abdelrahmanmahmoud22_english_sms` | Credit card phishing SMS: label 0 is legitimate conversation (ham), label 1 is credit card smishing (scam) |
| `sms_aditsawhney_indian_jobs` | Synthetic Indian jobs dataset: job postings (channel: job_post); label 0 is legitimate job posting, label 1 is recruitment scam |
| `sms_ahmadtijjani_urgency_phishing` | Phishing messages with authority/urgency cues all labeled phishing (scam) |
| `sms_ameenhasan_fake_fraud` | SMS fraud dataset: 0 is ham (UCI sample), 1 is fraud (scam) |
| `sms_atherionsystems_indian_scam_30k` | Chat completion Indian scam SMS: assistant evaluates LEGITIMATE (ham) vs SCAM (scam) |
| `sms_bwandowando_philippine_spam` | Philippine spam SMS collection containing only unwanted spam messages |
| `sms_dharshiyanacc_spam_ham_phishing` | Three-class message dataset: 0 is ham (appointments/records), 1 is phishing/scam (prize/support scam), 2 is commercial spam (unwanted) |
| `sms_fadlifatih_sms_phishing` | Mendeley smishing dataset: ham is legitimate, Smishing/smishing is scam, spam/Spam is promotional |
| `sms_galactus007_smssmishcollection` | Mishra-Soni smishing collection: ham is legitimate SMS, smish is smishing scam |
| `sms_gokhansoyturk_combined_sms` | Smishing SMS dataset: is_smishing column directly marks 1 for smishing scam and 0 for legitimate |
| `sms_junioralive_india_spam` | Indian telecom SMS: ham is transactional/personal, spam is unwanted promotional broadcast |
| `sms_karanverma_punjab_fraud` | Trilingual fraud benchmark: safe is advisory/legitimate, scam is immigration/financial scam |
| `sms_kritikgianta_merged_sms` | TRAI category definitions: service SMS is transactional/OTP (ham), promotional is commercial spam (unwanted) |
| `sms_mexwell_telegram_spam_ham` | Telegram messages: ham is regular conversation, spam is unwanted broadcast |
| `sms_msubhansiddiqui_financial_scam` | Financial deceptive text meta-dataset: 0 is verified authentic news/phrase, 1 is deceptive scam text |
| `sms_rajnathpatel_multilingual_spam` | Multilingual translated spam: ham is legitimate personal message, spam is unwanted message |
| `sms_rithikkumar802_adaption_fraud` | Adaption SMS fraud dataset: legit is legitimate communication (ham), fraud is scam/phishing (scam), 2,422 unlabelled null rows mapped to DROP |
| `sms_roberto2057_hindi_sms` | Hindi SMS spam/ham dataset: written in Devanagari script (lang: hi); ham is legitimate Hindi conversation, spam is promotional |
| `sms_siddharthrane07_scamshield_test` | ScamShield test split: is_scam indicates malicious scam (1) vs non-scam (0) |
| `sms_siddharthrane07_scamshield_train` | ScamShield train split: is_scam indicates malicious scam (1) vs non-scam (0) |
| `sms_siddharthrane07_scamshield_val` | ScamShield validation split: is_scam indicates malicious scam (1) vs non-scam (0) |
| `sms_sngmyd_india_cyber_scam` | Indian cyber scam call dataset: romanised Hindi mixed with English dialogue (lang: hinglish); 0 is non-scam legitimate dialogue, 1 is scam extortion/fraud |
| `sms_spamdetectorssms_combined_multilingual` | Combined multilingual spam: ham is legitimate communication, spam is unwanted marketing |
| `sms_tapakah68_spam_texts` | OCR-extracted promotional and marketing SMS screenshots all classified as unwanted spam |
| `sms_teeconnie_english_nonscam` | Legitimate customer service and medical call conversations |
| `sms_teeconnie_english_scam` | Scam and phishing call conversations requesting banking or credit card details |
| `sms_uciml_spam` | UCI SMS Spam Collection: v1 ham is legitimate SMS, spam is unwanted marketing |
| `sms_vinit119_sms_scam` | Merged SMS dataset: ham is legitimate, spam/Spam is unwanted marketing |
| `sms_wa1618i_whatsapp_chat_1` | WhatsApp investment scam conversation log |
| `sms_wa1618i_whatsapp_chat_2` | WhatsApp investment scam conversation log |
| `sms_wa1618i_whatsapp_violine_1` | WhatsApp romance/investment scam conversation log |
| `sms_wa1618i_whatsapp_zevanca_1` | WhatsApp crypto scam conversation log |
| `sms_yatinaggarwal033_whatsapp_scam` | WhatsApp scam dataset: message contains scam messages across 10 fraud types |
| `url_alishan07_homograph_phishing` | Adversarial homograph detection dataset: 0 is benign, 1 is homograph phishing attack |
| `url_antonyj453_urldataset` | antonyj453 dataset: good is benign URL, bad is malicious URL |
| `url_dhrubangtalukdar_phishing_unique` | Source column confirms: 0 from tranco (benign), 1 from urlhaus (malicious) |
| `url_golner_phishing_domains` | IS_PHISHING binary indicator: 0 is non-phishing (benign), 1 is phishing |
| `url_harisudhan411_new_data_urls` | Inspection shows status 1 contains legitimate sites (rgipt.ac.in, lifewire.com) and status 0 contains phishing domains (paypalsecurity.fr, lookalike amazon domains) |
| `url_harshsinghal_common_crawl_domains` | Random sample of Common Crawl domains from 2021 web crawl (benign) |
| `url_hassaanmustafavi_phishing_urls` | URL dataset types: legitimate is benign, phishing is phishing |
| `url_joebeachcapital_phishing_urls` | Inspection shows 1.0 contains PayPal/Skype phishing URLs, 0.0 contains university/gov URLs (benign), corrupted strings map to DROP |
| `url_joebeachcapital_phiusiil` | PhiUSIIL paper documentation specifies label 1 = legitimate (benign) and label 0 = phishing |
| `url_marryjanety_phishing_simple` | Labels explicitly given as benign and phishing |
| `url_moutasmtamimi_mud_2026` | MUD 2026 V2 dataset class_label: benign, defacement, phishing, malware |
| `url_nhutrinhanna_merged_urls` | nhutrinhanna: phish mapped to phishing, adult content outside threat classes mapped to DROP |
| `url_pilarpieiro_alexa` | Pilar Pieiro collection: Alexa top 1M benign domains snapshot with label 0 (benign) |
| `url_pilarpieiro_dmoz` | Pilar Pieiro collection: DMOZ category benign domains with label 0 (benign) |
| `url_pilarpieiro_domcop` | Pilar Pieiro collection: Domcop top benign domains with label 0 (benign) |
| `url_pilarpieiro_majestic` | Pilar Pieiro collection: Majestic Million benign domains with label 0 (benign) |
| `url_pilarpieiro_manual_data` | Pilar Pieiro collection: Manual benign URLs with label 0 (benign) |
| `url_pilarpieiro_manual_j` | Pilar Pieiro collection: Manual benign notifications with label 0 (benign) |
| `url_pilarpieiro_manual_plugin` | Pilar Pieiro collection: Manual plugin benign URLs with label 0 (benign) |
| `url_pilarpieiro_parsed_new` | Pilar Pieiro collection: Parsed new benign URLs with label 0 (benign) |
| `url_pilarpieiro_parsed_subdomain` | Pilar Pieiro collection: Parsed subdomain benign URLs with label 0 (benign) |
| `url_pilarpieiro_top500` | Pilar Pieiro collection: Top 500 benign domains with label 0 (benign) |
| `url_pilarpieiro_tranco` | Pilar Pieiro collection: Tranco top benign domains list with label 0 (benign) |
| `url_pilarpieiro_gmail` | Pilar Pieiro collection: Gmail benign URLs with label 0 (benign) |
| `url_pilarpieiro_outlook` | Pilar Pieiro collection: Outlook benign URLs with label 0 (benign) |
| `url_pilarpieiro_gmail_j` | Pilar Pieiro collection: Gmail notification benign URLs with label 0 (benign) |
| `url_pilarpieiro_419_fakeurls_0323` | Pilar Pieiro collection: 419 scam and fake URLs feed with label 1 (phishing) |
| `url_pilarpieiro_419_fakeurls_clean` | Pilar Pieiro collection: 419 clean fake URLs feed with label 1 (phishing) |
| `url_pilarpieiro_all_phishing_domains` | Pilar Pieiro collection: All phishing domains feed with label 1 (phishing) |
| `url_pilarpieiro_all_phishing_links` | Pilar Pieiro collection: All phishing links feed with label 1 (phishing) |
| `url_pilarpieiro_cryptoscan` | Pilar Pieiro collection: CryptoScanDB malicious URLs with label 1 (phishing) |
| `url_pilarpieiro_openphish` | Pilar Pieiro collection: OpenPhish feed snapshot with label 1 (phishing) |
| `url_pilarpieiro_openphish_2` | Pilar Pieiro collection: OpenPhish feed secondary snapshot with label 1 (phishing) |
| `url_pilarpieiro_data_clean_test` | Pilar Pieiro collection: Cleaned Mendel test set: 0 is benign, 1 is phishing |
| `url_pilarpieiro_data_clean_train` | Pilar Pieiro collection: Cleaned Mendel train set: 0 is benign, 1 is phishing |
| `url_pilarpieiro_manual_samples` | Pilar Pieiro collection: Manual samples: 0 is benign, 1 is phishing |
| `url_pilarpieiro_phishtank` | Pilar Pieiro PhishTank split files: all verified phishing URLs labeled 1 |
| `url_quangnguynv_phishtank` | PhishTank valid phishing URL dataset: CSV column URL; all entries verified phishing |
| `url_sahandnamvar_dataset` | Inspection shows label 0 contains university/legitimate domains (rmit.edu.au) and label 1 contains phishing URLs |
| `url_samahsadiq_balanced_urls` | Labels explicitly given as benign and malicious |
| `url_shawon10_dmoz_classification` | DMOZ open directory project URL classification: directory of legitimate/benign websites |
| `url_sid321axn_malicious_phish` | Multi-class dataset types: benign, defacement, phishing, malware |
| `url_siddharthkumar25_urldata` | Labels explicitly given as benign and malicious |
| `url_somanshumahajan_65lakh_urls` | Kaggle dataset description: 65 lakh URLs labeled 1 as malicious and 0 as non-malicious (benign) |
| `url_taruntiwarihp_phishing_site_urls` | taruntiwarihp dataset: good is benign URL, bad is phishing URL |
| `url_vibhuyadav0_stealthphisher` | StealthPhisher labels: Legitimate is benign, Phishing is phishing |
| `url_victusadi_phishing_features` | Inspection shows label 0 contains top alexa domains (google.com, youtube.com) as benign, label 1 contains phishing URLs |
| `url_vishalxtyagi_verified_online` | PhishTank verified online phishing URLs collection |
| `url_zishnusarker_4class_final` | 4-class final dataset: benign, phishing, defacement, malware |
| `url_openphish_feed` | OpenPhish community feed of active verified phishing URLs |
| `url_tranco_feed` | Tranco top 1 million legitimate domains feed |
| `sms_mendeley_mishra_soni` | Mishra & Soni smishing benchmark in Dataset_5971.zip: ham is legitimate, Smishing is scam, spam is unwanted |
| `url_mendeley_phishing_urls` | Mendeley URL phish 2025: phishing URLs labeled phishing |
| `url_mendeley_url_dataset` | Mendeley URL phish 2025: legitimate is benign, phishing is phishing |
| `sms_hf_alusci_sms_otp` | SMS OTP dataset: valid OTP message (ham) vs not valid spam (unwanted) |
| `sms_hf_bolewara_hinglish_scam` | Hinglish scam text dataset: romanised Hindi mixed with English (lang: hinglish); 0 is legitimate conversation (ham), 1 is scam/fraud (scam) |
| `sms_hf_cloveai_india_spam` | India spam SMS: 0 is ham, 1 is spam |
| `sms_hf_dbarbedillo_sms_spam_multilingual` | Multilingual augmented SMS spam: ham is legitimate, spam is unwanted |
| `sms_hf_karanverma19_indian_scam` | Indian multilingual scam messages: legit is ham, scam is scam |
| `url_hf_mitake_phishing_urls` | Mitake dataset: 0 is benign (eventbrite.com, tumblr.com), 1 is phishing (jreast lookalike, fake yahoo) |
| `sms_hf_moznlp_moz_smishing` | MOZ smishing: Legitimate is ham, Smishing is scam |
| `url_hf_pirocheto_phishing_url_train` | Pirocheto phishing URL dataset: legitimate is benign, phishing is phishing |
| `url_hf_pirocheto_phishing_url_test` | Pirocheto phishing URL test split: legitimate is benign, phishing is phishing |
| `sms_hf_ridham115_synthetic_audited` | Indian scam SMS synthetic audited: safe is ham, scam is scam |
| `sms_hf_ucirvine_sms_spam` | HuggingFace mirror of UCI SMS spam: 0 is ham, 1 is spam |
| `sms_hf_ysangam_phonecall_hinglish` | Indian cyber scam phone call dataset: romanised Hindi mixed with English phone call transcripts (lang: hinglish); 0 is ham, 1 is scam |
| `sms_smish_dt_banglabarta` | BanglaBarta smishing dataset: normal is ham, promo is unwanted, smish is scam |
| `sms_smish_dt_bangla_spam` | Bangla spam dataset: ham is personal message, spam is unwanted broadcast |
| `sms_smish_dt_revised_indian` | Revised Indian dataset: ham is legitimate Indian SMS, spam is unwanted promotional SMS |
| `sms_smish_dt_singapore_sms` | NUS SMS Corpus: 55k legitimate collected mobile messages from Singapore |
| `sms_smish_dt_smishtank` | SmishTank crowd-sourced smishing reports: verified smishing messages (scam) |
| `sms_smish_dt_spam_hunter` | SPAM-Hunter full dataset messages: collected promotional spam SMS |
| `sms_smish_dt_super_sms` | Super SMS dataset: label 0 is legitimate SMS, label 1 is smishing/spam, NaN label rows dropped explicitly |
| `sms_smish_dt_sp24_messages` | SP24 smishing campaign messages: active smishing attacks (scam) |
| `sms_smish_dt_exais_cleaned` | ExAIS SMS spam dataset: HAM is legitimate, SPAM is unwanted |
| `sms_smish_dt_kor_phishing` | Korean smishing dataset: 0 is legitimate Korean message, 1 is smishing fraud |
| `sms_smish_dt_enron1_ham` | Enron spam benchmark subset 1: ham folder contains verified legitimate business emails |
| `sms_smish_dt_enron1_spam` | Enron spam benchmark subset 1: spam folder contains unsolicited spam emails |
| `sms_smish_dt_enron2_ham` | Enron spam benchmark subset 2: ham folder contains verified legitimate business emails |
| `sms_smish_dt_enron2_spam` | Enron spam benchmark subset 2: spam folder contains unsolicited spam emails |
| `sms_smish_dt_enron3_ham` | Enron spam benchmark subset 3: ham folder contains verified legitimate business emails |
| `sms_smish_dt_enron3_spam` | Enron spam benchmark subset 3: spam folder contains unsolicited spam emails |
| `sms_smish_dt_enron4_ham` | Enron spam benchmark subset 4: ham folder contains verified legitimate business emails |
| `sms_smish_dt_enron4_spam` | Enron spam benchmark subset 4: spam folder contains unsolicited spam emails |
| `sms_smish_dt_enron5_ham` | Enron spam benchmark subset 5: ham folder contains verified legitimate business emails |
| `sms_smish_dt_enron5_spam` | Enron spam benchmark subset 5: spam folder contains unsolicited spam emails |
| `sms_smish_dt_enron6_ham` | Enron spam benchmark subset 6: ham folder contains verified legitimate business emails |
| `sms_smish_dt_enron6_spam` | Enron spam benchmark subset 6: spam folder contains unsolicited spam emails |

---

## 6. Known Gaps

The following feeds and datasets were catalogued during initial reconnaissance but are unavailable or omitted by contract:

1. **URLhaus Feed (`urlhaus_feed`)**: Feed endpoint returned HTTP `410 Gone` (feed discontinued / relocated).
2. **PhreshPhish (`phreshphish`)**: Full HTML dump of 732 GB was not downloaded to local environment due to size and scope constraints (HTML DOM content is out of Phase 1 URL threat classification scope).
3. **Kaggle `nikhilchauhan02/indian-social-media-fraud-and-scam-detection-d`**: Kaggle API returned HTTP `403 Client Error: Forbidden` (dataset restricted or deleted by owner).
4. **Network & Android Malware Sets**: Catalogued only in `data/kaggle_sources.csv` (`net/`, `mal/`); reserved for Phase 2 network traffic analysis or offline feature research, excluded from Phase 1 SMS/URL corpora.

---

## 7. Metadata Schema and Allowed Field Values

### Allowed Channel Values

The `channel` attribute identifies the communication surface or origin format of each ingested record:

| Channel | Description | Examples |
|---|---|---|
| `sms` | Short Message Service cellular text messages (P2P and A2P) | `sms_uciml_spam`, `sms_galactus007_smssmishcollection` |
| `job_post` | Online recruitment listings, job descriptions, and hiring advertisements | `sms_aditsawhney_indian_jobs` |
| `call_transcript` | Spoken conversation transcripts from voice fraud or customer service calls | `sms_teeconnie_english_scam`, `sms_sngmyd_india_cyber_scam` |
| `whatsapp` | Instant messaging chats and exports from WhatsApp | `sms_wa1618i_whatsapp_zevanca_1`, `sms_yatinaggarwal033_whatsapp_scam` |
| `telegram` | Broadcast channel and group messages from Telegram | `sms_mexwell_telegram_spam_ham` |
| `email` | Electronic mail messages and RFC 822 documents | `sms_smish_dt_enron1_ham`, `sms_smish_dt_enron1_spam` |
| `web` | Fully qualified web URLs, HTTP/HTTPS resources, and domains | `url_sid321axn_malicious_phish`, `url_alishan07_homograph_phishing` |
| `feed` | Automated threat intelligence feeds and top domain popularity rankings | `url_openphish_feed`, `url_tranco_feed` |

### Allowed Language Codes

| Language Code | Script / Variety | Description | Examples |
|---|---|---|---|
| `en` | Latin | English language messages | `sms_uciml_spam` |
| `hi` | Devanagari | Standard Hindi written in Devanagari script | `sms_roberto2057_hindi_sms` |
| `hinglish` | Latin | Romanised Hindi mixed with English | `sms_hf_bolewara_hinglish_scam`, `sms_hf_ysangam_phonecall_hinglish`, `sms_sngmyd_india_cyber_scam` |
| `bn` | Bengali | Bengali language messages | `sms_smish_dt_banglabarta`, `sms_smish_dt_bangla_spam` |
| `ko` | Hangul | Korean language smishing messages | `sms_smish_dt_kor_phishing` |
| `mixed` | Multilingual | Multi-language benchmark or code-switched entries | `sms_karanverma_punjab_fraud`, `sms_kritikgianta_merged_sms` |
