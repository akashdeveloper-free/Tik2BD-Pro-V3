"""
প্রতি IP + ডিভাইস (কুকি) ভিত্তিক দৈনিক HD/Photo ডাউনলোড লিমিট।

- প্রতিদিন রাত ১২.০০টায় (বাংলাদেশ সময়, Asia/Dhaka) রিসেট হয়।
- এই লিমিট শুধু HD ভিডিও ও Photo ডাউনলোডে (paid API ব্যবহারকারী) প্রযোজ্য।
  Normal ভিডিও ডাউনলোডে এই লিমিট কখনো প্রযোজ্য নয় (আনলিমিটেড)।

⚠️ গুরুত্বপূর্ণ (Render-এ কেন এটা Redis-ভিত্তিক করা হলো):
Render Free ওয়েব সার্ভিস কিছুক্ষণ নিষ্ক্রিয় থাকলে ঘুমিয়ে যায়/রিস্টার্ট হয়,
আর তখন লোকাল ডিস্কে রাখা যেকোনো ফাইল (SQLite সহ) মুছে যায় — তাই আগে কোটা
বারবার "রিসেট" হয়ে যাচ্ছিল। এটা ঠিক করতে কোটা এখন Upstash Redis-এ
(এক্সটার্নাল, সার্ভার রিস্টার্ট হলেও অক্ষত থাকে) রাখা হয়। UPSTASH_REDIS_REST_URL
/ TOKEN কনফিগার করা না থাকলে লোকাল SQLite-এ ফলব্যাক করে (তখনও রিস্টার্টে
রিসেট হতে পারে) — তাই প্রোডাকশনে Upstash অবশ্যই কনফিগার করা উচিত।
"""

import os
import sqlite3
import time
import threading
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from config import DAILY_LIMIT
from services import upstash_client

DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data')
DB_PATH = os.path.join(DB_DIR, 'limiter.db')

TZ = ZoneInfo("Asia/Dhaka")
_lock = threading.RLock()


def _today_str(now=None):
    now_dt = datetime.fromtimestamp(now if now else time.time(), TZ)
    return now_dt.strftime('%Y-%m-%d')


def _today_start_epoch(now=None):
    now_dt = datetime.fromtimestamp(now if now else time.time(), TZ)
    start_of_day = now_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    return start_of_day.timestamp()


def _seconds_to_reset(now=None):
    now = now or time.time()
    return max(1, int(_today_start_epoch(now) + 24 * 60 * 60 - now))


# ============== Backend ১: Upstash Redis (প্রাইমারি, persistent) ==============

def _redis_key(ip, device_id, day_str):
    return f'quota:{ip}:{device_id}:{day_str}'


def _get_status_redis(ip, device_id):
    now = time.time()
    key = _redis_key(ip, device_id, _today_str(now))
    # ttl আগে চেক করি কারণ এটা দিয়েই "key নেই" (স্বাভাবিক, -2 রিটার্ন করে)
    # বনাম "Upstash কল-ই ব্যর্থ হয়েছে" (None রিটার্ন করে) — এই দুটো আলাদা
    # করা যায়। শুধু 'get' দিয়ে সেটা সম্ভব না (দুটো ক্ষেত্রেই None আসে)।
    ttl = upstash_client.cmd('ttl', key)
    if ttl is None:
        return None  # Upstash কল ব্যর্থ — caller fail-closed করবে
    used_raw = upstash_client.cmd('get', key)
    used = int(used_raw) if used_raw else 0
    remaining = max(0, DAILY_LIMIT - used)
    resets_in = ttl if isinstance(ttl, int) and ttl > 0 else _seconds_to_reset(now)
    return {
        'locked': remaining <= 0,
        'used': used,
        'limit': DAILY_LIMIT,
        'remaining': remaining,
        'resets_in_seconds': resets_in,
    }


def _try_consume_redis(ip, device_id):
    now = time.time()
    key = _redis_key(ip, device_id, _today_str(now))
    new_val = upstash_client.cmd('incr', key)
    if new_val is None:
        return None  # Upstash কল ব্যর্থ — caller fail-closed করবে (SQLite fallback না)
    new_val = int(new_val)
    if new_val == 1:
        # প্রথম এন্ট্রি — কী-টা ঠিক পরের মধ্যরাতে expire হয়ে যাবে (স্বয়ংক্রিয় রিসেট)
        upstash_client.cmd('expire', key, _seconds_to_reset(now))
    allowed = new_val <= DAILY_LIMIT
    return allowed, _get_status_redis(ip, device_id)


def _release_redis(ip, device_id):
    """ব্যর্থ হওয়া paid API কলের জন্য সংরক্ষিত কোটা ফেরত দেয় (রিফান্ড)।"""
    now = time.time()
    key = _redis_key(ip, device_id, _today_str(now))
    upstash_client.cmd('decr', key)


# ============== Backend ২: লোকাল SQLite (ফলব্যাক, Upstash না থাকলে) ==============

def _get_conn():
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute('PRAGMA journal_mode=WAL')
    return conn


def _init_sqlite():
    with _lock, _get_conn() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS premium_downloads (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                ip        TEXT NOT NULL,
                device_id TEXT NOT NULL,
                ts        REAL NOT NULL
            )
        ''')
        conn.execute(
            'CREATE INDEX IF NOT EXISTS idx_premium_key ON premium_downloads (ip, device_id, ts)'
        )
        conn.commit()


def _usage_count_sqlite(conn, ip, device_id, day_start):
    cur = conn.execute(
        'SELECT COUNT(*) FROM premium_downloads WHERE ip=? AND device_id=? AND ts >= ?',
        (ip, device_id, day_start)
    )
    return cur.fetchone()[0]


def _get_status_sqlite(ip, device_id):
    now = time.time()
    day_start = _today_start_epoch(now)
    with _lock, _get_conn() as conn:
        used = _usage_count_sqlite(conn, ip, device_id, day_start)
    remaining = max(0, DAILY_LIMIT - used)
    return {
        'locked': remaining <= 0,
        'used': used,
        'limit': DAILY_LIMIT,
        'remaining': remaining,
        'resets_in_seconds': _seconds_to_reset(now),
    }


def _try_consume_sqlite(ip, device_id):
    now = time.time()
    day_start = _today_start_epoch(now)
    try:
        with _lock, _get_conn() as conn:
            conn.execute('BEGIN IMMEDIATE')
            used = _usage_count_sqlite(conn, ip, device_id, day_start)
            if used >= DAILY_LIMIT:
                conn.commit()
                return False, _get_status_sqlite(ip, device_id)
            conn.execute(
                'INSERT INTO premium_downloads (ip, device_id, ts) VALUES (?, ?, ?)',
                (ip, device_id, now)
            )
            conn.commit()
    except sqlite3.OperationalError:
        return False, {
            'locked': True, 'used': 0, 'limit': DAILY_LIMIT,
            'remaining': 0, 'resets_in_seconds': 5, 'busy': True,
        }
    return True, _get_status_sqlite(ip, device_id)


def _release_sqlite(ip, device_id):
    """ব্যর্থ হওয়া paid API কলের জন্য সংরক্ষিত কোটা ফেরত দেয় — সবচেয়ে
    সাম্প্রতিক এন্ট্রিটা মুছে দেওয়া হয়।"""
    with _lock, _get_conn() as conn:
        conn.execute('''
            DELETE FROM premium_downloads WHERE id = (
                SELECT id FROM premium_downloads
                WHERE ip=? AND device_id=?
                ORDER BY ts DESC LIMIT 1
            )
        ''', (ip, device_id))
        conn.commit()


_init_sqlite()


# ============== পাবলিক API — app.py শুধু এই ফাংশনগুলো কল করে ==============
#
# ব্যবহারের ধরন (গুরুত্বপূর্ণ — atomic reserve-first pattern):
#   allowed, status = try_consume(ip, device_id)   # ধাপ ১: আগে কোটা রিজার্ভ করো
#   if not allowed: return "লিমিট শেষ"
#   result = fetch_hd_or_photo(...)                 # ধাপ ২: তারপরই paid API কল করো
#   if not result.success: release(ip, device_id)   # ব্যর্থ হলে রিজার্ভেশন ফেরত দাও
#
# আগে এই ক্রম উল্টো ছিল (আগে API কল, পরে কোটা চেক) — তাতে concurrent
# রিকোয়েস্টে quota-limit পার হয়েও কিছু অতিরিক্ত paid কল হয়ে যেতে পারতো,
# কারণ চেক-করা আর কনজিউম-করা এক ধাপে atomic ছিল না ততক্ষণে API কল হয়ে
# গেছে। এখন রিজার্ভেশনটাই আগে atomic হয়, তাই এই রেসের সুযোগ নেই।


def get_status(ip, device_id):
    """শুধু পড়ে, কিছু কনজিউম/রিজার্ভ করে না।"""
    if upstash_client.configured():
        status = _get_status_redis(ip, device_id)
        if status is not None:
            return status
        # Upstash কনফিগার করা আছে কিন্তু কল ব্যর্থ — fail-closed: ভুল/পুরনো
        # সংখ্যা দেখানোর বদলে স্পষ্টভাবে "সাময়িক অনুপলব্ধ" বলা হচ্ছে।
        return {
            'locked': True, 'used': 0, 'limit': DAILY_LIMIT,
            'remaining': 0, 'resets_in_seconds': 30, 'busy': True,
        }
    return _get_status_sqlite(ip, device_id)


def try_consume(ip, device_id):
    """কোটা রিজার্ভ করে (atomic) — ব্যর্থ হলে কল করা কোডকে release() দিয়ে
    এটা ফেরত দিতে হবে।"""
    if upstash_client.configured():
        result = _try_consume_redis(ip, device_id)
        if result is not None:
            return result
        # Upstash কনফিগার করা আছে কিন্তু কল ব্যর্থ (নেটওয়ার্ক/আউটেজ) —
        # fail-closed করা হচ্ছে, SQLite ফলব্যাকে না গিয়ে। কারণ SQLite
        # ফলব্যাক এখানে ব্যবহার করলে Upstash আউটেজের সময় কোটা কার্যত
        # bypass হয়ে যেত (আলাদা, resettable কাউন্টার শুরু হতো) — যেটা
        # ইচ্ছাকৃতভাবে Upstash ব্যবহার করা অপারেটরের জন্য নিরাপত্তার দিক
        # থেকে ভুল ডিফল্ট। SQLite ফলব্যাক শুধু তখনই ব্যবহার হয় যখন Upstash
        # আদৌ কনফিগারই করা হয়নি (ইচ্ছাকৃত পছন্দ, নিচে দেখুন)।
        logging_msg = "Upstash quota reserve failed while configured — failing closed (not falling back to SQLite)."
        logging.error(logging_msg)
        return False, {
            'locked': True, 'used': 0, 'limit': DAILY_LIMIT,
            'remaining': 0, 'resets_in_seconds': 30, 'busy': True,
        }
    # Upstash কখনোই কনফিগার করা হয়নি — এক্ষেত্রে SQLite-ই ইচ্ছাকৃত, ডকুমেন্টেড
    # প্রাইমারি ব্যাকএন্ড (README-তে ব্যাখ্যা করা আছে যে এটা রিস্টার্টে
    # রিসেট হতে পারে)।
    return _try_consume_sqlite(ip, device_id)


def release(ip, device_id):
    """try_consume()-এ রিজার্ভ করা একটা স্লট ফেরত দেয় — ব্যর্থ হওয়া paid
    API কলের জন্য ইউজারের কোটা যাতে নষ্ট না হয়। এই কলটা কখনো ব্যর্থ হলেও
    (নেটওয়ার্ক ইস্যু) নীরবে এগিয়ে যায় — সর্বোচ্চ খারাপ ফল হলো ইউজার একটা
    ব্যর্থ চেষ্টার জন্য ১টা কোটা হারাবে, যেটা ক্র্যাশের চেয়ে অনেক কম ক্ষতিকর।"""
    try:
        if upstash_client.configured():
            _release_redis(ip, device_id)
        else:
            _release_sqlite(ip, device_id)
    except Exception:
        pass
