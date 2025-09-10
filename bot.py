import logging
import json
import os
import re
from datetime import datetime
from typing import Dict, Set
import asyncio

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from telegram.constants import ChatMemberStatus
from telegram.error import BadRequest

# Настройки
ADMIN_ID = 946695591
BOT_TOKEN = os.getenv('BOT_TOKEN')

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

chat_data = {}
DATA_FILE = "bot_data.json"

def load_data():
    global chat_data
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                for chat_id, info in data.items():
                    chat_data[int(chat_id)] = {
                        "bots": set(info.get("bots", [])),
                        "manual_bots": set(info.get("manual_bots", [])),
                        "ignored_bots": set(info.get("ignored_bots", []))
                    }
    except Exception as e:
        logger.error(f"Ошибка загрузки: {e}")
        chat_data = {}

def save_data():
    try:
        data_to_save = {}
        for chat_id, info in chat_data.items():
            data_to_save[str(chat_id)] = {
                "bots": list(info["bots"]),
                "manual_bots": list(info["manual_bots"]),
                "ignored_bots": list(info["ignored_bots"])
            }
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data_to_save, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Ошибка сохранения: {e}")

def is_bot_by_username(username: str):
    if not username:
        return False
    return username.lower().endswith('bot')

async def is_spam_message(text: str) -> bool:
    if not text:
        return False
    text = text.lower()
    spam_patterns = [
        r'(подписыв|subscribe|join|присоедин)[^.]*(@|t\.me|telegram)',
        r'(наш\s+канал|наша\s+группа|our\s+channel|our\s+group)',
        r'(жми\s+|нажми\s+|click\s+|tap\s+).*(ссылк|link)',
        r'(заработ|earn|profit|доход)[^.]*(\$|\d+|рубл|usd)',
        r'(инвест|invest|вклад|депозит)[^.]*(\%|процент|profit)',
        r'(бинарн|binary|опцион|trading|трейд)',
        r'(казино|casino|ставк|bet|слот|slot)',
        r'(выигр|win)[^.]*(\$|\d+.*рубл|\d+.*usd)',
        r'(промо|promo|скидк|discount|код)[^.]*(\d+|\%)',
        r'(акци|action|offer|предложени)',
        r't\.me/[^/\s]+',
        r'@[a-zA-Z0-9_]{5,}',
        r'(бесплатн|free)[^.]*(\$|\d+|подарок|gift)',
        r'(только\s+сегодня|today\s+only|ограничен|limited)',
        r'(не\s+упусти|don\'t\s+miss|срочно|urgent)'
    ]
    spam_score = sum(1 for pattern in spam_patterns if re.search(pattern, text, re.IGNORECASE))
    emoji_count = len(re.findall(r'[^\w\s]', text))
    link_count = len(re.findall(r'(http|t\.me|@)', text))
    if emoji_count > 10 or link_count > 2:
        spam_score += 1
    return spam_score >= 2

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id == ADMIN_ID:
        await update.message.reply_text(
            "🤖 Добро пожаловать в админ-панель!\n\nКоманды:\n/admin - Панель\n/stats - Статистика\n\nБот удаляет рекламу от ботов (по username ends with 'bot')."
        )
    else:
        await update.message.reply_text(
            "🤖 Привет! Я модерирую рекламу от ботов.\n\nДобавь меня в чат, дай админ-права на удаление.\n/botlist - Список ботов."
        )

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Нет прав.")
        return
    keyboard = [
        [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton("📋 Чаты", callback_data="admin_chats")],
        [InlineKeyboardButton("🔄 Обновить", callback_data="admin_refresh")]
    ]
    await update.message.reply_text("🔧 Админ панель:", reply_markup=InlineKeyboardMarkup(keyboard))

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if update.effective_user.id != ADMIN_ID and not query.data.startswith(('add_bot_', 'remove_bot_', 'ignore_bot_', 'back_to_botlist')):
        await query.edit_message_text("❌ Нет прав.")
        return
    data = query.data
    if data == "admin_stats":
        total_chats = len(chat_data)
        total_bots = sum(len(info["bots"]) + len(info["manual_bots"]) for info in chat_data.values())
        text = f"📊 Статистика:\n🔹 Чатов: {total_chats}\n🔹 Ботов: {total_bots}\n🔹 Обновлено: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
        await query.edit_message_text(text)
    elif data == "admin_chats":
        if not chat_data:
            await query.edit_message_text("📋 Нет чатов.")
            return
        text = "📋 Чаты:\n"
        for chat_id, info in list(chat_data.items())[:10]:
            text += f"🔸 {chat_id}: {len(info['bots']) + len(info['manual_bots'])} ботов\n"
        if len(chat_data) > 10:
            text += f"... +{len(chat_data)-10}"
        await query.edit_message_text(text)
    elif data == "admin_refresh":
        save_data()
        await query.edit_message_text("🔄 Обновлено!")
    elif data.startswith("add_bot_"):
        chat_id = int(data.split("_")[-1])
        member = await context.bot.get_chat_member(chat_id, update.effective_user.id)
        if member.status not in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
            await query.edit_message_text("❌ Только админы чата.")
            return
        await query.edit_message_text("➕ Ответьте на сообщение /addbot или /addbot @username/ID")
    elif data.startswith("remove_bot_"):
        chat_id = int(data.split("_")[-1])
        member = await context.bot.get_chat_member(chat_id, update.effective_user.id)
        if member.status not in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
            await query.edit_message_text("❌ Только админы чата.")
            return
        info = chat_data.get(chat_id, {"bots": set(), "manual_bots": set(), "ignored_bots": set()})
        all_bots = info["bots"].union(info["manual_bots"]) - info["ignored_bots"]
        if not all_bots:
            await query.edit_message_text("❌ Нет ботов.")
            return
        keyboard = []
        for bot_id in list(all_bots)[:10]:
            try:
                bot_info = await context.bot.get_chat(bot_id)
                name = bot_info.username or bot_info.first_name or str(bot_id)
                if bot_id < 0:
                    name = f"Channel: {name}"
            except:
                name = str(bot_id)
            keyboard.append([InlineKeyboardButton(f"❌ {name[:20]}...", callback_data=f"ignore_bot_{chat_id}_{bot_id}")])
        keyboard.append([InlineKeyboardButton("« Назад", callback_data=f"back_to_botlist_{chat_id}")])
        await query.edit_message_text("Выберите для исключения:", reply_markup=InlineKeyboardMarkup(keyboard))
    elif data.startswith("ignore_bot_"):
        parts = data.split("_")
        chat_id = int(parts[2])
        bot_id = int(parts[3])
        if chat_id in chat_data:
            chat_data[chat_id]["ignored_bots"].add(bot_id)
            chat_data[chat_id]["bots"].discard(bot_id)
            chat_data[chat_id]["manual_bots"].discard(bot_id)
            save_data()
        await query.edit_message_text(f"✅ Бот {bot_id} исключён.")
    elif data.startswith("back_to_botlist_"):
        chat_id = int(data.split("_")[-1])
        info = chat_data.get(chat_id, {"bots": set(), "manual_bots": set(), "ignored_bots": set()})
        all_bots = info["bots"].union(info["manual_bots"]) - info["ignored_bots"]
        if not all_bots:
            text = "🤖 Нет ботов."
        else:
            text = "🤖 Отслеживаемые боты:\n"
            for i, bot_id in enumerate(all_bots, 1):
                try:
                    bot_info = await context.bot.get_chat(bot_id)
                    name = f"@{bot_info.username}" if bot_info.username else bot_info.first_name or str(bot_id)
                    if bot_id < 0:
                        name = f"Channel: {name}"
                except:
                    name = str(bot_id)
                text += f"{i}. {name} ({bot_id})\n"
        keyboard = [
            [InlineKeyboardButton("➕ Добавить", callback_data=f"add_bot_{chat_id}")],
            [InlineKeyboardButton("➖ Исключить", callback_data=f"remove_bot_{chat_id}")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def botlist_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in chat_data:
        await update.message.reply_text("🤖 Нет ботов.")
        return
    info = chat_data[chat_id]
    all_bots = info["bots"].union(info["manual_bots"]) - info["ignored_bots"]
    if not all_bots:
        await update.message.reply_text("🤖 Нет ботов.")
        return
    text = "🤖 Отслеживаемые боты:\n"
    for i, bot_id in enumerate(all_bots, 1):
        try:
            bot_info = await context.bot.get_chat(bot_id)
            name = f"@{bot_info.username}" if bot_info.username else bot_info.first_name or str(bot_id)
            if bot_id < 0:
                name = f"Channel: {name}"
        except:
            name = str(bot_id)
        text += f"{i}. {name} ({bot_id})\n"
    member = await context.bot.get_chat_member(chat_id, update.effective_user.id)
    if member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
        keyboard = [
            [InlineKeyboardButton("➕ Добавить", callback_data=f"add_bot_{chat_id}")],
            [InlineKeyboardButton("➖ Исключить", callback_data=f"remove_bot_{chat_id}")]
        ]
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(text)

async def addbot_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    member = await context.bot.get_chat_member(chat_id, update.effective_user.id)
    if member.status not in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
        await update.message.reply_text("❌ Только админы.")
        return
    if chat_id not in chat_data:
        chat_data[chat_id] = {"bots": set(), "manual_bots": set(), "ignored_bots": set()}
    added = []
    errors = []
    if update.message.reply_to_message:
        reply_msg = update.message.reply_to_message
        target_id = None
        name = "Неизвестный"
        if reply_msg.from_user:
            target_id = reply_msg.from_user.id
            name = f"@{reply_msg.from_user.username}" if reply_msg.from_user.username else reply_msg.from_user.first_name
        elif reply_msg.sender_chat:
            target_id = reply_msg.sender_chat.id
            name = f"Channel @{reply_msg.sender_chat.username}" if reply_msg.sender_chat.username else str(target_id)
        elif reply_msg.forward_from:
            target_id = reply_msg.forward_from.id
            name = f"@{reply_msg.forward_from.username}" if reply_msg.forward_from.username else reply_msg.forward_from.first_name
        elif reply_msg.forward_sender_name:
            name = reply_msg.forward_sender_name
            errors.append(f"❌ {name}: Скрытый отправитель, используй ID.")
        if target_id:
            chat_data[chat_id]["manual_bots"].add(target_id)
            chat_data[chat_id]["ignored_bots"].discard(target_id)
            added.append(name)
        else:
            logger.info(f"addbot: target_id None for reply in {chat_id}")
            errors.append("❌ Тип сообщения не поддерживается, используй ID или @username.")
    elif context.args:
        for arg in context.args:
            target_id = None
            name = arg
            if arg.startswith('@'):
                try:
                    chat = await context.bot.get_chat(arg)
                    target_id = chat.id
                    name = f"@{chat.username}" if chat.username else chat.first_name or str(target_id)
                    if target_id < 0:
                        name = f"Channel {name}"
                except BadRequest as e:
                    errors.append(f"❌ {arg}: Не найден ({e.message}).")
            elif arg.lstrip('-').isdigit():  # Allow negative for channels
                target_id = int(arg)
            else:
                errors.append(f"❌ {arg}: Неверный формат (ID или @username).")
            if target_id:
                chat_data[chat_id]["manual_bots"].add(target_id)
                chat_data[chat_id]["ignored_bots"].discard(target_id)
                added.append(name)
    else:
        await update.message.reply_text("Использование:\n• Reply: /addbot\n• /addbot @username/ID [другие...]")
        return
    if added or errors:
        save_data()
        text = ""
        if added:
            text += "✅ Добавлены: " + ", ".join(added) + "\n"
        if errors:
            text += "\n".join(errors)
        await update.message.reply_text(text)

async def removebot_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    member = await context.bot.get_chat_member(chat_id, update.effective_user.id)
    if member.status not in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
        await update.message.reply_text("❌ Только админы.")
        return
    if chat_id not in chat_data:
        await update.message.reply_text("❌ Нет данных.")
        return
    removed = []
    errors = []
    if update.message.reply_to_message:
        reply_msg = update.message.reply_to_message
        target_id = None
        name = "Неизвестный"
        if reply_msg.from_user:
            target_id = reply_msg.from_user.id
            name = f"@{reply_msg.from_user.username}" if reply_msg.from_user.username else reply_msg.from_user.first_name
        elif reply_msg.sender_chat:
            target_id = reply_msg.sender_chat.id
            name = f"Channel @{reply_msg.sender_chat.username}" if reply_msg.sender_chat.username else str(target_id)
        elif reply_msg.forward_from:
            target_id = reply_msg.forward_from.id
            name = f"@{reply_msg.forward_from.username}" if reply_msg.forward_from.username else reply_msg.forward_from.first_name
        elif reply_msg.forward_sender_name:
            name = reply_msg.forward_sender_name
            errors.append(f"❌ {name}: Скрытый, используй ID.")
        if target_id:
            if target_id not in chat_data[chat_id]["bots"] and target_id not in chat_data[chat_id]["manual_bots"]:
                errors.append(f"❌ {name}: Не в списке.")
            else:
                chat_data[chat_id]["ignored_bots"].add(target_id)
                chat_data[chat_id]["bots"].discard(target_id)
                chat_data[chat_id]["manual_bots"].discard(target_id)
                removed.append(name)
        else:
            logger.info(f"removebot: target_id None for reply in {chat_id}")
            errors.append("❌ Тип не поддерживается, используй ID или @username.")
    elif context.args:
        for arg in context.args:
            target_id = None
            name = arg
            if arg.startswith('@'):
                try:
                    chat = await context.bot.get_chat(arg)
                    target_id = chat.id
                    name = f"@{chat.username}" if chat.username else chat.first_name or str(target_id)
                    if target_id < 0:
                        name = f"Channel {name}"
                except BadRequest as e:
                    errors.append(f"❌ {arg}: Не найден ({e.message}).")
            elif arg.lstrip('-').isdigit():
                target_id = int(arg)
            else:
                errors.append(f"❌ {arg}: Неверный формат.")
            if target_id:
                if target_id not in chat_data[chat_id]["bots"] and target_id not in chat_data[chat_id]["manual_bots"]:
                    errors.append(f"❌ {name}: Не в списке.")
                else:
                    chat_data[chat_id]["ignored_bots"].add(target_id)
                    chat_data[chat_id]["bots"].discard(target_id)
                    chat_data[chat_id]["manual_bots"].discard(target_id)
                    removed.append(name)
    else:
        await update.message.reply_text("Использование:\n• Reply: /removebot\n• /removebot @username/ID [другие...]")
        return
    if removed or errors:
        save_data()
        text = ""
        if removed:
            text += "✅ Исключены: " + ", ".join(removed) + "\n"
        if errors:
            text += "\n".join(errors)
        await update.message.reply_text(text)

async def refreshbot_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    member = await context.bot.get_chat_member(chat_id, update.effective_user.id)
    if member.status not in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
        await update.message.reply_text("❌ Только админы.")
        return
    if chat_id not in chat_data:
        await update.message.reply_text("❌ Нет данных.")
        return
    chat_data[chat_id]["bots"] = set()
    try:
        admins = await context.bot.get_chat_administrators(chat_id)
        for admin in admins:
            user = admin.user
            if (user.is_bot or is_bot_by_username(user.username)) and user.id != context.bot.id:
                chat_data[chat_id]["bots"].add(user.id)
    except Exception as e:
        logger.warning(f"Скан админов ошибка: {e}")
    save_data()
    await update.message.reply_text("✅ Список обновлён. Боты среди админов добавлены. Новые — при сообщениях.")

async def handle_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    chat_id = message.chat.id
    for member in message.new_chat_members:
        if member.id == context.bot.id:
            if chat_id not in chat_data:
                chat_data[chat_id] = {"bots": set(), "manual_bots": set(), "ignored_bots": set()}
                save_data()
            await message.reply_text(
                "🤖 Привет! Я модерирую рекламу от ботов.\n\n⚠️ Дайте админ-права на удаление.\n\nКоманды:\n/botlist\n/addbot\n/removebot\n/refreshbot\n\nОбнаруживаю по username ends with 'bot'."
            )
            try:
                admins = await context.bot.get_chat_administrators(chat_id)
                for admin in admins:
                    user = admin.user
                    if (user.is_bot or is_bot_by_username(user.username)) and user.id != context.bot.id:
                        chat_data[chat_id]["bots"].add(user.id)
                save_data()
            except:
                pass
            break

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message:
        return
    chat_id = message.chat.id
    from_user = message.from_user
    sender_chat = message.sender_chat
    target_id = from_user.id if from_user else sender_chat.id if sender_chat else None
    if target_id == context.bot.id or target_id is None:
        return
    if chat_id not in chat_data:
        chat_data[chat_id] = {"bots": set(), "manual_bots": set(), "ignored_bots": set()}
    is_bot = False
    username = ""
    if from_user:
        is_bot = from_user.is_bot or is_bot_by_username(from_user.username)
        username = from_user.username or from_user.first_name
    elif sender_chat:
        is_bot = is_bot_by_username(sender_chat.username)
        username = sender_chat.username
    if is_bot:
        chat_data[chat_id]["bots"].add(target_id)
        save_data()
    if target_id in chat_data[chat_id]["ignored_bots"]:
        return
    all_tracked = chat_data[chat_id]["bots"].union(chat_data[chat_id]["manual_bots"])
    if target_id not in all_tracked:
        return
    text = message.text or message.caption or ""
    if await is_spam_message(text):
        try:
            bot_member = await context.bot.get_chat_member(chat_id, context.bot.id)
            if bot_member.status == ChatMemberStatus.ADMINISTRATOR and bot_member.can_delete_messages:
                await message.delete()
                logger.info(f"Удалено от {username} ({target_id}) в {chat_id}")
                notification = await context.bot.send_message(chat_id, f"🚫 Удалена реклама от @{username}")
                await asyncio.sleep(5)
                await notification.delete()
            else:
                logger.warning(f"Нет прав в {chat_id}")
        except Exception as e:
            logger.error(f"Ошибка: {e}")

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Нет прав.")
        return
    total_chats = len(chat_data)
    total_bots = sum(len(info["bots"]) + len(info["manual_bots"]) for info in chat_data.values())
    text = f"📊 Статистика:\n🔹 Чатов: {total_chats}\n🔹 Ботов: {total_bots}\n🔹 Время: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\nТоп-5 чатов:\n"
    sorted_chats = sorted(chat_data.items(), key=lambda x: len(x[1]["bots"]) + len(x[1]["manual_bots"]), reverse=True)[:5]
    for i, (cid, info) in enumerate(sorted_chats, 1):
        text += f"{i}. {cid}: {len(info['bots']) + len(info['manual_bots'])} ботов\n"
    await update.message.reply_text(text)

def main():
    load_data()
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin_panel))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("botlist", botlist_command))
    application.add_handler(CommandHandler("addbot", addbot_command))
    application.add_handler(CommandHandler("removebot", removebot_command))
    application.add_handler(CommandHandler("refreshbot", refreshbot_command))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, handle_new_member))
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))
    print("🤖 Бот запущен! (Бесплатно 24/7)")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
