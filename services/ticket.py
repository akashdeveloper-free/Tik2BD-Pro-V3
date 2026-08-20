"""
/media/stream-এর জন্য short-lived, cryptographically-signed ticket সিস্টেম।

কেন লাগে: /media/stream আগে শুধু host-allowlist দিয়ে সুরক্ষিত ছিল — মানে
যেকোনো valid TikTok-CDN URL দিয়ে যে কেউ (এমনকি আমাদের app ব্যবহার না করেই,
সরাসরি curl/script দিয়ে) এই এন্ডপয়েন্ট hit করে আমাদের সার্ভারের bandwidth
খরচ করাতে পারতো (rate-limit থাকলেও, প্রতি মিনিটে কয়েকবার তো পারতোই)।

এখন /media/premium যখন hd_url/images রিটার্ন করে, প্রতিটা URL-এর সাথে একটা
স্বল্পস্থায়ী (৫ মিনিট) সাইন করা ticket-ও দেয়। /media/stream ticket যাচাই
করে দেখে এটা (ক) আমাদের সার্ভার নিজেই ইস্যু করেছিল, (খ) ঠিক এই URL-এর
জন্যই, (গ) মেয়াদ শেষ হয়নি — এই তিনটে না মিললে রিকোয়েস্ট প্রত্যাখ্যান হয়।
ফলে এখন /media/stream আর "open proxy" না — শুধু আমাদের নিজের অ্যাপের
সাম্প্রতিক /media/premium রেসপন্স থেকেই আসা রিকোয়েস্টই কাজ করবে।
"""

import hashlib
import hmac
import os
import time

# সব gunicorn worker-এ একই secret দরকার (নাহলে worker A-র ইস্যু করা ticket
# worker B verify করতে পারবে না)। ডেডিকেটেড APP_SECRET_KEY env var দেওয়া
# থাকলে সেটা ব্যবহার হয়; না থাকলে আগে থেকে কনফিগার করা অন্য secret-ভ্যালু
# (সব worker-এ env var হিসেবে একই থাকে)-গুলো মিলিয়ে একটা স্থিতিশীল secret
# ডেরাইভ করা হয় — তাই ইউজারকে নতুন করে কিছু সেট করতে হয় না।
_SECRET = os.environ.get('APP_SECRET_KEY') or hashlib.sha256(
    (
        os.environ.get('UPSTASH_REDIS_REST_TOKEN', '')
        + '|' + os.environ.get('API_KEYS', '')
        + '|tik2bd-static-fallback-secret'
    ).encode('utf-8')
).hexdigest()

TICKET_TTL_SECONDS = 5 * 60  # ৫ মিনিট — ইউজার ক্লিক করে ডাউনলোড শুরু করার জন্য যথেষ্ট


def issue_ticket(url):
    """একটা URL-এর জন্য নতুন ticket বানায়: '<expiry_ts>.<hmac_hex>'।"""
    expiry = int(time.time()) + TICKET_TTL_SECONDS
    sig = hmac.new(_SECRET.encode(), f'{expiry}|{url}'.encode(), hashlib.sha256).hexdigest()
    return f'{expiry}.{sig}'


def verify_ticket(url, ticket):
    """Ticket এই নির্দিষ্ট URL-এর জন্য বৈধ ও মেয়াদহীন না হলে True।"""
    if not ticket or '.' not in ticket:
        return False
    expiry_str, _, sig = ticket.partition('.')
    try:
        expiry = int(expiry_str)
    except ValueError:
        return False
    if time.time() > expiry:
        return False
    expected = hmac.new(_SECRET.encode(), f'{expiry}|{url}'.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)
