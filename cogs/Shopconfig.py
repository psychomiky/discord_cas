import disnake
from disnake.ext import commands
from utils.database import add_shop_item, update_shop_item, deactivate_shop_item, get_all_shop_items
import asyncio
from config import currency
import uuid
import logging
import time

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AddItemModal(disnake.ui.Modal):
    def __init__(self):
        components = [
            disnake.ui.TextInput(
                label="Тип товара",
                custom_id="type",
                placeholder="Введите: role, case или item",
                min_length=4,
                max_length=4,
                required=True
            ),
            disnake.ui.TextInput(
                label="Название товара",
                custom_id="name",
                placeholder="Например: VIP Роль",
                min_length=1,
                max_length=100,
                required=True
            ),
            disnake.ui.TextInput(
                label="Описание товара",
                custom_id="description",
                placeholder="Например: Дает доступ к эксклюзивным каналам",
                min_length=1,
                max_length=500,
                required=True
            ),
            disnake.ui.TextInput(
                label="Цена (в монетах)",
                custom_id="price",
                placeholder="Введите число, например: 1000",
                min_length=1,
                max_length=10,
                required=True
            ),
            disnake.ui.TextInput(
                label="External ID (Role ID для role)",
                custom_id="external_id",
                placeholder="Введите ID роли для role или ID предмета/кейса",
                min_length=0,
                max_length=20,
                required=False
            )
        ]
        super().__init__(title="Добавить товар в магазин", components=components, custom_id=f"add_item_modal_{uuid.uuid4()}")

    async def callback(self, inter: disnake.ModalInteraction):
        start_time = time.time()
        logger.info(f"AddItemModal callback started: user={inter.author.id}, values={inter.text_values}")

        async def try_defer():
            for attempt in range(3):
                try:
                    await inter.response.defer(ephemeral=True)
                    logger.debug(f"Deferred response: {time.time() - start_time:.2f} seconds")
                    return True
                except disnake.errors.NotFound as e:
                    logger.warning(f"Defer attempt {attempt + 1} failed: {e}")
                    await asyncio.sleep(0.5)
            return False

        if not await try_defer():
            logger.error(f"Failed to defer after retries: user={inter.author.id}")
            try:
                await inter.channel.send(
                    embed=disnake.Embed(
                        title="Ошибка",
                        description=f"<@{inter.author.id}>, не удалось обработать запрос. Попробуйте снова.",
                        color=0xFF0000
                    )
                )
            except Exception as e:
                logger.error(f"Failed to send fallback message: {e}")
            return

        try:
            type_input = inter.text_values["type"].lower()
            name = inter.text_values["name"]
            description = inter.text_values["description"]
            price_str = inter.text_values["price"]
            external_id_str = inter.text_values["external_id"]

            if type_input not in ["role", "case", "item"]:
                embed = disnake.Embed(
                    title="Ошибка",
                    description=f"<@{inter.author.id}>, Тип должен быть: role, case или item.",
                    color=0xFF0000
                )
                await inter.edit_original_response(embed=embed)
                logger.debug(f"Invalid type validation: {time.time() - start_time:.2f} seconds")
                return

            external_id = None
            if type_input == "role":
                if not external_id_str:
                    embed = disnake.Embed(
                        title="Ошибка",
                        description=f"<@{inter.author.id}>, Для роли необходимо указать ID роли.",
                        color=0xFF0000
                    )
                    await inter.edit_original_response(embed=embed)
                    logger.debug(f"Missing role ID: {time.time() - start_time:.2f} seconds")
                    return
                try:
                    external_id = int(external_id_str)
                    role = inter.guild.get_role(external_id)
                    if not role:
                        embed = disnake.Embed(
                            title="Ошибка",
                            description=f"<@{inter.author.id}>, Роль с ID {external_id} не найдена на сервере.",
                            color=0xFF0000
                        )
                        await inter.edit_original_response(embed=embed)
                        logger.debug(f"Role not found: {time.time() - start_time:.2f} seconds")
                        return
                except ValueError:
                    embed = disnake.Embed(
                        title="Ошибка",
                        description=f"<@{inter.author.id}>, Неверный формат ID роли.",
                        color=0xFF0000
                    )
                    await inter.edit_original_response(embed=embed)
                    logger.debug(f"Invalid role ID format: {time.time() - start_time:.2f} seconds")
                    return
            else:
                external_id = external_id_str if external_id_str else None

            try:
                price = int(price_str)
                if price <= 0:
                    raise ValueError("Цена должна быть положительной")
            except ValueError:
                embed = disnake.Embed(
                    title="Ошибка",
                    description=f"<@{inter.author.id}>, Цена должна быть положительным числом.",
                    color=0xFF0000
                )
                await inter.edit_original_response(embed=embed)
                logger.debug(f"Invalid price: {time.time() - start_time:.2f} seconds")
                return

            try:
                item_id = await add_shop_item(type_input, name, description, price, external_id)
                logger.debug(f"Item added to database: {time.time() - start_time:.2f} seconds")
                embed = disnake.Embed(
                    title="✅ Товар добавлен",
                    description=f"<@{inter.author.id}>, Товар **{name}** (ID: {item_id}) успешно добавлен в магазин.",
                    color=0x00FF00
                )
                embed.add_field(name="Тип", value=type_input, inline=True)
                embed.add_field(name="Цена", value=f"{price} {currency}", inline=True)
                embed.add_field(name="Описание", value=description, inline=False)
                if external_id:
                    embed.add_field(name="External ID", value=external_id, inline=True)
                await inter.edit_original_response(embed=embed)
                logger.info(f"AddItemModal completed in {time.time() - start_time:.2f} seconds")
            except Exception as e:
                logger.error(f"Ошибка добавления товара: {e}")
                embed = disnake.Embed(
                    title="Ошибка",
                    description=f"<@{inter.author.id}>, Не удалось добавить товар. Попробуйте снова.",
                    color=0xFF0000
                )
                await inter.edit_original_response(embed=embed)
                logger.info(f"AddItemModal failed in {time.time() - start_time:.2f} seconds")
        except Exception as e:
            logger.error(f"Общая ошибка в AddItemModal: {e}")
            embed = disnake.Embed(
                title="Ошибка",
                description=f"<@{inter.author.id}>, Произошла ошибка. Попробуйте снова.",
                color=0xFF0000
            )
            await inter.edit_original_response(embed=embed)
            logger.info(f"AddItemModal failed in {time.time() - start_time:.2f} seconds")

class EditItemModal(disnake.ui.Modal):
    def __init__(self, item_id, item_data):
        type_input, name, description, price, external_id = item_data
        components = [
            disnake.ui.TextInput(
                label="Тип товара",
                custom_id="type",
                placeholder="Введите: role, case или item",
                value=type_input,
                min_length=4,
                max_length=4,
                required=True
            ),
            disnake.ui.TextInput(
                label="Название товара",
                custom_id="name",
                placeholder="Например: VIP Роль",
                value=name,
                min_length=1,
                max_length=100,
                required=True
            ),
            disnake.ui.TextInput(
                label="Описание товара",
                custom_id="description",
                placeholder="Например: Дает доступ к эксклюзивным каналам",
                value=description,
                min_length=1,
                max_length=500,
                required=True
            ),
            disnake.ui.TextInput(
                label="Цена (в монетах)",
                custom_id="price",
                placeholder="Введите число, например: 1000",
                value=str(price),
                min_length=1,
                max_length=10,
                required=True
            ),
            disnake.ui.TextInput(
                label="External ID (Role ID для role)",
                custom_id="external_id",
                placeholder="Введите ID роли для role или ID предмета/кейса",
                value=external_id or "",
                min_length=0,
                max_length=20,
                required=False
            )
        ]
        super().__init__(title=f"Редактировать товар ID {item_id}", components=components, custom_id=f"edit_item_modal_{item_id}")

    async def callback(self, inter: disnake.ModalInteraction):
        start_time = time.time()
        logger.info(f"EditItemModal callback started: user={inter.author.id}, item_id={inter.custom_id.split('_')[-1]}, values={inter.text_values}")

        async def try_defer():
            for attempt in range(3):
                try:
                    await inter.response.defer(ephemeral=True)
                    logger.debug(f"Deferred response: {time.time() - start_time:.2f} seconds")
                    return True
                except disnake.errors.NotFound as e:
                    logger.warning(f"Defer attempt {attempt + 1} failed: {e}")
                    await asyncio.sleep(0.5)
            return False

        if not await try_defer():
            logger.error(f"Failed to defer after retries: user={inter.author.id}")
            try:
                await inter.channel.send(
                    embed=disnake.Embed(
                        title="Ошибка",
                        description=f"<@{inter.author.id}>, не удалось обработать запрос. Попробуйте снова.",
                        color=0xFF0000
                    )
                )
            except Exception as e:
                logger.error(f"Failed to send fallback message: {e}")
            return

        try:
            type_input = inter.text_values["type"].lower()
            name = inter.text_values["name"]
            description = inter.text_values["description"]
            price_str = inter.text_values["price"]
            external_id_str = inter.text_values["external_id"]

            if type_input not in ["role", "case", "item"]:
                embed = disnake.Embed(
                    title="Ошибка",
                    description=f"<@{inter.author.id}>, Тип должен быть: role, case или item.",
                    color=0xFF0000
                )
                await inter.edit_original_response(embed=embed)
                logger.debug(f"Invalid type validation: {time.time() - start_time:.2f} seconds")
                return

            external_id = None
            if type_input == "role":
                if not external_id_str:
                    embed = disnake.Embed(
                        title=" Ошибка",
                        description=f"<@{inter.author.id}>, Для роли необходимо указать ID роли.",
                        color=0xFF0000
                    )
                    await inter.edit_original_response(embed=embed)
                    logger.debug(f"Missing role ID: {time.time() - start_time:.2f} seconds")
                    return
                try:
                    external_id = int(external_id_str)
                    role = inter.guild.get_role(external_id)
                    if not role:
                        embed = disnake.Embed(
                            title=" Ошибка",
                            description=f"<@{inter.author.id}>, Роль с ID {external_id} не найдена на сервере.",
                            color=0xFF0000
                        )
                        await inter.edit_original_response(embed=embed)
                        logger.debug(f"Role not found: {time.time() - start_time:.2f} seconds")
                        return
                except ValueError:
                    embed = disnake.Embed(
                        title="Ошибка",
                        description=f"<@{inter.author.id}>, Неверный формат ID роли.",
                        color=0xFF0000
                    )
                    await inter.edit_original_response(embed=embed)
                    logger.debug(f"Invalid role ID format: {time.time() - start_time:.2f} seconds")
                    return
            else:
                external_id = external_id_str if external_id_str else None

            try:
                price = int(price_str)
                if price <= 0:
                    raise ValueError("Цена должна быть положительной")
            except ValueError:
                embed = disnake.Embed(
                    title="Ошибка",
                    description=f"<@{inter.author.id}>, Цена должна быть положительным числом.",
                    color=0xFF0000
                )
                await inter.edit_original_response(embed=embed)
                logger.debug(f"Invalid price: {time.time() - start_time:.2f} seconds")
                return

            try:
                item_id = int(inter.custom_id.split("_")[-1])
                await update_shop_item(item_id, type_input, name, description, price, external_id)
                logger.debug(f"Item updated in database: {time.time() - start_time:.2f} seconds")
                embed = disnake.Embed(
                    title="✅ Товар обновлен",
                    description=f"<@{inter.author.id}>, Товар **{name}** (ID: {item_id}) успешно обновлен.",
                    color=0x00FF00
                )
                embed.add_field(name="Тип", value=type_input, inline=True)
                embed.add_field(name="Цена", value=f"{price} {currency}", inline=True)
                embed.add_field(name="Описание", value=description, inline=False)
                if external_id:
                    embed.add_field(name="External ID", value=external_id, inline=True)
                await inter.edit_original_response(embed=embed)
                logger.info(f"EditItemModal completed in {time.time() - start_time:.2f} seconds")
            except Exception as e:
                logger.error(f"Ошибка обновления товара: {e}")
                embed = disnake.Embed(
                    title="Ошибка",
                    description=f"<@{inter.author.id}>, Не удалось обновить товар. Попробуйте снова.",
                    color=0xFF0000
                )
                await inter.edit_original_response(embed=embed)
                logger.info(f"EditItemModal failed in {time.time() - start_time:.2f} seconds")
        except Exception as e:
            logger.error(f"Общая ошибка в EditItemModal: {e}")
            embed = disnake.Embed(
                title="Ошибка",
                description=f"<@{inter.author.id}>, Произошла ошибка. Попробуйте снова.",
                color=0xFF0000
            )
            await inter.edit_original_response(embed=embed)
            logger.info(f"EditItemModal failed in {time.time() - start_time:.2f} seconds")

class ItemSelect(disnake.ui.Select):
    def __init__(self, items, action, placeholder):
        options = [
            disnake.SelectOption(
                label=f"ID {item[0]} - {item[2]} ({item[1]})",
                value=str(item[0]),
                description=item[3][:100]
            ) for item in items
        ]
        super().__init__(
            placeholder=placeholder,
            options=options,
            custom_id=f"{action}_item_select_{uuid.uuid4()}"
        )
        self.action = action
        self.items = {str(item[0]): item for item in items}

    async def callback(self, inter: disnake.ApplicationCommandInteraction):
        start_time = time.time()
        logger.info(f"ItemSelect callback started: user={inter.author.id}, action={self.action}, selected={self.values[0]}")

        await asyncio.sleep(0.1)  # Предотвращение состояния гонки

        try:
            item_id = int(self.values[0])
            item = self.items[self.values[0]]

            if self.action == "edit":
                modal = EditItemModal(
                    item_id=item_id,
                    item_data=(item[1], item[2], item[3], item[4], item[5])
                )
                await inter.response.send_modal(modal)
                logger.debug(f"Edit modal sent: {time.time() - start_time:.2f} seconds")
            elif self.action == "remove":
                async def try_defer():
                    for attempt in range(3):
                        try:
                            if not inter.response.is_done():
                                await inter.response.defer(ephemeral=True)
                                logger.debug(f"Deferred response: {time.time() - start_time:.2f} seconds")
                                return True
                            return True
                        except disnake.errors.NotFound as e:
                            logger.warning(f"Defer attempt {attempt + 1} failed: {e}")
                            await asyncio.sleep(0.5)
                    return False

                if not await try_defer():
                    logger.error(f"Failed to defer after retries: user={inter.author.id}")
                    try:
                        await inter.channel.send(
                            embed=disnake.Embed(
                                title="Ошибка",
                                description=f"<@{inter.author.id}>, не удалось обработать запрос. Попробуйте снова.",
                                color=0xFF0000
                            )
                        )
                    except Exception as e:
                        logger.error(f"Failed to send fallback message: {e}")
                    return

                try:
                    await deactivate_shop_item(item_id)
                    logger.debug(f"Item deactivated in database: {time.time() - start_time:.2f} seconds")
                    embed = disnake.Embed(
                        title="✅ Товар деактивирован",
                        description=f"<@{inter.author.id}>, Товар **{item[2]}** (ID: {item_id}) успешно деактивирован и удален из инвентарей.",
                        color=0x00FF00
                    )
                    await inter.edit_original_response(embed=embed)
                    logger.debug(f"Success response sent: {time.time() - start_time:.2f} seconds")
                except Exception as e:
                    logger.error(f"Ошибка деактивации товара: {e}")
                    embed = disnake.Embed(
                        title="Ошибка",
                        description=f"<@{inter.author.id}>, Не удалось деактивировать товар. Попробуйте снова.",
                        color=0xFF0000
                    )
                    await inter.edit_original_response(embed=embed)
                    logger.debug(f"Error response sent: {time.time() - start_time:.2f} seconds")
            logger.info(f"ItemSelect completed in {time.time() - start_time:.2f} seconds")
        except Exception as e:
            logger.error(f"Критическая ошибка в ItemSelect.callback: {e}")
            embed = disnake.Embed(
                title="Ошибка",
                description=f"<@{inter.author.id}>, Произошла ошибка при обработке запроса.",
                color=0xFF0000
            )
            await inter.edit_original_response(embed=embed)
            logger.info(f"ItemSelect failed in {time.time() - start_time:.2f} seconds")

class ShopConfigMenu(disnake.ui.Select):
    def __init__(self):
        options = [
            disnake.SelectOption(label="Добавить товар", value="add", description="Создать новый товар"),
            disnake.SelectOption(label="Редактировать товар", value="edit", description="Изменить существующий товар"),
            disnake.SelectOption(label="Деактивировать товар", value="remove", description="Пометить товар как неактивный и удалить из инвентарей")
        ]
        super().__init__(
            placeholder="Выберите действие",
            options=options,
            custom_id=f"shop_config_menu_{uuid.uuid4()}"
        )

    async def callback(self, inter: disnake.ApplicationCommandInteraction):
        start_time = time.time()
        logger.info(f"ShopConfigMenu callback started: user={inter.author.id}, action={self.values[0]}")

        async def try_defer():
            for attempt in range(3):
                try:
                    await inter.response.defer(ephemeral=True)
                    logger.debug(f"Deferred response: {time.time() - start_time:.2f} seconds")
                    return True
                except disnake.errors.NotFound as e:
                    logger.warning(f"Defer attempt {attempt + 1} failed: {e}")
                    await asyncio.sleep(0.5)
            return False

        try:
            action = self.values[0]

            if action == "add":
                logger.debug(f"Sending modal for AddItemModal: user={inter.author.id}")
                await inter.response.send_modal(AddItemModal())
                logger.debug(f"Add modal sent: {time.time() - start_time:.2f} seconds")
            else:
                if not await try_defer():
                    logger.error(f"Failed to defer after retries: user={inter.author.id}")
                    try:
                        await inter.channel.send(
                            embed=disnake.Embed(
                                title="Ошибка",
                                description=f"<@{inter.author.id}>, не удалось обработать запрос. Попробуйте снова.",
                                color=0xFF0000
                            )
                        )
                    except Exception as e:
                        logger.error(f"Failed to send fallback message: {e}")
                    return

                try:
                    items = await get_all_shop_items()
                    active_items = [item for item in items if item[6]]  # Только активные товары
                    logger.debug(f"Retrieved {len(active_items)} active items from database: {time.time() - start_time:.2f} seconds")
                except Exception as e:
                    logger.error(f"Ошибка получения товаров из базы данных: {e}")
                    embed = disnake.Embed(
                        title="Ошибка",
                        description=f"<@{inter.author.id}>, Не удалось загрузить товары. Попробуйте снова.",
                        color=0xFF0000
                    )
                    await inter.edit_original_response(embed=embed)
                    return

                if not active_items:
                    embed = disnake.Embed(
                        title="Ошибка",
                        description=f"<@{inter.author.id}>, Нет активных товаров для редактирования или деактивации.",
                        color=0xFF0000
                    )
                    await inter.edit_original_response(embed=embed)
                    logger.debug(f"No active items found: {time.time() - start_time:.2f} seconds")
                    return

                select = ItemSelect(
                    items=active_items,
                    action=action,
                    placeholder="Выберите товар для {}".format("редактирования" if action == "edit" else "деактивации")
                )
                view = disnake.ui.View()
                view.add_item(select)
                await inter.edit_original_response(content="Выберите товар:", view=view)
                logger.debug(f"Select menu sent: {time.time() - start_time:.2f} seconds")
            logger.info(f"ShopConfigMenu completed in {time.time() - start_time:.2f} seconds")
        except Exception as e:
            logger.error(f"Критическая ошибка в ShopConfigMenu.callback: {e}")
            embed = disnake.Embed(
                title="Ошибка",
                description=f"<@{inter.author.id}>, Произошла ошибка при обработке запроса.",
                color=0xFF0000
            )
            await inter.followup.send(embed=embed, ephemeral=True)
            logger.info(f"ShopConfigMenu failed in {time.time() - start_time:.2f} seconds")

class ShopConfig(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        logger.info("ShopConfig initialized")

    @commands.slash_command(name="shopconfig", description="Настройка магазина сервера")
    @commands.has_permissions(administrator=True)
    async def shopconfig(self, inter: disnake.ApplicationCommandInteraction):
        start_time = time.time()
        logger.info(f"Shopconfig command invoked: user={inter.author.id}")

        async def try_defer():
            for attempt in range(3):
                try:
                    await inter.response.defer(ephemeral=True)
                    logger.debug(f"Deferred response: {time.time() - start_time:.2f} seconds")
                    return True
                except disnake.errors.NotFound as e:
                    logger.warning(f"Defer attempt {attempt + 1} failed: {e}")
                    await asyncio.sleep(0.5)
            return False

        if not await try_defer():
            logger.error(f"Failed to defer after retries: user={inter.author.id}")
            try:
                await inter.channel.send(
                    embed=disnake.Embed(
                        title="Ошибка",
                        description=f"<@{inter.author.id}>, не удалось обработать команду. Попробуйте снова.",
                        color=0xFF0000
                    )
                )
            except Exception as e:
                logger.error(f"Failed to send fallback message: {e}")
            return

        try:
            items = await get_all_shop_items()
            logger.debug(f"Retrieved {len(items)} items from database: {time.time() - start_time:.2f} seconds")

            embed = disnake.Embed(
                title="Настройка магазина",
                description="Список всех товаров в магазине. Выберите действие ниже.",
                color=0x2F3136
            )

            roles = []
            cases = []
            items_list = []
            for item in items:
                item_id, item_type, name, description, price, external_id, active = item
                if not active:
                    continue
                item_text = f"**ID: {item_id}** - {name} ({price} {currency})\n{description}"
                if item_type == "role" and external_id:
                    roles.append(item_text + f"\nРоль: <@&{external_id}>")
                elif item_type == "case":
                    cases.append(item_text + (f"\nExternal ID: {external_id}" if external_id else ""))
                elif item_type == "item":
                    items_list.append(item_text + (f"\nExternal ID: {external_id}" if external_id else ""))

            if roles:
                embed.add_field(name="Роли", value="\n\n".join(roles), inline=False)
            if cases:
                embed.add_field(name="Кейсы", value="\n\n".join(cases), inline=False)
            if items_list:
                embed.add_field(name="Предметы", value="\n\n".join(items_list), inline=False)
            if not (roles or cases or items_list):
                embed.add_field(name="Информация", value="Магазин пуст. Добавьте товары с помощью меню ниже.", inline=False)

            view = disnake.ui.View()
            view.add_item(ShopConfigMenu())

            await inter.edit_original_response(embed=embed, view=view)
            logger.info(f"Shopconfig completed in {time.time() - start_time:.2f} seconds")
        except Exception as e:
            logger.error(f"Критическая ошибка в shopconfig: {e}")
            embed = disnake.Embed(
                title="Ошибка",
                description=f"<@{inter.author.id}>, Произошла ошибка при обработке команды.",
                color=0xFF0000
            )
            await inter.edit_original_response(embed=embed)
            logger.info(f"Shopconfig failed in {time.time() - start_time:.2f} seconds")

def setup(bot):
    bot.add_cog(ShopConfig(bot))
    logger.info("ShopConfig loaded")