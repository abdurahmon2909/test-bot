from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import time
from datetime import datetime
from html import escape
from typing import Any

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN topilmadi. Railway Variables ga BOT_TOKEN qo'shing.")

TEST_DURATION_SECONDS = 90 * 60  # 1 soat 30 daqiqa

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher(storage=MemoryStorage())

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
QUESTIONS_FILE = os.path.join(DATA_DIR, "questions.json")
USERS_FILE = os.path.join(DATA_DIR, "users.json")


class TestState(StatesGroup):
    testing = State()


def ensure_data_dir() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)


def safe_read_json(path: str, default: Any) -> Any:
    ensure_data_dir()

    if not os.path.exists(path):
        return default

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        logging.exception("JSON format xato: %s", path)
        return default
    except Exception:
        logging.exception("Faylni o'qishda xato: %s", path)
        return default


def safe_write_json(path: str, data: Any) -> None:
    ensure_data_dir()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        logging.exception("Faylga yozishda xato: %s", path)


def normalize_questions(data: dict) -> dict[str, list[dict]]:
    if not isinstance(data, dict):
        return {
            "ingliz_tili": [],
            "kasbiy_standart": [],
            "ped_mahorat": [],
        }

    return {
        "ingliz_tili": data.get("ingliz_tili", []) if isinstance(data.get("ingliz_tili", []), list) else [],
        "kasbiy_standart": data.get("kasbiy_standart", []) if isinstance(data.get("kasbiy_standart", []), list) else [],
        "ped_mahorat": data.get("ped_mahorat", []) if isinstance(data.get("ped_mahorat", []), list) else [],
    }


def load_questions() -> dict[str, list[dict]]:
    raw = safe_read_json(
        QUESTIONS_FILE,
        {
            "ingliz_tili": [],
            "kasbiy_standart": [],
            "ped_mahorat": [],
        }
    )
    return normalize_questions(raw)


def load_users() -> dict:
    data = safe_read_json(USERS_FILE, {})
    return data if isinstance(data, dict) else {}


def save_users(data: dict) -> None:
    safe_write_json(USERS_FILE, data)


def validate_question(q: dict) -> bool:
    return (
        isinstance(q, dict)
        and "text" in q
        and "options" in q
        and "correct" in q
        and isinstance(q["options"], list)
        and len(q["options"]) == 4
        and isinstance(q["correct"], int)
        and 0 <= q["correct"] <= 3
    )


def get_all_questions() -> list[dict]:
    questions = load_questions()

    english_source = [q for q in questions.get("ingliz_tili", []) if validate_question(q)]
    kasbiy_source = [q for q in questions.get("kasbiy_standart", []) if validate_question(q)]
    ped_source = [q for q in questions.get("ped_mahorat", []) if validate_question(q)]

    if len(english_source) < 35 or len(kasbiy_source) < 5 or len(ped_source) < 10:
        return []

    english = random.sample(english_source, 35)
    kasbiy = random.sample(kasbiy_source, 5)
    ped = random.sample(ped_source, 10)

    random.shuffle(english)
    random.shuffle(kasbiy)
    random.shuffle(ped)

    all_questions = english + kasbiy + ped

    for q in all_questions:
        q.setdefault("hint", "Izoh mavjud emas.")

    return all_questions


def format_seconds(seconds: int) -> str:
    if seconds < 0:
        seconds = 0
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02}:{minutes:02}:{secs:02}"


def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📝 Testni boshlash", callback_data="start_test")],
            [InlineKeyboardButton(text="📊 Natijalarim", callback_data="my_results")],
            [InlineKeyboardButton(text="🏆 Reyting", callback_data="rating")],
        ]
    )


def get_question_keyboard(question: dict, total: int, current_index: int, answers: list[dict]) -> InlineKeyboardMarkup:
    selected_answer = None
    if current_index < len(answers):
        selected_answer = answers[current_index].get("selected")

    option_rows = []
    for i, option in enumerate(question["options"]):
        prefix = "✅ " if selected_answer == i else ""
        option_rows.append([
            InlineKeyboardButton(
                text=f"{prefix}{chr(65 + i)}) {option}",
                callback_data=f"ans_{i}"
            )
        ])

    nav_buttons = []
    if current_index > 0:
        nav_buttons.append(InlineKeyboardButton(text="◀️ Orqaga", callback_data="nav_prev"))

    nav_buttons.append(
        InlineKeyboardButton(text=f"{current_index + 1}/{total}", callback_data="noop")
    )

    if current_index < total - 1:
        nav_buttons.append(InlineKeyboardButton(text="Keyingi ▶️", callback_data="nav_next"))

    return InlineKeyboardMarkup(
        inline_keyboard=[
            *option_rows,
            nav_buttons,
            [InlineKeyboardButton(text="❌ Testni tugatish", callback_data="finish_test_early")]
        ]
    )


def get_results_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🏠 Bosh menyu", callback_data="main_menu")]
        ]
    )


def short_text(value: str, limit: int) -> str:
    value = str(value)
    return value if len(value) <= limit else value[:limit] + "..."


def build_question_text(question: dict, total: int, current_index: int, remaining_seconds: int) -> str:
    text = escape(str(question.get("text", "")))
    time_text = format_seconds(remaining_seconds)

    return (
        f"⏳ <b>Qolgan vaqt:</b> {time_text}\n\n"
        f"📚 <b>Savol {current_index + 1} / {total}</b>\n\n"
        f"{text}\n\n"
        f"👇 <i>Javob variantini tanlang:</i>"
    )


async def is_time_over(state: FSMContext) -> bool:
    data = await state.get_data()
    end_time = data.get("end_time")

    if end_time is None:
        return False

    return time.time() >= float(end_time)


async def get_remaining_seconds(state: FSMContext) -> int:
    data = await state.get_data()
    end_time = data.get("end_time")

    if end_time is None:
        return TEST_DURATION_SECONDS

    return max(0, int(float(end_time) - time.time()))


async def show_question(target_message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    questions: list[dict] = data.get("questions", [])
    current_index: int = data.get("current_index", 0)
    answers: list[dict] = data.get("answers", [])
    message_id = data.get("message_id")

    if await is_time_over(state):
        await finish_test(target_message, state, time_over=True)
        return

    if not questions:
        await target_message.answer("⚠️ Savollar topilmadi yoki questions.json bo'sh.")
        await state.clear()
        return

    if current_index < 0:
        current_index = 0
        await state.update_data(current_index=0)

    if current_index >= len(questions):
        await finish_test(target_message, state)
        return

    remaining_seconds = await get_remaining_seconds(state)
    question = questions[current_index]
    question_text = build_question_text(question, len(questions), current_index, remaining_seconds)
    reply_markup = get_question_keyboard(question, len(questions), current_index, answers)

    if message_id:
        try:
            await target_message.bot.edit_message_text(
                chat_id=target_message.chat.id,
                message_id=message_id,
                text=question_text,
                reply_markup=reply_markup,
            )
            return
        except Exception:
            logging.exception("Savol xabarini edit qilishda xato, yangi xabar yuboriladi.")

    msg = await target_message.answer(question_text, reply_markup=reply_markup)
    await state.update_data(message_id=msg.message_id)


async def finish_test(
    target_message: Message,
    state: FSMContext,
    time_over: bool = False,
    finished_early: bool = False,
) -> None:
    data = await state.get_data()
    answers: list[dict] = data.get("answers", [])

    total = len(answers)
    correct_count = sum(1 for a in answers if a.get("correct") is True)
    score_percent = int((correct_count / total) * 100) if total > 0 else 0

    user = target_message.from_user
    user_id = str(user.id) if user else str(target_message.chat.id)
    username = "Foydalanuvchi"

    if user:
        username = user.username if user.username else user.full_name

    users = load_users()
    users.setdefault(user_id, {"username": username, "tests": []})
    users[user_id]["username"] = username
    users[user_id]["tests"].append(
        {
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "score": correct_count,
            "total": total,
            "answers": answers,
            "time_over": time_over,
            "finished_early": finished_early,
        }
    )
    save_users(users)

    header = ""
    if time_over:
        header = "⛔ <b>VAQT TUGADI!</b>\n\n"
    elif finished_early:
        header = "✅ <b>TEST FOYDALANUVCHI TOMONIDAN TUGATILDI!</b>\n\n"

    result_text = (
        f"{header}"
        f"🏁 <b>TEST YAKUNLANDI!</b> 🏁\n\n"
        f"📊 <b>Sizning ballingiz:</b> {correct_count} / {total} ({score_percent}%)\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📋 <b>SAVOL TAHLILI:</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )

    for i, ans in enumerate(answers, start=1):
        question = ans.get("question", {})
        is_correct = ans.get("correct", False)

        status = "✅" if is_correct else "❌"
        question_text_short = escape(short_text(question.get("text", ""), 50))
        result_text += f"{status} <b>{i}. {question_text_short}</b>\n"

        if not is_correct:
            user_ans_short = escape(short_text(ans.get("user_answer_text", ""), 40))
            correct_ans_short = escape(short_text(ans.get("correct_answer_text", ""), 40))
            hint = escape(question.get("hint", "Izoh mavjud emas."))
            result_text += f"   Siz: {user_ans_short}\n"
            result_text += f"   ✓ To'g'ri: {correct_ans_short}\n"
            result_text += f"   💡 <b>Hint:</b> {hint}\n\n"
        else:
            result_text += "   ✓ To'g'ri\n\n"

        if len(result_text) > 3800:
            result_text += "\n... va boshqa savollar. Batafsil natijalarni /natijalarim orqali ko'ring.\n"
            break

    result_text += (
        "\n━━━━━━━━━━━━━━━━━━━━━━\n"
        "📌 /natijalarim - barcha natijalaringiz\n"
        "🏆 /reyting - umumiy reyting\n"
    )

    message_id = data.get("message_id")
    if message_id:
        try:
            await target_message.bot.edit_message_text(
                chat_id=target_message.chat.id,
                message_id=message_id,
                text=result_text,
                reply_markup=get_results_keyboard(),
            )
        except Exception:
            logging.exception("Natijani edit qilishda xato, yangi xabar yuboriladi.")
            await target_message.answer(result_text, reply_markup=get_results_keyboard())
    else:
        await target_message.answer(result_text, reply_markup=get_results_keyboard())

    await state.clear()


@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()

    welcome_text = (
        "🏁 <b>Assalomu alaykum!</b>\n\n"
        "📚 Bu bot ingliz tili, kasbiy standart va pedagogik mahorat bo'yicha test topshirish uchun mo'ljallangan.\n\n"
        "📌 Test 50 ta savoldan iborat:\n"
        "• 35 ta ingliz tili\n"
        "• 5 ta kasbiy standart\n"
        "• 10 ta pedagogik mahorat\n\n"
        "⏳ Test uchun vaqt: <b>1 soat 30 daqiqa</b>\n\n"
        "✅ Test yakunida ball va xatolar bo'yicha izoh ko'rsatiladi.\n\n"
        "🎯 Quyidagi tugmalardan birini tanlang:"
    )

    await message.answer(welcome_text, reply_markup=get_main_menu_keyboard())


@dp.callback_query(F.data == "main_menu")
async def back_to_main_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()

    text = "🏠 <b>Asosiy menyu</b>\n\nKerakli bo'limni tanlang:"
    try:
        await callback.message.edit_text(text, reply_markup=get_main_menu_keyboard())
    except Exception:
        await callback.message.answer(text, reply_markup=get_main_menu_keyboard())

    await callback.answer()


@dp.callback_query(F.data == "start_test")
async def start_test(callback: CallbackQuery, state: FSMContext) -> None:
    questions = get_all_questions()

    if len(questions) < 50:
        await callback.answer(
            "⚠️ questions.json ichida yetarli savol yo'q. Ingliz 35, kasbiy 5, ped mahorat 10 ta bo'lishi kerak.",
            show_alert=True
        )
        return

    now_ts = time.time()

    await state.set_state(TestState.testing)
    await state.update_data(
        questions=questions,
        current_index=0,
        answers=[],
        total=len(questions),
        message_id=callback.message.message_id,
        start_time=now_ts,
        end_time=now_ts + TEST_DURATION_SECONDS,
    )

    await show_question(callback.message, state)
    await callback.answer()


@dp.callback_query(TestState.testing, F.data.startswith("ans_"))
async def handle_answer(callback: CallbackQuery, state: FSMContext) -> None:
    if await is_time_over(state):
        await finish_test(callback.message, state, time_over=True)
        await callback.answer("Vaqt tugadi.", show_alert=True)
        return

    data = await state.get_data()
    questions: list[dict] = data.get("questions", [])
    current_index: int = data.get("current_index", 0)
    answers: list[dict] = data.get("answers", [])

    if not questions or current_index >= len(questions):
        await callback.answer("Savol topilmadi.", show_alert=True)
        return

    selected = int(callback.data.split("_")[1])
    question = questions[current_index]
    is_correct = selected == question["correct"]

    answer_payload = {
        "selected": selected,
        "correct": is_correct,
        "question": question,
        "user_answer_text": question["options"][selected],
        "correct_answer_text": question["options"][question["correct"]],
    }

    if current_index < len(answers):
        answers[current_index] = answer_payload
    else:
        answers.append(answer_payload)

    next_index = current_index + 1

    await state.update_data(
        answers=answers,
        current_index=next_index,
    )

    if next_index >= len(questions):
        await finish_test(callback.message, state)
    else:
        await show_question(callback.message, state)

    await callback.answer()


@dp.callback_query(TestState.testing, F.data == "nav_prev")
async def nav_prev(callback: CallbackQuery, state: FSMContext) -> None:
    if await is_time_over(state):
        await finish_test(callback.message, state, time_over=True)
        await callback.answer("Vaqt tugadi.", show_alert=True)
        return

    data = await state.get_data()
    current_index: int = data.get("current_index", 0)

    if current_index > 0:
        await state.update_data(current_index=current_index - 1)
        await show_question(callback.message, state)

    await callback.answer()


@dp.callback_query(TestState.testing, F.data == "nav_next")
async def nav_next(callback: CallbackQuery, state: FSMContext) -> None:
    if await is_time_over(state):
        await finish_test(callback.message, state, time_over=True)
        await callback.answer("Vaqt tugadi.", show_alert=True)
        return

    data = await state.get_data()
    current_index: int = data.get("current_index", 0)
    total: int = data.get("total", 0)

    if current_index < total - 1:
        await state.update_data(current_index=current_index + 1)
        await show_question(callback.message, state)

    await callback.answer()


@dp.callback_query(TestState.testing, F.data == "finish_test_early")
async def finish_test_early(callback: CallbackQuery, state: FSMContext) -> None:
    await finish_test(callback.message, state, finished_early=True)
    await callback.answer("Test yakunlandi.", show_alert=False)


@dp.message(Command("natijalarim"))
async def my_results(message: Message) -> None:
    users = load_users()
    user_id = str(message.from_user.id)

    if user_id not in users or not users[user_id].get("tests"):
        await message.answer("📭 Siz hali test topshirmagansiz. /start orqali testni boshlang.")
        return

    user_data = users[user_id]
    username = escape(user_data.get("username", "Foydalanuvchi"))
    tests = user_data.get("tests", [])

    text = f"📊 <b>{username} ning natijalari</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n"

    recent_tests = tests[-5:]
    for i, test in enumerate(recent_tests, start=1):
        score = int(test.get("score", 0))
        total = int(test.get("total", 0))
        percent = int((score / total) * 100) if total > 0 else 0
        date_text = escape(str(test.get("date", "-")))

        status_note = ""
        if test.get("time_over"):
            status_note = " | vaqt tugagan"
        elif test.get("finished_early"):
            status_note = " | ertaroq tugatilgan"

        text += (
            f"{i}. {date_text}{status_note}\n"
            f"   Ball: {score} / {total} ({percent}%)\n\n"
        )

    await message.answer(text)


@dp.message(Command("reyting"))
async def rating(message: Message) -> None:
    users = load_users()

    if not users:
        await message.answer("📭 Hali hech kim test topshirmagan.")
        return

    rating_list = []
    for _, data in users.items():
        tests = data.get("tests", [])
        if tests:
            last_test = tests[-1]
            score = int(last_test.get("score", 0))
            total = int(last_test.get("total", 0))
            percent = int((score / total) * 100) if total > 0 else 0
            rating_list.append(
                (
                    str(data.get("username", "Foydalanuvchi")),
                    percent,
                    score,
                    total,
                )
            )

    if not rating_list:
        await message.answer("📭 Reyting uchun ma'lumot yo'q.")
        return

    rating_list.sort(key=lambda x: (x[1], x[2]), reverse=True)

    text = "🏆 <b>REYTING</b> (oxirgi test natijasi bo'yicha)\n━━━━━━━━━━━━━━━━━━━━━━\n\n"

    for i, (name, percent, score, total) in enumerate(rating_list[:10], start=1):
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        text += f"{medal} {escape(name)}: {score}/{total} ({percent}%)\n"

    await message.answer(text)


@dp.callback_query(F.data == "my_results")
async def callback_my_results(callback: CallbackQuery) -> None:
    await my_results(callback.message)
    await callback.answer()


@dp.callback_query(F.data == "rating")
async def callback_rating(callback: CallbackQuery) -> None:
    await rating(callback.message)
    await callback.answer()


@dp.callback_query(F.data == "noop")
async def noop(callback: CallbackQuery) -> None:
    await callback.answer()


async def main() -> None:
    logging.info("Bot ishga tushdi...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())