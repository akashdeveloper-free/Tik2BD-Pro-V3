# Tik2BD Pro — TikTok Video Downloader (Secure, Ad-Free Edition)

বিজ্ঞাপনমুক্ত, watermark-ছাড়া TikTok ভিডিও/ছবি ডাউনলোডার। এই ডকুমেন্টটা এমনভাবে লেখা যাতে **যারা কোডিং সম্পর্কে কিছুই জানে না** তারাও এটা নিজে থেকে হোস্ট/চালাতে পারে।

---

## সূচিপত্র
1. [এই প্রজেক্টটা কী করে](#১-এই-প্রজেক্টটা-কী-করে)
2. [আর্কিটেকচার — সহজ ভাষায়](#২-আর্কিটেকচার--সহজ-ভাষায়)
3. [Render-এ ডেপ্লয় করা — ধাপে ধাপে](#৩-render-এ-ডেপ্লয়-করা--ধাপে-ধাপে)
4. [Environment Variables — প্রতিটার বিস্তারিত ব্যাখ্যা](#৪-environment-variables--প্রতিটার-বিস্তারিত-ব্যাখ্যা)
5. [RapidAPI Key কীভাবে পাবেন](#৫-rapidapi-key-কীভাবে-পাবেন)
6. [Upstash Redis কীভাবে বানাবেন (ফ্রি)](#৬-upstash-redis-কীভাবে-বানাবেন-ফ্রি)
7. [নিজের সার্ভারে (VPS) হোস্ট করা](#৭-নিজের-সার্ভারে-vps-হোস্ট-করা)
8. [সমস্যা সমাধান (Troubleshooting)](#৮-সমস্যা-সমাধান-troubleshooting)
9. [সিকিউরিটি — কী কী সুরক্ষা আছে](#৯-সিকিউরিটি--কী-কী-সুরক্ষা-আছে)

---

## ১. এই প্রজেক্টটা কী করে

| ফিচার | বিস্তারিত |
|---|---|
| **Normal ভিডিও ডাউনলোড** | সম্পূর্ণ ফ্রি, **আনলিমিটেড** — কোনো কোটা/লিমিট নেই |
| **HD ভিডিও ডাউনলোড** | দিনে সর্বোচ্চ ৫টা ফ্রি (HD + Photo মিলিয়ে), রাত ১২টায় (বাংলাদেশ সময়) রিসেট |
| **Photo Slideshow ডাউনলোড** | HD-এর সাথে একই ৫টা কোটার মধ্যে |
| **বিজ্ঞাপন** | নেই, একদমই নেই |
| **ইউজার একাউন্ট/লগইন** | লাগে না |

---

## ২. আর্কিটেকচার — সহজ ভাষায়

TikTok-এর ভিডিও CDN-এ দুই ধরনের "সুরক্ষা" আছে যেটা এই প্রজেক্টের ডিজাইন ঠিক করেছে:

- **Normal ভিডিও** (yt-dlp দিয়ে বের করা লিংক) — TikTok-এর নিজস্ব ওয়েব-CDN থেকে আসে, যেটা browser থেকে সরাসরি খোলা যায় না (একটা বিশেষ হেডার লাগে যেটা browser-এর JavaScript দিয়ে বসানো যায় না)। তাই এই ভিডিওগুলো **আমাদের সার্ভার দিয়ে পাস হয়** (সার্ভার প্রথমে yt-dlp দিয়ে ভিডিওটা নিজে আনে, তারপর ইউজারকে পাঠায়, তারপর ডিলিট করে দেয়)। এতে সার্ভারের bandwidth লাগে — এটা অনিবার্য।
- **HD ভিডিও / Photo** (RapidAPI নামের একটা paid সার্ভিস থেকে বের করা লিংক) — এই লিংকগুলো browser থেকে সরাসরি খোলা যায়, তাই **সার্ভারের bandwidth লাগে না** — ইউজারের ব্রাউজার সরাসরি সেই লিংক থেকে ডাউনলোড করে।

```
ইউজার লিংক পেস্ট করে
        │
        ▼
  /download  (yt-dlp, ফ্রি প্রিভিউ — টাইটেল/থাম্বনেইল দেখায়, কোনো paid API লাগে না)
        │
   ┌────┴─────┐
   ▼          ▼
"Normal"    "HD" বাটন
বাটন ক্লিক   ক্লিক
   │          │
   ▼          ▼
/media/     /media/premium
normal-     (RapidAPI কল হয়,
download    দিনে ৫টা কোটা)
(সার্ভার       │
bandwidth      ▼
লাগে)      ব্রাউজার সরাসরি
            RapidAPI-র CDN
            থেকে ডাউনলোড করে
            (bandwidth লাগে না)
```

---

## ৩. Render-এ ডেপ্লয় করা — ধাপে ধাপে

### ধাপ ১ — GitHub-এ কোড আপলোড করো
1. [github.com](https://github.com) -এ একটা একাউন্ট খোলো (না থাকলে)
2. একটা নতুন **Repository** বানাও (public বা private, দুটোই চলবে)
3. এই প্রজেক্টের সব ফাইল সেই রিপোতে আপলোড করো (মোবাইল থেকে GitHub-এর "Add file → Upload files" ব্যবহার করে করা যায়, অথবা কম্পিউটার থেকে `git push`)

### ধাপ ২ — Render-এ একাউন্ট বানাও
1. [render.com](https://render.com) -এ যাও
2. **"Get Started"** চেপে GitHub দিয়ে সাইন আপ করো (এতে GitHub-এর সাথে অটোমেটিক কানেক্ট হয়ে যাবে)

### ধাপ ৩ — নতুন Web Service বানাও
1. Render ড্যাশবোর্ড → **"New +"** → **"Web Service"**
2. তোমার GitHub রিপো সিলেক্ট করো
3. এই সেটিংস দাও:

| ফিল্ড | মান |
|---|---|
| **Name** | যা খুশি (যেমন `my-tiktok-downloader`) |
| **Region** | Singapore (বাংলাদেশের সবচেয়ে কাছে) |
| **Branch** | `main` |
| **Root Directory** | খালি রাখো |
| **Runtime** | Python 3 |
| **Build Command** | `pip install -r requirements.txt` |
| **Start Command** | `gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120` |
| **Instance Type** | Free |

### ধাপ ৪ — Environment Variables যোগ করো
নিচে scroll করে **"Environment Variables"** সেকশনে যাও, এই ভ্যারিয়েবলগুলো একটা একটা করে "Add Environment Variable" দিয়ে বসাও (বিস্তারিত পরের সেকশনে):

| Key | কোথা থেকে পাবে |
|---|---|
| `API_KEYS` | ধাপ ৫ দেখো (RapidAPI) |
| `UPSTASH_REDIS_REST_URL` | ধাপ ৬ দেখো (Upstash) |
| `UPSTASH_REDIS_REST_TOKEN` | ধাপ ৬ দেখো (Upstash) |

### ধাপ ৫ — Deploy করো
**"Create Web Service"** বাটনে চাপো। Render নিজে থেকেই বিল্ড শুরু করবে (২-৪ মিনিট লাগতে পারে)। শেষ হলে উপরে একটা `https://xxxx.onrender.com` লিংক পাবে — এটাই তোমার লাইভ ওয়েবসাইট।

---

## ৪. Environment Variables — প্রতিটার বিস্তারিত ব্যাখ্যা

| ভ্যারিয়েবল | আবশ্যক? | কী করে | না দিলে কী হবে |
|---|---|---|---|
| `API_KEYS` | ✅ হ্যাঁ | HD ভিডিও ও Photo ডাউনলোডের জন্য RapidAPI-র key | HD/Photo বাটন কাজ করবে না, Normal ঠিকই চলবে |
| `UPSTASH_REDIS_REST_URL` | 🟡 জোরালোভাবে সুপারিশকৃত | দৈনিক কোটা (৫টা) মনে রাখার জন্য | কোটা লোকাল ফাইলে থাকবে, Render রিস্টার্ট হলেই কোটা রিসেট হয়ে যাবে (ভুয়া "আবার ৫টা পেয়ে গেলাম" সমস্যা হবে) |
| `UPSTASH_REDIS_REST_TOKEN` | 🟡 জোরালোভাবে সুপারিশকৃত | উপরেরটার সাথেই লাগে | উপরের মতোই |
| `DAILY_LIMIT` | ⭕ ঐচ্ছিক | দিনে কতগুলো HD/Photo ফ্রি (ডিফল্ট ৫) | ৫ থাকবে |
| `RATE_LIMIT_PER_MIN` | ⭕ ঐচ্ছিক | সাধারণ রিকোয়েস্টে bot-প্রতিরোধী সীমা (ডিফল্ট ২০/মিনিট) | ২০ থাকবে |
| `HEAVY_RATE_LIMIT_PER_MIN` | ⭕ ঐচ্ছিক | Normal ভিডিওর "আসল ডাউনলোড"-এ সীমা (ডিফল্ট ৬/মিনিট) | ৬ থাকবে |
| `FLASK_DEBUG` | ⭕ ঐচ্ছিক, **কখনো `true` দিও না প্রোডাকশনে** | ডিবাগ মোড — এরর পেজে কোড দেখায় (নিরাপত্তা ঝুঁকি) | `false` থাকবে (নিরাপদ) |
| `PORT` | ❌ দরকার নেই | Render নিজেই সেট করে | — |

---

## ৫. RapidAPI Key কীভাবে পাবেন

HD ভিডিও ও Photo ডাউনলোডের জন্য এই key লাগবে (Normal ভিডিওতে লাগে না)।

1. ব্রাউজারে যাও: **[rapidapi.com](https://rapidapi.com)** → একাউন্ট বানাও (Google দিয়েও সাইন আপ করা যায়, ফ্রি)
2. সার্চ বক্সে লিখো: **"TikTok Video No Watermark"**
3. যে API-টা দেখাবে (সাধারণত নাম হয় *"TikTok Video No Watermark"*, publisher: বিভিন্ন হতে পারে) সেটায় ক্লিক করো
4. পেজের ডানদিকে/উপরে **"Subscribe to Test"** বা **"Pricing"** ট্যাবে যাও — একটা **Basic/Free** প্ল্যান থাকবে (প্রতি মাসে সীমিত ফ্রি রিকোয়েস্ট) — সেটা সিলেক্ট করো (ক্রেডিট কার্ড লাগতে পারে ভেরিফিকেশনের জন্য, কিন্তু ফ্রি প্ল্যানে চার্জ হয় না)
5. Subscribe করার পর, পেজে **"X-RapidAPI-Key"** নামে একটা লম্বা কোড (যেমন `a1b2c3d4e5...`) দেখাবে — এটাই কপি করে Render-এর `API_KEYS` ভ্যারিয়েবলে বসাও

> 💡 একাধিক key কমা দিয়ে দিলে (`key1,key2`) একটার কোটা শেষ হলে অ্যাপ নিজে থেকেই পরেরটায় সুইচ করবে।

---

## ৬. Upstash Redis কীভাবে বানাবেন (ফ্রি)

এটা দিয়ে দৈনিক ৫টা কোটা মনে রাখা হয় (Render রিস্টার্ট হলেও)। সম্পূর্ণ ফ্রি, ক্রেডিট কার্ড লাগে না।

1. যাও: **[upstash.com](https://upstash.com)** → **"Sign Up"** (GitHub/Google দিয়ে দ্রুত হয়)
2. লগইন করার পর ড্যাশবোর্ডে **"Create Database"** চাপো
3. একটা নাম দাও (যেমন `tik2bd-quota`), **Region** সিলেক্ট করো (Singapore বা কাছাকাছি কিছু), **Type: Regional**, তারপর **"Create"**
4. ডেটাবেস বানানো হয়ে গেলে সেই পেজেই নিচে **"REST API"** সেকশন পাবে — সেখানে দুটো জিনিস থাকবে:
   - **UPSTASH_REDIS_REST_URL** (একটা লিংক, `https://....upstash.io` দিয়ে শুরু)
   - **UPSTASH_REDIS_REST_TOKEN** (একটা লম্বা কোড)
5. এই দুটোই কপি করে Render-এর env variable-এ যথাক্রমে `UPSTASH_REDIS_REST_URL` আর `UPSTASH_REDIS_REST_TOKEN`-এ বসাও

---

## ৭. নিজের সার্ভারে (VPS) হোস্ট করা

Render-এর বদলে নিজের সার্ভার (DigitalOcean, Hetzner, AWS EC2, বা যেকোনো VPS) ব্যবহার করতে চাইলে এই ধাপগুলো লাগবে।

### ন্যূনতম সার্ভার স্পেসিফিকেশন
| জিনিস | ন্যূনতম | সুপারিশকৃত |
|---|---|---|
| RAM | ১ GB | ২ GB+ |
| CPU | ১ vCPU | ২ vCPU |
| ডিস্ক | ১০ GB | ২৫ GB+ |
| OS | Ubuntu 22.04 / 24.04 LTS | একই |
| Bandwidth | কমপক্ষে ১০০ GB/মাস | ব্যবহারকারী বেশি হলে আরও বেশি |

### ইনস্টলেশন ধাপ

```bash
# ১. সিস্টেম আপডেট + প্রয়োজনীয় প্যাকেজ
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv nginx git ffmpeg

# ২. কোড ক্লোন করো
git clone <তোমার-GitHub-রিপোর-লিংক> tik2bd
cd tik2bd

# ৩. ভার্চুয়াল এনভায়রনমেন্ট বানাও
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# ৪. Environment variables সেট করো (একটা .env ফাইল বানাও, এই প্রজেক্টে
#    python-dotenv নেই বলে systemd সার্ভিস ফাইলে সরাসরি বসাতে হবে, নিচে দেখো)

# ৫. টেস্ট রান করো
gunicorn app:app --bind 0.0.0.0:8000 --workers 2 --timeout 120
# ব্রাউজারে http://তোমার-সার্ভার-IP:8000 খুলে টেস্ট করো, তারপর Ctrl+C দিয়ে বন্ধ করো
```

### systemd সার্ভিস বানাও (যাতে সার্ভার রিস্টার্ট হলেও অ্যাপ নিজে থেকে চালু হয়)

`/etc/systemd/system/tik2bd.service` ফাইল বানাও:

```ini
[Unit]
Description=Tik2BD Pro
After=network.target

[Service]
User=www-data
WorkingDirectory=/home/youruser/tik2bd
Environment="API_KEYS=তোমার_key_এখানে"
Environment="UPSTASH_REDIS_REST_URL=তোমার_url_এখানে"
Environment="UPSTASH_REDIS_REST_TOKEN=তোমার_token_এখানে"
ExecStart=/home/youruser/tik2bd/venv/bin/gunicorn app:app --bind 127.0.0.1:8000 --workers 2 --timeout 120
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable tik2bd
sudo systemctl start tik2bd
sudo systemctl status tik2bd   # চেক করো ঠিকভাবে চলছে কিনা
```

### Nginx দিয়ে রিভার্স-প্রক্সি + HTTPS (SSL)

`/etc/nginx/sites-available/tik2bd`:
```nginx
server {
    listen 80;
    server_name yourdomain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/tik2bd /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl restart nginx

# ফ্রি SSL সার্টিফিকেট (HTTPS)
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d yourdomain.com
```

⚠️ **গুরুত্বপূর্ণ**: নিজের সার্ভারে `app.py`-র `ProxyFix(app.wsgi_app, x_for=1, ...)` লাইনটা **শুধু তখনই ঠিক কাজ করবে যখন Nginx-এর মতো ঠিক ১টা রিভার্স-প্রক্সি থাকে**। যদি Cloudflare-ও ব্যবহার করো (Nginx-এর সামনে), তাহলে `x_for=2` করতে হবে (দুটো প্রক্সি হপ)।

### ফায়ারওয়াল
```bash
sudo ufw allow 22    # SSH
sudo ufw allow 80    # HTTP
sudo ufw allow 443   # HTTPS
sudo ufw enable
```

---

## ৮. সমস্যা সমাধান (Troubleshooting)

| সমস্যা | কারণ | সমাধান |
|---|---|---|
| HD/Photo বাটনে "সার্ভিস কনফিগার করা নেই" | `API_KEYS` সেট করা নেই | RapidAPI key যোগ করো |
| কিছুক্ষণ পর কোটা আবার ৫/৫ হয়ে যায় | `UPSTASH_REDIS_REST_URL/TOKEN` সেট নেই | Upstash যোগ করো (ধাপ ৬) |
| Normal ভিডিও ডাউনলোড আটকে থাকে/৪০৩ এরর | TikTok সাময়িক ব্লক করছে | কিছুক্ষণ পর আবার চেষ্টা করো; বারবার হলে yt-dlp আপডেট দরকার হতে পারে |
| "অনেক বেশি রিকোয়েস্ট" এরর | Rate limit-এ লেগেছে | ১ মিনিট অপেক্ষা করো |
| Deploy fail — `ModuleNotFoundError` | কোনো ফাইল/ফোল্ডার মিসিং আপলোডে | সব ফাইল (বিশেষ করে `services/`, `utils/` ফোল্ডারের `__init__.py`সহ সব ফাইল) ঠিকভাবে আপলোড হয়েছে কিনা চেক করো |

Render-এ কোনো এরর এলে: ড্যাশবোর্ড → তোমার সার্ভিস → **Logs** ট্যাব থেকে এরর মেসেজ কপি করে দেখো।

---

## ৯. সিকিউরিটি — কী কী সুরক্ষা আছে

- ✅ **ProxyFix** — সঠিক ইউজার IP ডিটেকশন (Render-এর প্রক্সির পেছনে)
- ✅ **Atomic কোটা-ট্রানজ্যাকশন** — একই মুহূর্তে একাধিক রিকোয়েস্টেও কোটা বাইপাস অসম্ভব
- ✅ **CDN Host Allowlist** — শুধু TikTok/ByteDance-এর ডোমেইনই fetch করা যায় (SSRF প্রতিরোধ)
- ✅ **Redirect পুনঃযাচাই** — allowlist-এড হোস্ট অন্য কোথাও রিডাইরেক্ট করলেও ব্লক হয়
- ✅ **Same-Origin চেক** — বাইরের সাইট থেকে সরাসরি API endpoint hit করা ঠেকায়
- ✅ **দুই-স্তরের Rate Limiting** — সাধারণ রিকোয়েস্টে ২০/মিনিট, ভারী অপারেশনে (Normal ডাউনলোড) ৬/মিনিট
- ✅ **Security Headers** — X-Frame-Options, X-Content-Type-Options, Referrer-Policy
- ✅ **টেম্প ফাইল অটো-ক্লিনআপ** — ডাউনলোডের পরপরই ডিলিট, স্টার্টআপে পুরনো ফাইলও পরিষ্কার
- ✅ **কোনো বিজ্ঞাপন/ট্র্যাকিং স্ক্রিপ্ট নেই**

---

**Developed with security-first architecture.** কোনো প্রশ্ন থাকলে Render-এর Logs শেয়ার করে জিজ্ঞেস করতে পারো।
