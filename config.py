import os
import time
import hashlib
import logging


class KeyManager:
    """
    একাধিক RapidAPI key রোটেট করে — একটা exhausted/rate-limited (৪২৯) হলে
    পরেরটায় সুইচ করে, exhausted key ২৪ ঘণ্টা cooldown-এ থাকে।

    ⚠️ Gunicorn একাধিক worker প্রসেস চালায় (--workers 2) — প্রতিটা worker
    আলাদা Python প্রসেস, আলাদা মেমোরি। তাই শুধু in-memory `self.keys` দিয়ে
    রাখলে worker A কোনো key exhausted মার্ক করলেও worker B সেটা জানে না,
    ফলে worker B আবার সেই (ইতিমধ্যে exhausted) key দিয়ে চেষ্টা করে আরেকটা
    ৪২৯ পায় — অপ্রয়োজনীয় ব্যর্থ কল। Upstash কনফিগার করা থাকলে cooldown
    স্টেট Redis-এও শেয়ার করা হয় (TTL সহ), তাই সব worker সাথে সাথে জানতে
    পারে। Upstash না থাকলে শুধু in-memory ব্যবহার হয় (আগের আচরণ)।
    """

    def __init__(self, keys_str):
        self.keys = [{'val': k.strip(), 'active': True, 'failed_at': 0}
                     for k in keys_str.split(",") if k.strip()]
        self.cooldown = 86400  # ২৪ ঘণ্টা

    @staticmethod
    def _redis_cooldown_key(key_val):
        # আসল key কখনো Redis-এ plain text রাখা হয় না, শুধু hash — সিকিউরিটির জন্য
        return f'apikey_cooldown:{hashlib.sha256(key_val.encode()).hexdigest()[:20]}'

    def _is_cooling_in_redis(self, key_val):
        from services import upstash_client
        if not upstash_client.configured():
            return False
        return bool(upstash_client.cmd('get', self._redis_cooldown_key(key_val)))

    def get_active_key(self):
        now = time.time()
        for k in self.keys:
            if not k['active'] and (now - k['failed_at'] > self.cooldown):
                k['active'] = True
                logging.info(f"Key re-activated after local cooldown: {k['val'][:8]}...")
            if k['active'] and self._is_cooling_in_redis(k['val']):
                # অন্য কোনো worker এটাকে ইতিমধ্যে exhausted মার্ক করেছে —
                # এই worker নিজে টেস্ট না করেই স্কিপ করবে
                continue
            if k['active']:
                return k
        return None

    def mark_failed(self, key_val):
        from services import upstash_client
        for k in self.keys:
            if k['val'] == key_val:
                k['active'] = False
                k['failed_at'] = time.time()
                if upstash_client.configured():
                    upstash_client.cmd('set', self._redis_cooldown_key(key_val), '1', 'EX', self.cooldown)
                remaining = [x for x in self.keys if x['active']]
                logging.warning(
                    f"Key exhausted: {key_val[:8]}... | "
                    f"Active keys remaining (this worker's view): {len(remaining)}"
                )

    def status(self):
        now = time.time()
        report = []
        for i, k in enumerate(self.keys):
            if k['active']:
                state = "active"
            else:
                hours_left = max(0, (self.cooldown - (now - k['failed_at'])) / 3600)
                state = f"cooldown ({hours_left:.1f}h left)"
            report.append(f"Key {i + 1}: {k['val'][:8]}... -> {state}")
        return " | ".join(report)


api_keys_env = os.environ.get("API_KEYS", "")
key_manager = KeyManager(api_keys_env)

if key_manager.keys:
    logging.info(f"KeyManager loaded {len(key_manager.keys)} key(s).")
else:
    logging.warning(
        "No API keys found (API_KEYS env var empty). "
        "HD video / Photo download will be unavailable until it's set."
    )

TIMEOUT = 15

# প্রতিদিন (রাত ১২টায়, বাংলাদেশ সময়ে রিসেট) সর্বোচ্চ কতগুলো HD ভিডিও/ফটো
# ডাউনলোড ফ্রি — এই লিমিট শুধু paid API (RapidAPI) ব্যবহারকারী ডাউনলোডে
# প্রযোজ্য। Normal (yt-dlp) ভিডিও ডাউনলোডে কোনো লিমিট নেই।
DAILY_LIMIT = int(os.environ.get("DAILY_LIMIT", "5"))
