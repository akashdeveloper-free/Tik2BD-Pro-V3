// =============================================
//  Tik2BD Pro — main.js  (বিজ্ঞাপনমুক্ত সংস্করণ)
// =============================================

let _inFlight = false; // network spam বন্ধ
let _lastUrl = '';      // /media/premium কল করার সময় কোন লিংকের জন্য কাজ করছি তা মনে রাখতে

const urlInput     = document.getElementById('urlInput');
const clearBtn      = document.getElementById('clearBtn');
const pasteBtn       = document.getElementById('pasteBtn');
const downloadBtn    = document.getElementById('downloadBtn');
const downloadBtnText = document.getElementById('downloadBtnText');
const resultArea     = document.getElementById('resultArea');
const inputWrapper   = document.getElementById('inputWrapper');

// ===== XSS Protection =====
function escapeHtml(text) {
    const div = document.createElement('div');
    div.appendChild(document.createTextNode(String(text)));
    return div.innerHTML;
}

// ── ডাউনলোড লজিক ──
// mode = 'direct-first' (ডিফল্ট) → আগে ব্রাউজার সরাসরি CDN থেকে fetch করার
//        চেষ্টা করে (zero-bandwidth), ব্যর্থ হলে সার্ভার-প্রক্সিতে ফলব্যাক।
//        HD (RapidAPI-র লিংক) আর Photo-এর জন্য এটা ব্যবহার হয়, কারণ এই
//        লিংকগুলো টেস্টে দেখা গেছে ব্রাউজার থেকে সরাসরিই কাজ করে (TikTok-এর
//        webapp-CDN-এর মতো Referer-ব্লক নেই) — তাই এখানে সার্ভার bandwidth
//        একদমই লাগে না।
// mode = 'server-only' → সরাসরি চেষ্টা না করেই সোজা সার্ভার-প্রক্সিতে যায়।
//        Normal (yt-dlp-র webapp-CDN লিংক)-এর জন্য এটা ব্যবহার হয়, কারণ
//        এই লিংক ব্রাউজার থেকে সরাসরি প্রায় সবসময়ই ব্লক হয় (Referer ছাড়া
//        TikTok-এর webapp CDN রিকোয়েস্ট প্রত্যাখ্যান করে) — তাই আগে থেকেই
//        জানা-ব্যর্থ একটা ধাপ চেষ্টা করে সময় নষ্ট না করে সরাসরি সার্ভার
//        দিয়ে পাঠানো হয় (bandwidth এখানে যা-ই হোক লাগবেই, তাই আগে থেকে
//        চেষ্টা করাটা নিছক দেরি করানো ছাড়া কিছু না)।
async function triggerDownload(url, filename, mode = 'direct-first', ticket = '') {
    if (!url) return;
    showToast('ডাউনলোড শুরু হচ্ছে...', 'info');

    if (mode === 'direct-first') {
        try {
            const resp = await fetch(url, { mode: 'cors' });
            if (!resp.ok) throw new Error('direct fetch not ok');
            const blob = await resp.blob();
            if (!blob || blob.size < 1024) throw new Error('empty/broken response');
            _saveBlob(blob, filename);
            return;
        } catch (_) {
            // সরাসরি ফেচ ব্যর্থ — নিচে সার্ভার-প্রক্সি ফলব্যাক চেষ্টা হবে
        }
    }

    try {
        // ticket ছাড়া /media/stream কাজ করবে না (স্বল্পস্থায়ী, /media/premium
        // থেকেই আসে) — এতে এই এন্ডপয়েন্টটা "ওপেন প্রক্সি" হিসেবে ব্যবহার
        // করা যায় না, শুধু আমাদের নিজের অ্যাপের সাম্প্রতিক রেসপন্স থেকেই কাজ করে।
        const streamUrl = `/media/stream?url=${encodeURIComponent(url)}&filename=${encodeURIComponent(filename)}&ticket=${encodeURIComponent(ticket)}`;
        const resp = await fetch(streamUrl);
        const contentType = resp.headers.get('Content-Type') || '';
        if (!resp.ok || contentType.includes('application/json')) {
            let msg = 'ডাউনলোড ব্যর্থ হয়েছে, একটু পর আবার চেষ্টা করুন।';
            try {
                const errJson = await resp.json();
                if (errJson && errJson.error) msg = errJson.error;
            } catch (_) { /* JSON না হলে ডিফল্ট মেসেজই থাকবে */ }
            showToast(msg, 'error');
            return;
        }
        const blob = await resp.blob();
        _saveBlob(blob, filename);
    } catch (_) {
        showToast('নেটওয়ার্ক এরর — ডাউনলোড ব্যর্থ হয়েছে।', 'error');
    }
}

function _saveBlob(blob, filename) {
    const blobUrl = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = blobUrl;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(blobUrl), 30000);
    showToast('ডাউনলোড সফল! ✅', 'success');
}

// ── Normal ভিডিও ডাউনলোড — সার্ভার yt-dlp দিয়ে extract+download একসাথে করে
//    (একই সেশনে, ফ্রেশ) তারপর ফাইলটা স্ট্রিম করে পাঠায় এবং ডিলিট করে দেয়।
//    আগে থেকে বের করা URL রিইউজ করলে TikTok ৪০৩ Forbidden দেয় বলে এই
//    পদ্ধতি — বিস্তারিত কারণ ব্যাকএন্ডে লেখা আছে। এতে সামান্য বেশি সময়
//    লাগতে পারে (সার্ভার আগে ভিডিওটা নিজে আনে), কিন্তু নিশ্চিতভাবে কাজ করে।
async function downloadNormalVideo(pageUrl, filename) {
    if (!pageUrl) return;
    showToast('ভিডিও প্রস্তুত হচ্ছে, একটু সময় লাগতে পারে...', 'info');
    try {
        const resp = await fetch('/media/normal-download', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: pageUrl }),
        });
        const contentType = resp.headers.get('Content-Type') || '';
        if (!resp.ok || contentType.includes('application/json')) {
            let msg = 'ডাউনলোড ব্যর্থ হয়েছে, একটু পর আবার চেষ্টা করুন।';
            try {
                const errJson = await resp.json();
                if (errJson && errJson.error) msg = errJson.error;
            } catch (_) { /* JSON না হলে ডিফল্ট মেসেজই থাকবে */ }
            showToast(msg, 'error');
            return;
        }
        const blob = await resp.blob();
        _saveBlob(blob, filename);
    } catch (_) {
        showToast('নেটওয়ার্ক এরর — ডাউনলোড ব্যর্থ হয়েছে।', 'error');
    }
}

// ===== Toast Notification System =====
function showToast(message, type = 'info', duration = 3500) {
    const container = document.getElementById('toastContainer');
    if (!container) return;
    const icons = {
        success: `<svg class="toast-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>`,
        error:   `<svg class="toast-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>`,
        info:    `<svg class="toast-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>`,
    };
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerHTML = `${icons[type] || icons.info}<span>${escapeHtml(message)}</span>`;
    container.appendChild(toast);
    setTimeout(() => {
        toast.classList.add('hide');
        toast.addEventListener('animationend', () => toast.remove());
    }, duration);
}

// ===== Animated Counter =====
function animateCounter(el, target, duration = 1800) {
    const isPercent = target <= 100 && el.closest('.stat-item')?.querySelector('.stat-label')?.textContent.includes('%');
    let start = 0;
    const step = target / (duration / 16);
    const timer = setInterval(() => {
        start = Math.min(start + step, target);
        const val = Math.floor(start);
        if (target >= 1000000) {
            el.textContent = (val / 1000000).toFixed(1) + 'M+';
        } else if (target >= 1000) {
            el.textContent = (val / 1000).toFixed(0) + 'K+';
        } else {
            el.textContent = val + (isPercent ? '%' : '');
        }
        if (start >= target) clearInterval(timer);
    }, 16);
}

function startCounters() {
    document.querySelectorAll('.stat-number[data-target]').forEach(el => {
        const target = parseInt(el.dataset.target, 10);
        animateCounter(el, target);
    });
}

const observer = new IntersectionObserver(entries => {
    entries.forEach(e => { if (e.isIntersecting) { startCounters(); observer.disconnect(); } });
}, { threshold: 0.3 });
const statsEl = document.querySelector('.hero-stats');
if (statsEl) observer.observe(statsEl);

// ===== Input Validation =====
urlInput.addEventListener('input', () => {
    const val = urlInput.value.trim();
    clearBtn.classList.toggle('hidden', !val);
    if (!val) {
        inputWrapper.className = 'input-wrapper';
    } else if (val.includes('tiktok.com')) {
        inputWrapper.className = 'input-wrapper valid';
    } else {
        inputWrapper.className = 'input-wrapper invalid';
    }
});

// ===== Paste Button =====
async function pasteLink() {
    try {
        const text = await navigator.clipboard.readText();
        urlInput.value = text;
        urlInput.dispatchEvent(new Event('input'));
        showToast('Link pasted!', 'success', 2000);
    } catch {
        showToast('Clipboard access denied — paste manually.', 'error');
    }
}

// ===== Clear Input =====
function clearInput() {
    urlInput.value = '';
    clearBtn.classList.add('hidden');
    inputWrapper.className = 'input-wrapper';
    resultArea.innerHTML = '';
}

// ===== Loading State =====
function setLoading(loading, label) {
    downloadBtn.disabled = loading;
    if (loading) {
        downloadBtnText.textContent = 'Processing...';
        resultArea.innerHTML = `
            <div class="loading-wrap">
                <div class="spinner"></div>
                <span>${escapeHtml(label || 'Fetching video info...')}</span>
            </div>`;
    } else {
        downloadBtnText.textContent = 'Download Video';
    }
}

// ===== দৈনিক HD/Photo কোটা badge (পেজ লোড হওয়ার সময় ও প্রতিটা সফল প্রিমিয়াম ডাউনলোডের পরে রিফ্রেশ হয়) =====
async function refreshQuotaBadge() {
    const el = document.getElementById('quotaBadge');
    if (!el) return;
    try {
        const status = await (await fetch('/media/status')).json();
        renderQuotaBadge(status);
    } catch { /* নীরবে ইগনোর — badge না দেখালেও মূল ফিচার কাজ করবে */ }
}

function renderQuotaBadge(status) {
    const el = document.getElementById('quotaBadge');
    if (!el || !status) return;
    if (status.locked) {
        el.textContent = `🔒 আজকের HD/Photo কোটা শেষ (${status.used}/${status.limit}) — রাত ১২টার পর আবার পাবেন`;
        el.classList.add('locked');
    } else {
        el.textContent = `HD/Photo বাকি আজকে: ${status.remaining}/${status.limit}`;
        el.classList.remove('locked');
    }
}

document.addEventListener('DOMContentLoaded', refreshQuotaBadge);

function formatWait(seconds) {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    if (h > 0) return `প্রায় ${h} ঘণ্টা ${m} মিনিট`;
    if (m > 0) return `প্রায় ${m} মিনিট`;
    return 'কিছুক্ষণের মধ্যেই';
}

function renderLockBox(status) {
    return `
        <div class="hd-lock-box" id="hdLockBox">
            <p class="hd-lock-msg">
                🔒 আজকের ফ্রি HD/Photo লিমিট শেষ (${status.used}/${status.limit})।
                রাত ১২টার পর (বাংলাদেশ সময়) রিসেট হবে — ${formatWait(status.resets_in_seconds)} পর।
                <br><small>Normal কোয়ালিটি ডাউনলোডে কোনো লিমিট নেই — চাইলে সেটা এখনই আনলিমিটেড ব্যবহার করতে পারেন।</small>
            </p>
        </div>`;
}

// ===== Normal ভিডিও রেজাল্ট (kind: 'video') =====
function renderVideoResult(data) {
    const safeTitle     = escapeHtml((data.title || 'Untitled Video').substring(0, 80));
    const safeAuthor    = escapeHtml(data.author || 'Unknown');
    const safeThumbnail = escapeHtml(data.thumbnail || '');

    const thumbBlock = safeThumbnail ? `
        <div class="video-thumb-wrap">
            <img class="video-thumb-img" src="${safeThumbnail}" alt="Thumbnail"
                 onerror="this.closest('.video-thumb-wrap').style.display='none'">
        </div>` : '';

    resultArea.innerHTML = `
        <div class="result-card">
            <div class="result-meta">
                ${thumbBlock}
                <div class="result-info">
                    <h3>${safeTitle}</h3>
                    <span class="result-author">@${safeAuthor}</span>
                </div>
            </div>
            <div class="dl-btn-row">
                <button class="dl-btn dl-btn-hd" id="_hdPill">
                    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                    HD Download
                </button>
                <button class="dl-btn dl-btn-sd" id="_sdPill">
                    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                    Normal
                </button>
            </div>
            <div id="premiumArea"></div>
        </div>`;

    const sdPill = document.getElementById('_sdPill');
    if (sdPill) sdPill.addEventListener('click', () => downloadNormalVideo(_lastUrl, 'tiktok_normal.mp4'));

    const hdPill = document.getElementById('_hdPill');
    if (hdPill) hdPill.addEventListener('click', () => requestPremium(_lastUrl, 'video'));

    showToast('Video found! Normal ডাউনলোড আনলিমিটেড, HD-তে দৈনিক কোটা প্রযোজ্য।', 'success');
}

// ===== অজানা টাইপ (সম্ভবত Photo পোস্ট) — kind: 'unknown' =====
function renderUnknownResult() {
    resultArea.innerHTML = `
        <div class="result-card">
            <p class="hd-lock-msg" style="margin-bottom:1rem">
                এটা সম্ভবত একটা ছবি (Photo) পোস্ট, অথবা normal ফরম্যাটে পাওয়া যায়নি।
                নিচের বাটনে ক্লিক করে HD/Photo হিসেবে চেষ্টা করুন (দৈনিক কোটা প্রযোজ্য)।
            </p>
            <div class="dl-btn-row">
                <button class="dl-btn dl-btn-hd dl-btn-full" id="_tryPremiumBtn">
                    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                    HD / Photo হিসেবে চেষ্টা করুন
                </button>
            </div>
            <div id="premiumArea"></div>
        </div>`;
    const btn = document.getElementById('_tryPremiumBtn');
    if (btn) btn.addEventListener('click', () => requestPremium(_lastUrl, 'unknown'));
}

// ===== Photo রেজাল্ট =====
function renderPhotoResult(data) {
    const safeTitle  = escapeHtml(data.title  || 'TikTok Photos');
    const safeAuthor = escapeHtml(data.author || 'Unknown');
    // data.images এখন [{url, ticket}, ...] — প্রতিটা ছবির নিজস্ব স্বল্পস্থায়ী
    // ticket থাকে (/media/stream ফলব্যাকের জন্য প্রয়োজন হলে)
    const photos = (data.images || []).map((img, i) => {
        const safeUrl = escapeHtml(img.url || '');
        const safeTicket = escapeHtml(img.ticket || '');
        return `
        <div class="photo-card">
            <div class="photo-preview">
                <img src="${safeUrl}" alt="Photo ${i + 1}" loading="lazy" onerror="this.closest('.photo-preview').innerHTML='<div class=photo-broken>🖼️</div>'">
            </div>
            <button class="photo-dl-btn" data-url="${safeUrl}" data-ticket="${safeTicket}" data-name="tiktok_photo_${i + 1}.jpg">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                Download
            </button>
        </div>`;
    }).join('');

    resultArea.innerHTML = `
        <div class="result-card">
            <div class="result-meta" style="margin-bottom:1rem">
                <div class="result-info">
                    <h3>${safeTitle}</h3>
                    <span class="result-author">@${safeAuthor}</span>
                </div>
            </div>
            <div class="photo-grid">${photos}</div>
        </div>`;

    // প্রতিটা ছবি সরাসরি CDN থেকে ক্লায়েন্ট-সাইড ফেচ — Render bandwidth শূন্য
    resultArea.querySelectorAll('.photo-dl-btn').forEach(btn => {
        btn.addEventListener('click', () => triggerDownload(btn.dataset.url, btn.dataset.name, 'direct-first', btn.dataset.ticket));
    });

    showToast(`${(data.images || []).length}টি ফটো পাওয়া গেছে!`, 'success');
}

function renderError(message) {
    resultArea.innerHTML = `
        <div class="error-box">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" style="flex-shrink:0;color:#f87171"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
            <span>${escapeHtml(message)}</span>
        </div>`;
    showToast(message, 'error');
}

// ===== HD / Photo গার্ডেড রিকোয়েস্ট (দৈনিক কোটা প্রযোজ্য) =====
async function requestPremium(url, context) {
    if (!url) return;
    const area = document.getElementById('premiumArea');
    if (area) area.innerHTML = `<div class="loading-wrap"><div class="spinner"></div><span>HD/Photo আনা হচ্ছে...</span></div>`;

    try {
        const res = await fetch('/media/premium', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url }),
        });
        const data = await res.json();

        if (res.status === 429 && data.error === 'limit_reached') {
            if (area) area.innerHTML = renderLockBox(data.limit_status);
            renderQuotaBadge(data.limit_status);
            showToast('আজকের HD/Photo কোটা শেষ।', 'error');
            return;
        }

        if (!data.success) {
            if (area) area.innerHTML = '';
            showToast(data.error || 'HD/Photo পাওয়া যায়নি।', 'error');
            return;
        }

        if (data.limit_status) renderQuotaBadge(data.limit_status);

        if (data.is_photo) {
            renderPhotoResult(data);
        } else if (data.hd_url) {
            if (area) area.innerHTML = '';
            triggerDownload(data.hd_url, 'tiktok_hd.mp4', 'direct-first', data.hd_ticket || '');
            showToast('HD ভিডিও পাওয়া গেছে!', 'success');
        }
    } catch {
        if (area) area.innerHTML = '';
        showToast('Network error. Please try again.', 'error');
    }
}

// ===== Main Download Process =====
async function processDownload() {
    if (_inFlight) { showToast('একটু অপেক্ষা করুন...', 'info'); return; }
    const url = urlInput.value.trim();
    if (!url) { showToast('Please paste a TikTok link first.', 'info'); return; }
    if (!url.includes('tiktok.com')) {
        renderError('Please enter a valid TikTok URL.');
        return;
    }

    _lastUrl = url;
    setLoading(true);
    _inFlight = true;
    try {
        const response = await fetch('/download', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url }),
        });
        const data = await response.json();

        if (data.success) {
            if (data.kind === 'video') {
                renderVideoResult(data);
            } else {
                renderUnknownResult();
            }
        } else {
            renderError(data.error || 'Something went wrong. Please try again.');
        }
    } catch {
        renderError('Network error. Please check your connection.');
    } finally {
        setLoading(false);
        _inFlight = false;
    }
}

// ===== Enter Key =====
urlInput.addEventListener('keydown', e => {
    if (e.key === 'Enter') processDownload();
});

// ===== FAQ Accordion =====
function toggleFaq(btn) {
    const item = btn.closest('.faq-item');
    const isOpen = item.classList.contains('open');
    document.querySelectorAll('.faq-item.open').forEach(i => i.classList.remove('open'));
    if (!isOpen) item.classList.add('open');
}

// ===== Smooth Scroll for nav links =====
document.querySelectorAll('a[href^="#"]').forEach(a => {
    a.addEventListener('click', e => {
        const target = document.querySelector(a.getAttribute('href'));
        if (target) {
            e.preventDefault();
            target.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
    });
});
