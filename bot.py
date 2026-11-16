import asyncio
import logging
import os
import sys
import re
import time
import random
import sqlite3
import urllib.parse
from io import BytesIO
import aiohttp
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, URLInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder
from telethon import TelegramClient, events
from telethon.sessions import StringSession

try:
    import qrcode
    HAS_QRCODE_LIB = True
except ImportError:
    HAS_QRCODE_LIB = False

logging.basicConfig(level=logging.INFO, stream=sys.stdout)

# ==================== 1. MAIN CONFIGURATION ====================
BOT_TOKEN = os.getenv("BOT_TOKEN", "9272691697:AAHfFzOIzDlyQHKIqtn1LWtP8QX83Iggzu0")
ADMIN_IDS = {6996401122, 8508701710}

API_ID = int(os.getenv("API_ID", "33462002"))
API_HASH = os.getenv("API_HASH", "c684a0e32627cabb231a8860c454834d")

SESSION_STRING = os.getenv(
    "SESSION_STRING",
    "1BVtsOGUBu8D-Zl9XZw_gmKq_gBAtv0sE65Z7bEsun1lD1Pbt0Je94QNEE_36ZqfNlObAJNMIpy-ODLisjNYyTBHTwefhvuu0dfgdLRX72zgvOYxsggXeFTNHnb3DamNph05LVx_V2dimQA3KCqSGO-CnUKvPhSg5kmbiJnEpxawoLolpaDFuh1b-Uoyov0Y1T7Iq6-AS1eYjd1nssjd8M1n65_JI5sGpJ-e6wRQj8raVmaNL6ZlcnmYdf2Rf25qf4v6rftcJMzSGKeAdl2h6Q5ltBwApfPNLERQa4Jeu4RqNMRZRdZQ4shGOEFGudXB2TYecoQuSmvClYX3Bj1wAP_n6YF8rPyA="
)

SOURCE_BOT = os.getenv("SOURCE_BOT", "tgsshopprobot")
PROFIT_MULTIPLIER = 1.5
UPI_ID = "Paytm.s2b9rko@pty"
MERCHANT_NAME = "TG Store"
SUPPORT_USERNAME = "@Tgshopssupport"

# ==================== 2. FORWARDER & REPLACER CONFIG ====================
ENABLE_INTERVAL_FORWARDER = True
INTERVAL_SOURCE_CHANNEL = "jgitih"
INTERVAL_MESSAGE_ID = 2

INTERVAL_TARGET_CHANNELS = [
    "@USA_Buying_Selling_Pages_Market",
    "@buyingandsellingigandfb",
    "@Sell_Buy_accountGroups",
]
REPEAT_INTERVAL_MINUTES = 30

ENABLE_AUTO_REPLACER = True
REPLACER_SOURCE_CHANNELS = [
    "TGSHOPLOGS",
    "sunilsainikotputli"
]
REPLACER_TARGET_CHANNEL = "cjjg7"
MY_BOT_USERNAME = "@TGS_SHOPSBOT"
MY_SUPPORT_USERNAME = "@Tgshopssupport"
MY_CHANNEL_LINK = "https://t.me/cjjg7"

# ==================== 3. DATABASE SETUP ====================
conn = sqlite3.connect("tgshop_reseller.db")
c = conn.cursor()
c.execute("""CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    balance REAL DEFAULT 0.0
)""")
c.execute("""CREATE TABLE IF NOT EXISTS orders (
    item_id TEXT PRIMARY KEY,
    user_id INTEGER,
    phone TEXT,
    price REAL
)""")
conn.commit()

def get_balance(user_id):
    c.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    if not row:
        c.execute("INSERT INTO users (user_id, balance) VALUES (?, 0.0)", (user_id,))
        conn.commit()
        return 0.0
    return round(row[0], 2)

def update_balance(user_id, amount):
    bal = get_balance(user_id)
    c.execute("UPDATE users SET balance=? WHERE user_id=?", (round(bal + amount, 2), user_id))
    conn.commit()

# ==================== 4. INITIALIZE CLIENTS & CACHE ====================
bot = Bot(token=BOT_TOKEN.strip())
dp = Dispatcher()
userbot = TelegramClient(StringSession(SESSION_STRING.strip()), API_ID, API_HASH)

panel_lock = asyncio.Lock()
stock_cache = {}
CACHE_TTL_SECONDS = 120

CATEGORIES = {
    "c1": ("✅ Cheap + Mail", "Cheap + Mail"),
    "c2": ("🚫 Cheap No Mail", "Cheap No Mail"),
    "c3": ("⭐📧 Good + Mail", "Good + Mail"),
    "c4": ("⭐🚫 Good No Mail", "Good No Mail"),
    "c5": ("🗑️ Use and Throw", "Use and Throw"),
}

REGIONS = {
    "r1": ("🇮🇳 India", "India"),
    "r2": ("🇺🇸 USA", "USA"),
    "r3": ("🇮🇩 Indonesia", "Indonesia"),
    "r4": ("🇲🇲 Myanmar", "Myanmar"),
    "r5": ("🇧🇩 Bangladesh", "Bangladesh"),
    "r6": ("🇻🇳 Vietnam", "Vietnam"),
    "r7": ("🌐 Global", "Global"),
}

search_state = {}
deposit_custom_state = set()
pending_deposit_amt = {}

# ==================== 5. 100% STEALTH SANITIZER & 1.5X PRICE REPLACER ====================
def format_multiplied_price(val: float) -> str:
    new_val = round(val * PROFIT_MULTIPLIER, 2)
    return str(int(new_val)) if new_val.is_integer() else str(new_val)

def multiply_prices_in_text(text: str) -> str:
    if not text:
        return ""

    def repl_prefix(match):
        symbol = match.group(1)
        val = float(match.group(2))
        return f"{symbol}{format_multiplied_price(val)}"

    text = re.sub(
        r'(₹\s*|Rs\.?\s*|INR\s*)(\d+(?:\.\d+)?)',
        repl_prefix,
        text,
        flags=re.IGNORECASE
    )

    def repl_suffix(match):
        val = float(match.group(1))
        symbol = match.group(2)
        return f"{format_multiplied_price(val)}{symbol}"

    text = re.sub(
        r'(\d+(?:\.\d+)?)(\s*₹|\s*Rs\.?|\s*INR)\b',
        repl_suffix,
        text,
        flags=re.IGNORECASE
    )
    return text

def sanitize_for_customer(text: str, multiply_price: bool = False) -> str:
    if not text:
        return ""
    if multiply_price:
        text = multiply_prices_in_text(text)

    text = re.sub(r'@?cheaptgsbot', MY_BOT_USERNAME, text, flags=re.IGNORECASE)
    text = re.sub(r'@?tgsshopprobot', MY_BOT_USERNAME, text, flags=re.IGNORECASE)
    text = re.sub(r'@?tgshopowner', MY_SUPPORT_USERNAME, text, flags=re.IGNORECASE)
    text = re.sub(r'@?tgshoplogs', MY_BOT_USERNAME, text, flags=re.IGNORECASE)
    text = re.sub(r'@[A-Za-z0-9_]{3,}', MY_BOT_USERNAME, text)
    text = re.sub(r'(https?://)?t\.me/[A-Za-z0-9_+]+', MY_CHANNEL_LINK, text)
    return text

async def copy_and_replace_message(msg_obj):
    raw_text = msg_obj.raw_text or msg_obj.text or ""
    modified_text = sanitize_for_customer(raw_text, multiply_price=True)

    if msg_obj.media:
        caption_part = modified_text[:1020] if len(modified_text) > 1020 else modified_text
        await userbot.send_file(REPLACER_TARGET_CHANNEL, msg_obj.media, caption=caption_part)
        if len(modified_text) > 1020:
            await userbot.send_message(REPLACER_TARGET_CHANNEL, modified_text[1020:])
    elif modified_text:
        await userbot.send_message(REPLACER_TARGET_CHANNEL, modified_text)

async def setup_auto_replacer():
    if not ENABLE_AUTO_REPLACER or not REPLACER_SOURCE_CHANNELS:
        return

    @userbot.on(events.NewMessage(chats=REPLACER_SOURCE_CHANNELS))
    async def replacer_handler(event):
        try:
            await copy_and_replace_message(event.message)
            print(f"✅ [LIVE REPLACER 1.5x] Auto-copied & multiplied price to {REPLACER_TARGET_CHANNEL}")
        except Exception as e:
            print(f"⚠️ [LIVE REPLACER ERROR]: {e}")

async def interval_multi_channel_forwarder():
    await asyncio.sleep(5)
    while True:
        if ENABLE_INTERVAL_FORWARDER and INTERVAL_TARGET_CHANNELS:
            try:
                msg = None
                if INTERVAL_MESSAGE_ID > 0:
                    msg = await userbot.get_messages(INTERVAL_SOURCE_CHANNEL, ids=INTERVAL_MESSAGE_ID)
                if not msg:
                    msgs = await userbot.get_messages(INTERVAL_SOURCE_CHANNEL, limit=1)
                    msg = msgs[0] if msgs else None

                if msg:
                    for target in INTERVAL_TARGET_CHANNELS:
                        try:
                            try:
                                await userbot.forward_messages(target, msg)
                            except Exception:
                                if msg.media:
                                    await userbot.send_file(target, msg.media, caption=msg.text or "")
                                else:
                                    await userbot.send_message(target, msg.text or "")
                            print(f"✅ [INTERVAL SENT] Successfully posted in -> {target}")
                            await asyncio.sleep(random.uniform(4.0, 7.0))
                        except Exception as ch_err:
                            print(f"❌ [CANNOT POST IN {target}]: {ch_err}")
            except Exception as e:
                print(f"⚠️ [INTERVAL TASK ERROR]: {e}")

        await asyncio.sleep(REPEAT_INTERVAL_MINUTES * 60)

# ==================== 6. SAFE TELEGRAM SENDER ====================
async def safe_edit_text(msg: types.Message, text: str, reply_markup=None):
    clean_txt = sanitize_for_customer(text, multiply_price=False)
    for _ in range(3):
        try:
            return await msg.edit_text(clean_txt, reply_markup=reply_markup, parse_mode=None)
        except Exception as e:
            if "message is not modified" in str(e).lower():
                return
            await asyncio.sleep(1)
    try:
        return await bot.send_message(msg.chat.id, clean_txt, reply_markup=reply_markup, parse_mode=None)
    except Exception:
        pass

# ==================== 7. QR CODE GENERATOR ====================
def generate_upi_qr_photo(amount: float = 0):
    if amount > 0:
        upi_link = f"upi://pay?pa={UPI_ID}&pn={urllib.parse.quote(MERCHANT_NAME)}&am={amount}&cu=INR"
    else:
        upi_link = f"upi://pay?pa={UPI_ID}&pn={urllib.parse.quote(MERCHANT_NAME)}&cu=INR"

    if HAS_QRCODE_LIB:
        qr = qrcode.QRCode(version=1, box_size=10, border=2)
        qr.add_data(upi_link)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        bio = BytesIO()
        img.save(bio, format="PNG")
        bio.seek(0)
        return BufferedInputFile(bio.read(), filename="upi_qr.png")
    else:
        encoded_data = urllib.parse.quote(upi_link)
        qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=400x400&margin=15&data={encoded_data}"
        return URLInputFile(qr_url, filename="upi_qr.png")

# ==================== 8. ROBUST TELETHON SHOP BRIDGE HELPERS ====================
async def human_delay(min_s=2.0, max_s=3.5):
    await asyncio.sleep(random.uniform(min_s, max_s))

async def wait_for_edit_or_reply(msg, timeout=25):
    steps = int(timeout / 1.5)
    current = msg
    for _ in range(steps):
        txt = (current.raw_text or current.text or "").lower()
        if any(w in txt for w in ["fetching", "please wait", "loading", "checking", "sending"]):
            await asyncio.sleep(1.5)
            refreshed = await userbot.get_messages(SOURCE_BOT, ids=current.id)
            if refreshed:
                current = refreshed
            latest = await userbot.get_messages(SOURCE_BOT, limit=1)
            if latest and latest[0].id > current.id:
                current = latest[0]
        else:
            break
    return current

async def click_button_by_substring(msg, substr):
    if not msg or not msg.buttons:
        return None
    for r_idx, row in enumerate(msg.buttons):
        for b_idx, btn in enumerate(row):
            if substr.lower() in btn.text.lower():
                await human_delay(1.5, 2.5)
                await msg.click(r_idx, b_idx)
                await asyncio.sleep(2.0)
                refreshed = await userbot.get_messages(SOURCE_BOT, ids=msg.id)
                latest = await userbot.get_messages(SOURCE_BOT, limit=1)
                target = latest[0] if (latest and latest[0].id > msg.id) else refreshed
                return await wait_for_edit_or_reply(target, timeout=25)
    return None

async def navigate_to_accounts(cat_key, region_name=None, custom_query=None, force_refresh=False):
    cache_key = f"{cat_key}_{region_name}_{custom_query}"

    if not force_refresh and cache_key in stock_cache:
        ts, cached_msg_id = stock_cache[cache_key]
        if time.time() - ts < CACHE_TTL_SECONDS:
            cached_msg = await userbot.get_messages(SOURCE_BOT, ids=cached_msg_id)
            if cached_msg and cached_msg.buttons:
                print(f"⚡ [CACHE HIT] Serving {cache_key} from cache!")
                return cached_msg

    async with panel_lock:
        await userbot.send_message(SOURCE_BOT, "/start")
        await human_delay(2.5, 3.5)
        latest = await userbot.get_messages(SOURCE_BOT, limit=1)
        if not latest:
            return None
        msg = latest[0]

        msg = await click_button_by_substring(msg, "Telegram Accounts")
        if not msg:
            return None

        _, cat_match = CATEGORIES[cat_key]
        msg = await click_button_by_substring(msg, cat_match)
        if not msg:
            return None

        if custom_query:
            msg = await click_button_by_substring(msg, "Search Country")
            if not msg:
                return None
            await human_delay(1.5, 2.5)
            await userbot.send_message(SOURCE_BOT, custom_query)
            await asyncio.sleep(2.5)
            latest = await userbot.get_messages(SOURCE_BOT, limit=1)
            msg = await wait_for_edit_or_reply(latest[0], timeout=25)
        else:
            msg = await click_button_by_substring(msg, region_name)

        if msg and msg.buttons:
            stock_cache[cache_key] = (time.time(), msg.id)
        return msg

# ==================== 9. SHOP BOT MENUS ====================
def get_main_menu_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="📱 Telegram Accounts", callback_data="menu_tg_acc")
    kb.button(text="💰 My Wallet", callback_data="my_wallet")
    kb.button(text="➕ Deposit", callback_data="deposit")
    kb.button(text="📦 My Orders", callback_data="my_orders")
    kb.button(text="🆘 Support", callback_data="support")
    kb.adjust(1, 2, 1, 1)
    return kb.as_markup()

def get_welcome_text(user_name, bal):
    return (
        f"Hi {user_name},\n\n"
        f"🔰 Welcome to STORE\n"
        f"Live Telegram accounts with instant delivery.\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 Your Wallet: ₹{bal}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⚡ Instant Delivery\n"
        f"🔐 Secure Payments\n\n"
        f"👇 Select an option:"
    )

@dp.message(Command("start"))
async def start_cmd(msg: types.Message):
    search_state.pop(msg.from_user.id, None)
    deposit_custom_state.discard(msg.from_user.id)
    bal = get_balance(msg.from_user.id)
    await msg.answer(
        get_welcome_text(msg.from_user.first_name, bal),
        reply_markup=get_main_menu_kb()
    )

@dp.message(Command("admin"))
async def register_admin_cmd(msg: types.Message):
    ADMIN_IDS.add(msg.from_user.id)
    await msg.reply(f"✅ Aapka ID ({msg.from_user.id}) Admin list mein jud gaya hai!")

@dp.callback_query(F.data == "back_home")
async def back_home_cb(call: types.CallbackQuery):
    search_state.pop(call.from_user.id, None)
    deposit_custom_state.discard(call.from_user.id)
    bal = get_balance(call.from_user.id)
    if call.message.photo:
        await call.message.delete()
        await call.message.answer(
            get_welcome_text(call.from_user.first_name, bal),
            reply_markup=get_main_menu_kb()
        )
    else:
        await safe_edit_text(
            call.message,
            get_welcome_text(call.from_user.first_name, bal),
            reply_markup=get_main_menu_kb()
        )

@dp.callback_query(F.data == "menu_tg_acc")
async def show_categories_menu(call: types.CallbackQuery):
    search_state.pop(call.from_user.id, None)
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Cheap + Mail", callback_data="cat_c1")
    kb.button(text="🚫 Cheap No Mail", callback_data="cat_c2")
    kb.button(text="⭐📧 Good + Mail", callback_data="cat_c3")
    kb.button(text="⭐🚫 Good No Mail", callback_data="cat_c4")
    kb.button(text="🗑️ Use and Throw", callback_data="cat_c5")
    kb.button(text="⬅️ Back", callback_data="back_home")
    kb.adjust(2, 2, 1, 1)

    await safe_edit_text(
        call.message,
        "📱 TG Accounts\n\nPrices are fetched live from the panel.\n⚠️ NO REFUNDS IN ANY CASE.",
        reply_markup=kb.as_markup()
    )

@dp.callback_query(F.data.startswith("cat_"))
async def show_regions_menu(call: types.CallbackQuery):
    cat_key = call.data.split("_")[1]
    cat_title, _ = CATEGORIES[cat_key]

    kb = InlineKeyboardBuilder()
    for r_key, (r_label, _) in REGIONS.items():
        kb.button(text=r_label, callback_data=f"reg_{cat_key}_{r_key}_0")
    kb.button(text="🔍 Search Country", callback_data=f"search_{cat_key}")
    kb.button(text="⬅️ Back", callback_data="menu_tg_acc")
    kb.adjust(2, 2, 2, 1, 1, 1)

    await safe_edit_text(
        call.message,
        f"📂 {cat_title}\n\n👇 Select a region to browse:",
        reply_markup=kb.as_markup()
    )

async def render_accounts_view(message_or_call, cat_key, r_key=None, custom_query=None, is_msg=False, force_refresh=False):
    target_msg = message_or_call if is_msg else message_or_call.message
    if is_msg:
        wait_msg = await target_msg.answer("⏳ Fetching accounts... Please wait.")
    else:
        await safe_edit_text(target_msg, "⏳ Fetching accounts... Please wait.")
        wait_msg = target_msg

    region_name = REGIONS[r_key][1] if r_key else None
    bot_msg = await navigate_to_accounts(cat_key, region_name=region_name, custom_query=custom_query, force_refresh=force_refresh)

    if not bot_msg:
        kb = InlineKeyboardBuilder()
        kb.button(text="⬅️ Back", callback_data=f"cat_{cat_key}")
        await safe_edit_text(wait_msg, "⚠️ Server busy hai ya timeout ho gaya. Try again!", reply_markup=kb.as_markup())
        return

    raw_text = bot_msg.raw_text or bot_msg.text or "Available Accounts"
    raw_text = sanitize_for_customer(raw_text, multiply_price=True)
    kb = InlineKeyboardBuilder()

    if bot_msg.buttons:
        for r_idx, row in enumerate(bot_msg.buttons):
            for b_idx, btn in enumerate(row):
                b_text = btn.text
                price_match = re.search(r"₹\s*(\d+(?:\.\d+)?)", b_text)
                if price_match:
                    base_p = float(price_match.group(1))
                    sell_p = round(base_p * PROFIT_MULTIPLIER, 1)
                    new_b_text = re.sub(r"₹\s*\d+(?:\.\d+)?", f"₹{sell_p}", b_text)
                    kb.button(
                        text=new_b_text,
                        callback_data=f"buybtn_{bot_msg.id}_{r_idx}_{b_idx}_{base_p}_{sell_p}_{cat_key}"
                    )
                elif "next" in b_text.lower() or "➡️" in b_text or ("⬅️" in b_text and "back" not in b_text.lower()):
                    kb.button(text=b_text, callback_data=f"page_{bot_msg.id}_{r_idx}_{b_idx}_{cat_key}")

    if r_key:
        kb.button(text="🔄 Refresh", callback_data=f"reg_{cat_key}_{r_key}_1")
    kb.button(text="⬅️ Back", callback_data=f"cat_{cat_key}")
    kb.adjust(1)

    await safe_edit_text(wait_msg, raw_text, reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("reg_"))
async def handle_region_click(call: types.CallbackQuery):
    parts = call.data.split("_")
    cat_key, r_key = parts[1], parts[2]
    force_ref = (len(parts) > 3 and parts[3] == "1")
    await render_accounts_view(call, cat_key, r_key=r_key, is_msg=False, force_refresh=force_ref)

@dp.callback_query(F.data.startswith("page_"))
async def handle_pagination(call: types.CallbackQuery):
    _, msg_id_str, r_idx_str, b_idx_str, cat_key = call.data.split("_")
    await call.answer("⏳ Loading next page...")
    try:
        async with panel_lock:
            msg = await userbot.get_messages(SOURCE_BOT, ids=int(msg_id_str))
            if msg and msg.buttons:
                await human_delay(1.5, 2.5)
                await msg.click(int(r_idx_str), int(b_idx_str))
                await asyncio.sleep(2.0)
                msg = await userbot.get_messages(SOURCE_BOT, ids=int(msg_id_str))
                msg = await wait_for_edit_or_reply(msg, timeout=25)

                kb = InlineKeyboardBuilder()
                for r_i, row in enumerate(msg.buttons or []):
                    for b_i, btn in enumerate(row):
                        b_text = btn.text
                        price_match = re.search(r"₹\s*(\d+(?:\.\d+)?)", b_text)
                        if price_match:
                            base_p = float(price_match.group(1))
                            sell_p = round(base_p * PROFIT_MULTIPLIER, 1)
                            new_b_text = re.sub(r"₹\s*\d+(?:\.\d+)?", f"₹{sell_p}", b_text)
                            kb.button(
                                text=new_b_text,
                                callback_data=f"buybtn_{msg.id}_{r_i}_{b_i}_{base_p}_{sell_p}_{cat_key}"
                            )
                        elif "next" in b_text.lower() or "➡️" in b_text:
                            kb.button(text=b_text, callback_data=f"page_{msg.id}_{r_i}_{b_i}_{cat_key}")
                kb.button(text="⬅️ Back", callback_data=f"cat_{cat_key}")
                kb.adjust(1)
                raw_t = sanitize_for_customer(msg.raw_text or msg.text or "", multiply_price=True)
                await safe_edit_text(call.message, raw_t, reply_markup=kb.as_markup())
    except Exception:
        await call.answer("⚠️ Page expired, please refresh.", show_alert=True)

@dp.callback_query(F.data.startswith("search_"))
async def prompt_search_country(call: types.CallbackQuery):
    cat_key = call.data.split("_")[1]
    search_state[call.from_user.id] = cat_key
    cat_title, _ = CATEGORIES[cat_key]
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Back", callback_data=f"cat_{cat_key}")
    await safe_edit_text(
        call.message,
        f"🔍 Search Country\n\nService: {cat_title}\nSend country name or code (e.g. India, in):",
        reply_markup=kb.as_markup()
    )

# ==================== 10. STEALTH AUTO BUY ACCOUNT ====================
@dp.callback_query(F.data.startswith("buybtn_"))
async def buy_specific_account(call: types.CallbackQuery):
    _, msg_id_str, r_idx_str, b_idx_str, base_str, sell_str, cat_key = call.data.split("_")
    base_price = float(base_str)
    sell_price = float(sell_str)
    user_id = call.from_user.id
    bal = get_balance(user_id)

    if bal < sell_price:
        await call.answer(f"❌ Insufficient Balance! Need ₹{sell_price} (Your Wallet: ₹{bal})", show_alert=True)
        return

    update_balance(user_id, -sell_price)
    await safe_edit_text(call.message, "⏳ Processing your order... Please wait.")

    admin_secret_error = None
    try:
        async with panel_lock:
            source_msg = await userbot.get_messages(SOURCE_BOT, ids=int(msg_id_str))
            if not source_msg or not source_msg.buttons:
                admin_secret_error = "Stock message expired."
                raise Exception("Stock page expired! Please click Refresh and try again.")

            await human_delay(1.5, 2.5)
            await source_msg.click(int(r_idx_str), int(b_idx_str))
            await asyncio.sleep(2.5)

            refreshed = await userbot.get_messages(SOURCE_BOT, ids=int(msg_id_str))
            latest = await userbot.get_messages(SOURCE_BOT, limit=1)
            purchase_msg = latest[0] if (latest and latest[0].id > int(msg_id_str)) else refreshed
            purchase_msg = await wait_for_edit_or_reply(purchase_msg, timeout=25)

            text = (purchase_msg.raw_text or purchase_msg.text or "")

            if purchase_msg.buttons:
                for r_i, row in enumerate(purchase_msg.buttons):
                    for b_i, btn in enumerate(row):
                        if any(w in btn.text.lower() for w in ["confirm", "yes", "buy now", "proceed"]):
                            await human_delay(1.2, 2.0)
                            await purchase_msg.click(r_i, b_i)
                            await asyncio.sleep(2.5)
                            latest2 = await userbot.get_messages(SOURCE_BOT, limit=1)
                            purchase_msg = await wait_for_edit_or_reply(latest2[0], timeout=25)
                            text = (purchase_msg.raw_text or purchase_msg.text or "")
                            break

        if any(w in text.lower() for w in ["need ₹", "insufficient", "low balance", "add funds", "deposit"]):
            admin_secret_error = f"URGENT: Panel (@{SOURCE_BOT}) par aapke Admin Wallet mein balance kam hai! Customer (ID: {user_id}) ₹{sell_price} ka account kharidne ki koshish kar raha hai."
            raise Exception("Server stock is currently refreshing. Please try again in a few minutes!")

        if "select a" in text.lower() and "phone" not in text.lower() and "#" not in text:
            admin_secret_error = "Account out of stock on panel."
            raise Exception("This account was just sold out! Please click Refresh and select another one.")

        item_match = re.search(r"#(\d+)", text)
        phone_match = re.search(r"(\+\d{7,15})", text)
        item_id = item_match.group(1) if item_match else str(purchase_msg.id)
        phone = phone_match.group(1) if phone_match else "See Details Above"

        c.execute("INSERT OR REPLACE INTO orders VALUES (?, ?, ?, ?)", (item_id, user_id, phone, sell_price))
        conn.commit()

        clean_text = re.sub(r"Charged:\s*₹\d+(\.\d+)?", f"Charged: ₹{sell_price}", text)
        clean_text = sanitize_for_customer(clean_text, multiply_price=False)

        kb = InlineKeyboardBuilder()
        kb.button(text="🔑 Get OTP", callback_data=f"otp_{item_id}")
        kb.button(text="🚪 Logout Session", callback_data=f"logout_{item_id}")
        kb.button(text="⬅️ Back to Store", callback_data="menu_tg_acc")
        kb.adjust(2, 1)

        await safe_edit_text(
            call.message,
            f"✅ Purchase Successful!\n\n{clean_text}\n\n📌 Step 1: Telegram mein {phone} login karein.\n📌 Step 2: Niche 🔑 Get OTP dabayein.",
            reply_markup=kb.as_markup()
        )

        profit = round(sell_price - base_price, 2)
        for adm_id in ADMIN_IDS:
            try:
                await bot.send_message(
                    adm_id,
                    f"✅ New Sale!\n📱 Phone: {phone}\n💵 Paid: ₹{sell_price}\n💰 Profit: ₹{profit}"
                )
            except Exception:
                pass

    except Exception as e:
        update_balance(user_id, sell_price)
        kb = InlineKeyboardBuilder()
        kb.button(text="⬅️ Back", callback_data=f"cat_{cat_key}")
        await safe_edit_text(
            call.message,
            f"⚠️ Order Could Not Be Completed!\nReason: {sanitize_for_customer(str(e))}\n\n💰 ₹{sell_price} has been refunded to your wallet.",
            reply_markup=kb.as_markup()
        )
        if admin_secret_error:
            for adm_id in ADMIN_IDS:
                try:
                    await bot.send_message(adm_id, f"🔔 [PRIVATE ADMIN ALERT]\n{admin_secret_error}")
                except Exception:
                    pass

# ==================== 11. OTP, WALLET & QR DEPOSIT ====================
@dp.callback_query(F.data.startswith("otp_"))
async def fetch_otp_code(call: types.CallbackQuery):
    item_id = call.data.split("_")[1]
    await call.answer("🔄 Fetching OTP...", show_alert=False)
    try:
        async with panel_lock:
            await human_delay(1.0, 2.0)
            await userbot.send_message(SOURCE_BOT, f"/otp {item_id}")
            await asyncio.sleep(2.5)
            latest = await userbot.get_messages(SOURCE_BOT, limit=1)
            otp_resp = await wait_for_edit_or_reply(latest[0], timeout=25)
            resp_text = sanitize_for_customer(otp_resp.raw_text or otp_resp.text or "")
            await call.message.reply(f"📩 OTP Status (#{item_id}):\n\n{resp_text}", parse_mode=None)
    except Exception:
        await call.message.reply("⏳ Abhi OTP nahi aaya hai. 5 second baad firse try karein.")

@dp.callback_query(F.data.startswith("logout_"))
async def logout_session_cb(call: types.CallbackQuery):
    item_id = call.data.split("_")[1]
    await call.answer("🔄 Logging out...", show_alert=False)
    try:
        async with panel_lock:
            await human_delay(1.0, 2.0)
            await userbot.send_message(SOURCE_BOT, f"/logout {item_id}")
            await asyncio.sleep(2.5)
            latest = await userbot.get_messages(SOURCE_BOT, limit=1)
            resp = await wait_for_edit_or_reply(latest[0], timeout=25)
            resp_text = sanitize_for_customer(resp.raw_text or resp.text or "")
            await call.message.reply(f"🚪 Session Status (#{item_id}):\n\n{resp_text}", parse_mode=None)
    except Exception:
        await call.message.reply("⚠️ Logout failed.")

@dp.callback_query(F.data == "my_orders")
async def my_orders_cb(call: types.CallbackQuery):
    c.execute("SELECT item_id, phone, price FROM orders WHERE user_id=? ORDER BY rowid DESC LIMIT 10", (call.from_user.id,))
    rows = c.fetchall()
    kb = InlineKeyboardBuilder()
    if not rows:
        text = "📦 My Orders\n\nYou haven't purchased any accounts yet."
    else:
        text = "📦 Your Recent Orders:\n\n"
        for item_id, phone, price in rows:
            text += f"• #{item_id} — {phone} (₹{price})\n"
            kb.button(text=f"🔑 OTP #{item_id}", callback_data=f"otp_{item_id}")
    kb.button(text="⬅️ Back", callback_data="back_home")
    kb.adjust(1)
    await safe_edit_text(call.message, text, reply_markup=kb.as_markup())

@dp.callback_query(F.data == "my_wallet")
async def my_wallet_cb(call: types.CallbackQuery):
    bal = get_balance(call.from_user.id)
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Deposit Funds", callback_data="deposit")
    kb.button(text="⬅️ Back", callback_data="back_home")
    kb.adjust(1)
    await safe_edit_text(
        call.message,
        f"💰 My Wallet\n\n🆔 User ID: {call.from_user.id}\n💵 Balance: ₹{bal}",
        reply_markup=kb.as_markup()
    )

async def send_qr_screen(target_msg, user_id: int, amount: float, is_callback=True):
    pending_deposit_amt[user_id] = amount
    qr_file = generate_upi_qr_photo(amount)

    amt_text = f"₹{amount}" if amount > 0 else "Any Amount"
    caption = (
        f"🏧 UPI QR Code Deposit\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💵 Selected Amount: {amt_text}\n"
        f"📌 UPI ID: {UPI_ID}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"1️⃣ Scan QR Code using GPay, PhonePe, Paytm.\n"
        f"2️⃣ Send Payment Screenshot here in chat!\n"
        f"3️⃣ Admin will approve instantly."
    )

    kb = InlineKeyboardBuilder()
    kb.button(text="₹50 QR", callback_data="qramt_50")
    kb.button(text="₹100 QR", callback_data="qramt_100")
    kb.button(text="₹200 QR", callback_data="qramt_200")
    kb.button(text="₹500 QR", callback_data="qramt_500")
    kb.button(text="✏️ Custom Amount", callback_data="qramt_custom")
    kb.button(text="⬅️ Back to Menu", callback_data="back_home")
    kb.adjust(2, 2, 1, 1)

    if is_callback:
        try:
            await target_msg.delete()
        except Exception:
            pass
    await bot.send_photo(
        chat_id=user_id,
        photo=qr_file,
        caption=caption,
        reply_markup=kb.as_markup()
    )

@dp.callback_query(F.data == "deposit")
async def deposit_funds(call: types.CallbackQuery):
    await call.answer("⏳ Generating QR...")
    await send_qr_screen(call.message, call.from_user.id, amount=100, is_callback=True)

@dp.callback_query(F.data.startswith("qramt_"))
async def change_qr_amount(call: types.CallbackQuery):
    val = call.data.split("_")[1]
    if val == "custom":
        deposit_custom_state.add(call.from_user.id)
        kb = InlineKeyboardBuilder()
        kb.button(text="⬅️ Back", callback_data="deposit")
        if call.message.photo:
            await call.message.delete()
            await call.message.answer("✏️ Enter Custom Amount: Type amount (e.g. 39, 150):", reply_markup=kb.as_markup())
        else:
            await safe_edit_text(call.message, "✏️ Enter Custom Amount: Type amount (e.g. 39, 150):", reply_markup=kb.as_markup())
        return

    amount = float(val)
    await call.answer(f"🔄 Generating ₹{amount} QR...")
    await send_qr_screen(call.message, call.from_user.id, amount=amount, is_callback=True)

@dp.message(F.text & ~F.text.startswith("/"))
async def handle_text_inputs(msg: types.Message):
    user_id = msg.from_user.id
    if user_id in deposit_custom_state:
        deposit_custom_state.discard(user_id)
        try:
            amt = float(msg.text.strip())
            if amt <= 0:
                raise ValueError()
            await send_qr_screen(msg, user_id, amount=amt, is_callback=False)
        except ValueError:
            await msg.reply("❌ Valid number daalein (Jaise: 39 ya 100).")
        return

    if user_id in search_state:
        cat_key = search_state.pop(user_id)
        query = msg.text.strip()
        await render_accounts_view(msg, cat_key, custom_query=query, is_msg=True)

@dp.callback_query(F.data == "support")
async def support_cb(call: types.CallbackQuery):
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Back", callback_data="back_home")
    await safe_edit_text(call.message, f"🆘 Support: {SUPPORT_USERNAME}", reply_markup=kb.as_markup())

# ==================== 12. ADMIN SCREENSHOT APPROVAL HANDLER ====================
@dp.message(F.photo | F.document)
async def handle_payment_screenshot(msg: types.Message):
    user_id = msg.from_user.id
    req_amt = pending_deposit_amt.get(user_id, 100.0)

    await msg.reply(f"✅ Screenshot submitted! Expected: ₹{req_amt}. Waiting for admin approval...")

    kb = InlineKeyboardBuilder()
    kb.button(text=f"✅ Approve ₹{req_amt}", callback_data=f"admdep_ok_{user_id}_{req_amt}")
    kb.button(text="✅ Approve ₹50", callback_data=f"admdep_ok_{user_id}_50")
    kb.button(text="✅ Approve ₹100", callback_data=f"admdep_ok_{user_id}_100")
    kb.button(text="❌ Reject", callback_data=f"admdep_no_{user_id}_0")
    kb.adjust(1, 2, 1)

    user_name = msg.from_user.full_name or "Customer"
    user_handle = f"@{msg.from_user.username}" if msg.from_user.username else "No Username"

    caption_text = (
        f"💰 NEW DEPOSIT SCREENSHOT!\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👤 Name: {user_name} ({user_handle})\n"
        f"🆔 User ID: {user_id}\n"
        f"💵 Expected Amount: ₹{req_amt}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👇 Click below to Approve or Reject:"
    )

    for adm_id in list(ADMIN_IDS):
        try:
            await bot.copy_message(
                chat_id=adm_id,
                from_chat_id=msg.chat.id,
                message_id=msg.message_id,
                caption=caption_text,
                reply_markup=kb.as_markup(),
                parse_mode=None
            )
        except Exception:
            try:
                await bot.send_message(chat_id=adm_id, text=caption_text, reply_markup=kb.as_markup(), parse_mode=None)
            except Exception:
                pass

@dp.callback_query(F.data.startswith("admdep_"))
async def admin_approve_reject_cb(call: types.CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("❌ Only Admin can approve!", show_alert=True)
        return

    parts = call.data.split("_")
    action = parts[1]
    uid = int(parts[2])
    amt = float(parts[3])

    if action == "ok":
        update_balance(uid, amt)
        new_bal = get_balance(uid)
        old_text = call.message.caption or call.message.text or ""
        new_status = f"{old_text}\n\n✅ APPROVED ₹{amt} (New Wallet Balance: ₹{new_bal})"
        try:
            if call.message.caption is not None:
                await call.message.edit_caption(caption=new_status, parse_mode=None)
            else:
                await call.message.edit_text(text=new_status, parse_mode=None)
        except Exception:
            pass

        await bot.send_message(uid, f"🎉 Deposit Approved!\n💵 Added: ₹{amt}\n💰 New Wallet Balance: ₹{new_bal}")
        await call.answer(f"✅ Approved ₹{amt}!")
    else:
        old_text = call.message.caption or call.message.text or ""
        new_status = f"{old_text}\n\n❌ REJECTED BY ADMIN"
        try:
            if call.message.caption is not None:
                await call.message.edit_caption(caption=new_status, parse_mode=None)
            else:
                await call.message.edit_text(text=new_status, parse_mode=None)
        except Exception:
            pass

        await bot.send_message(uid, "❌ Your payment screenshot was rejected by Admin.")
        await call.answer("❌ Rejected!")

@dp.message(Command("addbal"))
async def admin_add_balance(msg: types.Message):
    if msg.from_user.id not in ADMIN_IDS:
        return
    try:
        _, uid, amt = msg.text.split()
        update_balance(int(uid), float(amt))
        new_bal = get_balance(int(uid))
        await msg.reply(f"✅ Added ₹{amt} to {uid}! (New Balance: ₹{new_bal})")
        await bot.send_message(int(uid), f"✅ Deposit Approved!\nAdded: ₹{amt}\nNew Wallet Balance: ₹{new_bal}")
    except Exception:
        await msg.reply("❌ Usage: /addbal USER_ID AMOUNT")

# ==================== 13. RENDER 24/7 KEEP-ALIVE & ANTI-HIJACK GUARD ====================
async def health_check(request):
    return web.Response(text="✅ TG Shop Store is Active 24/7!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"🌐 Render Web Server bound to port {port}")

async def keep_render_awake_and_guard():
    await asyncio.sleep(15)
    render_url = os.environ.get("RENDER_EXTERNAL_URL")
    port = int(os.environ.get("PORT", 10000))
    target_url = render_url if render_url else f"http://127.0.0.1:{port}/"

    async with aiohttp.ClientSession() as session:
        while True:
            try:
                async with session.get(target_url, timeout=10) as resp:
                    print(f"💓 [KEEP-ALIVE PING] {target_url} -> Status {resp.status}")
                wh = await bot.get_webhook_info()
                if wh.url:
                    print(f"⚠️ Removing unauthorized webhook: {wh.url}")
                    await bot.delete_webhook(drop_pending_updates=False)
            except Exception as e:
                print(f"⚠️ [KEEP-ALIVE PING ERROR]: {e}")
            await asyncio.sleep(180)

async def main():
    await start_web_server()
    asyncio.create_task(keep_render_awake_and_guard())

    print("⏳ Connecting Telethon UserBot via StringSession...")
    await userbot.connect()
    if not await userbot.is_user_authorized():
        raise RuntimeError("❌ SESSION_STRING invalid or expired!")

    ub_me = await userbot.get_me()
    ADMIN_IDS.add(ub_me.id)
    print(f"✅ Telethon Connected as: {ub_me.first_name} (ID: {ub_me.id})")

    await setup_auto_replacer()
    asyncio.create_task(interval_multi_channel_forwarder())
    print("✅ Auto-Replacer (1.5x -> @cjjg7) & Interval Forwarder Active!")

    await bot.delete_webhook(drop_pending_updates=True)
    bot_me = await bot.get_me()
    print(f"🚀 Shop Bot @{bot_me.username} is LIVE 24/7 on Render!")
    await dp.start_polling(bot, handle_signals=False)

if __name__ == "__main__":
    asyncio.run(main())
