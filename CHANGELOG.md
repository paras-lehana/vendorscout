# Changelog — VendorScout

## 2.5 — 2026-06-14 — Live search theater + deterministic RFQ-to-OTP
### Added
- **Live browser in the search itself**: a single lightweight live browser streams the real IndiaMART listings into the search cockpit (panes appear instantly, no empty wait) while TradeIndia leads stream beside it — the "running agentic view", in parallel with the lead fetch, never delaying the report.
- **Deterministic RFQ-to-OTP flow**: "Request quote" opens the real enquiry form, fills mobile/quantity/requirement, auto-handles the one-time buyer-registration step (TradeIndia), clicks through to the **OTP/verification screen, and stops** (confirm-before-send). Mock supplier still demos the full fill→submit.
### Fixed
- Confirm-before-send guard no longer blocks the button that *opens* the enquiry form (it now blocks only OTP/sign-in completion).
- Calmer search: removed the post-report background agent + dual-browser jank.
### Docs
- Refreshed README, deck, and added `docs/SUBMISSION.md` (500-word description + feature list + site tour + local-hosting guide).

## 2.4 — 2026-06-14 — Multi-marketplace + UI overhaul
### Added
- **Multi-marketplace sourcing**: IndiaMART **+ TradeIndia** fetched in parallel, merged & ranked into one agent-curated list; per-vendor source badge, header source chip, filter-by-marketplace, coverage retry. (Flipkart excluded — HTTP 529 bot-block + B2C.)
- **Themes** (5): Aurora/Sunset/Royal/Mono/Light — persisted, carried to /theater + /learn.
- **Report power tools**: sort + filter toolbar, ★ Top pick ribbon, 💰 Cheapest / ⚡ Best value badges, Copy summary, density toggle (2⇄3 col), detail-view match-score ring.
- **Live run**: Plan›Scout›Score›Act phase stepper, progress bar, skeleton loading, motion.
- **Combined session report** prominent (header button), 10–15 pointers.
- **Sessions**: rename (dbl-click) / delete (✕).
### Fixed
- **Ask Q&A** is now stateless (answers from report in request body) — survives redeploys/reloaded sessions.
- **UI frees on REPORT** — input + buttons usable immediately; auto-RFQ runs in background.

## 2.3 — 2026-06-13 — Real-data + evidence + RFQ
- Self-healing Playwright browser; hybrid real-data SCOUT (IndiaMART catalog/SEO + seed).
- Evidence-based relative 9-dimension scoring with honesty enforcement; clickable real sources.
- Runtime Q&A; real-site RFQ (fill & stop at OTP); search-box-free SCOUT; grid/detail/compare report; sample-inspired compact dark UI.

## 2.0 — 2026-06 — Foundation
- Self-hosted Playwright agentic browser (observe→plan→act→verify→recover) on Azure OpenAI gpt-4o; Live Browser Theater; Docker + Traefik deploy.
