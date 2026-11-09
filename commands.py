"""Команды чата. Строка "/give apple 5" превращается в вызов give(game, ["apple", "5"]).

Координаты в командах как в оригинале: x, y вверх (высота ног), z. В самом мире
ось Y направлена вниз, перевод делают player_position и teleport у игры.
Каждая команда возвращает список ответов (текст, цвет) для ленты чата.
"""
from typing import Callable, NamedTuple

import structures
from chat import GRAY, RED, YELLOW
from door import OPPOSITE
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

    return [(f"Teleported {game.player_name} to {format_position(x, y, z)}", GRAY)]


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

    return [(f"Gave {given} [{item_name(item)}] to {game.player_name}", GRAY)]


@command("kill", "/kill", "Kill yourself")
def kill(game, args):
    if args:
        raise UsageError

    game.kill_player()

    return [(f"Killed {game.player_name}", GRAY)]


@command("clear", "/clear", "Empty your inventory")
def clear(game, args):
    if args:
        raise UsageError

    removed = sum(stack.count for stack in game.inventory.slots + game.inventory.armor if stack is not None)
    game.inventory.slots[:] = [None] * len(game.inventory.slots)
    game.inventory.armor[:] = [None] * len(game.inventory.armor)

    if removed == 0:
        raise CommandError(f"No items were found on player {game.player_name}")

    return [(f"Cleared the inventory of {game.player_name}, removing {removed} items", GRAY)]


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


@command("time", "/time <set|add> <value>", "Set or advance the time of day")
def time_command(game, args):
    if len(args) != 2 or args[0].lower() not in ("set", "add"):
        raise UsageError

    if game.is_client:
        raise CommandError("Only the host can change the time")

    if not args[1].isdigit():
        raise CommandError(f"Invalid number '{args[1]}'")

    value = int(args[1])

    if args[0].lower() == "set":
        game.set_time(value)
        return [(f"Set the time to {value}", GRAY)]

    game.set_time(game.world.time + value)
    return [(f"Added {value} to the time", GRAY)]


# Правила мира: имя как в оригинале -> атрибут игры. Пока одно.
GAME_RULES = {"keepinventory": ("keepInventory", "keep_inventory")}


@command("gamerule", "/gamerule <rule> [true|false]", "Show or change a game rule")
def gamerule(game, args):
    if not 1 <= len(args) <= 2:
        raise UsageError

    rule = GAME_RULES.get(args[0].lower())

    if rule is None:
        raise CommandError(f"Unknown game rule '{args[0]}'")

    name, attribute = rule

    if len(args) == 1:
        return [(f"{name} = {str(getattr(game, attribute)).lower()}", GRAY)]

    if game.is_client:
        raise CommandError("Only the host can change game rules")

    value = args[1].lower()

    if value not in ("true", "false"):
        raise CommandError(f"Invalid value '{args[1]}', expected true or false")

    game.set_game_rule(name, value == "true")

    return [(f"Game rule {name} has been updated to {value}", GRAY)]


@command("list", "/list", "Show players in this world")
def list_players(game, args):
    if args:
        raise UsageError

    names = [game.player_name]

    if game.net is not None:
        names += [player.name for player in game.net.players.values() if player.joined]

    return [(f"There are {len(names)} players online: {', '.join(names)}", GRAY)]


def block_text(cell):
    """Клетка блока в координатах команд: y вверх, блок под ногами на единицу ниже ног."""
    x, y, z = cell

    return f"{x}, {-y - 1}, {z}"


def looked_at(game):
    """Блок под прицелом и пустая клетка перед ним."""
    hit, before = game.world.raycast(game.camera.position, game.camera.forward(), game.reach)

    if hit is None:
        raise CommandError("Look at a block first")

    return hit, before


@command("structure", "/structure <pos1|pos2|save|place|list> [name]", "Save a building as a template, place it")
def structure(game, args):
    if not args:
        raise UsageError

    action = args[0].lower()

    if game.survival and action != "list":
        raise CommandError("Structures can be saved and placed only in Creative Mode")

    if action in ("pos1", "pos2"):
        if len(args) != 1:
            raise UsageError

        hit, _ = looked_at(game)
        game.structure_corners[action] = hit

        return [(f"Corner {action[-1]} set to {block_text(hit)}", GRAY)]

    if action == "list":
        found = structures.names()

        if not found:
            return [("No structures saved yet", GRAY)]

        return [(f"Structures ({len(found)}): {', '.join(found)}", GRAY)]

    if len(args) != 2:
        raise UsageError

    name = args[1].lower()

    try:
        structures.check_name(name)
    except ValueError as error:
        raise CommandError(str(error))

    if action == "save":
        corners = game.structure_corners

        if "pos1" not in corners or "pos2" not in corners:
            raise CommandError("Set both corners first: look at a block and type /structure pos1, then pos2")

        # Игрок стоит перед входом и смотрит на постройку: лицо обращено к нему.
        front = OPPOSITE[structures.side_of(game.camera.forward())]

        try:
            template = structures.capture(game.world, corners["pos1"], corners["pos2"], name, front)
        except ValueError as error:
            raise CommandError(str(error))

        replaced = name in structures.names()
        structures.save(template)
        size_x, size_y, size_z = template.size

        return [(
            f"{'Replaced' if replaced else 'Saved'} structure '{name}' ({size_x}x{size_y}x{size_z}), entrance faces {front}",
            YELLOW,
        )]

    if action == "place":
        try:
            template = structures.load(name)
        except ValueError as error:
            raise CommandError(str(error))

        hit, _ = looked_at(game)
        # Вход к игроку; нижний слой (пол) встаёт на место блока под прицелом.
        side = OPPOSITE[structures.side_of(game.camera.forward())]
        template = template.facing(side)
        size_x, size_y, size_z = template.size
        origin = (hit[0] - size_x // 2, hit[1] - (size_y - 1), hit[2] - size_z // 2)

        game.place_structure(template, origin)

        return [(f"Placed structure '{name}' at {block_text(hit)}, entrance faces {side}", GRAY)]

    raise UsageError
