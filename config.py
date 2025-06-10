Token = ''
Prefix = '.'
audit_webhook = ""
database_url = ''

import disnake
import configparser
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# Чтение конфигурации из config.ini
config = configparser.ConfigParser()
config.read("config.ini", encoding="utf-8")

currency = '🪙'

audit_url = audit_webhook

def make_audit_payload(action: str,
                       user_id: int,
                       cash_change: int,
                       bank_change: int,
                       reason: str) -> dict:
    """
    Формирует тело JSON для отправки в Discord Webhook.
    cash_change / bank_change должны быть signed integers.
    """
    ts = datetime.now().strftime("%-m/%-d/%Y %-I:%M %p")
    return {
        "content": str(user_id),
        "embeds": [
            {
                "color": 3092790,
                "title": action,
                "description":
                    f"**Пользователь:** <@{user_id}>\n"
                    f"**Сумма:** Cash: `{cash_change:+,}` | Bank: `{bank_change:+,}`\n"
                    f"**Причина:** {reason}",
                "footer": {"text": ts}
            }
        ]
    }

ROULETTE_INFO = """
В рулетке можно делать несколько ставок.
Использование: roulette <amount> <space>

**Множители выплат:**
[x36] Число
[x3] Десятки (1-12, 13-24, 25-36)
[x3] Столбцы (1st, 2nd, 3rd)
[x2] Половины (1-18, 19-36)
[x2] Нечетный/Четный (odd/even)
[x2] Цвета (red, black)

**Например:**
roulette 200 odd
roulette 600 2nd"""

ROULETTE_IMAGE_URL = "https://media.discordapp.net/attachments/506838906872922145/839184445453369374/unknown.png"

CARD_EMOJIS = {
    "2♠": "<:049twoofspades:1370656888576020480>",
    "3♠": "<:046threeofspades:1370656862177067038>",
    "4♠": "<:040fourofspades:1370656816291119136>",
    "5♠": "<:038fiveofspades:1370656798742151189>",
    "6♠": "<:032sixofspades:1370656749899616286>",
    "7♠": "<:030sevenofspades:1370656706597486602>",
    "8♠": "<:026eightofspades:1370656661605449750>",
    "9♠": "<:020nineofspades:1370656597847838841>",
    "10♠": "<:019tenofspades:1370656587496165517>",
    "J♠": "<:014jackofspades:1370656533544829049>",
    "Q♠": "<:010queenofspades:1370656477236301866>",
    "K♠": "<:007kingofspades:1370656412480573484>",
    "A♠": "<:002aceofspades:1370656309711601664>",
    "2♥": "<:051twoofhearts:1370656907412377671>",
    "3♥": "<:045threeofhearts:1370656854325334067>",
    "4♥": "<:042fourofhearts:1370656830698815558>",
    "5♥": "<:039fiveofhearts:1370656807952846978>",
    "6♥": "<:035sixofhearts:1370656775786856479>",
    "7♥": "<:029sevenofhearts:1370656694513831976>",
    "8♥": "<:024eightofhearts:1370656634648662056>",
    "9♥": "<:023nineofhearts:1370656619180068966>",
    "10♥": "<:017tenofhearts:1370656553878814851>",
    "J♥": "<:015jackofhearts:1370656540427550770>",
    "Q♥": "<:012queenofhearts:1370656518999117824>",
    "K♥": "<:006kingofhearts:1370656389516492821>",
    "A♥": "<:001aceofhearts:1370656294322573362>",
    "2♦": "<:052twoofdiamonds:1370656920481960037>",
    "3♦": "<:048threeofdiamonds:1370656880149532743>",
    "4♦": "<:043fourofdiamonds:1370656838974046208>",
    "5♦": "<:036fiveofdiamonds:1370656784083189830>",
    "6♦": "<:034sixofdiamonds:1370656765917794304>",
    "7♦": "<:031sevenofdiamonds:1370656729414504489>",
    "8♦": "<:027eightofdiamonds:1370656671214469241>",
    "9♦": "<:021nineofdiamonds:1370656605250781235>",
    "10♦": "<:016tenofdiamonds:1370656547679764583>",
    "J♦": "<:044jackofdiamonds:1370656845924012032>",
    "Q♦": "<:011queenofdiamonds:1370656510689935421>",
    "K♦": "<:008kingofdiamonds:1370656421573689384>",
    "A♦": "<:004aceofdiamonds:1370656349372944465>",
    "2♣": "<:050twoofclubs:1370656897723793528>",
    "3♣": "<:047threeofclubs:1370656871723171910>",
    "4♣": "<:041fourofclubs:1370656824382197821>",
    "5♣": "<:037fiveofclubs:1370656791184015391>",
    "6♣": "<:033sixofclubs:1370656757965127692>",
    "7♣": "<:028sevenofclubs:1370656682681565276>",
    "8♣": "<:025eightofclubs:1370656646120079370>",
    "9♣": "<:022nineofclubs:1370656611269480508>",
    "10♣": "<:018tenofclubs:1370656560568860795>",
    "J♣": "<:013jackofclubs:1370656525865062490>",
    "Q♣": "<:009queenofclubs:1370656432122232832>",
    "K♣": "<:005kingofclubs:1370656373443919892>",
    "A♣": "<:003aceofclubs:1370656327486935040>",
    "back": "<:053playingcard:1370656932238458943>"
}

# Сообщения для команды balance
BALANCE_BOT_ERROR = "Нельзя проверять баланс ботов!"
BALANCE_ERROR = "Ошибка при получении баланса: {error}"

# Сообщения для команды leaderboard
LEADERBOARD_NOTICE = (
    "Неверный аргумент. Используйте:\n"
    "- `leaderboard` или `leaderboard -total` — топ по сумме (cash + bank)\n"
    "- `leaderboard -cash` — топ по cash\n"
    "- `leaderboard -bank` — топ по bank"
)
LEADERBOARD_NO_USERS = "На сервере пока нет пользователей с балансом."
LEADERBOARD_ERROR = "Ошибка при получении топа: {error}"

# Сообщения для команды deposit
DEPOSIT_INVALID_AMOUNT = "Укажите число или 'all'."
DEPOSIT_INSUFFICIENT = "Недостаточно средств! У вас: {currency} {cash} (🏦 {currency} {bank})."
DEPOSIT_ZERO_AMOUNT = "Сумма должна быть больше 0."
DEPOSIT_ERROR = "Ошибка при выполнении депозита: {error}"

# Сообщения для команды withdraw
WITHDRAW_INVALID_AMOUNT = "Укажите число или 'all'."
WITHDRAW_INSUFFICIENT = "Недостаточно средств! У вас: {currency} {bank} (💵 {currency} {cash})."
WITHDRAW_ZERO_AMOUNT = "Сумма должна быть больше 0."
WITHDRAW_ERROR = "Ошибка при выполнении снятия: {error}"

# Сообщения для команд work, crime, slut
COMMAND_CONFIG_ERROR = "Ошибка конфигурации: {error}"
COMMAND_COOLDOWN = "Команда `{command_name}` на кулдауне! Осталось: {minutes} мин {seconds} сек."
COMMAND_ERROR = "Ошибка при выполнении команды: {error}"

# Сообщения для команды work
WORK_SUCCESS_MESSAGES = [
    "Отличная работа! Вы заработали {currency} {amount}!",
    "Успешный день! Получено {currency} {amount}!",
    "Работа сделана! Ваш доход: {currency} {amount}!"
]
WORK_FAIL_MESSAGES = [
    "Неудачный день... Вы потеряли {currency} {amount}.",
    "Работа не задалась, штраф: {currency} {amount}.",
    "Ошибка на работе, убыток: {currency} {amount}."
]

# Сообщения для команды crime
CRIME_SUCCESS_MESSAGES = [
    "Куш сорван! Вы украли {currency} {amount}!",
    "Идеальное преступление! Доход: {currency} {amount}!",
    "Вы обчистили сейф на {currency} {amount}!"
]
CRIME_FAIL_MESSAGES = [
    "Попались! Штраф: {currency} {amount}.",
    "Провал! Вы потеряли {currency} {amount}.",
    "Копы на хвосте, убыток: {currency} {amount}."
]

# Сообщения для команды slut
SLUT_SUCCESS_MESSAGES = [
    "Клиент доволен! Заработано {currency} {amount}!",
    "Успешная ночь! Получено {currency} {amount}!",
    "Работа сделана, доход: {currency} {amount}!"
]
SLUT_FAIL_MESSAGES = [
    "Клиент сбежал... Потеряно {currency} {amount}.",
    "Неудачная ночь, штраф: {currency} {amount}.",
    "Провал, убыток: {currency} {amount}."
]

# Сообщения для команды roulette
ROULETTE_SUCCESS_MESSAGES = [
    "{mention} выиграл {currency} {amount}, ставка на `{space}`!",
    "{mention} сорвал куш! {currency} {amount} за `{space}`!",
    "{mention}, удача на твоей стороне! {currency} {amount} за `{space}`!"
]
ROULETTE_FAIL_MESSAGES = [
    "{mention}, ставка на `{space}` проиграла. Потеряно {currency} {amount}.",
    "{mention}, не повезло... `{space}` не сыграл. Потеря: {currency} {amount}.",
    "{mention}, ставка `{space}` не зашла. Убыток: {currency} {amount}."
]
ROULETTE_NO_WINNERS = "К сожалению, никто не победил :-("
ROULETTE_ERROR_MESSAGES = {
    "invalid_bet": "Неверная ставка. Укажите число, 'all' или 'half'.",
    "insufficient_cash": "Недостаточно средств! У вас {currency} {cash}.",
    "min_bet": "Минимальная ставка: {currency} {min_bet}.",
    "invalid_space": "Неверное место ставки. Проверьте: {roulette_info}",
    "no_active_roulette": "Нет активной рулетки в этом канале.",
    "invalid_number": "Неверное число. Укажите число от 0 до 36.",
    "database_error": "Ошибка базы данных. Попробуйте позже."
}
ROULETTE_BET_SUCCESS = "🎰 {mention}, ставка {currency} {amount} на `{space}` принята! Осталось {seconds} сек."
ROULETTE_START = "🎰 {mention}, рулетка запущена! Ставка {currency} {amount} на `{space}` принята. Делайте ставки в течение {duration} сек!"
ROULETTE_SET_SUCCESS = "🎰 {mention}, результат рулетки установлен на {number}."
ROULETTE_CONFIG_ERROR = "Ошибка конфигурации: {error}"
ROULETTE_PROCESS_ERROR = "Ошибка обработки ставки: {error}"
ROULETTE_CASH_ERROR = "Ошибка при списании {currency}. Попробуйте снова."

# Резервные сообщения
FALLBACK_SUCCESS_MESSAGES = ["Успех! Получено {currency} {amount}!"]
FALLBACK_FAIL_MESSAGES = ["Неудача! Потеряно {currency} {amount}."]

# Blackjack Messages
BLACKJACK_SUCCESS_MESSAGES = [
    "Вы выиграли {amount} {currency}!",
    "Победа! Вы заработали {amount} {currency}!",
    "Отлично сыграно! Ваш выигрыш: {amount} {currency}."
]
BLACKJACK_FAIL_MESSAGES = [
    "Вы проиграли {amount} {currency}.",
    "Поражение! Вы потеряли {amount} {currency}.",
    "Не повезло... Потеряно {amount} {currency}."
]
BLACKJACK_PUSH_MESSAGES = [
    "Ничья!",
    "Равный счёт! Ставка возвращена.",
    "Ничья, ставка возвращена!"
]
BLACKJACK_ERROR_MESSAGES = {
    "invalid_bet": "Некорректная ставка! Укажите число, 'all' или 'half'.",
    "insufficient_cash": "Недостаточно средств для ставки!",
    "min_bet": "Ставка должна быть не меньше {min_bet} {currency}!",
    "active_game": "У вас уже есть активная игра! Завершите её (hit/stand/double)."
}

GIVEMONEY_SUCCESS_MESSAGES = [
    "Успешно переведено {amount} {currency} пользователю {target}! Налог: {fee} {currency}, получено: {received} {currency}"
]
GIVEMONEY_FAIL_MESSAGES = [
    "Не удалось перевести {amount} {currency} пользователю {target}."
]
GIVEMONEY_INSUFFICIENT_FUNDS_MESSAGES = [
    "Недостаточно средств: требуется {required} {currency}, доступно {available} {currency}"
]
GIVEMONEY_ERROR_MESSAGES = [
    "Ошибка: {error}"
]
GIVEMONEY_COOLDOWN_MESSAGES = [
    "Команда {command_name} на кулдауне! Попробуйте снова через {minutes} мин {seconds} сек."
]
GIVEMONEY_NOTICE_MESSAGES = [
    "Уведомление: {error}"
]

GIVEMONEY_SUCCESS_MESSAGES = [
    "Успешно переведено {amount} {currency} пользователю {target}! Налог: {fee} {currency}, получено: {received} {currency}"
]
GIVEMONEY_FAIL_MESSAGES = [
    "Не удалось перевести {amount} {currency} пользователю {target}."
]
GIVEMONEY_INSUFFICIENT_FUNDS_MESSAGES = [
    "Недостаточно средств: требуется {required} {currency}, доступно {available} {currency}"
]
GIVEMONEY_ERROR_MESSAGES = [
    "Ошибка: {error}"
]
GIVEMONEY_COOLDOWN_MESSAGES = [
    "Команда {command_name} на кулдауне! Попробуйте снова через {minutes} мин {seconds} сек."
]
GIVEMONEY_NOTICE_MESSAGES = [
    "Уведомление: {error}"
]

ROB_SUCCESS_MESSAGES = [
    "Успех! Ты украл {amount} {currency} у {target}!"
]
ROB_FAIL_MESSAGES = [
    "Неудача! Потеряно {amount} {currency} при попытке ограбить {target}."
]
ROB_ERROR_MESSAGES = [
    "Ошибка: {error}"
]
ROB_COOLDOWN_MESSAGES = [
    "Команда {command_name} на кулдауне! Попробуйте снова через {minutes} мин {seconds} сек."
]
ROB_NOTICE_MESSAGES = [
    "Неверный аргумент. Используйте:\n"
    "- `rob <@user>`\n"

]
