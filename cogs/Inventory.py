import disnake
from disnake.ext import commands
from utils.database import get_user_inventory
import asyncio
import math
import logging
import time
from config import currency

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class PreviousButton(disnake.ui.Button):
    def __init__(self, disabled=False):
        super().__init__(label="<", style=disnake.ButtonStyle.primary)

    async def callback(self, inter: disnake.MessageInteraction):
        view = self.view
        view.page -= 1
        embed = await view.get_page(view.page)
        view.update_buttons()
        await inter.response.edit_message(embed=embed, view=view)

class NextButton(disnake.ui.Button):
    def __init__(self, disabled=False):
        super().__init__(label=">", style=disnake.ButtonStyle.primary)

    async def callback(self, inter: disnake.MessageInteraction):
        view = self.view
        view.page += 1
        embed = await view.get_page(view.page)
        view.update_buttons()
        await inter.response.edit_message(embed=embed, view=view)

class InventoryView(disnake.ui.View):
    def __init__(self, user, items, page=0, items_per_page=10):
        super().__init__(timeout=180.0)
        self.user = user
        self.items = items
        self.page = page
        self.items_per_page = items_per_page
        self.total_pages = math.ceil(len(items) / items_per_page) if items else 1
        self.add_item(PreviousButton(disabled=True if page == 0 else False))
        self.add_item(NextButton(disabled=True if page >= self.total_pages - 1 else False))

    def update_buttons(self):
        self.children[0].disabled = self.page == 0
        self.children[1].disabled = self.page >= self.total_pages - 1

    async def get_page(self, page):
        embed = disnake.Embed(color=0x2F3136)
        embed.set_author(
            name=self.user.display_name,
            icon_url=self.user.avatar.url if self.user.avatar else self.user.default_avatar.url
        )

        if not self.items:
            embed.description = "Инвентарь пуст"
            return embed

        start_idx = page * self.items_per_page
        end_idx = min(start_idx + self.items_per_page, len(self.items))
        page_items = self.items[start_idx:end_idx]

        total_quantity = sum(item["quantity"] for item in self.items)
        embed.description = f"Всего предметов/кейсов: {total_quantity}"

        for idx, item in enumerate(page_items, start=start_idx + 1):
            embed.add_field(
                name=f"{idx}) {item['name']} - x{item['quantity']}",
                value=item["description"],
                inline=False
            )

        if self.total_pages > 1:
            embed.set_footer(text=f"Страница {self.page + 1}/{self.total_pages}")

        return embed

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        try:
            await self.message.edit(view=self)
        except disnake.HTTPException:
            pass

class InventoryCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        logger.info("InventoryCog initialized")

    @commands.command(name="inventory", aliases=["inv"])
    async def inventory(self, ctx: commands.Context, user: disnake.User = None):
        start_time = time.time()
        logger.info(f"Inventory command invoked: user={ctx.author.id}, target={user.id if user else ctx.author.id}")

        target_user = user or ctx.author

        try:
            items = await get_user_inventory(target_user.id)
            formatted_items = [
                {
                    "item_id": item[0],
                    "quantity": item[1],
                    "name": item[2] or "Неизвестный предмет",
                    "description": item[3] or "Нет описания"
                } for item in items
            ]

            view = InventoryView(target_user, formatted_items, page=0)
            embed = await view.get_page(0)
            message = await ctx.send(embed=embed, view=view)
            view.message = message
            logger.info(f"Inventory command completed in {time.time() - start_time:.2f} seconds")

        except Exception as e:
            logger.error(f"Общая ошибка в inventory: {e}")
            embed = disnake.Embed(
                description=f"<@{ctx.author.id}>, Произошла ошибка при загрузке инвентаря.",
                color=0xFF0000
            )
            await ctx.send(embed=embed)
            logger.info(f"Inventory command failed in {time.time() - start_time:.2f} seconds")

def setup(bot):
    bot.add_cog(InventoryCog(bot))
    logger.info("InventoryCog loaded")