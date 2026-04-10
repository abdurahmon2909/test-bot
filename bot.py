import json
import os
from datetime import datetime
from typing import Dict, List, Optional

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ============ KONFIGURATSIYA ============
BOT_TOKEN = os.getenv("BOT_TOKEN")

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# ============ MA'LUMOTLAR BAZASI (JSON) ============
DATA_DIR = "data"
QUESTIONS_FILE = os.path.join(DATA_DIR, "questions.json")
USERS_FILE = os.path.join(DATA_DIR, "users.json")


def ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def load_questions() -> Dict:
    ensure_data_dir()
    if not os.path.exists(QUESTIONS_FILE):
        # Namunaviy savollar (keyin kengaytirasiz)
        sample_questions = {
            "ingliz_tili": [
                {
                    "id": 1,
                    "text": "Which sentence uses 'in case' correctly?",
                    "options": [
                        "I'll take an umbrella in case it rains.",
                        "I'll take an umbrella in case it will rain.",
                        "I took an umbrella in case it rained yesterday.",
                        "I take an umbrella in case it rained."
                    ],
                    "correct": 0,
                    "hint": "⚠️ 'in case' dan keyin present simple ishlatiladi (future ma'nosida)."
                },
                {
                    "id": 2,
                    "text": "Choose the correctly inverted sentence.",
                    "options": [
                        "Rarely she has made such an error.",
                        "Not until the meeting ended did he reveal his plan.",
                        "Only after the test you will know your score.",
                        "No sooner he arrived than he left."
                    ],
                    "correct": 1,
                    "hint": "⚠️ Negativ adverb (Not until, Rarely, No sooner) bilan inversion: auxiliary verb + subject."
                }
            ],
            "kasbiy_standart": [
                {
                    "id": 36,
                    "text": "O'qituvchi o'quvchilarning individual ehtiyojlarini aniqlash uchun qanday usulni qo'llashi kasbiy standartga eng mos keladi?",
                    "options": [
                        "Faqat yozma testlar o'tkazish",
                        "Kuzatuv, suhbat va anketalarni kompleks qo'llash",
                        "Faqat ota-onalarning fikriga tayanish",
                        "O'quvchilarni bir-biriga baholashga undash"
                    ],
                    "correct": 1,
                    "hint": "⚠️ Kasbiy standart bo'yicha individual ehtiyojlarni aniqlashda kompleks yondashuv (kuzatuv, suhbat, anketa) tavsiya etiladi."
                }
            ],
            "ped_mahorat": [
                {
                    "id": 41,
                    "text": "A student says: 'He go to school yesterday.' The teacher says: 'Oh, he went to school yesterday?' This technique is called:",
                    "options": [
                        "Explicit correction",
                        "Recasting",
                        "Metalinguistic feedback",
                        "Elicitation"
                    ],
                    "correct": 1,
                    "hint": "⚠️ Recasting – o'qituvchi xatoni o'zi to'g'rilab, tabiiy holda takrorlaydi."
                }
            ]
        }
        with open(QUESTIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(sample_questions, f, ensure_ascii=False, indent=2)
        return sample_questions
    with open(QUESTIONS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def load_users() -> Dict:
    ensure_data_dir()
    if not os.path.exists(USERS_FILE):
        return {}
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_users(data: Dict):
    ensure_data_dir()
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ============ FSM HOLATLARI ============
class TestState(StatesGroup):
    testing = State()  # Test davomida


# ============ YORDAMCHI FUNKSIYALAR ============
def get_all_questions() -> List[Dict]:
    """Barcha savollarni ketma-ketlikda qaytaradi: 35 ingliz + 5 kasbiy + 10 ped"""
    questions = load_questions()
    all_questions = []
    all_questions.extend(questions["ingliz_tili"][:35])  # 35 ta ingliz
    all_questions.extend(questions["kasbiy_standart"][:5])  # 5 ta kasbiy
    all_questions.extend(questions["ped_mahorat"][:10])  # 10 ta ped
    return all_questions


def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Asosiy menyu knopkalari"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Testni boshlash", callback_data="start_test")],
        [InlineKeyboardButton(text="📊 Natijalarim", callback_data="my_results")],
        [InlineKeyboardButton(text="🏆 Reyting", callback_data="rating")]
    ])


def get_question_keyboard(question_id: int, total: int, current_index: int) -> InlineKeyboardMarkup:
    """Savol uchun inline knopkalar (variantlar + orqaga/oldinga)"""
    buttons = []
    # Variantlar (A, B, C, D)
    for i in range(4):
        buttons.append([InlineKeyboardButton(
            text=f"{chr(65 + i)}",  # A, B, C, D
            callback_data=f"ans_{i}"
        )])
    # Navigatsiya
    nav_buttons = []
    if current_index > 0:
        nav_buttons.append(InlineKeyboardButton(text="◀️ Orqaga", callback_data="nav_prev"))
    nav_buttons.append(InlineKeyboardButton(text=f"{current_index + 1}/{total}", callback_data="noop"))
    if current_index < total - 1:
        nav_buttons.append(InlineKeyboardButton(text="Keyingi ▶️", callback_data="nav_next"))
    buttons.append(nav_buttons)

    # Bekor qilish
    buttons.append([InlineKeyboardButton(text="❌ Testni bekor qilish", callback_data="cancel_test")])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_results_keyboard() -> InlineKeyboardMarkup:
    """Natijalardan keyin menyuga qaytish"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 Bosh menyu", callback_data="main_menu")]
    ])


# ============ BOT HANDLERLARI ============
@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    welcome_text = (
        "🏁 *Assalomu alaykum!* \n\n"
        "📚 Bu bot ingliz tili, kasbiy standart va pedagogik mahorat bo‘yicha test topshirish uchun mo‘ljallangan.\n\n"
        "📌 Test 50 ta savoldan iborat:\n"
        "   • 35 ta ingliz tili\n"
        "   • 5 ta kasbiy standart\n"
        "   • 10 ta pedagogik mahorat\n\n"
        "✅ Test yakunida ball va har bir savol uchun hint (izoh) ko‘rsatiladi.\n\n"
        "🎯 Quyidagi tugmalardan birini tanlang:"
    )
    await message.answer(welcome_text, parse_mode="Markdown", reply_markup=get_main_menu_keyboard())


@dp.callback_query(F.data == "main_menu")
async def back_to_main_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "🏁 *Asosiy menyu*",
        parse_mode="Markdown",
        reply_markup=get_main_menu_keyboard()
    )
    await callback.answer()


@dp.callback_query(F.data == "start_test")
async def start_test(callback: CallbackQuery, state: FSMContext):
    questions = get_all_questions()
    if len(questions) < 50:
        await callback.answer("⚠️ Yetarlicha savol mavjud emas. Admin bilan bog‘laning.", show_alert=True)
        return

    # Foydalanuvchi sessiyasini yaratish
    await state.update_data({
        "questions": questions,
        "current_index": 0,
        "answers": [],  # [{"selected": int, "correct": bool, "question": dict}]
        "total": len(questions)
    })
    await state.set_state(TestState.testing)

    # Birinchi savolni ko‘rsatish
    await show_question(callback.message, state, callback.from_user.id)
    await callback.answer()


async def show_question(message: Message, state: FSMContext, user_id: int = None):
    """Joriy savolni ko‘rsatadi (xabarni tahrirlaydi)"""
    data = await state.get_data()
    current_index = data.get("current_index", 0)
    questions = data.get("questions", [])
    total = data.get("total", 0)

    if current_index >= len(questions):
        await finish_test(message, state)
        return

    question = questions[current_index]

    question_text = (
        f"📚 *Savol {current_index + 1} / {total}*\n\n"
        f"{question['text']}\n\n"
        f"👇 Javob variantlarini tanlang:"
    )

    # Agar birinchi xabar bo'lsa -> yuborish, aks holda tahrirlash
    if user_id and not data.get("message_id"):
        msg = await message.answer(
            question_text,
            parse_mode="Markdown",
            reply_markup=get_question_keyboard(question["id"], total, current_index)
        )
        await state.update_data({"message_id": msg.message_id})
    else:
        await message.edit_text(
            question_text,
            parse_mode="Markdown",
            reply_markup=get_question_keyboard(question["id"], total, current_index)
        )


@dp.callback_query(TestState.testing, F.data.startswith("ans_"))
async def handle_answer(callback: CallbackQuery, state: FSMContext):
    """Javobni saqlash (hint ko'rsatilmaydi, faqat saqlanadi)"""
    selected = int(callback.data.split("_")[1])

    data = await state.get_data()
    current_index = data.get("current_index", 0)
    questions = data.get("questions", [])
    answers = data.get("answers", [])

    question = questions[current_index]
    is_correct = (selected == question["correct"])

    # Javobni saqlash
    answers.append({
        "selected": selected,
        "correct": is_correct,
        "question": question,
        "user_answer_text": question["options"][selected],
        "correct_answer_text": question["options"][question["correct"]]
    })

    await state.update_data({"answers": answers})

    # Keyingi savolga o‘tish
    await state.update_data({"current_index": current_index + 1})

    if current_index + 1 >= len(questions):
        await finish_test(callback.message, state)
    else:
        await show_question(callback.message, state)

    await callback.answer()


@dp.callback_query(TestState.testing, F.data == "nav_prev")
async def nav_prev(callback: CallbackQuery, state: FSMContext):
    """Oldingi savolga qaytish"""
    data = await state.get_data()
    current_index = data.get("current_index", 0)
    if current_index > 0:
        await state.update_data({"current_index": current_index - 1})
        await show_question(callback.message, state)
    await callback.answer()


@dp.callback_query(TestState.testing, F.data == "nav_next")
async def nav_next(callback: CallbackQuery, state: FSMContext):
    """Keyingi savolga o‘tish (javob bermasdan)"""
    data = await state.get_data()
    current_index = data.get("current_index", 0)
    total = data.get("total", 0)
    if current_index < total - 1:
        await state.update_data({"current_index": current_index + 1})
        await show_question(callback.message, state)
    await callback.answer()


@dp.callback_query(TestState.testing, F.data == "cancel_test")
async def cancel_test(callback: CallbackQuery, state: FSMContext):
    """Testni bekor qilish"""
    await state.clear()
    await callback.message.edit_text(
        "❌ Test bekor qilindi.\n\n🏁 Asosiy menyuga qaytish uchun /start buyrug‘ini bosing.",
        reply_markup=get_main_menu_keyboard()
    )
    await callback.answer()


async def finish_test(message: Message, state: FSMContext):
    """Test yakunlanganda ball va hintlarni ko‘rsatish"""
    data = await state.get_data()
    answers = data.get("answers", [])
    total = len(answers)
    correct_count = sum(1 for a in answers if a["correct"])
    score_percent = int(correct_count / total * 100) if total > 0 else 0

    # Natijani saqlash
    users = load_users()
    user_id = str(message.chat.id)
    username = message.from_user.username or message.from_user.full_name

    if user_id not in users:
        users[user_id] = {"username": username, "tests": []}

    users[user_id]["tests"].append({
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "score": correct_count,
        "total": total,
        "answers": answers
    })
    save_users(users)

    # Natija matnini tayyorlash
    result_text = (
        f"🏁 *TEST YAKUNLANDI!* 🏁\n\n"
        f"📊 *Sizning ballingiz:* {correct_count} / {total}  ({score_percent}%)\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📋 *SAVOL TAHLILI:*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )

    for i, ans in enumerate(answers, 1):
        status = "✅" if ans["correct"] else "❌"
        result_text += f"{status} *{i}. {ans['question']['text'][:60]}...*\n"
        if not ans["correct"]:
            result_text += f"   Siz: {ans['user_answer_text'][:50]}...\n"
            result_text += f"   ✓ To‘g‘ri: {ans['correct_answer_text'][:50]}...\n"
            result_text += f"   💡 *Hint:* {ans['question']['hint']}\n\n"
        else:
            result_text += f"   ✓ To‘g‘ri\n\n"

        # Xabar juda uzun bo‘lib ketmasligi uchun
        if len(result_text) > 3800:
            result_text += "\n... va boshqa savollar. Batafsil natijalarni /natijalarim orqali ko‘ring.\n"
            break

    result_text += f"\n━━━━━━━━━━━━━━━━━━━━━━\n"
    result_text += f"📌 /natijalarim - barcha natijalaringiz\n"
    result_text += f"🏆 /reyting - umumiy reyting\n"

    await message.edit_text(result_text, parse_mode="Markdown", reply_markup=get_results_keyboard())
    await state.clear()


@dp.message(Command("natijalarim"))
async def my_results(message: Message):
    users = load_users()
    user_id = str(message.chat.id)

    if user_id not in users or not users[user_id]["tests"]:
        await message.answer("📭 Siz hali hech qanday test topshirmagansiz. /start orqali testni boshlang!")
        return

    user_data = users[user_id]
    text = f"📊 *{user_data['username']} ning natijalari*\n━━━━━━━━━━━━━━━━━━━━━━\n\n"

    for i, test in enumerate(user_data["tests"][-5:], 1):  # Oxirgi 5 ta
        percent = int(test["score"] / test["total"] * 100)
        text += f"{i}. {test['date']}\n"
        text += f"   Ball: {test['score']} / {test['total']} ({percent}%)\n\n"

    await message.answer(text, parse_mode="Markdown")


@dp.message(Command("reyting"))
async def rating(message: Message):
    users = load_users()

    if not users:
        await message.answer("📭 Hali hech kim test topshirmagan.")
        return

    # Eng so‘nggi test bo‘yicha reyting
    rating_list = []
    for uid, data in users.items():
        if data["tests"]:
            last_test = data["tests"][-1]
            percent = int(last_test["score"] / last_test["total"] * 100)
            rating_list.append((data["username"], percent, last_test["score"], last_test["total"]))

    rating_list.sort(key=lambda x: x[1], reverse=True)

    text = "🏆 *REYTING* (oxirgi test natijasi bo‘yicha)\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
    for i, (name, percent, score, total) in enumerate(rating_list[:10], 1):
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        text += f"{medal} {name}: {score}/{total} ({percent}%)\n"

    await message.answer(text, parse_mode="Markdown")


@dp.callback_query(F.data == "my_results")
async def callback_my_results(callback: CallbackQuery):
    await my_results(callback.message)
    await callback.answer()


@dp.callback_query(F.data == "rating")
async def callback_rating(callback: CallbackQuery):
    await rating(callback.message)
    await callback.answer()


@dp.callback_query(F.data == "noop")
async def noop(callback: CallbackQuery):
    await callback.answer()


# ============ ISHGA TUSHIRISH ============
async def main():
    print("🤖 Bot ishga tushdi...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())