"""Регистрация игрока и создание таверны."""

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot import texts
from bot.db import repo
from bot.game.balance import REGIONS
from bot.keyboards import inline as kb

router = Router()
router.message.filter(F.chat.type == "private")


class CreateTavern(StatesGroup):
    name = State()
    region = State()


@router.message(CommandStart())
async def cmd_start(message: Message, session: AsyncSession) -> None:
    player = await repo.get_player(session, message.from_user.id)
    if player and player.tavern:
        await message.answer(texts.ALREADY_REGISTERED)
        await message.answer(
            texts.tavern_screen(player, player.tavern),
            reply_markup=kb.tavern_kb(player),
        )
        return

    if not player:
        await repo.create_player(
            session,
            message.from_user.id,
            message.from_user.username,
            message.from_user.first_name,
        )
    await message.answer(texts.WELCOME, reply_markup=kb.create_tavern_kb())


@router.callback_query(F.data == "create_tavern")
async def cb_create_tavern(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(CreateTavern.name)
    await callback.message.edit_text(texts.ASK_TAVERN_NAME)
    await callback.answer()


@router.message(CreateTavern.name, F.text)
async def tavern_name(message: Message, state: FSMContext) -> None:
    name = message.text.strip()
    if len(name) > 40:
        await message.answer(texts.NAME_TOO_LONG)
        return
    await state.update_data(name=name)
    await state.set_state(CreateTavern.region)
    await message.answer(
        texts.ASK_REGION.format(name=name), reply_markup=kb.regions_kb()
    )


@router.callback_query(CreateTavern.region, F.data.startswith("region:"))
async def tavern_region(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    region = callback.data.split(":", 1)[1]
    data = await state.get_data()
    await state.clear()

    player = await repo.get_player(session, callback.from_user.id)
    if player is None:
        player = await repo.create_player(
            session,
            callback.from_user.id,
            callback.from_user.username,
            callback.from_user.first_name,
        )
    if player.tavern is None:
        await repo.create_tavern(session, player, data["name"], region)

    await callback.message.edit_text(
        texts.CREATED.format(name=data["name"], region=REGIONS[region])
    )
    await callback.message.answer(
        texts.tavern_screen(player, player.tavern),
        reply_markup=kb.tavern_kb(player),
    )
    await callback.answer()
