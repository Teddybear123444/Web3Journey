import html
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
from ddgs import DDGS

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
SEEN_FILE = Path("seen.json")

MAX_PER_RUN = 15      # max new links sent per scan
MAX_PER_DOMAIN = 2    # stops one site flooding a scan
TIME_LIMIT = "m"      # d = day, w = week, m = month
KEEP_DAYS = 180

# ---------------------------------------------------------------- queries
# site: queries hit the quest platforms where projects post their own tasks.
QUERIES = {
    "🪂 Airdrops & Tasks": [
        "site:galxe.com airdrop campaign",
        "site:zealy.io airdrop quests",
        "site:layer3.xyz quests rewards",
        "site:taskon.xyz campaign",
        "site:questn.com airdrop task",
        "official airdrop claim points season tasks",
        "incentivized testnet points airdrop tasks",
    ],
    "👛 New Wallet Offers": [
        "new non-custodial wallet launch rewards points",
        "new self-custody wallet airdrop campaign",
        "wallet launch quests rewards earn points",
        "new crypto wallet referral rewards campaign",
    ],
    "💰 Web3 Earning": [
        "web3 project earn rewards tasks campaign",
        "testnet rewards points program new",
        "DePIN earn points launch",
        "learn and earn crypto quests new project",
    ],
    "🤖 AI Earning": [
        "AI agent network earn crypto points airdrop",
        "decentralized AI earn rewards tasks",
        "AI data tasks earn crypto web3",
        "AI testnet incentives points airdrop",
    ],
}

# ---------------------------------------------------------------- filters
# Blogs, news and roundup/aggregator sites (they list many platforms).
BLOCKED_DOMAINS = {
    "blogspot.com", "wordpress.com", "medium.com", "substack.com", "wixsite.com",
    "tumblr.com", "quora.com", "pinterest.com", "youtube.com", "youtu.be",
    "facebook.com", "instagram.com", "linkedin.com", "reddit.com", "tiktok.com",
    "airdrops.io", "airdropalert.com", "airdropbob.com", "coinmarketcap.com",
    "coingecko.com", "coinmarketcal.com", "cryptorank.io", "dropstab.com",
    "icodrops.com", "coindesk.com", "cointelegraph.com", "decrypt.co",
    "bitcoinist.com", "cryptonews.com", "beincrypto.com", "forbes.com",
    "investopedia.com", "bitdegree.org", "binance.com", "bybit.com",
}

# Titles that signal roundups, ambassador programs or off-topic offers.
BAD_TITLE = re.compile(
    r"\b(top|best)\s*\d*\b|\blist of\b|\b\d+\s+(best|top|new|free)\b|roundup|"
    r"ambassador|\bkol\b|casino|betting|forex|prop firm|no[- ]deposit|"
    r"signup bonus|sign-up bonus|trading bonus",
    re.I,
)

# Must look like a task / airdrop / earn page.
GOOD_WORDS = re.compile(
    r"airdrop|quest|task|testnet|points|reward|earn|campaign|claim|incentiv|season",
    re.I,
)


def domain_of(url: str) -> str:
    host = urlparse(url).netloc.lower().split(":")[0]
    return host[4:] if host.startswith("www.") else host


def is_blocked(domain: str) -> bool:
    return any(domain == d or domain.endswith("." + d) for d in BLOCKED_DOMAINS)


def normalize(url: str) -> str:
    """Same page = same key, ignoring tracking params, #fragments, trailing slash."""
    p = urlparse(url.strip())
    host = p.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return f"{host}{p.path.rstrip('/').lower()}"


# ---------------------------------------------------------------- seen store
def load_seen() -> dict:
    try:
        return json.loads(SEEN_FILE.read_text())
    except Exception:
        return {}


def save_seen(seen: dict) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=KEEP_DAYS)).date().isoformat()
    seen = {k: v for k, v in seen.items() if v >= cutoff}
    SEEN_FILE.write_text(json.dumps(seen, indent=0, sort_keys=True))


# ---------------------------------------------------------------- search
def search_all(seen: dict) -> dict:
    found = {c: [] for c in QUERIES}
    run_keys, per_domain = set(), {}
    with DDGS() as ddgs:
        for category, queries in QUERIES.items():
            for q in queries:
                try:
                    results = ddgs.text(q, max_results=15, timelimit=TIME_LIMIT)
                except Exception as e:
                    print(f"search failed [{q}]: {e}", file=sys.stderr)
                    time.sleep(3)
                    continue
                for r in results or []:
                    url, title = r.get("href", ""), r.get("title", "")
                    body = r.get("body", "")
                    if not url.startswith("http"):
                        continue
                    dom = domain_of(url)
                    key = normalize(url)
                    if is_blocked(dom) or key in seen or key in run_keys:
                        continue
                    if BAD_TITLE.search(title) or not GOOD_WORDS.search(f"{title} {body}"):
                        continue
                    if per_domain.get(dom, 0) >= MAX_PER_DOMAIN:
                        continue
                    run_keys.add(key)
                    per_domain[dom] = per_domain.get(dom, 0) + 1
                    found[category].append({"key": key, "url": url, "title": title, "body": body})
                time.sleep(2)
    return found


# ---------------------------------------------------------------- telegram
def send(text: str) -> bool:
    r = requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        json={
            "chat_id": CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=30,
    )
    if not r.ok:
        print("telegram error:", r.text, file=sys.stderr)
    return r.ok


def main() -> None:
    if not TOKEN or not CHAT_ID:
        sys.exit("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID secrets.")

    seen = load_seen()
    found = search_all(seen)
    today = datetime.now(timezone.utc).date().isoformat()

    budget = MAX_PER_RUN
    sent_any = False
    for category, items in found.items():
        items = items[:budget]
        if not items:
            continue
        lines = [f"<b>{html.escape(category)}</b>"]
        for it in items:
            title = html.escape(it["title"][:90] or it["key"])
            desc = html.escape(re.sub(r"\s+", " ", it["body"])[:140])
            lines.append(f'\n• <a href="{html.escape(it["url"], quote=True)}">{title}</a>\n{desc}')
        if send("\n".join(lines)):
            for it in items:
                seen[it["key"]] = today
            budget -= len(items)
            sent_any = True
        time.sleep(1)
        if budget <= 0:
            break

    save_seen(seen)
    print("sent new offers" if sent_any else "nothing new this scan")


if __name__ == "__main__":
    main()
