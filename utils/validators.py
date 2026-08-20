import re
from urllib.parse import urlparse

TIKTOK_URL_PATTERN = re.compile(
    r'^(https?://)?(www\.|m\.|vm\.|vt\.)?tiktok\.com/.+',
    re.IGNORECASE
)


def is_valid_tiktok_url(url):
    """
    TikTok URL ভ্যালিডেশন। tiktok.com, www., m., vm., vt. সাবডোমেইন সাপোর্ট
    করে (আগের ভার্সনের মতোই), শুধু case-insensitive করা হয়েছে এবং একটা
    দৈর্ঘ্য-সীমা যোগ করা হয়েছে (junk/অতিরিক্ত লম্বা ইনপুট আটকাতে)।
    """
    if not url or len(url) > 2048:
        return False
    return bool(TIKTOK_URL_PATTERN.match(url.strip()))


def is_same_origin(request):
    """
    রিকোয়েস্টটা আমাদের নিজের ওয়েবসাইট থেকেই এসেছে কিনা Origin/Referer
    হেডার দিয়ে যাচাই করে। এটা fool-proof নয় (হেডার স্পুফ করা সম্ভব),
    কিন্তু casual bot/script দিয়ে সরাসরি API endpoint hit করার সবচেয়ে
    সহজ পদ্ধতিটা আটকায়। Origin/Referer একদমই না থাকলে ব্লক করা হয় না,
    কারণ কিছু বৈধ ব্রাউজার/প্রাইভেসি-সেটিংসে এই হেডার বাদ যেতে পারে।
    """
    host = request.host
    check_value = request.headers.get('Origin') or request.headers.get('Referer') or ''
    if not check_value:
        return True
    try:
        parsed_host = urlparse(check_value).netloc
    except ValueError:
        return False
    return parsed_host == host
