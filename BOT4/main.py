import os
import random
import asyncio
import logging
import pytz
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from motor.motor_asyncio import AsyncIOMotorClient
from aiohttp import web
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
    ConversationHandler,
    Application
)

# ================= LOGGING SETUP =================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ================= CONFIGURATION =================
BOT4_TOKEN = os.getenv("BOT4_TOKEN", "")
MONGO_URI = os.getenv("MONGO_URI", "")
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "0"))
PORT = int(os.getenv("PORT", "8080"))

ADMIN_IDS = [5298223577, 2120581499]
FSUB_CHANNEL_IDS = [-1002114224580, -1003627956964, -1003680807119, -1002440964326, -1003541438177]

WELCOME_IMAGE = "https://raw.githubusercontent.com/DevXShiva/Save-Restricted-Bot/refs/heads/main/logo.png"
DEV_CREDITS = "\n\n\n\n👨‍💻 *Developed by:* [VoidXdevs](https://t.me/devXvoid)"

# ================= MONGODB SETUP =================
# Optimized connection pool
client = AsyncIOMotorClient(MONGO_URI, maxPoolSize=50, minPoolSize=10)
db = client.shein_coupon_bot

users_collection = db.users
coupons_collection = db.coupons
backup_logs_collection = db.backup_logs

# Indexes for speed
async def create_indexes():
    await coupons_collection.create_index([("category", 1), ("status", 1)])
    await coupons_collection.create_index("code", unique=True)
    await users_collection.create_index("user_id", unique=True)

user_captcha = {}
pending_referrals = {}
processing_users = set() # Set is faster for lookups
link_cache = {}

def get_ist_time():
    IST = pytz.timezone('Asia/Kolkata')
    return datetime.now(IST).strftime("%Y-%m-%d %I:%M:%S %p")

# ================= MONGODB FUNCTIONS =================
async def get_user_data(user_id: int):
    return await users_collection.find_one({"user_id": user_id})

async def update_user_balance(user_id: int, amount: int):
    await users_collection.update_one(
        {"user_id": user_id},
        {"$inc": {"balance": amount}},
        upsert=True
    )

async def register_user_mongo(user_id: int, first_name: str, referrer_id: Optional[int] = None):
    existing_user = await users_collection.count_documents({"user_id": user_id}, limit=1)
    if not existing_user:
        user_data = {
            "user_id": user_id,
            "first_name": first_name,
            "balance": 0,
            "referrer_id": referrer_id,
            "joined_date": datetime.now().strftime("%Y-%m-%d"),
            "created_at": datetime.now()
        }
        await users_collection.insert_one(user_data)
        return True
    return False

async def get_stock_count(category: str):
    # Faster than aggregate for simple counts
    return await coupons_collection.count_documents({"category": category, "status": "unused"})

async def add_coupons_mongo(category: str, codes_list: List[str]):
    new_coupons = []
    for code in codes_list:
        if code:
            new_coupons.append({
                "category": category,
                "code": code,
                "status": "unused",
                "used_by": None,
                "used_at": None,
                "created_at": datetime.now()
            })
    
    if not new_coupons: return 0
    
    try:
        # bulk insert ignoring duplicates
        result = await coupons_collection.insert_many(new_coupons, ordered=False)
        return len(result.inserted_ids)
    except Exception:
        # If some exist, we just return what we could insert or 0
        return 0

async def redeem_coupon_mongo(category: str, user_id: int, cost: int):
    coupon = await coupons_collection.find_one_and_update(
        {"category": category, "status": "unused"},
        {"$set": {"status": "used", "used_by": user_id, "used_at": datetime.now()}},
        sort=[("created_at", 1)]
    )
    
    if coupon:
        await users_collection.update_one(
            {"user_id": user_id},
            {"$inc": {"balance": -cost}}
        )
        return coupon["code"]
    return None

# ================= HELPER FUNCTIONS =================
async def is_joined(user_id: int, app: Application):
    if user_id in ADMIN_IDS: return True
    
    async def check_single(chat_id):
        try:
            member = await app.bot.get_chat_member(chat_id, user_id)
            return member.status in ['creator', 'administrator', 'member']
        except: return False

    # Check all channels in parallel (Much Faster)
    results = await asyncio.gather(*(check_single(cid) for cid in FSUB_CHANNEL_IDS))
    return all(results)

async def get_channel_invite_link(chat_id: int, app: Application):
    if chat_id in link_cache: return link_cache[chat_id]
    try:
        chat = await app.bot.get_chat(chat_id)
        link = chat.invite_link or await app.bot.export_chat_invite_link(chat_id)
        link_cache[chat_id] = link
        return link
    except:
        return f"https://t.me/c/{str(chat_id)[4:]}"

async def send_log(log_type: str, user_id: int, first_name: str, app: Application, details: str = ""):
    try:
        user_link = f"[{first_name}](tg://user?id={user_id})"
        bot_obj = await app.bot.get_me()
        msg = f"#{log_type} Log\n👤: {user_link}\n🆔: `{user_id}`\n{details}\n🕒: {get_ist_time()}\n🤖: @{bot_obj.username}"
        await app.bot.send_message(LOG_CHANNEL_ID, msg, parse_mode="Markdown")
    except: pass

# ================= COMMAND HANDLERS =================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not await is_joined(user_id, context.application):
        keyboard = []
        # Parallel link fetching
        links = await asyncio.gather(*(get_channel_invite_link(cid, context.application) for cid in FSUB_CHANNEL_IDS))
        for i, link in enumerate(links, 1):
            keyboard.append([InlineKeyboardButton(f"📢 Join Channel {i}", url=link)])
        
        keyboard.append([InlineKeyboardButton("✅ I've Joined All", callback_data="check_join")])
        await update.message.reply_text(
            "⚠️ **Action Required**\n\nTo use this bot, you must join all our channels.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return

    user_data = await get_user_data(user_id)
    if user_data:
        keyboard = [["🔗 My Link", "💎 Balance"], ["💸 Withdraw", "🎟 Coupon Stock"]]
        await update.message.reply_text("👇 Select option", reply_markup={"keyboard": keyboard, "resize_keyboard": True})
        return

    if context.args:
        referrer = context.args[0]
        if referrer.isdigit() and int(referrer) != user_id:
            pending_referrals[user_id] = int(referrer)

    n1, n2 = random.randint(1, 9), random.randint(1, 9)
    user_captcha[user_id] = n1 + n2
    await update.message.reply_text(f"🔒 *CAPTCHA*\n{n1} + {n2} = ??\n\nSend answer to verify.", parse_mode="Markdown")

async def check_join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if await is_joined(query.from_user.id, context.application):
        await query.message.delete()
        await start_command(update, context)
    else:
        await query.answer("❌ You haven't joined all channels!", show_alert=True)

async def handle_captcha(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_captcha: return
    
    try:
        if int(update.message.text) == user_captcha[user_id]:
            del user_captcha[user_id]
            ref_id = pending_referrals.pop(user_id, None)
            is_new = await register_user_mongo(user_id, update.effective_user.first_name, ref_id)
            
            if is_new:
                await send_log("NewUser", user_id, update.effective_user.first_name, context.application)
                if ref_id:
                    await update_user_balance(ref_id, 1)
                    try: await context.bot.send_message(ref_id, "🎉 New Referral! +1 💎")
                    except: pass
            
            keyboard = [["🔗 My Link", "💎 Balance"], ["💸 Withdraw", "🎟 Coupon Stock"]]
            await update.message.reply_photo(
                photo=WELCOME_IMAGE,
                caption=f"👋 Welcome to SHEIN Bot!{DEV_CREDITS}",
                parse_mode="Markdown",
                reply_markup={"keyboard": keyboard, "resize_keyboard": True}
            )
        else:
            await update.message.reply_text("❌ Wrong answer.")
    except: pass

async def handle_my_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot = await context.bot.get_me()
    link = f"https://t.me/{bot.username}?start={update.effective_user.id}"
    await update.message.reply_text(
        f"🔗 *Your Referral Link*\n`{link}`\n\nGet 1 💎 per referral.{DEV_CREDITS}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📤 Share", url=f"https://t.me/share/url?url={link}")]])
    )

async def handle_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = await get_user_data(update.effective_user.id)
    await update.message.reply_text(f"💎 *Balance*: {data['balance'] if data else 0}.0 💎", parse_mode="Markdown")

async def handle_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Fetch all counts in parallel
    s5, s10, s20, s40 = await asyncio.gather(
        get_stock_count("500"), get_stock_count("1000"),
        get_stock_count("2000"), get_stock_count("4000")
    )
    await update.message.reply_text(f"🎟 *Stock*\n500: {s5}\n1000: {s10}\n2000: {s20}\n4000: {s40}", parse_mode="Markdown")

async def handle_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = await get_user_data(update.effective_user.id)
    bal = data["balance"] if data else 0
    kb = [
        [InlineKeyboardButton("1💎 500🎟", callback_data="redeem_500_1"), InlineKeyboardButton("4💎 1000🎟", callback_data="redeem_1000_4")],
        [InlineKeyboardButton("15💎 2000🎟", callback_data="redeem_2000_15"), InlineKeyboardButton("25💎 4000🎟", callback_data="redeem_4000_25")]
    ]
    await update.message.reply_text(f"💸 *Withdraw*\nBalance: {bal} 💎", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def handle_redeem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    
    if user_id in processing_users:
        return await query.answer("⏳ Wait...", show_alert=True)
    
    processing_users.add(user_id)
    try:
        _, cat, cost = query.data.split("_")
        cost = int(cost)
        
        user_data = await get_user_data(user_id)
        if not user_data or user_data["balance"] < cost:
            return await query.answer("❌ No Diamonds!", show_alert=True)
            
        code = await redeem_coupon_mongo(cat, user_id, cost)
        if code:
            await query.message.reply_text(f"✅ *Redeemed!*\nCategory: {cat}\nCode: `{code}`{DEV_CREDITS}", parse_mode="Markdown")
            await send_log("Withdraw", user_id, query.from_user.first_name, context.application, f"🎟 {cat} Coupon")
        else:
            await query.answer("⚠️ Out of Stock!", show_alert=True)
    finally:
        processing_users.discard(user_id)

# ================= ADMIN HANDLERS =================
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    kb = [
        [InlineKeyboardButton("➕ 500", callback_data="admin_add_500"), InlineKeyboardButton("➕ 1000", callback_data="admin_add_1000")],
        [InlineKeyboardButton("📊 Stats", callback_data="admin_stats")]
    ]
    await update.message.reply_text("👨‍💻 Admin Panel", reply_markup=InlineKeyboardMarkup(kb))

async def admin_add_coupons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    cat = query.data.split("_")[2]
    context.user_data["admin_category"] = cat
    await query.message.reply_text(f"Send codes for {cat}:")
    return "WAITING_CODES"

async def admin_receive_codes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cat = context.user_data.get("admin_category")
    codes = update.message.text.replace('\n', ' ').split()
    added = await add_coupons_mongo(cat, codes)
    await update.message.reply_text(f"✅ Added {added} coupons to {cat}.")
    return ConversationHandler.END

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u_cnt = await users_collection.count_documents({})
    c_cnt = await coupons_collection.count_documents({})
    await update.callback_query.message.reply_text(f"📊 Stats\nUsers: {u_cnt}\nCoupons: {c_cnt}")

# ================= SERVER & INIT =================
async def web_start():
    app = web.Application()
    app.router.add_get('/', lambda r: web.Response(text="Bot Alive"))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', PORT).start()

async def post_init(app: Application):
    await create_indexes()
    await web_start()
    bot = await app.bot.get_me()
    await app.bot.send_message(LOG_CHANNEL_ID, f"🟢 Bot Online: @{bot.username}")

async def start_bot4():
    app = ApplicationBuilder().token(BOT4_TOKEN).post_init(post_init).build()
    
    admin_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_add_coupons, pattern="^admin_add_")],
        states={"WAITING_CODES": [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_receive_codes)]},
        fallbacks=[CommandHandler("cancel", lambda u,c: ConversationHandler.END)]
    )
    
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CallbackQueryHandler(check_join_callback, pattern="^check_join$"))
    app.add_handler(CallbackQueryHandler(handle_redeem, pattern="^redeem_"))
    app.add_handler(CallbackQueryHandler(admin_stats, pattern="^admin_stats$"))
    app.add_handler(admin_conv)
    
    app.add_handler(MessageHandler(filters.Regex("^🔗 My Link$"), handle_my_link))
    app.add_handler(MessageHandler(filters.Regex("^💎 Balance$"), handle_balance))
    app.add_handler(MessageHandler(filters.Regex("^🎟 Coupon Stock$"), handle_stock))
    app.add_handler(MessageHandler(filters.Regex("^💸 Withdraw$"), handle_withdraw))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_captcha))

    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    await asyncio.Event().wait()
    
    # ================= EXPORT FOR RUNNER =================
    __all__ = ['start_bot4']
