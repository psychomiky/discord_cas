import disnake
from disnake.ext import commands
import random
import logging
import configparser
import os
import time
import asyncio
from utils.database import get_user_balance, update_cash, ensure_user_exists, create_roulette, add_roulette_bet, get_active_roulette, set_roulette_result, save_roulette_history, delete_roulette
from config import (
    currency, ROULETTE_INFO, ROULETTE_IMAGE_URL,
    ROULETTE_SUCCESS_MESSAGES, ROULETTE_FAIL_MESSAGES, ROULETTE_NO_WINNERS,
    ROULETTE_ERROR_MESSAGES, ROULETTE_BET_SUCCESS, ROULETTE_START,
    ROULETTE_SET_SUCCESS, ROULETTE_CONFIG_ERROR, ROULETTE_PROCESS_ERROR, ROULETTE_CASH_ERROR
)

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Чтение конфигурации из games.ini
config = configparser.ConfigParser()
config_file = "games.ini"

if not os.path.exists(config_file):
    logger.error(f"Config file {config_file} not found.")
    raise FileNotFoundError(f"Config file {config_file} not found.")

try:
    config.read(config_file, encoding='utf-8')
except Exception as e:
    logger.error(f"Failed to read games.ini: {e}")
    raise

def get_roulette_config():
    """Получение настроек рулетки из games.ini."""
    try:
        section = config["Roulette"]
        duration = int(section.get("duration", 30))
        min_bet = int(section.get("min_bet", 100))
        if duration < 10 or min_bet < 1:
            raise ValueError("duration >= 10s, min_bet >= 1")
        logger.info(f"Loaded Roulette config: duration={duration}s, min_bet={min_bet}")
        return {"duration": duration, "min_bet": min_bet}
    except KeyError as e:
        logger.error(f"Invalid config section for Roulette: {e}")
        raise ValueError(f"Invalid config section for Roulette")
    except Exception as e:
        logger.error(f"Error parsing Roulette config: {e}")
        raise ValueError(f"Error parsing Roulette config")

class RouletteCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.slots = {
            '0': 'green', '1': 'red', '2': 'black', '3': 'red', '4': 'black', '5': 'red', '6': 'black',
            '7': 'red', '8': 'black', '9': 'red', '10': 'black', '11': 'red', '12': 'black', '13': 'red',
            '14': 'black', '15': 'red', '16': 'black', '17': 'red', '18': 'black', '19': 'red', '20': 'black',
            '21': 'red', '22': 'black', '23': 'red', '24': 'black', '25': 'red', '26': 'black', '27': 'red',
            '28': 'black', '29': 'red', '30': 'black', '31': 'red', '32': 'black', '33': 'red', '34': 'black',
            '35': 'red', '36': 'black'
        }
        self.valid_spaces = {
            "numbers": set(str(i) for i in range(0, 37)),
            "dozens": {"1-12", "13-24", "25-36"},
            "columns": {
                "1st": {1, 4, 7, 10, 13, 16, 19, 22, 25, 28, 31, 34},
                "2nd": {2, 5, 8, 11, 14, 17, 20, 23, 26, 29, 32, 35},
                "3rd": {3, 6, 9, 12, 15, 18, 21, 24, 27, 30, 33, 36}
            },
            "halves": {"1-18", "19-36"},
            "parity": {"odd", "even"},
            "colors": {"red", "black"}
        }
        self.multipliers = {
            "num    ber": 36, "dozen": 3, "column": 3, "half": 2, "parity": 2, "color": 2
        }
        self.channel_locks = {}  # Блокировки для каналов
        self.roulette_tasks = {}  # Задачи завершения рулетки

    async def validate_bet_and_space(self, user_id: int, guild_id: int, bet: str, space: str, config: dict) -> tuple:
        """Валидация ставки и места, возврат суммы, места и типа или ошибки."""
        logger.info(f"Validating bet: user={user_id}, bet={bet}, space={space}")
        try:
            cash, _ = await get_user_balance(user_id, guild_id)
            logger.info(f"User {user_id} cash: {cash}")
        except Exception as e:
            logger.error(f"Error fetching balance for user {user_id}: {e}")
            return None, None, "database_error"
        if bet.lower() == "all":
            amount = cash
        elif bet.lower() == "half":
            amount = cash // 2
        else:
            try:
                amount = int(bet)
            except ValueError:
                logger.warning(f"Invalid bet format: {bet}")
                return None, None, "invalid_bet"
        if amount > cash:
            logger.warning(f"Insufficient cash: bet={amount}, cash={cash}")
            return None, None, "insufficient_cash"
        if amount < config["min_bet"]:
            logger.warning(f"Bet below minimum: bet={amount}, min_bet={config['min_bet']}")
            return None, None, "min_bet"

        space = space.lower().strip()
        logger.info(f"Validating space: {space}")
        if space in self.valid_spaces["numbers"]:
            return amount, space, "number"
        if space in self.valid_spaces["dozens"]:
            return amount, space, "dozen"
        if space in self.valid_spaces["columns"]:
            return amount, space, "column"
        if space in self.valid_spaces["halves"]:
            return amount, space, "half"
        if space in self.valid_spaces["parity"]:
            return amount, space, "parity"
        if space in self.valid_spaces["colors"]:
            return amount, space, "color"
        logger.warning(f"Invalid space: {space}")
        return None, None, "invalid_space"

    async def process_bet(self, user_id: int, guild_id: int, amount: int, space: str, space_type: str, result: str) -> tuple:
        """Обработка ставки: проверка выигрыша и начисление."""
        try:
            await ensure_user_exists(user_id, guild_id)
            cash, _ = await get_user_balance(user_id, guild_id)

            win = False
            multiplier = self.multipliers[space_type]
            if space_type == "number":
                win = space == result
            elif space_type == "dozen":
                result_num = int(result)
                ranges = {"1-12": range(1, 13), "13-24": range(13, 25), "25-36": range(25, 37)}
                win = result_num in ranges[space]
            elif space_type == "column":
                result_num = int(result)
                win = result_num in self.valid_spaces["columns"][space]
            elif space_type == "half":
                result_num = int(result)
                ranges = {"1-18": range(1, 19), "19-36": range(19, 37)}
                win = result_num in ranges[space]
            elif space_type == "parity":
                result_num = int(result)
                win = (result_num % 2 == 1) if space == "odd" else (result_num % 2 == 0)
            elif space_type == "color":
                win = self.slots[result] == space

            winnings = amount * multiplier if win else 0
            if winnings > 0:
                await update_cash(user_id, guild_id, winnings)
            new_cash, _ = await get_user_balance(user_id, guild_id)

            logger.info(f"Processed bet: user={user_id}, space={space}, win={win}, winnings={winnings}, new_cash={new_cash}")
            return (win, winnings, new_cash), None
        except Exception as e:
            logger.error(f"Error processing bet for user {user_id} in guild {guild_id}: {e}")
            return None, str(e)

    async def complete_roulette(self, ctx, roulette_id, channel_id, guild_id, duration):
        """Завершение рулетки: ожидание, обработка ставок, отправка результата."""
        user_id = ctx.author.id
        start_time = time.time()
        logger.info(f"Starting roulette for roulette_id={roulette_id}, channel={channel_id} at {start_time}")
        try:
            # Ожидание длительности рулетки
            logger.info(f"Waiting {duration}s for roulette_id={roulette_id}")
            await asyncio.sleep(duration)
            logger.info(f"Finished waiting for roulette_id={roulette_id}")

            roulette = await get_active_roulette(channel_id)
            if not roulette or roulette["id"] != roulette_id:
                logger.warning(f"Roulette {roulette_id} not found or mismatched for channel {channel_id}")
                embed = disnake.Embed(
                    title="Ошибка",
                    description=f"{ctx.author.mention} Рулетка не найдена или завершена.",
                    color=0x2F3136
                )
                embed.set_footer(text=f"ID: {user_id}")
                await ctx.send(embed=embed)
                return

            result = roulette["result"] or random.choice(list(self.slots.keys()))
            result_prompt = f"🎰 Шар остановился на: **{self.slots[result]} {result}**!\n"
            winners = []
            results = {}

            for user_id, user_bets in roulette["bets"].items():
                user_mention = f"<@{user_id}>"
                results[user_id] = {}
                for amount, space, space_type in user_bets:
                    result_data, error = await self.process_bet(user_id, guild_id, amount, space, space_type, result)
                    if error:
                        embed = disnake.Embed(
                            title="Ошибка",
                            description=ROULETTE_PROCESS_ERROR.format(error=error),
                            color=0x2F3136
                        )
                        embed.set_footer(text=f"ID: {user_id}")
                        await ctx.send(embed=embed)
                        continue

                    win, winnings, new_cash = result_data
                    results[user_id][space] = winnings
                    if win:
                        message = random.choice(ROULETTE_SUCCESS_MESSAGES).format(
                            mention=user_mention, amount=winnings, space=space, currency=currency
                        )
                        winners.append(message)

            if winners:
                result_prompt += "Победители:\n" + "\n".join(winners)
            else:
                result_prompt += ROULETTE_NO_WINNERS

            await ctx.send(result_prompt)

            await save_roulette_history(roulette["id"], result, int(time.time()), roulette["bets"], results)
            await delete_roulette(roulette["id"])
            end_time = time.time()
            logger.info(f"Completed roulette {roulette_id}, result={result}, duration={end_time - start_time:.2f}s")
        except Exception as e:
            embed = disnake.Embed(
                title="Ошибка",
                description=f"{ctx.author.mention} Ошибка завершения рулетки: {str(e)}",
                color=0x2F3136
            )
            embed.set_footer(text=f"ID: {user_id}")
            await ctx.send(embed=embed)
            logger.error(f"Error completing roulette for channel {channel_id}: {e}")
        finally:
            # Очистка задачи и блокировки
            if channel_id in self.roulette_tasks:
                del self.roulette_tasks[channel_id]
            if channel_id in self.channel_locks:
                del self.channel_locks[channel_id]

    @commands.command(name="roulette", aliases=["r"])
    async def roulette(self, ctx, bet: str, space: str):
        """Команда для игры в рулетку."""
        user_id = ctx.author.id
        guild_id = ctx.guild.id
        channel_id = ctx.channel.id

        if not ctx.channel.permissions_for(ctx.guild.me).send_messages:
            logger.warning(f"Bot lacks send_messages permission in channel {ctx.channel.id}")
            embed = disnake.Embed(
                title="Ошибка",
                description=f"{ctx.author.mention} Бот не может отправлять сообщения в этом канале.",
                color=0x2F3136
            )
            embed.set_footer(text=f"ID: {user_id}")
            try:
                await ctx.author.send(embed=embed)
            except:
                pass
            return
        if not ctx.channel.permissions_for(ctx.guild.me).embed_links:
            logger.warning(f"Bot lacks embed_links permission in channel {ctx.channel.id}")
            embed = disnake.Embed(
                title="Ошибка",
                description=f"{ctx.author.mention} Бот не может отправлять эмбеды в этом канале.",
                color=0x2F3136
            )
            embed.set_footer(text=f"ID: {user_id}")
            try:
                await ctx.author.send(embed=embed)
            except:
                pass
            return

        try:
            config = get_roulette_config()
        except ValueError as e:
            embed = disnake.Embed(
                title="Ошибка",
                description=ROULETTE_CONFIG_ERROR.format(error=str(e)),
                color=0x2F3136
            )
            embed.set_footer(text=f"ID: {user_id}")
            await ctx.send(embed=embed)
            logger.error(f"Config error for user {user_id}: {e}")
            return

        amount, validated_space, space_type_or_error = await self.validate_bet_and_space(user_id, guild_id, bet, space, config)
        logger.info(f"Validation result: amount={amount}, space={validated_space}, type_or_error={space_type_or_error}")
        if space_type_or_error in ROULETTE_ERROR_MESSAGES:
            try:
                cash, _ = await get_user_balance(user_id, guild_id) if space_type_or_error != "database_error" else (0, 0)
                error_msg = ROULETTE_ERROR_MESSAGES[space_type_or_error].format(
                    cash=cash, min_bet=config["min_bet"], currency=currency, roulette_info=ROULETTE_INFO
                )
            except Exception as e:
                error_msg = f"Ошибка обработки: {space_type_or_error} (форматирование: {str(e)})"
            embed = disnake.Embed(
                title="Ошибка",
                description=f"{ctx.author.mention} {error_msg}",
                color=0x2F3136
            )
            embed.set_footer(text=f"ID: {user_id}")
            await ctx.send(embed=embed)
            logger.warning(f"Validation error for user {user_id}: {space_type_or_error}")
            return
        space_type = space_type_or_error

        try:
            logger.info(f"Ensuring user exists: user={user_id}, guild={guild_id}")
            await ensure_user_exists(user_id, guild_id)
            logger.info(f"Fetching balance for user={user_id}")
            cash, _ = await get_user_balance(user_id, guild_id)
            logger.info(f"User {user_id} cash: {cash}, attempting to deduct {amount}")
            if cash < amount:
                error_msg = ROULETTE_ERROR_MESSAGES["insufficient_cash"].format(cash=cash, currency=currency)
                embed = disnake.Embed(
                    title="Ошибка",
                    description=f"{ctx.author.mention} {error_msg}",
                    color=0x2F3136
                )
                embed.set_footer(text=f"ID: {user_id}")
                await ctx.send(embed=embed)
                logger.warning(f"Insufficient cash for user {user_id}: cash={cash}, amount={amount}")
                return
            await update_cash(user_id, guild_id, -amount)
            logger.info(f"Deducted {amount} cash for user {user_id}")
        except Exception as e:
            embed = disnake.Embed(
                title="Ошибка",
                description=f"{ctx.author.mention} {ROULETTE_CASH_ERROR.format(currency=currency)}",
                color=0x2F3136
            )
            embed.set_footer(text=f"ID: {user_id}")
            await ctx.send(embed=embed)
            logger.error(f"Error deducting cash for user {user_id}: {e}")
            return

        # Получаем или создаём блокировку для канала
        if channel_id not in self.channel_locks:
            self.channel_locks[channel_id] = asyncio.Lock()
        async with self.channel_locks[channel_id]:
            try:
                roulette = await get_active_roulette(channel_id)
                if roulette and time.time() > roulette["end_time"]:
                    await delete_roulette(roulette["id"])
                    roulette = None

                if roulette:
                    remaining_seconds = int(roulette["end_time"] - time.time())
                    if remaining_seconds <= 0:
                        logger.info(f"Roulette {roulette['id']} expired, ignoring bet for user {user_id}")
                        embed = disnake.Embed(
                            title="Ошибка",
                            description=f"{ctx.author.mention} Рулетка уже завершилась. Попробуйте снова.",
                            color=0x2F3136
                        )
                        embed.set_footer(text=f"ID: {user_id}")
                        await ctx.send(embed=embed)
                        # Вернуть деньги
                        await update_cash(user_id, guild_id, amount)
                        return
                    await add_roulette_bet(roulette["id"], user_id, amount, validated_space, space_type)
                    cash, _ = await get_user_balance(user_id, guild_id)
                    embed = disnake.Embed(
                        title="Рулетка",
                        description=ROULETTE_BET_SUCCESS.format(
                            mention=ctx.author.mention, amount=amount, currency=currency,
                            space=validated_space, seconds=remaining_seconds
                        ),
                        color=0x2F3136
                    )
                    embed.set_footer(text=f"ID: {user_id}")
                    await ctx.send(embed=embed)
                    logger.info(f"Added bet to existing roulette for user {user_id}, roulette_id={roulette['id']}")
                    return  # Не создаём новую задачу завершения

                logger.info(f"Creating new roulette for channel={channel_id}")
                roulette_id = await create_roulette(channel_id, guild_id, int(time.time() + config["duration"]))
                logger.info(f"Adding bet for roulette_id={roulette_id}, user={user_id}")
                await add_roulette_bet(roulette_id, user_id, amount, validated_space, space_type)
                cash, _ = await get_user_balance(user_id, guild_id)
                embed = disnake.Embed(
                    title="Рулетка",
                    description=ROULETTE_START.format(
                        mention=ctx.author.mention, amount=amount, currency=currency,
                        space=validated_space, duration=config["duration"]
                    ),
                    color=0x2F3136
                )
                embed.set_footer(text=f"ID: {user_id}")
                await ctx.send(embed=embed)
                logger.info(f"Started new roulette for user {user_id}, roulette_id={roulette_id}")

                # Создаём задачу завершения только для новой рулетки
                if channel_id not in self.roulette_tasks:
                    self.roulette_tasks[channel_id] = asyncio.create_task(
                        self.complete_roulette(ctx, roulette_id, channel_id, guild_id, config["duration"])
                    )
            except Exception as e:
                embed = disnake.Embed(
                    title="Ошибка",
                    description=f"{ctx.author.mention} Не удалось запустить рулетку: {str(e)}",
                    color=0x2F3136
                )
                embed.set_footer(text=f"ID: {user_id}")
                await ctx.send(embed=embed)
                logger.error(f"Error starting roulette for user {user_id} in channel {channel_id}: {e}")
                # Вернуть деньги при ошибке
                await update_cash(user_id, guild_id, amount)
                return

    @commands.command(name="roulette-info")
    async def roulette_info(self, ctx):
        """Команда для вывода подсказки по рулетке."""
        user_id = ctx.author.id
        if not ctx.channel.permissions_for(ctx.guild.me).send_messages:
            logger.warning(f"Bot lacks send_messages permission in channel {ctx.channel.id}")
            embed = disnake.Embed(
                title="Ошибка",
                description=f"{ctx.author.mention} Бот не может отправлять сообщения в этом канале.",
                color=0x2F3136
            )
            embed.set_footer(text=f"ID: {user_id}")
            try:
                await ctx.author.send(embed=embed)
            except:
                pass
            return
        if not ctx.channel.permissions_for(ctx.guild.me).embed_links:
            logger.warning(f"Bot lacks embed_links permission in channel {ctx.channel.id}")
            embed = disnake.Embed(
                title="Ошибка",
                description=f"{ctx.author.mention} Бот не может отправлять эмбеды в этом канале.",
                color=0x2F3136
            )
            embed.set_footer(text=f"ID: {user_id}")
            try:
                await ctx.author.send(embed=embed)
            except:
                pass
            return

        embed = disnake.Embed(
            title="Информация",
            description=ROULETTE_INFO,
            color=0x2F3136
        )
        embed.set_image(url=ROULETTE_IMAGE_URL)
        embed.set_footer(text=f"ID: {user_id}")
        try:
            await ctx.send(embed=embed)
            logger.info(f"Sent roulette-info embed for user {user_id}")
        except disnake.HTTPException as e:
            embed = disnake.Embed(
                title="Ошибка",
                description=f"{ctx.author.mention} Не удалось отправить информацию. Проверьте права бота.",
                color=0x2F3136
            )
            embed.set_footer(text=f"ID: {user_id}")
            await ctx.send(embed=embed)
            logger.error(f"Failed to send roulette-info embed for user {user_id}: {e}")

    @commands.command(name="set-roulette")
    @commands.has_permissions(administrator=True)
    async def set_roulette(self, ctx, number: str):
        """Секретная команда для установки результата рулетки."""
        user_id = ctx.author.id
        channel_id = ctx.channel.id
        if not ctx.channel.permissions_for(ctx.guild.me).send_messages:
            logger.warning(f"Bot lacks send_messages permission in channel {ctx.channel.id}")
            embed = disnake.Embed(
                title="Ошибка",
                description=f"{ctx.author.mention} Бот не может отправлять сообщения в этом канале.",
                color=0x2F3136
            )
            embed.set_footer(text=f"ID: {user_id}")
            try:
                await ctx.author.send(embed=embed)
            except:
                pass
            return
        if not ctx.channel.permissions_for(ctx.guild.me).embed_links:
            logger.warning(f"Bot lacks embed_links permission in channel {ctx.channel.id}")
            embed = disnake.Embed(
                title="Ошибка",
                description=f"{ctx.author.mention} Бот не может отправлять эмбеды в этом канале.",
                color=0x2F3136
            )
            embed.set_footer(text=f"ID: {user_id}")
            try:
                await ctx.author.send(embed=embed)
            except:
                pass
            return

        try:
            roulette = await get_active_roulette(channel_id)
            if not roulette:
                embed = disnake.Embed(
                    title="Ошибка",
                    description=f"{ctx.author.mention} {ROULETTE_ERROR_MESSAGES['no_active_roulette']}",
                    color=0x2F3136
                )
                embed.set_footer(text=f"ID: {user_id}")
                await ctx.send(embed=embed)
                logger.warning(f"No active roulette for channel {channel_id}")
                return

            if number not in self.slots:
                embed = disnake.Embed(
                    title="Ошибка",
                    description=f"{ctx.author.mention} {ROULETTE_ERROR_MESSAGES['invalid_number']}",
                    color=0x2F3136
                )
                embed.set_footer(text=f"ID: {user_id}")
                await ctx.send(embed=embed)
                logger.warning(f"Invalid number {number} for set-roulette")
                return

            await set_roulette_result(roulette["id"], number)
            cash, _ = await get_user_balance(user_id, ctx.guild.id)
            embed = disnake.Embed(
                title="Рулетка",
                description=ROULETTE_SET_SUCCESS.format(
                    mention=ctx.author.mention, number=number
                ),
                color=0x2F3136
            )
            embed.set_footer(text=f"ID: {user_id}")
            await ctx.send(embed=embed)
            logger.info(f"Set roulette result to {number} for user {user_id}")
        except Exception as e:
            embed = disnake.Embed(
                title="Ошибка",
                description=f"{ctx.author.mention} Не удалось установить результат рулетки: {str(e)}",
                color=0x2F3136
            )
            embed.set_footer(text=f"ID: {user_id}")
            await ctx.send(embed=embed)
            logger.error(f"Error setting roulette result for user {user_id}: {e}")

    @roulette.error
    async def roulette_error(self, ctx, error):
        """Обработка ошибок команды roulette."""
        user_id = ctx.author.id
        if isinstance(error, commands.MissingRequiredArgument):
            embed = disnake.Embed(
                title="Ошибка",
                description=f"{ctx.author.mention} Не указан аргумент: {error.param.name}. Используйте: `.roulette <bet> <space>` или `.roulette-info`",
                color=0x2F3136
            )
            embed.set_footer(text=f"ID: {user_id}")
            await ctx.send(embed=embed)
            logger.warning(f"Missing argument for roulette command: user={user_id}, param={error.param.name}")
        else:
            embed = disnake.Embed(
                title="Ошибка",
                description=f"{ctx.author.mention} Неизвестная ошибка: {str(error)}",
                color=0x2F3136
            )
            embed.set_footer(text=f"ID: {user_id}")
            await ctx.send(embed=embed)
            logger.error(f"Unexpected error in roulette command for user {user_id}: {error}")

def setup(bot):
    logger.info("Loading RouletteCog")
    bot.add_cog(RouletteCog(bot))