import logging
import yt_dlp

DEFAULT_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/125.0.0.0 Safari/537.36'
    ),
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer': 'https://www.tiktok.com/',
}

_YDL_OPTS = {
    'quiet': True,
    'no_warnings': True,
    'skip_download': True,
    'noplaylist': True,
    'socket_timeout': 30,
    'retries': 3,
    'fragment_retries': 3,
    'http_headers': DEFAULT_HEADERS,
    'extractor_args': {
        'tiktok': {
            'app_name': ['trill'],
        }
    },
}


def _quality_key(f):
    label = f"{f.get('format_id') or ''} {f.get('format_note') or ''}".lower()
    no_watermark_bonus = 1 if 'download' in label else 0
    return (
        no_watermark_bonus,
        f.get('filesize') or f.get('filesize_approx') or 0,
        f.get('tbr') or 0,
        f.get('height') or 0,
    )


def _av_formats(info):
    formats = info.get('formats') or []
    av = [f for f in formats
          if f.get('url') and f.get('vcodec') not in ('none', None, '')
          and f.get('acodec') not in ('none', None, '')]
    if not av:
        av = [f for f in formats if f.get('url') and f.get('vcodec') not in ('none', None, '')]
    if not av:
        av = [f for f in formats if f.get('url')]
    av.sort(key=_quality_key, reverse=True)
    return av


def fetch_ytdlp_preview(video_url):
    """
    yt-dlp দিয়ে Normal ভিডিওর তথ্য (টাইটেল/থাম্বনেইল/অথর) বের করে —
    download=False, তাই দ্রুত ও কোনো ভিডিও bytes সরায় না। sd_url এখানে আর
    ব্যবহার হয় না ডাউনলোডের জন্য (কারণ TikTok-এর signed URL অন্য কোনো
    আলাদা HTTP কানেকশন দিয়ে পরে fetch করলে 403 Forbidden দেয় — একই yt-dlp
    সেশনে extract+download একসাথে করতে হয়, দেখুন download_normal_video)।
    কোনো paid API লাগে না, তাই এই প্রিভিউ সম্পূর্ণ ফ্রি ও আনলিমিটেড।

    'maybe_photo': True মানে — এটা normal video না-ও হতে পারে (TikTok
    Photo/Slideshow পোস্ট হতে পারে, যেটা yt-dlp সাপোর্ট করে না); সেক্ষেত্রে
    ফ্রন্টএন্ড ইউজারকে HD/Photo (paid, quota-gated) পথে পাঠাবে।
    """
    try:
        with yt_dlp.YoutubeDL(_YDL_OPTS) as ydl:
            info = ydl.extract_info(video_url, download=False)
    except yt_dlp.utils.DownloadError as e:
        err_msg = str(e)
        logging.info(f"yt-dlp preview failed (may be photo post or private): {err_msg}")
        if 'private' in err_msg.lower():
            return {'success': False, 'error': 'ভিডিওটি প্রাইভেট।', 'maybe_photo': False}
        return {'success': False, 'error': 'ভিডিও পাওয়া যায়নি।', 'maybe_photo': True}
    except Exception as e:
        logging.error(f"yt-dlp preview unexpected error: {e}")
        return {'success': False, 'error': 'ভিডিও প্রসেস করতে সমস্যা হয়েছে।', 'maybe_photo': True}

    if not info:
        return {'success': False, 'error': 'কোনো তথ্য পাওয়া যায়নি।', 'maybe_photo': True}

    av = _av_formats(info)
    if not av and not info.get('url'):
        return {'success': False, 'error': 'ভিডিও পাওয়া যায়নি।', 'maybe_photo': True}

    return {
        'success': True,
        'title': info.get('title') or 'Untitled Video',
        'author': info.get('uploader') or info.get('uploader_id') or 'Unknown',
        'thumbnail': info.get('thumbnail') or '',
        'duration': info.get('duration') or 0,
    }


def download_normal_video(video_url, dest_dir):
    """
    Normal ভিডিও — yt-dlp দিয়ে 'extract করো এবং একই সেশনে সাথে সাথে
    download করো' (download=True) — দুটো ধাপ আলাদা করা হয় না।

    কেন এটা লাগলো: আগে আমরা yt-dlp দিয়ে শুধু লিংক বের করে সেটা সেভ রাখতাম,
    পরে ইউজার ক্লিক করলে আলাদা একটা requests.get() কল দিয়ে সেই লিংক ফেচ
    করতাম — কিন্তু TikTok-এর signed CDN URL এভাবে "আলাদা কানেকশনে পরে
    ফেচ করা" বরদাস্ত করে না, 403 Forbidden দেয় (আমরা লাইভ টেস্টে এটা
    দেখেছি)। yt-dlp নিজে extract+download একই ধারাবাহিক সেশনে করলে এটা
    কাজ করে (কমান্ড-লাইনে yt-dlp ব্যবহার করলে যেভাবে সবসময় কাজ করে, ঠিক
    সেভাবেই)।

    ভিডিওটা temp ফাইলে সেভ হয়, ব্যবহারের পরপরই app.py ডিলিট করে দেয় —
    স্থায়ীভাবে ডিস্কে কিছু জমা থাকে না।
    """
    import os
    import glob
    import uuid

    os.makedirs(dest_dir, exist_ok=True)
    file_id = uuid.uuid4().hex
    outtmpl = os.path.join(dest_dir, file_id + '.%(ext)s')

    def _cleanup_partial():
        """ব্যর্থ/অসম্পূর্ণ ডাউনলোডের কোনো অবশিষ্ট ফাইল (.part, .mp4, .ytdl
        ইত্যাদি — yt-dlp resume-এর জন্য যেগুলো রেখে দেয়) সাথে সাথে মুছে
        ফেলে, যাতে বারবার ব্যর্থ চেষ্টায় ডিস্ক ভরে না যায়।"""
        for f in glob.glob(os.path.join(dest_dir, file_id + '.*')):
            try:
                os.remove(f)
            except OSError:
                pass

    opts = dict(_YDL_OPTS)
    opts.update({
        'skip_download': False,
        'outtmpl': outtmpl,
        'format': 'best',
        'max_filesize': 250 * 1024 * 1024,  # নিরাপত্তার জন্য ২৫০MB ক্যাপ (অস্বাভাবিক বড় ফাইল প্রত্যাখ্যান)
        'noprogress': True,
    })

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(video_url, download=True)
            filepath = ydl.prepare_filename(info)
    except yt_dlp.utils.DownloadError as e:
        logging.error(f"yt-dlp full download failed: {e}")
        _cleanup_partial()
        return {'success': False, 'error': 'ভিডিও ডাউনলোড করতে ব্যর্থ হয়েছে, একটু পর আবার চেষ্টা করুন।'}
    except Exception as e:
        logging.error(f"yt-dlp full download unexpected error: {e}")
        _cleanup_partial()
        return {'success': False, 'error': 'ভিডিও প্রসেস করতে সমস্যা হয়েছে।'}

    if not filepath or not os.path.exists(filepath):
        _cleanup_partial()
        return {'success': False, 'error': 'ভিডিও ফাইল তৈরি হয়নি।'}

    return {
        'success': True,
        'filepath': filepath,
        'title': info.get('title') or 'Untitled Video',
    }
