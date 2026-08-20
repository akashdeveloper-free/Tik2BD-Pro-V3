import requests
import logging
from config import key_manager, TIMEOUT

RAPIDAPI_URL = "https://tiktok-video-no-watermark2.p.rapidapi.com/"


def fetch_hd_or_photo(video_url):
    """
    RapidAPI ব্যবহার করে HD ভিডিও লিংক অথবা Photo-স্লাইডশো ডেটা আনে।

    ⚠️ এটাই একমাত্র জায়গা যেখানে paid API কল হয়। Normal (SD) ভিডিও ডাউনলোডে
    এই ফাংশন কখনো call করা হয় না — সেটা services/ytdlp_handler.py দিয়ে
    সম্পূর্ণ ফ্রিতে হয়। app.py-তে এই ফাংশনটা শুধুমাত্র /media/premium
    রুট থেকে কল হয়, যেটা daily-limit দিয়ে গার্ড করা।
    """
    if not key_manager.keys:
        logging.warning("No API keys configured — HD/Photo unavailable.")
        return {
            'success': False,
            'error': 'HD/Photo সার্ভিস এই মুহূর্তে কনফিগার করা নেই (API key নেই)।',
        }

    for _ in range(len(key_manager.keys)):
        key_obj = key_manager.get_active_key()

        if not key_obj:
            logging.warning("All API keys exhausted — HD/Photo unavailable.")
            return {'success': False, 'error': 'সার্ভিস সাময়িকভাবে ব্যস্ত, একটু পর চেষ্টা করুন।'}

        headers = {
            "x-rapidapi-host": "tiktok-video-no-watermark2.p.rapidapi.com",
            "x-rapidapi-key": key_obj['val'],
            "Content-Type": "application/x-www-form-urlencoded",
        }

        try:
            response = requests.post(
                RAPIDAPI_URL,
                headers=headers,
                data={"url": video_url, "hd": "1"},
                timeout=TIMEOUT,
            )

            if response.status_code == 429:
                # শুধু এটাই আসল "এই key-র কোটা শেষ" সিগন্যাল — তাই এখানেই
                # শুধু পরের key-তে রোটেট করা হয়।
                logging.warning("RapidAPI rate limit hit, rotating key...")
                key_manager.mark_failed(key_obj['val'])
                continue

            if response.status_code != 200:
                # 500/502/503 ইত্যাদি সাধারণ/অস্থায়ী সার্ভার এরর — এটা কোনো
                # নির্দিষ্ট key-র সমস্যা না, তাই অন্য key দিয়ে আবার চেষ্টা
                # করলে শুধু অকারণে একাধিক paid কল খরচ হবে। সাথে সাথে থামানো
                # হচ্ছে (retry cost multiplication এড়াতে)।
                logging.error(f"RapidAPI returned status {response.status_code} — stopping (not retrying with other keys).")
                return {'success': False, 'error': 'সার্ভিস সাময়িকভাবে ব্যস্ত, একটু পর আবার চেষ্টা করুন।'}

            try:
                result = response.json()
            except ValueError:
                logging.error("RapidAPI returned non-JSON response — stopping.")
                return {'success': False, 'error': 'সার্ভিস থেকে অপ্রত্যাশিত রেসপন্স, একটু পর চেষ্টা করুন।'}

            if result.get('code') != 0:
                return {'success': False, 'error': 'ভিডিও পাওয়া যায়নি অথবা প্রাইভেট।'}

            d = result.get('data', {})

            if d.get('images'):
                images = [img for img in d.get('images', []) if _is_safe_url(img)]
                if not images:
                    return {'success': False, 'error': 'ছবি পাওয়া যায়নি।'}
                return {
                    'success': True,
                    'is_photo': True,
                    'images': images,
                    'title': d.get('title') or 'TikTok Photos',
                    'author': (d.get('author') or {}).get('unique_id') or 'Unknown',
                }

            hd_url = d.get('hdplay') or d.get('play')
            if not hd_url or not _is_safe_url(hd_url):
                return {'success': False, 'error': 'HD ভিডিও পাওয়া যায়নি।'}

            thumbnail = d.get('cover') or ''
            return {
                'success': True,
                'is_photo': False,
                'hd_url': hd_url,
                'thumbnail': thumbnail if _is_safe_url(thumbnail) else '',
                'title': d.get('title') or 'Untitled Video',
                'author': (d.get('author') or {}).get('unique_id') or 'Unknown',
                'duration': d.get('duration') or 0,
            }

        except requests.Timeout:
            # টাইমআউটও key-নির্দিষ্ট সমস্যা না — অন্য key দিয়ে আবার চেষ্টা
            # না করে সাথে সাথে থামানো হচ্ছে।
            logging.error(f"RapidAPI request timed out for URL: {video_url} — stopping.")
            return {'success': False, 'error': 'সার্ভিস সাড়া দিতে দেরি করছে, একটু পর আবার চেষ্টা করুন।'}
        except requests.ConnectionError:
            logging.error("RapidAPI connection error — stopping.")
            return {'success': False, 'error': 'সার্ভিসে সংযোগ করা যায়নি, একটু পর আবার চেষ্টা করুন।'}
        except Exception as e:
            logging.error(f"Unexpected RapidAPI error: {str(e)} — stopping.")
            return {'success': False, 'error': 'একটা সমস্যা হয়েছে, একটু পর আবার চেষ্টা করুন।'}

    return {'success': False, 'error': 'সিস্টেম ব্যস্ত, একটু পর আবার চেষ্টা করুন।'}


def _is_safe_url(u):
    """API রেসপন্স থেকে আসা URL সত্যিই http(s) লিংক কিনা যাচাই — সরাসরি
    ইউজারের ব্রাউজারে এই URL পাঠানো হবে, তাই সামান্য defense-in-depth।"""
    return isinstance(u, str) and (u.startswith('http://') or u.startswith('https://'))
