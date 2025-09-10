import logging
import json
import os
import re
from datetime import datetime
from typing import Dict, List, Set
import asyncio

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from telegram.constants import ChatMemberStatus

# Настройки
ADMIN_ID = 946695591
BOT_TOKEN = "8456387820:AAEpFPpRPntlBV0hAmAPIRIwk5KoxLlwDnA"

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Глобальные переменные для хранения данных
chat_data = {}  # {chat_id: {"bots": set(), "manual_bots": set(), "ignored_bots": set()}}
DATA_FILE = "bot_data.json"

def load_data():
    """Загружает данные из файла"""
    global chat_data
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Преобразуем списки обратно в множества
                for chat_id, info in data.items():
                    chat_data[int(chat_id)] = {
                        "bots": set(info.get("bots", [])),
                        "manual_bots": set(info.get("manual_bots", [])),
                        "ignored_bots": set(info.get("ignored_bots", []))
                    }
    except Exception as e:
        logger.error(f"Ошибка загрузки данных: {e}")
        chat_data = {}

def save_data():
    """Сохраняет данные в файл"""
    try:
        # Преобразуем множества в списки для JSON
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
        logger.error(f"Ошибка сохранения данных: {e}")

def is_bot_by_username(user):
    """Проверяет, является ли пользователь ботом по username"""
    if not user or not user.username:
        return False
    
    username = user.username.lower()
    # Проверяем наличие "bot" в username
    return "bot" in username

def is_spam_message(message_text: str) -> bool:
    """Простая проверка на спам без ИИ - по ключевым словам"""
    if not message_text:
        return False
    
    text = message_text.lower()
    
    # Спам-паттерны на русском и английском
    spam_patterns = [
        # Реклама каналов/групп
        r'(подписыв|subscribe|join|присоедин)[^.]*(@|t\.me|telegram)',
        r'(наш\s+канал|наша\s+группа|our\s+channel|our\s+group)',
        r'(жми\s+|нажми\s+|click\s+|tap\s+).*(ссылк|link)',
        
        # Финансовая реклама
        r'(заработ|earn|profit|доход)[^.]*(\$|\d+|рубл|usd)',
        r'(инвест|invest|вклад|депозит)[^.]*(\%|процент|profit)',
        r'(бинарн|binary|опцион|trading|трейд)',
        
        # Азартные игры
        r'(казино|casino|ставк|bet|слот|slot)',
        r'(выигр|win)[^.]*(\$|\d+.*рубл|\d+.*usd)',
        
        # Промо-коды и скидки
        r'(промо|promo|скидк|discount|код)[^.]*(\d+|\%)',
        r'(акци|action|offer|предложени)',
        
        # Подозрительные ссылки
        r't\.me/[^/\s]+',
        r'@[a-zA-Z0-9_]{5,}',
        
        # Спам-фразы
        r'(бесплатн|free)[^.]*(\$|\d+|подарок|gift)',
        r'(только\s+сегодня|today\s+only|ограничен|limited)',
        r'(не\s+упусти|don\'t\s+miss|срочно|urgent)'
    ]
    
    # Подсчитываем совпадения
    spam_score = 0
    for pattern in spam_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            spam_score += 1
    
    # Дополнительная проверка на количество эмодзи и ссылок
    emoji_count = len(re.findall(r'[^\w\s]', text))
    link_count = len(re.findall(r'(http|t\.me|@)', text))
    
    if emoji_count > 10 or link_count > 2:
        spam_score += 1
    
    # Если найдено 2 или больше спам-паттернов
    return spam_score >= 2

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start"""
    user_id = update.effective_user.id
    
    if user_id == ADMIN_ID:
        await update.message.reply_text(
            "🤖 Добро пожаловать в админ-панель бота!\n\n"
            "Доступные команды:\n"
            "/admin - Админ панель\n"
            "/stats - Статистика\n\n"
            "Бот автоматически удаляет рекламные сообщения от ботов (определяет по username с 'bot')."
        )
    else:
        await update.message.reply_text(
            "🤖 Привет! Я бот для модерации рекламы от других ботов.\n\n"
            "Добавь меня в чат и дай права администратора для удаления сообщений.\n"
            "Используй /botlist чтобы посмотреть список отслеживаемых ботов."
        )

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Админ панель"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ У вас нет прав для использования этой команды.")
        return
    
    keyboard = [
        [InlineKeyboardButton("📊 Статистика чатов", callback_data="admin_stats")],
        [InlineKeyboardButton("📋 Список всех чатов", callback_data="admin_chats")],
        [InlineKeyboardButton("🔄 Обновить данные", callback_data="admin_refresh")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🔧 Админ панель\n\nВыберите действие:",
        reply_markup=reply_markup
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка кнопок"""
    query = update.callback_query
    await query.answer()
    
    # Админ функции
    if update.effective_user.id == ADMIN_ID:
        if query.data == "admin_stats":
            total_chats = len(chat_data)
            total_bots = sum(len(info["bots"]) + len(info["manual_bots"]) for info in chat_data.values())
            
            text = f"📊 Статистика:\n\n"
            text += f"🔹 Всего чатов: {total_chats}\n"
            text += f"🔹 Всего отслеживаемых ботов: {total_bots}\n"
            text += f"🔹 Последнее обновление: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
            
            await query.edit_message_text(text)
            return
        
        elif query.data == "admin_chats":
            if not chat_data:
                await query.edit_message_text("📋 Нет активных чатов.")
                return
            
            text = "📋 Активные чаты:\n\n"
            for chat_id, info in list(chat_data.items())[:10]:
                bots_count = len(info["bots"]) + len(info["manual_bots"])
                text += f"🔸 Chat ID: {chat_id}\n"
                text += f"   Ботов: {bots_count}\n\n"
            
            if len(chat_data) > 10:
                text += f"... и еще {len(chat_data) - 10} чатов"
            
            await query.edit_message_text(text)
            return
        
        elif query.data == "admin_refresh":
            save_data()
            await query.edit_message_text("🔄 Данные обновлены!")
            return
    
    # Обработка кнопок управления ботами в чатах
    if query.data.startswith("add_bot_") or query.data.startswith("remove_bot_"):
        chat_id = int(query.data.split("_")[-1])
        
        # Проверяем права пользователя в чате
        try:
            member = await context.bot.get_chat_member(chat_id, update.effective_user.id)
            if member.status not in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
                await query.edit_message_text("❌ Только администраторы чата могут управлять списком ботов.")
                return
        except:
            await query.edit_message_text("❌ Ошибка проверки прав.")
            return
        
        if query.data.startswith("add_bot_"):
            await query.edit_message_text(
                "➕ Для добавления бота в список отслеживания:\n\n"
                "1. Ответьте на сообщение от бота командой /addbot\n"
                "2. Или отправьте /addbot @username_бота"
            )
        
        elif query.data.startswith("remove_bot_"):
            info = chat_data.get(chat_id, {"bots": set(), "manual_bots": set(), "ignored_bots": set()})
            all_bots = info["bots"].union(info["manual_bots"]) - info["ignored_bots"]
            
            if not all_bots:
                await query.edit_message_text("❌ Нет ботов для удаления.")
                return
            
            keyboard = []
            for bot_id in list(all_bots)[:10]:  # Показываем первые 10
                try:
                    bot_info = await context.bot.get_chat(bot_id)
                    bot_name = bot_info.username or bot_info.first_name or str(bot_id)
                except:
                    bot_name = str(bot_id)
                
                keyboard.append([InlineKeyboardButton(
                    f"❌ {bot_name[:20]}...", 
                    callback_data=f"ignore_bot_{chat_id}_{bot_id}"
                )])
            
            keyboard.append([InlineKeyboardButton("« Назад", callback_data="back_to_botlist")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                "Выберите бота для исключения из отслеживания:",
                reply_markup=reply_markup
            )
    
    elif query.data.startswith("ignore_bot_"):
        parts = query.data.split("_")
        chat_id = int(parts[2])
        bot_id = int(parts[3])
        
        if chat_id not in chat_data:
            chat_data[chat_id] = {"bots": set(), "manual_bots": set(), "ignored_bots": set()}
        
        chat_data[chat_id]["ignored_bots"].add(bot_id)
        save_data()
        
        await query.edit_message_text(f"✅ Бот {bot_id} исключен из отслеживания.")

async def botlist_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /botlist - показывает список ботов в чате"""
    chat_id = update.effective_chat.id
    
    if chat_id not in chat_data:
        await update.message.reply_text("🤖 В этом чате пока нет отслеживаемых ботов.")
        return
    
    info = chat_data[chat_id]
    all_bots = info["bots"].union(info["manual_bots"]) - info["ignored_bots"]
    
    if not all_bots:
        await update.message.reply_text("🤖 В этом чате нет активных ботов для отслеживания.")
        return
    
    text = "🤖 Отслеживаемые боты в этом чате:\n\n"
    for i, bot_id in enumerate(all_bots, 1):
        try:
            bot_info = await context.bot.get_chat(bot_id)
            bot_name = f"@{bot_info.username}" if bot_info.username else bot_info.first_name
        except:
            bot_name = str(bot_id)
        
        text += f"{i}. {bot_name} (ID: {bot_id})\n"
    
    # Кнопки для управления (только для админов чата)
    try:
        member = await context.bot.get_chat_member(chat_id, update.effective_user.id)
        if member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
            keyboard = [
                [InlineKeyboardButton("➕ Добавить бота", callback_data=f"add_bot_{chat_id}")],
                [InlineKeyboardButton("➖ Исключить бота", callback_data=f"remove_bot_{chat_id}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(text, reply_markup=reply_markup)
        else:
            await update.message.reply_text(text)
    except:
        await update.message.reply_text(text)

async def addbot_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для ручного добавления бота в отслеживание"""
    chat_id = update.effective_chat.id
    
    # Проверяем права пользователя
    try:
        member = await context.bot.get_chat_member(chat_id, update.effective_user.id)
        if member.status not in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
            await update.message.reply_text("❌ Только администраторы могут добавлять ботов.")
            return
    except:
        await update.message.reply_text("❌ Ошибка проверки прав.")
        return
    
    if chat_id not in chat_data:
        chat_data[chat_id] = {"bots": set(), "manual_bots": set(), "ignored_bots": set()}
    
    # Если команда - ответ на сообщение
    if update.message.reply_to_message:
        target_user = update.message.reply_to_message.from_user
        if is_bot_by_username(target_user) or target_user.is_bot:
            chat_data[chat_id]["manual_bots"].add(target_user.id)
            save_data()
            
            username = f"@{target_user.username}" if target_user.username else target_user.first_name
            await update.message.reply_text(f"✅ Бот {username} добавлен в отслеживание.")
        else:
            await update.message.reply_text("❌ Это не бот.")
        return
    
    # Если указан username
    if context.args:
        username = context.args[0].replace("@", "")
        try:
            # Ищем пользователя по username (упрощенный способ)
            await update.message.reply_text(
                f"🔍 Для добавления @{username} в отслеживание, попросите его написать в чат, "
                f"затем ответьте на его сообщение командой /addbot"
            )
        except:
            await update.message.reply_text("❌ Не удалось найти пользователя.")
    else:
        await update.message.reply_text(
            "Использование:\n"
            "• Ответьте на сообщение бота: /addbot\n"
            "• Или укажите username: /addbot @username"
        )

async def handle_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка добавления бота в чат"""
    message = update.message
    chat_id = message.chat.id
    
    # Проверяем, добавлен ли наш бот
    for member in message.new_chat_members:
        if member.id == context.bot.id:
            # Наш бот добавлен в чат
            if chat_id not in chat_data:
                chat_data[chat_id] = {
                    "bots": set(),
                    "manual_bots": set(),
                    "ignored_bots": set()
                }
                save_data()
            
            welcome_text = (
                "🤖 Привет! Я бот для модерации рекламных сообщений от других ботов.\n\n"
                "⚠️ Для корректной работы мне нужны права администратора:\n"
                "• Удаление сообщений\n\n"
                "📋 Команды:\n"
                "• /botlist - список отслеживаемых ботов\n"
                "• /addbot - добавить бота в отслеживание\n\n"
                "🎯 Я автоматически определяю ботов по их username (должен содержать 'bot')"
            )
            
            await message.reply_text(welcome_text)
            break

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Основной обработчик сообщений"""
    message = update.message
    if not message or not message.text:
        return
    
    chat_id = message.chat.id
    user = message.from_user
    
    # Пропускаем сообщения от нашего бота
    if user.id == context.bot.id:
        return
    
    # Инициализируем данные чата если их нет
    if chat_id not in chat_data:
        chat_data[chat_id] = {
            "bots": set(),
            "manual_bots": set(),
            "ignored_bots": set()
        }
    
    # Проверяем, является ли отправитель ботом
    is_bot = user.is_bot or is_bot_by_username(user)
    
    if is_bot and user.id != context.bot.id:
        # Добавляем бота в список если его там нет
        chat_data[chat_id]["bots"].add(user.id)
        save_data()
        
        # Проверяем, не в списке ли игнорируемых
        if user.id in chat_data[chat_id]["ignored_bots"]:
            return
        
        # Проверяем сообщение на рекламу
        try:
            is_spam = is_spam_message(message.text)
            if is_spam:
                # Проверяем права бота на удаление
                bot_member = await context.bot.get_chat_member(chat_id, context.bot.id)
                if (bot_member.status == ChatMemberStatus.ADMINISTRATOR and 
                    hasattr(bot_member, 'can_delete_messages') and 
                    bot_member.can_delete_messages):
                    
                    await message.delete()
                    
                    username = f"@{user.username}" if user.username else user.first_name
                    logger.info(f"Удалено рекламное сообщение от {username} ({user.id}) в чате {chat_id}")
                    
                    # Отправляем короткое уведомление
                    notification = await context.bot.send_message(
                        chat_id,
                        f"🚫 Удалена реклама от {username}"
                    )
                    
                    # Удаляем уведомление через 5 секунд
                    await asyncio.sleep(5)
                    try:
                        await notification.delete()
                    except:
                        pass
                        
                else:
                    logger.warning(f"Нет прав для удаления сообщения в чате {chat_id}")
        except Exception as e:
            logger.error(f"Ошибка при проверке сообщения: {e}")

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда статистики (только для админа)"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ У вас нет прав для использования этой команды.")
        return
    
    total_chats = len(chat_data)
    total_bots = sum(len(info["bots"]) + len(info["manual_bots"]) for info in chat_data.values())
    
    text = f"📊 Статистика бота:\n\n"
    text += f"🔹 Активных чатов: {total_chats}\n"
    text += f"🔹 Отслеживаемых ботов: {total_bots}\n"
    text += f"🔹 Время работы: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
    
    if chat_data:
        text += "📋 Топ-5 чатов по количеству ботов:\n"
        sorted_chats = sorted(
            chat_data.items(),
            key=lambda x: len(x[1]["bots"]) + len(x[1]["manual_bots"]),
            reverse=True
        )[:5]
        
        for i, (chat_id, info) in enumerate(sorted_chats, 1):
            bots_count = len(info["bots"]) + len(info["manual_bots"])
            text += f"{i}. Chat {chat_id}: {bots_count} ботов\n"
    
    await update.message.reply_text(text)

def main():
    """Запуск бота"""
    # Загружаем данные
    load_data()
    
    # Создаем приложение
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Добавляем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin_panel))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("botlist", botlist_command))
    application.add_handler(CommandHandler("addbot", addbot_command))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, handle_new_member))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Запускаем бота
    print("🤖 Бот запущен! (Полностью бесплатное решение)")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
