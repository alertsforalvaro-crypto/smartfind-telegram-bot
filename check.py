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


def get_available_jobs(page):
    """Safely extract job info. Returns empty list if anything fails."""

    jobs = []

    try:
        rows = page.locator("#parent-table-desktop-available tr")
        count = rows.count()

        if count <= 1:
            return jobs

        for i in range(1, count):

            try:
                date = rows.nth(i).locator(
                    f"#desktop-row-data-startenddate-{i} p"
                ).all_text_contents()

                time_text = rows.nth(i).locator(
                    f"#desktop-row-data-startendtime-{i} p"
                ).all_text_contents()

                employee = rows.nth(i).locator(
                    f"#desktop-row-data-employee-{i} p"
                ).all_text_contents()

                classification = rows.nth(i).locator(
                    f"#desktop-row-data-classification-{i}"
                ).inner_text()

                location = rows.nth(i).locator(
                    f"#desktop-row-data-location-{i} p"
                ).all_text_contents()

                jobs.append({
                    "date": " ".join(date).strip(),
                    "time": " ".join(time_text).strip(),
                    "employee": " ".join(employee).strip(),
                    "classification": classification.strip(),
                    "location": " ".join(location).strip()
                })

            except Exception as e:
                print("Row parsing error:", e)

    except Exception as e:
        print("Job scraping error:", e)

    return jobs


def send_job_details(jobs):

    for job in jobs:

        message = f"""
🚨 SMARTFIND JOB ALERT

School: {job['location']}
Teacher: {job['employee']}
Date: {job['date']}
Time: {job['time']}
Classification: {job['classification']}
"""

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
                        .querySelector('#parent-table-desktop-available tbody')
                        ?.querySelectorAll('tr').length > 0;

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

            # ALWAYS send alert first
            send_telegram("🚨 Jobs available on SmartFind!")

            # THEN attempt detailed scrape
            try:
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
