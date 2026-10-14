import asyncio
import logging
import io
import math
import sqlite3

from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message, BufferedInputFile, InlineKeyboardMarkup,
    InlineKeyboardButton, CallbackQuery, LabeledPrice, PreCheckoutQuery
)
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from PIL import Image, ImageDraw, ImageFont

# ================= НАСТРОЙКИ БОТА =================
API_TOKEN = "8650177831:AAHbaiDIMWlsiPAurdSOhFohMDKJ2r636SA"  # Вставьте сюда токен вашего бота
PHOTO_COST_APPLES = 10                 # Стоимость одной генерации в Яблоках
# ==================================================

bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

class WatermarkStates(StatesGroup):
    waiting_for_text = State()
    waiting_for_promo = State()

def init_db():
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, apples INTEGER DEFAULT 20)")
    cursor.execute("CREATE TABLE IF NOT EXISTS activated_promos (user_id INTEGER, promo_code TEXT, PRIMARY KEY (user_id, promo_code))")
    conn.commit()
    conn.close()

init_db()


def get_user_apples(user_id: int) -> int:
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT apples FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if row is None:
        cursor.execute("INSERT INTO users (user_id, apples) VALUES (?, 20)", (user_id,))
        conn.commit()
        conn.close()
        return 20
    conn.close()
    return row[0]


def update_user_apples(user_id: int, amount: int):
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET apples = apples + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    conn.close()


def check_and_use_promo(user_id: int, promo_code: str) -> int:
    promo_code = promo_code.upper().strip()
    VALID_PROMOS = {"APPLE2026": 50}

    if promo_code not in VALID_PROMOS:
        return 0

    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM activated_promos WHERE user_id = ? AND promo_code = ?", (user_id, promo_code))
    if cursor.fetchone() is not None:
        conn.close()
        return -1

    cursor.execute("INSERT INTO activated_promos (user_id, promo_code) VALUES (?, ?)", (user_id, promo_code))
    cursor.execute("UPDATE users SET apples = apples + ? WHERE user_id = ?", (VALID_PROMOS[promo_code], user_id))
    conn.commit()
    conn.close()
    return VALID_PROMOS[promo_code]
def get_welcome_menu(user_id: int):
    apples = get_user_apples(user_id)
    buttons = [
        [InlineKeyboardButton(text=f"📸 Наложить знак ({PHOTO_COST_APPLES} 🍎)", callback_data="go_watermark")],
        [InlineKeyboardButton(text=f"💰 Мой Баланс: {apples} 🍎", callback_data="go_balance")],
        [InlineKeyboardButton(text="⚙️ Настройки знака", callback_data="go_settings")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_balance_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Пополнить баланс", callback_data="sub_buy_menu")],
        [InlineKeyboardButton(text="🎁 Промокод", callback_data="use_promo")],
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="back_to_welcome")]
    ])

def get_buy_options_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🍎 Пакет 10 Яблок", callback_data="buy_10")],
        [InlineKeyboardButton(text="🍎 Пакет 50 Яблок", callback_data="buy_50")],
        [InlineKeyboardButton(text="🍎 Пакет 150 Яблок", callback_data="buy_150")],
        [InlineKeyboardButton(text="🔙 Назад к балансу", callback_data="go_balance")]
    ])

def get_positions_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="↖️ Сверху слева", callback_data="pos_top_left"), InlineKeyboardButton(text="↗️ Сверху справа", callback_data="pos_top_right")],
        [InlineKeyboardButton(text="      🔄 По центру      ", callback_data="pos_center")],
        [InlineKeyboardButton(text="↙️ Снизу слева", callback_data="pos_bottom_left"), InlineKeyboardButton(text="↘️ Снизу справа", callback_data="pos_bottom_right")],
        [InlineKeyboardButton(text="🔙 Назад к настройкам", callback_data="go_settings")]
    ])

def get_sizes_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 Мелкий", callback_data="size_small"), InlineKeyboardButton(text="👁 Средний", callback_data="size_medium"), InlineKeyboardButton(text="📢 Крупный", callback_data="size_large")],
        [InlineKeyboardButton(text="🔙 Назад к настройкам", callback_data="go_settings")]
    ])

def get_opacity_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✨ Легкая (30%)", callback_data="op_light"), InlineKeyboardButton(text="🌓 Средняя (55%)", callback_data="op_medium"), InlineKeyboardButton(text="🕶 Плотная (85%)", callback_data="op_dark")],
        [InlineKeyboardButton(text="🔙 Назад к настройкам", callback_data="go_settings")]
    ])

def get_after_generation_menu():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 В главное меню", callback_data="back_to_welcome_new")]])


def get_settings_menu(user_data):
    is_bold = user_data.get("is_bold", False)
    is_grid = user_data.get("is_grid", False)
    is_stroke = user_data.get("is_stroke", True)
    color = user_data.get("color", "white")

    bold_status = "🟢 Да" if is_bold else "⚪ Нет"
    grid_status = "🟥 Сетка (Всё фото)" if is_grid else "🟦 Одиночный (Угол)"
    color_status = "⚪ Белый" if color == "white" else "⚫ Черный"
    stroke_status = "🟢 Да" if is_stroke else "⚪ Нет"

    buttons = [
        [InlineKeyboardButton(text="📝 Изменить текст", callback_data="change_text")],
        [InlineKeyboardButton(text=f"🔄 Режим: {grid_status}", callback_data="toggle_grid")]
    ]
    if not is_grid:
        buttons.append([InlineKeyboardButton(text="📐 Изменить положение", callback_data="change_position")])

    buttons.extend([
        [InlineKeyboardButton(text="📏 Изменить размер", callback_data="change_size")],
        [InlineKeyboardButton(text=f"🎨 Цвет: {color_status}", callback_data="toggle_color")],
        [InlineKeyboardButton(text=f"🖼 Контур (Обводка): {stroke_status}", callback_data="toggle_stroke")],
        [InlineKeyboardButton(text="👁 Настроить прозрачность", callback_data="change_opacity")],
        [InlineKeyboardButton(text=f"🔤 Жирный шрифт: {bold_status}", callback_data="toggle_bold")],
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="back_to_welcome")]
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def add_watermark(image_bytes: io.BytesIO, text: str, position: str, size_type: str,
                  is_bold: bool, is_grid: bool, color: str, opacity_type: str, is_stroke: bool) -> io.BytesIO:
    base_image = Image.open(image_bytes).convert("RGBA")
    width, height = base_image.size

    size_multipliers = {"small": 0.025, "medium": 0.045, "large": 0.07}
    multiplier = size_multipliers.get(size_type, 0.045)
    font_size = max(14, int(width * multiplier))

    is_default_font = False
    try:
        font = ImageFont.truetype("arial.ttf", font_size)
    except IOError:
        try:
            font = ImageFont.truetype("DejaVuSans.ttf", font_size)
        except IOError:
            font = ImageFont.load_default()
            is_default_font = True

    opacity_values = {"light": 75, "medium": 140, "dark": 215}
    alpha = opacity_values.get(opacity_type, 140)

    if color == "black":
        text_color, stroke_color = (0, 0, 0, alpha), (255, 255, 255, alpha)
    else:
        text_color, stroke_color = (255, 255, 255, alpha), (0, 0, 0, alpha)

    if is_default_font:
        stroke_width = 0
    else:
        if is_stroke:
            stroke_width = max(1, int(font_size * 0.12)) if is_bold else max(1, int(font_size * 0.04))
        else:
            stroke_width = max(1, int(font_size * 0.06)) if is_bold else 0
            stroke_color = text_color

    temp_draw = ImageDraw.Draw(base_image)
    text_bbox = temp_draw.textbbox((0, 0), text, font=font, stroke_width=stroke_width)
    text_w = text_bbox[2] - text_bbox[0]
    text_h = text_bbox[3] - text_bbox[1]

    if is_grid:
        diag = int(math.sqrt(width ** 2 + height ** 2))
        txt_layer = Image.new("RGBA", (diag, diag), (255, 255, 255, 0))
        draw = ImageDraw.Draw(txt_layer)
        step_w, step_h = text_w + font_size * 2, text_h + font_size * 3

        for y_pos in range(0, diag, step_h):
            shift = (y_pos // step_h % 2) * (step_w // 2)
            for x_pos in range(-step_w, diag, step_w):
                draw.text((x_pos + shift, y_pos), text, fill=text_color, font=font, stroke_width=stroke_width,
                          stroke_fill=stroke_color)

        txt_layer = txt_layer.rotate(45, resample=Image.BICUBIC)
        start_x, start_y = (diag - width) // 2, (diag - height) // 2
        txt_layer = txt_layer.crop((start_x, start_y, start_x + width, start_y + height))
        watermarked_image = Image.alpha_composite(base_image, txt_layer)
    else:
        txt_layer = Image.new("RGBA", base_image.size, (255, 255, 255, 0))
        draw = ImageDraw.Draw(txt_layer)
        padding_x, padding_y = int(width * 0.05), int(height * 0.05)

        if position == "top_left":
            x, y = padding_x, padding_y
        elif position == "top_right":
            x, y = width - text_w - padding_x, padding_y
        elif position == "bottom_left":
            x, y = padding_x, height - text_h - padding_y
        elif position == "bottom_right":
            x, y = width - text_w - padding_x, height - text_h - padding_y
        else:
            x, y = (width - text_w) // 2, (height - text_h) // 2

        draw.text((x, y), text, fill=text_color, font=font, stroke_width=stroke_width, stroke_fill=stroke_color)
        watermarked_image = Image.alpha_composite(base_image, txt_layer)

    output_bytes = io.BytesIO()
    final_image = watermarked_image.convert("RGB")
    final_image.save(output_bytes, format="JPEG", quality=90)
    output_bytes.seek(0)
    return output_bytes
def get_settings_text(user_data: dict) -> str:
    ru_positions = {"center": "По центру", "top_left": "Сверху слева", "top_right": "Сверху справа", "bottom_left": "Снизу слева", "bottom_right": "Снизу справа"}
    ru_sizes = {"small": "Мелкий", "medium": "Средний", "large": "Крупный"}
    ru_opacities = {"light": "Легкая (30%)", "medium": "Средняя (55%)", "dark": "Плотная (85%)"}
    is_grid = user_data.get("is_grid", False)
    pos = "Сетка (По всему фото) 🟥" if is_grid else ru_positions.get(user_data.get("position"), "По центру")
    return (
        f"🛠 **Экран настройки параметров:**\n\n"
        f"📝 Текст: `{user_data.get('text')}`\n"
        f"📐 Расположение: `{pos}`\n"
        f"📏 Размер текста: `{ru_sizes.get(user_data.get('size'), 'Средний')}`\n"
        f"🎨 Цвет шрифта: `{'Белый ⚪' if user_data.get('color') == 'white' else 'Черный ⚫'}`\n"
        f"🖼 Обводка (Контур): `{'Да' if user_data.get('is_stroke', True) else 'Нет'}`\n"
        f"👁 Прозрачность: `{ru_opacities.get(user_data.get('opacity'), 'Средняя (55%)')}`\n"
        f"🔤 Жирный шрифт: `{'Да' if user_data.get('is_bold') else 'Нет'}`\n\n"
        f"Измените конфигурацию с помощью кнопок:"
    )

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    user_id = message.from_user.id
    user_data = await state.get_data()
    text = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name
    if "text" not in user_data:
        default_settings = {"text": text, "position": "center", "size": "medium", "is_bold": False, "is_grid": False, "color": "white", "opacity": "medium", "is_stroke": True}
        await state.update_data(**default_settings)
    await message.answer(f"Привет, {message.from_user.full_name}! 👋\n\nЯ накладываю водяные знаки на фото. Одна генерация стоит всего {PHOTO_COST_APPLES} 🍎.\nВаш баланс: {get_user_apples(user_id)} 🍎\n\nВыберите действие:", reply_markup=get_welcome_menu(user_id))

@dp.callback_query(F.data == "back_to_welcome")
async def back_to_welcome(callback: CallbackQuery):
    user_id = callback.from_user.id
    await callback.message.edit_text(f"Главное меню.\nОдна генерация стоит {PHOTO_COST_APPLES} 🍎. Чтобы наложить знак, просто пришлите мне фото в чат.\n\nВаш текущий баланс: {get_user_apples(user_id)} 🍎", reply_markup=get_welcome_menu(user_id))
    await callback.answer()

@dp.callback_query(F.data == "go_watermark")
async def go_watermark_info(callback: CallbackQuery):
    await callback.message.answer(f"📥 **Отлично! Отправьте мне любую фотографию.**\n\n"f"⚠️ *Обязательно проверьте настройки для точной генерации!*\nС вашего баланса спишется {PHOTO_COST_APPLES} 🍎 за её обработку.", parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "go_balance")
async def go_balance_screen(callback: CallbackQuery):
    user_id = callback.from_user.id
    await callback.message.edit_text(f"💰 **Управление балансом Яблок**\n\nВаш баланс: **{get_user_apples(user_id)} 🍎**\nСтоимость одной генерации: **{PHOTO_COST_APPLES} 🍎**\n\nВыберите действие:", reply_markup=get_balance_menu(), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "sub_buy_menu")
async def sub_buy_menu(callback: CallbackQuery):
    await callback.message.edit_text("🛒 **Выбор пакета для пополнения:**\n\n📈 **Курс конвертации:** `1 ⭐️ = 5 🍎`\n\nВыберите желаемое количество 🍎 для покупки через Telegram Stars:", reply_markup=get_buy_options_menu(), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "go_settings")
async def go_settings_screen(callback: CallbackQuery, state: FSMContext):
    user_data = await state.get_data()
    await callback.message.edit_text(get_settings_text(user_data), reply_markup=get_settings_menu(user_data), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "use_promo")
async def start_promo_activation(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("🎁 Введите секретный промокод для получения бесплатных 🍎:")
    await state.set_state(WatermarkStates.waiting_for_promo)
    await callback.answer()

@dp.message(WatermarkStates.waiting_for_promo)
async def process_promo_code(message: Message, state: FSMContext):
    user_id = message.from_user.id
    result = check_and_use_promo(user_id, message.text.strip())
    if result > 0:
        await message.answer(f"🎉 Успешно! Промокод активирован.\nВам начислено **+{result} 🍎**.\nВаш текущий баланс: **{get_user_apples(user_id)} 🍎**.", reply_markup=get_welcome_menu(user_id), parse_mode="Markdown")
    elif result == -1:
        await message.answer("❌ Вы уже активировали этот промокод ранее!", reply_markup=get_welcome_menu(user_id))
    else:
        await message.answer("❌ Неверный или уже истекший промокод.", reply_markup=get_welcome_menu(user_id))
    await state.set_state(None)


@dp.callback_query(F.data == "change_text")
async def process_change_text(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("📝 Введите новый текст:")
    await state.set_state(WatermarkStates.waiting_for_text)
    await callback.answer()


@dp.message(WatermarkStates.waiting_for_text)
async def save_new_text(message: Message, state: FSMContext):
    await state.update_data(text=message.text.strip())
    user_data = await state.get_data()
    await message.answer(f"✅ Изменено!\n\n{get_settings_text(user_data)}", reply_markup=get_settings_menu(user_data),
                         parse_mode="Markdown")
    await state.set_state(None)


@dp.callback_query(F.data == "toggle_grid")
async def toggle_grid(callback: CallbackQuery, state: FSMContext):
    user_data = await state.get_data()
    new_grid = not user_data.get("is_grid", False)
    await state.update_data(is_grid=new_grid)
    user_data["is_grid"] = new_grid
    await callback.message.edit_text(get_settings_text(user_data), reply_markup=get_settings_menu(user_data),
                                     parse_mode="Markdown")
    await callback.answer()


@dp.callback_query(F.data == "change_position")
async def process_change_position(callback: CallbackQuery):
    await callback.message.edit_text("📐 Выберите положение:", reply_markup=get_positions_menu())
    await callback.answer()


@dp.callback_query(F.data.startswith("pos_"))
async def save_position(callback: CallbackQuery, state: FSMContext):
    await state.update_data(position=callback.data.replace("pos_", ""))
    user_data = await state.get_data()
    await callback.message.edit_text(get_settings_text(user_data), reply_markup=get_settings_menu(user_data),
                                     parse_mode="Markdown")
    await callback.answer()


@dp.callback_query(F.data == "change_size")
async def process_change_size(callback: CallbackQuery):
    await callback.message.edit_text("📏 Выберите размер текста:", reply_markup=get_sizes_menu())
    await callback.answer()


@dp.callback_query(F.data.startswith("size_"))
async def save_size(callback: CallbackQuery, state: FSMContext):
    await state.update_data(size=callback.data.replace("size_", ""))
    user_data = await state.get_data()
    await callback.message.edit_text(get_settings_text(user_data), reply_markup=get_settings_menu(user_data),
                                     parse_mode="Markdown")
    await callback.answer()


@dp.callback_query(F.data == "toggle_color")
async def toggle_color(callback: CallbackQuery, state: FSMContext):
    user_data = await state.get_data()
    new_color = "black" if user_data.get("color", "white") == "white" else "white"
    await state.update_data(color=new_color)
    user_data["color"] = new_color
    await callback.message.edit_text(get_settings_text(user_data), reply_markup=get_settings_menu(user_data),
                                     parse_mode="Markdown")
    await callback.answer()


@dp.callback_query(F.data == "toggle_stroke")
async def toggle_stroke(callback: CallbackQuery, state: FSMContext):
    user_data = await state.get_data()
    new_stroke = not user_data.get("is_stroke", True)
    await state.update_data(is_stroke=new_stroke)
    user_data["is_stroke"] = new_stroke
    await callback.message.edit_text(get_settings_text(user_data), reply_markup=get_settings_menu(user_data),
                                     parse_mode="Markdown")
    await callback.answer()


@dp.callback_query(F.data == "change_opacity")
async def process_change_opacity(callback: CallbackQuery):
    await callback.message.edit_text("👁 Выберите уровень прозрачности:", reply_markup=get_opacity_menu())
    await callback.answer()


@dp.callback_query(F.data.startswith("op_"))
async def save_opacity(callback: CallbackQuery, state: FSMContext):
    await state.update_data(opacity=callback.data.replace("op_", ""))
    user_data = await state.get_data()
    await callback.message.edit_text(get_settings_text(user_data), reply_markup=get_settings_menu(user_data),
                                     parse_mode="Markdown")
    await callback.answer()


@dp.callback_query(F.data == "toggle_bold")
async def toggle_bold(callback: CallbackQuery, state: FSMContext):
    user_data = await state.get_data()
    new_bold = not user_data.get("is_bold", False)
    await state.update_data(is_bold=new_bold)
    user_data["is_bold"] = new_bold
    await callback.message.edit_text(get_settings_text(user_data), reply_markup=get_settings_menu(user_data),
                                     parse_mode="Markdown")
    await callback.answer()


@dp.callback_query(F.data.in_({"buy_10", "buy_50", "buy_150"}))
async def process_buy_apples(callback: CallbackQuery):
    stars_amount = 2 if callback.data == "buy_10" else (10 if callback.data == "buy_50" else 30)
    apples_to_add = 10 if callback.data == "buy_10" else (50 if callback.data == "buy_50" else 150)
    await callback.message.answer_invoice(title=f"Покупка {apples_to_add} Яблок",
                                          description=f"Пополнение баланса бота на {apples_to_add} Яблок для генерации водяных знаков",
                                          prices=[LabeledPrice(label=f"Пакет +{apples_to_add} Яблок 🍎",
                                                               amount=stars_amount)], provider_token="",
                                          payload=f"add_{apples_to_add}", currency="XTR")
    await callback.answer()


@dp.pre_checkout_query()
async def process_pre_checkout(pre_checkout_query: PreCheckoutQuery):
    await pre_checkout_query.answer(ok=True)


@dp.message(F.successful_payment)
async def process_successful_payment(message: Message):
    apples_to_add = int(message.successful_payment.invoice_payload.replace("add_", ""))
    user_id = message.from_user.id
    update_user_apples(user_id, apples_to_add)
    await message.answer(
        f"✅ Оплата успешна! На ваш баланс зачислено **+{apples_to_add} 🍎**.\nВаш текущий баланс: **{get_user_apples(user_id)} 🍎**.")


@dp.message(F.photo)
async def handle_photo_with_balance(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if get_user_apples(user_id) < PHOTO_COST_APPLES:
        await message.answer(
            f"❌ Недостаточно Яблок на балансе!\nДля генерации водяного знака требуется **{PHOTO_COST_APPLES} 🍎**.\nУ вас на счету: **{get_user_apples(user_id)} 🍎**.\n\nПополните баланс в главном меню бота.",
            parse_mode="Markdown")
        return
    status_msg = await message.answer("🔄 Списываю яблоки и накладываю водяной знак...")
    try:
        user_data = await state.get_data()
        photo_bytes = io.BytesIO()
        await bot.download(message.photo[-1].file_id, destination=photo_bytes)
        photo_bytes.seek(0)

        loop = asyncio.get_event_loop()
        processed_bytes = await loop.run_in_executor(None, add_watermark, photo_bytes,
                                                     user_data.get("text", message.from_user.first_name),
                                                     user_data.get("position", "center"),
                                                     user_data.get("size", "medium"), user_data.get("is_bold", False),
                                                     user_data.get("is_grid", False), user_data.get("color", "white"),
                                                     user_data.get("opacity", "medium"),
                                                     user_data.get("is_stroke", True))

        update_user_apples(user_id, -PHOTO_COST_APPLES)
        await message.answer_photo(photo=BufferedInputFile(processed_bytes.read(), filename="watermarked.jpg"),
                                   caption=f"Изображение готово! ✅\nСписано: {PHOTO_COST_APPLES} 🍎. Остаток: {get_user_apples(user_id)} 🍎",
                                   reply_markup=get_after_generation_menu())
        await status_msg.delete()
    except Exception as e:
        logging.error(f"Ошибка обработки: {e}")
        await status_msg.edit_text("❌ Ошибка при обработке. Яблоки не были списаны. Попробуйте еще раз.")


@dp.callback_query(F.data == "back_to_welcome_new")
async def process_back_to_welcome_after_photo(callback: CallbackQuery):
    user_id = callback.from_user.id
    await callback.message.answer(
        f"Вы вернулись в главное меню.\nСтоимость одной генерации: {PHOTO_COST_APPLES} 🍎.\nВаш текущий баланс: {get_user_apples(user_id)} 🍎",
        reply_markup=get_welcome_menu(user_id))
    await callback.answer()


async def main():
    logging.basicConfig(level=logging.INFO)
    print("Игровой бот на Красных Яблоках и Telegram Stars успешно запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
