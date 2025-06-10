import disnake
from disnake.ext import commands
import configparser
import os
import time
import logging
import random
import uuid
import asyncio
from utils.database import ensure_user_exists, update_cash, update_bank, get_cooldown, update_cooldown, get_user_balance
from config import currency, COMMAND_CONFIG_ERROR, COMMAND_COOLDOWN, COMMAND_ERROR

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Чтение конфигурации из config.ini
config_file = "config.ini"

if not os.path.exists(config_file):
    logger.error(f"Config file {config_file} not found.")
    raise FileNotFoundError(f"Config file {config_file} not found.")

try:
    config = configparser.ConfigParser()
    config.read(config_file, encoding='utf-8')
except Exception as e:
    logger.error(f"Failed to read {config_file}: {e}")
    raise

# Сообщения для команды collect-income
COLLECT_SUCCESS_MESSAGES = [
    "Награда {currency} {amount} за роль <@&{role_id}> получена!"
]
COLLECT_NO_ROLES_MESSAGE = "У вас нет ролей, за которые можно получить награду."

# Сообщения для команды collectconfig
COLLECT_CONFIG_SUCCESS = "Конфигурация обновлена: роль <@&{role_id}> с наградой {currency} {reward} и кулдауном {cooldown} сек."
COLLECT_CONFIG_DELETE_SUCCESS = "Роль <@&{role_id}> удалена из конфигурации."
COLLECT_CONFIG_INVALID_ROLE = "Укажите действительную роль."
COLLECT_CONFIG_INVALID_REWARD = "Награда должна быть положительным числом."
COLLECT_CONFIG_INVALID_COOLDOWN = "Кулдаун должен быть положительным числом в секундах."
COLLECT_CONFIG_INVALID_REWARD_TYPE = "Тип награды должен быть 'cash' или 'bank'."
COLLECT_CONFIG_NOT_FOUND = "Роль <@&{role_id}> не найдена в конфигурации."
COLLECT_CONFIG_LIST = "Текущая конфигурация:\n{config_list}"
COLLECT_CONFIG_ERROR = "Ошибка при обновлении конфигурации: {error}"

def get_collect_config():
    """Получение настроек из config.ini."""
    try:
        role_ids = [int(id.strip()) for id in config['Collect']['role_id'].strip('[]').split(',') if id.strip()]
        role_rewards = [int(reward.strip()) for reward in config['Collect']['role_reward'].strip('[]').split(',') if reward.strip()]
        reward_cooldowns = [int(cooldown.strip()) for cooldown in config['Collect']['reward_cooldown'].strip('[]').split(',') if cooldown.strip()]
        reward_types = [t.strip() for t in config['Collect']['reward_type'].strip('[]').split(',') if t.strip()]
        
        if not (len(role_ids) == len(role_rewards) == len(reward_cooldowns) == len(reward_types)):
            raise ValueError("Lists role_id, role_reward, reward_cooldown, and reward_type must have the same length.")
        
        for t in reward_types:
            if t not in ['cash', 'bank']:
                raise ValueError(f"Invalid reward_type: '{t}'. Must be 'cash' or 'bank'.")
        
        return [{"role_id": role_id, "reward": reward, "cooldown": cooldown, "reward_type": reward_type}
                for role_id, reward, cooldown, reward_type in zip(role_ids, role_rewards, reward_cooldowns, reward_types)]
    except KeyError as e:
        logger.error(f"Invalid config section for Collect: {e}")
        raise ValueError("Invalid config section for Collect")
    except Exception as e:
        logger.error(f"Error parsing {config_file}: {e}")
        raise ValueError(f"Error parsing {config_file}: {e}")

def save_collect_config(config_list):
    """Сохранение конфигурации в config.ini."""
    try:
        config.read(config_file, encoding='utf-8')  # Перечитываем текущий файл
        config['Collect'] = {
            'role_id': f"[{', '.join(str(item['role_id']) for item in config_list)}]",
            'role_reward': f"[{', '.join(str(item['reward']) for item in config_list)}]",
            'reward_cooldown': f"[{', '.join(str(item['cooldown']) for item in config_list)}]",
            'reward_type': f"[{', '.join(item['reward_type'] for item in config_list)}]"
        }
        with open(config_file, 'w', encoding='utf-8') as f:
            config.write(f)
        logger.info("Collect configuration saved successfully.")
        # Логируем содержимое config.ini для отладки
        with open(config_file, 'r', encoding='utf-8') as f:
            logger.debug(f"Current config.ini content:\n{f.read()}")
    except Exception as e:
        logger.error(f"Error saving {config_file}: {e}")
        raise

class AddRoleModal(disnake.ui.Modal):
    def __init__(self):
        components = [
            disnake.ui.TextInput(
                label="ID роли",
                custom_id="role_id",
                placeholder="Введите ID роли",
                min_length=1,
                max_length=20,
                required=True
            ),
            disnake.ui.TextInput(
                label="Награда (в монетах)",
                custom_id="reward",
                placeholder="Введите число, например: 1000",
                min_length=1,
                max_length=10,
                required=True
            ),
            disnake.ui.TextInput(
                label="Кулдаун (в секундах)",
                custom_id="cooldown",
                placeholder="Введите число, например: 3600",
                min_length=1,
                max_length=10,
                required=True
            ),
            disnake.ui.TextInput(
                label="Тип награды",
                custom_id="reward_type",
                placeholder="Введите 'cash' или 'bank'",
                min_length=4,
                max_length=4,
                required=True
            )
        ]
        super().__init__(title="Добавить роль в коллект", components=components, custom_id=f"add_role_modal_{uuid.uuid4()}")

    async def callback(self, inter: disnake.ModalInteraction):
        start_time = time.time()
        logger.info(f"AddRoleModal callback started: user={inter.author.id}, values={inter.text_values}")

        async def try_defer():
            for attempt in range(3):
                try:
                    await inter.response.defer(ephemeral=True)
                    return True
                except disnake.errors.NotFound:
                    await asyncio.sleep(0.5)
            return False

        if not await try_defer():
            logger.error(f"Failed to defer: user={inter.author.id}")
            return

        try:
            role_id_str = inter.text_values["role_id"]
            reward_str = inter.text_values["reward"]
            cooldown_str = inter.text_values["cooldown"]
            reward_type = inter.text_values["reward_type"].lower()

            try:
                role_id = int(role_id_str)
                reward = int(reward_str)
                cooldown = int(cooldown_str)
                if reward <= 0 or cooldown <= 0:
                    raise ValueError("Награда и кулдаун должны быть положительными")
                if reward_type not in ['cash', 'bank']:
                    raise ValueError(COLLECT_CONFIG_INVALID_REWARD_TYPE)
            except ValueError as e:
                embed = disnake.Embed(
                    title="Ошибка",
                    description=f"<@{inter.author.id}>, Убедитесь, что ID роли, награда и кулдаун - положительные числа, а тип награды - 'cash' или 'bank'. Ошибка: {e}",
                    color=0xFF0000
                )
                await inter.edit_original_response(embed=embed)
                return

            role = inter.guild.get_role(role_id)
            if not role:
                embed = disnake.Embed(
                    title="Ошибка",
                    description=f"<@{inter.author.id}>, Роль с ID {role_id} не найдена на сервере.",
                    color=0xFF0000
                )
                await inter.edit_original_response(embed=embed)
                return

            config_list = get_collect_config()
            config_list.append({"role_id": role.id, "reward": reward, "cooldown": cooldown, "reward_type": reward_type})
            save_collect_config(config_list)

            embed = disnake.Embed(
                title="✅ Роль добавлена",
                description=f"<@{inter.author.id}>, Роль <@&{role_id}> успешно добавлена в коллект.",
                color=0x00FF00
            )
            embed.add_field(name="Награда", value=f"{reward} {currency} ({reward_type})", inline=True)
            embed.add_field(name="Кулдаун", value=f"{cooldown} сек", inline=True)
            await inter.edit_original_response(embed=embed)
            logger.info(f"Role added: user={inter.author.id}, role_id={role_id}, reward={reward}, cooldown={cooldown}, reward_type={reward_type}")
        except Exception as e:
            logger.error(f"Error in AddRoleModal: {e}")
            embed = disnake.Embed(
                title="Ошибка",
                description=f"<@{inter.author.id}>, Не удалось добавить роль. Попробуйте снова.",
                color=0xFF0000
            )
            await inter.edit_original_response(embed=embed)

class EditRoleModal(disnake.ui.Modal):
    def __init__(self, role_id, role_data):
        reward, cooldown, reward_type = role_data
        components = [
            disnake.ui.TextInput(
                label="Награда (в монетах)",
                custom_id="reward",
                placeholder="Введите число, например: 1000",
                value=str(reward),
                min_length=1,
                max_length=10,
                required=True
            ),
            disnake.ui.TextInput(
                label="Кулдаун (в секундах)",
                custom_id="cooldown",
                placeholder="Введите число, например: 3600",
                value=str(cooldown),
                min_length=1,
                max_length=10,
                required=True
            ),
            disnake.ui.TextInput(
                label="Тип награды",
                custom_id="reward_type",
                placeholder="Введите 'cash' или 'bank'",
                value=reward_type,
                min_length=4,
                max_length=4,
                required=True
            )
        ]
        super().__init__(title=f"Редактировать роль ID {role_id}", components=components, custom_id=f"edit_role_modal_{role_id}")

    async def callback(self, inter: disnake.ModalInteraction):
        start_time = time.time()
        logger.info(f"EditRoleModal callback started: user={inter.author.id}, role_id={inter.custom_id.split('_')[-1]}")

        async def try_defer():
            for attempt in range(3):
                try:
                    await inter.response.defer(ephemeral=True)
                    return True
                except disnake.errors.NotFound:
                    await asyncio.sleep(0.5)
            return False

        if not await try_defer():
            logger.error(f"Failed to defer: user={inter.author.id}")
            return

        try:
            reward_str = inter.text_values["reward"]
            cooldown_str = inter.text_values["cooldown"]
            reward_type = inter.text_values["reward_type"].lower()

            try:
                reward = int(reward_str)
                cooldown = int(cooldown_str)
                if reward <= 0 or cooldown <= 0:
                    raise ValueError("Награда и кулдаун должны быть положительными")
                if reward_type not in ['cash', 'bank']:
                    raise ValueError(COLLECT_CONFIG_INVALID_REWARD_TYPE)
            except ValueError as e:
                embed = disnake.Embed(
                    title="Ошибка",
                    description=f"<@{inter.author.id}>, Награда и кулдаун должны быть положительными числами, а тип награды - 'cash' или 'bank'. Ошибка: {e}",
                    color=0xFF0000
                )
                await inter.edit_original_response(embed=embed)
                return

            role_id = int(inter.custom_id.split("_")[-1])
            config_list = get_collect_config()
            for item in config_list:
                if item['role_id'] == role_id:
                    item['reward'] = reward
                    item['cooldown'] = cooldown
                    item['reward_type'] = reward_type
                    break
            else:
                embed = disnake.Embed(
                    title="Ошибка",
                    description=COLLECT_CONFIG_NOT_FOUND.format(role_id=role_id),
                    color=0xFF0000
                )
                await inter.edit_original_response(embed=embed)
                return

            save_collect_config(config_list)
            embed = disnake.Embed(
                title="✅ Роль обновлена",
                description=f"<@{inter.author.id}>, Роль <@&{role_id}> успешно обновлена.",
                color=0x00FF00
            )
            embed.add_field(name="Награда", value=f"{reward} {currency} ({reward_type})", inline=True)
            embed.add_field(name="Кулдаун", value=f"{cooldown} сек", inline=True)
            await inter.edit_original_response(embed=embed)
            logger.info(f"Role edited: user={inter.author.id}, role_id={role_id}, reward={reward}, cooldown={cooldown}, reward_type={reward_type}")
        except Exception as e:
            logger.error(f"Error in EditRoleModal: {e}")
            embed = disnake.Embed(
                title="Ошибка",
                description=f"<@{inter.author.id}>, Не удалось обновить роль. Попробуйте снова.",
                color=0xFF0000
            )
            await inter.edit_original_response(embed=embed)

class RoleSelect(disnake.ui.Select):
    def __init__(self, roles, action):
        options = [
            disnake.SelectOption(
                label=f"ID {item['role_id']} - Награда: {item['reward']} {currency} ({item['reward_type']})",
                value=str(item['role_id']),
                description=f"Кулдаун: {item['cooldown']} сек"
            ) for item in roles
        ]
        super().__init__(
            placeholder=f"Выберите роль для {'редактирования' if action == 'edit' else 'удаления'}",
            min_values=1,
            max_values=1,
            options=options,
            custom_id=f"{action}_role_select_{uuid.uuid4()}"
        )
        self.action = action
        self.roles = {str(item['role_id']): item for item in roles}

    async def callback(self, inter: disnake.ApplicationCommandInteraction):
        start_time = time.time()
        logger.info(f"RoleSelect callback started: user={inter.author.id}, action={self.action}, selected={self.values[0]}")

        try:
            role_id = int(self.values[0])
            role_data = self.roles[self.values[0]]

            if self.action == "edit":
                modal = EditRoleModal(role_id=role_id, role_data=(role_data['reward'], role_data['cooldown'], role_data['reward_type']))
                try:
                    await inter.response.send_modal(modal)
                except disnake.errors.InteractionResponded:
                    logger.warning(f"Interaction already responded for modal: user={inter.author.id}")
                    embed = disnake.Embed(
                        title="Ошибка",
                        description=f"<@{inter.author.id}>, Взаимодействие уже обработано. Попробуйте снова.",
                        color=0xFF0000
                    )
                    await inter.followup.send(embed=embed, ephemeral=True)
                except AttributeError as e:
                    logger.error(f"Cannot send modal, possibly webhook interaction: {e}")
                    embed = disnake.Embed(
                        title="Ошибка",
                        description=f"<@{inter.author.id}>, Не удалось открыть форму редактирования. Попробуйте снова.",
                        color=0xFF0000
                    )
                    await inter.followup.send(embed=embed, ephemeral=True)
            elif self.action == "delete":
                async def try_defer():
                    for attempt in range(3):
                        try:
                            if not inter.response.is_done():
                                await inter.response.defer(ephemeral=True)
                                return True
                            return False
                        except (disnake.errors.NotFound, disnake.errors.InteractionResponded):
                            logger.warning(f"Defer attempt {attempt + 1} failed")
                            await asyncio.sleep(0.5)
                    return False

                deferred = await try_defer()
                config_list = get_collect_config()
                config_list = [item for item in config_list if item['role_id'] != role_id]
                save_collect_config(config_list)
                embed = disnake.Embed(
                    title="✅ Роль удалена",
                    description=COLLECT_CONFIG_DELETE_SUCCESS.format(role_id=role_id),
                    color=0x00FF00
                )
                if deferred:
                    await inter.edit_original_response(embed=embed, view=None)
                else:
                    await inter.response.send(embed=embed, ephemeral=True)
                logger.info(f"Role deleted: user={inter.author.id}, role_id={role_id}")
            logger.info(f"RoleSelect completed in {time.time() - start_time:.2f} seconds")
        except disnake.errors.InteractionResponded:
            logger.warning(f"Interaction already responded: user={inter.author.id}, action={self.action}, selected={self.values[0]}")
            embed = disnake.Embed(
                title="Ошибка",
                description=f"<@{inter.author.id}>, Взаимодействие уже обработано. Попробуйте снова.",
                color=0xFF0000
            )
            await inter.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            logger.error(f"Error in RoleSelect: {e}")
            embed = disnake.Embed(
                title="Ошибка",
                description=f"<@{inter.author.id}>, Произошла ошибка. Попробуйте снова.",
                color=0xFF0000
            )
            await inter.followup.send(embed=embed, ephemeral=True)

class CollectConfigMenu(disnake.ui.Select):
    def __init__(self):
        options = [
            disnake.SelectOption(label="Добавить роль", value="add", description="Добавить новую роль в коллект"),
            disnake.SelectOption(label="Редактировать роль", value="edit", description="Изменить награду или кулдаун роли"),
            disnake.SelectOption(label="Удалить роль", value="delete", description="Удалить роль из коллекта")
        ]
        super().__init__(
            placeholder="Выберите действие",
            options=options,
            custom_id=f"collect_config_menu_{uuid.uuid4()}"
        )

    async def callback(self, inter: disnake.ApplicationCommandInteraction):
        start_time = time.time()
        logger.info(f"CollectConfigMenu callback started: user={inter.author.id}, action={self.values[0]}")

        async def try_defer():
            for attempt in range(3):
                try:
                    if not inter.response.is_done():
                        await inter.response.defer(ephemeral=True)
                        return True
                    return False
                except (disnake.errors.NotFound, disnake.errors.InteractionResponded):
                    await asyncio.sleep(0.5)
            return False

        try:
            action = self.values[0]
            if action == "add":
                await inter.response.send_modal(AddRoleModal())
            else:
                deferred = await try_defer()
                config_list = get_collect_config()
                if not config_list:
                    embed = disnake.Embed(
                        title="Ошибка",
                        description=f"<@{inter.author.id}>, Нет ролей для редактирования или удаления.",
                        color=0xFF0000
                    )
                    if deferred:
                        await inter.edit_original_response(embed=embed)
                    else:
                        await inter.response.send(embed=embed, ephemeral=True)
                    return

                select = RoleSelect(roles=config_list, action=action)
                view = disnake.ui.View()
                view.add_item(select)
                if deferred:
                    await inter.edit_original_response(content="Выберите роль:", view=view)
                else:
                    await inter.response.send(content="Выберите роль:", view=view, ephemeral=True)
            logger.info(f"CollectConfigMenu completed in {time.time() - start_time:.2f} seconds")
        except Exception as e:
            logger.error(f"Error in CollectConfigMenu: {e}")
            embed = disnake.Embed(
                title="Ошибка",
                description=f"<@{inter.author.id}>, Произошла ошибка. Попробуйте снова.",
                color=0xFF0000
            )
            try:
                if inter.response.is_done():
                    await inter.followup.send(embed=embed, ephemeral=True)
                else:
                    await inter.response.send(embed=embed, ephemeral=True)
            except Exception as followup_err:
                logger.error(f"Failed to send error message: {followup_err}")

class CollectCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def check_cooldown(self, ctx, command_name: str, cooldown: int, role_id: int):
        """Проверка кулдауна для конкретной роли."""
        user_id = ctx.author.id
        guild_id = ctx.guild.id
        cooldown_key = f"collect_{role_id}"
        current_time = int(time.time())
        last_used = await get_cooldown(user_id, guild_id, cooldown_key)

        if last_used is not None:
            time_passed = current_time - last_used
            if time_passed < cooldown:
                remaining = cooldown - time_passed
                minutes, seconds = divmod(remaining, 60)
                return False, minutes, seconds, remaining
        return True, 0, 0, 0

    @commands.command(name="collect-income", aliases=["collect", "collectincome"])
    async def collect_income(self, ctx):
        user_id = ctx.author.id
        guild_id = ctx.guild.id
        member = ctx.guild.get_member(user_id)

        try:
            config_list = get_collect_config()
        except ValueError as e:
            embed = disnake.Embed(
                title="Ошибка",
                description=COMMAND_CONFIG_ERROR.format(error=str(e)),
                color=0xFF0000
            )
            await ctx.send(embed=embed)
            logger.error(f"Config error for collect-income command, user {user_id}: {e}")
            return

        eligible_roles = []
        for config_item in config_list:
            role = ctx.guild.get_role(config_item['role_id'])
            if role and role in member.roles:
                eligible_roles.append(config_item)
                logger.debug(f"Role {config_item['role_id']} is eligible for user {user_id}")
            else:
                if not role:
                    logger.warning(f"Role {config_item['role_id']} not found on server {guild_id}")
                else:
                    logger.debug(f"User {user_id} does not have role {config_item['role_id']}")

        if not eligible_roles:
            embed = disnake.Embed(
                title="Нет наград",
                description=COLLECT_NO_ROLES_MESSAGE,
                color=0x2F3136
            )
            await ctx.send(embed=embed)
            logger.info(f"User {user_id} has no eligible roles for collect-income in guild {guild_id}")
            return

        rewards = []
        remaining_cooldowns = []
        all_on_cooldown = True
        for config_item in eligible_roles:
            role_id = config_item['role_id']
            can_collect, minutes, seconds, remaining = await self.check_cooldown(ctx, "collect-income", config_item['cooldown'], role_id)
            if can_collect:
                all_on_cooldown = False
                try:
                    await ensure_user_exists(user_id, guild_id)
                    if config_item['reward_type'] == 'cash':
                        new_balance = await update_cash(user_id, guild_id, config_item['reward'])
                        balance_type = 'cash'
                    elif config_item['reward_type'] == 'bank':
                        new_balance = await update_bank(user_id, guild_id, config_item['reward'])
                        balance_type = 'bank'
                    else:
                        raise ValueError(f"Invalid reward_type: {config_item['reward_type']}")
                    await update_cooldown(user_id, guild_id, f"collect_{role_id}", int(time.time()))
                    message = random.choice(COLLECT_SUCCESS_MESSAGES).format(
                        mention=ctx.author.mention,
                        amount=config_item['reward'],
                        currency=currency,
                        role_id=role_id
                    )
                    rewards.append(f"{message}")
                    logger.info(f"User {user_id} collected {config_item['reward']} ({balance_type}) for role ID {role_id} in guild {guild_id}")
                except Exception as e:
                    logger.error(f"Error processing collect-income for user {user_id}, role ID {role_id}: {e}")
                    rewards.append(f"Ошибка при сборе награды за роль <@&{role_id}>: {str(e)}")
            else:
                rewards.append(f"Роль <@&{role_id}> на кулдауне: осталось {minutes} мин {seconds} сек.")
                remaining_cooldowns.append(remaining)

        if all_on_cooldown and remaining_cooldowns:
            min_remaining = min(remaining_cooldowns)
            minutes, seconds = divmod(min_remaining, 60)
            embed = disnake.Embed(
                title="Кулдаун",
                description=f"Все роли на кулдауне! Ближайший сбор через {minutes} мин {seconds} сек.",
                color=0x2F3136
            )
            await ctx.send(embed=embed)
            logger.info(f"User {user_id} tried collect-income but all roles on cooldown in guild {guild_id}")
            return

        description = "\n".join(rewards)
        cash, bank = await get_user_balance(user_id, guild_id)
        total = cash + bank
        embed = disnake.Embed(
            title="Сбор наград",
            description=f"{description}\n\n**Общий баланс:** {currency} {total}",
            color=0x2F3136
        )
        await ctx.send(embed=embed)

    @commands.slash_command(name="collectconfig", description="Настройка коллекта ролей")
    @commands.has_permissions(administrator=True)
    async def collectconfig(self, inter: disnake.ApplicationCommandInteraction):
        start_time = time.time()
        logger.info(f"Collectconfig command invoked: user={inter.author.id}")

        async def try_defer():
            for attempt in range(3):
                try:
                    if not inter.response.is_done():
                        await inter.response.defer(ephemeral=True)
                        return True
                    return False
                except (disnake.errors.NotFound, disnake.errors.InteractionResponded):
                    await asyncio.sleep(0.5)
            return False

        if not await try_defer():
            logger.error(f"Failed to defer: user={inter.author.id}")
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
            config_list = get_collect_config()
            embed = disnake.Embed(
                title="Настройка коллекта",
                description="Список ролей для сбора наград. Выберите действие ниже.",
                color=0x2F3136
            )

            if config_list:
                roles_text = []
                for item in config_list:
                    role = inter.guild.get_role(item['role_id'])
                    role_name = f"<@&{item['role_id']}>" if role else f"ID {item['role_id']}"
                    roles_text.append(f"Роль: {role_name}\nНаграда: {item['reward']} {currency} ({item['reward_type']})\nКулдаун: {item['cooldown']} сек")
                embed.add_field(name="Роли", value="\n\n".join(roles_text), inline=False)
            else:
                embed.add_field(name="Информация", value="Коллект пуст. Добавьте роли с помощью меню ниже.", inline=False)

            view = disnake.ui.View()
            view.add_item(CollectConfigMenu())
            await inter.edit_original_response(embed=embed, view=view)
            logger.info(f"Collectconfig completed in {time.time() - start_time:.2f} seconds")
        except Exception as e:
            logger.error(f"Error in collectconfig: {e}")
            embed = disnake.Embed(
                title="Ошибка",
                description=f"<@{inter.author.id}>, Произошла ошибка. Попробуйте снова.",
                color=0xFF0000
            )
            await inter.edit_original_response(embed=embed)

def setup(bot):
    bot.add_cog(CollectCog(bot))