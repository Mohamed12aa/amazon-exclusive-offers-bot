import os
import re
import json
import html
import time
import random
import asyncio
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters

# ----------------------------- الإعدادات -----------------------------
MY_TAG = os.getenv("AFFILIATE_TAG", "iexclusiveoff-21")
MAX_PRODUCTS = int(os.getenv("MAX_PRODUCTS", "8"))          # أقصى عدد منتجات من صفحة عروض
SCRAPER_API_KEY = os.getenv("SCRAPER_API_KEY")               # اختياري: لتخطي حظر أمازون
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")           # اختياري: لكتابة إعلان قوي بالذكاء الاصطناعي
SHOW_PRICE = os.getenv("SHOW_PRICE", "0") == "1"             # إظهار السعر (راجع شروط أمازون)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ar,en;q=0.8",
}

URL_RE = re.compile(
    r"(?:https?://)?(?:[\w-]+\.)*(?:amazon\.[a-z]{2,3}(?:\.[a-z]{2})?|amzn\.to|amzn\.eu|a\.co)(?:/\S*)?",
    re.I,
)
ASIN_RE = re.compile(r"/(?:dp|gp/product|gp/aw/d|product)/([A-Z0-9]{10})", re.I)
SHORT_HOSTS = ("amzn.to", "amzn.eu", "a.co")

HOOKS = [
    "🔥 لقطة اليوم من أمازون!",
    "⚡ عرض لفترة محدودة.. لا تفوّت الفرصة!",
    "💎 صفقة تستاهل التجربة!",
    "🚀 من أكتر المنتجات طلباً دلوقتي!",
    "🎯 اغتنم الفرصة ووفّر الآن!",
    "🌟 عرض مميز أُضيف حديثاً!",
    "💡 منتج عملي مش هتستغنى عنه!",
    "👑 اخترنا لك الأفضل النهاردة!",
    "💥 تخفيض قوي.. الحق قبل ما يخلص!",
    "✨ سهّل حياتك مع المنتج ده!",
]


# ----------------------- سيرفر صغير للـ Railway -----------------------
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot is alive and running!")

    def log_message(self, *args):
        pass


def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    HTTPServer(("0.0.0.0", port), SimpleHandler).serve_forever()


# ----------------------------- أدوات الروابط -----------------------------
def resolve_url(url: str) -> str:
    """يفك الروابط المختصرة (amzn.to / a.co) ويرجع الرابط الحقيقي."""
    host = urlparse(url).netloc.lower()
    if any(host == h or host.endswith("." + h) for h in SHORT_HOSTS):
        try:
            r = requests.get(url, headers=HEADERS, timeout=15, allow_redirects=True, stream=True)
            final = r.url
            r.close()
            return final
        except Exception as e:
            print("Resolve error:", e)
    return url


def normalize_host(host: str) -> str:
    return re.sub(r"^.*?(amazon\.)", r"www.amazon.", host.lower())


def affiliate_url(host: str, asin: str) -> str:
    # رابط نظيف: أي رابط إحالة تاني بيتشال تماماً ويتحط رابطك
    return f"https://{host}/dp/{asin}?tag={MY_TAG}"


def is_blocked(text: str) -> bool:
    t = text[:30000].lower()
    return ("validatecaptcha" in t
            or "enter the characters you see" in t
            or "api-services-support@amazon.com" in t)


LAST_REASON = {"msg": ""}


def fetch_html(url: str):
    """يجيب الصفحة مباشرة، ولو أمازون حجبت يجرب ScraperAPI (لو متفعّل)."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        if r.status_code == 200 and not is_blocked(r.text):
            return r.text
        reason = f"أمازون رجّعت كود {r.status_code}" + (" (صفحة captcha)" if is_blocked(r.text) else "")
        LAST_REASON["msg"] = reason
        print("Direct fetch failed:", reason, url)
    except Exception as e:
        LAST_REASON["msg"] = f"خطأ اتصال: {e}"
        print("Direct fetch error:", e)

    if SCRAPER_API_KEY:
        try:
            r = requests.get(
                "https://api.scraperapi.com/",
                params={"api_key": SCRAPER_API_KEY, "url": url},
                timeout=70,
            )
            if r.status_code == 200 and not is_blocked(r.text):
                return r.text
            LAST_REASON["msg"] = f"ScraperAPI رجّع كود {r.status_code}"
            print("Scraper failed:", r.status_code, r.text[:200])
        except Exception as e:
            LAST_REASON["msg"] = f"خطأ ScraperAPI: {e}"
            print("Scraper fetch error:", e)
    return None


def microlink_product(host: str, asin: str):
    """بديل احتياطي لو أمازون حجبت: Microlink (مع فلترة النتائج الغلط)."""
    try:
        r = requests.get("https://api.microlink.io", params={"url": f"https://{host}/dp/{asin}"}, timeout=25)
        d = r.json()
        if d.get("status") != "success":
            LAST_REASON["msg"] += f" | Microlink: {d.get('message', 'فشل')}"
            return None
        item = d.get("data", {})
        title = (item.get("title") or "").strip()
        bad = ("robot check", "sorry", "page not found", "captcha", "عذراً", "عذرا")
        if not title or any(b in title.lower() for b in bad) or len(title) < 8:
            LAST_REASON["msg"] += " | Microlink رجّع عنوان غير صالح"
            return None
        title = re.sub(r"^Amazon\.[a-z.]+\s*:\s*", "", title, flags=re.I)
        img = (item.get("image") or {}).get("url")
        if img and "/images/I/" not in img:   # يرفض اللوجو وأي صورة مش للمنتج
            img = None
        return {"asin": asin, "title": title, "image": img, "price": None, "link": affiliate_url(host, asin)}
    except Exception as e:
        LAST_REASON["msg"] += f" | Microlink error: {e}"
        return None


# ----------------------------- قراءة المنتج -----------------------------
def pick_image(soup: BeautifulSoup):
    img = soup.select_one("#landingImage, #imgBlkFront, #main-image")
    if img:
        dyn = img.get("data-a-dynamic-image")
        if dyn:
            try:
                sizes = json.loads(dyn)
                return max(sizes.items(), key=lambda kv: kv[1][0] * kv[1][1])[0]  # أكبر نسخة
            except Exception:
                pass
        for attr in ("data-old-hires", "src"):
            v = img.get(attr)
            if v and v.startswith("http"):
                return v
    og = soup.find("meta", property="og:image")
    if og and og.get("content") and "logo" not in og["content"].lower():
        return og["content"]
    return None


def get_product(host: str, asin: str):
    page = fetch_html(f"https://{host}/dp/{asin}")
    if not page:
        return microlink_product(host, asin)
    soup = BeautifulSoup(page, "html.parser")

    t = soup.select_one("#productTitle")
    title = t.get_text(" ", strip=True) if t else None
    if not title:
        og = soup.find("meta", property="og:title")
        title = og["content"].strip() if og and og.get("content") else None
    if not title:
        LAST_REASON["msg"] = "الصفحة اتحملت بس مفيهاش عنوان منتج"
        return microlink_product(host, asin)

    price = None
    if SHOW_PRICE:
        p = soup.select_one("#corePrice_feature_div .a-offscreen, span.a-price .a-offscreen")
        price = p.get_text(strip=True) if p else None

    return {
        "asin": asin,
        "title": title,                       # العنوان كامل بدون قص
        "image": pick_image(soup),
        "price": price,
        "link": affiliate_url(host, asin),
    }


def extract_asins(page: str):
    """يطلع كل الـ ASIN من صفحة عروض/بحث/قائمة بالترتيب بدون تكرار."""
    found = []
    soup = BeautifulSoup(page, "html.parser")
    for a in soup.find_all("a", href=True):
        m = ASIN_RE.search(a["href"])
        if m:
            found.append(m.group(1).upper())
    for m in re.finditer(r'data-asin="([A-Z0-9]{10})"', page):
        found.append(m.group(1))
    seen, out = set(), []
    for x in found:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def collect_products(url: str):
    url = resolve_url(url)
    host = normalize_host(urlparse(url).netloc)
    m = ASIN_RE.search(url)

    if m:
        asins = [m.group(1).upper()]
    else:
        page = fetch_html(url)
        asins = extract_asins(page)[:MAX_PRODUCTS] if page else []

    products = []
    for asin in asins:
        p = get_product(host, asin)
        if p:
            products.append(p)
        if len(asins) > 1:
            time.sleep(random.uniform(1.0, 2.0))   # عشان أمازون ما تحجبناش
    return products


# ----------------------------- كتابة الإعلان -----------------------------
def ai_ad(title: str):
    if not ANTHROPIC_API_KEY:
        return None
    prompt = (
        "اكتب إعلاناً تسويقياً قصيراً وقوياً بالعربية (بلهجة بيضاء مفهومة) لقناة تيليجرام عن المنتج التالي.\n"
        "الشروط: من 2 إلى 3 أسطر فقط، يبدأ بجملة جذب قوية، يذكر أهم فائدة مفهومة من اسم المنتج، "
        "مع إيموجي مناسب، وينتهي بدعوة للشراء.\n"
        "ممنوع: اختراع مواصفات أو أسعار أو نسب خصم غير موجودة في الاسم، وممنوع كتابة اسم المنتج أو أي رابط.\n"
        "اكتب نص الإعلان فقط بدون أي مقدمة.\n\n"
        f"اسم المنتج: {title}"
    )
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-5-5",
                "max_tokens": 300,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=30,
        )
        text = r.json()["content"][0]["text"].strip()
        return text[:500] or None
    except Exception as e:
        print("AI ad error:", e)
        return None


def build_caption(p: dict) -> str:
    body = ai_ad(p["title"]) or random.choice(HOOKS)
    lines = [html.escape(body), "", f"📌 <b>{html.escape(p['title'])}</b>"]
    if p.get("price"):
        lines.append(f"💰 {html.escape(p['price'])}")
    lines += ["", f'🛒 <a href="{html.escape(p["link"], quote=True)}">اطلبه الآن من أمازون</a>']
    return "\n".join(lines)


def download_image(url: str):
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code == 200 and r.headers.get("content-type", "").startswith("image"):
            return r.content
    except Exception as e:
        print("Image download error:", e)
    return None


# ----------------------------- تيليجرام -----------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "أهلاً بك! 👋\nابعتلي رابط منتج أمازون، أو رابط صفحة عروض فيها منتجات كتير، "
        "وأنا هجهز لك إعلان لكل منتج بالصورة والعنوان الكامل ورابط الإحالة بتاعك."
    )


async def send_product(update: Update, p: dict):
    caption = build_caption(p)
    img = await asyncio.to_thread(download_image, p["image"]) if p.get("image") else None

    if img:
        try:
            if len(caption) <= 1024:  # حد تيليجرام لكابشن الصورة
                await update.message.reply_photo(photo=img, caption=caption, parse_mode=ParseMode.HTML)
            else:
                await update.message.reply_photo(photo=img)
                await update.message.reply_text(caption, parse_mode=ParseMode.HTML)
            return
        except Exception as e:
            print("Photo send error:", e)

    await update.message.reply_text(caption, parse_mode=ParseMode.HTML)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    urls = [u.rstrip(".,)،") for u in URL_RE.findall(text)]
    urls = [u if u.lower().startswith("http") else "https://" + u for u in urls]

    if not urls:
        await update.message.reply_text("من فضلك أرسل رابط أمازون صالح.")
        return

    status = await update.message.reply_text("⏳ جاري قراءة المنتجات وتجهيز الإعلانات...")
    total = 0

    for url in urls:
        products = await asyncio.to_thread(collect_products, url)
        for p in products:
            await send_product(update, p)
            total += 1
            await asyncio.sleep(0.6)  # تجنب حدود الإرسال في تيليجرام

    try:
        await status.delete()
    except Exception:
        pass

    if total == 0:
        await update.message.reply_text(
            "❌ معرفتش أقرا بيانات المنتج.\n"
            f"السبب: {LAST_REASON['msg'] or 'الرابط مش لمنتج أو صفحة عروض ما فيهاش منتجات ظاهرة'}"
        )


if __name__ == "__main__":
    TOKEN = os.getenv("TELEGRAM_TOKEN")
    if not TOKEN:
        print("Error: TELEGRAM_TOKEN variable missing.")
        raise SystemExit(1)

    threading.Thread(target=run_web_server, daemon=True).start()

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

    print("Bot is running...")
    app.run_polling()
