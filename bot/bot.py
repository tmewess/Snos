import asyncio
import logging
import os
import random
import sqlite3
from datetime import datetime
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
SUPER_ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
BOT_USERNAME = os.getenv("BOT_USERNAME", "ExtraSnosRobot")
REFS_FOR_SNOS = 3

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ── Корявые Unicode-буквы ────────────────────────────────────────────────────
_GLITCH_MAP = {
    'н': 'η',  'Н': 'Η',
    'е': 'ҽ',  'Е': 'Ҽ',
    'т': 'τ',  'Т': 'Τ',
    'к': 'κ',  'К': 'Κ',
    'о': 'ο',  'О': 'Ο',
    'а': 'α',  'А': 'Α',
    'и': 'ᴎ',  'И': 'Ι',
    'х': 'χ',  'Х': 'Χ',
    'р': 'ρ',  'Р': 'Ρ',
    'с': 'ϲ',  'С': 'Ϲ',
    'у': 'υ',  'У': 'Υ',
    'л': 'ʌ',  'Л': 'Λ',
    'ф': 'φ',  'Ф': 'Φ',
    'п': 'ρ̃',
    'д': 'ɖ',
    'з': 'ȥ',
    'б': 'ƀ',
    'в': 'ѵ',  'В': 'Ѵ',
    'г': 'ƍ',
    'м': 'м̃',
    'e': 'ҽ', 'o': 'ο', 'a': 'α',
    'n': 'η', 'k': 'κ', 'x': 'χ',
    'c': 'ϲ', 'p': 'ρ',
}

def corrupt(text: str, rate: float = 0.5) -> str:
    result = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == '<':
            end = text.find('>', i)
            if end != -1:
                result.append(text[i:end + 1])
                i = end + 1
                continue
        url_skipped = False
        for prefix in ('http://', 'https://', 't.me/', '@'):
            if text[i:i+len(prefix)] == prefix:
                end = i
                while end < len(text) and text[end] not in (' ', '\n', '"', "'", ')', '<'):
                    end += 1
                result.append(text[i:end])
                i = end
                url_skipped = True
                break
        if not url_skipped:
            if ch in _GLITCH_MAP and random.random() < rate:
                result.append(_GLITCH_MAP[ch])
            else:
                result.append(ch)
            i += 1
    return ''.join(result)

def c(text: str) -> str:
    return corrupt(text)

# ── База данных ──────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.db"))
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            referrer_id INTEGER,
            ref_count INTEGER DEFAULT 0,
            snos_balance INTEGER DEFAULT 0,
            joined_at TEXT,
            is_banned INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS admins (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            added_by INTEGER,
            added_at TEXT
        );
        CREATE TABLE IF NOT EXISTS required_channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id TEXT UNIQUE,
            channel_name TEXT,
            invite_link TEXT
        );
        CREATE TABLE IF NOT EXISTS snos_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            target_type TEXT,
            target TEXT,
            reason TEXT,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS mirrors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            bot_username TEXT,
            bot_token TEXT,
            created_at TEXT,
            is_disabled INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS broadcast_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER,
            message TEXT,
            sent_count INTEGER,
            created_at TEXT
        );
    """)
    # Миграция: добавляем колонку is_disabled если её нет
    try:
        conn.execute("ALTER TABLE mirrors ADD COLUMN is_disabled INTEGER DEFAULT 0")
        conn.commit()
    except Exception:
        pass
    conn.commit()
    conn.close()

# ── Хелперы пользователей ────────────────────────────────────────────────────
def get_user(user_id):
    conn = get_db()
    u = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    return u

def create_user(user_id, username, full_name, referrer_id=None):
    conn = get_db()
    conn.execute(
        "INSERT OR IGNORE INTO users (user_id, username, full_name, referrer_id, joined_at) VALUES (?,?,?,?,?)",
        (user_id, username, full_name, referrer_id, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()

def get_channels():
    conn = get_db()
    channels = conn.execute("SELECT * FROM required_channels").fetchall()
    conn.close()
    return channels

def get_user_ref_count(user_id):
    conn = get_db()
    row = conn.execute("SELECT ref_count FROM users WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    return row["ref_count"] if row else 0

def get_snos_balance(user_id):
    conn = get_db()
    row = conn.execute("SELECT snos_balance FROM users WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    return row["snos_balance"] if row else 0

def deduct_snos(user_id):
    conn = get_db()
    conn.execute("UPDATE users SET snos_balance = snos_balance - 1 WHERE user_id=? AND snos_balance > 0", (user_id,))
    conn.commit()
    conn.close()

def add_snos(user_id, amount=1):
    conn = get_db()
    conn.execute("UPDATE users SET snos_balance = snos_balance + ? WHERE user_id=?", (amount, user_id))
    conn.commit()
    conn.close()

def add_ref(referrer_id):
    conn = get_db()
    conn.execute("UPDATE users SET ref_count = ref_count + 1 WHERE user_id=?", (referrer_id,))
    ref_count = conn.execute("SELECT ref_count FROM users WHERE user_id=?", (referrer_id,)).fetchone()
    got = False
    if ref_count and ref_count["ref_count"] % REFS_FOR_SNOS == 0:
        conn.execute("UPDATE users SET snos_balance = snos_balance + 1 WHERE user_id=?", (referrer_id,))
        got = True
    conn.commit()
    conn.close()
    return got

def get_all_users():
    conn = get_db()
    users = conn.execute("SELECT * FROM users").fetchall()
    conn.close()
    return users

def save_snos_request(user_id, target_type, target, reason):
    conn = get_db()
    conn.execute(
        "INSERT INTO snos_requests (user_id, target_type, target, reason, created_at) VALUES (?,?,?,?,?)",
        (user_id, target_type, target, reason, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()

def save_mirror(user_id, bot_username, bot_token):
    conn = get_db()
    conn.execute(
        "INSERT INTO mirrors (user_id, bot_username, bot_token, created_at) VALUES (?,?,?,?)",
        (user_id, bot_username, bot_token, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()

def get_all_mirrors():
    conn = get_db()
    mirrors = conn.execute("SELECT m.*, u.username FROM mirrors m LEFT JOIN users u ON m.user_id=u.user_id").fetchall()
    conn.close()
    return mirrors

def encode_id(target: str) -> str:
    result = []
    for i, ch in enumerate(target):
        shift = (i % 7) + 1
        result.append(chr(ord(ch) + shift))
    return "".join(result)

# ── Система админов ──────────────────────────────────────────────────────────
def get_all_admins() -> list:
    conn = get_db()
    rows = conn.execute("SELECT * FROM admins").fetchall()
    conn.close()
    return rows

def is_admin(user_id: int) -> bool:
    if user_id == SUPER_ADMIN_ID:
        return True
    conn = get_db()
    row = conn.execute("SELECT 1 FROM admins WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    return row is not None

def add_admin(user_id: int, username: str, added_by: int):
    conn = get_db()
    conn.execute(
        "INSERT OR IGNORE INTO admins (user_id, username, added_by, added_at) VALUES (?,?,?,?)",
        (user_id, username, added_by, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()

def remove_admin(user_id: int):
    conn = get_db()
    conn.execute("DELETE FROM admins WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

# ── FSM ─────────────────────────────────────────────────────────────────────
class SnosStates(StatesGroup):
    choose_type = State()
    choose_reason = State()
    enter_target = State()

class AdminStates(StatesGroup):
    broadcast = State()
    add_channel = State()
    add_channel_link = State()
    give_snos_user = State()
    give_snos_amount = State()
    ban_user = State()
    unban_user = State()
    add_admin_id = State()
    remove_admin_id = State()

class MirrorStates(StatesGroup):
    enter_token = State()
    enter_username = State()

# ── Клавиатуры ───────────────────────────────────────────────────────────────
def main_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=c("⚡️ СΗΟС"), callback_data="snos_start")],
        [
            InlineKeyboardButton(text=c("👥 Рҽфҽραʌы"), callback_data="referrals"),
            InlineKeyboardButton(text=c("🪞 Зҽρκαʌο"), callback_data="mirror")
        ]
    ])

def snos_type_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=c("📢 Καηαʌ"), callback_data="type_channel")],
        [InlineKeyboardButton(text=c("👥 Γρυρρα"), callback_data="type_group")],
        [InlineKeyboardButton(text=c("👤 Αккαυητ"), callback_data="type_account")],
        [InlineKeyboardButton(text=c("🤖 Βοτ"), callback_data="type_bot")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_main")]
    ])

def reason_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=c("🔞 Πορηοƍραφᴎя"), callback_data="reason_porn")],
        [InlineKeyboardButton(text=c("💊 Ηҽзακοηηыҽ τοѵαρы"), callback_data="reason_drugs")],
        [InlineKeyboardButton(text=c("🎰 Μοшҽηηᴎчҽϲτѵο"), callback_data="reason_scam")],
        [InlineKeyboardButton(text=c("☠️ Экϲτρҽмᴎзм"), callback_data="reason_extreme")],
        [InlineKeyboardButton(text=c("👶 Κοητҽητ 18+ c ηҽϲοѵ."), callback_data="reason_csam")],
        [InlineKeyboardButton(text=c("🔫 Ηαϲᴎʌᴎҽ / Υƍροзы"), callback_data="reason_violence")],
        [InlineKeyboardButton(text=c("📋 Ρρочҽҽ"), callback_data="reason_other")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="snos_start")]
    ])

def back_keyboard(cb):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data=cb)]
    ])

# ── Проверка подписок ─────────────────────────────────────────────────────────
async def check_subscriptions(user_id: int) -> list:
    channels = get_channels()
    not_subscribed = []
    for ch in channels:
        try:
            member = await bot.get_chat_member(ch["channel_id"], user_id)
            if member.status in ("left", "kicked", "banned"):
                not_subscribed.append(ch)
        except Exception:
            not_subscribed.append(ch)
    return not_subscribed

def subscription_keyboard(channels):
    buttons = []
    for ch in channels:
        link = ch["invite_link"] or f"https://t.me/{ch['channel_id'].lstrip('@')}"
        buttons.append([InlineKeyboardButton(text=f"📌 {ch['channel_name']}", url=link)])
    buttons.append([InlineKeyboardButton(text=c("✅ Я ροɖρᴎϲαʌϲя"), callback_data="check_sub")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# ── Главное меню ──────────────────────────────────────────────────────────────
async def send_welcome(message: types.Message, user_id: int, full_name: str):
    ref_count = get_user_ref_count(user_id)
    snos_bal = get_snos_balance(user_id)
    refs_needed = REFS_FOR_SNOS - (ref_count % REFS_FOR_SNOS) if ref_count % REFS_FOR_SNOS != 0 else 0
    if snos_bal > 0:
        refs_needed = 0

    admin_badge = c(" 👑 <b>[ADMIN]</b>") if is_admin(user_id) else ""

    text = c(
        f"🛡 <b>ExtraSnos</b>{admin_badge}\n\n"
        f"┌ 🆔 Ваш ID: <code>{user_id}</code>\n"
        f"├ 👥 Рефералов: <b>{ref_count}</b>\n"
        f"├ ⚡️ Сносов доступно: <b>{'∞' if is_admin(user_id) else snos_bal}</b>\n"
        f"└ 📊 До следующего сноса: <b>{'—' if is_admin(user_id) else (refs_needed if snos_bal == 0 else '—')} реф.</b>\n\n"
        f"<i>Каждые {REFS_FOR_SNOS} реферала = 1 снос.</i>\n"
        f"<i>Реферал засчитывается только после подписки на все каналы.</i>"
    )
    await message.answer(text, reply_markup=main_keyboard(), parse_mode="HTML")

# ── /start ─────────────────────────────────────────────────────────────────
@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    username = message.from_user.username or ""
    full_name = message.from_user.full_name or ""
    args = message.text.split()
    referrer_id = None

    if len(args) > 1:
        try:
            referrer_id = int(args[1])
            if referrer_id == user_id:
                referrer_id = None
        except ValueError:
            referrer_id = None

    existing = get_user(user_id)

    # ── БАГ 2 ИСПРАВЛЕН: проверка бана ──────────────────────────────────────
    if existing and existing["is_banned"]:
        await message.answer("🚫 Вы заблокированы и не можете использовать этого бота.")
        return

    create_user(user_id, username, full_name, referrer_id)

    # Админы не проходят проверку подписок
    if not is_admin(user_id):
        channels = get_channels()
        if channels:
            not_subbed = await check_subscriptions(user_id)
            if not_subbed:
                # ── БАГ 1 ИСПРАВЛЕН: сохраняем реферера в state до раннего выхода ──
                if not existing and referrer_id:
                    await state.update_data(pending_referrer=referrer_id)
                text = c(
                    f"🛡 <b>ExtraSnos</b>\n\n"
                    f"Для доступа к боту подпишитесь на все каналы ниже.\n"
                    f"После подписки нажмите <b>«Я подписался»</b>.\n\n"
                    f"⚠️ <i>Реферал засчитывается только после подписки на все каналы!</i>"
                )
                await message.answer(text, reply_markup=subscription_keyboard(not_subbed), parse_mode="HTML")
                return

    if not existing and referrer_id:
        ref_user = get_user(referrer_id)
        if ref_user:
            got_snos = add_ref(referrer_id)
            ref_count_now = get_user_ref_count(referrer_id)
            notify = c(
                f"🎉 <b>Новый реферал!</b>\n\n"
                f"👤 Пользователь присоединился по вашей ссылке.\n"
                f"👥 Всего рефералов: <b>{ref_count_now}</b>\n"
            )
            if got_snos:
                notify += c(f"⚡️ <b>+1 снос начислен!</b> Поздравляем!")
            else:
                left = REFS_FOR_SNOS - (ref_count_now % REFS_FOR_SNOS)
                notify += c(f"📊 До следующего сноса: <b>{left} реф.</b>")
            try:
                await bot.send_message(referrer_id, notify, parse_mode="HTML")
            except Exception:
                pass

    await send_welcome(message, user_id, full_name)

@dp.callback_query(F.data == "check_sub")
async def check_sub_callback(call: types.CallbackQuery, state: FSMContext):
    user_id = call.from_user.id
    # ── Проверка бана при нажатии «Я подписался» ─────────────────────────────
    user_check = get_user(user_id)
    if user_check and user_check["is_banned"]:
        await call.answer("🚫 Вы заблокированы.", show_alert=True)
        return
    channels = get_channels()
    if channels:
        not_subbed = await check_subscriptions(user_id)
        if not_subbed:
            await call.answer(c("❌ Вы ещё не подписались на все каналы!"), show_alert=True)
            return

    data = await state.get_data()
    referrer_id = data.get("pending_referrer")

    if referrer_id:
        existing_check = get_user(user_id)
        ref_user = get_user(referrer_id)
        if ref_user and existing_check and existing_check["referrer_id"] == referrer_id:
            got_snos = add_ref(referrer_id)
            ref_count_now = get_user_ref_count(referrer_id)
            notify = c(
                f"🎉 <b>Новый реферал!</b>\n\n"
                f"👤 Пользователь подписался и засчитан.\n"
                f"👥 Всего рефералов: <b>{ref_count_now}</b>\n"
            )
            if got_snos:
                notify += c(f"⚡️ <b>+1 снос начислен!</b>")
            else:
                left = REFS_FOR_SNOS - (ref_count_now % REFS_FOR_SNOS)
                notify += c(f"📊 До следующего сноса: <b>{left} реф.</b>")
            try:
                await bot.send_message(referrer_id, notify, parse_mode="HTML")
            except Exception:
                pass

    await call.message.delete()
    await send_welcome(call.message, user_id, call.from_user.full_name)
    await call.answer()

@dp.callback_query(F.data == "back_main")
async def back_main(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = call.from_user.id
    ref_count = get_user_ref_count(user_id)
    snos_bal = get_snos_balance(user_id)
    refs_needed = REFS_FOR_SNOS - (ref_count % REFS_FOR_SNOS) if ref_count % REFS_FOR_SNOS != 0 else 0
    admin_badge = c(" 👑 <b>[ADMIN]</b>") if is_admin(user_id) else ""

    text = c(
        f"🛡 <b>ExtraSnos</b>{admin_badge}\n\n"
        f"┌ 🆔 Ваш ID: <code>{user_id}</code>\n"
        f"├ 👥 Рефералов: <b>{ref_count}</b>\n"
        f"├ ⚡️ Сносов доступно: <b>{'∞' if is_admin(user_id) else snos_bal}</b>\n"
        f"└ 📊 До следующего сноса: <b>{'—' if is_admin(user_id) else (refs_needed if snos_bal == 0 else '—')} реф.</b>\n\n"
        f"<i>Каждые {REFS_FOR_SNOS} реферала = 1 снос.</i>\n"
        f"<i>Реферал засчитывается только после подписки на все каналы.</i>"
    )
    await call.message.edit_text(text, reply_markup=main_keyboard(), parse_mode="HTML")
    await call.answer()

# ── Снос ─────────────────────────────────────────────────────────────────────
@dp.callback_query(F.data == "snos_start")
async def snos_start(call: types.CallbackQuery, state: FSMContext):
    user_id = call.from_user.id
    admin = is_admin(user_id)

    # Проверка подписок — только для не-админов
    if not admin:
        channels = get_channels()
        if channels:
            not_subbed = await check_subscriptions(user_id)
            if not_subbed:
                await call.answer(c("❌ Сначала подпишитесь на все каналы!"), show_alert=True)
                text = c(f"📌 <b>Требуется подписка</b>\n\nПодпишитесь на все каналы для доступа к функции.")
                await call.message.edit_text(text, reply_markup=subscription_keyboard(not_subbed), parse_mode="HTML")
                return

    # Проверка баланса — только для не-админов
    if not admin:
        snos_bal = get_snos_balance(user_id)
        ref_count = get_user_ref_count(user_id)
        if snos_bal <= 0:
            refs_needed = REFS_FOR_SNOS - (ref_count % REFS_FOR_SNOS)
            text = c(
                f"⚡️ <b>Недостаточно сносов</b>\n\n"
                f"┌ 👥 Рефералов: <b>{ref_count}</b>\n"
                f"└ 📊 До следующего сноса: <b>{refs_needed} реф.</b>\n\n"
                f"Пригласите друзей — каждые <b>{REFS_FOR_SNOS} реферала</b> дают <b>1 снос</b>.\n"
                f"<i>Реферал засчитывается только после подписки на все каналы!</i>"
            )
            await call.message.edit_text(text, reply_markup=back_keyboard("back_main"), parse_mode="HTML")
            await call.answer()
            return

    await state.set_state(SnosStates.choose_type)
    text = c(f"⚡️ <b>Запуск сноса</b>\n\nВыберите тип цели:")
    await call.message.edit_text(text, reply_markup=snos_type_keyboard(), parse_mode="HTML")
    await call.answer()

@dp.callback_query(SnosStates.choose_type, F.data.startswith("type_"))
async def snos_type_chosen(call: types.CallbackQuery, state: FSMContext):
    type_map = {
        "type_channel": "Канал",
        "type_group": "Группа",
        "type_account": "Аккаунт",
        "type_bot": "Бот"
    }
    chosen = type_map.get(call.data, "Неизвестно")
    await state.update_data(target_type=chosen)
    await state.set_state(SnosStates.choose_reason)
    text = c(f"⚡️ <b>Снос: {chosen}</b>\n\nВыберите причину жалобы:")
    await call.message.edit_text(text, reply_markup=reason_keyboard(), parse_mode="HTML")
    await call.answer()

@dp.callback_query(SnosStates.choose_reason, F.data.startswith("reason_"))
async def snos_reason_chosen(call: types.CallbackQuery, state: FSMContext):
    reason_map = {
        "reason_porn": "Порнография",
        "reason_drugs": "Незаконные товары (наркотики/оружие)",
        "reason_scam": "Мошенничество / Фрод",
        "reason_extreme": "Экстремизм / Терроризм",
        "reason_csam": "Контент 18+ с несовершеннолетними",
        "reason_violence": "Насилие / Угрозы",
        "reason_other": "Прочее нарушение правил"
    }
    reason = reason_map.get(call.data, "Прочее")
    await state.update_data(reason=reason)
    await state.set_state(SnosStates.enter_target)

    data = await state.get_data()
    target_type = data.get("target_type", "цель")
    text = c(
        f"⚡️ <b>Снос: {target_type}</b>\n"
        f"📋 Причина: <b>{reason}</b>\n\n"
        f"Введите <b>@username</b> или ссылку на цель:\n\n"
        f"<i>Пример: @example или t.me/example</i>"
    )
    await call.message.edit_text(text, reply_markup=back_keyboard("snos_start"), parse_mode="HTML")
    await call.answer()

@dp.message(SnosStates.enter_target)
async def snos_enter_target(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    target = message.text.strip()
    data = await state.get_data()
    target_type = data.get("target_type", "Цель")
    reason = data.get("reason", "Прочее")
    admin = is_admin(user_id)

    if not admin:
        snos_bal = get_snos_balance(user_id)
        if snos_bal <= 0:
            await state.clear()
            await message.answer(c("❌ Недостаточно сносов!"), reply_markup=main_keyboard())
            return
        deduct_snos(user_id)

    save_snos_request(user_id, target_type, target, reason)
    encoded = encode_id(target)
    await state.clear()

    new_bal = get_snos_balance(user_id)
    bal_str = "∞" if admin else str(new_bal)

    text = c(
        f"✅ <b>Жалоба принята в работу</b>\n\n"
        f"┌ 🎯 Тип: <b>{target_type}</b>\n"
        f"├ 📋 Причина: <b>{reason}</b>\n"
        f"├ 🔗 Цель: <code>{target}</code>\n"
        f"└ 🔒 ID запроса: <code>{encoded[:14]}...</code>\n\n"
        f"⏳ Запрос передан в систему модерации Telegram.\n"
        f"📡 Среднее время обработки: <b>24–72 часа</b>.\n\n"
        f"⚡️ Остаток сносов: <b>{bal_str}</b>"
    )
    await message.answer(text, reply_markup=main_keyboard(), parse_mode="HTML")

# ── Рефералы ─────────────────────────────────────────────────────────────────
@dp.callback_query(F.data == "referrals")
async def referrals_menu(call: types.CallbackQuery):
    user_id = call.from_user.id
    ref_count = get_user_ref_count(user_id)
    snos_bal = get_snos_balance(user_id)
    refs_needed = REFS_FOR_SNOS - (ref_count % REFS_FOR_SNOS) if ref_count % REFS_FOR_SNOS != 0 else 0
    username = BOT_USERNAME.lstrip("@")
    ref_link = f"https://t.me/{username}?start={user_id}"

    text = c(
        f"👥 <b>Реферальная система</b>\n\n"
        f"┌ 👤 Ваших рефералов: <b>{ref_count}</b>\n"
        f"├ ⚡️ Сносов доступно: <b>{'∞' if is_admin(user_id) else snos_bal}</b>\n"
        f"└ 📊 До следующего сноса: <b>{'—' if is_admin(user_id) else refs_needed} реф.</b>\n\n"
        f"🔗 <b>Ваша реферальная ссылка:</b>\n"
        f"<code>{ref_link}</code>\n\n"
        f"📌 <b>Правила:</b>\n"
        f"• Каждые <b>{REFS_FOR_SNOS} реферала</b> = <b>1 снос</b>\n"
        f"• Реферал засчитывается <b>только после подписки</b> на все каналы\n"
        f"• Чем больше рефералов — тем больше сносов!"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=c("📤 Поделиться ссылкой"),
            url=f"https://t.me/share/url?url={ref_link}&text=Снос%20каналов%20и%20аккаунтов%20Telegram!"
        )],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_main")]
    ])
    await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await call.answer()

# ── Зеркало ─────────────────────────────────────────────────────────────────
@dp.callback_query(F.data == "mirror")
async def mirror_menu(call: types.CallbackQuery, state: FSMContext):
    user_id = call.from_user.id

    if not is_admin(user_id):
        channels = get_channels()
        if channels:
            not_subbed = await check_subscriptions(user_id)
            if not_subbed:
                await call.answer(c("❌ Сначала подпишитесь на все каналы!"), show_alert=True)
                return

    conn = get_db()
    existing_mirror = conn.execute("SELECT * FROM mirrors WHERE user_id=?", (user_id,)).fetchone()
    conn.close()

    if existing_mirror:
        text = c(
            f"🪞 <b>Ваше зеркало</b>\n\n"
            f"┌ 🤖 Бот: @{existing_mirror['bot_username']}\n"
            f"└ 📅 Создано: {existing_mirror['created_at'][:10]}\n\n"
            f"<i>Зеркало работает с теми же настройками подписки и реферальной системой.</i>"
        )
        await call.message.edit_text(text, reply_markup=back_keyboard("back_main"), parse_mode="HTML")
        await call.answer()
        return

    text = c(
        f"🪞 <b>Создать зеркало бота</b>\n\n"
        f"Зеркало — ваша личная копия <b>ExtraSnos</b>.\n\n"
        f"📌 <b>Возможности:</b>\n"
        f"• Те же обязательные подписки на каналы\n"
        f"• Полноценная реферальная система\n"
        f"• Вы управляете своими пользователями\n\n"
        f"🤖 Введите токен вашего бота (от @BotFather):"
    )
    await state.set_state(MirrorStates.enter_token)
    await call.message.edit_text(text, reply_markup=back_keyboard("back_main"), parse_mode="HTML")
    await call.answer()

@dp.message(MirrorStates.enter_token)
async def mirror_enter_token(message: types.Message, state: FSMContext):
    token = message.text.strip()
    if ":" not in token or len(token) < 30:
        await message.answer(c("❌ Неверный формат токена. Пример: <code>123456789:AAF...</code>"), parse_mode="HTML")
        return
    await state.update_data(mirror_token=token)
    await state.set_state(MirrorStates.enter_username)
    await message.answer(c("✅ Токен принят!\n\nВведите <b>username</b> бота (например: <code>MyMirrorBot</code>):"), parse_mode="HTML")

@dp.message(MirrorStates.enter_username)
async def mirror_enter_username(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    username = message.text.strip().lstrip("@")
    data = await state.get_data()
    token = data.get("mirror_token", "")
    save_mirror(user_id, username, token)
    await state.clear()

    text = c(
        f"🎉 <b>Зеркало создано!</b>\n\n"
        f"🤖 Бот: @{username}\n\n"
        f"<i>Ваше зеркало зарегистрировано.\n"
        f"Разверните бота, используя тот же исходный код.</i>"
    )
    await message.answer(text, reply_markup=main_keyboard(), parse_mode="HTML")
    try:
        await bot.send_message(
            SUPER_ADMIN_ID,
            c(f"🪞 <b>Новое зеркало!</b>\n\n"
              f"👤 Пользователь: {message.from_user.full_name} (<code>{user_id}</code>)\n"
              f"🤖 Бот: @{username}\n"
              f"🔑 Токен: <code>{token[:10]}...</code>"),
            parse_mode="HTML"
        )
    except Exception:
        pass

# ── Админ-панель ─────────────────────────────────────────────────────────────
@dp.message(Command("admin"))
async def admin_panel(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    await show_admin(message)

async def show_admin(message):
    conn = get_db()
    total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    total_snos = conn.execute("SELECT COUNT(*) FROM snos_requests").fetchone()[0]
    total_mirrors = conn.execute("SELECT COUNT(*) FROM mirrors").fetchone()[0]
    channels_count = conn.execute("SELECT COUNT(*) FROM required_channels").fetchone()[0]
    admins_count = conn.execute("SELECT COUNT(*) FROM admins").fetchone()[0]
    conn.close()

    text = (
        f"🔧 <b>Админ-панель ExtraSnos</b>\n\n"
        f"┌ 👥 Пользователей: <b>{total_users}</b>\n"
        f"├ ⚡️ Сносов подано: <b>{total_snos}</b>\n"
        f"├ 🪞 Зеркал: <b>{total_mirrors}</b>\n"
        f"├ 📌 Каналов: <b>{channels_count}</b>\n"
        f"└ 👑 Админов: <b>{admins_count + 1}</b>\n\n"
        f"Выберите действие:"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👑 Управление админами", callback_data="adm_admins")],
        [InlineKeyboardButton(text="📌 Каналы подписки", callback_data="adm_channels")],
        [InlineKeyboardButton(text="👥 Все пользователи", callback_data="adm_users")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="adm_broadcast")],
        [InlineKeyboardButton(text="⚡️ Выдать сносы", callback_data="adm_give_snos")],
        [InlineKeyboardButton(text="🪞 Все зеркала", callback_data="adm_mirrors")],
        [InlineKeyboardButton(text="📋 История сносов", callback_data="adm_snos_history")],
        [InlineKeyboardButton(text="🚫 Заблокировать юзера", callback_data="adm_ban")],
        [InlineKeyboardButton(text="✅ Разбанить юзера", callback_data="adm_unban")],
        [InlineKeyboardButton(text="📊 Топ рефоводов", callback_data="adm_ref_stats")],
        [InlineKeyboardButton(text="🗑 Очистить историю сносов", callback_data="adm_clear_snos")]
    ])
    await message.answer(text, reply_markup=kb, parse_mode="HTML")

# ── Управление админами ───────────────────────────────────────────────────────
@dp.callback_query(F.data == "adm_admins")
async def adm_admins(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    admins = get_all_admins()
    text = f"👑 <b>Список администраторов:</b>\n\n"
    text += f"• <b>Супер-Админ</b> — <code>{SUPER_ADMIN_ID}</code> (владелец)\n"
    for a in admins:
        uname = f"@{a['username']}" if a['username'] else "—"
        text += f"• {uname} — <code>{a['user_id']}</code>\n  📅 Добавлен: {a['added_at'][:10]}\n"
    if not admins:
        text += "<i>Дополнительных админов нет.</i>\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить админа", callback_data="adm_add_admin")],
        [InlineKeyboardButton(text="🗑 Удалить админа", callback_data="adm_remove_admin")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="adm_back")]
    ])
    await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await call.answer()

@dp.callback_query(F.data == "adm_add_admin")
async def adm_add_admin(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != SUPER_ADMIN_ID:
        await call.answer("❌ Только супер-админ может добавлять администраторов!", show_alert=True)
        return
    await state.set_state(AdminStates.add_admin_id)
    await call.message.edit_text(
        "👑 <b>Добавление админа</b>\n\n"
        "Введите <b>Telegram User ID</b> нового администратора:\n"
        "<i>Узнать ID можно через @userinfobot</i>",
        reply_markup=back_keyboard("adm_admins"),
        parse_mode="HTML"
    )
    await call.answer()

@dp.message(AdminStates.add_admin_id)
async def do_add_admin(message: types.Message, state: FSMContext):
    if message.from_user.id != SUPER_ADMIN_ID:
        return
    try:
        new_admin_id = int(message.text.strip())
        if new_admin_id == SUPER_ADMIN_ID:
            await message.answer("❌ Этот пользователь уже является супер-админом!")
            return
        if is_admin(new_admin_id):
            await message.answer("❌ Этот пользователь уже является администратором!")
            return

        # Пробуем получить username через базу пользователей
        u = get_user(new_admin_id)
        uname = u["username"] if u else ""

        add_admin(new_admin_id, uname, message.from_user.id)
        await state.clear()

        display = f"@{uname}" if uname else f"ID {new_admin_id}"
        await message.answer(
            f"✅ <b>Администратор добавлен!</b>\n\n"
            f"👑 {display} (<code>{new_admin_id}</code>)\n\n"
            f"<i>Теперь этот пользователь имеет доступ к /admin и неограниченным сносам без подписок и рефералов.</i>",
            parse_mode="HTML"
        )
        try:
            await bot.send_message(
                new_admin_id,
                c(f"👑 <b>Вы назначены администратором ExtraSnos!</b>\n\n"
                  f"Используйте /admin для доступа к панели управления.\n"
                  f"⚡️ Для вас сносы теперь безлимитны.\n"
                  f"📌 Вам не нужно подписываться на каналы и набирать рефералов."),
                parse_mode="HTML"
            )
        except Exception:
            pass
    except ValueError:
        await message.answer("❌ Введите числовой ID (например: <code>123456789</code>)", parse_mode="HTML")

@dp.callback_query(F.data == "adm_remove_admin")
async def adm_remove_admin(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != SUPER_ADMIN_ID:
        await call.answer("❌ Только супер-админ может удалять администраторов!", show_alert=True)
        return
    admins = get_all_admins()
    if not admins:
        await call.answer("Дополнительных админов нет", show_alert=True)
        return
    buttons = []
    for a in admins:
        uname = f"@{a['username']}" if a['username'] else str(a['user_id'])
        buttons.append([InlineKeyboardButton(text=f"🗑 {uname}", callback_data=f"del_adm_{a['user_id']}")])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="adm_admins")])
    await call.message.edit_text(
        "🗑 <b>Выберите админа для удаления:</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML"
    )
    await call.answer()

@dp.callback_query(F.data.startswith("del_adm_"))
async def del_admin(call: types.CallbackQuery):
    if call.from_user.id != SUPER_ADMIN_ID:
        await call.answer("❌ Нет доступа", show_alert=True)
        return
    adm_id = int(call.data.replace("del_adm_", ""))
    remove_admin(adm_id)
    await call.answer("✅ Администратор удалён", show_alert=True)
    try:
        await bot.send_message(adm_id, c("⚠️ <b>Ваши права администратора были отозваны.</b>"), parse_mode="HTML")
    except Exception:
        pass
    # Обновляем список
    admins = get_all_admins()
    text = f"👑 <b>Список администраторов:</b>\n\n"
    text += f"• <b>Супер-Админ</b> — <code>{SUPER_ADMIN_ID}</code> (владелец)\n"
    for a in admins:
        uname = f"@{a['username']}" if a['username'] else "—"
        text += f"• {uname} — <code>{a['user_id']}</code>\n"
    if not admins:
        text += "<i>Дополнительных админов нет.</i>"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить админа", callback_data="adm_add_admin")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="adm_back")]
    ])
    await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")

# ── Остальные разделы панели ──────────────────────────────────────────────────
@dp.callback_query(F.data == "adm_channels")
async def adm_channels(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    channels = get_channels()
    if channels:
        text = "📌 <b>Обязательные каналы:</b>\n\n"
        for i, ch in enumerate(channels, 1):
            text += f"{i}. <b>{ch['channel_name']}</b> — <code>{ch['channel_id']}</code>\n"
    else:
        text = "📌 <b>Каналов нет.</b>"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить канал", callback_data="adm_add_channel")],
        [InlineKeyboardButton(text="🗑 Удалить канал", callback_data="adm_del_channel")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="adm_back")]
    ])
    await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await call.answer()

@dp.callback_query(F.data == "adm_add_channel")
async def adm_add_channel(call: types.CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return
    await state.set_state(AdminStates.add_channel)
    await call.message.edit_text(
        "📌 <b>Добавление канала</b>\n\nВведите ID канала или @username:\n<i>Пример: @mychannel или -1001234567890</i>",
        reply_markup=back_keyboard("adm_channels"), parse_mode="HTML"
    )
    await call.answer()

@dp.message(AdminStates.add_channel)
async def adm_add_channel_id(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    channel_id = message.text.strip()
    await state.update_data(new_channel_id=channel_id)
    await state.set_state(AdminStates.add_channel_link)
    await message.answer(
        f"✅ ID принят: <code>{channel_id}</code>\n\nВведите название и ссылку через | (пайп):\n<i>Пример: Мой Канал | https://t.me/+xxxxx</i>",
        parse_mode="HTML"
    )

@dp.message(AdminStates.add_channel_link)
async def adm_add_channel_link(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split("|", 1)
    name = parts[0].strip()
    link = parts[1].strip() if len(parts) > 1 else ""
    data = await state.get_data()
    channel_id = data.get("new_channel_id")
    conn = get_db()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO required_channels (channel_id, channel_name, invite_link) VALUES (?,?,?)",
            (channel_id, name, link)
        )
        conn.commit()
        await message.answer(f"✅ Канал <b>{name}</b> добавлен!", parse_mode="HTML")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")
    conn.close()
    await state.clear()

@dp.callback_query(F.data == "adm_del_channel")
async def adm_del_channel(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    channels = get_channels()
    if not channels:
        await call.answer("Каналов нет", show_alert=True)
        return
    buttons = []
    for ch in channels:
        buttons.append([InlineKeyboardButton(text=f"🗑 {ch['channel_name']}", callback_data=f"del_ch_{ch['id']}")])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="adm_channels")])
    await call.message.edit_text("Выберите канал для удаления:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await call.answer()

@dp.callback_query(F.data.startswith("del_ch_"))
async def del_channel(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    ch_id = int(call.data.replace("del_ch_", ""))
    conn = get_db()
    conn.execute("DELETE FROM required_channels WHERE id=?", (ch_id,))
    conn.commit()
    conn.close()
    await call.answer("✅ Канал удалён", show_alert=True)
    channels = get_channels()
    text = "📌 <b>Обязательные каналы:</b>\n\n"
    if channels:
        for i, ch in enumerate(channels, 1):
            text += f"{i}. <b>{ch['channel_name']}</b> — <code>{ch['channel_id']}</code>\n"
    else:
        text = "📌 <b>Каналов нет.</b>"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить канал", callback_data="adm_add_channel")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="adm_back")]
    ])
    await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data == "adm_users")
async def adm_users(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    users = get_all_users()
    text = f"👥 <b>Пользователи ({len(users)}):</b>\n\n"
    for u in users[:25]:
        uname = f"@{u['username']}" if u['username'] else "—"
        badge = " 👑" if is_admin(u['user_id']) else ""
        text += (
            f"• <b>{u['full_name']}</b>{badge} {uname}\n"
            f"  ID: <code>{u['user_id']}</code> | Реф: {u['ref_count']} | Сносы: {u['snos_balance']}\n"
        )
    if len(users) > 25:
        text += f"\n<i>...и ещё {len(users) - 25} пользователей</i>"
    await call.message.edit_text(text, reply_markup=back_keyboard("adm_back"), parse_mode="HTML")
    await call.answer()

@dp.callback_query(F.data == "adm_broadcast")
async def adm_broadcast(call: types.CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return
    await state.set_state(AdminStates.broadcast)
    await call.message.edit_text(
        "📢 <b>Рассылка</b>\n\nВведите текст (поддерживается HTML):",
        reply_markup=back_keyboard("adm_back"), parse_mode="HTML"
    )
    await call.answer()

@dp.message(AdminStates.broadcast)
async def do_broadcast(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    users = get_all_users()
    text = message.text or message.caption or ""
    sent = 0
    for u in users:
        try:
            await bot.send_message(u["user_id"], text, parse_mode="HTML")
            sent += 1
            await asyncio.sleep(0.05)
        except Exception:
            pass
    conn = get_db()
    conn.execute(
        "INSERT INTO broadcast_log (admin_id, message, sent_count, created_at) VALUES (?,?,?,?)",
        (message.from_user.id, text[:200], sent, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()
    await state.clear()
    await message.answer(f"✅ Рассылка завершена!\n📨 Отправлено: <b>{sent}</b> из <b>{len(users)}</b>", parse_mode="HTML")

@dp.callback_query(F.data == "adm_give_snos")
async def adm_give_snos(call: types.CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return
    await state.set_state(AdminStates.give_snos_user)
    await call.message.edit_text(
        "⚡️ <b>Выдача сносов</b>\n\nВведите ID пользователя:",
        reply_markup=back_keyboard("adm_back"), parse_mode="HTML"
    )
    await call.answer()

@dp.message(AdminStates.give_snos_user)
async def adm_give_snos_user(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        uid = int(message.text.strip())
        u = get_user(uid)
        if not u:
            await message.answer("❌ Пользователь не найден")
            return
        await state.update_data(give_snos_uid=uid)
        await state.set_state(AdminStates.give_snos_amount)
        await message.answer(f"✅ Пользователь: <b>{u['full_name']}</b>\nВведите количество сносов:", parse_mode="HTML")
    except ValueError:
        await message.answer("❌ Введите числовой ID")

@dp.message(AdminStates.give_snos_amount)
async def adm_give_snos_amount(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        amount = int(message.text.strip())
        data = await state.get_data()
        uid = data.get("give_snos_uid")
        add_snos(uid, amount)
        u = get_user(uid)
        await state.clear()
        cur_bal = get_snos_balance(uid)
        await message.answer(
            f"✅ Выдано <b>{amount}</b> сносов пользователю <b>{u['full_name']}</b>!\nБаланс: <b>{cur_bal}</b>",
            parse_mode="HTML"
        )
        try:
            await bot.send_message(uid, c(f"🎁 <b>Администратор выдал вам {amount} сноса(ов)!</b>\n⚡️ Ваш баланс пополнен."), parse_mode="HTML")
        except Exception:
            pass
    except ValueError:
        await message.answer("❌ Введите число")

@dp.callback_query(F.data == "adm_mirrors")
async def adm_mirrors(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    mirrors = get_all_mirrors()
    if not mirrors:
        text = "🪞 <b>Зеркал нет</b>"
        await call.message.edit_text(text, reply_markup=back_keyboard("adm_back"), parse_mode="HTML")
        await call.answer()
        return

    text = f"🪞 <b>Все зеркала ({len(mirrors)}):</b>\n\nНажмите на зеркало для управления:"
    buttons = []
    for m in mirrors:
        uname = f"@{m['username']}" if m['username'] else str(m['user_id'])
        status = "🔴" if m['is_disabled'] else "🟢"
        buttons.append([InlineKeyboardButton(
            text=f"{status} @{m['bot_username']} — {uname}",
            callback_data=f"mirror_detail_{m['id']}"
        )])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="adm_back")])
    await call.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")
    await call.answer()

@dp.callback_query(F.data.startswith("mirror_detail_"))
async def mirror_detail(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    mirror_id = int(call.data.replace("mirror_detail_", ""))
    conn = get_db()
    m = conn.execute(
        "SELECT m.*, u.username, u.full_name FROM mirrors m LEFT JOIN users u ON m.user_id=u.user_id WHERE m.id=?",
        (mirror_id,)
    ).fetchone()
    conn.close()

    if not m:
        await call.answer("❌ Зеркало не найдено", show_alert=True)
        return

    uname = f"@{m['username']}" if m['username'] else "—"
    fname = m['full_name'] or str(m['user_id'])
    status = "🔴 Отключено" if m['is_disabled'] else "🟢 Активно"
    token_hidden = m['bot_token'][:10] + "..." + m['bot_token'][-5:]

    text = (
        f"🪞 <b>Зеркало: @{m['bot_username']}</b>\n\n"
        f"┌ 👤 Создатель: {fname} {uname}\n"
        f"├ 🆔 User ID: <code>{m['user_id']}</code>\n"
        f"├ 📅 Создано: {m['created_at'][:10]}\n"
        f"├ ⚙️ Статус: {status}\n"
        f"└ 🔑 Токен: <code>{token_hidden}</code>"
    )

    toggle_text = "✅ Включить бот" if m['is_disabled'] else "🚫 Отключить бот"
    toggle_cb = f"mirror_enable_{mirror_id}" if m['is_disabled'] else f"mirror_disable_{mirror_id}"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔑 Показать полный токен", callback_data=f"mirror_token_{mirror_id}")],
        [InlineKeyboardButton(text=toggle_text, callback_data=toggle_cb)],
        [InlineKeyboardButton(text="🗑 Удалить зеркало", callback_data=f"mirror_delete_{mirror_id}")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="adm_mirrors")]
    ])
    await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await call.answer()

@dp.callback_query(F.data.startswith("mirror_token_"))
async def mirror_show_token(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    mirror_id = int(call.data.replace("mirror_token_", ""))
    conn = get_db()
    m = conn.execute("SELECT bot_username, bot_token, user_id FROM mirrors WHERE id=?", (mirror_id,)).fetchone()
    conn.close()
    if not m:
        await call.answer("❌ Не найдено", show_alert=True)
        return
    text = (
        f"🔑 <b>Полный токен зеркала @{m['bot_username']}</b>\n\n"
        f"<code>{m['bot_token']}</code>\n\n"
        f"<i>Владелец: <code>{m['user_id']}</code></i>"
    )
    await call.answer()
    await call.message.answer(text, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад к зеркалу", callback_data=f"mirror_detail_{mirror_id}")]
        ])
    )

@dp.callback_query(F.data.startswith("mirror_disable_"))
async def mirror_disable(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    mirror_id = int(call.data.replace("mirror_disable_", ""))
    conn = get_db()
    m = conn.execute("SELECT * FROM mirrors WHERE id=?", (mirror_id,)).fetchone()
    if not m:
        conn.close()
        await call.answer("❌ Не найдено", show_alert=True)
        return
    conn.execute("UPDATE mirrors SET is_disabled=1 WHERE id=?", (mirror_id,))
    conn.commit()
    conn.close()

    # Пробуем остановить бот через API Telegram (logout)
    try:
        mirror_bot = Bot(token=m['bot_token'])
        await mirror_bot.log_out()
        await mirror_bot.session.close()
    except Exception:
        pass

    # Уведомляем владельца зеркала
    try:
        await bot.send_message(
            m['user_id'],
            c(f"🚫 <b>Ваше зеркало @{m['bot_username']} было отключено администратором.</b>\n\n"
              f"Для восстановления обратитесь к администрации."),
            parse_mode="HTML"
        )
    except Exception:
        pass

    await call.answer("✅ Бот отключён", show_alert=True)
    # Обновляем карточку
    uname_row = get_user(m['user_id'])
    uname = f"@{uname_row['username']}" if uname_row and uname_row['username'] else str(m['user_id'])
    token_hidden = m['bot_token'][:10] + "..." + m['bot_token'][-5:]
    text = (
        f"🪞 <b>Зеркало: @{m['bot_username']}</b>\n\n"
        f"┌ 🆔 User ID: <code>{m['user_id']}</code>\n"
        f"├ 📅 Создано: {m['created_at'][:10]}\n"
        f"├ ⚙️ Статус: 🔴 Отключено\n"
        f"└ 🔑 Токен: <code>{token_hidden}</code>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔑 Показать полный токен", callback_data=f"mirror_token_{mirror_id}")],
        [InlineKeyboardButton(text="✅ Включить бот", callback_data=f"mirror_enable_{mirror_id}")],
        [InlineKeyboardButton(text="🗑 Удалить зеркало", callback_data=f"mirror_delete_{mirror_id}")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="adm_mirrors")]
    ])
    await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data.startswith("mirror_enable_"))
async def mirror_enable(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    mirror_id = int(call.data.replace("mirror_enable_", ""))
    conn = get_db()
    m = conn.execute("SELECT * FROM mirrors WHERE id=?", (mirror_id,)).fetchone()
    if not m:
        conn.close()
        await call.answer("❌ Не найдено", show_alert=True)
        return
    conn.execute("UPDATE mirrors SET is_disabled=0 WHERE id=?", (mirror_id,))
    conn.commit()
    conn.close()

    # Уведомляем владельца
    try:
        await bot.send_message(
            m['user_id'],
            c(f"✅ <b>Ваше зеркало @{m['bot_username']} было восстановлено администратором.</b>"),
            parse_mode="HTML"
        )
    except Exception:
        pass

    await call.answer("✅ Бот включён", show_alert=True)
    token_hidden = m['bot_token'][:10] + "..." + m['bot_token'][-5:]
    text = (
        f"🪞 <b>Зеркало: @{m['bot_username']}</b>\n\n"
        f"┌ 🆔 User ID: <code>{m['user_id']}</code>\n"
        f"├ 📅 Создано: {m['created_at'][:10]}\n"
        f"├ ⚙️ Статус: 🟢 Активно\n"
        f"└ 🔑 Токен: <code>{token_hidden}</code>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔑 Показать полный токен", callback_data=f"mirror_token_{mirror_id}")],
        [InlineKeyboardButton(text="🚫 Отключить бот", callback_data=f"mirror_disable_{mirror_id}")],
        [InlineKeyboardButton(text="🗑 Удалить зеркало", callback_data=f"mirror_delete_{mirror_id}")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="adm_mirrors")]
    ])
    await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data.startswith("mirror_delete_"))
async def mirror_delete(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    mirror_id = int(call.data.replace("mirror_delete_", ""))
    conn = get_db()
    m = conn.execute("SELECT * FROM mirrors WHERE id=?", (mirror_id,)).fetchone()
    if not m:
        conn.close()
        await call.answer("❌ Не найдено", show_alert=True)
        return
    # Отключаем бот перед удалением
    try:
        mirror_bot = Bot(token=m['bot_token'])
        await mirror_bot.log_out()
        await mirror_bot.session.close()
    except Exception:
        pass
    conn.execute("DELETE FROM mirrors WHERE id=?", (mirror_id,))
    conn.commit()
    conn.close()
    try:
        await bot.send_message(
            m['user_id'],
            c(f"🗑 <b>Ваше зеркало @{m['bot_username']} было удалено администратором.</b>"),
            parse_mode="HTML"
        )
    except Exception:
        pass
    await call.answer("✅ Зеркало удалено", show_alert=True)
    # Возврат к списку
    mirrors = get_all_mirrors()
    if not mirrors:
        text = "🪞 <b>Зеркал нет</b>"
        await call.message.edit_text(text, reply_markup=back_keyboard("adm_back"), parse_mode="HTML")
        return
    text = f"🪞 <b>Все зеркала ({len(mirrors)}):</b>\n\nНажмите на зеркало для управления:"
    buttons = []
    for mir in mirrors:
        uname = f"@{mir['username']}" if mir['username'] else str(mir['user_id'])
        status = "🔴" if mir['is_disabled'] else "🟢"
        buttons.append([InlineKeyboardButton(
            text=f"{status} @{mir['bot_username']} — {uname}",
            callback_data=f"mirror_detail_{mir['id']}"
        )])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="adm_back")])
    await call.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")

@dp.callback_query(F.data == "adm_snos_history")
async def adm_snos_history(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    conn = get_db()
    rows = conn.execute(
        "SELECT s.*, u.username FROM snos_requests s LEFT JOIN users u ON s.user_id=u.user_id ORDER BY s.id DESC LIMIT 20"
    ).fetchall()
    conn.close()
    if not rows:
        text = "📋 <b>История пуста</b>"
    else:
        text = "📋 <b>Последние 20 сносов:</b>\n\n"
        for r in rows:
            uname = f"@{r['username']}" if r['username'] else str(r['user_id'])
            text += f"• {uname} → {r['target_type']} <code>{r['target']}</code>\n  {r['reason']}\n  📅 {r['created_at'][:16]}\n\n"
    await call.message.edit_text(text, reply_markup=back_keyboard("adm_back"), parse_mode="HTML")
    await call.answer()

@dp.callback_query(F.data == "adm_ban")
async def adm_ban(call: types.CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return
    await state.set_state(AdminStates.ban_user)
    await call.message.edit_text(
        "🚫 <b>Блокировка пользователя</b>\n\nВведите ID:",
        reply_markup=back_keyboard("adm_back"), parse_mode="HTML"
    )
    await call.answer()

@dp.message(AdminStates.ban_user)
async def do_ban(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        uid = int(message.text.strip())
        if uid == SUPER_ADMIN_ID or is_admin(uid):
            await message.answer("❌ Нельзя заблокировать администратора.")
            return
        conn = get_db()
        # ── БАГ 2 ИСПРАВЛЕН: ставим is_banned=1 вместо удаления из базы ──────
        conn.execute("UPDATE users SET is_banned=1 WHERE user_id=?", (uid,))
        conn.commit()
        conn.close()
        await state.clear()
        await message.answer(f"✅ Пользователь <code>{uid}</code> заблокирован.", parse_mode="HTML")
        try:
            await bot.send_message(uid, "🚫 Вы заблокированы администратором.")
        except Exception:
            pass
    except ValueError:
        await message.answer("❌ Введите числовой ID")

@dp.callback_query(F.data == "adm_unban")
async def adm_unban(call: types.CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return
    await state.set_state(AdminStates.unban_user)
    await call.message.edit_text(
        "✅ <b>Разблокировка пользователя</b>\n\nВведите ID пользователя:",
        reply_markup=back_keyboard("adm_back"), parse_mode="HTML"
    )
    await call.answer()

@dp.message(AdminStates.unban_user)
async def do_unban(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        uid = int(message.text.strip())
        conn = get_db()
        conn.execute("UPDATE users SET is_banned=0 WHERE user_id=?", (uid,))
        conn.commit()
        conn.close()
        await state.clear()
        await message.answer(f"✅ Пользователь <code>{uid}</code> разблокирован.", parse_mode="HTML")
        try:
            await bot.send_message(uid, "✅ Вы были разблокированы администратором. Напишите /start.")
        except Exception:
            pass
    except ValueError:
        await message.answer("❌ Введите числовой ID")

@dp.callback_query(F.data == "adm_ref_stats")
async def adm_ref_stats(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    conn = get_db()
    top = conn.execute(
        "SELECT user_id, username, full_name, ref_count FROM users ORDER BY ref_count DESC LIMIT 10"
    ).fetchall()
    conn.close()
    if not top:
        text = "📊 <b>Статистика пуста</b>"
    else:
        text = "📊 <b>Топ рефоводов:</b>\n\n"
        for i, u in enumerate(top, 1):
            uname = f"@{u['username']}" if u['username'] else u['full_name']
            text += f"{i}. {uname} — <b>{u['ref_count']} реф.</b>\n"
    await call.message.edit_text(text, reply_markup=back_keyboard("adm_back"), parse_mode="HTML")
    await call.answer()

@dp.callback_query(F.data == "adm_clear_snos")
async def adm_clear_snos(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    conn = get_db()
    conn.execute("DELETE FROM snos_requests")
    conn.commit()
    conn.close()
    await call.answer("✅ История очищена", show_alert=True)
    await call.message.edit_text("✅ <b>История сносов очищена.</b>", reply_markup=back_keyboard("adm_back"), parse_mode="HTML")

@dp.callback_query(F.data == "adm_back")
async def adm_back(call: types.CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return
    await state.clear()
    # ── БАГ 3 ИСПРАВЛЕН: оборачиваем delete в try/except ────────────────────
    try:
        await call.message.delete()
    except Exception:
        pass
    await show_admin(call.message)
    await call.answer()


# ── HTTP сервер для Render ───────────────────────────────────────────────────
from aiohttp import web

async def health(request):
    return web.Response(text="OK")

async def start_web():
    app = web.Application()
    app.router.add_get("/", health)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 8000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

# ── Запуск ─────────────────────────────────────────────────────────────────
async def main():
    init_db()
    logger.info("ExtraSnos bot starting...")
    await start_web()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
