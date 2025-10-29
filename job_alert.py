# job_alert.py
import os, smtplib, requests, datetime
from email.mime.text import MIMEText
from bs4 import BeautifulSoup

TO_EMAIL = os.getenv("ALERT_TO_EMAIL")
FROM_EMAIL = os.getenv("ALERT_FROM_EMAIL")
SMTP_PASS = os.getenv("ALERT_SMTP_PASS")

KEYWORDS = [
    "video editor", "junior video editor",
    "entry level video editor", "video intern",
    "youtube video editor"
]

SOURCES = [
    {"name":"Indeed", "url":"https://www.indeed.com/jobs?q=entry+level+video+editor"},
    {"name":"Wellfound", "url":"https://wellfound.com/jobs?query=video%20editor"},
    {"name":"RemoteRocketship", "url":"https://remoterocketship.com/jobs?search=junior+video+editor"}
]

def fetch_items(url):
    try:
        r = requests.get(url, timeout=15, headers={"User-Agent":"job-scraper/1.0"})
        soup = BeautifulSoup(r.text, "html.parser")
        items = []
        for a in soup.find_all("a", href=True):
            title = (a.get_text() or "").strip()
            href = a["href"]
            if title and len(title) < 200:
                if not href.startswith("http"):
                    href = url.rstrip("/") + href
                items.append({"title": title, "link": href})
        return items
    except Exception as e:
        print("Error fetching:", url, e)
        return []

def filter_items(items):
    return [i for i in items if any(k in i["title"].lower() for k in KEYWORDS)]

def build_email(found):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    if not found:
        return f"No new entry-level video editor jobs found on {now}."
    lines = [f"Found {len(found)} results on {now}:\n"]
    for idx, f in enumerate(found[:20], 1):
        lines.append(f"{idx}. {f['title']}\n   {f['link']}\n")
    return "\n".join(lines)

def send_email(body):
    msg = MIMEText(body)
    msg["Subject"] = "Daily: Entry-level Video Editor job alerts"
    msg["From"] = FROM_EMAIL
    msg["To"] = TO_EMAIL
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(FROM_EMAIL, SMTP_PASS)
        s.send_message(msg)

def main():
    all_found = []
    for s in SOURCES:
        hits = filter_items(fetch_items(s["url"]))
        for h in hits: h["source"] = s["name"]
        all_found.extend(hits)
    send_email(build_email(all_found))
    print("✅ Email sent")

if __name__ == "__main__":
    main()
