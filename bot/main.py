import asyncio
from aiogram import Bot, Dispatcher
from bot_config import settings
import start

async def main():
    bot = Bot(token=settings.bot_token)
    dp = Dispatcher()
    dp.include_router(start.router)

    print("🤖 Bot ishga tushdi...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
