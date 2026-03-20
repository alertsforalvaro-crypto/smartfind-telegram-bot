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

                # --- CLICK EXPAND (to reveal instructions) ---
                try:
                    expand_btn = row.locator("pds-icon[name*='caret-right']")
                    if expand_btn.count() > 0:
                        expand_btn.click()
                        page.wait_for_timeout(400)
                except:
                    pass  # never break

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
    """Always sends a message, appends data if available."""

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
                    const panel = document.querySelector('#available-panel');
                    if (!panel) return false;

                    const noJobs = panel
                        .querySelector('.pds-message-info')
                        ?.innerText
                        .toLowerCase()
                        .includes('no jobs');

                    const hasRows = panel
                        .querySelector('tbody.mobile-table-body')
                        ?.querySelectorAll('tr[id^="mobile-row-"]').length > 0;

                    return noJobs || hasRows;
                }
                """,
                timeout=60000
            )
        except TimeoutError:
            print("Timed out waiting for jobs state.")
            browser.close()
            return

        no_jobs_locator = page.locator("#available-panel .pds-message-info")

        if no_jobs_locator.count() > 0 and \
           "no jobs" in no_jobs_locator.first.inner_text().lower():

            print("❌ No jobs available.")

        else:

            print("✅ Jobs available!")

            # ✅ ALWAYS send main alert (UNCHANGED)
            send_telegram("🚨 Jobs available on SmartFind!")

            # THEN try to extract details safely
            try:
                page.wait_for_timeout(1500)  # allow UI to fully render

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

    print("⏳ Sleeping 30 seconds...\n")

    time.sleep(30)
