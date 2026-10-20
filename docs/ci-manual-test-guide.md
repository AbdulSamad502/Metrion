# CI manual test guide

Servers: frontend http://localhost:3000, backend http://localhost:8000, Ollama http://localhost:11434 (must be running, with `qwen2.5vl-manual` for screenshots and `qwen35-4b-q4` for chat).
Pages: CEO Hub `/dashboard/ceo-hub` (the only place you talk to CI), Competitors `/dashboard/competitors` (read-only).
Test screenshots: `Desktop\CI-test-screenshots\` (1 = Better Home bottle ₹279, 2 = Daniel Hechter watch ₹2,299, 3 = same bottle recaptured at ₹249, 4 = a reviews page).

Notes: the CEO's wording for open-ended answers comes from a small local model, so it will vary; the **facts** (numbers, states, what was held or stored) are what you check. A chat turn can take 10-60 s on a local model. Discovery (test 2) makes ONE real Tavily search and counts against the daily cap.

## 0. Start
Sign in at http://localhost:3000, open **CEO Hub**, start a new conversation. Open **Competitors** in a second tab. Expected on a tenant with no CI data: empty states ("Not available"/no competitors), no errors, the two CEO shortcut buttons visible.

## 1. Track by link
| Say | Expect |
|---|---|
| `track https://www.amazon.in/dp/B0F2Y8WFPP called The Better Home 1L` | "Tracking amazon.in/dp/B0F2Y8WFPP." plus "I have no price for a competitor until you send me a screenshot". If you have several products it asks "Which of your products is this competitor for?" — answer `track <same link> for my <product name>`. Competitors page: 1 tracked, price Not available. |
| same message again | "… is already tracked." |
| `track https://www.indiamart.com/x for my <product>` | "I can only track amazon.in, flipkart.com and meesho.com links." Nothing added. |

## 2. Bulk add needs your yes
| Say | Expect |
|---|---|
| `track https://www.amazon.in/dp/B079R9W1B6 and https://www.amazon.in/dp/B0FW5TP5WP for my <product>` | Echo list of both links + the product, "Before I add them, please check them", "Nothing has been added yet". Competitors page unchanged. |
| `yes` | "Tracking …" twice. Page now shows 3 tracked. |
| (repeat bulk with 2 new links, then say `no, only the first`) | Nothing added; the bulk question is not answered by anything but a yes. |

## 3. Discovery (approval card, then leads)
| Say | Expect |
|---|---|
| `find competitors for my <exact product name>` | An **approval card** saying your product's search terms go to Tavily; nothing runs yet. (If it asks which product, name one of yours.) |
| `find competitors for my <same product>` again while the card is open | "That plan is already waiting for your approval above" — no second card. |
| Press **Approve** | Search runs (one Tavily query). Then `show me what you found` lists numbered leads: "A listing on Amazon that looks like a direct competitor…", labelled **search leads, not verified prices**, no prices. |
| `track 1 and 3` | "Now tracking 1, 3. Each has no price yet…". |
| `reject 2` (use a number still listed) | "Rejected 2. I will not show those again…". |
| `track 9` | Nothing happens to your data (no such lead; it is not guessed). |
Edge: `Decline` on a card runs nothing. A card expires after 30 minutes ("Ask again to get a fresh plan").

## 4. Screenshot intake, held until you confirm
Attach `1-better-home-bottle-279.png` with the paperclip and say `this is The Better Home 1L's listing`.
Expect: "I read your screenshot of The Better Home 1L (rating …)", then "I am not using these until you confirm them… price ₹279.00 …". The small model may misread the discount or offers — that is expected and is why this step exists. Competitors page: price status still **Unavailable/Unverified**.
| Say | Expect |
|---|---|
| `price is 279, free delivery, in stock, discount 0` | Your values win. It may say it is still not using the offers until you confirm. |
| `yes` | "Thanks, confirmed… part of your verified competitor data." Page: price **Verified ₹279**, "What a buyer pays" ₹279 after discounts / ₹279 with delivery (free delivery was stated), offers "not counted (needs a card or a condition)". Freshness: Fresh. |
Other intake checks:
- Attach the same image again and say `this is The Better Home 1L` → "I already have exactly this screenshot."
- Attach image 2 and say only `here is a competitor` → asks which tracked competitor it is, stores nothing. Answer `this is <name>` (or track the watch's link first).
- A bare `yes` / `skip` with nothing pending must NOT confirm anything.
- Say `skip` to a fresh confirmation → "I have left those details out, so that screenshot will not be used for prices, comparisons or alerts."

## 5. A cheaper recapture: verified change, finding, alert
Attach `3-better-home-bottle-recapture-249.png`, say `The Better Home 1L again, a new capture from today`, then reply `price is 249, delivery is 40, in stock, discount 0`, then `yes` if it still asks.
Expect: "Thanks, confirmed… Compared with the previous screenshot, the price is down 10.75%." Competitors page: listed ₹249, effective ₹249, with delivery ₹289; one important change; a **Price change** finding; event history shows alert raised and finding created.

## 6. Ask CEO about a finding
On the Competitors page click **Ask CEO** on the price-change finding. Expect the CEO Hub opens with the question pre-filled; the answer says the price dropped from ₹279.00 to ₹249.00 (10.75%), "It rests on 1 screenshot you sent", confidence derived / confirmation confirmed, and "I have not worked out what this means for your margin…". No profit/margin number from CI.

## 7. Reviews
Attach `4-reviews-page.png`, say `these are the reviews of The Better Home 1L`. Expect: "I read the reviews screenshot… themes are saved with how many reviews were read… only what that screenshot showed, not all their reviews." Then ask `what do customers complain about at my competitors`. Expect an answer about complaint themes with the sample size, labelled as a small sample. **Known weak spot:** the small model's themes can be wrong or noisy and are not seller-confirmed; check the page's review insight shows a reviews-read count.

## 8. Monitoring and freshness
| Say | Expect |
|---|---|
| `how are my competitors doing?` | A status from saved evidence only: freshness per competitor, any verified price/stock change, each dated to its screenshot. Competitors with no screenshot are named as having no current evidence ("send a fresh screenshot"). Never "live", "real-time" or "I am tracking". |
| `re-check my competitors` | Same, plus "nothing was fetched". No outside call. |
| `what does Milton Aqua charge today?` (one with no screenshot) | Says it cannot say; asks for a fresh screenshot. No invented price. |
| `should I lower my price?` | No recommendation from CI; it points to the finance side for margin figures. |

## 9. Alert settings
| Say | Expect |
|---|---|
| `set quiet hours 10pm to 7am` | "Quiet hours are now 22:00 to 07:00 India time (IST) …held and shown when it ends… Nothing is dropped." (Your tenant's own timezone is used if it is not India time.) |
| `alert me when a competitor's price changes by more than 5%` | "I will alert you when … 5.00% or more between two of your confirmed screenshots." |
| `alert me when the price changes by 90%` | "I can alert you on price changes between 1% and 50%… Nothing was changed." |
| `set quiet hours 25 to 7` | "I could not read those quiet hours… Nothing was changed." |
| `turn off quiet hours` | "Quiet hours are off." |

## 9b. Held alert (optional, needs a quiet window that contains "now")
Set quiet hours to include the current time, confirm another price change (recapture at a different price), and check the page shows no new alert until the window ends; the housekeeping job releases it (default every 15 minutes) only if the evidence is still recent.

## 10. Stop tracking and restore
| Say | Expect |
|---|---|
| `stop tracking Milton Aqua` | Removed from the Competitors page; history kept. |
| `track https://www.amazon.in/dp/B079R9W1B6` | "…was tracked before; I have started tracking it again with its history." |
| `stop tracking Nobody` | Asks which one / says it is not tracked; nothing removed. |

## 11. Safety and isolation checks
- A second signed-in account (another business) must see **0 competitors, 0 findings** and, asking CEO about your finding id, get "I could not find that finding."
- A seller user without the CEO permission cannot reach the Hub; without CI access the CI actions are refused.
- With Ollama stopped, a screenshot says "I could not read details from that screenshot, so nothing was stored" (nothing half-saved).

## What would be a defect
A price shown as verified before you confirmed it; a competitor price you never gave or confirmed; "free delivery" shown when delivery was not stated; a conditional (card/coupon) offer subtracted from a price; any live/real-time claim; a margin or "you should reprice" statement from CI; data from another account; a number in an answer that is not on the Competitors page.

---

## Update 2026-10-18 (night): phrasings that now work without the small model guessing
Use your product's exact name (`Steel Water Bottle 1L (CI TEST)`) and competitors' names as you gave them. These are answered by CI itself from the same stored results as the Competitors page:

| Say | Expect |
|---|---|
| `Show all competitors tracked for my Steel Water Bottle 1L (CI TEST).` | "You have N competitors on your list for …", each with its price status; "no competitors on your list" when none. |
| `What is the total amount a customer would pay for The Better Home 1L, including delivery and confirmed discounts?` | Listed price, price after confirmed discounts, price with delivery (or why it is not available), offers not counted, and "I do not know what it costs today unless you have sent a newer screenshot". If there is no confirmed screenshot it says it cannot say. |
| `Compare my Steel Water Bottle 1L (CI TEST) at ₹399 with The Better Home 1L. How much cheaper is the competitor?` | The price comparison (no 11-question form). |
| `I have a newer screenshot of The Better Home 1L. Compare it with the previous screenshot...` (nothing attached) | "I do not see a screenshot attached… paperclip…" plus the newest verified change it holds. |
| `Explain this competitor finding...` | Explains the newest finding, or says there are none. |
| `Start tracking The Better Home 1L again for my Steel Water Bottle 1L (CI TEST).` | Restores it with its history. |
| `Yes, confirm the competitor price as ₹279. Keep delivery charges, offers and stock status as unknown.` | The price is used; the three fields you named stay unknown; anything you did not mention (for example the discount) is asked about. Then the page shows the effective price, and the total with delivery as unavailable. |

If a question is open (for example "What does one unit cost you?") you can now ask anything else and it moves on, or say `cancel`.
Discovery now searches for "Steel Water Bottle 1L", not the "(CI TEST)" note. Old junk leads from before are not shown; ask again: `find competitors for my Steel Water Bottle 1L (CI TEST)`.
