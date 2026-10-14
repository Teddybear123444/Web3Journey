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
