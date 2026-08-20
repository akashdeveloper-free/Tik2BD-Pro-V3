from flask import Flask, render_template, request, jsonify, g, Response, stream_with_context
from werkzeug.middleware.proxy_fix import ProxyFix
import os
import re
import secrets
import tempfile
import time
import threading
from urllib.parse import urlparse

import requests as cdn_requests

from services.api_handler import fetch_hd_or_photo
from services.rapidapi_cache import get_cached, set_cached
from services.ytdlp_handler import fetch_ytdlp_preview, download_normal_video
from services import limiter
from services import rate_limiter
from services import ticket as ticket_service
from utils.validators import is_valid_tiktok_url, is_same_origin
from services.logger import logger

app = Flask(__name__, template_folder='templates', static_folder='static')

# Normal ভিডিও ডাউনলোডের সময় yt-dlp সাময়িকভাবে যেখানে ফাইল সেভ করে,
# ইউজারকে পাঠানোর পরপরই ডিলিট হয়ে যায় — স্থায়ীভাবে কিছু জমে থাকে না।
NORMAL_DL_TMP_DIR = os.path.join(tempfile.gettempdir(), 'tik2bd_normal_dl')


def _cleanup_stale_temp_files():
    """সার্ভার ক্র্যাশ/রিস্টার্ট হলে (Render ফ্রি টায়ারে যা মাঝেমধ্যেই হয়)
    আগের কোনো অসম্পূর্ণ Normal-ডাউনলোড টেম্প ফাইল ডিস্কে আটকে থাকতে
    পারে — স্টার্টআপে ১ ঘণ্টার বেশি পুরনো যেকোনো ফাইল মুছে ফেলা হয়।"""
    try:
        if not os.path.isdir(NORMAL_DL_TMP_DIR):
            return
        cutoff = time.time() - 3600
        for fname in os.listdir(NORMAL_DL_TMP_DIR):
            fpath = os.path.join(NORMAL_DL_TMP_DIR, fname)
            try:
                if os.path.isfile(fpath) and os.path.getmtime(fpath) < cutoff:
                    os.remove(fpath)
            except OSError:
                pass
    except OSError:
        pass


_cleanup_stale_temp_files()


def _background_ytdlp_updater():
    """
    Procfile-এ প্রতিটা রিস্টার্টে লাইভ `pip install -U yt-dlp` করা হতো —
    এতে প্রতিটা রিস্টার্ট ধীর হতো, আর কোনো faulty নতুন ভার্সন এলে সরাসরি
    লাইভ অ্যাপ ভেঙে যাওয়ার ঝুঁকি ছিল। এখন এটা সরিয়ে, বদলে একটা নিরাপদ
    background থ্রেড দিনে একবার (২৪ ঘণ্টা পরপর) yt-dlp আপডেট চেক করে —
    subprocess-এ, main app থ্রেড থেকে সম্পূর্ণ আলাদা, তাই ব্যর্থ হলেও
    (নেটওয়ার্ক/pip এরর) চলমান অ্যাপ কখনো ক্র্যাশ করে না বা ব্লক হয় না।
    নতুন ভার্সন ইনস্টল হলেও এই *চলমান* প্রসেসে সাথে সাথে কার্যকর হয় না
    (Python-এর স্বাভাবিক সীমাবদ্ধতা) — পরের ডিপ্লয়/রিস্টার্টে কার্যকর হবে,
    যেটা যথেষ্ট নিরাপদ কারণ TikTok প্রতিদিন বদলায় না।
    """
    import subprocess
    import sys

    def _run():
        while True:
            try:
                time.sleep(24 * 60 * 60)  # প্রথমবার অ্যাপ স্টার্ট হওয়ার ২৪ ঘণ্টা পর
                logger.info("Background yt-dlp update check starting...")
                result = subprocess.run(
                    [sys.executable, '-m', 'pip', 'install', '--upgrade', '--quiet', 'yt-dlp'],
                    capture_output=True, text=True, timeout=120,
                )
                if result.returncode == 0:
                    logger.info("Background yt-dlp update check completed successfully.")
                else:
                    logger.warning(f"Background yt-dlp update failed (non-fatal): {result.stderr[:300]}")
            except Exception as e:
                logger.warning(f"Background yt-dlp update error (non-fatal): {e}")

    t = threading.Thread(target=_run, daemon=True)
    t.start()


_background_ytdlp_updater()

# Render (এবং প্রায় সব ক্লাউড হোস্ট) নিজে একটা রিভার্স-প্রক্সির পেছনে অ্যাপ
# চালায়। ProxyFix ছাড়া request.remote_addr সবসময় Render-এর ইন্টারনাল প্রক্সি
# IP দেখাবে (সব ইউজার একটাই IP-তে "মিশে" যাবে), অথবা raw X-Forwarded-For
# হেডার নিজে পার্স করলে ইউজার ভুয়া হেডার পাঠিয়ে IP spoof করে রেট-লিমিট ও
# দৈনিক কোটা বাইপাস করতে পারত। x_for=1 মানে ঠিক ১টা বিশ্বস্ত প্রক্সি হপ
# (Render-এর নিজের) — এটাই XFF-এর সঠিক (শেষের) মানটা বিশ্বাস করে, ইউজারের
# পাঠানো ভুয়া আগের এন্ট্রিগুলো উপেক্ষা করে।
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

DEVICE_COOKIE_NAME = 'tik2bd_device'
DEVICE_COOKIE_MAX_AGE = 60 * 60 * 24 * 365  # ১ বছর


def _client_ip():
    # ProxyFix ইতিমধ্যে request.remote_addr-কে সঠিক real client IP দিয়ে
    # রিপ্লেস করে দিয়েছে (X-Forwarded-For হাতে পার্স করার দরকার নেই আর,
    # ওটা করলে spoofing-এর ঝুঁকি থাকত)।
    return request.remote_addr or 'unknown'


def _get_or_create_device_id():
    existing = request.cookies.get(DEVICE_COOKIE_NAME)
    if existing:
        return existing
    if not hasattr(g, '_new_device_id'):
        g._new_device_id = secrets.token_urlsafe(24)
    return g._new_device_id


@app.after_request
def add_device_cookie(response):
    if not request.cookies.get(DEVICE_COOKIE_NAME) and hasattr(g, '_new_device_id'):
        response.set_cookie(
            DEVICE_COOKIE_NAME,
            g._new_device_id,
            max_age=DEVICE_COOKIE_MAX_AGE,
            httponly=True,
            samesite='Lax',
            secure=request.is_secure,
        )
    return response


@app.after_request
def add_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    return response


def _guard(video_url):
    """সব ডাউনলোড-সম্পর্কিত রুটের কমন যাচাই: valid URL + same-origin +
    anti-flood। সমস্যা থাকলে (error_response, status_code) রিটার্ন করে,
    ঠিক থাকলে None।"""
    if not is_valid_tiktok_url(video_url):
        return jsonify({'success': False, 'error': 'সঠিক TikTok লিংক দিন।'}), 400
    if not is_same_origin(request):
        logger.warning("Blocked cross-origin request.")
        return jsonify({'success': False, 'error': 'Forbidden'}), 403
    if not rate_limiter.allow(_client_ip()):
        return jsonify({'success': False, 'error': 'অনেক বেশি রিকোয়েস্ট, একটু পর চেষ্টা করুন।'}), 429
    return None


# TikTok/ByteDance-এর CDN ডোমেইনগুলোর allowlist — /media/stream শুধু এই
# হোস্টগুলোর URL-ই ফেচ করবে, অন্য কোনো (attacker-controlled) হোস্ট না —
# এটাই SSRF ঠেকানোর মূল সুরক্ষা। TikTok একাধিক CDN ব্র্যান্ড/শর্ট-ডোমেইন
# ব্যবহার করে (রিজিওন/এজ-নোড অনুযায়ী পাল্টায়), তাই তালিকাটা ইচ্ছাকৃতভাবে
# বিস্তৃত রাখা হয়েছে — কোনো নতুন CDN ডোমেইনে ৪০০ এরর এলে এখানে যোগ করলেই
# হবে (server লগে ঠিক কোন হোস্ট ব্লক হয়েছে সেটা লেখা থাকে)।
ALLOWED_CDN_HOST_SUFFIXES = (
    'tiktokcdn.com', 'tiktokcdn-us.com', 'tiktokcdn-eu.com', 'tiktokcdn-in.com',
    'tiktokv.com', 'tiktokv.us', 'muscdn.com', 'ibyteimg.com', 'byteicdn.com',
    'tokcdn.com',        # যেমন v16.tokcdn.com — TikTok-এর সংক্ষিপ্ত CDN ব্র্যান্ড
    'ttwstatic.com', 'byteoversea.com', 'sgpstatp.com', 'ibytedtos.com',
    'tiktok.com',  # yt-dlp-এর Normal ভিডিও লিংক এই ডোমেইনের সাব-ডোমেইন থেকে আসে
)


def _is_allowed_cdn_url(url):
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    return any(host == s or host.endswith('.' + s) for s in ALLOWED_CDN_HOST_SUFFIXES)


@app.route('/')
def home():
    return render_template('index.html')


@app.route('/download', methods=['POST'])
def download():
    """
    Normal ভিডিওর প্রিভিউ (টাইটেল/থাম্বনেইল/অথর) — সম্পূর্ণ ফ্রি, yt-dlp দিয়ে,
    কোনো paid API লাগে না, কোনো দৈনিক লিমিট নেই। এখানে কোনো CDN লিংক
    রিটার্ন করা হয় না (TikTok-এর signed URL একবার extract করার পর আলাদা
    কানেকশনে পরে fetch করলে 403 দেয়) — আসল ডাউনলোড হয় /media/normal-download
    এন্ডপয়েন্টে ক্লিক করার মুহূর্তে, fresh extract+download একসাথে করে।
    """
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'success': False, 'error': 'Invalid request.'}), 400

    video_url = data.get('url', '').strip()
    guard_error = _guard(video_url)
    if guard_error:
        return guard_error

    logger.info(f"Processing normal preview for: {video_url}")
    preview = fetch_ytdlp_preview(video_url)

    if preview.get('success'):
        return jsonify({
            'success': True,
            'kind': 'video',
            'title': preview['title'],
            'author': preview['author'],
            'thumbnail': preview['thumbnail'],
            'duration': preview['duration'],
        })

    if preview.get('maybe_photo'):
        # স্বাভাবিক ভিডিও পাওয়া যায়নি — সম্ভবত এটা Photo পোস্ট। নিশ্চিত
        # হতে paid API লাগবে, তাই এখানেই সেটা কল করা হচ্ছে না — ইউজার
        # আলাদা বাটনে ক্লিক করলে তবেই /media/premium কল হবে (কোটা প্রযোজ্য)।
        return jsonify({'success': True, 'kind': 'unknown', 'hint': 'photo_or_unavailable'})

    return jsonify({'success': False, 'error': preview.get('error', 'ভিডিও পাওয়া যায়নি।')}), 400


@app.route('/media/normal-download', methods=['POST'])
def media_normal_download():
    """
    Normal ভিডিও — আসল ডাউনলোড। yt-dlp দিয়ে extract+download একই সেশনে
    (fresh, ক্লিক করার মুহূর্তেই) করে, তারপর ফাইলটা ইউজারের কাছে স্ট্রিম
    করে দিয়ে সাথে সাথে ডিলিট করে দেয়। কোনো paid API/দৈনিক কোটা এখানে
    লাগে না — সম্পূর্ণ আনলিমিটেড, তবে Render-এর bandwidth এখানে খরচ হয়
    (এটা অনিবার্য, TikTok-এর CDN protection-এর কারণে — বিস্তারিত কারণ
    services/ytdlp_handler.py-তে লেখা আছে)।
    """
    data = request.get_json(silent=True) or {}
    video_url = data.get('url', '').strip()
    guard_error = _guard(video_url)
    if guard_error:
        return guard_error

    # সাধারণ ২০/মিনিট রেট-লিমিট ছাড়াও এই রুটের জন্য আলাদা, কড়া সীমা —
    # কারণ প্রতিটা কল সরাসরি সার্ভারের bandwidth/CPU/ডিস্ক খরচ করে।
    if not rate_limiter.allow(_client_ip(), bucket='heavy', max_per_minute=rate_limiter.HEAVY_MAX_REQUESTS_PER_MINUTE):
        return jsonify({'success': False, 'error': 'একটু বেশি দ্রুত ডাউনলোড চেষ্টা হচ্ছে, কিছুক্ষণ পর আবার চেষ্টা করুন।'}), 429

    logger.info(f"Normal video full-download starting for: {video_url}")
    result = download_normal_video(video_url, NORMAL_DL_TMP_DIR)

    if not result.get('success'):
        logger.error(f"Normal video download failed: {result.get('error')}")
        return jsonify(result), 502

    filepath = result['filepath']
    filename = re.sub(r'[^\w.\-]', '_', os.path.basename(filepath))[:100] or 'tiktok_normal.mp4'

    def _generate():
        try:
            with open(filepath, 'rb') as f:
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    yield chunk
        finally:
            try:
                os.remove(filepath)
            except OSError:
                pass

    file_size = os.path.getsize(filepath)
    resp_headers = {
        'Content-Disposition': f'attachment; filename="{filename}"',
        'Content-Type': 'video/mp4',
        'Content-Length': str(file_size),
        'Cache-Control': 'no-store',
    }
    return Response(stream_with_context(_generate()), headers=resp_headers, status=200)


@app.route('/media/premium', methods=['POST'])
def media_premium():
    """
    HD ভিডিও + Photo স্লাইডশো — একমাত্র জায়গা যেখানে RapidAPI (paid) কল
    হয়। প্রতিদিন (রাত ১২টায়, বাংলাদেশ সময়ে রিসেট) সর্বোচ্চ DAILY_LIMIT বার
    ব্যবহারযোগ্য — HD ও Photo মিলিয়ে একই কোটা।

    ক্রম গুরুত্বপূর্ণ: কোটা আগে atomic-ভাবে রিজার্ভ করা হয় (limiter.try_consume),
    *তারপর* paid API কল হয় — উল্টো ক্রমে (আগে API কল, পরে কোটা চেক) করলে
    concurrent রিকোয়েস্টে কোটা limit পার হয়েও অতিরিক্ত paid কল হয়ে যেতে
    পারতো (কারণ চেক আর কনজিউম তখন এক atomic ধাপ ছিল না)। API কল ব্যর্থ
    হলে রিজার্ভেশন limiter.release() দিয়ে ফেরত দেওয়া হয়, তাই ব্যর্থ চেষ্টায়
    ইউজারের কোটা নষ্ট হয় না।

    রেসপন্সে প্রতিটা CDN URL-এর সাথে একটা স্বল্পস্থায়ী ticket-ও পাঠানো হয়,
    যেটা /media/stream ফলব্যাকে লাগে (দেখুন services/ticket.py) — এতে
    /media/stream কখনো "open proxy" হিসেবে ব্যবহার করা যায় না।
    """
    data = request.get_json(silent=True) or {}
    video_url = data.get('url', '').strip()
    guard_error = _guard(video_url)
    if guard_error:
        return guard_error

    ip = _client_ip()
    device_id = _get_or_create_device_id()

    # ধাপ ১: আগে কোটা atomic-ভাবে রিজার্ভ করো (paid API কলের আগেই)
    allowed, status = limiter.try_consume(ip, device_id)
    if not allowed:
        return jsonify({'success': False, 'error': 'limit_reached', 'limit_status': status}), 429

    # ধাপ ২: তারপর ক্যাশ/paid API থেকে ডেটা আনো
    cached = get_cached(video_url)
    if cached and cached.get('success'):
        logger.info("Cache hit — RapidAPI call বাঁচলো।")
        result = cached
    else:
        result = fetch_hd_or_photo(video_url)
        if result.get('success'):
            set_cached(video_url, result)

    if not result.get('success'):
        logger.error(f"Premium fetch failed: {result.get('error')}")
        limiter.release(ip, device_id)  # ব্যর্থ হলে রিজার্ভেশন ফেরত দাও
        return jsonify(result), 400

    # সফল — CDN URL-গুলোতে স্বল্পস্থায়ী ticket যোগ করো (/media/stream-এর জন্য)
    if result.get('is_photo'):
        result['images'] = [
            {'url': u, 'ticket': ticket_service.issue_ticket(u)} for u in result.get('images', [])
        ]
    elif result.get('hd_url'):
        result['hd_ticket'] = ticket_service.issue_ticket(result['hd_url'])

    result['limit_status'] = status
    logger.info("Premium (HD/Photo) granted, quota consumed.")
    return jsonify(result)


@app.route('/media/status')
def media_status():
    """UI-তে 'আজকে কতটা HD/Photo বাকি' badge দেখানোর জন্য — কিছু কনজিউম করে না।"""
    status = limiter.get_status(_client_ip(), _get_or_create_device_id())
    return jsonify(status)


@app.route('/media/stream')
def media_stream():
    """
    HD/Photo ফলব্যাক পাস-থ্রু — ব্রাউজার নিজে সরাসরি RapidAPI-র CDN থেকে
    ফেচ করতে ব্যর্থ হলে (কদাচিৎ, কোনো নির্দিষ্ট CDN নোডে CORS ব্লক থাকলে)
    তখনই ফ্রন্টএন্ড এই রুটে ফলব্যাক করে। সাধারণত HD/Photo সরাসরি ব্রাউজার
    থেকেই ডাউনলোড হয় (zero bandwidth) — এটা শুধু নিরাপত্তা-জাল হিসেবে থাকে।
    (Normal ভিডিও আর এই রুট ব্যবহার করে না — /media/normal-download দেখুন,
    কারণ TikTok-এর signed URL এভাবে আলাদা কানেকশনে পরে fetch করলে ৪০৩ দেয়।)
    """
    cdn_url = request.args.get('url', '').strip()
    filename = request.args.get('filename', 'tiktok.mp4').strip()
    filename = re.sub(r'[^\w.\-]', '_', filename)[:100] or 'tiktok.mp4'
    ticket = request.args.get('ticket', '').strip()

    if not cdn_url or not _is_allowed_cdn_url(cdn_url):
        logger.warning(f"Blocked /media/stream — disallowed host: {cdn_url}")
        return jsonify({'error': 'Invalid or disallowed URL.'}), 400

    # Ticket যাচাই — এটাই মূল সুরক্ষা যেটা /media/stream-কে "open proxy"
    # হওয়া থেকে আটকায়। এই ticket শুধু /media/premium ইস্যু করে (দেখুন
    # services/ticket.py), তাই আমাদের নিজের অ্যাপের সাম্প্রতিক
    # /media/premium রেসপন্স ছাড়া কেউ এই এন্ডপয়েন্ট ব্যবহার করতে পারবে না।
    if not ticket_service.verify_ticket(cdn_url, ticket):
        logger.warning(f"Blocked /media/stream — invalid/expired/missing ticket for: {cdn_url}")
        return jsonify({'error': 'Invalid or expired request.'}), 403

    if not is_same_origin(request):
        logger.warning("Blocked cross-origin /media/stream request.")
        return jsonify({'error': 'Forbidden'}), 403

    if not rate_limiter.allow(_client_ip()):
        return jsonify({'error': 'অনেক বেশি রিকোয়েস্ট, একটু পর চেষ্টা করুন।'}), 429

    headers = {
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/125.0.0.0 Safari/537.36'
        ),
        'Referer': 'https://www.tiktok.com/',
    }

    try:
        cdn_resp = cdn_requests.get(
            cdn_url, headers=headers, stream=True, timeout=60, allow_redirects=True
        )
        cdn_resp.raise_for_status()
    except cdn_requests.Timeout:
        return jsonify({'error': 'Download timed out, please try again.'}), 504
    except cdn_requests.RequestException as e:
        logger.error(f"media_stream fetch error: {e}")
        return jsonify({'error': 'Media fetch failed, please try again.'}), 502

    # রিডাইরেক্ট অনুসরণ করার পর চূড়ান্ত URL-টাও আবার allowlist-এর বিপরীতে
    # যাচাই করা হয় — নাহলে allowlist-এ থাকা কোনো হোস্ট (থিওরিটিক্যালি) অন্য
    # কোনো হোস্টে রিডাইরেক্ট করলে সেটাই ফেচ হয়ে যেত, allowlist বাইপাস হতো।
    if not _is_allowed_cdn_url(cdn_resp.url):
        cdn_resp.close()
        logger.warning(f"Blocked /media/stream — redirect led to disallowed host: {cdn_resp.url}")
        return jsonify({'error': 'Invalid or disallowed URL.'}), 400


    resp_headers = {
        'Content-Disposition': f'attachment; filename="{filename}"',
        'Content-Type': cdn_resp.headers.get('Content-Type', 'application/octet-stream'),
        'Cache-Control': 'no-store',
    }
    content_length = cdn_resp.headers.get('Content-Length')
    if content_length:
        resp_headers['Content-Length'] = content_length

    def _generate():
        try:
            for chunk in cdn_resp.iter_content(chunk_size=65536):
                if chunk:
                    yield chunk
        finally:
            cdn_resp.close()

    return Response(stream_with_context(_generate()), headers=resp_headers, status=200)


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8000))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host='0.0.0.0', port=port, debug=debug)
