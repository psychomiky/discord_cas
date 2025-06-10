import disnake
from disnake.ext import commands
import random
import logging
import configparser
import os
import time
from utils.database import ensure_user_exists, update_cash, get_user_balance, get_cooldown, update_cooldown, apply_fine
from config import (
    currency, COMMAND_CONFIG_ERROR, COMMAND_COOLDOWN, COMMAND_ERROR,
    WORK_SUCCESS_MESSAGES, WORK_FAIL_MESSAGES,
    CRIME_SUCCESS_MESSAGES, CRIME_FAIL_MESSAGES,
    SLUT_SUCCESS_MESSAGES, SLUT_FAIL_MESSAGES,
    FALLBACK_SUCCESS_MESSAGES, FALLBACK_FAIL_MESSAGES
)

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

def get_command_config(command_name):
    """Получение настроек для команды из config.ini."""
    try:
        section = config[command_name]
        # Выбор сообщений в зависимости от команды
        if command_name == "Work":
            success_msgs = WORK_SUCCESS_MESSAGES
            fail_msgs = WORK_FAIL_MESSAGES
        elif command_name == "Crime":
            success_msgs = CRIME_SUCCESS_MESSAGES
            fail_msgs = CRIME_FAIL_MESSAGES
        elif command_name == "Slut":
            success_msgs = SLUT_SUCCESS_MESSAGES
            fail_msgs = SLUT_FAIL_MESSAGES
        else:
            success_msgs = FALLBACK_SUCCESS_MESSAGES
            fail_msgs = FALLBACK_FAIL_MESSAGES

        min_fine = float(section.get("min_fine", 5))
        max_fine = float(section.get("max_fine", 10))
        if not (0 <= min_fine <= 100) or not (0 <= max_fine <= 100):
            raise ValueError(f"min_fine and max_fine must be between 0 and 100 for {command_name}")

        logger.info(f"Loaded config for {command_name}: min_fine={min_fine}%, max_fine={max_fine}%")
        
        return {
            "success_chance": float(section.get("success_chance", 0.5)),
            "min_reward": int(section.get("min_reward", 100)),
            "max_reward": int(section.get("max_reward", 500)),
            "min_fine_percent": min_fine,
            "max_fine_percent": max_fine,
            "cooldown": int(section.get("cooldown", 3600)),
            "success_messages": success_msgs,
            "fail_messages": fail_msgs,
        }
    except KeyError as e:
        logger.error(f"Invalid config section for {command_name}: {e}")
        raise ValueError(f"Invalid config section for {command_name}")
    except Exception as e:
        logger.error(f"Error parsing config for {command_name}: {e}")
        raise ValueError(f"Error parsing config for {command_name}")

class WorkCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def check_cooldown(self, ctx, command_name: str, cooldown: int):
        user_id = ctx.author.id
        guild_id = ctx.guild.id
        current_time = int(time.time())
        last_used = await get_cooldown(user_id, guild_id, command_name)

        if last_used is not None:
            time_passed = current_time - last_used
            if time_passed < cooldown:
                remaining = cooldown - time_passed
                minutes, seconds = divmod(remaining, 60)
                embed = disnake.Embed(
                    title="Кулдаун",
                    description=COMMAND_COOLDOWN.format(
                        command_name=command_name,
                        minutes=minutes,
                        seconds=seconds
                    ),
                    color=0xFFA500
                )
                await ctx.send(embed=embed)
                logger.info(f"User {user_id} tried {command_name} but on cooldown: {remaining}s remaining")
                return False
        return True

    @commands.command(name="work")
    async def work(self, ctx):
        user_id = ctx.author.id
        guild_id = ctx.guild.id

        try:
            config = get_command_config("Work")
        except ValueError as e:
            embed = disnake.Embed(
                title="Ошибка",
                description=COMMAND_CONFIG_ERROR.format(error=str(e)),
                color=0xFF0000
            )
            await ctx.send(embed=embed)
            logger.error(f"Config error for work command, user {user_id}: {e}")
            return

        if not await self.check_cooldown(ctx, "work", config["cooldown"]):
            return

        try:
            await ensure_user_exists(user_id, guild_id)
            cash, bank = await get_user_balance(user_id, guild_id)
            total = cash + bank

            if random.random() < config["success_chance"]:
                reward = random.randint(config["min_reward"], config["max_reward"])
                await update_cash(user_id, guild_id, reward)
                message = random.choice(config["success_messages"]).format(amount=reward, currency=currency)
                embed_type = "success"
                color = 0x2F3136
            else:
                fine_percent = random.uniform(config["min_fine_percent"], config["max_fine_percent"])
                fine = int(total * (fine_percent / 100))
                fine = max(0, fine)
                await apply_fine(user_id, guild_id, fine)
                message = random.choice(config["fail_messages"]).format(amount=fine, currency=currency)
                embed_type = "failure"
                color = 0x2F3136

            cash, bank = await get_user_balance(user_id, guild_id)
            total = cash + bank
            embed = disnake.Embed(
                title="Результат" if embed_type == "success" else "Провал",
                description=f"{ctx.author.mention} {message}\n**Общий баланс:** {total} {currency}",
                color=color
            )
            await ctx.send(embed=embed)
            await update_cooldown(user_id, guild_id, "work", int(time.time()))
            logger.info(f"User {user_id} executed work command in guild {guild_id}: {message}")
        except Exception as e:
            embed = disnake.Embed(
                title="Ошибка",
                description=COMMAND_ERROR.format(error=str(e)),
                color=0x2F3136
            )
            await ctx.send(embed=embed)
            logger.error(f"Error in work command for user {user_id} in guild {guild_id}: {e}")

    @commands.command(name="crime")
    async def crime(self, ctx):
        user_id = ctx.author.id
        guild_id = ctx.guild.id

        try:
            config = get_command_config("Crime")
        except ValueError as e:
            embed = disnake.Embed(
                title="Ошибка",
                description=COMMAND_CONFIG_ERROR.format(error=str(e)),
                color=0xFF0000
            )
            await ctx.send(embed=embed)
            logger.error(f"Config error for crime command, user {user_id}: {e}")
            return

        if not await self.check_cooldown(ctx, "crime", config["cooldown"]):
            return

        try:
            await ensure_user_exists(user_id, guild_id)
            cash, bank = await get_user_balance(user_id, guild_id)
            total = cash + bank

            if random.random() < config["success_chance"]:
                reward = random.randint(config["min_reward"], config["max_reward"])
                await update_cash(user_id, guild_id, reward)
                message = random.choice(config["success_messages"]).format(amount=reward, currency=currency)
                embed_type = "success"
                color = 0x00BFFF
            else:
                fine_percent = random.uniform(config["min_fine_percent"], config["max_fine_percent"])
                fine = int(total * (fine_percent / 100))
                fine = max(0, fine)
                await apply_fine(user_id, guild_id, fine)
                message = random.choice(config["fail_messages"]).format(amount=fine, currency=currency)
                embed_type = "failure"
                color = 0xFF0000

            cash, bank = await get_user_balance(user_id, guild_id)
            total = cash + bank
            embed = disnake.Embed(
                title="Результат" if embed_type == "success" else "Провал",
                description=f"{ctx.author.mention} {message}\n**Общий баланс:** {total} {currency}",
                color=color
            )
            await ctx.send(embed=embed)
            await update_cooldown(user_id, guild_id, "crime", int(time.time()))
            logger.info(f"User {user_id} executed crime command in guild {guild_id}: {message}")
        except Exception as e:
            embed = disnake.Embed(
                title="Ошибка",
                description=COMMAND_ERROR.format(error=str(e)),
                color=0xFF0000
            )
            await ctx.send(embed=embed)
            logger.error(f"Error in crime command for user {user_id} in guild {guild_id}: {e}")

    @commands.command(name="slut")
    async def slut(self, ctx):
        user_id = ctx.author.id
        guild_id = ctx.guild.id

        try:
            config = get_command_config("Slut")
        except ValueError as e:
            embed = disnake.Embed(
                title="Ошибка",
                description=COMMAND_CONFIG_ERROR.format(error=str(e)),
                color=0xFF0000
            )
            await ctx.send(embed=embed)
            logger.error(f"Config error for slut command, user {user_id}: {e}")
            return

        if not await self.check_cooldown(ctx, "slut", config["cooldown"]):
            return

        try:
            await ensure_user_exists(user_id, guild_id)
            cash, bank = await get_user_balance(user_id, guild_id)
            total = cash + bank

            if random.random() < config["success_chance"]:
                reward = random.randint(config["min_reward"], config["max_reward"])
                await update_cash(user_id, guild_id, reward)
                message = random.choice(config["success_messages"]).format(amount=reward, currency=currency)
                embed_type = "success"
                color = 0x00BFFF
            else:
                fine_percent = random.uniform(config["min_fine_percent"], config["max_fine_percent"])
                fine = int(total * (fine_percent / 100))
                fine = max(0, fine)
                await apply_fine(user_id, guild_id, fine)
                message = random.choice(config["fail_messages"]).format(amount=fine, currency=currency)
                embed_type = "failure"
                color = 0xFF0000

            cash, bank = await get_user_balance(user_id, guild_id)
            total = cash + bank
            embed = disnake.Embed(
                title="Результат" if embed_type == "success" else "Провал",
                description=f"{ctx.author.mention} {message}\n**Общий баланс:** {total} {currency}",
                color=color
            )
            await ctx.send(embed=embed)
            await update_cooldown(user_id, guild_id, "slut", int(time.time()))
            logger.info(f"User {user_id} executed slut command in guild {guild_id}: {message}")
        except Exception as e:
            embed = disnake.Embed(
                title="Ошибка",
                description=COMMAND_ERROR.format(error=str(e)),
                color=0xFF0000
            )
            await ctx.send(embed=embed)
            logger.error(f"Error in slut command for user {user_id} in guild {guild_id}: {e}")

def setup(bot):
    bot.add_cog(WorkCog(bot))