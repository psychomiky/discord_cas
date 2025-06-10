import disnake
from disnake import Embed
from disnake.ext import commands
import random
import asyncio
import logging

from datetime import datetime, timezone

from utils.database import (
    get_pool,
    get_all_cases,
    get_case_contents,
    get_item_id_by_external,
    decrement_inventory,
    add_to_inventory,
    update_bank,
    update_cash,
    add_shop_item,
    update_shop_item,
    deactivate_shop_item,
    add_case_content,
    update_case_content,
    delete_case_content,
    add_or_update_temp_role,
    remove_temp_role_record,
    get_all_active_temp_roles
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def format_duration(seconds: int) -> str:
    """
    Разбивает секунды на месяцы, дни, часы, минуты, секунды и выводит до непустых компонентов.
    """
    parts = []
    # 1 месяц ≈ 30 дней = 2592000 секунд
    if seconds >= 2592000:
        m = seconds // 2592000
        seconds %= 2592000
        parts.append(f"{m}мес")
    if seconds >= 86400:
        d = seconds // 86400
        seconds %= 86400
        parts.append(f"{d}д")
    if seconds >= 3600:
        h = seconds // 3600
        seconds %= 3600
        parts.append(f"{h}ч")
    if seconds >= 60:
        m = seconds // 60
        seconds %= 60
        parts.append(f"{m}м")
    if seconds > 0 or not parts:
        parts.append(f"{seconds}с")
    return " ".join(parts)


class Cases(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.temp_role_data = {}
        bot.loop.create_task(self._recover_temp_roles())

    async def _recover_temp_roles(self):
        """
        Восстанавливает задачи по удалению временных ролей после рестарта бота.
        """
        await self.bot.wait_until_ready()
        try:
            rows = await get_all_active_temp_roles()
            now_ts = int(datetime.now(timezone.utc).timestamp())

            for user_id, guild_id, role_id, expires_at in rows:
                expires_ts = int(expires_at.replace(tzinfo=timezone.utc).timestamp())
                delay = max(0, expires_ts - now_ts)

                guild = self.bot.get_guild(guild_id)
                if guild is None:
                    continue
                try:
                    member = guild.get_member(user_id) or await guild.fetch_member(user_id)
                except:
                    continue

                role_obj = guild.get_role(role_id)
                if role_obj and role_obj not in member.roles:
                    try:
                        await member.add_roles(role_obj, reason="Восстановление временной роли")
                    except Exception as e_add:
                        logger.error(f"recover_temp_role: {e_add}")

                key = (user_id, role_id)

                async def remove_later(m: disnake.Member, rid: int, delay_secs: int):
                    try:
                        await asyncio.sleep(delay_secs)
                        role_obj2 = m.guild.get_role(rid)
                        if role_obj2 and role_obj2 in m.roles:
                            try:
                                await m.remove_roles(role_obj2, reason="Срок временной роли истёк")
                            except Exception as e_rm:
                                logger.error(f"recover_remove_temp_role: {e_rm}")
                        self.temp_role_data.pop((m.id, rid), None)
                        try:
                            await remove_temp_role_record(m.id, m.guild.id, rid)
                        except Exception as e_db2:
                            logger.error(f"remove_temp_role_record error: {e_db2}")
                    except asyncio.CancelledError:
                        return

                task = self.bot.loop.create_task(remove_later(member, role_id, delay))
                self.temp_role_data[key] = {"expires": expires_ts, "task": task}

            logger.info("Восстановлены задачи на удаление временных ролей.")
        except Exception as e:
            logger.error(f"_recover_temp_roles: {e}")

    async def schedule_temp_role_removal(self, member: disnake.Member, role_id: int, until_ts: int):
        """
        Планирует удаление временной роли в момент until_ts.
        """
        key = (member.id, role_id)
        prev = self.temp_role_data.get(key)
        if prev and prev.get("task"):
            prev["task"].cancel()

        now_ts = int(datetime.now(timezone.utc).timestamp())
        delay = max(0, until_ts - now_ts)

        async def remove_later():
            try:
                await asyncio.sleep(delay)
                role_obj = member.guild.get_role(role_id)
                if role_obj and role_obj in member.roles:
                    try:
                        await member.remove_roles(role_obj, reason="Срок временной роли истёк")
                    except Exception as e2:
                        logger.error(f"remove_temp_role: {e2}")
                self.temp_role_data.pop(key, None)
                try:
                    await remove_temp_role_record(member.id, member.guild.id, role_id)
                except Exception as e_db:
                    logger.error(f"remove_temp_role_record error: {e_db}")
            except asyncio.CancelledError:
                return

        task = asyncio.create_task(remove_later())
        self.temp_role_data[key] = {"expires": until_ts, "task": task}


    # -----------------------------
    #  Префикс‐группа .case
    # -----------------------------
    @commands.group(name="case", invoke_without_command=True)
    async def case(self, ctx: commands.Context):
        embed = Embed(
            title="📦 Команды с кейсами",
            description=(
                "`.case list` — показать все кейсы\n"
                "`.case drops <имя кейса>` — показать награды и шансы\n"
                "`.case open <количество> <имя кейса>` — открыть кейсы"
            ),
            color=0x2F3136
        )
        await ctx.send(embed=embed)

    @case.command(name="list")
    async def case_list(self, ctx: commands.Context):
        try:
            cases = await get_all_cases()
            if not cases:
                embed = Embed(
                    title="📦 Нет кейсов",
                    description="Пока нет активных кейсов.",
                    color=0xFFD700
                )
                return await ctx.send(embed=embed)

            embed = Embed(title="📦 Доступные кейсы", color=0x2F3136)
            for item_id, name, description, price, _ext in cases:
                embed.add_field(
                    name=f"**{name}** — {price} 💰",
                    value=description,
                    inline=False
                )
            embed.set_footer(text="`.case drops <имя>` • `.case open <количество> <имя>`")
            await ctx.send(embed=embed)

        except Exception as e:
            logger.error(f"case_list: {e}")
            await ctx.send(
                embed=Embed(
                    title="🚫 Ошибка",
                    description="Не удалось загрузить список кейсов.",
                    color=0xFF0000
                )
            )

    @case.command(name="drops")
    async def case_drops(self, ctx: commands.Context, *, partial_name: str):
        try:
            all_cases = await get_all_cases()
            matches = [r for r in all_cases if r[1].lower() == partial_name.lower()]
            if not matches:
                matches = [r for r in all_cases if partial_name.lower() in r[1].lower()]

            if not matches:
                return await ctx.send(
                    embed=Embed(
                        title="❓ Кейс не найден",
                        description=f"Укажите корректное имя или часть имени: `{partial_name}`",
                        color=0xFFA500
                    )
                )
            if len(matches) > 1:
                names = "\n".join(f"• {r[1]}" for r in matches)
                return await ctx.send(
                    embed=Embed(
                        title="❓ Несколько вариантов",
                        description=f"Найдены похожие кейсы:\n{names}\n\nУточните имя.",
                        color=0xFFA500
                    )
                )

            item_id, name, description, price, external_id = matches[0]
            drops = await get_case_contents(external_id)
            if not drops:
                return await ctx.send(
                    embed=Embed(
                        title=f"ℹ️ Нет наград для «{name}»",
                        description="Администратор ещё не настроил награды.",
                        color=0xFFD700
                    )
                )

            embed = Embed(title=f"🎲 Награды «{name}»", color=0x2F3136)
            for row in drops:
                if len(row) != 7:
                    continue
                cid, rtype, rval, chance, dur_secs, comp_coins, hidden = row

                if hidden:
                    label = "???"
                else:
                    if rtype == "coins_cash":
                        label = f"Монеты: {rval}"
                    elif rtype == "coins_bank":
                        label = f"Монеты (в банк): {rval}"
                    elif rtype == "role_perm":
                        label = f"Роль: <@&{rval}>"
                    elif rtype == "role_temp":
                        dur = format_duration(dur_secs) if dur_secs else "—"
                        label = f"Временная роль: <@&{rval}> ({dur})"
                    elif rtype == "item":
                        label = f"Предмет: `{rval}`"
                    elif rtype == "case":
                        label = f"Кейс: `{rval}`"
                    else:
                        label = f"{rtype}: `{rval}`"

                embed.add_field(
                    name=f"• {label}",
                    value=f"Шанс: {chance}%",
                    inline=False
                )
            await ctx.send(embed=embed)

        except Exception as e:
            logger.error(f"case_drops: {e}")
            await ctx.send(
                embed=Embed(
                    title="🚫 Ошибка",
                    description="Не удалось получить награды кейса.",
                    color=0xFF0000
                )
            )

    @case.command(name="open")
    async def case_open(self, ctx: commands.Context, count: int, *, partial_name: str):
        user = ctx.author
        user_id = user.id
        guild_id = ctx.guild.id

        try:
            pool = await get_pool()
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("""
SELECT si.item_id, si.name, ui.quantity, si.external_id
FROM user_inventory AS ui
JOIN shop_items AS si ON si.item_id = ui.item_id
WHERE ui.user_id = %s AND si.type = 'case' AND ui.quantity > 0;
""", (user_id,))
                    owned = await cur.fetchall()

            if not owned:
                return await ctx.send(
                    embed=Embed(
                        title="ℹ️ У вас нет кейсов",
                        description="В инвентаре отсутствуют кейсы.",
                        color=0xFFD700
                    )
                )

            matches = [
                (item_id, name, qty, ext)
                for (item_id, name, qty, ext) in owned
                if partial_name.lower() in name.lower()
            ]
            if not matches:
                return await ctx.send(
                    embed=Embed(
                        title="❓ Кейс не найден",
                        description=f"В инвентаре не найден кейс, содержащий «{partial_name}».",
                        color=0xFFA500
                    )
                )
            if len(matches) > 1:
                names = "\n".join(f"• {m[1]} (×{m[2]})" for m in matches)
                return await ctx.send(
                    embed=Embed(
                        title="❓ Несколько совпадений",
                        description=f"Найдены кейсы:\n{names}\nУточните имя.",
                        color=0xFFA500
                    )
                )

            item_id, actual_name, qty_owned, case_ext_id = matches[0]
            if count > qty_owned:
                return await ctx.send(
                    embed=Embed(
                        title="❗ Недостаточно кейсов",
                        description=f"У вас есть только **{qty_owned}** × «{actual_name}».",
                        color=0xFFA500
                    )
                )

            drops = await get_case_contents(case_ext_id)
            if not drops:
                return await ctx.send(
                    embed=Embed(
                        title="ℹ️ Награды не настроены",
                        description=f"В кейсе «{actual_name}» пока нет дропов.",
                        color=0xFFD700
                    )
                )

            valid_drops = [row for row in drops if len(row) == 7]
            if not valid_drops:
                return await ctx.send(
                    embed=Embed(
                        title="🚫 Ошибка",
                        description="Некорректная запись дропа (ожидалось 7 полей).",
                        color=0xFF0000
                    )
                )

            # Проверяем сумму шансов
            probs = [(row[0], float(row[3])) for row in valid_drops]
            total_chance = sum(p for _, p in probs)
            if abs(total_chance - 100.0) > 1e-6:
                # Если сумма шансов не равна ровно 100%
                return await ctx.send(
                    embed=Embed(
                        title="🚫 Ошибка администрирования",
                        description=(
                            f"Суммарный шанс дропов для «{actual_name}» составляет **{total_chance}%**. "
                            "Попросите администрацию исправить сумму шансов до 100%."
                        ),
                        color=0xFF0000
                    )
                )

            # Копим кумулятивные вероятности
            cum = []
            acc = 0.0
            for cid, p in probs:
                acc += p
                cum.append((cid, acc))

            total_cash = 0
            total_bank = 0

            perm_roles_assigned = {}
            compensation_for_roles = {}

            temp_roles_info = {}

            items_received = {}
            nested_cases = {}

            now_ts = int(datetime.now(timezone.utc).timestamp())

            # Открываем count кейсов
            for _ in range(count):
                r = random.random() * total_chance
                chosen_cid = None
                for cid, bound in cum:
                    if r <= bound:
                        chosen_cid = cid
                        break
                if chosen_cid is None:
                    chosen_cid = cum[-1][0]

                sel = next(x for x in valid_drops if x[0] == chosen_cid)
                _, rtype, rval, _chance, dur_secs, comp_coins, hidden = sel

                if rtype == "coins_cash":
                    total_cash += int(rval)

                elif rtype == "coins_bank":
                    total_bank += int(rval)

                elif rtype == "role_perm":
                    role_id = int(rval)
                    role_obj = ctx.guild.get_role(role_id)
                    if role_obj in user.roles:
                        if comp_coins > 0:
                            compensation_for_roles.setdefault(role_id, 0)
                            compensation_for_roles[role_id] += comp_coins
                    else:
                        if role_obj:
                            await user.add_roles(role_obj, reason="Кейс: перм-роль")
                            perm_roles_assigned.setdefault(role_id, 0)
                            perm_roles_assigned[role_id] += 1

                elif rtype == "role_temp":
                    role_id = int(rval)
                    role_obj = ctx.guild.get_role(role_id)

                    key = (user_id, role_id)
                    existing = self.temp_role_data.get(key)
                    if existing and existing["expires"] > now_ts:
                        base_expires = existing["expires"]
                        new_expires = base_expires + dur_secs
                        if comp_coins > 0:
                            compensation_for_roles.setdefault(role_id, 0)
                            compensation_for_roles[role_id] += comp_coins
                    else:
                        new_expires = now_ts + dur_secs
                        if role_obj:
                            await user.add_roles(role_obj, reason="Кейс: временная роль")

                    expires_dt = datetime.fromtimestamp(new_expires, tz=timezone.utc)
                    try:
                        await add_or_update_temp_role(user_id, guild_id, role_id, expires_dt)
                    except Exception as e_db:
                        logger.error(f"DB add_or_update_temp_role error: {e_db}")

                    await self.schedule_temp_role_removal(user, role_id, new_expires)

                    info = temp_roles_info.get(role_id, {"added": 0, "final_expires": new_expires})
                    info["added"] += dur_secs
                    info["final_expires"] = new_expires
                    temp_roles_info[role_id] = info

                elif rtype == "item":
                    child_item = await get_item_id_by_external(rval)
                    if child_item:
                        await add_to_inventory(user_id, child_item, 1)
                        items_received.setdefault(rval, 0)
                        items_received[rval] += 1

                elif rtype == "case":
                    child_item = await get_item_id_by_external(rval)
                    if child_item:
                        await add_to_inventory(user_id, child_item, 1)
                        nested_cases.setdefault(rval, 0)
                        nested_cases[rval] += 1

                else:
                    continue

            # Снимаем из инвентаря открытые кейсы
            await decrement_inventory(user_id, item_id, count)

            # Обновляем баланс, если что-нибудь выпало
            if total_cash:
                try:
                    await update_cash(user_id, guild_id, total_cash)
                except Exception as e:
                    logger.error(f"update_cash: {e}")
            if total_bank:
                try:
                    await update_bank(user_id, guild_id, total_bank)
                except Exception as e:
                    logger.error(f"update_bank: {e}")

            total_comp_coins = sum(compensation_for_roles.values())
            if total_comp_coins:
                try:
                    await update_bank(user_id, guild_id, total_comp_coins)
                except Exception as e:
                    logger.error(f"compensation update_bank: {e}")

            # Собираем эмбед
            embed = Embed(
                title=f"🎁 Открытие {count}× «{actual_name}»",
                color=0x2F3136
            )

            if total_cash:
                embed.add_field(name="💰 Наличные", value=f"🪙 {total_cash}", inline=False)

            if total_bank:
                embed.add_field(name="🏦 Банк", value=f"🪙 {total_bank}", inline=False)

            if temp_roles_info:
                now_ts2 = int(datetime.now(timezone.utc).timestamp())
                for role_id, info in temp_roles_info.items():
                    role_obj = ctx.guild.get_role(role_id)
                    role_name = role_obj.name if role_obj else str(role_id)
                    added = info["added"]
                    final_exp = info["final_expires"]
                    remaining = max(0, final_exp - now_ts2)
                    granted_str = format_duration(added)
                    remaining_str = format_duration(remaining)
                    embed.add_field(
                        name=f"⏳ Временная роль «{role_name}»",
                        value=f"получил: {granted_str}, осталось: {remaining_str}",
                        inline=False
                    )

            if perm_roles_assigned:
                lines = []
                for rid, cnt in perm_roles_assigned.items():
                    role_obj = ctx.guild.get_role(rid)
                    role_name = role_obj.name if role_obj else str(rid)
                    lines.append(f"• {role_name} ×{cnt}")
                embed.add_field(name="🌟 Перм-роли", value="\n".join(lines), inline=False)

            if items_received:
                txt = "\n".join(f"• `{name}` ×{cnt}" for name, cnt in items_received.items())
                embed.add_field(name="📦 Предметы", value=txt, inline=False)

            if nested_cases:
                txt = "\n".join(f"• `{cid}` ×{cnt}" for cid, cnt in nested_cases.items())
                embed.add_field(name="📦 Вложенные кейсы", value=txt, inline=False)

            if compensation_for_roles:
                lines = []
                for rid, comp_sum in compensation_for_roles.items():
                    if comp_sum > 0:
                        role_obj = ctx.guild.get_role(rid)
                        role_name = role_obj.name if role_obj else str(rid)
                        lines.append(f"• «{role_name}» — 🪙 {comp_sum}")
                if lines:
                    embed.add_field(name="💵 Компенсация за роли (банк)", value="\n".join(lines), inline=False)

            total_money = total_cash + total_bank + total_comp_coins
            if total_money > 0:
                embed.set_footer(text=f"СуммарноПолучено: 🪙 {total_money}")

            await ctx.send(embed=embed)

        except Exception as e:
            logger.error(f"case_open: {e}")
            await ctx.send(
                embed=Embed(
                    title="🚫 Ошибка",
                    description="Не удалось открыть кейсы.",
                    color=0xFF0000
                )
            )


    # -----------------------------
    #  Админ: /caseconfig (Slash)
    # -----------------------------
    @commands.slash_command(
        name="caseconfig",
        description="🔧 Панель управления кейсами"
    )
    @commands.has_permissions(administrator=True)
    async def caseconfig(self, inter: disnake.ApplicationCommandInteraction):
        # сразу отправляем сообщение, чтобы не было тайм-аута
        embed = Embed(
            title="🛠 Настройка кейсов",
            description=(
                "Выберите действие:\n"
                "• ➕ Добавить\n"
                "• ✏️ Редактировать\n"
                "• 🚫 Деактивировать\n"
                "• 🎲 Дропы"
            ),
            color=0x2F3136
        )
        view = CaseConfigView(self.bot)
        await inter.response.send_message(embed=embed, view=view, ephemeral=True)


# ----------------------------
#  VIEW для /caseconfig
# ----------------------------
class CaseConfigView(disnake.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot
        options = [
            disnake.SelectOption(label="➕ Добавить", value="add_case", description="Новый кейс"),
            disnake.SelectOption(label="✏️ Редактировать", value="edit_case", description="Изменить кейс"),
            disnake.SelectOption(label="🚫 Деактивировать", value="delete_case", description="Вывести из продажи"),
            disnake.SelectOption(label="🎲 Дропы", value="manage_drops", description="Управление дропами")
        ]
        select = disnake.ui.Select(
            placeholder="Выберите действие",
            options=options,
            custom_id="case_config_action"
        )
        select.callback = self.on_action_select
        self.add_item(select)

    async def on_action_select(self, inter: disnake.MessageInteraction):
        action = inter.values[0]
        all_cases = await get_all_cases()

        if action == "add_case":
            return await inter.response.send_modal(AddCaseModal())

        if not all_cases:
            return await inter.response.send_message(
                embed=Embed(
                    title="ℹ️ Нет кейсов",
                    description="В магазине нет активных кейсов.",
                    color=0xFFD700
                ),
                ephemeral=True
            )

        options = [
            disnake.SelectOption(
                label=f"{name} (ID {item_id})",
                value=str(item_id),
                description=f"ext_id: {ext} | price: {price}"
            )
            for item_id, name, _desc, price, ext in all_cases
        ]
        select = disnake.ui.Select(
            placeholder="Выберите кейс",
            options=options,
            custom_id=f"case_sel_{action}"
        )
        view = disnake.ui.View(timeout=None)
        view.add_item(select)

        async def sel_callback(inter2: disnake.MessageInteraction):
            chosen_id = int(inter2.values[0])

            if action == "delete_case":
                try:
                    await deactivate_shop_item(chosen_id)
                    return await inter2.response.send_message(
                        embed=Embed(
                            title="✅ Кейс деактивирован",
                            description=f"ID {chosen_id} удалён из продажи.",
                            color=0x00FF00
                        ),
                        ephemeral=True
                    )
                except Exception as e:
                    logger.error(f"del_case: {e}")
                    return await inter2.response.send_message(
                        embed=Embed(
                            title="🚫 Ошибка",
                            description="Не удалось деактивировать кейс.",
                            color=0xFF0000
                        ),
                        ephemeral=True
                    )

            if action == "edit_case":
                pool = await get_pool()
                async with pool.acquire() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute("""
SELECT name, description, price, external_id
FROM shop_items
WHERE item_id = %s;
""", (chosen_id,))
                        row = await cur.fetchone()
                if not row:
                    return await inter2.response.send_message(
                        embed=Embed(
                            title="🚫 Ошибка",
                            description="Кейс не найден.",
                            color=0xFF0000
                        ),
                        ephemeral=True
                    )
                name, desc, price, extid = row
                return await inter2.response.send_modal(EditCaseModal(chosen_id, name, desc, price, extid))

            # Управление дропами
            pool2 = await get_pool()
            async with pool2.acquire() as conn2:
                async with conn2.cursor() as cur2:
                    await cur2.execute("""
SELECT external_id, name FROM shop_items WHERE item_id = %s;
""", (chosen_id,))
                    row2 = await cur2.fetchone()
            if not row2:
                return await inter2.response.send_message(
                    embed=Embed(
                        title="🚫 Ошибка",
                        description="Кейс не найден.",
                        color=0xFF0000
                    ),
                    ephemeral=True
                )
            ext_id, case_name = row2
            drops = await get_case_contents(ext_id)

            embed_drops = Embed(
                title=f"🎲 Дропы «{case_name}»",
                description="Текущий список наград:",
                color=0x2F3136
            )
            if not drops:
                embed_drops.description = "Награды ещё не настроены."
            else:
                for row in drops:
                    if len(row) != 7:
                        continue
                    cid, rtype, rval, chance, dur, comp, hidden = row
                    if hidden:
                        disp = "???"
                    else:
                        if rtype in ("coins_cash", "coins_bank"):
                            disp = f"Монеты: {rval}"
                        elif rtype == "role_perm":
                            disp = f"Перм-роль <@&{rval}>"
                        elif rtype == "role_temp":
                            dr = format_duration(dur) if dur else "—"
                            disp = f"Временная роль <@&{rval}> ({dr})"
                        elif rtype == "item":
                            disp = f"Предмет `{rval}`"
                        elif rtype == "case":
                            disp = f"Влож. кейс `{rval}`"
                        else:
                            disp = f"{rtype}: `{rval}`"
                    embed_drops.add_field(
                        name=f"• [{cid}] {disp}",
                        value=f"Шанс: {chance}%",
                        inline=False
                    )

            await inter2.response.send_message(embed=embed_drops, view=ManageDropsView(self.bot, chosen_id), ephemeral=True)

        select.callback = sel_callback
        await inter.response.send_message(
            embed=Embed(
                title="🔧 Выбор кейса",
                description="Выберите кейс для действия.",
                color=0x2F3136
            ),
            view=view,
            ephemeral=True
        )


# ----------------------------
#  МОДАЛКИ
# ----------------------------
class AddCaseModal(disnake.ui.Modal):
    def __init__(self):
        components = [
            disnake.ui.TextInput(
                label="Название кейса",
                custom_id="case_name",
                style=disnake.TextInputStyle.short,
                placeholder="Например: Epic Box",
                required=True
            ),
            disnake.ui.TextInput(
                label="Описание",
                custom_id="case_desc",
                style=disnake.TextInputStyle.long,
                placeholder="Кратко о содержимом",
                max_length=200,
                required=True
            ),
            disnake.ui.TextInput(
                label="Цена (целое)",
                custom_id="case_price",
                style=disnake.TextInputStyle.short,
                placeholder="Например: 1000",
                required=True
            ),
            disnake.ui.TextInput(
                label="external_id (уникально)",
                custom_id="case_extid",
                style=disnake.TextInputStyle.short,
                placeholder="Например: epic_box_1",
                required=True
            )
        ]
        super().__init__(title="➕ Добавить кейс", components=components, custom_id="add_case_modal")

    async def callback(self, inter: disnake.ModalInteraction):
        await inter.response.defer(ephemeral=True)

        name = inter.text_values["case_name"].strip()
        desc = inter.text_values["case_desc"].strip()
        price_str = inter.text_values["case_price"].strip()
        extid = inter.text_values["case_extid"].strip()

        existing = await get_item_id_by_external(extid)
        if existing:
            return await inter.followup.send(
                embed=Embed(
                    title="🚫 Ошибка",
                    description=f"Кейс с external_id `{extid}` уже существует (ID {existing}).",
                    color=0xFF0000
                ),
                ephemeral=True
            )

        try:
            price = int(price_str)
            if price < 0:
                raise ValueError
        except:
            return await inter.followup.send(
                embed=Embed(
                    title="🚫 Ошибка",
                    description="Цена должна быть неотрицательным целым числом.",
                    color=0xFF0000
                ),
                ephemeral=True
            )

        try:
            cid = await add_shop_item("case", name, desc, price, extid)
            await inter.followup.send(
                embed=Embed(
                    title="✅ Кейс добавлен",
                    description=f"Новый кейс **{name}** (ID {cid}) создан.",
                    color=0x00FF00
                ),
                ephemeral=True
            )
        except Exception as e:
            logger.error(f"add_case: {e}")
            await inter.followup.send(
                embed=Embed(
                    title="🚫 Ошибка",
                    description="Не удалось добавить кейс в базу.",
                    color=0xFF0000
                ),
                ephemeral=True
            )


class EditCaseModal(disnake.ui.Modal):
    def __init__(self, item_id: int, cur_name: str, cur_desc: str, cur_price: int, cur_extid: str):
        self.item_id = item_id
        components = [
            disnake.ui.TextInput(
                label="Название кейса",
                custom_id="case_name",
                style=disnake.TextInputStyle.short,
                value=cur_name,
                required=True
            ),
            disnake.ui.TextInput(
                label="Описание",
                custom_id="case_desc",
                style=disnake.TextInputStyle.long,
                value=cur_desc,
                max_length=200,
                required=True
            ),
            disnake.ui.TextInput(
                label="Цена (целое)",
                custom_id="case_price",
                style=disnake.TextInputStyle.short,
                value=str(cur_price),
                required=True
            ),
            disnake.ui.TextInput(
                label="external_id",
                custom_id="case_extid",
                style=disnake.TextInputStyle.short,
                value=cur_extid,
                required=True
            )
        ]
        super().__init__(title=f"✏️ Редактировать кейс {item_id}", components=components,
                         custom_id=f"edit_case_{item_id}")

    async def callback(self, inter: disnake.ModalInteraction):
        await inter.response.defer(ephemeral=True)

        new_name = inter.text_values["case_name"].strip()
        new_desc = inter.text_values["case_desc"].strip()
        price_str = inter.text_values["case_price"].strip()
        new_extid = inter.text_values["case_extid"].strip()

        try:
            new_price = int(price_str)
            if new_price < 0:
                raise ValueError
        except:
            return await inter.followup.send(
                embed=Embed(
                    title="🚫 Ошибка",
                    description="Цена должна быть неотрицательным целым числом.",
                    color=0xFF0000
                ),
                ephemeral=True
            )

        try:
            await update_shop_item(self.item_id, "case", new_name, new_desc, new_price, new_extid)
            await inter.followup.send(
                embed=Embed(
                    title="✅ Кейс обновлён",
                    description=f"ID {self.item_id} сохранён.",
                    color=0x00FF00
                ),
                ephemeral=True
            )
        except Exception as e:
            logger.error(f"edit_case: {e}")
            await inter.followup.send(
                embed=Embed(
                    title="🚫 Ошибка",
                    description="Не удалось обновить кейс.",
                    color=0xFF0000
                ),
                ephemeral=True
            )


# ----------------------------
#  УПРАВЛЕНИЕ ДРОПАМИ
# ----------------------------
class ManageDropsView(disnake.ui.View):
    def __init__(self, bot: commands.Bot, case_item_id: int):
        super().__init__(timeout=None)
        self.bot = bot
        self.case_item_id = case_item_id

        btn_add = disnake.ui.Button(label="➕ Добавить дроп", style=disnake.ButtonStyle.green, custom_id="add_drop")
        btn_add.callback = self.on_add
        self.add_item(btn_add)

        btn_edit = disnake.ui.Button(label="✏️ Редактировать дроп", style=disnake.ButtonStyle.blurple, custom_id="edit_drop")
        btn_edit.callback = self.on_edit
        self.add_item(btn_edit)

        btn_del = disnake.ui.Button(label="🗑️ Удалить дроп", style=disnake.ButtonStyle.danger, custom_id="delete_drop")
        btn_del.callback = self.on_delete
        self.add_item(btn_del)

    async def on_add(self, inter: disnake.MessageInteraction):
        return await inter.response.send_modal(AddDropModal(self.case_item_id))

    async def on_edit(self, inter: disnake.MessageInteraction):
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT external_id FROM shop_items WHERE item_id=%s;", (self.case_item_id,))
                row = await cur.fetchone()
        if not row:
            return await inter.response.send_message(
                embed=Embed(title="🚫 Ошибка", description="Кейс не найден.", color=0xFF0000),
                ephemeral=True
            )
        ext_id = row[0]
        drops = await get_case_contents(ext_id)
        if not drops:
            return await inter.response.send_message(
                embed=Embed(title="ℹ️ Нет дропов", description="Нечего редактировать.", color=0xFFD700),
                ephemeral=True
            )

        options = []
        for row in drops:
            if len(row) != 7:
                continue
            cid, rtype, rval, chance, dur, comp, hidden = row
            options.append(
                disnake.SelectOption(
                    label=f"{cid} — {rtype}",
                    value=str(cid),
                    description=f"Шанс: {chance}%"
                )
            )

        if not options:
            return await inter.response.send_message(
                embed=Embed(title="🚫 Ошибка", description="Некорректные записи дропов.", color=0xFF0000),
                ephemeral=True
            )

        select = disnake.ui.Select(placeholder="Выберите ID дропа", options=options, custom_id="sel_edit_drop")
        view = disnake.ui.View(timeout=None)
        view.add_item(select)

        async def sel_edit(inter2: disnake.MessageInteraction):
            chosen = int(inter2.values[0])
            pool2 = await get_pool()
            async with pool2.acquire() as conn2:
                async with conn2.cursor() as cur2:
                    await cur2.execute("""
SELECT reward_type, reward_value, chance, duration_secs, comp_coins
FROM case_contents WHERE id=%s;
""", (chosen,))
                    row2 = await cur2.fetchone()
            if not row2:
                return await inter2.response.send_message(
                    embed=Embed(title="🚫 Ошибка", description="Дроп не найден.", color=0xFF0000),
                    ephemeral=True
                )
            rtype, rval, chance, dur, comp = row2
            return await inter2.response.send_modal(EditDropModal(chosen, rtype, rval, chance, dur, comp))

        select.callback = sel_edit
        await inter.response.send_message(
            embed=Embed(
                title="✏️ Редактировать дроп",
                description="Выберите дроп для редактирования.",
                color=0x2F3136
            ),
            view=view,
            ephemeral=True
        )

    async def on_delete(self, inter: disnake.MessageInteraction):
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT external_id FROM shop_items WHERE item_id=%s;", (self.case_item_id,))
                row = await cur.fetchone()
        if not row:
            return await inter.response.send_message(
                embed=Embed(title="🚫 Ошибка", description="Кейс не найден.", color=0xFF0000),
                ephemeral=True
            )
        ext_id = row[0]
        drops = await get_case_contents(ext_id)
        if not drops:
            return await inter.response.send_message(
                embed=Embed(title="ℹ️ Нет дропов", description="Нечего удалять.", color=0xFFD700),
                ephemeral=True
            )

        options = []
        for row in drops:
            if len(row) != 7:
                continue
            cid, rtype, rval, chance, dur, comp, hidden = row
            options.append(
                disnake.SelectOption(
                    label=f"{cid} — {rtype}",
                    value=str(cid),
                    description=f"Шанс: {chance}%"
                )
            )

        if not options:
            return await inter.response.send_message(
                embed=Embed(title="🚫 Ошибка", description="Некорректные записи дропов.", color=0xFF0000),
                ephemeral=True
            )

        select = disnake.ui.Select(placeholder="Выберите ID дропа", options=options, custom_id="sel_delete_drop")
        view = disnake.ui.View(timeout=None)
        view.add_item(select)

        async def sel_del(inter2: disnake.MessageInteraction):
            chosen = int(inter2.values[0])
            try:
                await delete_case_content(chosen)
                await inter2.response.send_message(
                    embed=Embed(title="✅ Дроп удалён", description=f"ID {chosen}", color=0x00FF00),
                    ephemeral=True
                )
            except Exception as e:
                logger.error(f"del_drop: {e}")
                await inter2.response.send_message(
                    embed=Embed(title="🚫 Ошибка", description="Не удалось удалить.", color=0xFF0000),
                    ephemeral=True
                )

        select.callback = sel_del
        await inter.response.send_message(
            embed=Embed(
                title="🗑️ Удалить дроп",
                description="Выберите дроп для удаления.",
                color=0x2F3136
            ),
            view=view,
            ephemeral=True
        )


class AddDropModal(disnake.ui.Modal):
    def __init__(self, case_item_id: int):
        self.case_item_id = case_item_id
        components = [
            disnake.ui.TextInput(
                label="Тип награды",        # ≤ 45 символов
                custom_id="rt",
                style=disnake.TextInputStyle.short,
                placeholder="coins_cash / coins_bank / role_perm / role_temp / item / case",
                required=True
            ),
            disnake.ui.TextInput(
                label="Значение",           # ≤ 45 символов
                custom_id="rv",
                style=disnake.TextInputStyle.short,
                placeholder="ID или число или external_id",
                required=True
            ),
            disnake.ui.TextInput(
                label="Шанс (0–100)",       # ≤ 45 символов
                custom_id="ch",
                style=disnake.TextInputStyle.short,
                placeholder="Например: 50 (означает 50%)",
                required=True
            ),
            disnake.ui.TextInput(
                label="Длительность (сек)",  # ≤ 45 символов
                custom_id="dur",
                style=disnake.TextInputStyle.short,
                placeholder="Для role_temp (сек). Иначе оставьте пустым",
                required=False
            ),
            disnake.ui.TextInput(
                label="Компенсация (монеты в банк)",  # ≤ 45 символов
                custom_id="comp",
                style=disnake.TextInputStyle.short,
                placeholder="Если у пользователя уже есть роль — сколько монет в банк",
                required=False
            )
        ]
        super().__init__(title="➕ Добавить дроп", components=components, custom_id="add_drop_modal")

    async def callback(self, inter: disnake.ModalInteraction):
        await inter.response.defer(ephemeral=True)

        rt = inter.text_values["rt"].strip()
        rv = inter.text_values["rv"].strip()
        chance_str = inter.text_values["ch"].strip()
        dur_str = inter.text_values.get("dur", "").strip()
        comp_str = inter.text_values.get("comp", "").strip()

        try:
            chance = int(chance_str)
            if chance < 0 or chance > 100:
                raise ValueError
        except:
            return await inter.followup.send(
                embed=Embed(
                    title="🚫 Ошибка",
                    description="Шанс должен быть целым числом от 0 до 100.",
                    color=0xFF0000
                ),
                ephemeral=True
            )

        duration_secs = 0
        if rt == "role_temp":
            try:
                duration_secs = int(dur_str) if dur_str else 0
                if duration_secs < 0:
                    raise ValueError
            except:
                return await inter.followup.send(
                    embed=Embed(
                        title="🚫 Ошибка",
                        description="Длительность должна быть неотрицательным целым числом.",
                        color=0xFF0000
                    ),
                    ephemeral=True
                )

        comp_coins = 0
        if comp_str:
            try:
                comp_coins = int(comp_str)
                if comp_coins < 0:
                    raise ValueError
            except:
                return await inter.followup.send(
                    embed=Embed(
                        title="🚫 Ошибка",
                        description="Компенсация должна быть неотрицательным целым числом.",
                        color=0xFF0000
                    ),
                    ephemeral=True
                )

        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT external_id FROM shop_items WHERE item_id = %s;", (self.case_item_id,))
                row = await cur.fetchone()
        if not row:
            return await inter.followup.send(
                embed=Embed(
                    title="🚫 Ошибка",
                    description="Кейс не найден в базе.",
                    color=0xFF0000
                ),
                ephemeral=True
            )
        case_ext = row[0]

        try:
            new_id = await add_case_content(
                case_external=case_ext,
                reward_type=rt,
                reward_value=rv,
                chance=chance,
                duration_secs=duration_secs,
                comp_coins=comp_coins,
                hidden_name=False
            )
            await inter.followup.send(
                embed=Embed(
                    title="✅ Дроп добавлен",
                    description=f"ID = {new_id}, шанс {chance}%",
                    color=0x00FF00
                ),
                ephemeral=True
            )
        except Exception as e:
            logger.error(f"add_drop(error): {e}")
            await inter.followup.send(
                embed=Embed(
                    title="🚫 Ошибка",
                    description="Не удалось добавить дроп в базу.",
                    color=0xFF0000
                ),
                ephemeral=True
            )


class EditDropModal(disnake.ui.Modal):
    def __init__(self, content_id: int, rtype: str, rval: str, chance: int, duration: int, comp: int):
        self.content_id = content_id
        components = [
            disnake.ui.TextInput(
                label="Тип награды",
                custom_id="rt",
                style=disnake.TextInputStyle.short,
                value=rtype,
                max_length=45,
                required=True
            ),
            disnake.ui.TextInput(
                label="Значение",
                custom_id="rv",
                style=disnake.TextInputStyle.short,
                value=rval,
                max_length=45,
                required=True
            ),
            disnake.ui.TextInput(
                label="Шанс (0–100)",
                custom_id="chance",
                style=disnake.TextInputStyle.short,
                value=str(chance),
                required=True
            ),
            disnake.ui.TextInput(
                label="Длительность (сек)",
                custom_id="dur",
                style=disnake.TextInputStyle.short,
                value=str(duration) if duration else "",
                required=False
            ),
            disnake.ui.TextInput(
                label="Компенсация (монеты в банк)",
                custom_id="comp",
                style=disnake.TextInputStyle.short,
                value=str(comp),
                required=False
            )
        ]
        super().__init__(title=f"✏️ Редактировать дроп {content_id}", components=components,
                         custom_id=f"edit_drop_modal_{content_id}")

    async def callback(self, inter: disnake.ModalInteraction):
        await inter.response.defer(ephemeral=True)

        rt = inter.text_values["rt"].strip()
        rv = inter.text_values["rv"].strip()
        chance_str = inter.text_values["chance"].strip()
        dur_str = inter.text_values.get("dur", "").strip()
        comp_str = inter.text_values.get("comp", "").strip()

        try:
            chance = int(chance_str)
            if chance < 0 or chance > 100:
                raise ValueError
        except:
            return await inter.followup.send(
                embed=Embed(
                    title="🚫 Ошибка",
                    description="Шанс должен быть целым от 0 до 100.",
                    color=0xFF0000
                ),
                ephemeral=True
            )

        duration_secs = 0
        if rt == "role_temp":
            try:
                duration_secs = int(dur_str) if dur_str else 0
                if duration_secs < 0:
                    raise ValueError
            except:
                return await inter.followup.send(
                    embed=Embed(
                        title="🚫 Ошибка",
                        description="Длительность должна быть неотрицательным целым числом.",
                        color=0xFF0000
                    ),
                    ephemeral=True
                )

        comp_coins = 0
        if comp_str:
            try:
                comp_coins = int(comp_str)
                if comp_coins < 0:
                    raise ValueError
            except:
                return await inter.followup.send(
                    embed=Embed(
                        title="🚫 Ошибка",
                        description="Компенсация должна быть неотрицательным целым числом.",
                        color=0xFF0000
                    ),
                    ephemeral=True
                )

        try:
            await update_case_content(
                content_id=self.content_id,
                reward_type=rt,
                reward_value=rv,
                chance=chance,
                duration_secs=duration_secs,
                comp_coins=comp_coins,
                hidden_name=False
            )
            await inter.followup.send(
                embed=Embed(
                    title="✅ Дроп обновлён",
                    description=f"ID = {self.content_id}, шанс {chance}%",
                    color=0x00FF00
                ),
                ephemeral=True
            )
        except Exception as e:
            logger.error(f"edit_drop: {e}")
            await inter.followup.send(
                embed=Embed(
                    title="🚫 Ошибка",
                    description="Не удалось обновить дроп.",
                    color=0xFF0000
                ),
                ephemeral=True
            )


def setup(bot):
    bot.add_cog(Cases(bot))
