import disnake
from disnake.ext import commands
import random
import logging
import configparser
import os
import aiohttp

from utils.database import (
    get_user_balance,
    update_cash,
    get_user_inventory,
    remove_from_inventory,
    get_cock_fight_chance,
    update_cock_fight_chance
)
from config import currency, audit_webhook, make_audit_payload

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Загрузка конфигурации из games.ini
config = configparser.ConfigParser()
config_file = "games.ini"
if not os.path.exists(config_file):
    logger.error(f"Файл конфигурации {config_file} не найден.")
    raise FileNotFoundError(f"Файл конфигурации {config_file} не найден.")
config.read(config_file, encoding="utf-8")

def get_cock_fight_config():
    """Читает настройки CockFight из games.ini один раз."""
    section = config["CockFight"]
    min_bet = int(section.get("min_bet", 10))
    min_chance = int(section.get("min_chance", 50))
    max_chance = int(section.get("max_chance", 90))
    if min_bet < 1:
        raise ValueError("min_bet должен быть >= 1")
    if not (0 <= min_chance <= max_chance <= 100):
        raise ValueError(
            "min_chance/max_chance должны быть в диапазоне 0–100 и min_chance ≤ max_chance"
        )
    return {
        "min_bet": min_bet,
        "min_chance": min_chance,
        "max_chance": max_chance,
        "errors": {
            "insufficient_cash": "Недостаточно средств для ставки!",
            "no_chicken": "У вас нет курицы для участия в бою!",
            "invalid_bet": "Некорректная ставка. Укажите число, 'all', 'half' или формат 1e6.",
            "min_bet": f"Минимальная ставка: {min_bet} {currency}."
        }
    }

def create_win_embed(user: disnake.Member, winnings: int, chance: int, max_chance: int) -> disnake.Embed:
    embed = disnake.Embed(
        description=(
            f"<@{user.id}>, ваша курица победила! "
            f"Вы получили **{currency} {winnings:,}**! 🐓"
        ),
        color=0x2F3136
    )
    embed.set_footer(
        text=f"Сила курицы (шанс на победу): {min(chance + 1, max_chance)}%"
    )
    embed.set_author(
        name=user.display_name,
        icon_url=(user.avatar.url if user.avatar else user.default_avatar.url)
    )
    return embed

def create_loss_embed(user: disnake.Member) -> disnake.Embed:
    embed = disnake.Embed(
        description=f"<@{user.id}>, ваша курица проиграла и погибла 🪦",
        color=0x2F3136
    )
    embed.set_author(
        name=user.display_name,
        icon_url=(user.avatar.url if user.avatar else user.default_avatar.url)
    )
    return embed

def create_error_embed(msg: str, user_id: int) -> disnake.Embed:
    return disnake.Embed(
        title="Ошибка",
        description=f"<@{user_id}>, {msg}",
        color=0x2F3136
    )

class CockFightCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.cfg = get_cock_fight_config()
        self._session = None
        logger.info("CockFightCog initialized")

    def cog_unload(self):
        if self._session and not self._session.closed:
            self.bot.loop.create_task(self._session.close())

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def _send_audit(self, user_id: int, cash_change: int, bank_change: int, reason: str):
        payload = make_audit_payload(
            action="Обновление баланса",
            user_id=user_id,
            cash_change=cash_change,
            bank_change=bank_change,
            reason=reason
        )
        try:
            session = await self._get_session()
            await session.post(audit_webhook, json=payload)
        except Exception as e:
            logger.warning(f"Audit webhook error: {e}")

    async def validate_bet(self, user_id: int, guild_id: int, bet: str):
        """Поддерживает 'all', 'half', натуральные числа и формат 1e6."""
        cash, _ = await get_user_balance(user_id, guild_id)
        bet_l = bet.lower()
        if bet_l == "all":
            amount = cash
        elif bet_l == "half":
            amount = cash // 2
        else:
            try:
                if 'e' in bet_l:
                    amount = int(float(bet_l))
                else:
                    amount = int(bet_l)
            except ValueError:
                return None, "invalid_bet"
            if amount > cash:
                return None, "insufficient_cash"
        if amount < self.cfg["min_bet"]:
            return None, "min_bet"
        return amount, None

    async def deduct_bet(self, user_id: int, guild_id: int, amount: int) -> bool:
        cash, _ = await get_user_balance(user_id, guild_id)
        if cash < amount:
            return False
        await update_cash(user_id, guild_id, -amount)
        logger.info(f"Списано {amount:,} cash для ставки: user={user_id}")
        return True

    async def has_chicken(self, user_id: int) -> bool:
        for item_id, qty, name, *_ in await get_user_inventory(user_id):
            if name == "Chicken" and qty > 0:
                return True
        return False

    @commands.command(name="cock-fight", aliases=["cf"])
    async def cock_fight(self, ctx: commands.Context, bet: str):
        user_id = ctx.author.id
        guild_id = ctx.guild.id
        logger.info(f"CockFight called: user={user_id}, bet={bet}")

        amount, err = await self.validate_bet(user_id, guild_id, bet)
        if err:
            await ctx.send(embed=create_error_embed(self.cfg["errors"][err], user_id))
            return

        if not await self.has_chicken(user_id):
            await ctx.send(embed=create_error_embed(self.cfg["errors"]["no_chicken"], user_id))
            return

        if not await self.deduct_bet(user_id, guild_id, amount):
            await ctx.send(embed=create_error_embed(self.cfg["errors"]["insufficient_cash"], user_id))
            return

        chance = await get_cock_fight_chance(user_id, guild_id)
        if chance is None:
            chance = self.cfg["min_chance"]
            await update_cock_fight_chance(user_id, guild_id, chance)

        roll = random.randint(1, 100)
        win = roll <= chance
        logger.debug(f"Fight roll={roll} vs chance={chance} => win={win}")

        if win:
            winnings = amount * 2
            new_chance = min(chance + 1, self.cfg["max_chance"])
            await update_cash(user_id, guild_id, winnings)
            await update_cock_fight_chance(user_id, guild_id, new_chance)

            await self._send_audit(
                user_id=user_id,
                cash_change=winnings,
                bank_change=0,
                reason="Победа в куриных боях"
            )

            embed = create_win_embed(ctx.author, winnings, new_chance, self.cfg["max_chance"])
            logger.info(f"Victory: user={user_id}, +{winnings:,}, new_chance={new_chance}")

        else:
            chicken = next(
                (i for i in await get_user_inventory(user_id) if i[2] == "Chicken" and i[1] > 0),
                None
            )
            removed = False
            if chicken:
                await remove_from_inventory(user_id, chicken[0], 1)
                removed = True
                logger.info(f"Removed Chicken (item_id={chicken[0]}) for user={user_id}")
            else:
                logger.warning(f"No Chicken to remove for user={user_id}")

            await self._send_audit(
                user_id=user_id,
                cash_change=-amount,
                bank_change=0,
                reason="Поражение в куриных боях"
            )

            await update_cock_fight_chance(user_id, guild_id, self.cfg["min_chance"])
            embed = create_loss_embed(ctx.author)
            logger.info(f"Defeat: user={user_id}, -{amount:,}, chicken_removed={removed}")

        await ctx.send(embed=embed)

def setup(bot: commands.Bot):
    bot.add_cog(CockFightCog(bot))
    logger.info("CockFightCog loaded")
