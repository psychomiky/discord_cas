import disnake
from disnake.ext import commands
from utils.database import get_user_balance, update_cash, get_cooldown, update_cooldown, get_shop_items, get_shop_item_by_id, get_shop_item_by_name, add_to_inventory
import time
import asyncio
from config import currency
import math
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ShopView(disnake.ui.View):
    def __init__(self, author_id, items, category, currency, cash):
        super().__init__(timeout=180.0)
        self.author_id = author_id
        self.items = items
        self.category = category
        self.currency = currency
        self.cash = cash
        self.items_per_page = 10
        self.current_page = 0
        self.total_pages = math.ceil(len(items) / self.items_per_page) if items else 1
        self.update_buttons()

    def update_buttons(self):
        self.first_page.disabled = self.current_page == 0
        self.previous_page.disabled = self.current_page == 0
        self.next_page.disabled = self.current_page == self.total_pages - 1
        self.last_page.disabled = self.current_page == self.total_pages - 1
        self.page_indicator.label = f"{self.current_page + 1}/{self.total_pages}"
        self.page_indicator.disabled = True

    async def create_embed(self):
        start_time = time.time()
        start_idx = self.current_page * self.items_per_page
        end_idx = start_idx + self.items_per_page
        page_items = self.items[start_idx:end_idx]

        embed = disnake.Embed(
            description=f"Товары в категории `{self.category}`. Используйте `.buy <item_id>` или `.buy <название>` для покупки.",
            color=0x2F3136
        )

        if not page_items:
            embed.description = f"В категории `{self.category}` нет доступных товаров."

        if self.category == "all":
            roles = []
            cases = []
            items_list = []
            for item in page_items:
                item_id, item_type, name, description, price, external_id = item
                item_text = f"**{name}** (ID: {item_id}) – {price} {self.currency}\n{description}"
                if item_type == "role" and external_id:
                    item_text += f"\nРоль: <@&{external_id}>"
                elif external_id:
                    item_text += f"\nExternal ID: {external_id}"
                if item_type == "role":
                    roles.append(item_text)
                elif item_type == "case":
                    cases.append(item_text)
                elif item_type == "item":
                    items_list.append(item_text)

            if roles:
                embed.add_field(name="Роли", value="\n\n".join(roles), inline=False)
            if cases:
                embed.add_field(name="Кейсы", value="\n\n".join(cases), inline=False)
            if items_list:
                embed.add_field(name="Предметы", value="\n\n".join(items_list), inline=False)
        else:
            item_text = [
                f"{i + 1 + start_idx}) **{name}** (ID: {item_id}) – {price} {self.currency}\n{description}"
                + (f"\nРоль: <@&{external_id}>" if item_type == "role" and external_id else f"\nExternal ID: {external_id}" if external_id else "")
                for i, (item_id, item_type, name, description, price, external_id) in enumerate(page_items)
            ]
            embed.add_field(name="Товары", value="\n\n".join(item_text) if item_text else "Нет товаров на этой странице", inline=False)

        embed.set_footer(text=f"Ваш баланс: {self.cash} {self.currency} | Страница {self.current_page + 1}/{self.total_pages}")
        logger.debug(f"ShopView create_embed completed in {time.time() - start_time:.2f} seconds")
        return embed

    async def interaction_check(self, interaction: disnake.MessageInteraction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Только автор команды может листать страницы!", ephemeral=True)
            return False
        return True

    @disnake.ui.button(label="<<", style=disnake.ButtonStyle.primary)
    async def first_page(self, button: disnake.ui.Button, interaction: disnake.MessageInteraction):
        start_time = time.time()
        await interaction.response.defer()
        self.current_page = 0
        self.update_buttons()
        await interaction.edit_original_response(embed=await self.create_embed(), view=self)
        logger.debug(f"ShopView first_page completed in {time.time() - start_time:.2f} seconds")

    @disnake.ui.button(label="<", style=disnake.ButtonStyle.primary)
    async def previous_page(self, button: disnake.ui.Button, interaction: disnake.MessageInteraction):
        start_time = time.time()
        await interaction.response.defer()
        self.current_page = max(0, self.current_page - 1)
        self.update_buttons()
        await interaction.edit_original_response(embed=await self.create_embed(), view=self)
        logger.debug(f"ShopView previous_page completed in {time.time() - start_time:.2f} seconds")

    @disnake.ui.button(label="1/1", style=disnake.ButtonStyle.secondary, disabled=True)
    async def page_indicator(self, button: disnake.ui.Button, interaction: disnake.MessageInteraction):
        pass

    @disnake.ui.button(label=">", style=disnake.ButtonStyle.primary)
    async def next_page(self, button: disnake.ui.Button, interaction: disnake.MessageInteraction):
        start_time = time.time()
        await interaction.response.defer()
        self.current_page = min(self.total_pages - 1, self.current_page + 1)
        self.update_buttons()
        await interaction.edit_original_response(embed=await self.create_embed(), view=self)
        logger.debug(f"ShopView next_page completed in {time.time() - start_time:.2f} seconds")

    @disnake.ui.button(label=">>", style=disnake.ButtonStyle.primary)
    async def last_page(self, button: disnake.ui.Button, interaction: disnake.MessageInteraction):
        start_time = time.time()
        await interaction.response.defer()
        self.current_page = self.total_pages - 1
        self.update_buttons()
        await interaction.edit_original_response(embed=await self.create_embed(), view=self)
        logger.debug(f"ShopView last_page completed in {time.time() - start_time:.2f} seconds")

    async def on_timeout(self):
        start_time = time.time()
        for item in self.children:
            item.disabled = True
        if self.message:
            await self.message.edit(view=self)
        logger.debug(f"ShopView on_timeout completed in {time.time() - start_time:.2f} seconds")

class Shop(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.cooldown_duration = 5
        self.valid_categories = ["role", "case", "item", "all"]
        logger.info("Shop initialized")

    @commands.command(name="shop")
    async def shop(self, ctx, category: str = None):
        start_time = time.time()
        logger.info(f"Shop command invoked: user={ctx.author.id}, category={category}")

        if not category:
            embed = disnake.Embed(
                description="Пожалуйста, выберите категорию товаров:\n"
                           "`shop role` - Роли\n"
                           "`shop case` - Кейсы\n"
                           "`shop item` - Предметы\n"
                           "`shop all` - Все товары\n\n"
                           "Используйте `.buy <item_id>` или `.buy <название>` для покупки.",
                color=0x2F3136
            )
            await ctx.send(embed=embed)
            logger.info(f"Shop command completed (no category) in {time.time() - start_time:.2f} seconds")
            return

        category = category.lower()
        if category not in self.valid_categories:
            embed = disnake.Embed(
                description=f"<@{ctx.author.id}>, неверная категория. Используйте: role, case, item или all.",
                color=0xFF4500
            )
            await ctx.send(embed=embed)
            logger.info(f"Shop command completed (invalid category) in {time.time() - start_time:.2f} seconds")
            return

        try:
            items = await get_shop_items(category)
            logger.debug(f"Database query completed: {time.time() - start_time:.2f} seconds")
        except Exception as e:
            logger.error(f"Ошибка получения товаров из базы данных: {e}")
            embed = disnake.Embed(
                description=f"<@{ctx.author.id}>, не удалось загрузить товары. Попробуйте снова.",
                color=0xFF4500
            )
            await ctx.send(embed=embed)
            logger.info(f"Shop command failed in {time.time() - start_time:.2f} seconds")
            return

        if not items:
            embed = disnake.Embed(
                description=f"<@{ctx.author.id}>, в категории `{category}` нет доступных товаров.",
                color=0xFF4500
            )
            await ctx.send(embed=embed)
            logger.info(f"Shop command completed (no items) in {time.time() - start_time:.2f} seconds")
            return

        cash, _ = await get_user_balance(ctx.author.id, ctx.guild.id)
        view = ShopView(ctx.author.id, items, category, currency, cash)
        view.message = await ctx.send(embed=await view.create_embed(), view=view)
        logger.info(f"Shop command completed in {time.time() - start_time:.2f} seconds")

    @commands.command(name="buy")
    async def buy(self, ctx, *, identifier: str):
        start_time = time.time()
        logger.info(f"Buy command invoked: user={ctx.author.id}, identifier={identifier}")

        last_used = await get_cooldown(ctx.author.id, ctx.guild.id, "buy")
        current_time = int(time.time())
        if last_used and current_time - last_used < self.cooldown_duration:
            remaining = self.cooldown_duration - (current_time - last_used)
            embed = disnake.Embed(
                description=f"<@{ctx.author.id}>, команда `buy` будет доступна через {remaining // 60} мин. {remaining % 60} сек.",
                color=0xFF4500
            )
            await ctx.send(embed=embed)
            logger.info(f"Buy command completed (cooldown) in {time.time() - start_time:.2f} seconds")
            return

        item = None
        try:
            try:
                item_id = int(identifier)
                item = await get_shop_item_by_id(item_id)
            except ValueError:
                item = await get_shop_item_by_name(identifier)
            logger.debug(f"Database query for item completed: {time.time() - start_time:.2f} seconds")
        except Exception as e:
            logger.error(f"Ошибка получения товара из базы данных: {e}")
            embed = disnake.Embed(
                description=f"<@{ctx.author.id}>, не удалось загрузить товар. Попробуйте снова.",
                color=0xFF4500
            )
            await ctx.send(embed=embed)
            logger.info(f"Buy command failed in {time.time() - start_time:.2f} seconds")
            return

        if not item:
            embed = disnake.Embed(
                description=f"<@{ctx.author.id}>, товар с ID или названием '{identifier}' не найден или недоступен.",
                color=0xFF4500
            )
            await ctx.send(embed=embed)
            logger.info(f"Buy command completed (item not found) in {time.time() - start_time:.2f} seconds")
            return

        item_id, item_type, name, description, price, external_id = item
        cash, _ = await get_user_balance(ctx.author.id, ctx.guild.id)

        if cash < price:
            embed = disnake.Embed(
                description=f"<@{ctx.author.id}>, недостаточно средств для покупки.",
                color=0xFF4500
            )
            embed.add_field(name="Требуется", value=f"{price} {currency}", inline=True)
            embed.add_field(name="Доступно", value=f"{cash} {currency}", inline=True)
            await ctx.send(embed=embed)
            logger.info(f"Buy command completed (insufficient funds) in {time.time() - start_time:.2f} seconds")
            return

        if item_type == "role":
            try:
                role_id = int(external_id)
                role = ctx.guild.get_role(role_id)
                if not role:
                    embed = disnake.Embed(
                        description=f"<@{ctx.author.id}>, роль не найдена на сервере. Обратитесь к администратору.",
                        color=0xFF4500
                    )
                    await ctx.send(embed=embed)
                    logger.info(f"Buy command completed (role not found) in {time.time() - start_time:.2f} seconds")
                    return

                if role in ctx.author.roles:
                    embed = disnake.Embed(
                        description=f"<@{ctx.author.id}>, у вас уже есть роль '{name}'.",
                        color=0xFF4500
                    )
                    await ctx.send(embed=embed)
                    logger.info(f"Buy command completed (role already owned) in {time.time() - start_time:.2f} seconds")
                    return
            except ValueError:
                logger.error(f"Некорректный external_id для роли: {external_id}")
                embed = disnake.Embed(
                    description=f"<@{ctx.author.id}>, некорректный ID роли. Обратитесь к администратору.",
                    color=0xFF4500
                )
                await ctx.send(embed=embed)
                logger.info(f"Buy command completed (invalid role ID) in {time.time() - start_time:.2f} seconds")
                return

        try:
            new_cash = await update_cash(ctx.author.id, ctx.guild.id, -price)
            await update_cooldown(ctx.author.id, ctx.guild.id, "buy", current_time)
            logger.debug(f"Balance updated and cooldown set: {time.time() - start_time:.2f} seconds")
        except Exception as e:
            logger.error(f"Ошибка обновления баланса или кулдауна: {e}")
            embed = disnake.Embed(
                description=f"<@{ctx.author.id}>, не удалось обработать покупку. Попробуйте снова.",
                color=0xFF4500
            )
            await ctx.send(embed=embed)
            logger.info(f"Buy command failed in {time.time() - start_time:.2f} seconds")
            return

        if item_type == "role":
            try:
                await ctx.author.add_roles(role)
                logger.debug(f"Role assigned: {time.time() - start_time:.2f} seconds")
                message = f"<@{ctx.author.id}>, вы успешно купили **{name}** за {price} {currency}!\nРоль <@&{role_id}> выдана."
            except disnake.Forbidden:
                embed = disnake.Embed(
                    description=f"<@{ctx.author.id}>, у бота нет прав для выдачи роли '{name}'.",
                    color=0xFF4500
                )
                await ctx.send(embed=embed)
                logger.info(f"Buy command completed (forbidden) in {time.time() - start_time:.2f} seconds")
                return
        else:
            try:
                await add_to_inventory(ctx.author.id, item_id)
                logger.debug(f"Inventory updated: {time.time() - start_time:.2f} seconds")
                message = f"<@{ctx.author.id}>, вы успешно купили **{name}** за {price} {currency}!\n{'Кейс' if item_type == 'case' else 'Предмет'} добавлен в инвентарь. Проверьте с помощью `.inv`."
            except Exception as e:
                logger.error(f"Ошибка добавления в инвентарь: {e}")
                embed = disnake.Embed(
                    description=f"<@{ctx.author.id}>, не удалось добавить товар в инвентарь. Попробуйте снова.",
                    color=0xFF4500
                )
                await ctx.send(embed=embed)
                logger.info(f"Buy command failed in {time.time() - start_time:.2f} seconds")
                return

        embed = disnake.Embed(
            description=message,
            color=0x2F3136
        )
        embed.add_field(name="Баланс", value=f"{new_cash} {currency}", inline=True)
        await ctx.send(embed=embed)
        logger.info(f"Buy command completed in {time.time() - start_time:.2f} seconds")

def setup(bot):
    bot.add_cog(Shop(bot))
    logger.info("Shop loaded")