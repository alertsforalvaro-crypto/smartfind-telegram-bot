import os
import time
import requests
from playwright.sync_api import sync_playwright

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

LOGIN_URL = "https://hrsubsfresnounified.eschoolsolutions.com/logOnInitAction.do"


def send_telegram(message):

    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

    requests.post(url, data={
        "chat_id": CHAT_ID,
        "text": message
    })


def check_jobs():

    with sync_playwright() as p:

        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        page.goto(LOGIN_URL)

        page.fill("#userId", os.getenv("SMARTFIND_USERNAME"))
        page.fill("#userPin", os.getenv("SMARTFIND_PASSWORD"))
        page.click("#submitBtn")

        page.wait_for_selector("#available-tab", timeout=60000)

        page.click("#available-tab")
        page.wait_for_selector("#available-panel.pds-is-active")

        no_jobs = page.locator("#available-panel .pds-message-info")

        if no_jobs.count() > 0 and "no jobs" in no_jobs.first.inner_text().lower():
            print("No jobs")
        else:
            print("Jobs available!")
            send_telegram("🚨 Jobs available on SmartFind!")

        browser.close()


print("Bot running...")

while True:

    try:
        check_jobs()
    except Exception as e:
        print("Error:", e)

    time.sleep(60)
