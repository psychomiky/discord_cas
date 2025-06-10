import disnake
from disnake.ext import commands
import logging
import asyncio

from utils.database import get_pool, init_db

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ID пользователя, которому разрешено выполнять команду
ALLOWED_USER_ID = 852873937917968405


class DatabaseClearCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        logger.info("Initialized DatabaseClearCog")

    async def drop_and_recreate_schema(self) -> bool:
        """
        Удаляем всю текущую схему public (со всеми таблицами и зависимостями),
        затем создаём её заново и вызываем init_db() для воссоздания таблиц.
        """
        try:
            pool = await get_pool()
            async with pool.acquire() as conn:
                # Выполняем DROP/CREATE SCHEMA внутри стандартной транзакции aiopg
                async with conn.cursor() as cur:
                    # 1) Удаляем схему public вместе со всеми объектами
                    await cur.execute("DROP SCHEMA public CASCADE;")
                    logger.info("Схема public удалена")

                    # 2) Создаем пустую схему public
                    await cur.execute("CREATE SCHEMA public;")
                    logger.info("Схема public создана")

                # Коммит транзакции произойдёт при выходе из async with conn.cursor()
                logger.info("Очистка схемы выполнена")
            # 3) Переинициализируем структуру через init_db()
            await init_db()
            logger.info("Все таблицы пересозданы через init_db")
            return True

        except Exception as e:
            logger.error(f"Ошибка при очистке схемы и пересоздании: {e}")
            return False

    @commands.command(name="clear_database", aliases=["cleardb"])
    async def clear_database(self, ctx: commands.Context):
        """
        Полная очистка и пересоздание базы данных (для тестов).
        Удаляет все таблицы и заново создаёт их.
        """
        logger.info(f"Команда очистки БД вызвана: user={ctx.author.id}, channel={ctx.channel.id}")

        # Проверка прав: только ALLOWED_USER_ID может выполнить
        if ctx.author.id != ALLOWED_USER_ID:
            embed = disnake.Embed(
                title="🚫 Ошибка",
                description=f"<@{ctx.author.id}>, у вас нет прав для выполнения этой команды!",
                color=0xFF0000
            )
            await ctx.send(embed=embed)
            logger.warning(f"Несанкционированная попытка очистки БД: user={ctx.author.id}")
            return

        # Запрашиваем подтверждение
        embed = disnake.Embed(
            title="⚠️ Предупреждение",
            description=(
                f"<@{ctx.author.id}>, вы собираетесь **полностью удалить все таблицы** из текущей схемы PostgreSQL.\n"
                "Это действие необратимо и удалит все данные (пользователи, игры, транзакции и т.д.).\n\n"
                "**Для подтверждения введите** `.confirm_drop_database` **в течение 30 секунд.**"
            ),
            color=0xFF0000
        )
        await ctx.send(embed=embed)
        logger.info(f"Ожидание подтверждения от user={ctx.author.id}")

        def check(m: disnake.Message):
            return (
                m.author.id == ctx.author.id and
                m.channel.id == ctx.channel.id and
                m.content == ".confirm_drop_database"
            )

        try:
            await self.bot.wait_for("message", check=check, timeout=30.0)
        except asyncio.TimeoutError:
            embed = disnake.Embed(
                title="🚫 Отмена",
                description=f"<@{ctx.author.id}>, очистка базы данных отменена — подтверждение не получено.",
                color=0xFF0000
            )
            await ctx.send(embed=embed)
            logger.info(f"Очистка БД отменена: user={ctx.author.id} не подтвердил")
            return

        # Выполняем удаление схемы и пересоздание таблиц
        success = await self.drop_and_recreate_schema()
        if success:
            embed = disnake.Embed(
                title="🧹 База данных пересоздана",
                description=(
                    f"<@{ctx.author.id}>, все таблицы успешно удалены и заново созданы. "
                    "Схема пуста, инициализация выполнена."
                ),
                color=0x00FF00
            )
            logger.info(f"БД успешно пересоздана: user={ctx.author.id}")
        else:
            embed = disnake.Embed(
                title="🚫 Ошибка",
                description=(
                    f"<@{ctx.author.id}>, произошла ошибка при удалении/пересоздании базы данных. "
                    "Проверьте логи."
                ),
                color=0xFF0000
            )
            logger.error(f"Не удалось пересоздать БД: user={ctx.author.id}")

        await ctx.send(embed=embed)


def setup(bot: commands.Bot):
    bot.add_cog(DatabaseClearCog(bot))
    logger.info("DatabaseClearCog загружен")
