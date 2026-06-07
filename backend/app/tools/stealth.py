# ============================================================
# VendorScout - Browser stealth / fingerprint masking
# ============================================================
# Ported from parse.lehana.in's puppeteer_scraper_v2.mjs
# (buildMaskedUserAgent / applyBrowserFingerprint) to Playwright (Microsoft).
#
# Purpose: make our headless Chromium look like an ordinary desktop browser
# so public B2B pages don't serve us a false-positive bot wall. This is NOT
# credential stuffing or paywall bypass — we only act on public pages and
# public enquiry forms.
# ============================================================

from urllib.parse import urlparse

# Marketplaces / directories with aggressive bot detection → use a "stealth"
# context. Everything else → a faster "lite" context. (Ported list.)
STEALTH_DOMAINS = {
    "indiamart.com", "tradeindia.com", "exportersindia.com",
    "thomasnet.com", "kompass.com", "alibaba.com", "globalsources.com",
    "made-in-china.com", "ec21.com", "tradekey.com",
    "amazon.com", "amazon.in", "flipkart.com",
    "g2.com", "capterra.com", "trustpilot.com", "linkedin.com",
}

DEFAULT_LAUNCH_ARGS = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
    "--disable-blink-features=AutomationControlled",
]

# Injected before any page script runs — masks the headless fingerprint.
STEALTH_INIT_SCRIPT = """
(() => {
  try { Object.defineProperty(navigator, 'webdriver', { get: () => false }); } catch (e) {}
  try { Object.defineProperty(navigator, 'platform', { get: () => 'Win32' }); } catch (e) {}
  try { Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] }); } catch (e) {}
  try {
    // A couple of commonly-checked properties.
    window.chrome = window.chrome || { runtime: {} };
    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
  } catch (e) {}
})();
"""

# Realistic desktop UA (Playwright Chromium reports HeadlessChrome by default).
MASKED_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def _root_domain(url: str) -> str:
    try:
        netloc = urlparse(url).netloc.lower()
        return netloc[4:] if netloc.startswith("www.") else netloc
    except Exception:
        return ""


def profile_for(url: str) -> str:
    """Return "stealth" for bot-protected marketplaces, else "lite"."""
    domain = _root_domain(url)
    if not domain:
        return "lite"
    if domain in STEALTH_DOMAINS:
        return "stealth"
    return "stealth" if any(domain.endswith("." + d) for d in STEALTH_DOMAINS) else "lite"


def context_kwargs(profile: str = "stealth") -> dict:
    """Playwright `browser.new_context(**kwargs)` options for the given profile."""
    return {
        "user_agent": MASKED_USER_AGENT,
        "locale": "en-US",
        "viewport": {"width": 1280, "height": 800},
        "extra_http_headers": {"Accept-Language": "en-US,en;q=0.9"},
        # "stealth" gets the init script; "lite" still benefits from a real UA.
    }
