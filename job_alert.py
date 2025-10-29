import os
import json
import hashlib
import time
import random
import requests
import smtplib
from pathlib import Path
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from bs4 import BeautifulSoup
from datetime import datetime
from typing import List, Dict

# ---------- CONFIG ----------
KEYWORDS = [
    "video editor", "junior video editor",
    "entry level video editor", "video intern",
    "youtube video editor"
]

SOURCES = [
    {"type": "indeed", "name": "Indeed", "url": "https://www.indeed.com/jobs?q=entry+level+video+editor"},
    {"type": "wellfound", "name": "Wellfound", "url": "https://wellfound.com/jobs?query=video%20editor"},
    {"type": "generic_html", "name": "RemoteRocketship", "url": "https://remoterocketship.com/jobs?search=junior+video+editor"},
]

REMOTIVE_API = "https://remotive.com/api/remote-jobs?search=video%20editor"
PREV_FILE = "previous_jobs.json"

# Environment variables
TO_EMAIL = os.getenv("ALERT_TO_EMAIL")
FROM_EMAIL = os.getenv("ALERT_FROM_EMAIL")
SMTP_PASS = os.getenv("ALERT_SMTP_PASS")
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Randomized browser-like headers
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/120.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]

# ---------- HELPERS ----------
def get_random_headers():
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.google.com/"
    }

def safe_get_text(url, retries=3, backoff=2):
    for attempt in range(1, retries + 1):
        hdrs = get_random_headers()
        try:
            r = requests.get(url, headers=hdrs, timeout=20)
            if r.status_code == 200:
                return r.text
            if r.status_code == 429:
                wait = backoff * attempt + random.uniform(5, 10)
                print(f"[WARN] 429 from {url}. Sleeping {wait:.1f}s (attempt {attempt})")
                time.sleep(wait)
                continue
            if r.status_code in (403, 401):
                print(f"[WARN] {r.status_code} Forbidden/Unauthorized for {url}. Returning empty.")
                return ""
            print(f"[WARN] HTTP {r.status_code} for {url} (attempt {attempt})")
        except requests.RequestException as e:
            wait = backoff * attempt + random.uniform(1, 3)
            print(f"[ERROR] Request exception for {url}: {e}. Retrying in {wait:.1f}s (attempt {attempt})")
            time.sleep(wait)
    print(f"[ERROR] Failed to fetch {url} after {retries} attempts.")
    return ""

def clean_text(element):
    return element.get_text(strip=True) if element else "N/A"

# ---------- SCRAPERS ----------
def scrape_indeed(url, html_content):
    jobs = []
    if not html_content: return jobs
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        job_cards = soup.find_all('div', class_=lambda x: x and 'cardOutline' in x)
        for card in job_cards:
            title_tag = card.find('h2', class_=lambda x: x and 'jobTitle' in x)
            company_tag = card.find('span', class_=lambda x: x and 'companyName' in x)
            link_tag = title_tag.find('a') if title_tag else None
            if link_tag and company_tag:
                title = clean_text(title_tag)
                company = clean_text(company_tag)
                href = link_tag.get('href')
                link = f"https://www.indeed.com{href}" if href.startswith('/') else href
                jobs.append({"title": title, "company": company, "link": link, "source": "Indeed"})
    except Exception as e:
        print(f"[ERROR] Indeed scraping failed: {e}")
    return jobs

def scrape_wellfound(url, html_content):
    jobs = []
    if not html_content: return jobs
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        job_cards = soup.find_all('div', class_=lambda x: x and 'Card_card' in x)
        for card in job_cards:
            link_tag = card.find('a', class_=lambda x: x and 'styles_title' in x)
            company_tag = card.find('a', class_=lambda x: x and 'styles_startupName' in x)
            if link_tag and company_tag:
                title = clean_text(link_tag)
                link = requests.compat.urljoin(url, link_tag.get('href'))
                company = clean_text(company_tag)
                jobs.append({"title": title, "company": company, "link": link, "source": "Wellfound"})
    except Exception as e:
        print(f"[ERROR] Wellfound scraping failed: {e}")
    return jobs

def scrape_generic_html(url, html_content):
    items = []
    if not html_content: return items
    try:
        soup = BeautifulSoup(html_content, "html.parser")
        for a in soup.find_all("a", href=True):
            title = (a.get_text() or "").strip()
            href = a["href"]
            if len(title) < 15 or len(title) > 200:
                continue
            if not href.startswith("http"):
                href = requests.compat.urljoin(url, href)
            items.append({"title": title, "link": href, "company": f"Unknown ({url})"})
    except Exception as e:
        print(f"[ERROR] Generic HTML scraping failed: {e}")
    return items

def fetch_remotive_jobs():
    try:
        r = requests.get(REMOTIVE_API, headers=get_random_headers(), timeout=15)
        r.raise_for_status()
        data = r.json()
        jobs = []
        for j in data.get("jobs", []):
            jobs.append({
                "title": j.get("title"),
                "link": j.get("url"),
                "company": j.get("company_name"),
                "source": "Remotive"
            })
        return jobs
    except Exception as e:
        print("[WARN] Remotive fetch failed:", e)
        return []

SCRAPER_MAP = {
    "indeed": scrape_indeed,
    "wellfound": scrape_wellfound,
    "generic_html": scrape_generic_html,
}

# ---------- UTIL ----------
def keywords_match(title):
    t = (title or "").lower()
    return any(k in t for k in KEYWORDS)

def job_id(job):
    link = job.get("link")
    if link:
        return link
    s = (job.get("title", "") + "|" + job.get("company", "") + "|" + job.get("source", "")).strip()
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def load_previous():
    p = Path(PREV_FILE)
    if p.exists():
        try:
            return set(json.loads(p.read_text()))
        except Exception:
            return set()
    return set()

def save_previous(ids):
    Path(PREV_FILE).write_text(json.dumps(sorted(list(ids)), indent=2))

# ---------- DELIVERY ----------
def build_html_table(jobs):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    if not jobs:
        return f"<p>No new results on {now}.</p>"
    rows = []
    for i, j in enumerate(jobs[:100], 1):
        rows.append(f"""
            <tr>
                <td>{i}</td>
                <td><a href='{j.get('link','#')}'>{j.get('title')}</a></td>
                <td>{j.get('company')}</td>
                <td>{j.get('source')}</td>
            </tr>""")
    return f"""
    <html><body>
    <h2>Daily Video Editing Job Alert — {now}</h2>
    <table border='1' cellspacing='0' cellpadding='5'>
    <tr><th>#</th><th>Title</th><th>Company</th><th>Source</th></tr>
    {''.join(rows)}
    </table>
    </body></html>
    """

def send_via_gmail(html_body, subject="Daily Job Alert"):
    if not (FROM_EMAIL and SMTP_PASS and TO_EMAIL):
        print("[INFO] Gmail credentials missing.")
        return False
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = FROM_EMAIL
    msg["To"] = TO_EMAIL
    msg.attach(MIMEText(html_body, "html"))
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as s:
            s.login(FROM_EMAIL, SMTP_PASS)
            s.send_message(msg)
        print("[INFO] Email sent via Gmail")
        return True
    except Exception as e:
        print("[ERROR] Gmail send failed:", e)
        return False

def send_telegram_short(text):
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
        print("[INFO] Telegram not configured.")
        return False
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text}
        r = requests.post(url, data=payload, timeout=15)
        r.raise_for_status()
        print("[INFO] Telegram sent")
        return True
    except Exception as e:
        print("[ERROR] Telegram send failed:", e)
        return False

# ---------- MAIN ----------
def main():
    print("[START] job_alert run:", datetime.now().isoformat())
    prev_ids = load_previous()
    found, new_jobs = [], []

    for s in SOURCES:
        print(f"[FETCH] {s['name']} -> {s['url']}")
        html_content = safe_get_text(s["url"])
        scraper = SCRAPER_MAP.get(s["type"], scrape_generic_html)
        items = scraper(s["url"], html_content)
        for it in items:
            if keywords_match(it.get("title", "")):
                it["source"] = s["name"]
                found.append(it)
        print(f"[INFO] {len(items)} scraped from {s['name']}")
        time.sleep(random.uniform(2.0, 4.0))

    print("[INFO] Fetching Remotive API fallback")
    found.extend(fetch_remotive_jobs())

    current_ids = set(prev_ids)
    for job in found:
        jid = job_id(job)
        if jid not in current_ids:
            new_jobs.append(job)
            current_ids.add(jid)
    save_previous(current_ids)

    if new_jobs:
        print(f"[INFO] {len(new_jobs)} new jobs found; sending...")
        html = build_html_table(new_jobs)
        subject = f"🚨 {len(new_jobs)} New Video Editor Jobs - {datetime.now().strftime('%b %d')}"
        sent = send_via_gmail(html, subject)
        if not sent:
            txt = f"✅ {len(new_jobs)} new jobs found today. Check your email for details."
            send_telegram_short(txt)
    else:
        print("[INFO] No new jobs found today.")
    print("[DONE] job_alert finished successfully")

if __name__ == "__main__":
    main()

