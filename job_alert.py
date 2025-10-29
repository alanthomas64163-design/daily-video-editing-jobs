# job_alert.py
import os, json, hashlib, time, requests, datetime
from pathlib import Path
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from bs4 import BeautifulSoup

# Optional: feedparser for RSS
try:
    import feedparser
except Exception:
    feedparser = None

# ----------------- CONFIG -----------------
KEYWORDS = [
    "video editor", "junior video editor",
    "entry level video editor", "video intern",
    "youtube video editor"
]

# Add HTML search pages (safe to add). For RSS, use RSS_SOURCES below
SOURCES = [
    {"type":"html", "name":"Indeed", "url":"https://www.indeed.com/jobs?q=entry+level+video+editor"},
    {"type":"html", "name":"Wellfound", "url":"https://wellfound.com/jobs?query=video%20editor"},
    {"type":"html", "name":"RemoteRocketship", "url":"https://remoterocketship.com/jobs?search=junior+video+editor"}
]

# RSS sources (use if available)
RSS_SOURCES = [
    # {"name":"Indeed RSS", "url":"https://www.indeed.com/rss?q=entry+level+video+editor"},
    # {"name":"Wellfound RSS", "url":"https://wellfound.com/jobs.rss?query=video+editor"},
]

PREV_FILE = "previous_jobs.json"

# Environment-configured values (set as GitHub secrets)
TO_EMAIL = os.getenv("ALERT_TO_EMAIL")
FROM_EMAIL = os.getenv("ALERT_FROM_EMAIL")
SMTP_PASS = os.getenv("ALERT_SMTP_PASS")        # Gmail app password
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

USER_AGENT = "job-scraper/1.0 (+https://github.com/yourusername/daily-video-jobs)"

# ----------------- HELPERS -----------------
def safe_get(url):
    try:
        r = requests.get(url, timeout=15, headers={"User-Agent": USER_AGENT})
        r.raise_for_status()
        return r.text
    except Exception as e:
        print("Fetch error:", url, e)
        return ""

def fetch_html_items(url):
    html_text = safe_get(url)
    soup = BeautifulSoup(html_text, "html.parser")
    items = []
    # Generic heuristic: find job link anchors with descriptive text
    for a in soup.find_all("a", href=True):
        title = (a.get_text() or "").strip()
        href = a["href"]
        if title and len(title) < 200:
            if not href.startswith("http"):
                # make absolute where possible
                href = requests.compat.urljoin(url, href)
            items.append({"title": title, "link": href})
    return items

def fetch_rss_items(url):
    if not feedparser:
        print("feedparser not installed; skipping RSS:", url)
        return []
    d = feedparser.parse(url)
    items = []
    for e in d.entries:
        items.append({
            "title": e.get("title", "").strip(),
            "link": e.get("link", ""),
            "description": e.get("summary", "")
        })
    return items

def keywords_match(title):
    t = (title or "").lower()
    return any(k in t for k in KEYWORDS)

def job_id(job):
    # prefer canonical link; otherwise hash title+source
    link = job.get("link")
    if link:
        return link
    s = (job.get("title","") + "|" + job.get("company","") + "|" + job.get("source","")).strip()
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

# ----------------- EMAIL BUILDERS -----------------
def build_html_table(jobs):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    if not jobs:
        return f"<p>No new entry-level video editor jobs found on {now}.</p>"
    rows = []
    for idx, j in enumerate(jobs[:100], 1):
        title = j.get("title","")
        link = j.get("link","")
        source = j.get("source","")
        company = j.get("company","")
        location = j.get("location","")
        rows.append(f"<tr><td>{idx}</td>"
                    f"<td><a href='{link}' target='_blank'>{title}</a></td>"
                    f"<td>{company or ''}</td><td>{location or ''}</td><td>{source or ''}</td></tr>")
    html_body = f"""
    <html><body>
      <h2>Daily entry-level video editor job alerts — {now}</h2>
      <table border="0" cellpadding="6" cellspacing="0" style="border-collapse:collapse;">
        <thead><tr style="text-align:left;"><th>#</th><th>Title</th><th>Company</th><th>Location</th><th>Source</th></tr></thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
      <p>Sent by GitHub Actions job-alert script.</p>
    </body></html>
    """
    return html_body

def send_via_gmail(html_body, subject="Daily: Entry-level Video Editor job alerts"):
    if not (FROM_EMAIL and SMTP_PASS and TO_EMAIL):
        print("Gmail credentials not provided; skipping SMTP send.")
        return False
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = FROM_EMAIL
    msg["To"] = TO_EMAIL
    msg.attach(MIMEText("Open in HTML-capable client.", "plain"))
    msg.attach(MIMEText(html_body, "html"))
    import smtplib
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as s:
            s.login(FROM_EMAIL, SMTP_PASS)
            s.send_message(msg)
        print("Sent via Gmail SMTP.")
        return True
    except Exception as e:
        print("Gmail send failed:", e)
        return False

def send_via_sendgrid(html_body, subject="Daily: Entry-level Video Editor job alerts"):
    if not SENDGRID_API_KEY or not FROM_EMAIL or not TO_EMAIL:
        print("SendGrid config missing; skipping.")
        return False
    url = "https://api.sendgrid.com/v3/mail/send"
    payload = {
        "personalizations":[{"to":[{"email": TO_EMAIL}], "subject": subject}],
        "from": {"email": FROM_EMAIL},
        "content":[{"type":"text/html","value": html_body}]
    }
    headers = {"Authorization": f"Bearer {SENDGRID_API_KEY}", "Content-Type":"application/json"}
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=30)
        r.raise_for_status()
        print("Sent via SendGrid.")
        return True
    except Exception as e:
        print("SendGrid send failed:", e, getattr(e, "response", None))
        return False

def send_telegram_short(text):
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
        print("Telegram not configured; skipping.")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode":"HTML"}
    try:
        r = requests.post(url, data=payload, timeout=15)
        r.raise_for_status()
        print("Sent Telegram message.")
        return True
    except Exception as e:
        print("Telegram send failed:", e)
        return False

# ----------------- MAIN -----------------
def main():
    prev = load_previous()
    found = []

    # HTML sources
    for s in SOURCES:
        if s.get("type") == "html":
            items = fetch_html_items(s["url"])
            for it in items:
                if keywords_match(it.get("title","")):
                    it.setdefault("source", s.get("name"))
                    found.append(it)
            time.sleep(1)

    # RSS sources
    for r in RSS_SOURCES:
        items = fetch_rss_items(r["url"])
        for it in items:
            if keywords_match(it.get("title","")):
                it.setdefault("source", r.get("name"))
                found.append(it)
        time.sleep(1)

    # deduplicate by link/title+source
    new_jobs = []
    current_ids = set(prev)
    for job in found:
        jid = job_id(job)
        if jid not in current_ids:
            new_jobs.append(job)
            current_ids.add(jid)

    # persist ids
    save_previous(current_ids)

    # If there are new jobs, send HTML email. If sending fails and TELEGRAM defined, send short telegram.
    if new_jobs:
        html = build_html_table(new_jobs)
        sent = False
        # Try SendGrid first (if configured)
        if SENDGRID_API_KEY:
            sent = send_via_sendgrid(html)
        # Fall back to Gmail SMTP
        if not sent and FROM_EMAIL and SMTP_PASS:
            sent = send_via_gmail(html)
        # If still not sent, send short Telegram summary
        if not sent and TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
            txt = f"Found {len(new_jobs)} new entry-level video editor jobs. Check repo for details."
            send_telegram_short(txt)
        print(f"Done. New jobs: {len(new_jobs)}")
    else:
        print("No new jobs found. Nothing sent.")

if __name__ == "__main__":
    main()
if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
    txt = f"✅ {len(new_jobs)} new jobs found today. Check your email for full list."
    send_telegram_short(txt)

