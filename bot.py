
import os
import re
import io
import asyncio
import random
import requests

from bs4 import BeautifulSoup
from PIL import Image
from google import genai
from google.genai import types

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)

from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)

# ==================================================
# 1. RAILWAY DEBUG - اختبار متغيرات البيئة
# ==================================================

print("\n========== RAILWAY DEBUG ==========", flush=True)

required_vars = [
    "BOT_TOKEN",
    "GEMINI_API_KEY",
    "AFFILIATE_TAG",
    "TARGET_CHANNEL",
    "OWNER_ID"
]

for name in required_vars:
    value = os.getenv(name)
    status = "FOUND" if value and value.strip() else "MISSING"
    print(f"{name}: {status}", flush=True)

print(
    "SERVICE:",
    os.getenv("RAILWAY_SERVICE_NAME", "NOT FOUND"),
    flush=True
)

print(
    "ENVIRONMENT:",
    os.getenv("RAILWAY_ENVIRONMENT_NAME", "NOT FOUND"),
    flush=True
)

print(
    "PROJECT:",
    os.getenv("RAILWAY_PROJECT_NAME", "NOT FOUND"),
    flush=True
)

print("==================================\n", flush=True)


# ==================================================
# 2. قراءة الإعدادات
# ==================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
GEMINI_KEY = os.getenv("GEMINI_API_KEY", "").strip()
AFFILIATE_TAG = os.getenv("AFFILIATE_TAG", "").strip()
TARGET_CHANNEL = os.getenv("TARGET_CHANNEL", "").strip()

OWNER_ID_RAW = os.getenv("OWNER_ID", "").strip()

TEXT_MODEL = os.getenv("TEXT_MODEL", "gemini-1.5-flash")
IMAGE_MODEL = os.getenv("IMAGE_MODEL", "gemini-1.5-flash")

# ==================================================
# 3. التأكد من وجود المتغيرات
# ==================================================

missing = [
    name for name in required_vars
    if not os.getenv(name, "").strip()
]

if missing:
    raise SystemExit(
        f"متغيرات ناقصة في Variables: {', '.join(missing)}"
    )

try:
    OWNER_ID = int(OWNER_ID_RAW)
except ValueError:
    raise SystemExit("OWNER_ID لازم يكون رقم Telegram صحيح")


if OWNER_ID <= 0:
    raise SystemExit("OWNER_ID غير صحيح")


print("✅ All environment variables loaded successfully!", flush=True)


# ==================================================
# 4. إعداد Gemini
# ==================================================

client = genai.Client(api_key=GEMINI_KEY)


# ==================================================
# 5. إعدادات الاتصال بأمازون
# ==================================================

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "ar-EG,ar;q=0.9,en;q=0.8"
}


STYLES = [
    "أسلوب حماسي مع إيموجي",
    "أسلوب قصصي بسيط (مشكلة وحل)",
    "أسلوب سؤال وجواب",
    "أسلوب عرض مباشر ومختصر",
    "أسلوب مقارنة (قبل وبعد)",
    "أسلوب نصيحة من صديق"
]


pending = {}


# ==================================================
# 6. أدوات أمازون
# ==================================================

def resolve(url):
    try:
        response = requests.get(
            url,
            headers=HEADERS,
            allow_redirects=True,
            timeout=15
        )
        return response.url

    except Exception as e:
        print("Resolve error:", e, flush=True)
        return url


def get_asin(url):
    match = re.search(
        r"/(?:dp|gp/product)/([A-Z0-9]{10})",
        url
    )

    return match.group(1) if match else None


def affiliate_link(asin):
    return (
        f"https://www.amazon.eg/dp/{asin}"
        f"?tag={AFFILIATE_TAG}"
    )


def scrape_product(asin):

    try:
        response = requests.get(
            f"https://www.amazon.eg/dp/{asin}",
            headers=HEADERS,
            timeout=20
        )

        response.raise_for_status()

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )

        title = soup.select_one("#productTitle")

        if not title:
            print(
                f"Product title not found: {asin}",
                flush=True
            )
            return None

        bullets = [
            li.get_text(strip=True)
            for li in soup.select(
                "#feature-bullets li span.a-list-item"
            )
        ][:6]

        img = soup.select_one("#landingImage")

        img_url = None

        if img:
            img_url = (
                img.get("data-old-hires")
                or img.get("src")
            )

        return {
            "title": title.get_text(strip=True),
            "bullets": bullets,
            "image": img_url,
            "asin": asin
        }

    except Exception as e:
        print("Scraping error:", e, flush=True)
        return None


def scrape_listing(url):

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=20
        )

        response.raise_for_status()

        asins = re.findall(
            r"/dp/([A-Z0-9]{10})",
            response.text
        )

        return list(dict.fromkeys(asins))[:15]

    except Exception as e:
        print("Listing error:", e, flush=True)
        return []


# ==================================================
# 7. كتابة الإعلان باستخدام Gemini
# ==================================================

def write_ad(product):

    style = random.choice(STYLES)

    prompt = f"""
اكتب بوست إعلاني قصير بالعامية المصرية لقناة تليجرام.

المنتج:
{product['title']}

المميزات:
{' | '.join(product['bullets'])}

الأسلوب المطلوب:
{style}

الشروط:
- من 4 إلى 7 سطور.
- استخدم العامية المصرية الطبيعية.
- استخدم إيموجي مناسبة.
- بدون ذكر السعر.
- لا تخترع مميزات غير موجودة.
- اختم بدعوة للضغط على الرابط.
- اجعل أسلوب الإعلان مختلفا عن الإعلانات التقليدية.

اكتب البوست فقط.
"""

    response = client.models.generate_content(
        model=TEXT_MODEL,
        contents=prompt
    )

    return response.text.strip()


# ==================================================
# 8. إنشاء صورة إعلانية باستخدام Gemini
# ==================================================

def make_ad_image(product):

    if not product["image"]:
        return None

    try:
        image_response = requests.get(
            product["image"],
            headers=HEADERS,
            timeout=20
        )

        image_response.raise_for_status()

        src = Image.open(
            io.BytesIO(image_response.content)
        )

        src.load()

        prompt = """
حوّل صورة المنتج المرفقة إلى صورة إعلانية احترافية.

المطلوب:
- خلفية جذابة ومناسبة لطبيعة المنتج.
- إضاءة استوديو احترافية.
- جودة عالية وتفاصيل واضحة.
- حافظ على شكل المنتج الأصلي تماما.
- لا تغير تصميم المنتج أو علامته التجارية.
- اترك مساحة مناسبة للنص.
- لا تضف أي كتابة أو أسعار أو شعارات جديدة.
"""

        try:
            response = client.models.generate_content(
                model=IMAGE_MODEL,
                contents=[prompt, src],
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE"]
                )
            )

            for part in response.candidates[0].content.parts:

                if part.inline_data:
                    return part.inline_data.data

        except Exception as e:
            print(
                "Gemini image generation error:",
                e,
                flush=True
            )

        return None

    except Exception as e:
        print("Image processing error:", e, flush=True)
        return None


# ==================================================
# 9. تجهيز المنتج وإرسال المعاينة
# ==================================================

async def process(asin, update, ctx):

    try:

        product = await asyncio.to_thread(
            scrape_product,
            asin
        )

        if not product:
            await update.message.reply_text(
                f"⚠️ مقدرتش أسحب المنتج {asin}"
            )
            return

        await update.message.reply_text(
            "✍️ جاري كتابة الإعلان..."
        )

        ad = await asyncio.to_thread(
            write_ad,
            product
        )

        link = affiliate_link(asin)

        caption = (
            f"{ad}\n\n"
            f"🛒 اشتري من هنا 👇\n"
            f"{link}\n\n"
            f"#إعلان (رابط أفيليت)"
        )

        await update.message.reply_text(
            "🎨 جاري تجهيز الصورة الإعلانية..."
        )

        img = await asyncio.to_thread(
            make_ad_image,
            product
        )

        # في حالة فشل Gemini نستخدم صورة المنتج الأصلية

        if img is None and product["image"]:

            try:
                image_response = requests.get(
                    product["image"],
                    headers=HEADERS,
                    timeout=20
                )

                image_response.raise_for_status()

                img = image_response.content

            except Exception as e:
                print("Original image error:", e, flush=True)

        key = f"{asin}_{random.randint(1000, 9999)}"

        pending[key] = (img, caption)

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "✅ نشر",
                    callback_data=f"pub|{key}"
                ),
                InlineKeyboardButton(
                    "❌ تجاهل",
                    callback_data=f"del|{key}"
                )
            ]
        ])

        if img:

            await update.message.reply_photo(
                photo=img,
                caption=caption[:1024],
                reply_markup=keyboard
            )

        else:

            await update.message.reply_text(
                caption,
                reply_markup=keyboard
            )

    except Exception as e:

        print("Process error:", e, flush=True)

        await update.message.reply_text(
            f"⚠️ حصل خطأ أثناء تجهيز المنتج:\n{str(e)[:500]}"
        )


# ==================================================
# 10. استقبال روابط المنتجات
# ==================================================

async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):

    if update.effective_user.id != OWNER_ID:
        return

    text = update.message.text or ""

    match = re.search(
        r"https?://\S+",
        text
    )

    if not match:
        return

    url = match.group(0).rstrip(".,)")

    await update.message.reply_text(
        "🔍 جاري تحليل الرابط..."
    )

    url = await asyncio.to_thread(
        resolve,
        url
    )

    asin = get_asin(url)

    # منتج واحد

    if asin:

        await update.message.reply_text(
            "⏳ جاري تجهيز المنتج..."
        )

        await process(asin, update, ctx)

    # صفحة عروض أو قائمة منتجات

    else:

        await update.message.reply_text(
            "📄 بحلل صفحة المنتجات..."
        )

        asins = await asyncio.to_thread(
            scrape_listing,
            url
        )

        if not asins:

            await update.message.reply_text(
                "⚠️ مقدرتش أستخرج منتجات من الصفحة."
            )
            return

        await update.message.reply_text(
            f"✅ لقيت {len(asins)} منتج.\n"
            "هبدأ تجهيزهم واحد واحد."
        )

        for index, asin in enumerate(asins, 1):

            await update.message.reply_text(
                f"📦 المنتج {index} من {len(asins)}"
            )

            await process(asin, update, ctx)

            if index < len(asins):
                delay = random.randint(8, 15)

                print(
                    f"Waiting {delay} seconds...",
                    flush=True
                )

                await asyncio.sleep(delay)


# ==================================================
# 11. أزرار النشر والتجاهل
# ==================================================

async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query

    # السماح للمالك فقط بالتحكم في الأزرار

    if not update.effective_user or update.effective_user.id != OWNER_ID:

        await query.answer(
            "غير مسموح لك باستخدام الزر.",
            show_alert=True
        )
        return

    await query.answer()

    action, key = query.data.split("|", 1)

    # تجاهل الإعلان

    if action == "del":

        pending.pop(key, None)

        await query.edit_message_reply_markup(
            reply_markup=None
        )

        await query.message.reply_text(
            "🗑️ تم تجاهل الإعلان."
        )

        return

    # نشر الإعلان

    if action == "pub":

        data = pending.pop(key, None)

        if not data:

            await query.message.reply_text(
                "⚠️ البوست ده اتنشر قبل كده أو انتهت صلاحيته."
            )
            return

        img, caption = data

        try:

            if img:

                await ctx.bot.send_photo(
                    chat_id=TARGET_CHANNEL,
                    photo=img,
                    caption=caption[:1024]
                )

            else:

                await ctx.bot.send_message(
                    chat_id=TARGET_CHANNEL,
                    text=caption
                )

            await query.edit_message_reply_markup(
                reply_markup=None
            )

            await query.message.reply_text(
                "✅ تم نشر الإعلان على القناة بنجاح!"
            )

        except Exception as e:

            print("Telegram publishing error:", e, flush=True)

            # إعادة البوست للقائمة لو النشر فشل

            pending[key] = (img, caption)

            await query.message.reply_text(
                f"❌ فشل النشر:\n{str(e)[:500]}"
            )


# ==================================================
# 12. تشغيل البوت
# ==================================================

def main():

    print("🚀 Starting Telegram bot...", flush=True)

    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .build()
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            on_message
        )
    )

    app.add_handler(
        CallbackQueryHandler(on_button)
    )

    print("✅ Bot is starting polling...", flush=True)

    app.run_polling()


if __name__ == "__main__":
    main()
