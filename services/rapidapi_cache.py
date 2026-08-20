"""
RapidAPI রেজাল্ট ক্যাশ — Upstash Redis (services/upstash_client.py) ব্যবহার
করে, limiter.py-র সাথে একই কানেকশন-লজিক শেয়ার করে।

কেন লাগে: প্রতিটা HD/Photo রিকোয়েস্টে RapidAPI-কে একটা কল যেতো, এমনকি
একই ভিডিও লিংক বহু ভিজিটর/বহুবার চাইলেও (ভাইরাল ভিডিওতে এটা খুব সাধারণ)।
এখন একই ভিডিও URL-এর রেজাল্ট CACHE_TTL_SECONDS সময় ধরে Redis-এ থাকে,
তাই ঐ সময়ের মধ্যে আবার সেই লিংক এলে RapidAPI-কে না ডেকে ক্যাশ থেকেই
উত্তর দেওয়া যায় — মাসিক API কোটা বাঁচে। (ব্যবহারকারীর ব্যক্তিগত দৈনিক
৫টার কোটা এটা থেকে আলাদা — ক্যাশ হিট হলেও ইউজারের কোটা ঠিকই কাটে,
services/limiter.py দেখুন।)
"""

import json
import logging

from services import upstash_client

CACHE_TTL_SECONDS = 75 * 60  # ১ ঘণ্টা ১৫ মিনিট (৭৫ মিনিট)


def _key(video_url):
    return f'rapidapi:cache:{video_url}'


def get_cached(video_url):
    """ক্যাশে থাকলে সেই dict রিটার্ন করে, না থাকলে/এরর হলে None।"""
    raw = upstash_client.cmd('get', _key(video_url))
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


def set_cached(video_url, result):
    """সফল রেজাল্টই ক্যাশ করা হয় — এরর/ব্যর্থ রেজাল্ট ক্যাশ করলে সাময়িক
    সমস্যাও ৭৫ মিনিট ধরে সবার জন্য দেখাতে থাকবে, তাই সেগুলো ক্যাশ করা হয় না।"""
    if not result or not result.get('success'):
        return
    upstash_client.cmd('set', _key(video_url), json.dumps(result), 'EX', CACHE_TTL_SECONDS)
