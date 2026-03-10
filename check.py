import os
import time
import requests
from playwright.sync_api import sync_playwright, TimeoutError

# Environment variables (set these in Railway → Variables)
USERNAME = os.getenv("SMARTFIND_USERNAME")
PASSWORD = os.getenv("SMARTFIND_PASSWORD")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

LOGIN_URL = "https://hrsubsfresnounified.eschoolsolutions.com/logOnInitAction.do"


def send_telegram():
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

        response = requests.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": "🚨 Jobs are available on SmartFind! Log in now."
            }
        )

        print("Telegram response:", response.status_code, response.text)

    except Exception as e:
        print("Telegram error:", e)


def check_for_jobs():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        print("🔐 Logging in...")

        page.goto(LOGIN_URL)

        page.fill("#userId", USERNAME)
        page.fill("#userPin", PASSWORD)
        page.click("#submitBtn")

        # Wait for dashboard
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
                        .querySelector('#parent-table-desktop-available tbody')
                        ?.querySelectorAll('tr').length > 0;

                    return noJobs || hasRows;
                }
                """,
                timeout=60000
            )
        except TimeoutError:
            print("⏱ Timed out waiting for jobs state.")
            browser.close()
            return

        no_jobs_locator = page.locator("#available-panel .pds-message-info")

        if no_jobs_locator.count() > 0 and \
           "no jobs" in no_jobs_locator.first.inner_text().lower():
            print("❌ No jobs available.")
        else:
            print("✅ Jobs available!")
            send_telegram()

        browser.close()


# Continuous loop for Railway
print("🚀 SmartFind Railway Bot Started")

while True:
    try:
        check_for_jobs()
    except Exception as e:
        print(f"Unexpected error: {e}")

    print("⏳ Sleeping 120 seconds...\n")

    time.sleep(90)
