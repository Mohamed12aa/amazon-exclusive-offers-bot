import os, re, io, asyncio, random, requests
from bs4 import BeautifulSoup
from PIL import Image
from google import genai
from google.genai import types
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (ApplicationBuilder, MessageHandler,
                          CallbackQueryHandler, ContextTypes, filters)

# ====== الإعدادات (كلها بتتقرأ من Railway Variables) ======
AFFILIATE_TAG  = os.getenv("AFFILIATE_TAG")
BOT_TOKEN      = os.getenv("BOT_TOKEN")
GEMINI_KEY     = os.getenv("GEMINI_API_KEY")
OWNER_ID       = int(os.getenv("OWNER_ID", "0"))
TARGET_CHANNEL = os.getenv("TARGET_CHANNEL")
TEXT_MODEL     = os.getenv("TEXT_MODEL", "gemini-2.5-flash")
IMAGE_MODEL    = os.getenv("IMAGE_MODEL", "gemini-2.5-flash-image")

missing = [k for k, v in {
    "BOT_TOKEN": BOT_TOKEN, "GEMINI_API_KEY": GEMINI_KEY,
    "AFFILIATE_TAG": AFFILIATE_TAG, "TARGET_CHANNEL": TARGET_CHANNEL,
    "OWNER_ID": OWNER_ID or None}.items() if not v]
if missing:
    raise SystemExit(f"متغيرات ناقصة في Variables: {', '.join(missing)}")

client = genai.Client(api_key=GEMINI_KEY)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "ar-EG,ar;q=0.9,en;q=0.8",
}
STYLES = [
    "أسلوب حماسي مع إيموجي", "أسلوب قصصي بسيط (مشكلة وحل)",
    "أسلوب سؤال وجواب", "أسلوب عرض مباشر ومختصر",
    "أسلوب مقارنة (قبل وبعد)", "أسلوب نصيحة من صديق",
]
pending = {}

# ====== أدوات أمازون ======
def resolve(url):
    try:
        return requests.get(url, headers=HEADERS, allow_redirects=True, timeout=15).url
    except Exception:
        return url

def get_asin(url):
    m = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})", url)
    return m.group(1) if m else None

def affiliate_link(asin):
    return f"https://www.amazon.eg/dp/{asin}?tag={AFFILIATE_TAG}"

def scrape_product(asin):
    r = requests.get(f"https://www.amazon.eg/dp/{asin}", headers=HEADERS, timeout=20)
    soup = BeautifulSoup(r.text, "html.parser")
    title = soup.select_one("#productTitle")
    if not title:
        return None
    bullets = [li.get_text(strip=True) for li in
               soup.select("#feature-bullets li span.a-list-item")][:6]
    img = soup.select_one("#landingImage")
    img_url = None
    if img:
        img_url = img.get("data-old-hires") or img.get("src")
    return {"title": title.get_text(strip=True), "bullets": bullets,
            "image": img_url, "asin": asin}

def scrape_listing(url):
    r = requests.get(url, headers=HEADERS, timeout=20)
    asins = re.findall(r"/dp/([A-Z0-9]{10})", r.text)
    return list(dict.fromkeys(asins))[:15]

# ====== Gemini ======
def write_ad(p):
    style = random.choice(STYLES)
    prompt = f"""اكتب بوست إعلاني قصير بالعامية المصرية لقناة تليجرام.
المنتج: {p['title']}
المميزات: {' | '.join(p['bullets'])}
الأسلوب المطلوب: {style}
الشروط: من 4 لـ 7 سطور، بدون ذكر السعر، فيه إيموجي مناسبة،
وينتهي بدعوة للضغط على الرابط. اكتب البوست فقط."""
    res = client.models.generate_content(model=TEXT_MODEL, contents=prompt)
    return res.text.strip()

def make_ad_image(p):
    if not p["image"]:
        return None
    src = Image.open(io.BytesIO(requests.get(p["image"], timeout=20).content))
    prompt = ("حوّل صورة المنتج دي لصورة إعلانية احترافية: خلفية جذابة وإضاءة استوديو، "
              "حافظ على شكل المنتج الأصلي بدون تغيير، ومساحة فاضية للنص. "
              "من غير أي كتابة أو أسعار على الصورة.")
    try:
        res = client.models.generate_content(
            model=IMAGE_MODEL,
            contents=[prompt, src],
            config=types.GenerateContentConfig(response_modalities=["IMAGE"]),
        )
        for part in res.candidates[0].content.parts:
            if part.inline_data:
                return part.inline_data.data
    except Exception as e:
        print("image error:", e)
    return None

# ====== معالجة منتج واحد ======
async def process(asin, update, ctx):
    p = scrape_product(asin)
    if not p:
        await update.message.reply_text(f"⚠️ مقدرتش أسحب المنتج {asin} (ممكن أمازون حظرت الطلب)")
        return
    ad = write_ad(p)
    link = affiliate_link(asin)
    caption = f"{ad}\n\n🛒 اشتري من هنا 👇\n{link}\n\n#إعلان (رابط أفيليت)"
    img = make_ad_image(p)
    if img is None and p["image"]:
        img = requests.get(p["image"], timeout=20).content

    key = f"{asin}_{random.randint(1000,9999)}"
    pending[key] = (img, caption)
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ نشر على القناة", callback_data=f"pub|{key}"),
        InlineKeyboardButton("❌ تجاهل", callback_data=f"del|{key}"),
    ]])
    if img:
        await update.message.reply_photo(photo=img, caption=caption[:1024], reply_markup=kb)
    else:
        await update.message.reply_text(caption, reply_markup=kb)

# ====== استقبال الرسائل ======
async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    text = update.message.text or ""
    m = re.search(r"https?://\S+", text)
    if not m:
        return
    url = resolve(m.group(0))
    asin = get_asin(url)

    if asin:
        await update.message.reply_text("⏳ جاري التجهيز...")
        await process(asin, update, ctx)
    else:
        await update.message.reply_text("📄 بحلل الصفحة...")
        asins = scrape_listing(url)
        await update.message.reply_text(f"لقيت {len(asins)} منتج، هبدأ واحد واحد")
        for a in asins:
            await process(a, update, ctx)
            await asyncio.sleep(random.randint(5, 10))

# ====== زراير النشر ======
async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    action, key = q.data.split("|")
    if action == "del":
        pending.pop(key, None)
        await q.edit_message_reply_markup(None)
        return
    data = pending.pop(key, None)
    if not data:
        await q.message.reply_text("البوست ده اتنشر قبل كده أو انتهت صلاحيته")
        return
    img, caption = data
    if img:
        await ctx.bot.send_photo(TARGET_CHANNEL, photo=img, caption=caption[:1024])
    else:
        await ctx.bot.send_message(TARGET_CHANNEL, caption)
    await q.edit_message_reply_markup(None)
    await q.message.reply_text("✅ اتنشر على القناة")

app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
app.add_handler(CallbackQueryHandler(on_button))
app.run_polling()
