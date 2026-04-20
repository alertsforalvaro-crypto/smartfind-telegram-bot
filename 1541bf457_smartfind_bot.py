import os
import time
import requests
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# ─── CONFIG ────────────────────────────────────────────────────────────────────
USERNAME           = os.getenv("SMARTFIND_USERNAME")
PASSWORD           = os.getenv("SMARTFIND_PASSWORD")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID")

LOGIN_URL          = "https://hrsubsfresnounified.eschoolsolutions.com/logOnInitAction.do"
CHECK_INTERVAL     = 15   # seconds between refreshes (site enforces 15s minimum)

# ─── CRITERIA ─────────────────────────────────────────────────────────────────
# Job is accepted if classification/location matches ANY of these keywords (case-insensitive)
TARGET_KEYWORDS = [
    "middle school",
    "middle",
    "high school",
    "junior high",
    "grade 7",
    "grade 8",
    "grades 7",
    "grades 8",
    "7th grade",
    "8th grade",
    "ms ",       # common abbreviation e.g. "TENAYA MS"
    " ms",
    "jr high",
]
MIN_HOURS = 4.0   # minimum shift duration in hours


# ─── HELPERS ──────────────────────────────────────────────────────────────────
def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log("⚠️  Telegram not configured — skipping notification.")
        return
    try:
        url  = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        resp = requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=10)
        if resp.status_code == 200:
            log("📨 Telegram notification sent.")
        else:
            log(f"⚠️  Telegram error {resp.status_code}: {resp.text}")
    except Exception as e:
        log(f"⚠️  Telegram exception: {e}")


def safe_text(locator):
    """Return stripped text or empty string — never raises."""
    try:
        if locator.count() > 0:
            return locator.first.inner_text().strip()
    except Exception:
        pass
    return ""


def parse_hours(time_str):
    """
    Parse a time range like '09:15 AM - 03:45 PM' or '08:00 AM 03:00 PM'
    and return the duration in hours. Returns 0.0 on failure.
    """
    try:
        # normalise separators
        cleaned = time_str.replace("–", "-").replace("—", "-")
        parts   = [p.strip() for p in cleaned.replace("-", " ").split() if p.strip()]

        # look for two time tokens (HH:MM) in the string
        time_tokens = [p for p in parts if ":" in p]
        ampm_tokens = [p for p in parts if p.upper() in ("AM", "PM")]

        if len(time_tokens) >= 2 and len(ampm_tokens) >= 2:
            t1 = f"{time_tokens[0]} {ampm_tokens[0]}"
            t2 = f"{time_tokens[1]} {ampm_tokens[1]}"
            fmt = "%I:%M %p"
            start = datetime.strptime(t1, fmt)
            end   = datetime.strptime(t2, fmt)
            diff  = (end - start).total_seconds() / 3600
            return diff if diff > 0 else diff + 24   # handle overnight
    except Exception:
        pass
    return 0.0


def matches_criteria(classification, location, time_str):
    """Return True if the job meets ALL acceptance criteria."""
    combined = f"{classification} {location}".lower()

    keyword_match = any(kw.lower() in combined for kw in TARGET_KEYWORDS)
    if not keyword_match:
        return False

    hours = parse_hours(time_str)
    if hours < MIN_HOURS:
        log(f"   ↳ Keyword matched but only {hours:.1f}h — skipping (need ≥{MIN_HOURS}h).")
        return False

    return True


# ─── CORE LOGIC ───────────────────────────────────────────────────────────────
def check_and_accept_jobs():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page    = context.new_page()

        # ── 1. LOGIN ──────────────────────────────────────────────────────────
        log("🔐 Logging in…")
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60_000)

        # The login page uses input[type=text] for username and input[type=password] for pin
        page.locator("input[type='text']").first.fill(USERNAME)
        page.locator("input[type='password']").first.fill(PASSWORD)
        page.locator("button[type='submit'], input[type='submit']").first.click()

        # Wait until we land on the job search dashboard
        try:
            page.wait_for_selector(
                "text=Available Jobs, text=Job Search, #available-tab, .tab",
                timeout=60_000
            )
        except PlaywrightTimeoutError:
            log("❌ Login timed out — check credentials or site availability.")
            browser.close()
            return

        log("✅ Logged in.")

        # ── 2. NAVIGATE TO AVAILABLE JOBS TAB ─────────────────────────────────
        # Try multiple selectors — SmartFind Express uses different versions
        for selector in [
            "#available-tab",
            "button:has-text('Available Jobs')",
            "a:has-text('Available Jobs')",
            "[data-tab='available']",
            "li:first-child a",
        ]:
            try:
                btn = page.locator(selector)
                if btn.count() > 0:
                    btn.first.click()
                    log(f"🗂  Clicked Available Jobs tab via: {selector}")
                    break
            except Exception:
                continue

        # Wait for the tab panel to become active
        try:
            page.wait_for_function(
                """
                () => {
                    const hasRows = document.querySelectorAll(
                        "tr[id^='mobile-row-'], tbody tr, .job-row, [class*='job-row']"
                    ).length > 0;
                    const noJobs = (
                        document.body.innerText.toLowerCase().includes("no jobs available") ||
                        document.body.innerText.toLowerCase().includes("there are no jobs")
                    );
                    return hasRows || noJobs;
                }
                """,
                timeout=30_000,
            )
        except PlaywrightTimeoutError:
            log("⏳ Timed out waiting for jobs state — will retry next cycle.")
            browser.close()
            return

        # ── 3. DETECT AVAILABLE JOB ROWS ──────────────────────────────────────
        # SmartFind Express renders jobs as <tr id="mobile-row-0">, <tr id="mobile-row-1">, …
        rows = page.locator("tr[id^='mobile-row-']")
        count = rows.count()

        if count == 0:
            log("😴 No jobs available right now.")
            browser.close()
            return

        log(f"📋 Found {count} available job(s) — checking criteria…")

        accepted_any = False

        for i in range(count):
            try:
                row = rows.nth(i)

                # ── EXPAND ROW to load full details ───────────────────────────
                try:
                    caret = row.locator("pds-icon[name*='caret'], button[aria-label*='expand'], [class*='expand']")
                    if caret.count() > 0:
                        caret.first.click()
                        page.wait_for_timeout(500)
                except Exception:
                    pass

                # ── EXTRACT FIELDS ────────────────────────────────────────────
                # Date column
                date_text = safe_text(row.locator("td[id*='startendDate'], td:nth-child(1)"))

                # Time column
                time_text = safe_text(row.locator("td[id*='startendtime'], td[id*='time'], td:nth-child(2)"))

                # Classification column (contains "ELEM FOUR SIX", "SOCIAL STUDIES", etc.)
                classification = safe_text(
                    row.locator("td[id*='classification'], td[id*='classif'], td:nth-child(4)")
                )

                # Location column
                location = safe_text(
                    row.locator("td[id*='location'], td[id*='school'], td:nth-child(5)")
                )

                # Also check the expanded panel for location / classification
                expanded = page.locator(f"#mobile-row-expanded-{i}, tr[id='mobile-row-expanded-{i}']")
                if expanded.count() > 0:
                    exp_text = expanded.inner_text()
                    # Append to existing for broader keyword matching
                    classification += " " + exp_text
                    location       += " " + exp_text

                log(f"   Job {i+1}: {date_text} | {time_text} | {classification.strip()[:60]} | {location.strip()[:40]}")

                # ── CHECK CRITERIA ────────────────────────────────────────────
                if not matches_criteria(classification, location, time_text):
                    log(f"   ↳ Skipped — doesn't meet criteria.")
                    continue

                log(f"   ✅ Criteria MET — attempting to accept…")

                # ── CLICK ACCEPT ──────────────────────────────────────────────
                # The Accept button is in the same row; try multiple selectors
                accepted = False
                for accept_sel in [
                    f"tr[id='mobile-row-{i}'] button:has-text('Accept')",
                    f"tr[id='mobile-row-{i}'] [id*='accept']",
                    f"tr[id='mobile-row-{i}'] a:has-text('Accept')",
                    f"tr[id='mobile-row-{i}'] td:last-child button",
                    f"tr[id='mobile-row-{i}'] td:last-child a",
                    f"#accept-{i}",
                    f"[id*='accept'][id*='{i}']",
                ]:
                    try:
                        btn = page.locator(accept_sel)
                        if btn.count() > 0:
                            btn.first.click()
                            page.wait_for_timeout(2000)

                            # ── CONFIRM DIALOG (if any) ────────────────────────
                            for confirm_sel in [
                                "button:has-text('Confirm')",
                                "button:has-text('Yes')",
                                "button:has-text('OK')",
                                "[class*='confirm'] button",
                                "dialog button",
                                ".modal button:has-text('Accept')",
                            ]:
                                try:
                                    confirm = page.locator(confirm_sel)
                                    if confirm.count() > 0:
                                        confirm.first.click()
                                        page.wait_for_timeout(1500)
                                        log(f"   📩 Confirm dialog handled.")
                                        break
                                except Exception:
                                    continue

                            accepted = True
                            accepted_any = True
                            log(f"   🎉 Job {i+1} ACCEPTED!")
                            break
                    except Exception as e:
                        log(f"   Accept selector '{accept_sel}' failed: {e}")
                        continue

                if not accepted:
                    log(f"   ⚠️  Could not find Accept button for job {i+1}.")

                # ── SEND TELEGRAM ──────────────────────────────────────────────
                hours = parse_hours(time_text)
                msg = (
                    f"{'✅ AUTO-ACCEPTED' if accepted else '⚠️ FOUND (manual accept needed)'}\n"
                    f"\n🏫 Location:       {location.strip()[:80]}"
                    f"\n📚 Classification: {classification.strip()[:80]}"
                    f"\n📅 Date:           {date_text}"
                    f"\n⏰ Time:           {time_text}  ({hours:.1f}h)"
                )
                send_telegram(msg)

            except Exception as e:
                log(f"   ❌ Error processing job {i}: {e}")
                continue

        if not accepted_any:
            log("   No jobs met all criteria this cycle.")

        browser.close()


# ─── MAIN LOOP ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    log("🚀 SmartFind Bot started — checking every 15 seconds")
    log(f"   Criteria: {TARGET_KEYWORDS}")
    log(f"   Min hours: {MIN_HOURS}")

    while True:
        try:
            check_and_accept_jobs()
        except Exception as e:
            log(f"💥 Unexpected error: {e}")

        log(f"⏳ Sleeping {CHECK_INTERVAL}s…\n")
        time.sleep(CHECK_INTERVAL)
