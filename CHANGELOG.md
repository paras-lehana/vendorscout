# Changelog — VendorScout

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
