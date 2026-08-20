"""
Upstash Redis REST API-এর জন্য একটা ছোট শেয়ারড হেল্পার — rapidapi_cache.py
আর limiter.py দুটোই এটা ব্যবহার করে, যাতে HTTP call লজিক একবারই লেখা থাকে।
"""

import os
import logging

import requests

UPSTASH_URL = os.environ.get('UPSTASH_REDIS_REST_URL', '').rstrip('/')
UPSTASH_TOKEN = os.environ.get('UPSTASH_REDIS_REST_TOKEN', '')

_headers = {'Authorization': f'Bearer {UPSTASH_TOKEN}'}


def configured():
    return bool(UPSTASH_URL and UPSTASH_TOKEN)


def cmd(*parts):
    """
    একটা Upstash Redis REST কমান্ড চালায় (যেমন cmd('get', key) বা
    cmd('set', key, value, 'EX', ttl))। Upstash কনফিগার করা না থাকলে,
    বা নেটওয়ার্ক/API এরর হলে None রিটার্ন করে — কল করা কোড সেটা দেখে
    নিজে fallback করবে (কখনো এখানে exception raise করা হয় না)।
    """
    if not configured():
        return None
    path = '/'.join(requests.utils.quote(str(p), safe='') for p in parts)
    try:
        resp = requests.get(f'{UPSTASH_URL}/{path}', headers=_headers, timeout=10)
        resp.raise_for_status()
        return resp.json().get('result')
    except Exception as e:
        logging.warning(f"Upstash command failed (ignoring, caller will fallback): {e}")
        return None
