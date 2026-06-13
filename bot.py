"""
bot.py
Telegram front-end for SIP Saathi. Run locally with: python3 bot.py
Requires TELEGRAM_BOT_TOKEN and ANTHROPIC_API_KEY in the environment / .env.
"""
import os
import asyncio
import logging
from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

load_dotenv()

import db
import agent

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("sip-bot")

WELCOME = (
    "Namaste! I'm *SIP Saathi* — your mutual-fund SIP planning assistant.\n\n"
    "I can help you:\n"
    "• Plan a goal (e.g. \u201c₹50 lakh in 10 years\u201d)\n"
    "• Project a SIP (\u201c₹10,000/month at 12% for 15 years\u201d)\n"
    "• Analyse a fund's real returns (\u201chow has Parag Parikh Flexi Cap done?\u201d)\n"
    "• Backtest (\u201cwhat if I'd put ₹5,000/month in it for 5 years?\u201d)\n\n"
    "_Educational tool only — not SEBI-registered advice. Past performance doesn't guarantee future returns._\n\n"
    "What's on your mind?"
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(WELCOME, parse_mode="Markdown")


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db.clear_user(str(update.effective_user.id))
    await update.message.reply_text("Cleared. We're starting fresh. 🙏")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    text = update.message.text
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    try:
        reply = await asyncio.to_thread(agent.run_turn, user_id, text)
    except Exception as e:
        log.exception("agent error")
        reply = f"Sorry, something went wrong: {e}"

    # Send any charts / PDFs the agent generated during this turn
    from tools import get_and_clear_pending_files
    pending = get_and_clear_pending_files()
    for f in pending:
        try:
            if f["type"] == "photo":
                await update.message.reply_photo(photo=open(f["path"], "rb"))
            elif f["type"] == "document":
                await update.message.reply_document(document=open(f["path"], "rb"),
                                                    filename="SIP_Plan.pdf")
        except Exception as e:
            log.warning(f"Could not send file {f}: {e}")

    # Telegram hard limit is 4096 chars
    for i in range(0, len(reply), 4000):
        await update.message.reply_text(reply[i:i + 4000])


def main():
    db.init_db()
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    from telegram.request import HTTPXRequest
    request = HTTPXRequest(connect_timeout=20, read_timeout=30, write_timeout=30)
    app = Application.builder().token(token).request(request).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    log.info("SIP Saathi is running. Press Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
