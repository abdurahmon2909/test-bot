from __future__ import annotations

import asyncio
import copy
import json
import logging
import math
import os
import random
import time
import uuid
from datetime import datetime
from html import escape
from typing import Any

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN topilmadi. Railway Variables ga BOT_TOKEN qo'shing.")

TEST_DURATION_SECONDS = 90 * 60
TOTAL_SCORE_POINTS = 100
POINTS_PER_CORRECT = 2
QUESTIONS_PER_PAGE = 10

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

TIMER_TASKS: dict[str, asyncio.Task] = {}
EDIT_LOCKS: dict[str, asyncio.Lock] = {}


class TestState(StatesGroup):
    testing = State()


def get_user_lock(user_id: str) -> asyncio.Lock:
    if user_id not in EDIT_LOCKS:
        EDIT_LOCKS[user_id] = asyncio.Lock()
    return EDIT_LOCKS[user_id]


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


def shuffle_question_options(question: dict) -> dict:
    q = copy.deepcopy(question)
    original_options = q["options"]
    original_correct_index = q["correct"]

    option_pairs = []
    for idx, option_text in enumerate(original_options):
        option_pairs.append(
            {
                "text": option_text,
                "is_correct": idx == original_correct_index,
            }
        )

    random.shuffle(option_pairs)

    q["options"] = [item["text"] for item in option_pairs]
    q["correct"] = next(i for i, item in enumerate(option_pairs) if item["is_correct"])
    q.setdefault("hint", "Izoh mavjud emas.")
    return q


def prepare_question_set(source_questions: list[dict], sample_count: int) -> list[dict]:
    sampled = random.sample(source_questions, sample_count)
    shuffled_questions = [shuffle_question_options(q) for q in sampled]
    random.shuffle(shuffled_questions)
    return shuffled_questions


def get_all_questions() -> list[dict]:
    questions = load_questions()

    english_source = [q for q in questions.get("ingliz_tili", []) if validate_question(q)]
    kasbiy_source = [q for q in questions.get("kasbiy_standart", []) if validate_question(q)]
    ped_source = [q for q in questions.get("ped_mahorat", []) if validate_question(q)]

    if len(english_source) < 35 or len(kasbiy_source) < 5 or len(ped_source) < 10:
        return []

    english = prepare_question_set(english_source, 35)
    kasbiy = prepare_question_set(kasbiy_source, 5)
    ped = prepare_question_set(ped_source, 10)

    return english + kasbiy + ped


def format_seconds(seconds: int) -> str:
    if seconds < 0:
        seconds = 0
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02}:{minutes:02}:{secs:02}"


def get_display_name_from_user_obj(user) -> str:
    if not user:
        return "Foydalanuvchi"

    username = getattr(user, "username", None)
    full_name = getattr(user, "full_name", None)
    first_name = getattr(user, "first_name", None)

    return username or full_name or first_name or "Foydalanuvchi"


def get_display_name_from_saved(data: dict) -> str:
    username = str(data.get("username", "")).strip()
    full_name = str(data.get("full_name", "")).strip()
    first_name = str(data.get("first_name", "")).strip()

    if username:
        return username
    if full_name:
        return full_name
    if first_name:
        return first_name
    return "Foydalanuvchi"


def upsert_user_profile(user) -> None:
    if not user:
        return

    users = load_users()
    user_id = str(user.id)

    users.setdefault(
        user_id,
        {
            "username": "",
            "full_name": "",
            "first_name": "",
            "tests": [],
        }
    )

    users[user_id]["username"] = getattr(user, "username", None) or users[user_id].get("username", "")
    users[user_id]["full_name"] = getattr(user, "full_name", None) or users[user_id].get("full_name", "")
    users[user_id]["first_name"] = getattr(user, "first_name", None) or users[user_id].get("first_name", "")

    save_users(users)


def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📝 Testni boshlash", callback_data="start_test")],
            [InlineKeyboardButton(text="📊 Natijalarim", callback_data="my_results")],
            [InlineKeyboardButton(text="🏆 Reyting", callback_data="rating")],
        ]
    )


def get_home_inline_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🏠 Bosh sahifa", callback_data="main_menu")]
        ]
    )


def build_grid_rows(
    total: int,
    current_index: int,
    answers_map: dict,
    visited: list[int],
    page: int,
) -> list[list[InlineKeyboardButton]]:
    rows: list[list[InlineKeyboardButton]] = []
    start = page * QUESTIONS_PER_PAGE
    end = min(start + QUESTIONS_PER_PAGE, total)

    current_row: list[InlineKeyboardButton] = []
    for i in range(start, end):
        key = str(i)
        answered = key in answers_map
        seen = i in visited

        if answered:
            prefix = "🟩"
        elif seen:
            prefix = "🟨"
        else:
            prefix = "⬜"

        if i == current_index:
            prefix = "🔹"

        current_row.append(
            InlineKeyboardButton(
                text=f"{prefix}{i + 1}",
                callback_data=f"goto_{i}"
            )
        )

        if len(current_row) == 5:
            rows.append(current_row)
            current_row = []

    if current_row:
        rows.append(current_row)

    return rows


def get_question_keyboard(
    question: dict,
    total: int,
    current_index: int,
    answers_map: dict,
    visited: list[int],
    page: int,
) -> InlineKeyboardMarkup:
    selected_answer = None
    answer_data = answers_map.get(str(current_index))
    if answer_data:
        selected_answer = answer_data.get("selected")

    option_rows = []
    for i, option in enumerate(question["options"]):
        prefix = "✅ " if selected_answer == i else ""
        option_rows.append(
            [InlineKeyboardButton(text=f"{prefix}{chr(65 + i)}) {option}", callback_data=f"ans_{i}")]
        )

    total_pages = math.ceil(total / QUESTIONS_PER_PAGE)
    grid_rows = build_grid_rows(total, current_index, answers_map, visited, page)

    page_nav = []
    if page > 0:
        page_nav.append(InlineKeyboardButton(text="⬅️ Sahifa", callback_data=f"gridpage_{page - 1}"))
    page_nav.append(InlineKeyboardButton(text=f"📋 {page + 1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        page_nav.append(InlineKeyboardButton(text="Sahifa ➡️", callback_data=f"gridpage_{page + 1}"))

    question_nav = []
    if current_index > 0:
        question_nav.append(InlineKeyboardButton(text="◀️ Orqaga", callback_data="nav_prev"))
    question_nav.append(InlineKeyboardButton(text=f"{current_index + 1}/{total}", callback_data="noop"))
    if current_index < total - 1:
        question_nav.append(InlineKeyboardButton(text="Keyingi ▶️", callback_data="nav_next"))

    inline_keyboard = []
    inline_keyboard.extend(option_rows)
    inline_keyboard.extend(grid_rows)
    inline_keyboard.append(page_nav)
    inline_keyboard.append(question_nav)
    inline_keyboard.append([InlineKeyboardButton(text="❌ Testni tugatish", callback_data="finish_test_early")])

    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


def get_result_grid_keyboard(test_index: int, test: dict) -> InlineKeyboardMarkup:
    answers = test.get("answers", [])

    rows: list[list[InlineKeyboardButton]] = []
    current_row: list[InlineKeyboardButton] = []

    for i, ans in enumerate(answers):
        is_correct = bool(ans.get("correct"))
        prefix = "🟩" if is_correct else "🟥"

        current_row.append(
            InlineKeyboardButton(
                text=f"{prefix}{i + 1}",
                callback_data=f"result_q_{test_index}_{i}"
            )
        )

        if len(current_row) == 5:
            rows.append(current_row)
            current_row = []

    if current_row:
        rows.append(current_row)

    rows.append([InlineKeyboardButton(text="🏠 Bosh sahifa", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_result_question_keyboard(test_index: int, total_questions: int, index: int) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []

    nav_row = []
    if index > 0:
        nav_row.append(InlineKeyboardButton(text="◀️ Oldingi", callback_data=f"result_q_{test_index}_{index - 1}"))
    nav_row.append(InlineKeyboardButton(text=f"{index + 1}/{total_questions}", callback_data="noop"))
    if index < total_questions - 1:
        nav_row.append(InlineKeyboardButton(text="Keyingi ▶️", callback_data=f"result_q_{test_index}_{index + 1}"))

    buttons.append(nav_row)
    buttons.append([InlineKeyboardButton(text="📋 Yakuniy natijaga qaytish", callback_data=f"result_summary_{test_index}")])
    buttons.append([InlineKeyboardButton(text="🏠 Bosh sahifa", callback_data="main_menu")])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def build_question_text(
    question: dict,
    total: int,
    current_index: int,
    remaining_seconds: int,
) -> str:
    text = escape(str(question.get("text", "")))
    time_text = format_seconds(remaining_seconds)

    return (
        f"⏳ <b>Qolgan vaqt:</b> {time_text}\n"
        f"🟩 javob berilgan | 🟨 ko'rilgan, javobsiz | ⬜ ko'rilmagan\n\n"
        f"📚 <b>Savol {current_index + 1} / {total}</b>\n\n"
        f"{text}\n\n"
        f"👇 <i>Javob variantini tanlang:</i>"
    )


def get_category_text(score_points: int) -> str:
    if score_points > 86:
        return 'tabriklaymiz siz <b>"70% ustamani qo‘lga kiritdingiz"</b>'
    if score_points > 80:
        return 'tabriklaymiz siz <b>"Oliy toifa"</b> oldingiz!'
    if 70 <= score_points <= 79:
        return 'tabriklaymiz siz <b>"I toifa"</b> oldingiz!'
    if 60 <= score_points <= 69:
        return 'tabriklaymiz siz <b>"II toifa"</b> oldingiz!'
    return 'siz hali toifa olmadingiz.'


def build_result_summary_text(test: dict, display_name: str) -> str:
    score_points = int(test.get("score", 0))
    total = int(test.get("total", TOTAL_SCORE_POINTS))
    correct_answers = int(test.get("correct_answers", 0))
    questions_total = int(test.get("questions_total", 50))
    header = ""

    if test.get("time_over"):
        header = "⛔ <b>VAQT TUGADI!</b>\n\n"
    elif test.get("finished_early"):
        header = "✅ <b>TEST FOYDALANUVCHI TOMONIDAN TUGATILDI!</b>\n\n"

    category_text = get_category_text(score_points)

    return (
        f"{header}"
        f"🏁 <b>Test yakunlandi!</b>\n\n"
        f"👤 <b>Foydalanuvchi:</b> {escape(display_name)}\n"
        f"📊 <b>To‘plangan ball:</b> {score_points} / {total}\n"
        f"✅ <b>To‘g‘ri javoblar:</b> {correct_answers} / {questions_total}\n\n"
        f"🎉 {category_text}\n\n"
        f"Pastdagi 50 ta tugmadan birini bossangiz, o‘sha savolning tahlili chiqadi."
    )


def build_result_question_text(test: dict, display_name: str, index: int) -> str:
    answers = test.get("answers", [])
    total_questions = len(answers)

    if not (0 <= index < total_questions):
        return "Savol topilmadi."

    ans = answers[index]
    question = ans.get("question", {})
    options = question.get("options", [])
    selected = ans.get("selected")
    correct_answer_text = ans.get("correct_answer_text")

    correct_index = None
    for i, option in enumerate(options):
        if option == correct_answer_text:
            correct_index = i
            break

    lines = [
        f"👤 <b>Foydalanuvchi:</b> {escape(display_name)}",
        f"📚 <b>Savol {index + 1} / {total_questions}</b>",
        "",
        escape(str(question.get("text", ""))),
        "",
    ]

    for i, option in enumerate(options):
        prefix = "▫️"
        if selected is not None and i == selected:
            prefix = "👉"
        if correct_index is not None and i == correct_index:
            prefix = "✅"
        if selected is not None and i == selected and correct_index == selected:
            prefix = "✅"

        lines.append(f"{prefix} <b>{chr(65 + i)})</b> {escape(str(option))}")

    lines.append("")

    if ans.get("unanswered"):
        lines.append("❌ <b>Sizning javobingiz:</b> Javob berilmagan")
    elif selected is not None and 0 <= selected < len(options):
        lines.append(f"📝 <b>Siz tanlagan variant:</b> {escape(str(options[selected]))}")
    else:
        lines.append("📝 <b>Siz tanlagan variant:</b> Noma'lum")

    lines.append(f"✅ <b>To‘g‘ri javob:</b> {escape(str(correct_answer_text))}")
    lines.append(f"💡 <b>HINT:</b> {escape(str(question.get('hint', 'Izoh mavjud emas.')))}")

    return "\n".join(lines)


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


async def cancel_timer_task(user_id: str) -> None:
    task = TIMER_TASKS.pop(user_id, None)
    if task and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:
            logging.exception("Timer task cancel qilishda xato")


async def safe_edit_message(
    target_message: Message,
    state: FSMContext,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    data = await state.get_data()
    message_id = data.get("message_id")
    user_id = str(target_message.from_user.id if target_message.from_user else target_message.chat.id)
    lock = get_user_lock(user_id)

    async with lock:
        if message_id:
            try:
                await target_message.bot.edit_message_text(
                    chat_id=target_message.chat.id,
                    message_id=message_id,
                    text=text,
                    reply_markup=reply_markup,
                )
                return
            except TelegramBadRequest as e:
                if "message is not modified" in str(e).lower():
                    return
                if "message to edit not found" not in str(e).lower():
                    logging.exception("Xabarni edit qilishda TelegramBadRequest")
            except Exception:
                logging.exception("Xabarni edit qilishda xato")

        try:
            msg = await target_message.answer(text, reply_markup=reply_markup)
            await state.update_data(message_id=msg.message_id)
        except Exception:
            logging.exception("Yangi xabar yuborishda xato")


async def show_question(target_message: Message, state: FSMContext, force: bool = False) -> None:
    data = await state.get_data()
    questions: list[dict] = data.get("questions", [])
    current_index: int = data.get("current_index", 0)
    answers_map: dict = data.get("answers_map", {})
    visited: list[int] = data.get("visited", [])
    page: int = data.get("grid_page", 0)
    last_render_second_bucket = data.get("last_render_second_bucket")

    if await is_time_over(state):
        await finish_test(target_message, state, time_over=True)
        return

    if not questions:
        await safe_edit_message(target_message, state, "⚠️ Savollar topilmadi yoki questions.json bo'sh.")
        await state.clear()
        return

    if current_index < 0:
        current_index = 0

    if current_index >= len(questions):
        await finish_test(target_message, state)
        return

    if current_index not in visited:
        visited.append(current_index)

    total_pages = max(1, math.ceil(len(questions) / QUESTIONS_PER_PAGE))
    auto_page = current_index // QUESTIONS_PER_PAGE
    if page < 0 or page >= total_pages:
        page = auto_page

    remaining_seconds = await get_remaining_seconds(state)
    second_bucket = remaining_seconds // 10

    if (not force) and last_render_second_bucket == second_bucket:
        return

    question = questions[current_index]
    question_text = build_question_text(question, len(questions), current_index, remaining_seconds)
    reply_markup = get_question_keyboard(
        question=question,
        total=len(questions),
        current_index=current_index,
        answers_map=answers_map,
        visited=visited,
        page=page,
    )

    await state.update_data(
        visited=visited,
        grid_page=page,
        last_render_second_bucket=second_bucket,
    )
    await safe_edit_message(target_message, state, question_text, reply_markup=reply_markup)


async def timer_updater(target_message: Message, state: FSMContext, user_id: str, session_id: str) -> None:
    try:
        while True:
            await asyncio.sleep(1)

            current_state = await state.get_state()
            if current_state != TestState.testing.state:
                return

            data = await state.get_data()
            if data.get("session_id") != session_id:
                return

            if await is_time_over(state):
                await finish_test(target_message, state, time_over=True)
                return

            remaining_seconds = await get_remaining_seconds(state)
            if remaining_seconds % 10 == 0:
                await show_question(target_message, state, force=False)
    except asyncio.CancelledError:
        return
    except Exception:
        logging.exception("Timer updater xatoligi")
        try:
            await finish_test(target_message, state, time_over=True)
        except Exception:
            logging.exception("Timer xatosidan keyin testni yakunlashda ham xato")
    finally:
        if TIMER_TASKS.get(user_id) is asyncio.current_task():
            TIMER_TASKS.pop(user_id, None)


async def finish_test(
    target_message: Message,
    state: FSMContext,
    time_over: bool = False,
    finished_early: bool = False,
) -> None:
    data = await state.get_data()
    questions: list[dict] = data.get("questions", [])
    answers_map: dict = data.get("answers_map", {})

    total_questions = len(questions)
    correct_count = sum(
        1 for i in range(total_questions)
        if answers_map.get(str(i), {}).get("correct") is True
    )
    score_points = correct_count * POINTS_PER_CORRECT
    score_percent = int((correct_count / total_questions) * 100) if total_questions > 0 else 0

    user = target_message.from_user
    user_id = str(user.id) if user else str(target_message.chat.id)

    await cancel_timer_task(user_id)
    upsert_user_profile(user)

    users = load_users()
    display_name = get_display_name_from_saved(users.get(user_id, {}))

    serialized_answers = []
    for i, question in enumerate(questions):
        answer_data = answers_map.get(str(i))
        if answer_data:
            serialized_answers.append(answer_data)
        else:
            serialized_answers.append(
                {
                    "selected": None,
                    "correct": False,
                    "question": question,
                    "user_answer_text": "Javob berilmagan",
                    "correct_answer_text": question["options"][question["correct"]],
                    "unanswered": True,
                }
            )

    users.setdefault(user_id, {"username": "", "full_name": "", "first_name": "", "tests": []})
    users[user_id]["tests"].append(
        {
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "score": score_points,
            "total": TOTAL_SCORE_POINTS,
            "correct_answers": correct_count,
            "questions_total": total_questions,
            "percent": score_percent,
            "answers": serialized_answers,
            "time_over": time_over,
            "finished_early": finished_early,
        }
    )
    save_users(users)

    test_index = len(users[user_id]["tests"]) - 1
    latest_test = users[user_id]["tests"][test_index]

    result_text = build_result_summary_text(latest_test, display_name)
    result_keyboard = get_result_grid_keyboard(test_index, latest_test)

    await safe_edit_message(target_message, state, result_text, reply_markup=result_keyboard)
    await state.clear()


@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    user_id = str(message.from_user.id)
    await cancel_timer_task(user_id)
    upsert_user_profile(message.from_user)

    welcome_text = (
        "🏁 <b>Assalomu alaykum!</b>\n\n"
        "📚 Bu bot ingliz tili, kasbiy standart va pedagogik mahorat bo'yicha test topshirish uchun mo'ljallangan.\n\n"
        "📌 Test 50 ta savoldan iborat:\n"
        "• 35 ta ingliz tili\n"
        "• 5 ta kasbiy standart\n"
        "• 10 ta pedagogik mahorat\n\n"
        "💯 Baholash tizimi: <b>har bir to'g'ri javob = 2 ball</b>\n"
        "⏳ Test uchun vaqt: <b>1 soat 30 daqiqa</b>\n\n"
        "🎨 Grid belgilar:\n"
        "🟩 javob berilgan\n"
        "🟨 ko'rilgan, javobsiz\n"
        "⬜ ko'rilmagan\n\n"
        "🎯 Quyidagi tugmalardan birini tanlang:"
    )

    await message.answer(welcome_text, reply_markup=get_main_menu_keyboard())


@dp.callback_query(F.data == "main_menu")
async def back_to_main_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    user_id = str(callback.from_user.id)
    await cancel_timer_task(user_id)
    upsert_user_profile(callback.from_user)

    text = "🏠 <b>Bosh sahifa</b>\n\nKerakli bo'limni tanlang:"
    try:
        await callback.message.edit_text(text, reply_markup=get_main_menu_keyboard())
    except Exception:
        await callback.message.answer(text, reply_markup=get_main_menu_keyboard())

    await callback.answer()


@dp.callback_query(F.data == "start_test")
async def start_test(callback: CallbackQuery, state: FSMContext) -> None:
    upsert_user_profile(callback.from_user)
    questions = get_all_questions()

    if len(questions) < 50:
        await callback.answer(
            "⚠️ questions.json ichida yetarli savol yo'q. Ingliz 35, kasbiy 5, ped mahorat 10 ta bo'lishi kerak.",
            show_alert=True
        )
        return

    user_id = str(callback.from_user.id)
    await cancel_timer_task(user_id)

    now_ts = time.time()
    session_id = str(uuid.uuid4())

    await state.set_state(TestState.testing)
    await state.update_data(
        session_id=session_id,
        questions=questions,
        current_index=0,
        answers_map={},
        visited=[],
        total=len(questions),
        message_id=callback.message.message_id,
        start_time=now_ts,
        end_time=now_ts + TEST_DURATION_SECONDS,
        grid_page=0,
        last_render_second_bucket=None,
    )

    await show_question(callback.message, state, force=True)
    TIMER_TASKS[user_id] = asyncio.create_task(timer_updater(callback.message, state, user_id, session_id))
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
    answers_map: dict = data.get("answers_map", {})
    visited: list[int] = data.get("visited", [])

    if not questions or current_index >= len(questions):
        await callback.answer("Savol topilmadi.", show_alert=True)
        return

    selected = int(callback.data.split("_")[1])
    question = questions[current_index]
    is_correct = selected == question["correct"]

    answers_map[str(current_index)] = {
        "selected": selected,
        "correct": is_correct,
        "question": question,
        "user_answer_text": question["options"][selected],
        "correct_answer_text": question["options"][question["correct"]],
        "unanswered": False,
    }

    if current_index not in visited:
        visited.append(current_index)

    next_index = current_index + 1

    await state.update_data(
        answers_map=answers_map,
        visited=visited,
        current_index=next_index,
        grid_page=min(next_index, len(questions) - 1) // QUESTIONS_PER_PAGE if next_index < len(questions) else data.get("grid_page", 0),
        last_render_second_bucket=None,
    )

    if next_index >= len(questions):
        await finish_test(callback.message, state)
    else:
        await show_question(callback.message, state, force=True)

    await callback.answer()


@dp.callback_query(TestState.testing, F.data == "nav_prev")
async def nav_prev(callback: CallbackQuery, state: FSMContext) -> None:
    if await is_time_over(state):
        await finish_test(callback.message, state, time_over=True)
        await callback.answer("Vaqt tugadi.", show_alert=True)
        return

    data = await state.get_data()
    current_index: int = data.get("current_index", 0)
    new_index = max(0, current_index - 1)

    await state.update_data(
        current_index=new_index,
        grid_page=new_index // QUESTIONS_PER_PAGE,
        last_render_second_bucket=None,
    )
    await show_question(callback.message, state, force=True)
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
    new_index = min(total - 1, current_index + 1)

    await state.update_data(
        current_index=new_index,
        grid_page=new_index // QUESTIONS_PER_PAGE,
        last_render_second_bucket=None,
    )
    await show_question(callback.message, state, force=True)
    await callback.answer()


@dp.callback_query(TestState.testing, F.data.startswith("goto_"))
async def goto_question(callback: CallbackQuery, state: FSMContext) -> None:
    if await is_time_over(state):
        await finish_test(callback.message, state, time_over=True)
        await callback.answer("Vaqt tugadi.", show_alert=True)
        return

    try:
        index = int(callback.data.split("_")[1])
    except Exception:
        await callback.answer()
        return

    data = await state.get_data()
    total: int = data.get("total", 0)

    if not (0 <= index < total):
        await callback.answer("Savol topilmadi.", show_alert=True)
        return

    await state.update_data(
        current_index=index,
        grid_page=index // QUESTIONS_PER_PAGE,
        last_render_second_bucket=None,
    )
    await show_question(callback.message, state, force=True)
    await callback.answer()


@dp.callback_query(TestState.testing, F.data.startswith("gridpage_"))
async def grid_page_change(callback: CallbackQuery, state: FSMContext) -> None:
    if await is_time_over(state):
        await finish_test(callback.message, state, time_over=True)
        await callback.answer("Vaqt tugadi.", show_alert=True)
        return

    try:
        page = int(callback.data.split("_")[1])
    except Exception:
        await callback.answer()
        return

    data = await state.get_data()
    total: int = data.get("total", 0)
    total_pages = max(1, math.ceil(total / QUESTIONS_PER_PAGE))
    page = max(0, min(page, total_pages - 1))

    await state.update_data(
        grid_page=page,
        last_render_second_bucket=None,
    )
    await show_question(callback.message, state, force=True)
    await callback.answer()


@dp.callback_query(TestState.testing, F.data == "finish_test_early")
async def finish_test_early(callback: CallbackQuery, state: FSMContext) -> None:
    await finish_test(callback.message, state, finished_early=True)
    await callback.answer("Test yakunlandi.")


@dp.callback_query(F.data.startswith("result_summary_"))
async def result_summary(callback: CallbackQuery) -> None:
    upsert_user_profile(callback.from_user)
    users = load_users()
    user_id = str(callback.from_user.id)

    if user_id not in users or not users[user_id].get("tests"):
        await callback.answer("Natija topilmadi.", show_alert=True)
        return

    try:
        test_index = int(callback.data.split("_")[2])
    except Exception:
        await callback.answer("Natija topilmadi.", show_alert=True)
        return

    tests = users[user_id]["tests"]
    if not (0 <= test_index < len(tests)):
        await callback.answer("Natija topilmadi.", show_alert=True)
        return

    test = tests[test_index]
    display_name = get_display_name_from_saved(users[user_id])
    text = build_result_summary_text(test, display_name)
    keyboard = get_result_grid_keyboard(test_index, test)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
    except Exception:
        pass

    await callback.answer()


@dp.callback_query(F.data.startswith("result_q_"))
async def result_question(callback: CallbackQuery) -> None:
    upsert_user_profile(callback.from_user)
    users = load_users()
    user_id = str(callback.from_user.id)

    if user_id not in users or not users[user_id].get("tests"):
        await callback.answer("Natija topilmadi.", show_alert=True)
        return

    try:
        parts = callback.data.split("_")
        test_index = int(parts[2])
        question_index = int(parts[3])
    except Exception:
        await callback.answer("Natija topilmadi.", show_alert=True)
        return

    tests = users[user_id]["tests"]
    if not (0 <= test_index < len(tests)):
        await callback.answer("Natija topilmadi.", show_alert=True)
        return

    test = tests[test_index]
    display_name = get_display_name_from_saved(users[user_id])

    text = build_result_question_text(test, display_name, question_index)
    keyboard = get_result_question_keyboard(
        test_index=test_index,
        total_questions=len(test.get("answers", [])),
        index=question_index,
    )

    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
    except Exception:
        pass

    await callback.answer()


@dp.message(Command("natijalarim"))
async def my_results(message: Message) -> None:
    upsert_user_profile(message.from_user)
    users = load_users()
    user_id = str(message.from_user.id)

    if user_id not in users or not users[user_id].get("tests"):
        await message.answer(
            "📭 Siz hali test topshirmagansiz. /start orqali testni boshlang.",
            reply_markup=get_home_inline_keyboard()
        )
        return

    user_data = users[user_id]
    display_name = escape(get_display_name_from_saved(user_data))
    tests = user_data.get("tests", [])

    text = f"📊 <b>{display_name} ning barcha natijalari</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n"

    for i, test in enumerate(tests, start=1):
        score = int(test.get("score", 0))
        total = int(test.get("total", TOTAL_SCORE_POINTS))
        correct_answers = int(test.get("correct_answers", 0))
        questions_total = int(test.get("questions_total", 50))
        date_text = escape(str(test.get("date", "-")))

        text += (
            f"{i}. {date_text}\n"
            f"   Ball: {score} / {total}\n"
            f"   To‘g‘ri javoblar: {correct_answers} / {questions_total}\n\n"
        )

        if len(text) > 3500:
            text += "...\n"
            break

    await message.answer(text, reply_markup=get_home_inline_keyboard())


@dp.message(Command("reyting"))
async def rating(message: Message) -> None:
    upsert_user_profile(message.from_user)
    users = load_users()

    if not users:
        await message.answer(
            "📭 Hali hech kim test topshirmagan.",
            reply_markup=get_home_inline_keyboard()
        )
        return

    rating_list = []
    for _, data in users.items():
        tests = data.get("tests", [])
        if not tests:
            continue

        best_test = max(
            tests,
            key=lambda t: (
                int(t.get("score", 0)),
                int(t.get("correct_answers", 0)),
            )
        )

        score = int(best_test.get("score", 0))
        total = int(best_test.get("total", TOTAL_SCORE_POINTS))
        correct_answers = int(best_test.get("correct_answers", 0))
        questions_total = int(best_test.get("questions_total", 50))
        name = get_display_name_from_saved(data)

        rating_list.append((name, score, total, correct_answers, questions_total))

    rating_list.sort(key=lambda x: (x[1], x[3]), reverse=True)

    text = "🏆 <b>REYTING</b> (har bir foydalanuvchining tarixdagi eng yaxshi natijasi)\n━━━━━━━━━━━━━━━━━━━━━━\n\n"

    for i, (name, score, total, correct_answers, questions_total) in enumerate(rating_list, start=1):
        text += (
            f"{i}. {escape(name)}: {score}/{total} | "
            f"{correct_answers}/{questions_total}\n"
        )

        if len(text) > 3500:
            text += "...\n"
            break

    await message.answer(text, reply_markup=get_home_inline_keyboard())


@dp.callback_query(F.data == "my_results")
async def callback_my_results(callback: CallbackQuery) -> None:
    upsert_user_profile(callback.from_user)
    users = load_users()
    user_id = str(callback.from_user.id)

    if user_id not in users or not users[user_id].get("tests"):
        try:
            await callback.message.edit_text(
                "📭 Siz hali test topshirmagansiz. /start orqali testni boshlang.",
                reply_markup=get_home_inline_keyboard()
            )
        except Exception:
            pass
        await callback.answer()
        return

    user_data = users[user_id]
    display_name = escape(get_display_name_from_saved(user_data))
    tests = user_data.get("tests", [])

    text = f"📊 <b>{display_name} ning barcha natijalari</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n"

    for i, test in enumerate(tests, start=1):
        score = int(test.get("score", 0))
        total = int(test.get("total", TOTAL_SCORE_POINTS))
        correct_answers = int(test.get("correct_answers", 0))
        questions_total = int(test.get("questions_total", 50))
        date_text = escape(str(test.get("date", "-")))

        text += (
            f"{i}. {date_text}\n"
            f"   Ball: {score} / {total}\n"
            f"   To‘g‘ri javoblar: {correct_answers} / {questions_total}\n\n"
        )

        if len(text) > 3500:
            text += "...\n"
            break

    try:
        await callback.message.edit_text(text, reply_markup=get_home_inline_keyboard())
    except Exception:
        pass

    await callback.answer()


@dp.callback_query(F.data == "rating")
async def callback_rating(callback: CallbackQuery) -> None:
    upsert_user_profile(callback.from_user)
    users = load_users()

    if not users:
        try:
            await callback.message.edit_text(
                "📭 Hali hech kim test topshirmagan.",
                reply_markup=get_home_inline_keyboard()
            )
        except Exception:
            pass
        await callback.answer()
        return

    rating_list = []
    for _, data in users.items():
        tests = data.get("tests", [])
        if not tests:
            continue

        best_test = max(
            tests,
            key=lambda t: (
                int(t.get("score", 0)),
                int(t.get("correct_answers", 0)),
            )
        )

        score = int(best_test.get("score", 0))
        total = int(best_test.get("total", TOTAL_SCORE_POINTS))
        correct_answers = int(best_test.get("correct_answers", 0))
        questions_total = int(best_test.get("questions_total", 50))
        name = get_display_name_from_saved(data)

        rating_list.append((name, score, total, correct_answers, questions_total))

    rating_list.sort(key=lambda x: (x[1], x[3]), reverse=True)

    text = "🏆 <b>REYTING</b> (har bir foydalanuvchining tarixdagi eng yaxshi natijasi)\n━━━━━━━━━━━━━━━━━━━━━━\n\n"

    for i, (name, score, total, correct_answers, questions_total) in enumerate(rating_list, start=1):
        text += (
            f"{i}. {escape(name)}: {score}/{total} | "
            f"{correct_answers}/{questions_total}\n"
        )

        if len(text) > 3500:
            text += "...\n"
            break

    try:
        await callback.message.edit_text(text, reply_markup=get_home_inline_keyboard())
    except Exception:
        pass

    await callback.answer()


@dp.callback_query(F.data == "noop")
async def noop(callback: CallbackQuery) -> None:
    await callback.answer()


async def main() -> None:
    logging.info("Bot ishga tushdi...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())