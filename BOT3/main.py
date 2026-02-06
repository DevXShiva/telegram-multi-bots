import os

import json

import random

import asyncio

import uuid

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup

from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes

from telegram.constants import ParseMode

# ================= CONFIGURATION =================

BOT3_TOKEN = os.getenv("BOT3_TOKEN", "YOUR_BOT3_TOKEN_HERE")

DIVIDER = "✨━━━━━━━━━━━━━━━━━━✨"

STADIUM_EMOJI = "🏟️"

FOOTER = "\n\n───\n🌟 **Powered by [𝐒𝐇𝐈𝐕𝐀 𝐂𝐇𝐀𝐔𝐃𝐇𝐀𝐑𝐘](https://t.me/theprofessorreport_bot)**"

STATS_FILE = "stats.json"



matches_cache = {}



# ================= HELPERS =================

def get_commentary(runs, is_wicket):

    if is_wicket:

        return random.choice(["☝️ BIG WICKET! Finger goes up!", "🎯 CLEAN BOWLED! Stumps in the air!", "😲 What a catch! Incredible!"])

    if runs == 6:

        return random.choice(["🚀 OVER THE ROOF! Huge Six!", "🔥 Absolute Fire! 100 meters plus!", "🏏 Pure Timing! That's a maximum!"])

    if runs == 4:

        return random.choice(["⚡ Bullet Shot! Boundary!", "🏏 Cracking Four! Fielders had no chance.", "💎 Pure Class! Four runs!"])

    if runs == 0:

        return random.choice(["🛑 Dot ball! High pressure.", "👀 Beats the bat! Great delivery."])

    return random.choice([f"🏃 Fast running! {runs} runs.", f"🏏 Tucked away for {runs}."])



def get_num_kb(cid):

    return InlineKeyboardMarkup([

        [InlineKeyboardButton("1️⃣", callback_data=f"n1_{cid}"), InlineKeyboardButton("2️⃣", callback_data=f"n2_{cid}"), InlineKeyboardButton("3️⃣", callback_data=f"n3_{cid}")],

        [InlineKeyboardButton("4️⃣", callback_data=f"n4_{cid}"), InlineKeyboardButton("5️⃣", callback_data=f"n5_{cid}"), InlineKeyboardButton("6️⃣", callback_data=f"n6_{cid}")],

        [InlineKeyboardButton("🏳️ SURRENDER", callback_data=f"surrender_{cid}")]

    ])



# ================= COMMANDS =================



async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    intro = (f"{STADIUM_EMOJI} **APEX CRICKET WORLD**\n{DIVIDER}\n\n"

             f"Welcome to the most realistic Hand-Cricket bot!\n\n"

             f"🏆 **Format:** 1 Over | 2 Wickets Max")

    kb = InlineKeyboardMarkup([

        [InlineKeyboardButton("🤖 VS CPU", callback_data=f"mode_cpu_{update.effective_chat.id}"),

         InlineKeyboardButton("👥 VS FRIEND", callback_data=f"mode_duel_{update.effective_chat.id}")]

    ])

    await update.message.reply_text(intro + FOOTER, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)



async def cancel_match(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not context.args:

        await update.message.reply_text("❌ **Usage:** `/cancel MATCH_ID` (Example: `/cancel A1B2C3`)")

        return

    

    m_id = context.args[0].upper()

    chat_id = str(update.effective_chat.id)

    

    if chat_id in matches_cache and matches_cache[chat_id].get("match_id") == m_id:

        del matches_cache[chat_id]

        await update.message.reply_text(f"🛑 **Match `{m_id}` has been cancelled successfully!**\nYou can now start a new one.")

    else:

        await update.message.reply_text("⚠️ **Invalid Match ID!** No active match found with this ID in this group.")



# ================= CORE ENGINE =================



async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query

    user = update.effective_user

    uid, data = str(user.id), query.data.split('_')

    action, chat_id = data[0], data[-1]



    m = matches_cache.get(chat_id)



    # Spectator Guard

    if action.startswith('n') or action in ["tb", "tw", "th", "tt", "surrender"]:

        if m and uid not in m["players"]:

            await query.answer("🚫 OOPS! You are just a Spectator. You can't play this match!", show_alert=True)

            return



    # Initial Mode Setup

    if action == "mode":

        match_id = str(uuid.uuid4())[:6].upper()

        matches_cache[chat_id] = {

            "match_id": match_id, "players": [uid] if data[1]=="duel" else [uid, "cpu"],

            "names": {uid: user.first_name, "cpu": "APEX AI 🤖"},

            "score": 0, "wickets": 0, "overs": 0, "balls": 0, "choices": {},

            "state": "toss", "cpu_mode": data[1]=="cpu", "total_overs": 1, "max_wickets": 2, "history": []

        }

        

        txt = f"{STADIUM_EMOJI} **MATCH ID: `{match_id}`**\n{DIVIDER}\n"

        if data[1] == "cpu":

            m = matches_cache[chat_id]

            m["toss_caller"] = uid

            await query.edit_message_text(f"{txt}🪙 **TOSS TIME**\n\n{user.first_name}, call Heads or Tails:", 

                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🌕 HEADS", callback_data=f"th_{chat_id}"), InlineKeyboardButton("🌑 TAILS", callback_data=f"tt_{chat_id}")]]) , parse_mode=ParseMode.MARKDOWN)

        else:

            await query.edit_message_text(f"{txt}👥 **WAITING FOR OPPONENT...**\n\nAsk your friend to join the battle!", 

                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏏 JOIN MATCH", callback_data=f"j_{chat_id}")]]) , parse_mode=ParseMode.MARKDOWN)

        return



    if not m: return



    # Join logic

    if action == "j" and uid not in m["players"]:

        m["players"].append(uid)

        m["names"][uid] = user.first_name

        m["toss_caller"] = random.choice(m["players"])

        await query.edit_message_text(f"🪙 **TOSS CALL**\n\nHey {m['names'][m['toss_caller']]}, it's your turn to call!", 

            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🌕 HEADS", callback_data=f"th_{chat_id}"), InlineKeyboardButton("🌑 TAILS", callback_data=f"tt_{chat_id}")]]) , parse_mode=ParseMode.MARKDOWN)

        return



    # Toss Result

    if action in ["th", "tt"] and uid == m["toss_caller"]:

        m["toss_winner"] = uid if (m["cpu_mode"] or random.choice([0,1])==1) else [p for p in m["players"] if p != uid][0]

        await query.edit_message_text(f"🎊 **{m['names'][m['toss_winner']]}** won the toss!\nChoose your strategy:", 

            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏏 BAT", callback_data=f"tb_{chat_id}"), InlineKeyboardButton("🎯 BOWL", callback_data=f"tw_{chat_id}")]]) , parse_mode=ParseMode.MARKDOWN)

        return



    # Strategy Selection

    if action in ["tb", "tw"] and uid == m["toss_winner"]:

        p1, p2 = m["players"][0], m["players"][1]

        if action == "tb": m["bat_f"], m["bowl_f"] = uid, (p2 if uid==p1 else p1)

        else: m["bowl_f"], m["bat_f"] = uid, (p2 if uid==p1 else p1)

        m.update({"current_batsman": m["bat_f"], "current_bowler": m["bowl_f"], "state": "inning1"})

        await update_scorecard(query, m, chat_id)

        return



    # Gameplay Logic

    if action.startswith('n'):

        if uid in m["choices"]:

            await query.answer("Wait for the other player! ⏳", show_alert=False)

            return

        

        m["choices"][uid] = int(action[1])

        if m["cpu_mode"]: m["choices"]["cpu"] = random.randint(1,6)

        

        if len(m["choices"]) == 2:

            await resolve_ball(query, m, chat_id)

        else:

            other_p = [p for p in [m["current_batsman"], m["current_bowler"]] if p != uid][0]

            await update_scorecard(query, m, chat_id, waiting_for=m["names"][other_p])

        await query.answer()



async def resolve_ball(query, m, cid):

    b_id, bo_id = m["current_batsman"], m["current_bowler"]

    b1, b2 = m["choices"][b_id], m["choices"][bo_id]

    m["choices"] = {}

    

    await query.edit_message_text(f"🏏 **{m['names'][b_id]}** is ready...\n🎯 **{m['names'][bo_id]}** runs in...\n\n⚡ *THE BALL IS IN THE AIR...*", parse_mode=ParseMode.MARKDOWN)

    await asyncio.sleep(1.2)



    is_wicket = (b1 == b2)

    comm = get_commentary(b1, is_wicket)

    

    if is_wicket:

        m["wickets"] += 1

        m["history"].append("🔴")

        res = f"☝️ **OUT! ( {b1} vs {b2} )**"

    else:

        m["score"] += b1

        m["history"].append(f"`{b1}`")

        res = f"✨ **{b1} RUNS! ( {b1} vs {b2} )**"



    m["balls"] += 1

    if m["balls"] == 6: m["overs"] += 1; m["balls"] = 0



    if (m["state"] == "inning2" and m["score"] >= m["target"]):

        await end_match(query, m, cid, b_id, "CHASE COMPLETED! 🏆")

    elif (m["wickets"] >= m["max_wickets"] or m["overs"] >= 1):

        if m["state"] == "inning1":

            m["target"] = m["score"] + 1

            m.update({"state": "inning2", "current_batsman": m["bowl_f"], "current_bowler": m["bat_f"], "score": 0, "wickets": 0, "overs": 0, "balls": 0, "history": []})

            await query.edit_message_text(f"🏁 **INNING OVER!**\n{DIVIDER}\n🎯 Target: **{m['target']}**\n\nGet ready for the chase!", reply_markup=get_num_kb(cid), parse_mode=ParseMode.MARKDOWN)

        else:

            await end_match(query, m, cid, bo_id, "TARGET DEFENDED! 🔥")

    else:

        await update_scorecard(query, m, cid, last_ball=res, comm=comm)



async def update_scorecard(query, m, cid, last_ball=None, comm=None, waiting_for=None):

    bat, bowl = m["current_batsman"], m["current_bowler"]

    hist_str = " ".join(m["history"]) if m["history"] else "---"

    

    status = (f"🏟️ **APEX ARENA** | ID: `{m['match_id']}`\n"

              f"{DIVIDER}\n")

    if last_ball: status += f"{last_ball}\n"

    if comm: status += f"🎤 _{comm}_\n\n"

    

    status += (f"🏏 **BAT:** {m['names'][bat]}\n"

               f"🎯 **BOWL:** {m['names'][bowl]}\n\n"

               f"📊 **SCORE: {m['score']}/{m['wickets']}**\n"

               f"⏳ **OVERS: {m['overs']}.{m['balls']} / 1.0**\n"

               f"📝 **BALLS:** [ {hist_str} ]\n")

    

    if m["state"] == "inning2":

        status += f"🚩 **NEED {m['target'] - m['score']} FROM {6-(m['overs']*6+m['balls'])} BALLS**\n"

    if waiting_for:

        status += f"\n⏳ _Waiting for {waiting_for}..._"



    await query.edit_message_text(status + FOOTER, reply_markup=get_num_kb(cid), parse_mode=ParseMode.MARKDOWN)



async def end_match(query, m, cid, winner, reason):

    status = (f"🏆 **MATCH FINISHED**\n{DIVIDER}\n"

              f"👑 **WINNER:** {m['names'][winner]}\n"

              f"📝 **REASON:** {reason}\n\n"

              f"Final Score: {m['score']}/{m['wickets']}")

    await query.edit_message_text(status + FOOTER, parse_mode=ParseMode.MARKDOWN)

    matches_cache.pop(str(cid), None)

async def start_bot3():
    app = ApplicationBuilder().token(BOT3_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("cricket", start_command))
    app.add_handler(CommandHandler("cancel", cancel_match))
    app.add_handler(CallbackQueryHandler(handle_callback))
    print("✅ PRO BOT ONLINE")
    
    await app.bot.initialize()
    await app.initialize()
    await app.start()
    await app.updater.start_polling()

