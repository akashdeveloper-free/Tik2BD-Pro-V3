"""
সাধারণ Flood / Bot-Abuse Protection।

Normal ভিডিও ডাউনলোডে কোনো "৫টা কোটা" নেই (সেটা শুধু HD/Photo-র জন্য,
services/limiter.py দেখুন) — কিন্তু "আনলিমিটেড" মানে এই না যে কোনো bot বা
script সেকেন্ডে শত শত রিকোয়েস্ট পাঠিয়ে সার্ভার/yt-dlp/TikTok-কে স্প্যাম
করতে পারবে। তাই প্রতিটা endpoint-এ এই generic per-IP rate-limit বসানো হয়,
যেটা সাধারণ ব্যবহারকারীর কাছে কখনো দৃশ্যমানই হবে না।
"""

import os
import sqlite3
import time
import threading

DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data')
DB_PATH = os.path.join(DB_DIR, 'ratelimit.db')

_lock = threading.RLock()

# প্রতি IP-তে প্রতি মিনিটে সর্বোচ্চ কতগুলো রিকোয়েস্ট — .env-এ RATE_LIMIT_PER_MIN
# দিয়ে override করা যায়। ডিফল্ট ২০/মিনিট একজন সাধারণ মানুষের জন্য যথেষ্টর
# চেয়ে বেশি, কিন্তু script-ভিত্তিক স্প্যাম আটকাতে যথেষ্ট কম।
MAX_REQUESTS_PER_MINUTE = int(os.environ.get('RATE_LIMIT_PER_MIN', '20'))

# ভারী অপারেশনের (Normal ভিডিওর পুরো সার্ভার-সাইড ডাউনলোড) জন্য আলাদা,
# কড়া সীমা — কারণ এতে সার্ভারের bandwidth/CPU/ডিস্ক সরাসরি খরচ হয়, তাই
# সাধারণ ২০/মিনিট এখানে অনেক বেশি (স্প্যাম করলে দ্রুত Render-এর মাসিক
# bandwidth শেষ করে দিতে পারত)।
HEAVY_MAX_REQUESTS_PER_MINUTE = int(os.environ.get('HEAVY_RATE_LIMIT_PER_MIN', '6'))
WINDOW_SECONDS = 60


def _get_conn():
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute('PRAGMA journal_mode=WAL')
    return conn


def init_db():
    with _lock, _get_conn() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS request_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ip TEXT NOT NULL,
                ts REAL NOT NULL
            )
        ''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_req_log_ip_ts ON request_log (ip, ts)')
        conn.commit()


def allow(ip, bucket='default', max_per_minute=None):
    """
    রিকোয়েস্ট অনুমোদিত হলে True, স্প্যাম-থ্রেশহোল্ড পার হলে False।

    `bucket` — একই IP-র জন্য আলাদা আলাদা কাউন্টার রাখতে (যেমন 'default'
    সাধারণ রিকোয়েস্টের জন্য, 'heavy' ভারী/costly অপারেশনের জন্য আলাদা,
    কড়া সীমায়) — যাতে হালকা রিকোয়েস্ট (পেজ লোড, স্ট্যাটাস চেক) ভারী
    অপারেশনের কোটা না খেয়ে ফেলে, আর উল্টোটাও না হয়।
    `max_per_minute` — না দিলে ডিফল্ট MAX_REQUESTS_PER_MINUTE ব্যবহার হয়।

    SQLite write-lock (বিরল, একাধিক worker concurrent হলে) এর ক্ষেত্রে
    fail-open করা হয় — অর্থাৎ ডেটাবেস সাময়িক ব্যস্ত থাকলে সাধারণ ইউজারকে
    ভুলবশত ব্লক না করে রিকোয়েস্ট যেতে দেওয়া হয় (এটা শুধু anti-abuse স্তর,
    আসল কোটা লিমিটার/limiter.py fail-open করে না)।
    """
    limit = max_per_minute if max_per_minute is not None else MAX_REQUESTS_PER_MINUTE
    now = time.time()
    key = f'{bucket}:{ip}'
    try:
        with _lock, _get_conn() as conn:
            conn.execute('DELETE FROM request_log WHERE ts < ?', (now - WINDOW_SECONDS,))
            cur = conn.execute(
                'SELECT COUNT(*) FROM request_log WHERE ip=? AND ts > ?',
                (key, now - WINDOW_SECONDS)
            )
            count = cur.fetchone()[0]
            if count >= limit:
                conn.commit()
                return False
            conn.execute('INSERT INTO request_log (ip, ts) VALUES (?, ?)', (key, now))
            conn.commit()
    except sqlite3.OperationalError:
        return True
    return True


init_db()
