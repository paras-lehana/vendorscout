<div align="center">

# 🛰️ VendorScout — The Autonomous Agentic‑Web Procurement Platform

### *You describe what you need. An AI agent browses the live web, vets suppliers, negotiates first contact, and hands you a ranked decision — end to end, while you watch every click.*

**Microsoft Build AI Hackathon · Theme 03 — Agentic Web**
Built on the **Microsoft AI stack**: Azure AI Foundry · Azure OpenAI (GPT‑4o, Computer Use) · Microsoft Agent Framework · Semantic Kernel · AutoGen · Playwright · Model Context Protocol

🔗 **Live:** https://vendorscout.lehana.in  ·  🎬 **Watch it work:** https://vendorscout.lehana.in/theater  ·  📚 **Learn:** https://vendorscout.lehana.in/learn

</div>

---

## ⚡ The 10‑second story

Type *“Hitachi 1.5–2 ton ACs, bulk of 12, best price”* into one chat box. VendorScout's autonomous agent **plans** the sourcing mission, **drives a real browser** across live B2B marketplaces, **extracts and verifies** suppliers, **scores** them across nine procurement dimensions, **sends RFQ enquiries** on your behalf, and **recovers on its own** when a page breaks — then returns a ranked, decision‑ready shortlist. No tabs. No spreadsheets. No hand‑holding.

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
| 🌐 **Navigates** | Drives a real Chromium browser across live marketplaces (IndiaMART, TradeIndia, the open web) |
| 📋 **Extracts** | Pulls real suppliers, products, prices, certifications, locations — not cached data |
| 🛡️ **Vets** | Scores compliance, financial health, risk, authenticity, reputation, capability |
| 💸 **Compares** | 9‑dimension Multi‑Criteria Decision Analysis with a transparent market price index |
| 🤝 **Transacts** | Opens supplier enquiry forms, fills the RFQ, and **submits** it — with a confirm‑before‑send safety gate |
| 🔗 **Orchestrates** | Coordinates discovery, vetting, outreach and notification across multiple services |
| ♻️ **Recovers** | When a page changes or a step fails, it re‑reads, re‑plans, and keeps going |
| 👁️ **Shows its work** | A live “browser theater” streams the agent's screen + its reasoning, step by step |

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

## 🎬 See it / use it

- **Source something:** https://vendorscout.lehana.in — one chat box, ranked report inline.
- **Watch the agent browse live:** https://vendorscout.lehana.in/theater
- **Live RFQ transaction:** the *“Send an RFQ”* mission fills & submits a supplier enquiry on camera (confirm‑before‑send).
- **Learn the method:** https://vendorscout.lehana.in/learn

## 🚀 Why it wins Theme 03

- **It acts, not just reads.** Most agents stop at extraction; VendorScout completes **transactions** and **orchestrates across services**.
- **Glass‑box autonomy.** A live browser view + transparent MCDA scoring + receipts — the trust procurement teams need.
- **Resilient by design.** A self‑correcting recover loop keeps it going when the real web breaks.
- **Authentically Microsoft‑native.** Azure OpenAI + Playwright + Agent Framework + MCP — the recommended way to build for the open agentic web.
- **Real market, India‑first.** A focused B2B‑sourcing agent for IndiaMART/TradeIndia — a $37.7B sourcing‑tools market.

## 🧪 Run it locally

```bash
git clone https://github.com/paras-lehana/vendorscout && cd vendorscout
cp .env.example .env          # add AZURE_OPENAI_* values
pip install -r requirements.txt
playwright install chromium
uvicorn app.main:app --app-dir backend --reload   # → http://localhost:8000
# or: docker compose up --build
```

## 🗺️ Roadmap

Continuous vendor monitoring · ERP push (SAP/Coupa) · multi‑marketplace + cross‑border sourcing · Copilot Studio business‑user front door · agent‑to‑agent (A2A) procurement networks.

---

<div align="center">

**Built for the Microsoft Build AI Hackathon — Theme 03, Agentic Web.**
Azure AI Foundry · Azure OpenAI GPT‑4o · Playwright · Microsoft Agent Framework · MCP
*Engineered with GitHub Copilot.*

</div>
