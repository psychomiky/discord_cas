import disnake
from disnake.ext import commands
import random
import logging
import configparser
import os
from utils.database import get_user_balance, update_cash, save_active_game, get_active_game, delete_active_game, log_game_history
from config import currency, CARD_EMOJIS, BLACKJACK_SUCCESS_MESSAGES, BLACKJACK_FAIL_MESSAGES, BLACKJACK_PUSH_MESSAGES, BLACKJACK_ERROR_MESSAGES

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Чтение конфигурации из games.ini
config = configparser.ConfigParser()
config_file = "games.ini"

if not os.path.exists(config_file):
    logger.error(f"Файл конфигурации {config_file} не найден.")
    raise FileNotFoundError(f"Файл конфигурации {config_file} не найден.")

try:
    config.read(config_file, encoding='utf-8')
    logger.info(f"Файл конфигурации {config_file} успешно прочитан")
except Exception as e:
    logger.error(f"Ошибка чтения games.ini: {e}")
    raise

def get_blackjack_config():
    """Получение настроек блэкджека из games.ini."""
    logger.info("Загрузка конфигурации блэкджека")
    try:
        section = config["Blackjack"]
        min_bet = int(section.get("min_bet", 10))
        decks = int(section.get("decks", 1))
        if min_bet < 1:
            raise ValueError("min_bet должен быть >= 1")
        if decks < 1:
            raise ValueError("decks должен быть >= 1")
        logger.info(f"Конфигурация блэкджека загружена: min_bet={min_bet}, decks={decks}")
        return {
            "min_bet": min_bet,
            "decks": decks,
            "success_messages": BLACKJACK_SUCCESS_MESSAGES,
            "fail_messages": BLACKJACK_FAIL_MESSAGES,
            "push_messages": BLACKJACK_PUSH_MESSAGES,
            "error_messages": BLACKJACK_ERROR_MESSAGES
        }
    except KeyError as e:
        logger.error(f"Неверная секция конфигурации для блэкджека: {e}")
        raise ValueError(f"Неверная секция конфигурации для блэкджека")
    except Exception as e:
        logger.error(f"Ошибка разбора конфигурации блэкджека: {e}")
        raise ValueError(f"Ошибка разбора конфигурации блэкджека")

def create_game_embed(user, player_hand, player_score, dealer_hand, dealer_score, deck_count, decks, is_soft=False):
    """Создание эмбеда для текущего состояния игры."""
    total_cards = decks * 52
    embed = disnake.Embed(
        description="Используйте кнопки ниже или команды:\n`hit` - взять карту\n`stand` - завершить ход\n`double down` - удвоить ставку и взять одну карту",
        color=0x2F3136
    )
    embed.set_author(name=user.display_name, icon_url=user.avatar.url if user.avatar else user.default_avatar.url)
    embed.add_field(
        name="Ваша рука",
        value=f"{player_hand}\n**{f'soft {player_score}' if is_soft else player_score}**",
        inline=True
    )
    embed.add_field(
        name="Рука дилера",
        value=f"{dealer_hand}\n**{dealer_score}**",
        inline=True
    )
    embed.set_footer(text=f"Карт в колоде осталось: {deck_count} (из {total_cards})")
    return embed

def create_win_embed(user, winnings, bet, player_hand, player_score, dealer_hand, dealer_score, balance, is_blackjack=False):
    """Создание эмбеда для победы."""
    messages = BLACKJACK_SUCCESS_MESSAGES if BLACKJACK_SUCCESS_MESSAGES else ["Вы победили и получили {amount} {currency}!"]
    message = random.choice(messages).format(
        amount=winnings, currency=currency,
        player_hand=player_hand, player_score=player_score,
        dealer_hand=dealer_hand, dealer_score=dealer_score
    )
    embed = disnake.Embed(
        description=f"<@{user.id}>, {message}",
        color=0x2F3136
    )
    embed.set_author(name=user.display_name, icon_url=user.avatar.url if user.avatar else user.default_avatar.url)
    embed.add_field(
        name="Ваша рука",
        value=f"{player_hand}\n**{'Blackjack' if is_blackjack and player_score == 21 else player_score}**",
        inline=True
    )
    embed.add_field(
        name="Рука дилера",
        value=f"{dealer_hand}\n**{'Blackjack' if is_blackjack and dealer_score == 21 else dealer_score}**",
        inline=True
    )
    return embed

def create_loss_embed(user, bet, player_hand, player_score, dealer_hand, dealer_score, balance, dealer_blackjack=False):
    """Создание эмбеда для проигрыша."""
    messages = BLACKJACK_FAIL_MESSAGES if BLACKJACK_FAIL_MESSAGES else ["Вы проиграли {amount} {currency}."]
    try:
        message = random.choice(messages).format(
            amount=bet, currency=currency,
            player_hand=player_hand, player_score=player_score,
            dealer_hand=dealer_hand, dealer_score=dealer_score
        )
    except (AttributeError, TypeError) as e:
        logger.error(f"Ошибка форматирования сообщения о проигрыше: {e}, используется запасной вариант")
        message = f"Вы проиграли {bet} {currency}."
    embed = disnake.Embed(
        description=f"<@{user.id}>, {message}",
        color=0x2F3136
    )
    embed.set_author(name=user.display_name, icon_url=user.avatar.url if user.avatar else user.default_avatar.url)
    embed.add_field(
        name="Ваша рука",
        value=f"{player_hand}\n**{player_score}**",
        inline=True
    )
    embed.add_field(
        name="Рука дилера",
        value=f"{dealer_hand}\n**{'Blackjack' if dealer_blackjack else dealer_score}**",
        inline=True
    )
    return embed

def create_push_embed(user, bet, player_hand, player_score, dealer_hand, dealer_score, balance, is_blackjack=False):
    """Создание эмбеда для ничьей."""
    messages = BLACKJACK_PUSH_MESSAGES if BLACKJACK_PUSH_MESSAGES else ["Ничья!"]
    message = random.choice(messages).format(
        player_hand=player_hand, player_score=player_score,
        dealer_hand=dealer_hand, dealer_score=dealer_score
    )
    embed = disnake.Embed(
        description=f"<@{user.id}>, {message}",
        color=0x2F3136
    )
    embed.set_author(name=user.display_name, icon_url=user.avatar.url if user.avatar else user.default_avatar.url)
    embed.add_field(
        name="Ваша рука",
        value=f"{player_hand}\n**{'Blackjack' if is_blackjack and player_score == 21 else player_score}**",
        inline=True
    )
    embed.add_field(
        name="Рука дилера",
        value=f"{dealer_hand}\n**{'Blackjack' if is_blackjack and dealer_score == 21 else dealer_score}**",
        inline=True
    )
    return embed

def create_error_embed(error_message, user_id):
    """Создание эмбеда для ошибок."""
    embed = disnake.Embed(
        title="Ошибка",
        description=f"<@{user_id}>, {error_message}",
        color=0x2F3136
    )
    return embed

def create_timeout_embed(user_id):
    """Создание эмбеда для таймаута (оставлено для совместимости)."""
    embed = disnake.Embed(
        description=f"<@{user_id}>, время ожидания истекло. Игра завершена.",
        color=0x2F3136
    )
    return embed

class BlackjackView(disnake.ui.View):
    """Класс для кнопок Hit, Stand, Double Down."""
    def __init__(self, cog, user_id: int, game_id: int, can_double: bool):
        super().__init__(timeout=300.0)  # 5 минут
        self.cog = cog
        self.user_id = user_id
        self.game_id = game_id
        self.can_double = can_double
        
        for item in self.children:
            if isinstance(item, disnake.ui.Button) and item.label == "Double Down":
                item.disabled = not self.can_double
                break
        logger.debug(f"Инициализирован BlackjackView: user_id={user_id}, game_id={game_id}, can_double={can_double}")

    def disable_buttons(self):
        """Отключение всех кнопок."""
        for item in self.children:
            if isinstance(item, disnake.ui.Button):
                item.disabled = True
        logger.debug(f"Отключены все кнопки для game_id={self.game_id}")

    async def interaction_check(self, interaction: disnake.MessageInteraction) -> bool:
        logger.debug(f"Проверка взаимодействия: user={interaction.user.id}, ожидаемый={self.user_id}, interaction_data={interaction.data}")
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Это не ваша игра!", ephemeral=True)
            return False
        # Проверка, активна ли игра
        game = await get_active_game(interaction.user.id)
        if not game or game["game_id"] != self.game_id or game["message_id"] != interaction.message.id:
            await interaction.response.send_message("Игра уже завершена или не найдена.", ephemeral=True)
            self.disable_buttons()
            await interaction.message.edit(view=self)
            return False
        return True

    async def on_timeout(self):
        """Автоматический stand при таймауте с эмбедом как при ручном stand."""
        logger.debug(f"Таймаут для game_id={self.game_id}, user_id={self.user_id}")
        game = await get_active_game(self.user_id)
        if not game or game["game_id"] != self.game_id or not game["message_id"]:
            logger.warning(f"Игра не найдена или уже завершена при таймауте: game_id={self.game_id}")
            await delete_active_game(self.game_id)
            return

        try:
            channel = self.cog.bot.get_channel(game["channel_id"])
            if not channel:
                logger.error(f"Канал {game['channel_id']} не найден для game_id={self.game_id}")
                await delete_active_game(self.game_id)
                return

            game_message = await channel.fetch_message(game["message_id"])
            # Получаем полноценный объект пользователя
            guild = self.cog.bot.get_guild(game["guild_id"])
            user = guild.get_member(self.user_id) if guild else await self.cog.bot.fetch_user(self.user_id)
            if not user:
                logger.error(f"Пользователь {self.user_id} не найден для game_id={self.game_id}")
                await delete_active_game(self.game_id)
                return

            # Создаем фейковый объект взаимодействия
            class FakeInteraction:
                def __init__(self, cog, user, message, channel):
                    self.cog = cog
                    self.user = user  # Используем полноценный disnake.Member или disnake.User
                    self.message = message
                    self.channel = channel
                    self.response = self
                    self.data = {"custom_id": str(game["game_id"])}

                async def edit_message(self, embed, view):
                    logger.debug(f"FakeInteraction: Редактирование сообщения {self.message.id} при таймауте")
                    try:
                        await self.message.edit(embed=embed, view=view)
                        logger.debug(f"FakeInteraction: Эмбед успешно обновлен для сообщения {self.message.id}")
                    except disnake.HTTPException as e:
                        logger.error(f"FakeInteraction: Ошибка обновления эмбеда при таймауте: {e}")
                        await self.channel.send("Ошибка обновления игры при таймауте.", delete_after=5.0)

                async def send_message(self, content, delete_after=None):
                    logger.debug(f"FakeInteraction: Отправка сообщения при таймауте: content={content}")
                    await self.channel.send(content, delete_after=delete_after)

            interaction = FakeInteraction(self.cog, user, game_message, channel)
            await self.cog.process_action(interaction, "stand")
            logger.info(f"Игра {self.game_id} автоматически завершена с stand из-за таймаута")
        except Exception as e:
            logger.error(f"Ошибка при обработке таймаута для game_id={self.game_id}: {e}")
            # Резервное завершение игры
            try:
                channel = self.cog.bot.get_channel(game["channel_id"])
                if channel:
                    game_message = await channel.fetch_message(game["message_id"])
                    # Получаем пользователя для резервного эмбеда
                    guild = self.cog.bot.get_guild(game["guild_id"])
                    user = guild.get_member(self.user_id) if guild else await self.cog.bot.fetch_user(self.user_id)
                    if not user:
                        logger.error(f"Пользователь {self.user_id} не найден для резервного завершения game_id={self.game_id}")
                        await delete_active_game(self.game_id)
                        return

                    # Используем стандартный эмбед для stand
                    dealer_score, _ = self.cog.calculate_score(game["dealer_hand"], is_dealer=True)
                    while dealer_score < 17:
                        game["dealer_hand"].append(game["deck"].pop())
                        dealer_score, _ = self.cog.calculate_score(game["dealer_hand"], is_dealer=True)
                    player_score, _ = self.cog.calculate_score(game["player_hand"])
                    cash, _ = await get_user_balance(self.user_id, game["guild_id"])
                    self.disable_buttons()

                    if dealer_score > 21 or player_score > dealer_score:
                        winnings = game["bet"] * 2
                        is_blackjack = len(game["player_hand"]) == 2 and player_score == 21
                        if is_blackjack:
                            winnings = int(game["bet"] * 2.5)
                        await update_cash(self.user_id, game["guild_id"], winnings)
                        cash, _ = await get_user_balance(self.user_id, game["guild_id"])
                        embed = create_win_embed(
                            user=user,
                            winnings=winnings,
                            bet=game["bet"],
                            player_hand=self.cog.format_hand(game["player_hand"]),
                            player_score=player_score,
                            dealer_hand=self.cog.format_hand(game["dealer_hand"]),
                            dealer_score=dealer_score,
                            balance=cash,
                            is_blackjack=is_blackjack
                        )
                        result = "player" if not is_blackjack else "blackjack"
                    elif player_score == dealer_score:
                        await update_cash(self.user_id, game["guild_id"], game["bet"])
                        cash, _ = await get_user_balance(self.user_id, game["guild_id"])
                        embed = create_push_embed(
                            user=user,
                            bet=game["bet"],
                            player_hand=self.cog.format_hand(game["player_hand"]),
                            player_score=player_score,
                            dealer_hand=self.cog.format_hand(game["dealer_hand"]),
                            dealer_score=dealer_score,
                            balance=cash,
                            is_blackjack=(player_score == 21 and dealer_score == 21)
                        )
                        result = "push"
                    else:
                        embed = create_loss_embed(
                            user=user,
                            bet=game["bet"],
                            player_hand=self.cog.format_hand(game["player_hand"]),
                            player_score=player_score,
                            dealer_hand=self.cog.format_hand(game["dealer_hand"]),
                            dealer_score=dealer_score,
                            balance=cash,
                            dealer_blackjack=(dealer_score == 21 and len(game["dealer_hand"]) == 2)
                        )
                        result = "dealer"

                    await game_message.edit(embed=embed, view=self)
                    logger.debug(f"Резервный эмбед stand отправлен для game_id={self.game_id}")
                    await log_game_history(
                        game_id=self.game_id,
                        user_id=self.user_id,
                        guild_id=game["guild_id"],
                        bet=game["bet"],
                        result=result,
                        player_hand=game["player_hand"],
                        player_score=player_score,
                        dealer_hand=game["dealer_hand"],
                        dealer_score=dealer_score
                    )
            except Exception as e:
                logger.error(f"Ошибка резервного завершения игры для game_id={self.game_id}: {e}")
            finally:
                await delete_active_game(self.game_id)
                logger.info(f"Игра {self.game_id} удалена из-за ошибки таймаута")

    @disnake.ui.button(label="Hit", style=disnake.ButtonStyle.blurple)
    async def hit(self, button: disnake.ui.Button, interaction: disnake.MessageInteraction):
        logger.debug(f"Кнопка Hit нажата пользователем={interaction.user.id}")
        await self.cog.process_action(interaction, "hit")

    @disnake.ui.button(label="Stand", style=disnake.ButtonStyle.green)
    async def stand(self, button: disnake.ui.Button, interaction: disnake.MessageInteraction):
        logger.debug(f"Кнопка Stand нажата пользователем={interaction.user.id}")
        await self.cog.process_action(interaction, "stand")

    @disnake.ui.button(label="Double Down", style=disnake.ButtonStyle.secondary)
    async def double_down(self, button: disnake.ui.Button, interaction: disnake.MessageInteraction):
        logger.debug(f"Кнопка Double Down нажата пользователем={interaction.user.id}")
        await self.cog.process_action(interaction, "double down")

class BlackjackCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.suits = ['♠', '♥', '♦', '♣']
        self.ranks = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']
        self.card_emojis = CARD_EMOJIS
        logger.info("Инициализирован BlackjackCog")

    def init_deck(self, decks: int):
        """Инициализация колоды из указанного количества колод."""
        try:
            deck = [f"{rank}{suit}" for suit in self.suits for rank in self.ranks] * decks
            random.shuffle(deck)
            logger.debug(f"Инициализирована колода с {len(deck)} картами ({decks} колод)")
            return deck
        except Exception as e:
            logger.error(f"Ошибка в init_deck({decks}): {e}")
            raise

    def calculate_score(self, hand, is_dealer=False):
        """Подсчет очков руки, учет туза и soft рук."""
        try:
            score = 0
            aces = 0
            for card in hand:
                rank = card[:-1]
                if rank in ['J', 'Q', 'K']:
                    score += 10
                elif rank == 'A':
                    aces += 1
                else:
                    score += int(rank)
            
            for _ in range(aces):
                if score + 11 <= 21:
                    score += 11
                else:
                    score += 1
            
            if is_dealer and aces > 0 and score == 17:
                for card in hand:
                    if card[:-1] == '6':
                        score = 7
                        for c in hand:
                            rank = c[:-1]
                            if rank in ['J', 'Q', 'K']:
                                score += 10
                            elif rank == 'A':
                                score += 1
                            elif rank != '6':
                                score += int(rank)
                        break
            
            is_soft = False
            if aces > 0 and score > 11 and score <= 21:
                temp_score = score - 10
                if temp_score + 11 == score:
                    is_soft = True
            
            logger.debug(f"Рассчитан счёт: hand={hand}, score={score}, is_soft={is_soft}, is_dealer={is_dealer}")
            return score, is_soft
        except Exception as e:
            logger.error(f"Ошибка в calculate_score(hand={hand}, is_dealer={is_dealer}): {e}")
            raise

    def format_hand(self, hand, hide_first=False):
        """Форматирование руки в строку с эмодзи."""
        try:
            if hide_first and len(hand) > 0:
                formatted = f"{' '.join(self.card_emojis[card] for card in hand[1:])} {self.card_emojis['back']} "
            else:
                formatted = ' '.join(self.card_emojis[card] for card in hand)
            logger.debug(f"Форматирована рука: hand={hand}, hide_first={hide_first}, result={formatted}")
            return formatted
        except Exception as e:
            logger.error(f"Ошибка в format_hand(hand={hand}, hide_first={hide_first}): {e}")
            raise

    async def validate_bet(self, user_id: int, guild_id: int, bet: str, config: dict) -> tuple:
        """Валидация ставки."""
        logger.debug(f"Валидация ставки: user_id={user_id}, guild_id={guild_id}, bet={bet}")
        try:
            cash, _ = await get_user_balance(user_id, guild_id)
            logger.debug(f"Денежный баланс пользователя: {cash}")
            if bet.lower() == "all":
                amount = cash
            elif bet.lower() == "half":
                amount = cash // 2
            else:
                try:
                    amount = int(bet)
                except ValueError:
                    logger.debug(f"Неверная ставка: {bet}, не число")
                    return None, "invalid_bet"
                if amount > cash:
                    logger.debug(f"Недостаточно средств: bet={amount}, cash={cash}")
                    return None, "insufficient_cash"
            if amount < config["min_bet"]:
                logger.debug(f"Ставка ниже минимальной: bet={amount}, min_bet={config['min_bet']}")
                return None, "min_bet"
            logger.debug(f"Ставка проверена: amount={amount}")
            return amount, None
        except Exception as e:
            logger.error(f"Ошибка в validate_bet(user_id={user_id}, guild_id={guild_id}, bet={bet}): {e}")
            raise

    async def deduct_bet(self, user_id: int, guild_id: int, amount: int) -> bool:
        """Списание ставки."""
        logger.debug(f"Списание ставки: user_id={user_id}, guild_id={guild_id}, amount={amount}")
        try:
            cash, _ = await get_user_balance(user_id, guild_id)
            if cash < amount:
                logger.debug(f"Недостаточно средств для ставки: current_cash={cash}, amount={amount}")
                return False
            await update_cash(user_id, guild_id, -amount)
            logger.info(f"Списано {amount} cash для ставки в блэкджек пользователем {user_id}")
            return True
        except Exception as e:
            logger.error(f"Ошибка списания средств для пользователя {user_id}: {e}")
            return False

    async def process_action(self, interaction, action: str):
        """Обработка действий игрока (hit, stand, double down)."""
        logger.info(f"Обработка действия: user={interaction.user.id}, action={action}, message_id={interaction.message.id}, interaction_data={interaction.data}")
        try:
            # Проверка активной игры
            game = await get_active_game(interaction.user.id)
            if not game or game["message_id"] != interaction.message.id:
                logger.warning(f"Игра не найдена или message_id не совпадает: user={interaction.user.id}, game_message_id={game.get('message_id') if game else None}, interaction_message_id={interaction.message.id}")
                await interaction.response.send_message("Игра не найдена или завершена.", delete_after=5.0)
                view = BlackjackView(self, interaction.user.id, game["game_id"] if game else 0, can_double=False)
                view.disable_buttons()
                await interaction.message.edit(view=view)
                return

            config = get_blackjack_config()
            player_hand = game["player_hand"]
            dealer_hand = game["dealer_hand"]
            deck = game["deck"]
            bet = game["bet"]
            guild_id = game["guild_id"]
            game_id = game["game_id"]
            deck_count = len(deck)
            logger.debug(f"Состояние игры: game_id={game_id}, player_hand={player_hand}, dealer_hand={dealer_hand}, bet={bet}, deck_count={deck_count}")

            # Проверка наличия карт в колоде
            if deck_count < 10:
                deck = self.init_deck(config["decks"])
                deck_count = len(deck)
                logger.debug(f"Переинициализирована колода для game_id={game_id}: {deck_count} карт")

            view = BlackjackView(self, interaction.user.id, game_id, can_double=(await get_user_balance(interaction.user.id, guild_id))[0] >= bet)

            if action == "hit":
                player_hand.append(deck.pop())
                deck_count -= 1
                player_score, is_soft = self.calculate_score(player_hand)
                dealer_score, _ = self.calculate_score(dealer_hand[1:], is_dealer=True)
                logger.debug(f"Hit: player_hand={player_hand}, player_score={player_score}, is_soft={is_soft}, dealer_score={dealer_score}")
                await save_active_game(
                    game_id=game_id,
                    user_id=interaction.user.id,
                    guild_id=guild_id,
                    channel_id=game["channel_id"],
                    message_id=game["message_id"],
                    player_hand=player_hand,
                    dealer_hand=dealer_hand,
                    bet=bet,
                    deck=deck
                )
                embed = create_game_embed(
                    user=interaction.user,
                    player_hand=self.format_hand(player_hand),
                    player_score=player_score,
                    dealer_hand=self.format_hand(dealer_hand, hide_first=True),
                    dealer_score=dealer_score,
                    deck_count=deck_count,
                    decks=config["decks"],
                    is_soft=is_soft
                )
                if player_score > 21:
                    dealer_score, _ = self.calculate_score(dealer_hand, is_dealer=True)
                    cash, _ = await get_user_balance(interaction.user.id, guild_id)
                    logger.debug(f"Перебор: player_score={player_score}, dealer_score={dealer_score}, cash={cash}")
                    embed = create_loss_embed(
                        user=interaction.user,
                        bet=bet,
                        player_hand=self.format_hand(player_hand),
                        player_score=player_score,
                        dealer_hand=self.format_hand(dealer_hand),
                        dealer_score=dealer_score,
                        balance=cash,
                        dealer_blackjack=False
                    )
                    logger.info(f"Создание эмбеда проигрыша: bet={bet}")
                    await log_game_history(
                        game_id=game_id,
                        user_id=interaction.user.id,
                        guild_id=guild_id,
                        bet=bet,
                        result="dealer",
                        player_hand=player_hand,
                        player_score=player_score,
                        dealer_hand=dealer_hand,
                        dealer_score=dealer_score
                    )
                    await delete_active_game(game_id)
                    logger.info(f"Игра {game_id} завершена: игрок перебрал")
                    view.disable_buttons()
                try:
                    await interaction.response.edit_message(embed=embed, view=view)
                    logger.debug(f"Эмбед успешно обновлен для действия hit, game_id={game_id}")
                except disnake.HTTPException as e:
                    logger.error(f"Ошибка обновления эмбеда для hit: {e}")
                    await interaction.response.send_message("Ошибка обновления игры. Пожалуйста, проверьте игру.", delete_after=5.0)

            elif action == "stand":
                dealer_score, _ = self.calculate_score(dealer_hand, is_dealer=True)
                while dealer_score < 17:
                    dealer_hand.append(deck.pop())
                    dealer_score, _ = self.calculate_score(dealer_hand, is_dealer=True)
                    logger.debug(f"Дилер взял карту: dealer_hand={dealer_hand}, dealer_score={dealer_score}")
                player_score, is_soft = self.calculate_score(player_hand)
                cash, _ = await get_user_balance(interaction.user.id, guild_id)
                logger.debug(f"Stand: player_score={player_score}, dealer_score={dealer_score}, cash={cash}")

                view.disable_buttons()  # Отключаем кнопки до обновления эмбеда
                if dealer_score > 21 or player_score > dealer_score:
                    winnings = bet * 2
                    is_blackjack = len(player_hand) == 2 and player_score == 21
                    if is_blackjack:
                        winnings = int(bet * 2.5)
                    await update_cash(interaction.user.id, guild_id, winnings)
                    cash, _ = await get_user_balance(interaction.user.id, guild_id)
                    embed = create_win_embed(
                        user=interaction.user,
                        winnings=winnings,
                        bet=bet,
                        player_hand=self.format_hand(player_hand),
                        player_score=player_score,
                        dealer_hand=self.format_hand(dealer_hand),
                        dealer_score=dealer_score,
                        balance=cash,
                        is_blackjack=is_blackjack
                    )
                    logger.info(f"Создание эмбеда победы: winnings={winnings}, bet={bet}, is_blackjack={is_blackjack}")
                    result = "player" if not is_blackjack else "blackjack"
                elif player_score == dealer_score:
                    await update_cash(interaction.user.id, guild_id, bet)
                    cash, _ = await get_user_balance(interaction.user.id, guild_id)
                    embed = create_push_embed(
                        user=interaction.user,
                        bet=bet,
                        player_hand=self.format_hand(player_hand),
                        player_score=player_score,
                        dealer_hand=self.format_hand(dealer_hand),
                        dealer_score=dealer_score,
                        balance=cash,
                        is_blackjack=(player_score == 21 and dealer_score == 21)
                    )
                    logger.info(f"Создание эмбеда ничьей: bet={bet}")
                    result = "push"
                else:
                    embed = create_loss_embed(
                        user=interaction.user,
                        bet=bet,
                        player_hand=self.format_hand(player_hand),
                        player_score=player_score,
                        dealer_hand=self.format_hand(dealer_hand),
                        dealer_score=dealer_score,
                        balance=cash,
                        dealer_blackjack=(dealer_score == 21 and len(dealer_hand) == 2)
                    )
                    logger.info(f"Создание эмбеда проигрыша: bet={bet}")
                    result = "dealer"

                await log_game_history(
                    game_id=game_id,
                    user_id=interaction.user.id,
                    guild_id=guild_id,
                    bet=bet,
                    result=result,
                    player_hand=player_hand,
                    player_score=player_score,
                    dealer_hand=dealer_hand,
                    dealer_score=dealer_score
                )
                await delete_active_game(game_id)
                logger.info(f"Игра {game_id} завершена: result={result}")
                try:
                    await interaction.response.edit_message(embed=embed, view=view)
                    logger.debug(f"Эмбед успешно обновлен для действия stand, game_id={game_id}")
                except disnake.HTTPException as e:
                    logger.error(f"Ошибка обновления эмбеда для stand: {e}")
                    await interaction.response.send_message("Ошибка обновления игры. Игра завершена.", delete_after=5.0)

            elif action == "double down":
                cash, _ = await get_user_balance(interaction.user.id, guild_id)
                if cash < bet:
                    embed = create_error_embed(config["error_messages"]["insufficient_cash"], interaction.user.id)
                    try:
                        await interaction.response.edit_message(embed=embed, view=BlackjackView(self, interaction.user.id, game_id, can_double=False))
                        logger.debug(f"Эмбед ошибки отправлен для double down: insufficient_cash")
                    except disnake.HTTPException as e:
                        logger.error(f"Ошибка обновления эмбеда для double down (insufficient_cash): {e}")
                        await interaction.response.send_message("Ошибка обновления игры.", delete_after=5.0)
                    logger.warning(f"Double down не удался: недостаточно средств, user={interaction.user.id}, cash={cash}, bet={bet}")
                    return
                if len(player_hand) != 2:
                    embed = create_error_embed("Double Down доступен только на первых двух картах!", interaction.user.id)
                    try:
                        await interaction.response.edit_message(embed=embed, view=BlackjackView(self, interaction.user.id, game_id, can_double=False))
                        logger.debug(f"Эмбед ошибки отправлен для double down: not initial hand")
                    except disnake.HTTPException as e:
                        logger.error(f"Ошибка обновления эмбеда для double down (not initial hand): {e}")
                        await interaction.response.send_message("Ошибка обновления игры.", delete_after=5.0)
                    logger.warning(f"Double down не удался: не начальная рука, user={interaction.user.id}, player_hand={player_hand}")
                    return
                await self.deduct_bet(interaction.user.id, guild_id, bet)
                bet *= 2
                player_hand.append(deck.pop())
                deck_count -= 1
                player_score, is_soft = self.calculate_score(player_hand)
                logger.debug(f"Double down: player_hand={player_hand}, player_score={player_score}, bet={bet}")

                view.disable_buttons()  # Отключаем кнопки до обновления эмбеда
                if player_score > 21:
                    dealer_score, _ = self.calculate_score(dealer_hand, is_dealer=True)
                    cash, _ = await get_user_balance(interaction.user.id, guild_id)
                    embed = create_loss_embed(
                        user=interaction.user,
                        bet=bet,
                        player_hand=self.format_hand(player_hand),
                        player_score=player_score,
                        dealer_hand=self.format_hand(dealer_hand),
                        dealer_score=dealer_score,
                        balance=cash,
                        dealer_blackjack=False
                    )
                    logger.info(f"Создание эмбеда проигрыша: bet={bet}")
                    result = "dealer"
                else:
                    dealer_score, _ = self.calculate_score(dealer_hand, is_dealer=True)
                    while dealer_score < 17:
                        dealer_hand.append(deck.pop())
                        dealer_score, _ = self.calculate_score(dealer_hand, is_dealer=True)
                        logger.debug(f"Дилер взял карту: dealer_hand={dealer_hand}, dealer_score={dealer_score}")
                    cash, _ = await get_user_balance(interaction.user.id, guild_id)
                    if dealer_score > 21 or player_score > dealer_score:
                        winnings = bet * 2
                        await update_cash(interaction.user.id, guild_id, winnings)
                        cash, _ = await get_user_balance(interaction.user.id, guild_id)
                        embed = create_win_embed(
                            user=interaction.user,
                            winnings=winnings,
                            bet=bet,
                            player_hand=self.format_hand(player_hand),
                            player_score=player_score,
                            dealer_hand=self.format_hand(dealer_hand),
                            dealer_score=dealer_score,
                            balance=cash,
                            is_blackjack=False
                        )
                        logger.info(f"Создание эмбеда победы: winnings={winnings}, bet={bet}")
                        result = "player"
                    elif player_score == dealer_score:
                        await update_cash(interaction.user.id, guild_id, bet)
                        cash, _ = await get_user_balance(interaction.user.id, guild_id)
                        embed = create_push_embed(
                            user=interaction.user,
                            bet=bet,
                            player_hand=self.format_hand(player_hand),
                            player_score=player_score,
                            dealer_hand=self.format_hand(dealer_hand),
                            dealer_score=dealer_score,
                            balance=cash,
                            is_blackjack=False
                        )
                        logger.info(f"Создание эмбеда ничьей: bet={bet}")
                        result = "push"
                    else:
                        embed = create_loss_embed(
                            user=interaction.user,
                            bet=bet,
                            player_hand=self.format_hand(player_hand),
                            player_score=player_score,
                            dealer_hand=self.format_hand(dealer_hand),
                            dealer_score=dealer_score,
                            balance=cash,
                            dealer_blackjack=(dealer_score == 21 and len(dealer_hand) == 2)
                        )
                        logger.info(f"Создание эмбеда проигрыша: bet={bet}")
                        result = "dealer"

                await log_game_history(
                    game_id=game_id,
                    user_id=interaction.user.id,
                    guild_id=guild_id,
                    bet=bet,
                    result=result,
                    player_hand=player_hand,
                    player_score=player_score,
                    dealer_hand=dealer_hand,
                    dealer_score=dealer_score
                )
                await delete_active_game(game_id)
                logger.info(f"Игра {game_id} завершена: result={result}")
                try:
                    await interaction.response.edit_message(embed=embed, view=view)
                    logger.debug(f"Эмбед успешно обновлен для действия double down, game_id={game_id}")
                except disnake.HTTPException as e:
                    logger.error(f"Ошибка обновления эмбеда для double down: {e}")
                    await interaction.response.send_message("Ошибка обновления игры. Игра завершена.", delete_after=5.0)
        except Exception as e:
            logger.error(f"Критическая ошибка в process_action(user={interaction.user.id}, action={action}): {e}")
            embed = create_error_embed("Произошла ошибка при обработке действия. Игра завершена.", interaction.user.id)
            view = BlackjackView(self, interaction.user.id, game_id if 'game_id' in locals() else 0, can_double=False)
            view.disable_buttons()
            try:
                await interaction.response.edit_message(embed=embed, view=view)
                logger.debug(f"Эмбед ошибки отправлен для критической ошибки")
            except disnake.HTTPException as e:
                logger.error(f"Ошибка отправки эмбеда ошибки: {e}")
                await interaction.response.send_message("Критическая ошибка. Игра завершена.", delete_after=5.0)
            if 'game_id' in locals():
                await delete_active_game(game_id)

    @commands.command(name="blackjack", aliases=["bj"])
    async def blackjack(self, ctx: commands.Context, bet: str):
        """Команда для начала игры в блэкджек."""
        logger.info(f"Команда блэкджека вызвана: user={ctx.author.id}, bet={bet}, channel={ctx.channel.id}")
        try:
            config = get_blackjack_config()
            amount, error = await self.validate_bet(ctx.author.id, ctx.guild.id, bet, config)
            if error:
                error_message = config["error_messages"].get(error, "Некорректная ставка.")
                embed = create_error_embed(error_message, ctx.author.id)
                await ctx.send(embed=embed)
                logger.warning(f"Валидация ставки не удалась: user={ctx.author.id}, error={error}")
                return

            game = await get_active_game(ctx.author.id)
            if game:
                embed = create_error_embed(config["error_messages"]["active_game"], ctx.author.id)
                await ctx.send(embed=embed)
                logger.info(f"Найдена активная игра для пользователя {ctx.author.id}, отправлен эмбед ошибки")
                return

            if not await self.deduct_bet(ctx.author.id, ctx.guild.id, amount):
                embed = create_error_embed(config["error_messages"]["insufficient_cash"], ctx.author.id)
                await ctx.send(embed=embed)
                logger.warning(f"Списание ставки не удалось: user={ctx.author.id}, amount={amount}")
                return

            deck = self.init_deck(config["decks"])
            logger.debug(f"Создана колода: {len(deck)} карт")
            player_hand = [deck.pop(), deck.pop()]
            dealer_hand = [deck.pop(), deck.pop()]
            deck_count = len(deck)
            player_score, is_soft = self.calculate_score(player_hand)
            dealer_score, _ = self.calculate_score(dealer_hand, is_dealer=True)
            logger.debug(f"Игра начата: player_hand={player_hand}, dealer_hand={dealer_hand}, player_score={player_score}, dealer_score={dealer_score}, deck_count={deck_count}")

            # Проверка на моментальный блэкджек
            is_blackjack = len(player_hand) == 2 and player_score == 21
            dealer_blackjack = len(dealer_hand) == 2 and dealer_score == 21
            logger.debug(f"Проверка блэкджека: is_blackjack={is_blackjack}, dealer_blackjack={dealer_blackjack}")

            if is_blackjack or dealer_blackjack:
                cash, _ = await get_user_balance(ctx.author.id, ctx.guild.id)
                game_id = await save_active_game(
                    game_id=0,
                    user_id=ctx.author.id,
                    guild_id=ctx.guild.id,
                    channel_id=ctx.channel.id,
                    message_id=0,
                    player_hand=player_hand,
                    dealer_hand=dealer_hand,
                    bet=amount,
                    deck=deck
                )
                if game_id == 0:
                    await update_cash(ctx.author.id, ctx.guild.id, amount)
                    logger.info(f"Возвращено {amount} пользователю {ctx.author.id} из-за ошибки сохранения игры")
                    embed = create_error_embed("Ошибка при сохранении игры. Ставка возвращена.", ctx.author.id)
                    await ctx.send(embed=embed)
                    return

                view = BlackjackView(self, ctx.author.id, game_id, can_double=False)
                view.disable_buttons()
                if is_blackjack and not dealer_blackjack:
                    winnings = int(amount * 2.5)
                    await update_cash(ctx.author.id, ctx.guild.id, winnings)
                    cash, _ = await get_user_balance(ctx.author.id, ctx.guild.id)
                    embed = create_win_embed(
                        user=ctx.author,
                        winnings=winnings,
                        bet=amount,
                        player_hand=self.format_hand(player_hand),
                        player_score=player_score,
                        dealer_hand=self.format_hand(dealer_hand),
                        dealer_score=self.calculate_score(dealer_hand[1:], is_dealer=True)[0],
                        balance=cash,
                        is_blackjack=True
                    )
                    logger.info(f"Создание эмбеда победы блэкджека: winnings={winnings}, bet={amount}")
                    result = "blackjack"
                elif dealer_blackjack and not is_blackjack:
                    embed = create_loss_embed(
                        user=ctx.author,
                        bet=amount,
                        player_hand=self.format_hand(player_hand),
                        player_score=player_score,
                        dealer_hand=self.format_hand(dealer_hand),
                        dealer_score=dealer_score,
                        balance=cash,
                        dealer_blackjack=True
                    )
                    logger.info(f"Создание эмбеда проигрыша (дилерский блэкджек): bet={amount}")
                    result = "dealer"
                else:  # Оба блэкджека
                    await update_cash(ctx.author.id, ctx.guild.id, amount)
                    cash, _ = await get_user_balance(ctx.author.id, ctx.guild.id)
                    embed = create_push_embed(
                        user=ctx.author,
                        bet=amount,
                        player_hand=self.format_hand(player_hand),
                        player_score=player_score,
                        dealer_hand=self.format_hand(dealer_hand),
                        dealer_score=dealer_score,
                        balance=cash,
                        is_blackjack=True
                    )
                    logger.info(f"Создание эмбеда ничьей (оба блэкджека): bet={amount}")
                    result = "push"
                
                message = await ctx.send(embed=embed, view=view)
                # Обновляем message_id
                await save_active_game(
                    game_id=game_id,
                    user_id=ctx.author.id,
                    guild_id=ctx.guild.id,
                    channel_id=ctx.channel.id,
                    message_id=message.id,
                    player_hand=player_hand,
                    dealer_hand=dealer_hand,
                    bet=amount,
                    deck=deck
                )
                await log_game_history(
                    game_id=game_id,
                    user_id=ctx.author.id,
                    guild_id=ctx.guild.id,
                    bet=amount,
                    result=result,
                    player_hand=player_hand,
                    player_score=player_score,
                    dealer_hand=dealer_hand,
                    dealer_score=dealer_score
                )
                await delete_active_game(game_id)
                logger.info(f"Игра {game_id} завершена: result={result} (блэкджек)")
            else:
                can_double = (await get_user_balance(ctx.author.id, ctx.guild.id))[0] >= amount
                game_id = await save_active_game(
                    game_id=0,
                    user_id=ctx.author.id,
                    guild_id=ctx.guild.id,
                    channel_id=ctx.channel.id,
                    message_id=0,
                    player_hand=player_hand,
                    dealer_hand=dealer_hand,
                    bet=amount,
                    deck=deck
                )
                if game_id == 0:
                    await update_cash(ctx.author.id, ctx.guild.id, amount)
                    logger.info(f"Возвращено {amount} пользователю {ctx.author.id} из-за ошибки сохранения игры")
                    embed = create_error_embed("Ошибка при сохранении игры. Ставка возвращена.", ctx.author.id)
                    await ctx.send(embed=embed)
                    return
                
                logger.debug(f"Игра сохранена: game_id={game_id}")
                embed = create_game_embed(
                    user=ctx.author,
                    player_hand=self.format_hand(player_hand),
                    player_score=player_score,
                    dealer_hand=self.format_hand(dealer_hand, hide_first=True),
                    dealer_score=self.calculate_score(dealer_hand[1:], is_dealer=True)[0],
                    deck_count=deck_count,
                    decks=config["decks"],
                    is_soft=is_soft
                )
                view = BlackjackView(self, ctx.author.id, game_id, can_double)
                logger.debug(f"Отправка эмбеда игры для game_id={game_id}")
                message = await ctx.send(embed=embed, view=view)
                logger.debug(f"Обновление игры с message_id={message.id}")
                await save_active_game(
                    game_id=game_id,
                    user_id=ctx.author.id,
                    guild_id=ctx.guild.id,
                    channel_id=ctx.channel.id,
                    message_id=message.id,
                    player_hand=player_hand,
                    dealer_hand=dealer_hand,
                    bet=amount,
                    deck=deck
                )
                logger.info(f"Игра начата: game_id={game_id}, user_id={ctx.author.id}, bet={amount}")
        except Exception as e:
            logger.error(f"Ошибка в blackjack(user={ctx.author.id}, bet={bet}): {e}")
            embed = create_error_embed("Произошла ошибка при создании игры. Попробуйте снова.", ctx.author.id)
            await ctx.send(embed=embed)
            # Вернуть ставку, если она была списана
            if 'amount' in locals():
                await update_cash(ctx.author.id, ctx.guild.id, amount)
                logger.info(f"Возвращено {amount} пользователю {ctx.author.id} из-за ошибки создания игры")

    @commands.Cog.listener()
    async def on_message(self, message: disnake.Message):
        """Обработка текстовых действий hit, stand, double down."""
        logger.debug(f"Получено сообщение: user={message.author.id}, content={message.content}, channel={message.channel.id}")
        if message.author.bot or not message.guild:
            logger.debug(f"Игнорирование сообщения: bot={message.author.bot}, guild={message.guild}")
            return

        action = message.content.lower().strip()
        if action not in ["hit", "stand", "double down"]:
            logger.debug(f"Игнорирование сообщения: action '{action}' не в ['hit', 'stand', 'double down']")
            return

        game = await get_active_game(message.author.id)
        if not game:
            logger.debug(f"Нет активной игры для user={message.author.id}")
            return
        if game["channel_id"] != message.channel.id:
            logger.debug(f"Несоответствие канала: game_channel={game['channel_id']}, message_channel={message.channel.id}")
            return

        # Получаем сообщение игры
        try:
            game_message = await message.channel.fetch_message(game["message_id"])
        except disnake.NotFound:
            logger.warning(f"Игровое сообщение не найдено: message_id={game['message_id']}")
            await message.channel.send("Игровое сообщение не найдено.", delete_after=5.0)
            return

        logger.info(f"Обработка текстового действия: user={message.author.id}, action={action}, game_id={game['game_id']}, message_id={game['message_id']}")

        # Создаём FakeInteraction для обработки действия
        class FakeInteraction:
            def __init__(self, user, message, channel):
                self.user = user  # Используем message.author (disnake.Member)
                self.message = message
                self.channel = channel
                self.response = self
                self.data = {"custom_id": str(game["game_id"])}

            async def edit_message(self, embed, view):
                logger.debug(f"FakeInteraction: Редактирование сообщения {self.message.id} с эмбедом и view")
                try:
                    await self.message.edit(embed=embed, view=view)
                    logger.debug(f"FakeInteraction: Эмбед успешно обновлен для сообщения {self.message.id}")
                except disnake.HTTPException as e:
                    logger.error(f"FakeInteraction: Ошибка обновления эмбеда: {e}")
                    await self.channel.send("Ошибка обновления игры.", delete_after=5.0)

            async def send_message(self, content, delete_after=None):
                logger.debug(f"FakeInteraction: Отправка сообщения: content={content}, delete_after={delete_after}")
                await self.channel.send(content, delete_after=delete_after)

        interaction = FakeInteraction(message.author, game_message, message.channel)
        await self.process_action(interaction, action)
        try:
            await message.delete()
        except Exception as e:
            logger.warning(f"Не удалось удалить сообщение действия: {e}")

def setup(bot):
    bot.add_cog(BlackjackCog(bot))
    logger.info("BlackjackCog загружен")