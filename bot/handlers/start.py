"""Регистрация игрока и создание таверны."""

from html import escape

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot import images, texts
from bot.db import repo
from bot.game.balance import REGIONS
from bot.handlers import common
from bot.handlers.common import send_tavern_screen
from bot.keyboards import inline as kb

router = Router()
router.message.filter(F.chat.type == "private")


class CreateTavern(StatesGroup):
    name = State()
    region = State()


def _parse_ref(args: str | None, self_id: int) -> int | None:
    """Из payload `ref_<id>` достать id пригласившего (не себя). Иначе None."""
    if not args or not args.startswith("ref_"):
        return None
    raw = args[4:]
    if not raw.isdigit():
        return None
    rid = int(raw)
    return rid if rid != self_id else None


@router.message(CommandStart())
async def cmd_start(
    message: Message, session: AsyncSession, command: CommandObject
) -> None:
    player = await repo.get_player(session, message.from_user.id)
    if player and player.tavern:
        await message.answer(texts.ALREADY_REGISTERED)
        await send_tavern_screen(message, player)
        return

    if not player:
        player = await repo.create_player(
            session,
            message.from_user.id,
            message.from_user.username,
            message.from_user.first_name,
        )
        ref = _parse_ref(command.args, player.id)   # пришёл по зазыву — запоминаем (один раз)
        if ref is not None:
            player.referred_by = ref
    img = images.named_image("welcome")
    if img is not None:
        msg = await message.answer_photo(
            common.cached_media(img), caption=texts.WELCOME,
            reply_markup=kb.welcome_kb(),
        )
        common.remember_file_id(img, msg)
    else:
        await message.answer(texts.WELCOME, reply_markup=kb.welcome_kb())


@router.message(Command("help", "rules"))
async def cmd_help(message: Message) -> None:
    await message.answer(texts.RULES)


@router.callback_query(F.data == "create_tavern")
async def cb_create_tavern(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(CreateTavern.name)
    # welcome теперь фото-баннер — текст не отредактируешь, шлём вопрос отдельно.
    await callback.message.answer(texts.ASK_TAVERN_NAME)
    await callback.answer()


@router.message(CreateTavern.name, F.text)
async def tavern_name(message: Message, state: FSMContext) -> None:
    name = message.text.strip()
    if not 2 <= len(name) <= 40:
        await message.answer(texts.NAME_TOO_LONG)
        return
    await state.update_data(name=name)
    await state.set_state(CreateTavern.region)
    await message.answer(
        texts.ASK_REGION.format(name=escape(name)), reply_markup=kb.regions_kb()
    )


@router.callback_query(CreateTavern.region, F.data.startswith("region:"))
async def tavern_region(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    region = callback.data.split(":", 1)[1]
    data = await state.get_data()
    await state.clear()

    name = data.get("name")
    if not name:  # стейт сбросился (рестарт/устаревшая кнопка) — начать заново
        await callback.answer("Что-то сбилось. Начни заново: /start", show_alert=True)
        return

    player = await repo.get_player(session, callback.from_user.id)
    if player is None:
        player = await repo.create_player(
            session,
            callback.from_user.id,
            callback.from_user.username,
            callback.from_user.first_name,
        )
        await session.refresh(player, ["tavern"])  # свежий объект: связь явно (MissingGreenlet)
    chest = None
    ref_bonus = None
    if player.tavern is None:
        tavern = await repo.create_tavern(session, player, name, region)
        await repo.assign_map_slot(session, tavern, region)
        repo.add_log(session, "player", player.id,
                     f"🏗 завёл таверну «{name}» в регионе {REGIONS[region]}")
        from bot.game import newbie
        chest = newbie.grant_chest(player)  # стартовый сундук новосёла
        ref_bonus = await repo.grant_referral_rewards(session, player)  # зазыв активирован

    await callback.message.edit_text(
        texts.CREATED.format(name=escape(name), region=REGIONS[region])
    )
    if chest:
        await callback.message.answer(texts.starter_chest(chest))
    if ref_bonus:
        await callback.message.answer(texts.referral_welcome(ref_bonus["invitee_gold"]))
    await send_tavern_screen(callback.message, player)
    await callback.answer()
