# ============================================================
# VendorScout - Action Agent (multi-step web transactions)
# ============================================================
# The headline "Agentic Web" capability: VendorScout doesn't just research
# vendors — it ACTS. For the top-ranked shortlist, the Action agent uses the
# self-hosted agentic browser to open each supplier's "Send Enquiry / Contact
# Supplier" form, fill it with the buyer's RFQ, and submit it — then verifies a
# success/acknowledgement state and captures a receipt.
#
# Safety: real submits are gated by BROWSER_ALLOW_AUTOSUBMIT (confirm-before-send).
# In production the agent fills the form and stops at "ready_to_send"; only a
# seeded demo account auto-submits for a clean video.
# ============================================================

import asyncio
import logging
from typing import Optional

from app.agents.base import BaseAgent
from app.config import settings

logger = logging.getLogger(__name__)


def _rfq_goal(vendor: dict, rfq: dict, buyer: dict, autosubmit: bool) -> str:
    """Build the natural-language transaction goal for the agentic browser."""
    submit_clause = (
        "After filling every field, SUBMIT the enquiry form. Then VERIFY a success / "
        "thank-you / acknowledgement state appeared and extract any reference or "
        "acknowledgement text."
        if autosubmit else
        "Fill every field but DO NOT click the final submit button — stop once the form "
        "is fully filled and ready, and report status 'ready_to_send' with a screenshot."
    )
    return f"""You are on a B2B supplier's page for "{vendor.get('company_name','this supplier')}".
GOAL: send a Request-for-Quote (RFQ) enquiry to this supplier.

Steps:
1. Find and open the "Send Enquiry" / "Contact Supplier" / "Get Best Quote" / contact form
   (it may be a button, a modal, or a section lower on the page — scroll if needed).
2. Fill the enquiry/RFQ with these details (use null / skip fields the form doesn't have;
   never invent data):
   - Product / requirement: {rfq.get('product','')}
   - Quantity: {rfq.get('quantity','')}
   - Target price: {rfq.get('target_price','')}
   - Message: {rfq.get('message','')}
   - Buyer name: {buyer.get('name','')}
   - Buyer email: {buyer.get('email','')}
   - Buyer phone: {buyer.get('phone','')}
   - Buyer company / city: {buyer.get('company','')} / {buyer.get('city','')}
3. {submit_clause}

Return JSON: {{ "form_found": bool, "fields_filled": [..], "submitted": bool,
"status": "submitted"|"ready_to_send"|"no_form_found"|"failed", "reference": str|null }}.
If you cannot find a form after a reasonable look, set status 'no_form_found' and stop.
"""


class ActionAgent(BaseAgent):
    """Completes RFQ/enquiry transactions on shortlisted suppliers' pages."""

    name = "action"
    description = "Sending RFQ enquiries to shortlisted suppliers"

    async def execute(self, state: dict, job_id: str) -> dict:
        vendors = self._shortlist(state)
        if not vendors:
            await self.log_activity(job_id, "running", "No shortlisted vendors to contact — skipping outreach")
            return {"actions": [], "_findings_count": 0}

        autosubmit = bool(settings.BROWSER_ALLOW_AUTOSUBMIT)
        rfq = self._build_rfq(state)
        buyer = self._buyer_profile(state)

        mode = "auto-submit (demo)" if autosubmit else "confirm-before-send"
        await self.log_activity(
            job_id, "running",
            f"Preparing RFQ enquiries for {len(vendors)} shortlisted suppliers ({mode})"
        )

        actions: list[dict] = []
        sent = 0
        for i, vendor in enumerate(vendors):
            name = vendor.get("company_name", "Unknown")
            website = vendor.get("website", "")
            if not website:
                continue

            await self.log_activity(
                job_id, "running", f"Outreach [{i+1}/{len(vendors)}]: {name}"
            )

            async def _emit(event: dict):
                # Surface live browser frames + steps to the SSE stream for this job.
                event = {**event, "agent": self.name, "vendor": name}
                await self.log_activity(
                    job_id, "running",
                    event.get("message") or f"{self.name}: {event.get('type','step')}",
                    details={"frame": event} if event.get("screenshot") else None,
                )

            try:
                result = await self.browser.run_task_streaming(
                    url=website,
                    goal=_rfq_goal(vendor, rfq, buyer, autosubmit),
                    on_update=_emit,
                    timeout=180,
                    allow_submit=autosubmit,  # confirm-before-send: only submit when enabled
                )
                data = result.extracted_data if isinstance(result.extracted_data, dict) else {}
                status = data.get("status") or ("submitted" if result.success else "failed")
                receipt = {
                    "vendor": name,
                    "website": website,
                    "status": status,
                    "submitted": bool(data.get("submitted")) or (status == "submitted"),
                    "reference": data.get("reference"),
                    "steps": result.num_steps,
                    "run_id": result.run_id,
                    "rfq": rfq,
                }
                actions.append(receipt)
                if receipt["submitted"]:
                    sent += 1
                await self._record(job_id, receipt)
            except Exception as e:  # noqa: BLE001 — one vendor failing must not kill outreach
                logger.error("action agent failed for %s: %s", name, e)
                actions.append({"vendor": name, "website": website,
                                "status": "failed", "error": str(e)})
            await asyncio.sleep(0.2)

        verb = "sent" if autosubmit else "prepared (awaiting confirmation)"
        await self.log_activity(
            job_id, "running",
            f"Outreach complete: {sent if autosubmit else len(actions)} RFQ enquiries {verb}",
            findings_count=sent,
        )
        return {"actions": actions, "_findings_count": sent}

    # ---- helpers ------------------------------------------------------------

    def _shortlist(self, state: dict, top_n: int = 3) -> list[dict]:
        """Pick the top-N vendors to contact: prefer the analysis ranking,
        else fall back to discovered vendors."""
        ranked = state.get("ranked_vendors") or state.get("rankings")
        if isinstance(ranked, list) and ranked:
            vendors = []
            for r in ranked[:top_n]:
                # ranking rows may embed the vendor or just reference it
                v = r.get("vendor") if isinstance(r, dict) and "vendor" in r else r
                if isinstance(v, dict):
                    vendors.append(v)
            if vendors:
                return vendors
        vendors = state.get("vendors", []) or []
        # If vendors carry a score, sort desc; else keep discovery order.
        try:
            vendors = sorted(vendors, key=lambda v: v.get("score", 0), reverse=True)
        except Exception:
            pass
        return vendors[:top_n]

    def _build_rfq(self, state: dict) -> dict:
        req = state.get("requirements") or state.get("parsed_requirements") or {}
        return {
            "product": req.get("product") or req.get("product_service") or state.get("query", ""),
            "quantity": req.get("quantity") or req.get("capacity") or "as per requirement",
            "target_price": req.get("budget") or req.get("target_price") or "best market price",
            "message": (
                "We are evaluating suppliers and would like your best quote, MOQ, lead time, "
                "and applicable certifications. Please share a proforma if possible."
            ),
        }

    def _buyer_profile(self, state: dict) -> dict:
        # In production this comes from the signed-in buyer; demo uses a safe default.
        buyer = state.get("buyer") or {}
        return {
            "name": buyer.get("name", "VendorScout Buyer"),
            "email": buyer.get("email", "sourcing@vendorscout.demo"),
            "phone": buyer.get("phone", ""),
            "company": buyer.get("company", "VendorScout"),
            "city": buyer.get("city", ""),
        }

    async def _record(self, job_id: str, receipt: dict):
        """Persist the transaction receipt if the DB supports it (decoupled —
        works before the agent_actions migration ships)."""
        try:
            from app import database as db
            fn = getattr(db, "record_agent_action", None)
            if callable(fn):
                await fn(job_id=job_id, **receipt)
        except Exception as e:  # noqa: BLE001
            logger.debug("action receipt not persisted (db helper missing): %s", e)
