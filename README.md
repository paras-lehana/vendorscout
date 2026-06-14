<div align="center">

# 🛰️ VendorScout — The Autonomous Agentic‑Web Procurement Platform

### *You describe what you need. An AI agent browses the live web, vets suppliers, negotiates first contact, and hands you a ranked decision — end to end, while you watch every click.*

**Microsoft Build AI Hackathon · Theme 03 — Agentic Web**
Built on the **Microsoft AI stack**: Azure AI Foundry · Azure OpenAI (GPT‑4o, Computer Use) · Microsoft Agent Framework · Semantic Kernel · AutoGen · Playwright · Model Context Protocol

🔗 **Live:** https://vendorscout.lehana.in  ·  🎬 **Watch it work:** https://vendorscout.lehana.in/theater  ·  📚 **Learn:** https://vendorscout.lehana.in/learn

</div>

---

## ⚡ The 10‑second story

Type *“Hitachi 1.5–2 ton ACs, bulk of 12, best price”* into one chat box. VendorScout's autonomous agent **plans** the sourcing mission, **drives a real browser** across live B2B marketplaces (**IndiaMART + TradeIndia**), **extracts and verifies** suppliers, **scores** them across nine procurement dimensions, **drafts an RFQ** and drives it to the supplier's verification gate, and **recovers on its own** when a page breaks — then returns a ranked, decision‑ready shortlist. You watch every click live. No tabs. No spreadsheets. No hand‑holding.

> This is not a scraper and not a chatbot. It is an **autonomous web agent that gets the job done** — exactly what Theme 03 asks for: *navigate · extract · complete multi‑step transactions · orchestrate across services.*

## 🔥 The problem we destroy

B2B procurement is a **$1.2 trillion** activity still run on human tabs and copy‑paste:

- Analysts spend **60–70%** of their time researching and contacting suppliers.
- A single evaluation takes **2–4 weeks** and costs **$5K–$25K** via consultants.
- **78%** of sourcing decisions are made on incomplete data.

VendorScout collapses **weeks into minutes** — a vetted, contacted shortlist before your coffee is cold.

## 🧠 What VendorScout does (today, live)

| Capability | What the agent does |
|---|---|
| 🧭 **Plans** | Turns a one‑line need into a structured sourcing strategy |
| 🌐 **Navigates** | Drives a real Chromium browser across live marketplaces — **IndiaMART + TradeIndia** — merged into one ranked list |
| 👁️ **Shows its work live** | The **search itself** streams the agent's browser screen while leads fill in beside it — watch it work, on one screen, no scrolling |
| 📋 **Extracts** | Pulls real suppliers, products, prices, locations — not cached data — each with a clickable source link |
| 🛡️ **Vets & scores** | 9‑dimension, evidence‑based scoring with a transparent market price index; **never fabricates** — flags what needs a supplier visit |
| 💬 **Answers questions** | Ask the report follow‑ups in plain English and get grounded answers |
| 🤝 **Transacts** | Opens the supplier's real enquiry form, fills the RFQ, and **drives it to the OTP/verification gate — stopping there** (confirm‑before‑send). A safe demo supplier shows the full fill‑and‑submit |
| 🧩 **Combines** | One consolidated procurement brief across every search in a session |
| ♻️ **Recovers** | When a page changes or a step fails, it re‑reads, re‑plans, and keeps going |
| 🎬 **Theater** | A dedicated “browser theater” replays any mission step‑by‑step with the agent's reasoning |

## 🏗️ Architecture — Microsoft‑native, end to end

```
                          ┌──────────────────────────────────────────────┐
   "Source 12 Hitachi     │                 VendorScout                   │
    1.5‑ton ACs, best     │                                              │
    price"  ───────────▶  │   ┌────────────────────────────────────────┐ │
                          │   │   ORCHESTRATION — Microsoft Agent       │ │
   ChatGPT‑style          │   │   Framework · Magentic · Semantic       │ │
   single‑page UI  ◀────▶ │   │   Kernel · AutoGen                      │ │
   (live theater + SSE)   │   │                                        │ │
                          │   │  Planner → Scout → [Compliance ∥        │ │
                          │   │  Financial ∥ Risk ∥ Authenticity ∥      │ │
                          │   │  Price ∥ Spec] → Analysis(MCDA) →       │ │
                          │   │  ▶ Action(RFQ) → Report                 │ │
                          │   └───────────────┬────────────────────────┘ │
                          │   ┌───────────────▼────────────────────────┐ │
                          │   │   AGENTIC BROWSER                       │ │
                          │   │   observe → plan → act → verify →       │ │
                          │   │   recover                               │ │
                          │   │   Azure OpenAI GPT‑4o (Computer Use,    │ │
                          │   │   vision‑grounded) + Playwright         │ │
                          │   └──────────────┬──────────┬──────────────┘ │
                          │      Azure AI    │          │  MCP tools      │
                          │      Foundry ◀───┘          └──▶ NLWeb / A2A  │
                          └──────────────────────────────────────────────┘
                                  Docker · Traefik · vendorscout.lehana.in
```

**Two nested agent layers:** a *strategic* multi‑agent team (orchestration) and a *tactical* `observe → plan → act → verify → recover` browser loop — the same pattern Azure AI Foundry's Browser Automation Tool is built on.

## 🔷 The Microsoft AI stack (powering every layer)

| Layer | Microsoft technology |
|---|---|
| **Reasoning & vision** | **Azure OpenAI GPT‑4o** in **Azure AI Foundry** — vision‑grounded *Computer Use* control of the browser |
| **Browser automation** | **Playwright** (Microsoft) — the engine behind Foundry's Browser Automation Tool |
| **Agent orchestration** | **Microsoft Agent Framework** with **Magentic** orchestration · **Semantic Kernel** · **AutoGen** |
| **Interoperability** | **Model Context Protocol (MCP)** + **NLWeb** — VendorScout is agent‑ready and agent‑interoperable |
| **Hosting & identity** | **Azure AI Foundry** managed agent hosting · Microsoft Entra |
| **Engineered with** | **GitHub Copilot** (disclosed) |

Every decision the agent makes runs on **Azure OpenAI GPT‑4o**. `GET /health` reports `llm_provider: azure-openai`.

## 🎬 See it / use it (2‑minute tour)

1. **Source something** → https://vendorscout.lehana.in — type *"industrial RO membrane suppliers in India"*. Watch the **live search** (the agent's browser + leads streaming in), then read the ranked report.
2. **Dig in** → click a card for the full **9‑factor breakdown** + source link · tick two to **compare** · **Ask this report** a question · **Request quote** to run a live RFQ · **Combined session report** to merge searches.
3. **Watch a mission** → https://vendorscout.lehana.in/theater — presets include the **full RFQ fill‑and‑submit** on a safe demo supplier, and a **real‑site RFQ** that drives to the OTP gate and stops (confirm‑before‑send).
4. **Learn the method** → https://vendorscout.lehana.in/learn — the nine dimensions + how it works.

## 🚀 Why it wins Theme 03

- **It acts, not just reads.** Most agents stop at extraction; VendorScout completes **transactions** and **orchestrates across services**.
- **Glass‑box autonomy.** A live browser view + transparent MCDA scoring + receipts — the trust procurement teams need.
- **Resilient by design.** A self‑correcting recover loop keeps it going when the real web breaks.
- **Authentically Microsoft‑native.** Azure OpenAI + Playwright + Agent Framework + MCP — the recommended way to build for the open agentic web.
- **Real market, India‑first.** A focused B2B‑sourcing agent for IndiaMART/TradeIndia — a $37.7B sourcing‑tools market.

## 🧪 Run it locally

**Prerequisites:** Python 3.11+, ~2 GB free disk (Chromium), and an **Azure OpenAI** resource with a `gpt-4o` deployment (endpoint, key, deployment name, API version).

```bash
git clone https://github.com/paras-lehana/vendorscout && cd vendorscout

cp .env.example .env          # then set AZURE_OPENAI_ENDPOINT / _API_KEY / _DEPLOYMENT / _API_VERSION

# Option A — Python
pip install -r requirements.txt
playwright install chromium
uvicorn app.main:app --app-dir backend --reload    # → http://localhost:8000

# Option B — Docker (Chromium bundled)
docker compose up --build                           # → http://localhost:8000
```

**Verify:** `http://localhost:8000/health` → `healthy`, `llm_provider: azure-openai`, `browser_agent: ready`, then open `/` and run a search.
No Azure keys? Set `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` for any OpenAI‑compatible endpoint instead (see `.env.example`).

## 🗺️ Roadmap

Continuous vendor monitoring · ERP push (SAP/Coupa) · multi‑marketplace + cross‑border sourcing · Copilot Studio business‑user front door · agent‑to‑agent (A2A) procurement networks.

---

<div align="center">

**Built for the Microsoft Build AI Hackathon — Theme 03, Agentic Web.**
Azure AI Foundry · Azure OpenAI GPT‑4o · Playwright · Microsoft Agent Framework · MCP
*Engineered with GitHub Copilot.*

</div>
