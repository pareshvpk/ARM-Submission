# PS3 Sentinel UI redesign (Figma), 2026-11-07

Figma file: https://www.figma.com/design/2NEl8jhrQy4CnqK2gVgdSp (drafts of the user's Starter team).

References studied (mood only, nothing copied): Dribbble "AI Cyber Mentor App UI/UX Concept" (Tajkim Masum) —
near-black with a deep-red top glow, glass cards, pill chips, red pill CTA, floating pill nav; Dribbble "Banking App,
Fintech App" (Conceptzilla) — charcoal panels, glossy red 3D object hero, red primary + grey secondary pills.

Decisions (user, 2026-11-07): audience = everyday Indian phone users; red is reserved for danger, brand accent is a
cool periwinkle; screens = onboarding, privacy, home, lock-screen alert, results (scam, suspicious, safe, not checked).
Signature move: the top glow takes the verdict colour (red scam, amber suspicious, green safe, grey not checked,
blue brand screens), so a safe result never looks alarming. Colour is never the only signal: every verdict pill has its
own icon and word.

## Tokens (Figma variable collection "Sentinel", mode Dark)
color/bg #0A0B0F · surface #15171D · surface-2 #1C1F27 · surface-glass #FFFFFF 5 % · stroke #FFFFFF 9 % ·
text #F3F4F6 · text-2 #A3A7B3 · text-3 #6B7080 · brand #7C9CFF · brand-deep #1B2A6B · on-accent #0A0B0F ·
danger #FF4057 · danger-deep #7A0C1C · warn #F6B23C · warn-deep #5C3A06 · safe #3DD68C · safe-deep #0B4A2E.
space 4/8/12/16/20/24/32 · radius pill 999, card 24, tile 18, sm 12.
Type: Space Grotesk (Display XL 40/44, Display L 30/34, Heading M 20/26), Inter (Body L 16/24, Body M 14/21,
Label M 14/18 semibold, Label S 12/16 medium), JetBrains Mono (Mono M 13/18, Mono S 11/14) for links and timings.
Glow layers use hardcoded radial gradients (Figma cannot bind gradient stops to variables in this flow).

## Components (page "Components")
22 icon components (Lucide, MIT) with strokes bound to color/text; StatusBar; Button (Primary, Secondary, Danger;
text property Label); Chip (Neutral, Brand, Danger, Warn, Safe; Label); VerdictBadge (High "HIGH RISK", Medium
"SUSPICIOUS", Low "LOOKS SAFE", Unchecked "NOT CHECKED"); NavPill (Home, History, Settings).

## Screens (page "Screens", 360 x 800)
Built: 01 Onboarding (glossy 3D shield hero), 02 Privacy (no internet permission, on-device models, encrypted store,
real permission list), 03 Home (status card, model chips, check-a-message card, recent checks, floating nav),
04 Lock-screen alert (public notification only: "Possible scam message · Tap to inspect", sender hidden),
05 Result · Scam (risk meter 1.00, cue highlights, fake-bank-link row, three Llama steps, measured timings
"Detect 478 ms · first word 2.0 s" from bench/results/f14_final_sms_20261107_run2), 06 Result · Suspicious.
Not built (Figma Starter MCP tool-call limit reached): 07 Result · Looks safe, 08 Result · Not checked. The build
script for both is in `figma_screens_07_08.js` next to this file; run it with the Figma MCP `use_figma` tool when
the limit resets or the plan allows (file key 2NEl8jhrQy4CnqK2gVgdSp), then take one screenshot of page Screens.

Copy rules kept: no invented metrics (all numbers are measured or sample message content), no italic headings,
plain words, the "not checked" text matches the app string `models_still_loading`.
