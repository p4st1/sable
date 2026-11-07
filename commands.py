"""Команды чата. Строка "/give apple 5" превращается в вызов give(game, ["apple", "5"]).

Координаты в командах как в оригинале: x, y вверх (высота ног), z. В самом мире
ось Y направлена вниз, перевод делают player_position и teleport у игры.
Каждая команда возвращает список ответов (текст, цвет) для ленты чата.
"""
from typing import Callable, NamedTuple

from chat import GRAY, PLAYER_NAME, RED
from items import MAX_STACK, NAMES, item_name
from storage import GAME_MODES

MAX_GIVE = MAX_STACK * 36

MODE_ALIASES = {
    "survival": "survival", "s": "survival", "0": "survival",
    "creative": "creative", "c": "creative", "1": "creative",
}


class CommandError(Exception):
    """Ошибка с понятным текстом для чата."""


class UsageError(Exception):
    """Неверные аргументы: в чат выводится подсказка, как писать команду."""


class Command(NamedTuple):
    usage: str
    description: str
    run: Callable


COMMANDS = {}


def command(name, usage, description):
    def register(function):
        COMMANDS[name] = Command(usage, description, function)
        return function

    return register


def run(game, line):
    """Выполняет строку из чата, которая начинается с /."""
    parts = line[1:].split()

    if not parts or parts[0].lower() not in COMMANDS:
        return [('Unknown command. Type "/help" for help.', RED)]

    entry = COMMANDS[parts[0].lower()]

    try:
        return entry.run(game, parts[1:])

    except UsageError:
        return [(f"Usage: {entry.usage}", RED)]

    except CommandError as error:
        return [(str(error), RED)]


def number(text):
    try:
        return float(text)
    except ValueError:
        raise CommandError(f"Invalid number '{text}'")


def coordinate(text, current):
    """Число или ~ (текущее значение), ~5 это на 5 больше текущего."""
    if text.startswith("~"):
        return current + (number(text[1:]) if text[1:] else 0.0)

    return number(text)


def format_position(x, y, z):
    return f"{x:.2f}, {y:.2f}, {z:.2f}"


@command("help", "/help", "Show this list")
def help_command(game, args):
    return [("Commands:", GRAY)] + [
        (f"{entry.usage} - {entry.description}", GRAY)
        for entry in COMMANDS.values()
    ]


@command("gamemode", "/gamemode <survival|creative>", "Change game mode")
def gamemode(game, args):
    if len(args) != 1:
        raise UsageError

    mode = MODE_ALIASES.get(args[0].lower())

    if mode not in GAME_MODES:
        raise CommandError(f"Unknown game mode '{args[0]}'")

    game.set_game_mode(mode)

    return [(f"Set own game mode to {mode.title()} Mode", GRAY)]


@command("tp", "/tp <x> <y> <z>", "Teleport, ~ means current position")
def teleport(game, args):
    if len(args) != 3:
        raise UsageError

    current = game.player_position()
    x, y, z = (coordinate(text, value) for text, value in zip(args, current))

    game.teleport(x, y, z)

    return [(f"Teleported {PLAYER_NAME} to {format_position(x, y, z)}", GRAY)]


@command("give", "/give <item> [count]", "Give yourself an item")
def give(game, args):
    if not 1 <= len(args) <= 2:
        raise UsageError

    item = args[0].lower().removeprefix("minecraft:")

    if item not in NAMES:
        raise CommandError(f"Unknown item '{args[0]}'")

    count = 1

    if len(args) == 2:
        if not args[1].isdigit() or not 1 <= int(args[1]) <= MAX_GIVE:
            raise CommandError(f"Count must be between 1 and {MAX_GIVE}")

        count = int(args[1])

    left = game.inventory.add(item, count)
    given = count - left

    if given == 0:
        raise CommandError("Inventory is full")

    return [(f"Gave {given} [{item_name(item)}] to {PLAYER_NAME}", GRAY)]


@command("kill", "/kill", "Kill yourself")
def kill(game, args):
    if args:
        raise UsageError

    game.kill_player()

    return [(f"Killed {PLAYER_NAME}", GRAY)]


@command("clear", "/clear", "Empty your inventory")
def clear(game, args):
    if args:
        raise UsageError

    removed = sum(stack.count for stack in game.inventory.slots if stack is not None)
    game.inventory.slots[:] = [None] * len(game.inventory.slots)

    if removed == 0:
        raise CommandError(f"No items were found on player {PLAYER_NAME}")

    return [(f"Cleared the inventory of {PLAYER_NAME}, removing {removed} items", GRAY)]


@command("spawnpoint", "/spawnpoint", "Respawn here after death")
def spawnpoint(game, args):
    if args:
        raise UsageError

    game.spawn_point = game.camera.position

    return [(f"Set spawn point to {format_position(*game.player_position())}", GRAY)]


@command("seed", "/seed", "Show the world seed")
def seed(game, args):
    if args:
        raise UsageError

    if game.seed is None:
        raise CommandError("This world type has no seed")

    return [(f"Seed: [{game.seed}]", GRAY)]
