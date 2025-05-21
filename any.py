#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import logging
import os
import sys
import traceback
import time
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from telegram.error import TelegramError

# Настройка расширенного логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler("bot_log.txt", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Директория для хранения файлов со стоп-словами для разных групп
STOPWORDS_DIR = 'stopwords'

# Создаем директорию, если она не существует
if not os.path.exists(STOPWORDS_DIR):
    os.makedirs(STOPWORDS_DIR)
    logger.info(f"Создана директория {STOPWORDS_DIR}")

# Кэш для хранения последних обработанных сообщений, чтобы избежать повторной обработки
processed_messages = set()
# Максимальный размер кэша
MAX_CACHE_SIZE = 1000

# Функция для получения пути к файлу стоп-слов для конкретной группы
def get_stopwords_file(chat_id):
    return os.path.join(STOPWORDS_DIR, f'stopwords_{chat_id}.json')

# Функция для загрузки стоп-слов из файла для конкретной группы
async def load_stopwords(chat_id):
    file_path = get_stopwords_file(chat_id)
    logger.info(f"Загрузка стоп-слов для чата {chat_id} из файла {file_path}")
    
    try:
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as file:
                data = json.load(file)
                stopwords = data.get('stopwords', [])
                logger.info(f"Загружены стоп-слова для чата {chat_id}: {stopwords}")
                return stopwords
        else:
            # Если файл не существует, создаем его с пустым списком
            logger.info(f"Файл стоп-слов для чата {chat_id} не существует, создаем новый")
            await save_stopwords(chat_id, [])
            return []
    except Exception as e:
        logger.error(f"Ошибка при загрузке стоп-слов для чата {chat_id}: {e}")
        logger.error(traceback.format_exc())
        return []

# Функция для сохранения стоп-слов в файл для конкретной группы
async def save_stopwords(chat_id, stopwords):
    file_path = get_stopwords_file(chat_id)
    logger.info(f"Сохранение стоп-слов для чата {chat_id} в файл {file_path}: {stopwords}")
    
    try:
        with open(file_path, 'w', encoding='utf-8') as file:
            json.dump({'stopwords': stopwords}, file, ensure_ascii=False, indent=4)
        logger.info(f"Стоп-слова для чата {chat_id} успешно сохранены")
    except Exception as e:
        logger.error(f"Ошибка при сохранении стоп-слов для чата {chat_id}: {e}")
        logger.error(traceback.format_exc())

# Функция для проверки, является ли пользователь администратором группы
async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    # Для личных чатов всегда возвращаем True
    if update.effective_chat.type == 'private':
        logger.info(f"Пользователь {user_id} в личном чате {chat_id}, права администратора: True")
        return True
    
    # Для групповых чатов проверяем, является ли пользователь администратором
    try:
        chat_member = await context.bot.get_chat_member(chat_id, user_id)
        is_admin_result = chat_member.status in ['creator', 'administrator']
        logger.info(f"Пользователь {user_id} в чате {chat_id}, статус: {chat_member.status}, права администратора: {is_admin_result}")
        return is_admin_result
    except Exception as e:
        logger.error(f"Ошибка при проверке прав администратора для пользователя {user_id} в чате {chat_id}: {e}")
        logger.error(traceback.format_exc())
        return False

# Функция для проверки прав бота в группе
async def check_bot_permissions(context: ContextTypes.DEFAULT_TYPE, chat_id):
    try:
        bot_id = context.bot.id
        bot_member = await context.bot.get_chat_member(chat_id, bot_id)
        
        logger.info(f"Права бота в чате {chat_id}: статус={bot_member.status}, can_delete_messages={getattr(bot_member, 'can_delete_messages', False)}")
        
        if bot_member.status not in ['administrator', 'creator']:
            logger.warning(f"Бот не является администратором в чате {chat_id}")
            return False, "Бот не является администратором в этом чате"
        
        if not getattr(bot_member, 'can_delete_messages', False):
            logger.warning(f"У бота нет прав на удаление сообщений в чате {chat_id}")
            return False, "У бота нет прав на удаление сообщений"
        
        return True, "Бот имеет все необходимые права"
    except Exception as e:
        logger.error(f"Ошибка при проверке прав бота в чате {chat_id}: {e}")
        logger.error(traceback.format_exc())
        return False, f"Ошибка при проверке прав бота: {str(e)}"

# Обработчик команды /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    logger.info(f"Команда /start от пользователя {user_id} в чате {chat_id}")
    
    # Проверяем права бота в группе
    if update.effective_chat.type != 'private':
        has_permissions, message = await check_bot_permissions(context, chat_id)
        if not has_permissions:
            await update.message.reply_text(
                f"⚠️ {message}\n\n"
                f"Для корректной работы бота необходимо:\n"
                f"1. Добавить бота как администратора группы\n"
                f"2. Предоставить боту право удалять сообщения"
            )
            return
    
    await update.message.reply_text(
        'Привет! Я бот для удаления сообщений со стоп-словами.\n\n'
        'Доступные команды:\n'
        '/add_word <слово> - добавить стоп-слово (только для администраторов)\n'
        '/remove_word <слово> - удалить стоп-слово (только для администраторов)\n'
        '/list_words - показать список стоп-слов\n'
        '/check_permissions - проверить права бота в группе\n'
        '/help - показать справку'
    )

# Обработчик команды /help
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    logger.info(f"Команда /help от пользователя {user_id} в чате {chat_id}")
    
    await update.message.reply_text(
        'Доступные команды:\n'
        '/add_word <слово> - добавить стоп-слово (только для администраторов)\n'
        '/remove_word <слово> - удалить стоп-слово (только для администраторов)\n'
        '/list_words - показать список стоп-слов\n'
        '/check_permissions - проверить права бота в группе\n'
        '/help - показать справку'
    )

# Обработчик команды /check_permissions
async def check_permissions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    logger.info(f"Команда /check_permissions от пользователя {user_id} в чате {chat_id}")
    
    if update.effective_chat.type == 'private':
        await update.message.reply_text('Эта команда работает только в группах.')
        return
    
    has_permissions, message = await check_bot_permissions(context, chat_id)
    
    if has_permissions:
        await update.message.reply_text(f"✅ {message}\n\nБот готов к работе в этой группе!")
    else:
        await update.message.reply_text(
            f"⚠️ {message}\n\n"
            f"Для корректной работы бота необходимо:\n"
            f"1. Добавить бота как администратора группы\n"
            f"2. Предоставить боту право удалять сообщения"
        )

# Обработчик команды /add_word
async def add_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    logger.info(f"Команда /add_word от пользователя {user_id} в чате {chat_id}")
    
    # Проверяем, является ли пользователь администратором
    if not await is_admin(update, context):
        await update.message.reply_text('Только администраторы могут добавлять стоп-слова.')
        return
    
    # Проверяем права бота в группе
    if update.effective_chat.type != 'private':
        has_permissions, message = await check_bot_permissions(context, chat_id)
        if not has_permissions:
            await update.message.reply_text(f"⚠️ {message}\nНевозможно добавить стоп-слово.")
            return
    
    # Проверяем, есть ли аргументы команды
    if not context.args:
        await update.message.reply_text('Пожалуйста, укажите слово для добавления. Пример: /add_word плохоеслово')
        return

    word = context.args[0].lower()
    stopwords = await load_stopwords(chat_id)
    
    # Проверяем, есть ли уже такое слово в списке
    if word in stopwords:
        await update.message.reply_text(f'Слово "{word}" уже есть в списке стоп-слов.')
        return
    
    # Добавляем слово в список и сохраняем
    stopwords.append(word)
    await save_stopwords(chat_id, stopwords)
    await update.message.reply_text(f'Слово "{word}" добавлено в список стоп-слов.')

# Обработчик команды /remove_word
async def remove_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    logger.info(f"Команда /remove_word от пользователя {user_id} в чате {chat_id}")
    
    # Проверяем, является ли пользователь администратором
    if not await is_admin(update, context):
        await update.message.reply_text('Только администраторы могут удалять стоп-слова.')
        return
    
    # Проверяем, есть ли аргументы команды
    if not context.args:
        await update.message.reply_text('Пожалуйста, укажите слово для удаления. Пример: /remove_word плохоеслово')
        return

    word = context.args[0].lower()
    stopwords = await load_stopwords(chat_id)
    
    # Проверяем, есть ли такое слово в списке
    if word not in stopwords:
        await update.message.reply_text(f'Слово "{word}" не найдено в списке стоп-слов.')
        return
    
    # Удаляем слово из списка и сохраняем
    stopwords.remove(word)
    await save_stopwords(chat_id, stopwords)
    await update.message.reply_text(f'Слово "{word}" удалено из списка стоп-слов.')

# Обработчик команды /list_words
async def list_words(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    logger.info(f"Команда /list_words от пользователя {user_id} в чате {chat_id}")
    
    stopwords = await load_stopwords(chat_id)
    
    if not stopwords:
        await update.message.reply_text('Список стоп-слов пуст.')
        return
    
    # Формируем сообщение со списком стоп-слов
    words_list = '\n'.join([f'• {word}' for word in stopwords])
    await update.message.reply_text(f'Список стоп-слов для этого чата:\n{words_list}')

# Функция для безопасного удаления сообщения с обработкой ошибок
async def safe_delete_message(context, chat_id, message_id):
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
        logger.info(f"Сообщение {message_id} в чате {chat_id} успешно удалено")
        return True
    except TelegramError as e:
        error_str = str(e)
        if "message to delete not found" in error_str.lower():
            logger.warning(f"Сообщение {message_id} в чате {chat_id} не найдено для удаления (возможно, уже удалено)")
        elif "message can't be deleted" in error_str.lower():
            logger.warning(f"Сообщение {message_id} в чате {chat_id} не может быть удалено")
        else:
            logger.error(f"Ошибка при удалении сообщения {message_id} в чате {chat_id}: {e}")
            logger.error(traceback.format_exc())
        return False
    except Exception as e:
        logger.error(f"Неизвестная ошибка при удалении сообщения {message_id} в чате {chat_id}: {e}")
        logger.error(traceback.format_exc())
        return False

# Обработчик всех сообщений
async def check_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Проверяем, есть ли сообщение
    if not update.message or not update.message.text:
        return
    
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    message_id = update.message.message_id
    message_text = update.message.text
    
    # Проверяем, не обрабатывали ли мы уже это сообщение
    message_key = f"{chat_id}_{message_id}"
    if message_key in processed_messages:
        logger.info(f"Сообщение {message_id} в чате {chat_id} уже было обработано, пропускаем")
        return
    
    # Добавляем сообщение в кэш обработанных
    processed_messages.add(message_key)
    
    # Ограничиваем размер кэша
    if len(processed_messages) > MAX_CACHE_SIZE:
        # Удаляем старые записи
        processed_messages.clear()
        processed_messages.add(message_key)
    
    logger.info(f"Получено сообщение {message_id} от пользователя {user_id} в чате {chat_id}: {message_text[:20]}...")
    
    # Не проверяем сообщения от администраторов (опционально)
    # if await is_admin(update, context):
    #     logger.info(f"Пользователь {user_id} является администратором, пропускаем проверку")
    #     return
    
    # Проверяем права бота в группе (только для групповых чатов)
    if update.effective_chat.type != 'private':
        has_permissions, message = await check_bot_permissions(context, chat_id)
        if not has_permissions:
            logger.warning(f"Бот не имеет необходимых прав в чате {chat_id}: {message}")
            # Не отправляем сообщение об ошибке при каждом сообщении, чтобы не спамить
            return
    
    # Загружаем список стоп-слов для текущего чата
    stopwords = await load_stopwords(chat_id)
    
    # Если список пуст, не проверяем сообщение
    if not stopwords:
        logger.info(f"Список стоп-слов для чата {chat_id} пуст, пропускаем проверку")
        return
    
    # Проверяем, содержит ли сообщение стоп-слова
    message_text_lower = message_text.lower()
    for word in stopwords:
        if word in message_text_lower:
            logger.info(f"Обнаружено стоп-слово '{word}' в сообщении {message_id} от пользователя {user_id} в чате {chat_id}")
            
            # Небольшая задержка перед удалением для обеспечения доставки сообщения
            time.sleep(0.5)
            
            # Если сообщение содержит стоп-слово, удаляем его
            success = await safe_delete_message(context, chat_id, message_id)
            
            if success:
                logger.info(f"Сообщение {message_id} со стоп-словом '{word}' от пользователя {user_id} в чате {chat_id} успешно удалено")
                # Отправляем уведомление пользователю (опционально)
                # await context.bot.send_message(
                #     chat_id=update.effective_chat.id,
                #     text=f"Сообщение от {update.message.from_user.first_name} было удалено, так как содержало стоп-слово."
                # )
            else:
                logger.warning(f"Не удалось удалить сообщение {message_id} со стоп-словом '{word}' в чате {chat_id}")
            
            break

# Функция для обработки ошибок
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f"Произошла ошибка: {context.error}")
    logger.error(traceback.format_exc())
    
    # Отправляем сообщение об ошибке (опционально)
    if update and isinstance(update, Update) and update.effective_chat:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"Произошла ошибка при обработке запроса: {context.error}"
        )

def main():
    # Вставьте ваш токен здесь
    TOKEN = "7339416015:AAFSDeUI_3cFsDtT-j_iwwaqooESx6VmNtE"
    
    logger.info("Запуск бота...")
    logger.info(f"Python версия: {sys.version}")
    logger.info(f"Рабочая директория: {os.getcwd()}")
    logger.info(f"Директория для стоп-слов: {os.path.abspath(STOPWORDS_DIR)}")
    
    try:
        # Создаем приложение с увеличенным таймаутом для PythonAnywhere
        application = Application.builder().token(TOKEN).connect_timeout(30).read_timeout(30).build()
        
        # Добавляем обработчики команд
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("add_word", add_word))
        application.add_handler(CommandHandler("remove_word", remove_word))
        application.add_handler(CommandHandler("list_words", list_words))
        application.add_handler(CommandHandler("check_permissions", check_permissions))
        
        # Добавляем обработчик всех сообщений
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, check_message))
        
        # Добавляем обработчик ошибок
        application.add_error_handler(error_handler)
        
        # Запускаем бота
        logger.info("Бот запущен и готов к работе")
        application.run_polling(allowed_updates=["message", "edited_message", "channel_post", "edited_channel_post"])
        
    except Exception as e:
        logger.error(f"Критическая ошибка при запуске бота: {e}")
        logger.error(traceback.format_exc())

if __name__ == '__main__':
    main()
