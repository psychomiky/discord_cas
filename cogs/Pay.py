import disnake
from disnake.ext import commands
import logging
import configparser
import os
import time
import math
import random
import asyncio
from typing import Union
from utils.database import get_user_balance, ensure_user_exists, get_cooldown, update_cooldown, transfer_cash
from config import currency, GIVEMONEY_SUCCESS_MESSAGES, GIVEMONEY_FAIL_MESSAGES, GIVEMONEY_INSUFFICIENT_FUNDS_MESSAGES, GIVEMONEY_ERROR_MESSAGES, GIVEMONEY_COOLDOWN_MESSAGES, GIVEMONEY_NOTICE_MESSAGES

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Чтение конфигурации из config.ini
config = configparser.ConfigParser()
config_file = "config.ini"

if not os.path.exists(config_file):
    logger.error(f"Config file {config_file} not found.")
    raise FileNotFoundError(f"Config file {config_file} not found.")

try:
    config.read(config_file, encoding='utf-8')
except Exception as e:
    logger.error(f"Failed to read config.ini: {e}")
    raise

def create_embed(embed_type, user, message=None, error_message=None, total=None, amount=None, fee=None, received=None, required=None, available=None):
    """Создание эмбеда для различных типов сообщений."""
    embed = disnake.Embed(color=0x2F3136)
    # Установка автора с именем и аватаром пользователя
    embed.set_author(
        name=user.display_name,
        icon_url=user.avatar.url if user.avatar else user.default_avatar.url
    )

    if embed_type == "success":
        embed.description = f"✅ {user.mention} получил ваши {currency}"
        if amount is not None:
            embed.add_field(name="Сумма перевода", value=f"{amount} {currency}", inline=True)
        if fee is not None:
            embed.add_field(name="Налог", value=f"{fee} {currency}", inline=True)
        if received is not None:
            embed.add_field(name="Получено", value=f"{received} {currency}", inline=True)
        if total is not None:
            embed.add_field(name="Ваш баланс", value=f"{total} {currency}", inline=False)
    elif embed_type == "error":
        embed.title = "🚫 Ошибка"
        embed.description = error_message
    elif embed_type == "insufficient_funds":
        embed.title = "🚫 Недостаточно средств"
        embed.description = message
    elif embed_type == "cooldown":
        embed.title = "⏳ Кулдаун"
        embed.description = message
    elif embed_type == "notice":
        embed.title = "📢 Уведомление"
        embed.description = message
    return embed

def get_command_config(command_name):
    """Получение настроек для команды из config.ini."""
    try:
        section = config[command_name]
        cooldown = int(section.get("cooldown", 3))
        banned_roles = section.get("banned_roles", "[]")
        reduce_tax_roles = section.get("reduce_tax_roles", "[]")
        try:
            banned_roles = eval(banned_roles)
            reduce_tax_roles = eval(reduce_tax_roles)
            if not isinstance(banned_roles, list) or not isinstance(reduce_tax_roles, list):
                raise ValueError("banned_roles and reduce_tax_roles must be lists")
        except Exception as e:
            logger.error(f"Invalid roles format for {command_name}: {e}")
            raise ValueError(f"Invalid roles format for {command_name}")

        min_amount = int(section.get("min_amount", 0))
        max_amount = int(section.get("max_amount", 1000))
        tax_percentage = float(section.get("tax_percentage", 10))
        reduce_tax_percentage = float(section.get("reduce_tax_percentage", 5))

        if min_amount < 0 or max_amount < 0:
            raise ValueError("min_amount and max_amount cannot be negative")
        if max_amount != 0 and min_amount > max_amount:
            raise ValueError("min_amount cannot be greater than max_amount")
        if not (0 <= tax_percentage <= 100) or not (0 <= reduce_tax_percentage <= 100):
            raise ValueError("tax_percentage and reduce_tax_percentage must be between 0 and 100")

        logger.info(f"Loaded config for {command_name}: cooldown={cooldown}s, banned_roles={banned_roles}, reduce_tax_roles={reduce_tax_roles}, min_amount={min_amount}, max_amount={max_amount}, tax_percentage={tax_percentage}%, reduce_tax_percentage={reduce_tax_percentage}%")
        
        return {
            "cooldown": cooldown,
            "banned_roles": banned_roles,
            "reduce_tax_roles": reduce_tax_roles,
            "min_amount": min_amount,
            "max_amount": max_amount,
            "tax_percentage": tax_percentage,
            "reduce_tax_percentage": reduce_tax_percentage,
            "success_messages": GIVEMONEY_SUCCESS_MESSAGES,
            "fail_messages": GIVEMONEY_FAIL_MESSAGES,
            "insufficient_funds_messages": GIVEMONEY_INSUFFICIENT_FUNDS_MESSAGES,
            "error_messages": GIVEMONEY_ERROR_MESSAGES,
            "cooldown_messages": GIVEMONEY_COOLDOWN_MESSAGES,
            "notice_messages": GIVEMONEY_NOTICE_MESSAGES,
        }
    except KeyError as e:
        logger.error(f"Invalid config section for {command_name}: {e}")
        raise ValueError(f"Invalid config section for {command_name}")
    except Exception as e:
        logger.error(f"Error parsing config for {command_name}: {e}")
        raise ValueError(f"Error parsing config for {command_name}")

class PayCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def check_cooldown(self, ctx, command_name: str, cooldown: int):
        """Проверка кулдауна команды."""
        user_id = ctx.author.id
        guild_id = ctx.guild.id
        current_time = int(time.time())
        last_used = await get_cooldown(user_id, guild_id, command_name)

        if last_used is not None:
            time_passed = current_time - last_used
            if time_passed < cooldown:
                remaining = cooldown - time_passed
                minutes, seconds = divmod(remaining, 60)
                message = random.choice(GIVEMONEY_COOLDOWN_MESSAGES).format(
                    command_name=command_name.lower(),
                    minutes=minutes,
                    seconds=seconds
                )
                embed = create_embed(
                    embed_type="cooldown",
                    user=ctx.author,
                    message=message
                )
                await ctx.send(embed=embed)
                logger.info(f"User {user_id} tried {command_name} but on cooldown: {remaining}s remaining")
                return False
        return True

    async def transfer_money(self, ctx, user: disnake.Member, amount: Union[int, str]):
        """Общая логика перевода денег."""
        sender_id = ctx.author.id
        guild_id = ctx.guild.id
        receiver_id = user.id

        logger.debug(f"User {sender_id} invoked transfer command with target {receiver_id}, amount {amount}")

        # Проверка получателя
        if receiver_id == sender_id:
            message = random.choice(GIVEMONEY_ERROR_MESSAGES).format(error="нельзя перевести деньги самому себе")
            embed = create_embed(
                embed_type="error",
                user=ctx.author,
                error_message=message
            )
            await ctx.send(embed=embed)
            logger.info(f"User {sender_id} tried to transfer to themselves")
            return
        if user.bot:
            message = random.choice(GIVEMONEY_ERROR_MESSAGES).format(error="нельзя перевести деньги боту")
            embed = create_embed(
                embed_type="error",
                user=ctx.author,
                error_message=message
            )
            await ctx.send(embed=embed)
            logger.info(f"User {sender_id} tried to transfer to a bot")
            return

        # Проверка конфигурации
        try:
            config = get_command_config("Pay")
        except ValueError as e:
            message = random.choice(GIVEMONEY_ERROR_MESSAGES).format(error=f"ошибка конфигурации: {str(e)}")
            embed = create_embed(
                embed_type="error",
                user=ctx.author,
                error_message=message
            )
            await ctx.send(embed=embed)
            logger.error(f"Config error for transfer command: {e}")
            return

        # Проверка кулдауна
        if not await self.check_cooldown(ctx, "pay", config["cooldown"]):
            return

        # Проверка ролей
        user_roles = [role.id for role in ctx.author.roles]
        banned_roles = config["banned_roles"]
        reduce_tax_roles = config["reduce_tax_roles"]

        if any(role_id in banned_roles for role_id in user_roles):
            message = random.choice(GIVEMONEY_ERROR_MESSAGES).format(error="у вас есть роль, запрещающая перевод денег")
            embed = create_embed(
                embed_type="error",
                user=ctx.author,
                error_message=message
            )
            await ctx.send(embed=embed)
            logger.info(f"User {sender_id} has banned role for transfer")
            return

        # Расчёт налога
        fee_percent = config["tax_percentage"]
        for role_id in user_roles:
            if role_id in reduce_tax_roles:
                fee_percent = config["reduce_tax_percentage"]
                break
        fee = math.ceil(amount * (fee_percent / 100)) if isinstance(amount, int) else None
        amount_to_receive = amount - fee if isinstance(amount, int) and fee is not None else None

        # Проверка суммы
        if isinstance(amount, str):
            if amount.lower() not in ["all", "half"]:
                message = random.choice(GIVEMONEY_ERROR_MESSAGES).format(error="неверная сумма: используйте число, 'all' или 'half'")
                embed = create_embed(
                    embed_type="error",
                    user=ctx.author,
                    error_message=message
                )
                await ctx.send(embed=embed)
                logger.info(f"User {sender_id} provided invalid amount string: {amount}")
                return

            # Получение баланса отправителя
            sender_cash, _ = await get_user_balance(sender_id, guild_id)
            if sender_cash <= 0:
                message = random.choice(GIVEMONEY_ERROR_MESSAGES).format(error="у вас нет денег для перевода")
                embed = create_embed(
                    embed_type="error",
                    user=ctx.author,
                    error_message=message
                )
                await ctx.send(embed=embed)
                logger.info(f"User {sender_id} has no cash for 'all' or 'half' transfer")
                return

            if amount.lower() == "all":
                amount = sender_cash
                logger.info(f"User {sender_id} used 'all', transferring full cash: {amount}")
            elif amount.lower() == "half":
                amount = sender_cash // 2
                logger.info(f"User {sender_id} used 'half', transferring half cash: {amount}")

            # Пересчёт налога и полученной суммы
            fee = math.ceil(amount * (fee_percent / 100))
            amount_to_receive = amount - fee

        if amount <= 0:
            message = random.choice(GIVEMONEY_ERROR_MESSAGES).format(error="сумма перевода должна быть больше 0")
            embed = create_embed(
                embed_type="error",
                user=ctx.author,
                error_message=message
            )
            await ctx.send(embed=embed)
            logger.info(f"User {sender_id} tried to transfer invalid amount: {amount}")
            return

        min_amount = config["min_amount"]
        max_amount = config["max_amount"]
        if min_amount > 0 and amount < min_amount:
            message = random.choice(GIVEMONEY_ERROR_MESSAGES).format(error=f"минимальная сумма перевода: {min_amount} {currency}")
            embed = create_embed(
                embed_type="error",
                user=ctx.author,
                error_message=message
            )
            await ctx.send(embed=embed)
            logger.info(f"User {sender_id} tried to transfer below min_amount: {amount} < {min_amount}")
            return
        if max_amount > 0 and amount > max_amount:
            message = random.choice(GIVEMONEY_ERROR_MESSAGES).format(error=f"максимальная сумма перевода: {max_amount} {currency}")
            embed = create_embed(
                embed_type="error",
                user=ctx.author,
                error_message=message
            )
            await ctx.send(embed=embed)
            logger.info(f"User {sender_id} tried to transfer above max_amount: {amount} > {max_amount}")
            return

        if amount_to_receive <= 0:
            message = random.choice(GIVEMONEY_ERROR_MESSAGES).format(error=f"сумма после налога ({amount_to_receive} {currency}) должна быть больше 0")
            embed = create_embed(
                embed_type="error",
                user=ctx.author,
                error_message=message
            )
            await ctx.send(embed=embed)
            logger.info(f"User {sender_id} tried to transfer with invalid amount after fee: {amount_to_receive}")
            return

        # Создание записей пользователей
        await ensure_user_exists(sender_id, guild_id)
        await ensure_user_exists(receiver_id, guild_id)

        # Проверка баланса
        sender_cash, _ = await get_user_balance(sender_id, guild_id)
        total_required = amount
        if sender_cash < total_required:
            message = random.choice(config["insufficient_funds_messages"]).format(
                required=total_required,
                available=sender_cash,
                currency=currency
            )
            embed = create_embed(
                embed_type="insufficient_funds",
                user=ctx.author,
                message=message,
                required=total_required,
                available=sender_cash
            )
            await ctx.send(embed=embed)
            logger.info(f"User {sender_id} has insufficient funds: {sender_cash} < {total_required}")
            return

        try:
            # Выполнение перевода
            new_sender_cash, new_receiver_cash = await transfer_cash(sender_id, receiver_id, guild_id, amount, fee)
            embed = create_embed(
                embed_type="success",
                user=user,
                total=new_sender_cash,
                amount=amount,
                fee=fee,
                received=amount_to_receive
            )
            await ctx.send(embed=embed)
            logger.info(f"User {sender_id} transferred {amount} to {receiver_id} in guild {guild_id}: amount={amount}, fee={fee}, received={amount_to_receive}")

            # Обновление кулдауна
            await update_cooldown(sender_id, guild_id, "pay", int(time.time()))
        except ValueError as e:
            message = random.choice(GIVEMONEY_ERROR_MESSAGES).format(error=str(e))
            embed = create_embed(
                embed_type="error",
                user=ctx.author,
                error_message=message
            )
            await ctx.send(embed=embed)
            logger.error(f"Error in transfer command for user {sender_id} to {receiver_id} in guild {guild_id}: {e}")
        except Exception as e:
            message = random.choice(GIVEMONEY_ERROR_MESSAGES).format(error="база данных временно недоступна, попробуйте снова")
            embed = create_embed(
                embed_type="error",
                user=ctx.author,
                error_message=message
            )
            await ctx.send(embed=embed)
            logger.error(f"Database error in transfer command for user {sender_id} to {receiver_id} in guild {guild_id}: {e}")

    @commands.command(name="pay", aliases=["give-money", "givemoney"])
    async def pay(self, ctx, user: disnake.Member, amount: str):
        """Команда для перевода денег пользователю. Псевдонимы: give-money, pay."""
        try:
            # Попытка преобразовать amount в int
            amount = int(amount)
        except ValueError:
            # Если не удалось преобразовать, оставить как строку (для 'all' или 'half')
            pass
        await self.transfer_money(ctx, user, amount)

    async def cog_command_error(self, ctx, error):
        """Обработка ошибок команд."""
        if ctx.command.name == "pay" or ctx.invoked_with in ("give-money", "givemoney"):
            if isinstance(error, (commands.MemberNotFound, commands.BadArgument, commands.MissingRequiredArgument)):
                message = random.choice(GIVEMONEY_NOTICE_MESSAGES).format(
                    error=(
                        "неверный пользователь или сумма. Используйте:\n"
                        "- `.pay @user <amount|all|half>`\n"
                        "- `.give-money @user <amount|all|half>`\n"
                        "- `.givemoney @user <amount|all|half>`"
                    )
                )
                embed = create_embed(
                    embed_type="notice",
                    user=ctx.author,
                    message=message
                )
                await ctx.send(embed=embed)
                logger.info(f"User {ctx.author.id} provided invalid argument for transfer command: {error}")
                return
        raise error

def setup(bot):
    bot.add_cog(PayCog(bot))
    logger.info("PayCog loaded")