# METRION CMO 3.0 — Complete Plan

> Source: seller-written planning text, converted to Markdown with no features or information added, removed or skipped.

## Table of Contents

1. [Project Description](#1-project-description)
2. [Complete Existing CMO Feature Inventory](#2-complete-existing-cmo-feature-inventory)
3. [Finalized CMO 3.x Upgrades — All 12 Features](#3-finalized-cmo-3x-upgrades--all-12-features)
4. [Personalized News Features (Item 14)](#4-personalized-news-features-item-14)
5. [Mandatory Five-Title Evaluation Design](#5-mandatory-five-title-evaluation-design)
6. [Objective](#6-objective)
7. [Demo Product](#7-demo-product)
8. [PART ONE — Existing CMO Seller Experience](#8-part-one--existing-cmo-seller-experience)
9. [PART TWO — Upgraded CMO 3.x Seller Experience](#9-part-two--upgraded-cmo-3x-seller-experience)
10. [Complete Finalized Upgrade List](#10-complete-finalized-upgrade-list)
11. [What To Produce](#11-what-to-produce)
12. [Strict Instructions](#12-strict-instructions)
13. [Final Objective](#13-final-objective)

---

**Roles:** Act as a Senior E-commerce Product Architect, AI Agent Engineer, QA Tester, and Real Indian Marketplace Seller. Also act as a Senior AI Product Architect, E-commerce Marketplace Specialist, UX Designer and Technical Product Manager.

## 1. Project Description

METRION is an AI-powered e-commerce operating system for Amazon India, Flipkart and Meesho sellers.

The **CEO agent** is the seller-facing orchestrator. The **CMO agent** specializes in product understanding, SEO titles, descriptions, bullet points, keywords, catalog questions and market research.

We want to upgrade CMO from an **AI Listing Writer** into a **Marketplace Listing Intelligence & Optimization System** that understands products, researches keywords and competitors, evaluates listing quality, explains recommendations, and improves listings over time.

First inspect the actual repository, specifications, database, frontend, backend, tests and available running services. Treat documented features as **unverified** until confirmed in code and runtime.

## 2. Complete Existing CMO Feature Inventory

Inspect and verify every feature below:

1. Product image upload, normalization and local Ollama vision analysis.
2. Vision-suggested attributes: color, material, brand, product type and visible text.
3. Vision trust gate, attribute confidence/provenance and seller confirmation.
4. CEO questions for missing product information and persistent seller facts.
5. Five SEO title options per marketplace; the user chooses which marketplace title he wants — one or more.
6. Seller title selection, editing, validation and approval.
7. Full listing generation after separate CEO approval.
8. Standalone descriptions, bullet points and keyword generation.
9. Amazon backend search terms and optional marketing hashtags.
10. Catalog Q&A with attribute basis labels and unknown-value handling.
11. Amazon, Flipkart and Meesho format constraints and deterministic validation.
12. Unsupported-claim prevention and seller-fact grounding.
13. Seven-section source-linked market-trend reports.
14. Niche confirmation and external research approval.
15. CI-informed listing generation — verify whether implemented or only planned.
16. CEO-first routing, specialist delegation, approval cards and result presentation.
17. Read-only CMO dashboard: saved titles, copy packs, hashtags, trends, validation information, search and filters.
18. Saved generations, title approvals, copy/mark-used events and historical retrieval.
19. Tenant isolation, permissions, quotas, idempotency, auditability and recommend-only behavior.
20. Error handling, retries, missing configuration and fail-closed marketplace rules.

**Reporting requirement:** For every item, report one of:

`IMPLEMENTED` / `PARTIAL` / `BLOCKED` / `MISSING` / `NOT VERIFIED`

…with **repository evidence** and **runtime test results**.

## 3. Finalized CMO 3.x Upgrades — All 12 Features

> This is the list of new features to add.

Compare each upgrade with existing functionality and evaluate the required implementation.

| # | Feature | Old CMO | New CMO 3.x |
|---|---|---|---|
| 1 | Smart Product Intelligence | Image hints and confirmed seller facts | Reusable SKU-based product profile, provenance and history |
| 2 | Keyword Intelligence | AI-generated keyword suggestions | Evidence-backed keyword relevance, buyer intent, placement and confidence |
| 3 | Listing Quality Analyzer | Formatting and claim checks | Five-title quality breakdowns and full listing audits |
| 4 | CI + CMO Integration | Planned CI-informed handoff | CEO-authorized structured competitor evidence for differentiation |
| 5 | Advanced Listing Generation | Titles, descriptions, bullets and keywords | Coordinated content based on selected title strategy and buyer needs |
| 6 | Listing History & Optimization | Saved artifacts and usage events | Product-linked snapshots, comparisons, revisions and future performance feedback |
| 7 | Smart Market Opportunities | Source-linked trend reports | Actionable product-specific recommendations |
| 8 | Search Result & Mobile Preview | Text-based title review | Simulated mobile/desktop preview and truncation awareness |
| 9 | Product Image Quality Advisor | Attribute extraction | Image clarity, composition and missing-image recommendations |
| 10 | Product Variant Intelligence | Individual product facts | Shared product families with variant-specific attributes |
| 12 | Buyer Questions & Objection Intelligence | Catalog Q&A | Identify likely buyer concerns, confirm facts and improve content |
| 13 | Listing Readiness Checklist | Format and claim validation | Required blockers, missing facts, optional improvements and next actions |

> **Note on numbering:** The source list jumps from 10 to 12 (no item 11 in the table). It is preserved exactly as written. In Section 10 the same scope is renumbered 1–12, where Product Variant Intelligence is #10, Buyer Questions & Objection Intelligence is #11 and Listing Readiness is #12.

**Exclusions:**

- **Bulk listing is explicitly excluded.**
- **No automatic marketplace publishing.**

## 4. Personalized News Features (Item 14)

> In the source these are numbered 1–5 under item "14".

### 14.1 Personalized Seller News Feed

Instead of showing every e-commerce story, prioritize news relevant to the seller's **products, niches and selected marketplaces**.

**Example:** An AquaNest seller sees reusable-bottle trends, Amazon India listing-policy changes and relevant packaging developments — not unrelated fashion-market news.

### 14.2 Marketplace Policy & Seller Alerts

Highlight **verified** changes to Amazon, Flipkart or Meesho policies that could affect listings, images, restricted claims or seller operations.

- An **official marketplace source** should be preferred.
- News articles alone should **not** change CMO's enforcement rules.

### 14.3 News-to-Action Recommendations

Turn a supported finding into a suggested task.

**Example:** "Research suggests increased interest in reusable drinkware. Would you like CMO to review whether your current listing clearly communicates its reusable design?"

The seller must approve any listing changes.

### 14.4 News Follow-up & Change Tracking

When a seller revisits a topic, show:

- what's new since the previous report,
- what's unchanged,
- and whether earlier claims were corrected.

This prevents repeating old headlines as fresh intelligence.

### 14.5 Ask Questions About Any News Story

**Seller:** "Does this news affect my water bottle?"

CEO asks CMO to explain the story in relation to the seller's product and marketplace, with links to the original evidence.

This makes the news experience conversational rather than a static report.

### Example — How CMO News Should Look

**Illustrative News Insight — Hypothetical**

| Field | Value |
|---|---|
| Topic / Marketplace | Reusable Drinkware · Amazon India |
| Headline | Growing buyer attention toward reusable water bottles |
| Disclaimer | Example scenario only. No live news source has been verified for this demonstration. |
| Product relevance | High (demo) |
| Evidence confidence | Not assessed |
| Why it may matter | AquaNest is a reusable water bottle, so this topic is directly related to the product category. |
| Suggested action | Review whether the existing title and bullets communicate the confirmed reusable feature clearly. |

A real report would include the **source, publication date, evidence assessment** and **whether the recommendation is supported**.

> **Scoring rule:** Do **not** add an arbitrary "market opportunity 95/100" score. News relevance can be estimated, but business impact and actual demand should not be invented.

## 5. Mandatory Five-Title Evaluation Design

When the seller asks for titles:

1. Understand uploaded images and seller-confirmed facts.
2. Retrieve existing product data when available.
3. Research relevant keywords and authorized CI evidence.
4. Generate **five meaningfully different title strategies**.
5. Evaluate each title for **keyword relevance, buyer intent, market positioning and readability**.
6. Show **explainable scores, supporting evidence, confidence and a recommendation**.
7. Treat **unsupported claims** and **verified marketplace-rule violations** as **hard failures**.
8. Show `NOT_ASSESSED` when evidence is insufficient; **never fabricate metrics**.
9. Let the seller **select or edit** any valid title.
10. Obtain **separate CEO approval** before generating the complete listing.
11. Generate and audit descriptions, bullets, keywords and backend terms.
12. Save approved versions and their strategy for future comparison.

**Limitation:** Do not present internal quality scores as Amazon SEO rankings, actual search volume, conversion rates or sales predictions.

---

## 6. Objective

I want you to understand the complete vision for METRION CMO, compare it with our existing CMO implementation, and prepare a detailed, easy-to-understand product overview for both my development team and business partner.

METRION is an AI-powered e-commerce operating system for Amazon India, Flipkart and Meesho sellers.

The **CEO agent** is the seller-facing assistant. The **CMO agent** is a specialist that works through CEO to understand products, create listings, generate keywords, analyze market trends and improve product content.

Our goal is to transform CMO from an **AI Listing Writer** into an **AI Marketplace Listing Intelligence & Optimization System**.

**Important:** The conversations below are fictional examples showing the intended seller experience. They are **not evidence** that a feature is implemented.

First inspect the actual repository and identify which capabilities exist. **Do not implement or change code yet.**

## 7. Demo Product

Use the following fictional seller product throughout the entire explanation.

| Attribute | Value |
|---|---|
| Brand | AquaNest |
| Product | Stainless Steel Water Bottle |
| Capacity | 1 litre |
| Material | Stainless steel |
| Color | Silver |
| Reusable | Yes |
| Marketplaces | Amazon India, Flipkart and Meesho |
| Insulated | Not confirmed |
| Leakproof | Not confirmed |
| Dishwasher safe | Unknown |

These are seller-provided demo facts. Do not invent certifications, specifications or performance claims.

## 8. PART ONE — Existing CMO Seller Experience

Explain the current CMO experience using the following complete conversation.

### Scene 1 — Image Understanding & Product Facts

**Seller:** "Hi CEO, I have a water bottle that I want to sell on Amazon. I'm uploading its picture. Can you help me create a professional listing?"

**CEO:** "Certainly. I'll ask CMO to analyze your image and identify visible product details. Please confirm the information before we use it."

**CEO:** "The image appears to show a silver-colored bottle. What's its brand, material and capacity?"

**Seller:** "My brand is AquaNest. It's a 1-litre stainless steel bottle, silver in color and reusable."

**CEO:** "Is it insulated or leakproof?"

**Seller:** "I haven't tested those features. Don't mention them."

**CEO:** "Understood. CMO will use only confirmed details and exclude unsupported claims."

**Features:** Image upload, Ollama vision, attribute extraction, uncertainty, seller confirmation, persistent facts, provenance and unsupported-claim prevention.

### Scene 2 — Five SEO Titles & Seller Approval

**Seller:** "CEO, now create five SEO titles for Amazon India."

**CEO:** "I'll request five title options from CMO using your confirmed product facts. Please approve the plan."

**Seller:** "Approved."

**CMO — Example Titles:**

1. AquaNest Stainless Steel Water Bottle 1 Litre, Silver, Reusable Bottle for Daily Use
2. AquaNest 1L Stainless Steel Drinking Water Bottle, Silver, Reusable Design
3. AquaNest Reusable Stainless Steel Water Bottle, 1 Litre Capacity, Silver
4. AquaNest Silver Steel Water Bottle, 1 Litre, for Everyday Drinking Water
5. AquaNest Stainless Steel Bottle for Drinking Water, 1L Capacity, Silver

**Seller:** "I like option one. Can you move '1 Litre' earlier?"

**CEO:** "Revised title: AquaNest 1 Litre Stainless Steel Water Bottle, Silver, Reusable Bottle for Daily Use. Would you like to approve it?"

**Seller:** "Yes, approve this title."

**Features:** CEO plan approval, five titles, editing, marketplace validation, title selection and seller approval.

### Scene 3 — Complete Listing Generation

**Seller:** "Now generate my description, bullet points, keywords and backend terms."

**CEO:** "I'll ask CMO to prepare the complete listing pack using your approved title. Please approve this separate generation plan."

**Seller:** "Approved."

**CMO — Example Listing:**

**Title:** AquaNest 1 Litre Stainless Steel Water Bottle, Silver, Reusable Bottle for Daily Use

**Bullet Points:**

- 1 Litre Capacity: Holds up to 1 litre of water.
- Stainless Steel Material: Made using seller-confirmed stainless steel.
- Reusable Bottle: Intended for repeated everyday use.
- Silver Color: Features a simple silver-colored appearance.
- Everyday Drinking Water: Suitable for regular drinking-water needs.

**Description:**

> The AquaNest Stainless Steel Water Bottle combines a 1-litre capacity with a reusable design. Made from stainless steel and finished in silver, it provides a straightforward option for carrying drinking water during everyday activities.

**Keywords:** stainless steel water bottle, 1 litre water bottle, reusable steel bottle, silver water bottle.

**Backend Terms:** steel drinking bottle reusable silver 1 litre water container.

**Hashtags:** #AquaNest #ReusableWaterBottle #StainlessSteelBottle #DailyHydration.

**Features:** Full listing generation, standalone descriptions, bullets, keywords, backend search terms, hashtags and separate seller approval.

### Scene 4 — Standalone Editing & Catalog Q&A

**Seller:** "CEO, improve only my third bullet point. Don't regenerate the entire listing."

**CEO:** "Proposed revision: Reusable for Everyday Use — Designed for repeated use as part of your daily drinking-water routine."

**Seller:** "Good. Also, is my bottle dishwasher safe?"

**CEO:** "That information hasn't been confirmed. I won't include the claim without reliable product information."

**Features:** Standalone revisions, catalog questions, confirmed facts and unknown-value handling.

### Scene 5 — Multiple Marketplaces

**Seller:** "I also want to sell this bottle on Flipkart and Meesho. Can you create separate listings?"

**CEO:** "Yes. CMO will generate marketplace-specific content under the configured rules, with the necessary approvals."

- **Example Flipkart Title:** AquaNest Stainless Steel Water Bottle, 1 Litre, Silver, Reusable.
- **Example Meesho Title:** AquaNest 1 Litre Silver Stainless Steel Water Bottle.

**Features:** Marketplace selection, Amazon/Flipkart/Meesho differences, format constraints and validations.

### Scene 6 — Market Trend Research

**Seller:** "CEO, research current trends for reusable stainless steel water bottles."

**CEO:** "Please confirm the niche: reusable stainless steel water bottles in India. I'll preview the research request and ask for approval."

**Seller:** "Yes, approved."

**CEO:** "CMO will prepare a seven-section source-linked report covering market attention, relevant news, seller tactics, product buzz, adjacent opportunities, interpretation and evidence."

*No live trend findings or sources are provided in this example.*

**Features:** Niche confirmation, research approval, source-linked trends and evidence limitations.

### Scene 7 — Saved History & Dashboard

**Seller:** "Show my previously selected Amazon title and description."

**CEO:** "Your selected title was: AquaNest 1 Litre Stainless Steel Water Bottle, Silver, Reusable Bottle for Daily Use."

**Seller:** "If I copy a title or mark it used, does that mean it was published on Amazon?"

**CEO:** "No. Copying or marking it used records an action in Metrion. It does not prove marketplace publication."

**Features:** Saved generations, approvals, copy/mark-used events, historical retrieval and read-only CMO dashboard.

### Existing System Safeguards (also cover)

- Tenant isolation
- Quotas
- Idempotency
- Cancellation
- Retries
- Error handling
- Stale marketplace configurations
- Recommend-only behavior

## 9. PART TWO — Upgraded CMO 3.x Seller Experience

Now demonstrate the same seller returning after the proposed CMO upgrade.

### Scene 8 — Smart Product Memory, Keywords & CI

**Seller:** "Hi CEO, remember my AquaNest bottle? I want to improve its Amazon listing. First, research relevant keywords and tell me what competitors are emphasizing."

**CEO:** "I found your saved product profile: AquaNest, stainless steel, 1 litre, silver and reusable. I'll request keyword research and authorized competitor intelligence."

**Seller:** "Approved. Explain the results simply."

**CMO — Illustrative Keyword Candidates:**

| Keyword | Intended use |
|---|---|
| Stainless steel water bottle | Primary title keyword |
| 1 litre water bottle | Capacity-related keyword |
| Reusable water bottle | Supporting term |
| Insulated water bottle | Excluded — unconfirmed |

Keyword volume, actual demand and competitor occurrence must remain **unassessed** unless supported by real evidence.

**Upgrades:** Smart Product Intelligence, Keyword Intelligence and CI-to-CEO-to-CMO integration.

### Scene 9 — Five Title Strategies & Quality Analyzer

**Seller:** "Generate five different title strategies. Show keyword relevance, buyer intent, positioning and readability scores."

**CMO — Illustrative Title Comparison:**

1. **Search Coverage — 90/100**
   AquaNest 1 Litre Stainless Steel Water Bottle, Silver, Reusable Bottle for Daily Use
2. **Buyer Intent — 91/100**
   AquaNest Stainless Steel Water Bottle 1L for Everyday Drinking Water, Silver
3. **Feature Focus — 89/100**
   AquaNest Reusable Stainless Steel Water Bottle, 1 Litre Capacity, Silver
4. **Short & Clear — 86/100**
   AquaNest Stainless Steel Water Bottle 1 Litre, Silver
5. **Balanced SEO — 93/100**
   AquaNest 1L Stainless Steel Water Bottle, Reusable, Silver, for Daily Use

For every title, the future CMO must explain:

- Keyword relevance.
- Buyer search intent.
- Market positioning.
- Readability.
- Strengths and weaknesses.
- Supporting evidence and confidence.
- Product fact accuracy.
- Marketplace-rule compliance.

These example scores are **fictional**. Real scoring requires a documented methodology; missing dimensions must be marked `NOT_ASSESSED`, not invented. Unsupported claims and marketplace-rule violations are **hard failures**.

**Seller:** "I choose option five. Can you show me a mobile preview?"

**CEO:** "I'll display a simulated mobile search-result preview so you can check readability and possible truncation. Actual marketplace display may differ."

**Upgrades:** Five-Title Quality Analyzer and Search Result & Mobile Preview.

### Scene 10 — Buyer Questions & Image Quality

**Seller:** "Before finalizing, what questions might customers ask about my bottle?"

**CEO:** "They may ask whether it's insulated, leakproof or dishwasher safe. These are questions to investigate, not confirmed product claims."

**Seller:** "Don't include unverified claims. Also, check my product image quality."

**CEO:** "CMO can evaluate image clarity, composition, visible details and possible missing product photos. A real image assessment requires the actual uploaded images."

**Upgrades:** Buyer Questions & Objection Intelligence and Product Image Quality Advisor.

### Scene 11 — Advanced Listing Generation & Readiness Audit

**Seller:** "I approve title option five. Generate my complete listing and tell me if it's ready."

**CEO:** "I'll request separate approval for complete listing generation, then CMO will generate a strategy-aligned listing and perform an audit."

**Seller:** "Approved."

**Proposed Readiness Checklist:**

- Confirmed brand, material, capacity and color.
- Unsupported insulation and leakproof claims excluded.
- Keyword evidence not available in this demo.
- Marketplace-specific validation not executed in this demo.
- Image-quality assessment pending actual image analysis.

**Status:** Draft generated; final marketplace readiness not verified.

The complete listing should include the selected title, coherent bullets, description, keyword placement and backend terms, followed by a full quality audit.

**Upgrades:** Advanced Listing Generation, Full Listing Quality Audit and Listing Readiness Checklist.

### Scene 12 — Product Variant Intelligence

**Seller:** "I also sell 500ml and 750ml versions. Can you create their listings without mixing the capacities?"

**CEO:** "CMO can maintain a product family while keeping variant-specific facts separate. Do the new variants share the same brand, material and color?"

**Seller:** "Yes. Both are AquaNest, silver and stainless steel. Only the capacities differ."

**CEO:** "I'll record those as separate confirmed variants and generate appropriately differentiated listings."

**Upgrade:** Product Variant Intelligence.

### Scene 13 — Listing History & Optimization

**Seller:** "Compare my old Amazon title with the new one. What improved?"

**CEO:**

- **Old:** AquaNest 1 Litre Stainless Steel Water Bottle, Silver, Reusable Bottle for Daily Use.
- **New:** AquaNest 1L Stainless Steel Water Bottle, Reusable, Silver, for Daily Use.

"The new version is slightly shorter while preserving the main product details. CMO can store both versions and explain the changes."

**Seller:** "Has this improved my Amazon sales?"

**CEO:** "I can't determine that from the title alone. We would need actual marketplace performance data from comparable periods."

**Upgrade:** Listing History, Version Comparison and Evidence-Based Optimization.

### Scene 14 — Smart Market Opportunities

**Seller:** "Based on current research, what opportunities should I consider for my bottle listing?"

**CEO:** "CMO can connect verified market findings to your product and recommend relevant changes. For example, if supported research identifies buyer interest in reusable products, CMO may recommend improving that messaging. This example is hypothetical until actual evidence is available."

**Upgrade:** Smart Market Opportunities.

## 10. Complete Finalized Upgrade List

The final scope contains **12 upgrades**:

1. Smart Product Intelligence.
2. Evidence-Based Keyword Intelligence.
3. Five-Title Scoring & Full Listing Quality Analyzer.
4. CI + CMO Competitor Intelligence.
5. Advanced Listing Generation.
6. Listing History & Optimization.
7. Smart Market Opportunities.
8. Search Result & Mobile Preview.
9. Product Image Quality Advisor.
10. Product Variant Intelligence.
11. Buyer Questions & Objection Intelligence.
12. Listing Readiness & Missing Information Checklist.

**Out of scope:** Do **not** add Bulk Listing, automatic marketplace publishing or Language & Audience Adaptation to this finalized scope.

## 11. What To Produce

Using the repository and these fictional conversations, prepare:

- **A. Current CMO Overview:** Explain the existing architecture, seller workflow and verified capabilities.
- **B. Complete Existing Feature Inventory:** Include image understanding, confirmed facts, titles, approvals, descriptions, bullets, keywords, backend terms, hashtags, catalog Q&A, marketplace rules, trends, dashboard, history, security and error handling.
- **C. Old vs New Feature Comparison:** Compare every one of the 12 upgrades with the existing behavior and explain the seller benefit.
- **D. Complete Seller Conversation:** Present the old and new journeys as readable Seller → CEO → CMO → CEO conversations, including seller answers, approvals, title selections and example outputs. Use the conversations above as the reference, but make the transitions natural.
- **E. Five-Title Quality Analyzer Design:** Explain the title strategies, assessment dimensions, evidence requirements, validation gates, scoring limitations and seller-selection experience.
- **F. Full Listing Workflow:** Explain how an approved title becomes a coordinated listing pack and how CMO evaluates its readiness.
- **G. Architecture & Development Gaps:** Identify existing reusable components, missing functionality, required API/database/UI changes and CI integration needs.
- **H. Phased Roadmap:** Phase 0 stabilization, CMO 3.0 core intelligence, and CMO 3.1 product history, variants and optimization.
- **I. Partner-Friendly Summary:** Explain the business value in simple language, using the AquaNest example.
- **J. Feature Coverage Matrix:** Account for every existing feature and all 12 upgrades, so nothing is missed.

## 12. Strict Instructions

- First inspect the real repository; do not assume the fictional demo represents implemented functionality.
- Keep actual implementation findings separate from proposed product behavior.
- The seller interacts with CEO; CEO delegates to CMO.
- Preserve seller approvals and fact confirmation.
- Show actual example titles, bullets, descriptions and keyword suggestions where relevant.
- Never invent research sources, search volumes, sales results or marketplace compliance.
- Treat marketplace accuracy and product-claim validity as mandatory gates.
- Keep copied, approved and marketplace-live statuses separate.
- Do not add bulk listing or automatic publishing.
- Do not change code or implement features yet.
- Make the final document detailed enough for engineering planning but understandable to a business partner.

## 13. Final Objective

Clearly show how the existing Metrion CMO works, what changes in CMO 3.x, and how a real seller would experience every feature through the CEO agent. Use the complete AquaNest conversation as the primary demonstration, and do not skip any feature.
