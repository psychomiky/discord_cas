import aiopg
import json
import logging
import asyncio
from datetime import datetime, timezone
from config import database_url

# ------------------------
#  Настройка логирования
# ------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ------------------------
#  Параметры подключения
# ------------------------
DATABASE_DSN = database_url

# ------------------------
#  Глобальный пул соединений
# ------------------------
_pool = None

async def get_pool():
    """
    Возвращает глобальный пул соединений к PostgreSQL,
    создавая его при первом вызове.
    """
    global _pool
    if _pool is None:
        try:
            _pool = await aiopg.create_pool(DATABASE_DSN, minsize=1, maxsize=10)
            logger.info("Пул PostgreSQL создан.")
        except Exception as e:
            logger.error(f"Ошибка создания пула: {e}")
            raise
    return _pool

async def close_pool():
    """
    Закрывает пул соединений.
    """
    global _pool
    if _pool is not None:
        _pool.close()
        await _pool.wait_closed()
        _pool = None
        logger.info("Пул PostgreSQL закрыт.")

# ------------------------
#  Инициализация схемы БД
# ------------------------
async def init_db():
    """
    Создаёт все таблицы, если их ещё нет.
    Каждый DDL-оператор выполняется отдельно.
    """
    pool = await get_pool()

    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                # 1) Таблица users
                await cur.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id        BIGINT       NOT NULL,
    guild_id       BIGINT       NOT NULL,
    cash           BIGINT       DEFAULT 0,
    bank           BIGINT       DEFAULT 0,
    work_cooldown  TIMESTAMPTZ,
    PRIMARY KEY(user_id, guild_id)
);
""")

                # 2) Таблица cooldowns
                await cur.execute("""
CREATE TABLE IF NOT EXISTS cooldowns (
    user_id       BIGINT       NOT NULL,
    guild_id      BIGINT       NOT NULL,
    command_name  VARCHAR(255) NOT NULL,
    last_used     BIGINT,
    PRIMARY KEY(user_id, guild_id, command_name)
);
""")

                # 3) Таблица active_roulettes
                await cur.execute("""
CREATE TABLE IF NOT EXISTS active_roulettes (
    id         SERIAL PRIMARY KEY,
    channel_id BIGINT NOT NULL,
    guild_id   BIGINT NOT NULL,
    end_time   BIGINT NOT NULL,
    result     VARCHAR(255)
);
""")

                # 4) Таблица roulette_bets
                await cur.execute("""
CREATE TABLE IF NOT EXISTS roulette_bets (
    id          SERIAL       PRIMARY KEY,
    roulette_id INTEGER      NOT NULL REFERENCES active_roulettes(id) ON DELETE CASCADE,
    user_id     BIGINT       NOT NULL,
    amount      BIGINT       NOT NULL,
    space       VARCHAR(255) NOT NULL,
    space_type  VARCHAR(255) NOT NULL
);
""")

                # 5) Таблица roulette_history
                await cur.execute("""
CREATE TABLE IF NOT EXISTS roulette_history (
    id          SERIAL       PRIMARY KEY,
    roulette_id INTEGER      NOT NULL,
    result      VARCHAR(255) NOT NULL,
    timestamp   BIGINT       NOT NULL,
    user_id     BIGINT       NOT NULL,
    amount      BIGINT       NOT NULL,
    space       VARCHAR(255) NOT NULL,
    space_type  VARCHAR(255) NOT NULL,
    winnings    BIGINT       NOT NULL
);
""")

                # 6) Таблица active_games
                await cur.execute("""
CREATE TABLE IF NOT EXISTS active_games (
    game_id     SERIAL       PRIMARY KEY,
    user_id     BIGINT       NOT NULL,
    guild_id    BIGINT       NOT NULL,
    channel_id  BIGINT       NOT NULL,
    message_id  BIGINT       NOT NULL,
    player_hand JSONB        NOT NULL,
    dealer_hand JSONB        NOT NULL,
    bet         BIGINT       NOT NULL,
    start_time  TIMESTAMPTZ  NOT NULL,
    deck        JSONB        NOT NULL
);
""")

                # 7) Таблица game_history
                await cur.execute("""
CREATE TABLE IF NOT EXISTS game_history (
    game_id      INTEGER       NOT NULL,
    user_id      BIGINT        NOT NULL,
    guild_id     BIGINT        NOT NULL,
    bet          BIGINT        NOT NULL,
    result       VARCHAR(50)   NOT NULL,
    player_hand  JSONB         NOT NULL,
    player_score INTEGER       NOT NULL,
    dealer_hand  JSONB         NOT NULL,
    dealer_score INTEGER       NOT NULL,
    timestamp    TIMESTAMPTZ   NOT NULL,
    PRIMARY KEY(game_id)
);
""")

                # 8) Таблица transactions (лог переводов)
                await cur.execute("""
CREATE TABLE IF NOT EXISTS transactions (
    id               BIGSERIAL     PRIMARY KEY,
    user_id          BIGINT        NOT NULL,
    datetime         TIMESTAMPTZ   NOT NULL,
    amount           BIGINT        NOT NULL,
    reason           VARCHAR(255)  NOT NULL,
    transaction_type VARCHAR(50)   NOT NULL,
    guild_id         BIGINT        NOT NULL
);
""")

                # 9) Таблица shop_items
                await cur.execute("""
CREATE TABLE IF NOT EXISTS shop_items (
    item_id     SERIAL       PRIMARY KEY,
    type        VARCHAR(20)  NOT NULL,
    name        VARCHAR(100) NOT NULL,
    description VARCHAR(500) NOT NULL,
    price       BIGINT       NOT NULL,
    external_id VARCHAR(50),
    active      BOOLEAN      DEFAULT TRUE
);
""")
                await cur.execute("CREATE INDEX IF NOT EXISTS idx_shop_items_active ON shop_items(active);")
                await cur.execute("CREATE INDEX IF NOT EXISTS idx_shop_items_type   ON shop_items(type);")

                # 10) Таблица user_inventory
                await cur.execute("""
CREATE TABLE IF NOT EXISTS user_inventory (
    user_id   BIGINT NOT NULL,
    item_id   INTEGER NOT NULL REFERENCES shop_items(item_id) ON DELETE CASCADE,
    quantity  INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY(user_id, item_id)
);
""")
                await cur.execute("CREATE INDEX IF NOT EXISTS idx_user_inv_user ON user_inventory(user_id);")
                await cur.execute("CREATE INDEX IF NOT EXISTS idx_user_inv_item ON user_inventory(item_id);")

                # 11) Таблица cock_fight_chance
                await cur.execute("""
CREATE TABLE IF NOT EXISTS cock_fight_chance (
    user_id  BIGINT NOT NULL,
    guild_id BIGINT NOT NULL,
    chance   INTEGER DEFAULT 50,
    PRIMARY KEY(user_id, guild_id)
);
""")

                # 12) Таблица case_contents (для кейсов) с полем chance (INTEGER)
                await cur.execute("""
CREATE TABLE IF NOT EXISTS case_contents (
    id             SERIAL       PRIMARY KEY,
    case_external  VARCHAR(50)  NOT NULL,
    reward_type    VARCHAR(20)  NOT NULL,      -- 'role_perm', 'role_temp', 'coins_cash', 'coins_bank', 'item', 'case'
    reward_value   VARCHAR(100) NOT NULL,      -- для ролей: role_id, для монет: число, для item/case: external_id
    chance         INTEGER      NOT NULL,      -- шанс (целое число 0–100)
    duration_secs  INTEGER,                    -- только для role_temp (время в секундах)
    comp_coins     INTEGER      DEFAULT 0,     -- компенсация в монетах, если у юзера уже есть та же перм-роль
    hidden_name    BOOLEAN      DEFAULT FALSE  -- если TRUE: в списке дропа вместо названия показываем '???'
);
""")
                await cur.execute("CREATE INDEX IF NOT EXISTS idx_case_contents_on_case ON case_contents(case_external);")

                # 13) Таблица user_temp_roles (для хранения активных временных ролей)
                await cur.execute("""
CREATE TABLE IF NOT EXISTS user_temp_roles (
    user_id      BIGINT NOT NULL,
    guild_id     BIGINT NOT NULL,
    role_id      BIGINT NOT NULL,
    expires_at   TIMESTAMPTZ NOT NULL,
    PRIMARY KEY(user_id, guild_id, role_id)
);
""")

                # Если таблица shop_items пуста, добавляем тестовый товар
                await cur.execute("SELECT COUNT(*) FROM shop_items;")
                count_row = await cur.fetchone()
                if count_row and count_row[0] == 0:
                    await cur.execute("""
INSERT INTO shop_items (type, name, description, price, external_id, active)
VALUES (%s, %s, %s, %s, %s, TRUE);
""", ("item", "Chicken", "Боевая курица", 10, "Chickens"))

        logger.info("Схема базы данных успешно инициализирована.")
    except Exception as e:
        logger.error(f"Ошибка при init_db(): {e}")
        raise

# ------------------------
#  Пользователи и баланс
# ------------------------
async def ensure_user_exists(user_id: int, guild_id: int):
    """
    Если записи (user_id, guild_id) нет в таблице users,
    создаёт её с cash=0, bank=0.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT 1 FROM users WHERE user_id=%s AND guild_id=%s;", (user_id, guild_id))
            if not await cur.fetchone():
                await cur.execute(
                    "INSERT INTO users (user_id, guild_id, cash, bank) VALUES (%s, %s, 0, 0);",
                    (user_id, guild_id)
                )

async def get_user_balance(user_id: int, guild_id: int) -> tuple:
    """
    Возвращает (cash, bank) для user_id в guild_id.
    Сначала вызывает ensure_user_exists.
    """
    await ensure_user_exists(user_id, guild_id)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT cash, bank FROM users WHERE user_id=%s AND guild_id=%s;", (user_id, guild_id))
            row = await cur.fetchone()
            return (row[0], row[1]) if row else (0, 0)

async def update_cash(user_id: int, guild_id: int, amount: int) -> int:
    """
    Обновляет cash = cash + amount (может быть отрицательным).
    Проверяет, что cash + bank >= 0.
    Возвращает новый cash.
    """
    await ensure_user_exists(user_id, guild_id)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT cash, bank FROM users WHERE user_id=%s AND guild_id=%s FOR UPDATE;", (user_id, guild_id))
            cash, bank = await cur.fetchone()
            new_cash = cash + amount
            if new_cash < -bank:
                raise ValueError("Недостаточно средств (cash+bank не может быть отрицательным).")
            await cur.execute("UPDATE users SET cash=%s WHERE user_id=%s AND guild_id=%s;", (new_cash, user_id, guild_id))
            return new_cash

async def update_bank(user_id: int, guild_id: int, amount: int) -> int:
    """
    Обновляет bank = bank + amount (может быть отрицательным).
    Проверяет bank >= 0 и cash + bank >= 0.
    Возвращает новый bank.
    """
    await ensure_user_exists(user_id, guild_id)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT cash, bank FROM users WHERE user_id=%s AND guild_id=%s FOR UPDATE;", (user_id, guild_id))
            cash, bank = await cur.fetchone()
            new_bank = bank + amount
            if new_bank < 0 or cash < -new_bank:
                raise ValueError("Недостаточно средств или общая сумма < 0.")
            await cur.execute("UPDATE users SET bank=%s WHERE user_id=%s AND guild_id=%s;", (new_bank, user_id, guild_id))
            return new_bank

async def transfer_to_bank(user_id: int, guild_id: int, amount: int) -> tuple:
    """
    Переводит amount из cash в bank.
    Проверяет cash >= amount.
    Возвращает (новый cash, новый bank).
    """
    await ensure_user_exists(user_id, guild_id)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT cash, bank FROM users WHERE user_id=%s AND guild_id=%s FOR UPDATE;", (user_id, guild_id))
            cash, bank = await cur.fetchone()
            if cash < amount:
                raise ValueError("Недостаточно cash для перевода.")
            await cur.execute("UPDATE users SET cash=cash-%s, bank=bank+%s WHERE user_id=%s AND guild_id=%s;", (amount, amount, user_id, guild_id))
            return (cash - amount, bank + amount)

async def transfer_from_bank(user_id: int, guild_id: int, amount: int) -> tuple:
    """
    Переводит amount из bank в cash.
    Проверяет bank >= amount и cash + bank >= 0.
    Возвращает (новый cash, новый bank).
    """
    await ensure_user_exists(user_id, guild_id)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT cash, bank FROM users WHERE user_id=%s AND guild_id=%s FOR UPDATE;", (user_id, guild_id))
            cash, bank = await cur.fetchone()
            if bank < amount:
                raise ValueError("Недостаточно bank для перевода.")
            new_cash = cash + amount
            new_bank = bank - amount
            if new_cash < -new_bank:
                raise ValueError("Общая сумма cash+bank не может быть отрицательной.")
            await cur.execute("UPDATE users SET cash=%s, bank=%s WHERE user_id=%s AND guild_id=%s;", (new_cash, new_bank, user_id, guild_id))
            return (new_cash, new_bank)

async def apply_fine(user_id: int, guild_id: int, fine: int) -> tuple:
    """
    Списывает fine с cash, ограничивая cash+bank >= 0.
    Если fine > cash+bank, списывает всю сумму.
    Возвращает (новый cash, банк).
    """
    await ensure_user_exists(user_id, guild_id)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT cash, bank FROM users WHERE user_id=%s AND guild_id=%s FOR UPDATE;", (user_id, guild_id))
            cash, bank = await cur.fetchone()
            total = cash + bank
            if fine > total:
                fine = total
            new_cash = cash - fine
            if new_cash < -bank:
                raise ValueError("Cash не может стать меньше -bank.")
            await cur.execute("UPDATE users SET cash=%s WHERE user_id=%s AND guild_id=%s;", (new_cash, user_id, guild_id))
            return (new_cash, bank)

async def get_user_position(user_id: int, guild_id: int) -> int:
    """
    Возвращает позицию пользователя в топе (по сумме cash+bank) в guild_id.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT user_id FROM users WHERE guild_id=%s ORDER BY (cash + bank) DESC;", (guild_id,))
            rows = await cur.fetchall()
            for idx, (uid,) in enumerate(rows, start=1):
                if uid == user_id:
                    return idx
            return len(rows) + 1

async def get_top_users(guild_id: int, sort_field: str) -> list:
    """
    Возвращает [(user_id, cash, bank), …], отсортированный по sort_field:
    "cash", "bank" или "total" (cash+bank).
    """
    order_by = "cash" if sort_field == "cash" else ("bank" if sort_field == "bank" else "(cash + bank)")
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(f"SELECT user_id, cash, bank FROM users WHERE guild_id=%s ORDER BY {order_by} DESC;", (guild_id,))
            return await cur.fetchall()

async def get_total_balance(guild_id: int) -> int:
    """
    Возвращает сумму cash+bank для всех пользователей guild_id.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT COALESCE(SUM(cash + bank), 0) FROM users WHERE guild_id=%s;", (guild_id,))
            row = await cur.fetchone()
            return row[0]

# ------------------------
#  Рулетка
# ------------------------
async def create_roulette(channel_id: int, guild_id: int, end_time: int) -> int:
    """
    Создаёт новую рулетку. Возвращает id.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO active_roulettes (channel_id, guild_id, end_time, result) VALUES (%s, %s, %s, NULL) RETURNING id;",
                (channel_id, guild_id, end_time)
            )
            row = await cur.fetchone()
            return row[0]

async def add_roulette_bet(roulette_id: int, user_id: int, amount: int, space: str, space_type: str):
    """
    Добавляет запись о ставке для рулетки.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO roulette_bets (roulette_id, user_id, amount, space, space_type) VALUES (%s, %s, %s, %s, %s);",
                (roulette_id, user_id, amount, space, space_type)
            )

async def get_active_roulette(channel_id: int) -> dict:
    """
    Возвращает данные по активной рулетке (или None).
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT id, channel_id, guild_id, end_time, result FROM active_roulettes WHERE channel_id=%s;", (channel_id,))
            row = await cur.fetchone()
            if not row:
                return None

            rid, ch, gid, et, res = row
            await cur.execute("SELECT user_id, amount, space, space_type FROM roulette_bets WHERE roulette_id=%s;", (rid,))
            bets = {}
            for usr, amt, sp, st in await cur.fetchall():
                bets.setdefault(usr, []).append((amt, sp, st))

            return {
                "id":         rid,
                "channel_id": ch,
                "guild_id":   gid,
                "end_time":   et,
                "result":     res,
                "bets":       bets
            }

async def set_roulette_result(roulette_id: int, result: str):
    """
    Устанавливает поле result для рулетки.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("UPDATE active_roulettes SET result=%s WHERE id=%s;", (result, roulette_id))

async def save_roulette_history(
    roulette_id: int,
    result: str,
    timestamp: int,
    bets: dict,
    results: dict
):
    """
    Записывает историю рулетки.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            for usr, bet_list in bets.items():
                for amount, space, space_type in bet_list:
                    win = results.get(usr, {}).get(space, 0)
                    await cur.execute("""
INSERT INTO roulette_history
  (roulette_id, result, timestamp, user_id, amount, space, space_type, winnings)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
""", (roulette_id, result, timestamp, usr, amount, space, space_type, win))

async def delete_roulette(roulette_id: int):
    """
    Удаляет рулетку и связанные ставки.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM roulette_bets WHERE roulette_id=%s;", (roulette_id,))
            await cur.execute("DELETE FROM active_roulettes WHERE id=%s;", (roulette_id,))

# ------------------------
#  Игры (Blackjack и др.)
# ------------------------
async def save_active_game(
    game_id: int,
    user_id: int,
    guild_id: int,
    channel_id: int,
    message_id: int,
    player_hand: list,
    dealer_hand: list,
    bet: int,
    deck: list
) -> int:
    """
    Сохраняет или обновляет запись в active_games.
    Если game_id=0, создаёт новую и возвращает её id.
    """
    now = datetime.now(timezone.utc)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            if game_id == 0:
                await cur.execute(
                    "INSERT INTO active_games "
                    "(user_id, guild_id, channel_id, message_id, player_hand, dealer_hand, bet, start_time, deck) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING game_id;",
                    (
                        user_id, guild_id, channel_id, message_id,
                        json.dumps(player_hand), json.dumps(dealer_hand),
                        bet, now, json.dumps(deck)
                    )
                )
                row = await cur.fetchone()
                return row[0]
            else:
                await cur.execute(
                    "UPDATE active_games SET "
                    "user_id=%s, guild_id=%s, channel_id=%s, message_id=%s, "
                    "player_hand=%s, dealer_hand=%s, bet=%s, start_time=%s, deck=%s "
                    "WHERE game_id=%s;",
                    (
                        user_id, guild_id, channel_id, message_id,
                        json.dumps(player_hand), json.dumps(dealer_hand),
                        bet, now, json.dumps(deck), game_id
                    )
                )
                return game_id

async def get_active_game(user_id: int) -> dict:
    """
    Возвращает активную игру (словарь) по user_id или пустой dict.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
SELECT game_id, user_id, guild_id, channel_id, message_id, player_hand, dealer_hand, bet, deck
FROM active_games WHERE user_id=%s;
""", (user_id,))
            row = await cur.fetchone()
            if not row:
                return {}
            return {
                "game_id":     row[0],
                "user_id":     row[1],
                "guild_id":    row[2],
                "channel_id":  row[3],
                "message_id":  row[4],
                "player_hand": row[5],
                "dealer_hand": row[6],
                "bet":         row[7],
                "deck":        row[8]
            }

async def delete_active_game(game_id: int):
    """
    Удаляет запись из active_games.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM active_games WHERE game_id=%s;", (game_id,))

async def log_game_history(
    game_id: int,
    user_id: int,
    guild_id: int,
    bet: int,
    result: str,
    player_hand: list,
    player_score: int,
    dealer_hand: list,
    dealer_score: int
):
    """
    Вставляет завершённую игру в game_history.
    """
    now = datetime.now(timezone.utc)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO game_history "
                "(game_id, user_id, guild_id, bet, result, player_hand, player_score, dealer_hand, dealer_score, timestamp) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s);",
                (
                    game_id, user_id, guild_id, bet, result,
                    json.dumps(player_hand), player_score,
                    json.dumps(dealer_hand), dealer_score, now
                )
            )

# ------------------------
#  Cooldowns (для команд)
# ------------------------
async def get_cooldown(user_id: int, guild_id: int, command_name: str) -> int:
    """
    Возвращает last_used или None, если записи нет.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT last_used FROM cooldowns WHERE user_id=%s AND guild_id=%s AND command_name=%s;", (user_id, guild_id, command_name))
            row = await cur.fetchone()
            return row[0] if row else None

async def update_cooldown(user_id: int, guild_id: int, command_name: str, timestamp: int):
    """
    Вставляет или обновляет last_used для (user_id, guild_id, command_name).
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO cooldowns (user_id, guild_id, command_name, last_used) "
                "VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (user_id, guild_id, command_name) DO UPDATE SET last_used=EXCLUDED.last_used;",
                (user_id, guild_id, command_name, timestamp)
            )

# ------------------------
#  Лог переводов (transactions)
# ------------------------
async def log_transfer(
    guild_id: int,
    sender_id: int,
    receiver_id: int,
    amount: int,
    fee: int
):
    """
    Делает две записи в transactions:
    1) списание у sender_id
    2) зачисление receiver_id (amount - fee)
    """
    now = datetime.now(timezone.utc)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO transactions "
                "(user_id, datetime, amount, reason, transaction_type, guild_id) "
                "VALUES (%s, %s, %s, %s, %s, %s);",
                (sender_id, now, -amount, f"Платёж пользователю {receiver_id}", "write-off", guild_id)
            )
            await cur.execute(
                "INSERT INTO transactions "
                "(user_id, datetime, amount, reason, transaction_type, guild_id) "
                "VALUES (%s, %s, %s, %s, %s, %s);",
                (receiver_id, now, amount - fee, f"Платёж от {sender_id}", "receipt", guild_id)
            )

async def transfer_cash(
    sender_id: int,
    receiver_id: int,
    guild_id: int,
    amount: int,
    fee: int,
    retries: int = 3,
    delay: float = 1.0
) -> tuple:
    """
    Переводит из cash у sender_id → cash у receiver_id, удерживая fee.
    При дедлоке повторяет до retries раз.
    Возвращает (новый_cash_sender, новый_cash_receiver).
    """
    await ensure_user_exists(sender_id, guild_id)
    await ensure_user_exists(receiver_id, guild_id)
    pool = await get_pool()

    for attempt in range(retries):
        try:
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("SELECT cash FROM users WHERE user_id=%s AND guild_id=%s FOR UPDATE;", (sender_id, guild_id))
                    sender_cash = (await cur.fetchone())[0]
                    if sender_cash < amount:
                        raise ValueError("Недостаточно средств для перевода.")

                    await cur.execute("UPDATE users SET cash=cash-%s WHERE user_id=%s AND guild_id=%s;", (amount, sender_id, guild_id))
                    recv_amount = amount - fee
                    await cur.execute("UPDATE users SET cash=cash+%s WHERE user_id=%s AND guild_id=%s;", (recv_amount, receiver_id, guild_id))

                    # Логируем обе операции
                    await log_transfer(guild_id, sender_id, receiver_id, amount, fee)

                    # Читаем новые балансы
                    await cur.execute("SELECT cash FROM users WHERE user_id=%s AND guild_id=%s;", (sender_id, guild_id))
                    new_sender_cash = (await cur.fetchone())[0]
                    await cur.execute("SELECT cash FROM users WHERE user_id=%s AND guild_id=%s;", (receiver_id, guild_id))
                    new_receiver_cash = (await cur.fetchone())[0]

                    return (new_sender_cash, new_receiver_cash)

        except Exception as e:
            if "deadlock" in str(e).lower() and attempt < retries - 1:
                await asyncio.sleep(delay)
                continue
            raise

async def rob_user(
    robber_id: int,
    target_id: int,
    guild_id: int,
    stolen_amount: int,
    retries: int = 3,
    delay: float = 1.0
) -> tuple:
    """
    Операция ограбления: списывает до stolen_amount у target_id,
    зачисляет robber_id. Логирует две транзакции.
    Возвращает (новый_cash_robber, bank_robber, новый_cash_target, bank_target).
    """
    await ensure_user_exists(robber_id, guild_id)
    await ensure_user_exists(target_id, guild_id)
    pool = await get_pool()

    for attempt in range(retries):
        try:
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    # Блокируем цель
                    await cur.execute("SELECT cash, bank FROM users WHERE user_id=%s AND guild_id=%s FOR UPDATE;", (target_id, guild_id))
                    tgt_row = await cur.fetchone()
                    if not tgt_row:
                        raise ValueError("Цель не найдена.")
                    target_cash, target_bank = tgt_row

                    steal = min(target_cash, stolen_amount)
                    await cur.execute("UPDATE users SET cash=%s WHERE user_id=%s AND guild_id=%s;", (target_cash - steal, target_id, guild_id))

                    # Блокируем грабителя
                    await cur.execute("SELECT cash, bank FROM users WHERE user_id=%s AND guild_id=%s FOR UPDATE;", (robber_id, guild_id))
                    rob_row = await cur.fetchone()
                    if not rob_row:
                        raise ValueError("Грабитель не найден.")
                    robber_cash, robber_bank = rob_row

                    await cur.execute("UPDATE users SET cash=%s WHERE user_id=%s AND guild_id=%s;", (robber_cash + steal, robber_id, guild_id))

                    now = datetime.now(timezone.utc)
                    await cur.execute(
                        "INSERT INTO transactions (user_id, datetime, amount, reason, transaction_type, guild_id) "
                        "VALUES (%s, %s, %s, %s, %s, %s);",
                        (target_id, now, -steal, f"Ограбление пользователем {robber_id}", "write-off", guild_id)
                    )
                    await cur.execute(
                        "INSERT INTO transactions (user_id, datetime, amount, reason, transaction_type, guild_id) "
                        "VALUES (%s, %s, %s, %s, %s, %s);",
                        (robber_id, now, steal, f"Ограбление у {target_id}", "receipt", guild_id)
                    )

                    return (robber_cash + steal, robber_bank, target_cash - steal, target_bank)

        except Exception as e:
            if "deadlock" in str(e).lower() and attempt < retries - 1:
                await asyncio.sleep(delay)
                continue
            raise

# ------------------------
#  Магазин и инвентарь
# ------------------------
async def add_shop_item(item_type: str, name: str, description: str, price: int, external_id: str = None) -> int:
    """
    Добавляет новый товар и возвращает его item_id.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO shop_items (type, name, description, price, external_id, active) "
                "VALUES (%s, %s, %s, %s, %s, TRUE) RETURNING item_id;",
                (item_type, name, description, price, external_id)
            )
            row = await cur.fetchone()
            return row[0]

async def update_shop_item(item_id: int, item_type: str, name: str, description: str, price: int, external_id: str = None):
    """
    Обновляет поля существующего товара по item_id.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "UPDATE shop_items SET type=%s, name=%s, description=%s, price=%s, external_id=%s "
                "WHERE item_id=%s;",
                (item_type, name, description, price, external_id, item_id)
            )

async def deactivate_shop_item(item_id: int):
    """
    Деактивирует товар (active=FALSE) и удаляет его из всех инвентарей.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("UPDATE shop_items SET active=FALSE WHERE item_id=%s;", (item_id,))
            await cur.execute("DELETE FROM user_inventory WHERE item_id=%s;", (item_id,))

async def get_shop_items(category: str = None) -> list:
    """
    Если category="all", возвращает все активные товары.
    Иначе только type=category.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            if category == "all":
                await cur.execute("SELECT item_id, type, name, description, price, external_id FROM shop_items WHERE active=TRUE ORDER BY price ASC, item_id ASC;")
            else:
                await cur.execute("SELECT item_id, type, name, description, price, external_id FROM shop_items WHERE type=%s AND active=TRUE ORDER BY price ASC, item_id ASC;", (category,))
            return await cur.fetchall()

async def get_shop_item_by_id(item_id: int) -> tuple:
    """
    Возвращает (item_id, type, name, description, price, external_id) или None.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT item_id, type, name, description, price, external_id FROM shop_items WHERE item_id=%s AND active=TRUE;", (item_id,))
            return await cur.fetchone()

async def get_shop_item_by_external(external_id: str) -> tuple:
    """
    Возвращает (item_id, type, name, description, price, external_id) или None.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT item_id, type, name, description, price, external_id FROM shop_items WHERE external_id=%s AND active=TRUE;", (external_id,))
            return await cur.fetchone()

async def get_shop_item_by_name(name: str) -> tuple:
    """
    Возвращает (item_id, type, name, description, price, external_id) или None
    для товара с данным name (нечувствительно к регистру).
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
SELECT item_id, type, name, description, price, external_id
FROM shop_items
WHERE LOWER(name) = LOWER(%s) AND active = TRUE;
""", (name,))
            return await cur.fetchone()

async def get_all_shop_items() -> list:
    """
    Возвращает все товары (включая неактивные) для админки.
    Формат: [(item_id, type, name, description, price, external_id, active), …]
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
SELECT item_id, type, name, description, price, external_id, active
FROM shop_items;
""")
            return await cur.fetchall()

# ------------------------
#  Инвентарь пользователя
# ------------------------
async def add_to_inventory(user_id: int, item_id: int, count: int = 1) -> None:
    """
    Добавляет count штук item_id в инвентарь пользователя.
    Если уже есть, увеличивает quantity.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
INSERT INTO user_inventory (user_id, item_id, quantity)
VALUES (%s, %s, %s)
ON CONFLICT (user_id, item_id) DO UPDATE
  SET quantity = user_inventory.quantity + EXCLUDED.quantity;
""", (user_id, item_id, count))

async def get_user_inventory(user_id: int) -> list:
    """
    Возвращает [(item_id, quantity, name, description), …] активных предметов.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
SELECT ui.item_id, ui.quantity, si.name, si.description
FROM user_inventory ui
JOIN shop_items si ON ui.item_id = si.item_id
WHERE ui.user_id=%s AND si.active=TRUE
ORDER BY si.name;
""", (user_id,))
            return await cur.fetchall()

async def remove_from_inventory(user_id: int, item_id: int, count: int = 1) -> int:
    """
    Уменьшает quantity на count штук для user_id/item_id.
    Если quantity <= count, удаляет запись.
    Возвращает реально удалённое количество.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT quantity FROM user_inventory WHERE user_id=%s AND item_id=%s FOR UPDATE;", (user_id, item_id))
            row = await cur.fetchone()
            if not row:
                return 0
            current_qty = row[0]
            to_remove = min(current_qty, count)
            new_qty = current_qty - to_remove
            if new_qty > 0:
                await cur.execute("UPDATE user_inventory SET quantity=%s WHERE user_id=%s AND item_id=%s;", (new_qty, user_id, item_id))
            else:
                await cur.execute("DELETE FROM user_inventory WHERE user_id=%s AND item_id=%s;", (user_id, item_id))
            return to_remove

# ------------------------
#  CockFight (шанс)
# ------------------------
async def get_cock_fight_chance(user_id: int, guild_id: int) -> int:
    """
    Получение текущего шанса победы в CockFight (0–100).
    Если записи нет — возвращает None.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT chance FROM cock_fight_chance WHERE user_id=%s AND guild_id=%s;", (user_id, guild_id))
            row = await cur.fetchone()
            return row[0] if row else None

async def update_cock_fight_chance(user_id: int, guild_id: int, chance: int):
    """
    Вставляет или обновляет шанс (0–100) для CockFight.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO cock_fight_chance (user_id, guild_id, chance) "
                "VALUES (%s, %s, %s) "
                "ON CONFLICT (user_id, guild_id) DO UPDATE SET chance=EXCLUDED.chance;",
                (user_id, guild_id, chance)
            )

# ------------------------
#  Case‐логика
# ------------------------
async def get_all_cases() -> list:
    """
    Возвращает список всех активных кейсов:
    [(item_id, name, description, price, external_id), …]
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
SELECT item_id, name, description, price, external_id
FROM shop_items
WHERE type='case' AND active=TRUE
ORDER BY price ASC, item_id ASC;
""")
            return await cur.fetchall()

async def get_case_contents(case_external: str) -> list:
    """
    Возвращает список дропов для кейса case_external:
    [(id, reward_type, reward_value, chance, duration_secs, comp_coins, hidden_name), …]
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
SELECT id, reward_type, reward_value, chance, duration_secs, comp_coins, hidden_name
FROM case_contents
WHERE case_external=%s
ORDER BY id ASC;
""", (case_external,))
            return await cur.fetchall()

async def add_case_content(
    case_external: str,
    reward_type: str,
    reward_value: str,
    chance: int,
    duration_secs: int = None,
    comp_coins: int = 0,
    hidden_name: bool = False
) -> int:
    """
    Добавляет новую запись дропа для кейса. Возвращает id вставленной записи.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
INSERT INTO case_contents
  (case_external, reward_type, reward_value, chance, duration_secs, comp_coins, hidden_name)
VALUES (%s, %s, %s, %s, %s, %s, %s)
RETURNING id;
""", (case_external, reward_type, reward_value, chance, duration_secs, comp_coins, hidden_name))
            row = await cur.fetchone()
            return row[0] if row else None

async def update_case_content(
    content_id: int,
    reward_type: str,
    reward_value: str,
    chance: int,
    duration_secs: int = None,
    comp_coins: int = 0,
    hidden_name: bool = False
):
    """
    Обновляет существующую запись дропа по content_id.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
UPDATE case_contents
SET reward_type=%s,
    reward_value=%s,
    chance=%s,
    duration_secs=%s,
    comp_coins=%s,
    hidden_name=%s
WHERE id=%s;
""", (reward_type, reward_value, chance, duration_secs, comp_coins, hidden_name, content_id))

async def delete_case_content(content_id: int):
    """
    Удаляет запись дропа по content_id.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM case_contents WHERE id=%s;", (content_id,))

async def get_item_id_by_external(external_id: str) -> int:
    """
    Возвращает item_id (int) из shop_items по external_id.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT item_id FROM shop_items WHERE external_id=%s AND active=TRUE;", (external_id,))
            row = await cur.fetchone()
            return row[0] if row else None

async def decrement_inventory(user_id: int, item_id: int, count: int = 1):
    """
    Уменьшает количество товара item_id в инвентаре пользователя на count.
    Если quantity <= count, удаляет запись.
    Возвращает число реально удалённых штук.
    """
    return await remove_from_inventory(user_id, item_id, count)

# ------------------------
#  Функции для временных ролей
# ------------------------
async def add_or_update_temp_role(user_id: int, guild_id: int, role_id: int, expires_at: datetime):
    """
    Вставляет новую запись в user_temp_roles или обновляет существующую:
    ON CONFLICT (user_id, guild_id, role_id) DO UPDATE SET expires_at = EXCLUDED.expires_at.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
INSERT INTO user_temp_roles (user_id, guild_id, role_id, expires_at)
VALUES (%s, %s, %s, %s)
ON CONFLICT (user_id, guild_id, role_id) DO UPDATE
  SET expires_at = EXCLUDED.expires_at;
""", (user_id, guild_id, role_id, expires_at))

async def remove_temp_role_record(user_id: int, guild_id: int, role_id: int):
    """
    Удаляет запись о временной роли из user_temp_roles.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
DELETE FROM user_temp_roles
WHERE user_id = %s AND guild_id = %s AND role_id = %s;
""", (user_id, guild_id, role_id))

async def get_all_active_temp_roles() -> list:
    """
    Возвращает список всех активных временных ролей (expires_at > NOW()):
    [(user_id, guild_id, role_id, expires_at), …]
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
SELECT user_id, guild_id, role_id, expires_at
FROM user_temp_roles
WHERE expires_at > NOW();
""")
            return await cur.fetchall()
