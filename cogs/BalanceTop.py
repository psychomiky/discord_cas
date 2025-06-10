import disnake
from disnake.ext import commands
import logging
from utils.database import get_user_balance, transfer_to_bank, transfer_from_bank, ensure_user_exists, get_user_position, get_top_users, get_total_balance
from config import currency, BALANCE_BOT_ERROR, BALANCE_ERROR, LEADERBOARD_NOTICE, LEADERBOARD_NO_USERS, LEADERBOARD_ERROR, DEPOSIT_INVALID_AMOUNT, DEPOSIT_INSUFFICIENT, DEPOSIT_ZERO_AMOUNT, DEPOSIT_ERROR, WITHDRAW_INVALID_AMOUNT, WITHDRAW_INSUFFICIENT, WITHDRAW_ZERO_AMOUNT, WITHDRAW_ERROR

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_ordinal_suffix(position: int) -> str:
    """Возвращает суффикс для позиции (1st, 2nd, 3rd, 4th, ...)."""
    if 10 <= position % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(position % 10, "th")
    return f"{position}{suffix}"

class LeaderboardView(disnake.ui.View):
    """Класс для интерактивных кнопок пагинации в leaderboard."""
    def __init__(self, author_id: int, users: list, sort_field: str, display_field: str, guild_name: str, total_balance: int, guild_id: int, items_per_page: int = 10):
        super().__init__(timeout=60.0)
        self.author_id = author_id
        self.users = users
        self.sort_field = sort_field
        self.display_field = display_field
        self.guild_name = guild_name
        self.total_balance = total_balance
        self.guild_id = guild_id
        self.items_per_page = items_per_page
        self.current_page = 0
        self.total_pages = (len(users) + items_per_page - 1) // items_per_page
        self.update_buttons()

    def update_buttons(self):
        """Обновляет состояние кнопок в зависимости от текущей страницы."""
        self.children[0].disabled = self.current_page == 0
        self.children[1].disabled = self.current_page == 0
        self.children[3].disabled = self.current_page == self.total_pages - 1
        self.children[4].disabled = self.current_page == self.total_pages - 1
        self.children[2].label = f"{self.current_page + 1}/{self.total_pages}"

    async def create_embed(self):
        """Создает эмбед для текущей страницы."""
        embed = disnake.Embed(
            title=f"Топ по {self.display_field}",
            color=0x2F3136
        )
        start_idx = self.current_page * self.items_per_page
        end_idx = start_idx + self.items_per_page
        page_users = self.users[start_idx:end_idx]

        for i, (user_id, cash, bank) in enumerate(page_users, start_idx + 1):
            try:
                user = await self.bot.fetch_user(user_id)
                display_name = user.display_name if user else "Неизвестный пользователь"
            except disnake.NotFound:
                display_name = "Неизвестный пользователь"
            total = cash + bank
            value = cash if self.sort_field == "cash" else bank if self.sort_field == "bank" else total
            embed.add_field(
                name=f"{i}. {display_name}",
                value=f"{currency} {value}",
                inline=False
            )
            embed.set_author(
                name=f"{self.guild_name} Список лидеров",
                icon_url='https://media.discordapp.net/attachments/1312800066171310103/1372501278827085916/top.png'
            )

        embed.set_footer(text=f"Guild: {self.guild_id}")
        return embed

    async def interaction_check(self, interaction: disnake.MessageInteraction) -> bool:
        """Проверяет, что взаимодействие выполнено автором команды."""
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Только автор команды может листать страницы!", ephemeral=True)
            return False
        return True

    @disnake.ui.button(label="<<", style=disnake.ButtonStyle.primary)
    async def first_page(self, button: disnake.ui.Button, interaction: disnake.MessageInteraction):
        self.current_page = 0
        self.update_buttons()
        await interaction.response.edit_message(embed=await self.create_embed(), view=self)

    @disnake.ui.button(label="<", style=disnake.ButtonStyle.primary)
    async def previous_page(self, button: disnake.ui.Button, interaction: disnake.MessageInteraction):
        self.current_page = max(0, self.current_page - 1)
        self.update_buttons()
        await interaction.response.edit_message(embed=await self.create_embed(), view=self)

    @disnake.ui.button(label="1/1", style=disnake.ButtonStyle.secondary, disabled=True)
    async def page_indicator(self, button: disnake.ui.Button, interaction: disnake.MessageInteraction):
        pass

    @disnake.ui.button(label=">", style=disnake.ButtonStyle.primary)
    async def next_page(self, button: disnake.ui.Button, interaction: disnake.MessageInteraction):
        self.current_page = min(self.total_pages - 1, self.current_page + 1)
        self.update_buttons()
        await interaction.response.edit_message(embed=await self.create_embed(), view=self)

    @disnake.ui.button(label=">>", style=disnake.ButtonStyle.primary)
    async def last_page(self, button: disnake.ui.Button, interaction: disnake.MessageInteraction):
        self.current_page = self.total_pages - 1
        self.update_buttons()
        await interaction.response.edit_message(embed=await self.create_embed(), view=self)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            await self.message.edit(view=self)

class EconomyCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="balance", aliases=["bal"])
    async def balance(self, ctx, user: disnake.Member = None):
        guild_id = ctx.guild.id
        default_user = ctx.author
        if user is None:
            target_user = default_user
            user_id = default_user.id
        else:
            if user.bot:
                embed = disnake.Embed(
                    title="Ошибка",
                    description=BALANCE_BOT_ERROR,
                    color=0x2F3136
                )
                await ctx.send(embed=embed)
                logger.info(f"User {ctx.author.id} tried to check balance of bot {user.id} in guild {guild_id}")
                return
            target_user = user
            user_id = user.id

        try:
            await ensure_user_exists(user_id, guild_id)
            cash, bank = await get_user_balance(user_id, guild_id)
            total = cash + bank
            position = await get_user_position(user_id, guild_id)
            user = await self.bot.fetch_user(user_id)
            embed = disnake.Embed(
                title=f"Баланс {user.display_name}",
                description=(f"Позиция в топе: {get_ordinal_suffix(position)}\n"
                ),
                color=0x2F3136
            )
            embed.add_field(name="💵 Cash",value=f"{currency} {cash}", inline=True)
            embed.add_field(name="🏦 Bank",value=f"{currency} {bank}", inline=True)
            embed.add_field(name="💰 Total",value=f"{currency} {total}", inline=True)
            await ctx.send(embed=embed)
            logger.info(f"User {ctx.author.id} checked balance for user {user_id} in guild {guild_id}: cash={cash}, bank={bank}, total={total}")
        except Exception as e:
            embed = disnake.Embed(
                title="Ошибка",
                description=BALANCE_ERROR.format(error=str(e)),
                color=0x2F3136
            )
            await ctx.send(embed=embed)
            logger.error(f"Error fetching balance for user {user_id} in guild {guild_id}: {e}")

    @commands.command(name="deposit", aliases=["dep"])
    async def deposit(self, ctx, amount: str):
        user_id = ctx.author.id
        guild_id = ctx.guild.id
        try:
            cash, bank = await get_user_balance(user_id, guild_id)
            if amount.lower() == "all":
                transfer_amount = cash
            else:
                try:
                    transfer_amount = int(amount)
                except ValueError:
                    embed = disnake.Embed(
                        title="Ошибка",
                        description=DEPOSIT_INVALID_AMOUNT,
                        color=0x2F3136
                    )
                    await ctx.send(embed=embed)
                    return
            if transfer_amount <= 0:
                embed = disnake.Embed(
                    title="Ошибка",
                    description=DEPOSIT_ZERO_AMOUNT,
                    color=0x2F3136
                )
                await ctx.send(embed=embed)
                return
            if transfer_amount > cash:
                embed = disnake.Embed(
                    title="Ошибка",
                    description=DEPOSIT_INSUFFICIENT.format(cash=cash, bank=bank, currency=currency),
                    color=0x2F3136
                )
                await ctx.send(embed=embed)
                return
            new_cash, new_bank = await transfer_to_bank(user_id, guild_id, transfer_amount)
            user = await self.bot.fetch_user(user_id)
            embed = disnake.Embed(
                title=f"{user.display_name}",
                description=(
                    f"✅ на ваш счет переведено {currency} {transfer_amount}"
                ),
                color=0x2F3136
            )
            await ctx.send(embed=embed)
            logger.info(f"User {user_id} deposited {transfer_amount} in guild {guild_id}")
        except ValueError as e:
            embed = disnake.Embed(
                title="Ошибка",
                description=str(e),
                color=0x2F3136
            )
            await ctx.send(embed=embed)
        except Exception as e:
            embed = disnake.Embed(
                title="Ошибка",
                description=DEPOSIT_ERROR.format(error=str(e)),
                color=0x2F3136
            )
            await ctx.send(embed=embed)
            logger.error(f"Error processing deposit for user {user_id} in guild {guild_id}: {e}")

    @commands.command(name="withdraw", aliases=["with"])
    async def withdraw(self, ctx, amount: str):
        user_id = ctx.author.id
        guild_id = ctx.guild.id
        try:
            cash, bank = await get_user_balance(user_id, guild_id)
            if amount.lower() == "all":
                transfer_amount = bank
            else:
                try:
                    transfer_amount = int(amount)
                except ValueError:
                    embed = disnake.Embed(
                        title="Ошибка",
                        description=WITHDRAW_INVALID_AMOUNT,
                        color=0x2F3136
                    )
                    await ctx.send(embed=embed)
                    return
            if transfer_amount <= 0:
                embed = disnake.Embed(
                    title="Ошибка",
                    description=WITHDRAW_ZERO_AMOUNT,
                    color=0x2F3136
                )
                await ctx.send(embed=embed)
                return
            if transfer_amount > bank:
                embed = disnake.Embed(
                    title="Ошибка",
                    description=WITHDRAW_INSUFFICIENT.format(bank=bank, cash=cash, currency=currency),
                    color=0x2F3136
                )
                await ctx.send(embed=embed)
                return
            new_cash, new_bank = await transfer_from_bank(user_id, guild_id, transfer_amount)
            user = await self.bot.fetch_user(user_id)
            embed = disnake.Embed(
                title=f"{user.display_name}",
                description=(
                    f"✅ с вашего счета снято {currency} {transfer_amount}"
                ),
                color=0x2F3136
            )
            await ctx.send(embed=embed)
            logger.info(f"User {user_id} withdrew {transfer_amount} in guild {guild_id}")
        except ValueError as e:
            embed = disnake.Embed(
                title="Ошибка",
                description=str(e),
                color=0x2F3136
            )
            await ctx.send(embed=embed)
        except Exception as e:
            embed = disnake.Embed(
                title="Ошибка",
                description=WITHDRAW_ERROR.format(error=str(e)),
                color=0x2F3136
            )
            await ctx.send(embed=embed)
            logger.error(f"Error processing withdraw for user {user_id} in guild {guild_id}: {e}")

    @commands.command(name="leaderboard", aliases=["top", "lb"])
    async def top(self, ctx, sort_by: str = "-total"):
        guild_id = ctx.guild.id
        sort_by = sort_by.lower()
        valid_sorts = ["-cash", "-bank", "-total"]
        if sort_by not in valid_sorts:
            embed = disnake.Embed(
                title="Уведомление",
                description=LEADERBOARD_NOTICE,
                color=0x2F3136
            )
            await ctx.send(embed=embed)
            return
        if sort_by == "-cash":
            sort_field = "cash"
            display_field = "Cash"
        elif sort_by == "-bank":
            sort_field = "bank"
            display_field = "Bank"
        else:
            sort_field = "total"
            display_field = "Total"
        try:
            top_users = await get_top_users(guild_id, sort_field)
            total_balance = await get_total_balance(guild_id)
            if not top_users:
                embed = disnake.Embed(
                    title="Ошибка",
                    description=LEADERBOARD_NO_USERS,
                    color=0x2F3136
                )
                await ctx.send(embed=embed)
                return
            view = LeaderboardView(
                author_id=ctx.author.id,
                users=top_users,
                sort_field=sort_field,
                display_field=display_field,
                guild_name=ctx.guild.name,
                total_balance=total_balance,
                guild_id=guild_id
            )
            view.bot = self.bot
            embed = await view.create_embed()
            view.message = await ctx.send(embed=embed, view=view)
            logger.info(f"User {ctx.author.id} requested top list in guild {guild_id} sorted by {sort_field}")
        except Exception as e:
            embed = disnake.Embed(
                title="Ошибка",
                description=LEADERBOARD_ERROR.format(error=str(e)),
                color=0x2F3136
            )
            await ctx.send(embed=embed)
            logger.error(f"Error fetching top list for guild {guild_id}: {e}")

def setup(bot):
    bot.add_cog(EconomyCog(bot))