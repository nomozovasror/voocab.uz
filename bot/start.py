from aiogram import Router
from aiogram.types import Message

router = Router()

@router.message()
async def start_handler(message: Message):
    await message.answer("👋 Salom! VocabBot ishga tushdi.")
