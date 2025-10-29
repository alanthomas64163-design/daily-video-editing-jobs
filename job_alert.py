# job_alert.py (final fixed version)
import os
import json
import hashlib
import time
import random
import requests
from pathlib import Path
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from bs4 import BeautifulSoup
from datetime import datetime

# ---------- CONFIG ----------
KEYWORDS = [
    "video editor", "junior video editor",
    "entry level video editor", "video intern",
    "youtube video editor"
]

SOURCES = [
    {"type": "html", "name": "Indeed", "url": "https://www.indeed.com/jobs?q=entry+level+video+editor"},
    {"type": "html", "name": "Wellfound", "url": "https://wellfound.com/jobs?query=video%20editor"},
    {"type": "html", "name": "RemoteRocketship", "url": "https://remoterocketship.com/jobs?search=junior+video+editor"},
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

# Browser-like headers (important to avoid 403)
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.google.com/"
}

# ---------- HELPERS ----------
def safe_get_text(url, headers=None, retries=3, backoff=2):
    """GET with retries, exponential backoff. Returns text or empty string."""
    hdrs = headers or HEADERS
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, headers=hdrs, timeout=20)
            if r.status_code == 200:
                return r.text
            if r.status_code == 429:
                wait = backoff * attempt + random.uniform(2, 5)
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


def fetch_html_items(url):
    text = safe_get_text(url)
    if not text:
        return []
    soup = BeautifulSoup(text, "html.parser")
    items = []
    for a in soup.find_all("a", href=True):
        title = (a.get_text() or "").strip()
        href = a["href"]
        if not title or len(title) > 200:
            continue
        if not href.startswith("http"):
            href = requests.compat.urljoin(url, href)
        items.append({"title": title, "link": href})
    return items


def fetch_remotive_jobs():
    try:
        r = requests.get(REMOTIVE_API, headers=HEADERS, timeout=15)
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
        except Exception as e:
            print("[WARN] Could not parse previous file:", e)
            return set()
    return set()


def save_previous(ids):
    Path(PREV_FILE).write_text(json.dumps(sorted(list(ids)), indent=2))


# ---------- EMAIL / DELIVERY ----------
def build_html_table(jobs):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    if not jobs:
        return f"<p>No new results on {now}.</p>"
    rows = []
    for i, j in enumerate(jobs[:100], 1):
        title = j.get("title", "")
        link = j.get("link", "")
        company = j.get("company", "") or ""
        source = j.get("source", "") or ""
        rows.append(f"<tr><td>{i}</td><td><a href='{link}'>{title}</a></td><td>{company}</td><td>{source}</td></tr>")
    return (
        f"<html><body><h3>Video Editing Jobs — {now}</h3>"
        f"<table border='0' cellpadding='6'><thead><tr><th>#</th><th>Title</th><th>Company</th><th>Source</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></body></html>"
    )


def send_via_gmail(html_body, subject="Daily jobs"):
    if not (FROM_EMAIL and SMTP_PASS and TO_EMAIL):
        print("[INFO] Gmail credentials missing; skipping Gmail send.")
        return False
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = FROM_EMAIL
    msg["To"] = TO_EMAIL
    msg.attach(MIMEText("Open html email.", "plain"))
    msg.attach(MIMEText(html_body, "html"))
    import smtplib
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as s:
            s.login(FROM_EMAIL, SMTP_PASS)
            s.send_message(msg)
        print("[INFO] Email sent via Gmail")
        return True
    except Exception as e:
        print("[ERROR] Gmail send failed:", e)
        return False


def send_via_sendgrid(html_body, subject="Daily jobs"):
    if not SENDGRID_API_KEY:
        return False
    try:
        url = "https://api.sendgrid.com/v3/mail/send"
        payload = {
            "personalizations": [{"to": [{"email": TO_EMAIL}], "subject": subject}],
            "from": {"email": FROM_EMAIL},
            "content": [{"type": "text/html", "value": html_body}]
        }
        headers = {"Authorization": f"Bearer {SENDGRID_API_KEY}", "Content-Type": "application/json"}
        r = requests.post(url, json=payload, headers=headers, timeout=20)
        r.raise_for_status()
        print("[INFO] Sent via SendGrid")
        return True
    except Exception as e:
        print("[ERROR] SendGrid failed:", e)
        return False


def send_telegram_short(text):
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
        print("[INFO] Telegram not configured; skipping.")
        return False
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
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
    found = []
    new_jobs = []

    for s in SOURCES:
        url = s.get("url")
        print(f"[FETCH] {s.get('name')} -> {url}")
        try:
            items = fetch_html_items(url)
            for it in items:
                if keywords_match(it.get("title", "")):
                    it.setdefault("source", s.get("name"))
                    found.append(it)
            time.sleep(random.uniform(2.0, 4.0))
        except Exception as e:
            print(f"[ERROR] Exception while processing {s.get('name')}: {e}")

    print("[INFO] Fetching Remotive API fallback")
    rem = fetch_remotive_jobs()
    for j in rem:
        if keywords_match(j.get("title", "")):
            found.append(j)

    current_ids = set(prev_ids)
    for job in found:
        jid = job_id(job)
        if jid not in current_ids:
            new_jobs.append(job)
            current_ids.add(jid)

    save_previous(current_ids)

    if new_jobs:
        print(f"[INFO] {len(new_jobs)} new jobs found; preparing delivery")
        html = build_html_table(new_jobs)
        sent = False
        if SENDGRID_API_KEY:
            sent = send_via_sendgrid(html)
        if not sent:
            sent = send_via_gmail(html)
        if not sent:
            txt = f"Found {len(new_jobs)} new video editor jobs today."
            send_telegram_short(txt)
        print("[DONE] job_alert finished successfully")
    else:
        print("[INFO] No new jobs found. Nothing to send.")


if __name__ == "__main__":
    main()



