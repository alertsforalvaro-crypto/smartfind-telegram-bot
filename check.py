import os
import time
import requests
from playwright.sync_api import sync_playwright, TimeoutError

USERNAME = os.getenv("SMARTFIND_USERNAME")
PASSWORD = os.getenv("SMARTFIND_PASSWORD")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

LOGIN_URL = "https://hrsubsfresnounified.eschoolsolutions.com/logOnInitAction.do"


def send_telegram(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

        response = requests.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message
            }
        )

        print("Telegram response:", response.status_code)

    except Exception as e:
        print("Telegram error:", e)


# --- SAFE TEXT HELPER ---
def safe_text(locator):
    try:
        if locator.count() > 0:
            return locator.first.inner_text().strip()
    except:
        pass
    return None


def get_available_jobs(page):
    """Extract job info safely (never breaks)."""

    jobs = []

    try:
        rows = page.locator("tbody.mobile-table-body tr[id^='mobile-row-']")
        count = rows.count()

        for i in range(count):

            try:
                row = rows.nth(i)

                # --- CLICK EXPAND ---
                try:
                    expand_btn = row.locator("pds-icon[name*='caret-right']")
                    if expand_btn.count() > 0:
                        expand_btn.click()
                        page.wait_for_timeout(400)
                except:
                    pass

                # --- BASIC INFO ---
                date = safe_text(row.locator("td[id*='startendDate']"))
                time_text = safe_text(row.locator("td[id*='startendtime']"))

                # --- EXPANDED PANEL ---
                expanded = page.locator(f"#mobile-row-expanded-{i}")

                school = safe_text(
                    expanded.locator("pds-icon[name='school']").locator("xpath=..")
                )

                instructions = safe_text(
                    expanded.locator(".text")
                )

                jobs.append({
                    "date": date,
                    "time": time_text,
                    "location": school,
                    "instructions": instructions
                })

            except Exception as e:
                print(f"Job {i} failed:", e)
                continue

    except Exception as e:
        print("Job scraping error:", e)

    return jobs


def send_job_details(jobs):
    """Always sends message, appends info if available."""

    for job in jobs:

        message = "🚨 SMARTFIND JOB ALERT\n"

        if job.get("location"):
            message += f"\n🏫 School: {job['location']}"

        if job.get("date"):
            message += f"\n📅 Date: {job['date']}"

        if job.get("time"):
            message += f"\n⏰ Time: {job['time']}"

        if job.get("instructions"):
            message += f"\n📝 Notes: {job['instructions']}"

        send_telegram(message)


def check_for_jobs():

    with sync_playwright() as p:

        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        print("🔐 Logging in...")

        page.goto(LOGIN_URL)

        page.fill("#userId", USERNAME)
        page.fill("#userPin", PASSWORD)
        page.click("#submitBtn")

        page.wait_for_selector("#available-tab", timeout=60000)

        page.click("#available-tab")
        page.wait_for_selector("#available-panel.pds-is-active", timeout=60000)

        print("📋 Waiting for jobs state...")

        try:
            page.wait_for_function(
                """
                () => {
                    const hasRows = document.querySelectorAll(
                        "tbody.mobile-table-body tr[id^='mobile-row-']"
                    ).length > 0;

                    const noJobs = document.querySelector('#available-panel .pds-message-info')
                        ?.innerText
                        ?.toLowerCase()
                        .includes('no jobs');

                    return hasRows || noJobs;
                }
                """,
                timeout=60000
            )
        except TimeoutError:
            print("Timed out waiting for jobs state.")
            browser.close()
            return

        # --- REAL DETECTION ---
        rows = page.locator("tbody.mobile-table-body tr[id^='mobile-row-']")
        row_count = rows.count()

        if row_count == 0:
            print("❌ No job rows detected (avoiding false alert).")
            browser.close()
            return

        # Optional extra safety
        try:
            first_row_text = rows.nth(0).inner_text().strip()
            if not first_row_text:
                print("⚠️ Rows detected but empty — skipping alert.")
                browser.close()
                return
        except:
            pass

        print(f"✅ Jobs detected: {row_count}")

        # ✅ ALWAYS send main alert (only when real jobs exist)
        send_telegram("🚨 Jobs available on SmartFind!")

        try:
            page.wait_for_timeout(1500)

            jobs = get_available_jobs(page)

            if jobs:
                send_job_details(jobs)

        except Exception as e:
            print("Detail extraction failed:", e)

        browser.close()


print("🚀 SmartFind Railway Bot Started")

while True:

    try:
        check_for_jobs()

    except Exception as e:
        print("Unexpected error:", e)

    print("⏳ Sleeping 20 seconds...\n")

    time.sleep(20)
