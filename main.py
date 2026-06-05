import os
import asyncio
import logging
import http.server
import threading
from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.tl.types import InputMediaPhoto, InputMediaDocument
import google.generativeai as genai

# Налаштування логування
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

load_dotenv()

# Завантажуємо змінні оточення
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_KEY")
TARGET_CHANNEL = "@aiworldgptnews"

# Список каналів-доноров (6 штук). Заміни юзернейми на ті, які тобі треба!
DONOR_CHANNELS = [
    "gpt_news", 
    "strangedalle", 
    "tech_donor_2", 
    "tech_donor_3", 
    "tech_donor_4", 
    "tech_donor_5"
]

# Налаштування Gemini
genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel(
    model_name="gemini-2.5-flash",
    system_instruction=(
        "Ти — топовий, цинічний і хайповий автор крупного Telegram-каналу про штучний інтелект и технології. "
        "Твій стиль — жорстка іронія, меми, щільний текст без води, короткі речення і подача 'для своїх'. "
        "ГЛАВНОЕ ПРАВИЛО: Делай рерайт СТРОГО на основе фактов, цифр и сути из входящего текста! "
        "Тебе запрещено выдумывать абстрактную чушь, которой нет в новости. "
        "ТЕХНИЧЕСКИЕ ОГРАНИЧЕНИЯ: Категорически запрещено использовать маркдаун-разметку! "
        "Никаких звездочек (** или *), никаких нижних подчеркиваний (_) и HTML-тегов. "
        "Текст должен быть абсолютно чистым, иначе Telegram выдаст ошибку."
    )
)

# Клієнт для Юзер-бота (Турецький акаунт)
user_client = TelegramClient('user_session', API_ID, API_HASH)
# Клієнт для Бот-публікатора
bot_client = TelegramClient('bot_session', API_ID, API_HASH)

# Сховище для збору медіагруп (альбомів)
media_groups = {}
processed_posts = set()

# Завантаження бази вже оброблених постів
if os.path.exists("processed_posts.txt"):
    with open("processed_posts.txt", "r") as f:
        processed_posts = set(f.read().splitlines())

def save_processed_post(post_id):
    processed_posts.add(str(post_id))
    with open("processed_posts.txt", "a") as f:
        f.write(f"{post_id}\n")

async def process_media_group(mg_id):
    """Обробка накопиченого альбому після невеликої паузи"""
    await asyncio.sleep(2.5) # Чекаємо 2.5 секунди, поки долетять усі шматочки альбому
    if mg_id not in media_groups:
        return

    items = media_groups.pop(mg_id)
    first_item = items[0]
    raw_text = first_item['text']
    channel_id = first_item['channel_id']
    msg_id = first_item['msg_id']
    
    unique_key = f"{channel_id}_{msg_id}"
    if unique_key in processed_posts:
        return
    save_processed_post(unique_key)

    logging.info(f"Обробка альбому {mg_id} з каналу {channel_id}")

    # Рерайт через Gemini
    rewritten_text = raw_text
    if raw_text:
        try:
            response = model.generate_content(raw_text)
            rewritten_text = response.text
        except Exception as e:
            logging.error(f"Помилка Gemini: {e}")

    # Збираємо файли для відправки
    media_files = []
    for it in items:
        if it['file']:
            media_files.append(it['file'])

    try:
        if media_files:
            # Телеграм бот відправляє альбом
            await bot_client.send_file(TARGET_CHANNEL, media_files, caption=rewritten_text)
        elif rewritten_text:
            await bot_client.send_message(TARGET_CHANNEL, rewritten_text)
        logging.info("Пост успішно опубліковано!")
    except Exception as e:
        logging.error(f"Помилка публікації: {e}")

@user_client.on(events.NewMessage(chats=DONOR_CHANNELS))
async def handler(event):
    msg = event.message
    
    # Якщо це частина альбому
    if msg.media_group_id:
        mg_id = msg.media_group_id
        if mg_id not in media_groups:
            media_groups[mg_id] = []
            asyncio.create_task(process_media_group(mg_id))
        
        media_groups[mg_id].append({
            'text': msg.text if msg.text else "",
            'file': msg.media if msg.media else None,
            'channel_id': event.chat_id,
            'msg_id': msg.id
        })
        # Якщо в першому повідомленні альбому немає тексту, але він прийшов в іншому — зліплюємо
        if msg.text and not media_groups[mg_id][0]['text']:
            media_groups[mg_id][0]['text'] = msg.text
    else:
        # Якщо це звичайний одиночний пост (1 фото/відео або просто текст)
        unique_key = f"{event.chat_id}_{msg.id}"
        if unique_key in processed_posts:
            return
        save_processed_post(unique_key)

        logging.info(f"Обробка одиночного поста з каналу {event.chat_id}")

        rewritten_text = msg.text
        if msg.text:
            try:
                response = model.generate_content(msg.text)
                rewritten_text = response.text
            except Exception as e:
                logging.error(f"Помилка Gemini: {e}")

        try:
            if msg.media:
                await bot_client.send_file(TARGET_CHANNEL, msg.media, caption=rewritten_text)
            elif rewritten_text:
                await bot_client.send_message(TARGET_CHANNEL, rewritten_text)
            logging.info("Одиночний пост успішно опубліковано!")
        except Exception as e:
            logging.error(f"Помилка публікації: {e}")

def run_fake_server():
    """Фейковий сервер для обману Render, щоб він бачив відкритий порт"""
    server_address = ('', int(os.getenv("PORT", 10000)))
    httpd = http.server.HTTPServer(server_address, http.server.SimpleHTTPRequestHandler)
    logging.info(f"Фейковий веб-сервер запущено на порту {server_address[1]}")
    httpd.serve_forever()

async def main():
    # Запуск фейкового сервера в окремому потоці, щоб не заважав боту
    threading.Thread(target=run_fake_server, daemon=True).start()

    # Запуск обох клієнтів
    await user_client.start()
    await bot_client.start(bot_token=BOT_TOKEN)
    logging.info("Скрипт запущений і слухає канали...")
    await user_client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
if __name__ == '__main__':
    asyncio.run(main())
