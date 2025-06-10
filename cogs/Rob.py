import disnake
from disnake.ext import commands
import random
import logging
import configparser
import os
import time
from utils.database import get_user_balance, ensure_user_exists, apply_fine, get_cooldown, update_cooldown, rob_user
from config import currency, ROB_SUCCESS_MESSAGES, ROB_FAIL_MESSAGES, ROB_ERROR_MESSAGES, ROB_COOLDOWN_MESSAGES, ROB_NOTICE_MESSAGES

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

# Резервные сообщения
FALLBACK_SUCCESS_MESSAGES = ["Успех! Ты украл {amount} {currency} у {target}!"] 
FALLBACK_FAIL_MESSAGES = ["Неудача! Потеряно {amount} {currency} при попытке ограбить {target}."]
FALLBACK_ERROR_MESSAGES = ["Ошибка: {error}"]
FALLBACK_COOLDOWN_MESSAGES = ["Команда {command_name} на кулдауне! Попробуйте снова через {minutes} мин {seconds} сек."]
FALLBACK_NOTICE_MESSAGES = ["Уведомление: {error}"]

def get_command_config(command_name):
    """Получение настроек для команды из config.ini."""
    try:
        section = config[command_name]
        min_fine = float(section.get("min_fine", 10))
        max_fine = float(section.get("max_fine", 25))
        cooldown = int(section.get("cooldown", 15))
        immune_role = section.get("immune_role", "[]")
        
        try:
            immune_role = eval(immune_role)
            if not isinstance(immune_role, list):
                raise ValueError("immune_role must be a list")
        except Exception as e:
            logger.error(f"Invalid immune_role format for {command_name}: {e}")
            raise ValueError(f"Invalid immune_role format for {command_name}")

        if not (0 <= min_fine <= 100) or not (0 <= max_fine <= 100):
            raise ValueError("min_fine and max_fine must be between 0 and 100")
        if min_fine > max_fine:
            raise ValueError("min_fine cannot be greater than max_fine")
        if cooldown < 0:
            raise ValueError("cooldown cannot be negative")

        success_msgs = getattr(globals().get('config', {}), 'ROB_SUCCESS_MESSAGES', FALLBACK_SUCCESS_MESSAGES)
        fail_msgs = getattr(globals().get('config', {}), 'ROB_FAIL_MESSAGES', FALLBACK_FAIL_MESSAGES)
        error_msgs = getattr(globals().get('config', {}), 'ROB_ERROR_MESSAGES', FALLBACK_ERROR_MESSAGES)
        cooldown_msgs = getattr(globals().get('config', {}), 'ROB_COOLDOWN_MESSAGES', FALLBACK_COOLDOWN_MESSAGES)
        notice_msgs = getattr(globals().get('config', {}), 'ROB_NOTICE_MESSAGES', FALLBACK_NOTICE_MESSAGES)

        logger.info(f"Loaded config for {command_name}: min_fine={min_fine}%, max_fine={max_fine}%, cooldown={cooldown}s, immune_role={immune_role}")
        return {
            "min_fine_percent": min_fine,
            "max_fine_percent": max_fine,
            "cooldown": cooldown,
            "immune_role": immune_role,
            "success_messages": success_msgs,
            "fail_messages": fail_msgs,
            "error_messages": error_msgs,
            "cooldown_messages": cooldown_msgs,
            "notice_messages": notice_msgs
        }
    except KeyError as e:
        logger.error(f"Invalid config section for {command_name}: {e}")
        raise ValueError(f"Invalid config section for {command_name}")
    except Exception as e:
        logger.error(f"Error parsing config for {command_name}: {e}")
        raise ValueError(f"Error parsing config for {command_name}")

class RobCog(commands.Cog):
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
                embed = disnake.Embed(color=0x2F3136)
                embed.set_author(
                    name=ctx.author.display_name,
                    icon_url=ctx.author.avatar.url if ctx.author.avatar else ctx.author.default_avatar.url
                )
                embed.title = "⏳ Кулдаун"
                message = random.choice(ROB_COOLDOWN_MESSAGES).format(
                    command_name=command_name.lower(),
                    minutes=minutes,
                    seconds=seconds
                )
                embed.description = message
                await ctx.send(embed=embed)
                logger.info(f"User {user_id} tried {command_name} but on cooldown: {remaining}s remaining")
                return False
        return True

    @commands.command(name="rob")
    async def rob(self, ctx, user: disnake.Member = None):
        """Команда для ограбления пользователя."""
        robber_id = ctx.author.id
        guild_id = ctx.guild.id

        logger.debug(f"User {robber_id} invoked rob command with target: {user}")

        embed = disnake.Embed(color=0x2F3136)
        embed.set_author(
            name=ctx.author.display_name,
            icon_url=ctx.author.avatar.url if ctx.author.avatar else ctx.author.default_avatar.url
        )

        if user is None:
            embed.title = "📢 Уведомление"
            embed.description = random.choice(ROB_NOTICE_MESSAGES).format(
                error="укажите пользователя: `rob @user`"
            )
            await ctx.send(embed=embed)
            logger.info(f"User {robber_id} provided no argument for rob command")
            return

        target_id = user.id

        if target_id == robber_id:
            embed.title = "🚫 Ошибка"
            embed.description = random.choice(ROB_ERROR_MESSAGES).format(error="нельзя ограбить самого себя")
            await ctx.send(embed=embed)
            logger.info(f"User {robber_id} tried to rob themselves")
            return
        if user.bot:
            embed.title = "🚫 Ошибка"
            embed.description = random.choice(ROB_ERROR_MESSAGES).format(error="нельзя ограбить бота")
            await ctx.send(embed=embed)
            logger.info(f"User {robber_id} tried to rob a bot")
            return

        try:
            config = get_command_config("Rob")
        except ValueError as e:
            embed.title = "🚫 Ошибка"
            embed.description = random.choice(ROB_ERROR_MESSAGES).format(error=f"ошибка конфигурации: {str(e)}")
            await ctx.send(embed=embed)
            logger.error(f"Config error for rob command: {e}")
            return

        # Проверка защищённых ролей
        target_roles = [role.id for role in user.roles]
        if any(role_id in config["immune_role"] for role_id in target_roles):
            embed.title = "🚫 Ошибка"
            embed.description = random.choice(ROB_ERROR_MESSAGES).format(error="нельзя ограбить пользователя с защищённой ролью")
            await ctx.send(embed=embed)
            logger.info(f"User {robber_id} tried to rob {target_id} with immune role")
            return

        if not await self.check_cooldown(ctx, "rob", config["cooldown"]):
            return

        try:
            await ensure_user_exists(robber_id, guild_id)
            await ensure_user_exists(target_id, guild_id)
            robber_cash, robber_bank = await get_user_balance(robber_id, guild_id)
            target_cash, target_bank = await get_user_balance(target_id, guild_id)
            total_robber = robber_cash + robber_bank

            if target_cash <= 0:
                embed.title = "🚫 Ошибка"
                embed.description = random.choice(ROB_ERROR_MESSAGES).format(error=f"у {user.mention} нет денег в кармане")
                await ctx.send(embed=embed)
                logger.info(f"User {robber_id} tried to rob {target_id} with no cash")
                return

            raw_fail = total_robber / (target_cash + total_robber) if (total_robber + target_cash) > 0 else 0
            fail_chance = max(0.20, min(0.80, raw_fail))

            # и уже успех = 1 − P(fail)
            success_chance = 1.0 - fail_chance

            if random.random() < success_chance:
                stolen_amount = int(success_chance * target_cash)
                stolen_amount = max(0, min(stolen_amount, target_cash))
                new_robber_cash, robber_bank, new_target_cash, target_bank = await rob_user(
                    robber_id, target_id, guild_id, stolen_amount
                )
                embed.description = f"✅ Вы успешно обчистили {user.mention} достав из его карманов {currency} {stolen_amount}"
                embed.add_field(name="Ваш баланс", value=f"{new_robber_cash + robber_bank} {currency}", inline=False)
                await ctx.send(embed=embed)
                await update_cooldown(robber_id, guild_id, "rob", int(time.time()))
                logger.info(f"User {robber_id} successfully robbed {target_id} in guild {guild_id}: stole {stolen_amount}")
            else:
                fine_percent = random.uniform(config["min_fine_percent"], config["max_fine_percent"])
                fine = int(total_robber * (fine_percent / 100))
                fine = max(0, fine)
                new_robber_cash, robber_bank = await apply_fine(robber_id, guild_id, fine)
                embed.description = f"Похоже вас поймали, и вам придется заплатить {currency} {fine}"
                embed.add_field(name="Ваш баланс", value=f"{new_robber_cash + robber_bank} {currency}", inline=False)
                await ctx.send(embed=embed)
                await update_cooldown(robber_id, guild_id, "rob", int(time.time()))
                logger.info(f"User {robber_id} failed to rob {target_id} in guild {guild_id}: fined {fine}")
        except ValueError as e:
            embed.title = "🚫 Ошибка"
            embed.description = random.choice(ROB_ERROR_MESSAGES).format(error=str(e))
            await ctx.send(embed=embed)
            logger.error(f"Error in rob command for user {robber_id} targeting {target_id} in guild {guild_id}: {e}")
        except Exception as e:
            embed.title = "🚫 Ошибка"
            embed.description = random.choice(ROB_ERROR_MESSAGES).format(error="база данных временно недоступна, попробуйте снова")
            await ctx.send(embed=embed)
            logger.error(f"Database error in rob command for user {robber_id} targeting {target_id} in guild {guild_id}: {e}")

    async def cog_command_error(self, ctx, error):
        """Обработка ошибок команд."""
        if ctx.command.name == "rob":
            if isinstance(error, (commands.MemberNotFound, commands.BadArgument)):
                embed = disnake.Embed(color=0x2F3136)
                embed.set_author(
                    name=ctx.author.display_name,
                    icon_url=ctx.author.avatar.url if ctx.author.avatar else ctx.author.default_avatar.url
                )
                embed.title = "📢 Уведомление"
                embed.description = random.choice(ROB_NOTICE_MESSAGES).format(
                    error="укажите пользователя: `rob @user`"
                )
                await ctx.send(embed=embed)
                logger.info(f"User {ctx.author.id} provided invalid argument for rob command: {error}")
                return
        raise error

def setup(bot):
    bot.add_cog(RobCog(bot))
    logger.info("RobCog loaded")