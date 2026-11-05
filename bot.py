import asyncio
import io
import os
import random
import re
import uuid

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from google import genai
from PIL import Image
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (Application, CallbackQueryHandler, ContextTypes,
                          MessageHandler, filters)

load_dotenv()

BOT_TOKEN = os.environ["BOT_TOKEN"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
AFFILIATE_TAG = os.environ["AFFILIATE_TAG"]
CHANNEL_ID = os.environ.get("CHANNEL_ID", "")
OWNER_ID = os.environ.get("OWNER_ID", "")
SCRAPER_API_KEY = os.environ.get("SCRAPER_API_KEY", "")
TEXT_MODEL = os.environ.get("GEMINI_TEXT_MODEL", "gemini-2.5-flash")
IMAGE_MODEL = os.environ.get("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")
MAX_PRODUCTS = int(os.environ.get("MAX_PRODUCTS", "10"))
DOMAIN = "https://www.amazon.eg"

client = genai.Client(api_key=GEMINI_API_KEY)

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept-Language": "ar-EG,ar;q=0.9,en;q=0.8",
}

STYLES = [
    "ابدأ بسؤال يلفت الانتباه",
    "احكي قصة قصيرة من موقف يومي بسيط",
    "اعرض المنتج كحل لمشكلة شائعة",
    "استخدم أسلوب حماسي وعرض حصري",
    "أسلوب هادئ وراقي يركز على الجودة",
    "ابدأ بجملة مفاجئة ثم اشرح الفائدة",
    "أسلوب صديق بينصح صاحبه",
    "استخدم إحساس بالإلحاح بدون ذكر أسعار أو نسب خصم",
]

DISCLOSURE = "\n\n(بصفتي شريك في برنامج عمولات أمازون، أحصل على عمولة من المشتريات المؤهلة)"


def fetch(url: str) -> str:
    if SCRAPER_API_KEY:
        r = requests.get("http://api.scraperapi.com",
                         params={"api_key": SCRAPER_API_KEY, "url": url},
                         timeout=70)
    else:
        r = requests.get(url, headers=HEADERS, timeout=25)
    r.raise_for_status()
    return r.text


def resolve(url: str) -> str:
    if re.search(r"amzn\.(to|eu)|a\.co", url):
        try:
            return requests.head(url, headers=HEADERS, allow_redirects=True,
                                 timeout=15).url
        except Exception:
            return url
    return url


def get_asin(url: str):
    m = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})", url)
    return m.group(1) if m else None


def affiliate_link(asin: str) -> str:
    return f"{DOMAIN}/dp/{asin}?tag={AFFILIATE_TAG}"


def scrape_product(asin: str) -> dict:
    html = fetch(f"{DOMAIN}/dp/{asin}")
    soup = BeautifulSoup(html, "html.parser")
    t = soup.select_one("#productTitle")
    title = t.get_text(strip=True) if t else ""
    if not title:
        og = soup.find("meta", property="og:title")
        title = og["content"] if og else ""
    img_url = None
    img = soup.select_one("#landingImage")
    if img:
        img_url = img.get("data-old-hires") or img.get("src")
    if not img_url:
        og = soup.find("meta", property="og:image")
        img_url = og["content"] if og else None
    bullets = [li.get_text(strip=True)
               for li in soup.select("#feature-bullets li")][:5]
    if not title or not img_url:
        raise RuntimeError("تعذر قراءة الصفحة (ممكن أمازون حظرت الطلب)")
    img_bytes = requests.get(img_url, headers=HEADERS, timeout=25).content
    return {"asin": asin, "title": title, "bullets": bullets,
            "image": img_bytes}


def find_asins(url: str) -> list:
    html = fetch(url)
    asins = []
    for a in re.findall(r"/(?:dp|gp/product)/([A-Z0-9]{10})", html):
        if a not in asins:
            asins.append(a)
    return asins[:MAX_PRODUCTS]


def make_ad_text(p: dict) -> str:
    style = random.choice(STYLES)
    prompt = (
        "اكتب إعلان قصير (4 إلى 6 أسطر) بالعامية المصرية لمنتج من أمازون مصر.\n"
        f"الأسلوب: {style}.\n"
        "اذكر مزايا حقيقية من البيانات فقط، ولا تذكر أي سعر أو نسبة خصم "
        "أو ادعاء غير موجود. اختم بدعوة لمشاهدة التفاصيل من الرابط. "
        "استخدم إيموجي بشكل خفيف. لا تكتب الرابط.\n\n"
        f"العنوان: {p['title']}\nالمميزات: {' | '.join(p['bullets'])}"
    )
    r = client.models.generate_content(model=TEXT_MODEL, contents=prompt)
    return (r.text or "").strip()


def make_ad_image(p: dict):
    prompt = (
        "Use the provided product image as the exact reference. Do NOT modify "
        "the product in any way: keep its shape, colors, logo, text, labels "
        "and packaging identical. Only change the background, lighting and "
        "surrounding scene to create a professional, eye-catching "
        "advertising image. No added text, no watermarks, no extra logos. "
        "Square 1:1."
    )
    ref = Image.open(io.BytesIO(p["image"]))
    r = client.models.generate_content(model=IMAGE_MODEL,
                                       contents=[prompt, ref])
    for part in r.candidates[0].content.parts:
        if getattr(part, "inline_data", None) and part.inline_data.data:
            return part.inline_data.data
    return None


def build_post(p: dict):
    text = make_ad_text(p)
    try:
        img = make_ad_image(p) or p["image"]
    except Exception as e:
        print("image gen failed:", e)
        img = p["image"]
    caption = f"{text}\n\n🛒 اطلبه من هنا:\n{affiliate_link(p['asin'])}{DISCLOSURE}"
    return img, caption[:1024]


def keyboard(pid: str):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ انشر في القناة", callback_data=f"pub:{pid}"),
        InlineKeyboardButton("🔄 أعد التوليد", callback_data=f"regen:{pid}"),
    ]])


def allowed(update: Update) -> bool:
    u = update.effective_user
    return not OWNER_ID or (u and str(u.id) == OWNER_ID)


async def send_post(chat_id, context, p: dict):
    img, caption = await asyncio.to_thread(build_post, p)
    pid = uuid.uuid4().hex[:10]
    context.application.bot_data.setdefault("posts", {})[pid] = {
        "product": p, "image": img, "caption": caption}
    await context.bot.send_photo(chat_id, photo=img, caption=caption,
                                 reply_markup=keyboard(pid))


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return
    urls = re.findall(r"https?://\S+", update.message.text or "")
    if not urls:
        await update.message.reply_text("ابعتلي لينك منتج أو صفحة عروض من أمازون مصر.")
        return
    chat_id = update.effective_chat.id
    for raw in urls:
        url = resolve(raw)
        try:
            asin = get_asin(url)
            if asin:
                asins = [asin]
            else:
                await update.message.reply_text("⏳ بحلل الصفحة...")
                asins = await asyncio.to_thread(find_asins, url)
            if not asins:
                await update.message.reply_text("ملقيتش منتجات في اللينك ده.")
                continue
            for a in asins:
                try:
                    p = await asyncio.to_thread(scrape_product, a)
                    await send_post(chat_id, context, p)
                except Exception as e:
                    await update.message.reply_text(f"❌ فشل المنتج {a}: {e}")
                await asyncio.sleep(2)
        except Exception as e:
            await update.message.reply_text(f"❌ خطأ: {e}")


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not allowed(update):
        return
    action, pid = q.data.split(":", 1)
    post = context.application.bot_data.get("posts", {}).get(pid)
    if not post:
        await q.message.reply_text("البوست ده انتهت صلاحيته، ابعت اللينك تاني.")
        return
    if action == "pub":
        if not CHANNEL_ID:
            await q.message.reply_text("CHANNEL_ID مش متحدد في ملف .env")
            return
        try:
            await context.bot.send_photo(CHANNEL_ID, photo=post["image"],
                                         caption=post["caption"])
            await q.message.reply_text("✅ اتنشر في القناة")
        except Exception as e:
            await q.message.reply_text(f"❌ فشل النشر: {e}")
    elif action == "regen":
        try:
            await send_post(q.message.chat_id, context, post["product"])
        except Exception as e:
            await q.message.reply_text(f"❌ فشل التوليد: {e}")


async def on_channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """اكتب /chatid في القناة (والبوت أدمن) ليرد برقم القناة."""
    post = update.channel_post
    if post and (post.text or "").startswith("/chatid"):
        await context.bot.send_message(post.chat.id, f"CHANNEL_ID = {post.chat.id}")


def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND
                                   & filters.ChatType.PRIVATE, on_message))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.UpdateType.CHANNEL_POST,
                                   on_channel_post))
    print("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
