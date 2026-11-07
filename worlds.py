"""Типы миров: бесконечный мир из генератора и тестовые площадки.

Быстрый вход минуя меню: python main.py hills [--new] или python main.py default --new.
"""
import math
from typing import Callable, NamedTuple

from block import Block
from chunk import Chunk

NEW_FLAG = "--new"


class TestWorld(NamedTuple):
    description: str
    generate: Callable
    position: tuple
    rotation: tuple
    flying: bool = False
    # Блок, которым мир изображён в списке миров.
    icon: str = "grass"
    # Бесконечный мир: чанки строит terrain.TerrainGenerator по мере надобности,
    # а generate, position и rotation не нужны.
    infinite: bool = False


def fill_columns(world, radius, column):
    """Заполняет квадрат чанков. column(x, z) возвращает пары (y, тип блока)."""
    for chunk_x in range(-radius, radius):
        for chunk_z in range(-radius, radius):
            chunk = Chunk(chunk_x, chunk_z)

            for x in range(Chunk.SIZE):
                for z in range(Chunk.SIZE):
                    world_x = chunk_x * Chunk.SIZE + x
                    world_z = chunk_z * Chunk.SIZE + z

                    for y, block_type in column(world_x, world_z):
                        chunk.set_block(x, y, z, Block(block_type))

            world.add_chunk(chunk)


def one_block(world):
    chunk = Chunk(0, 0)
    chunk.set_block(0, -1, 0, Block("grass"))
    world.add_chunk(chunk)


def flat_column(x, z):
    return [(0, "grass")]


STONE_LAYERS = 3
TREE_SPACING = 7
TREE_MARGIN = 3

# Уровень воды в холмах: низины ниже него (больший y) заливаются прудами.
SEA_LEVEL = 1


def hills_top(x, z):
    return int(2 * math.sin(x * 0.35) + 2 * math.cos(z * 0.3))


def hills_column(x, z):
    """Трава, два слоя земли и камень под ними. Ось Y направлена вниз.

    В низинах ниже SEA_LEVEL пруд: вода до уровня, а дно из песка.
    """
    top = hills_top(x, z)
    underwater = top > SEA_LEVEL

    return [(y, "water") for y in range(SEA_LEVEL, top)] + [
        (top, "sand" if underwater else "grass"),
        (top + 1, "dirt"),
        (top + 2, "dirt"),
    ] + [(top + 3 + depth, "stone") for depth in range(STONE_LAYERS)]


def noise(x, z):
    """Одинаковое для одних и тех же координат псевдослучайное число."""
    return ((x * 73856093) ^ (z * 19349663) ^ 0x5bd1e995) & 0xffff


def grow_tree(world, x, ground, z, height):
    """Дуб: ствол из брёвен и шапка листвы. ground — y травы под деревом."""
    top = ground - height

    for y in range(ground - 1, top - 1, -1):
        world.set_block(x, y, z, Block("oak_log"))

    # Как у дуба в оригинале: два широких слоя на третьем и втором блоке от верха
    # ствола, узкий слой у самой верхушки и крестик над ней. Ось Y вниз, так что
    # top + 2 это на два блока ниже верхнего бревна.
    for y, radius in ((top + 2, 2), (top + 1, 2), (top, 1), (top - 1, 1)):
        for dx in range(-radius, radius + 1):
            for dz in range(-radius, radius + 1):
                corner = abs(dx) == radius and abs(dz) == radius

                if corner and (radius == 1 and y == top - 1 or noise(x + dx * 7, z + dz * 13 + y) % 2):
                    continue

                if world.get_block(x + dx, y, z + dz) is None:
                    world.set_block(x + dx, y, z + dz, Block("oak_leaves"))


def plant_trees(world, radius):
    """Деревья примерно через TREE_SPACING блоков, со случайным сдвигом и пропусками."""
    limit = radius * Chunk.SIZE - TREE_MARGIN

    for grid_x in range(-limit, limit, TREE_SPACING):
        for grid_z in range(-limit, limit, TREE_SPACING):
            value = noise(grid_x, grid_z)

            if value % 10 < 4:
                continue

            x = grid_x + value % 3
            z = grid_z + value // 3 % 3

            # Деревья не растут из воды.
            if x < limit and z < limit and hills_top(x, z) <= SEA_LEVEL:
                grow_tree(world, x, hills_top(x, z), z, 4 + value // 9 % 3)


def hills(radius):
    def generate(world):
        fill_columns(world, radius, hills_column)
        plant_trees(world, radius)

    return generate


def checker_column(x, z):
    if (x + z) % 2 == 0:
        return [(0, "grass")]

    return []


def towers_column(x, z):
    column = [(1, "grass")]

    if x % 8 < 3 and z % 8 < 3:
        height = 8 + (x // 8 * 7 + z // 8 * 13) % 33
        column += [(-y, "netherrack") for y in range(height)]

    return column


def mixed_column(x, z):
    types = ("grass", "dirt", "netherrack", "danilEfail")
    index = (x // 4 + z // 4) % len(types)

    return [(-y, types[index]) for y in range(index + 1)]


WORLDS = {
    "default": TestWorld(
        "бесконечный мир: биомы, реки, горы, пещеры и руды",
        None,
        (0, 0, 0),
        (0, 0, 0),
        infinite=True
    ),
    "block": TestWorld(
        "один блок",
        one_block,
        (0.5, -0.5, -3),
        (0, 0, 0),
        flying=True
    ),
    "flat": TestWorld(
        "ровная площадка 4x4 чанка, минимум треугольников",
        lambda world: fill_columns(world, 2, flat_column),
        (0, -6, -40),
        (-0.2, 0, 0)
    ),
    "hills": TestWorld(
        "холмы 6x6 чанков с деревьями, обычная нагрузка",
        hills(3),
        (0, -14, -40),
        (-0.35, 0, 0)
    ),
    "checker": TestWorld(
        "шахматка 4x4 чанка, greedy-мешинг не помогает",
        lambda world: fill_columns(world, 2, checker_column),
        (0, -8, -40),
        (-0.3, 0, 0)
    ),
    "towers": TestWorld(
        "башни до 40 блоков, проверка отсечения по высоте",
        lambda world: fill_columns(world, 2, towers_column),
        (0, -20, -50),
        (-0.1, 0, 0),
        icon="netherrack"
    ),
    "mixed": TestWorld(
        "все типы блоков, несколько текстур в чанке",
        lambda world: fill_columns(world, 1, mixed_column),
        (0, -8, -24),
        (-0.3, 0, 0),
        icon="danilEfail"
    ),
    "big": TestWorld(
        "холмы 16x16 чанков с деревьями, стресс-тест",
        hills(8),
        (0, -14, -120),
        (-0.2, 0, 0)
    ),
}


def find_world(answer):
    """Ищет мир по названию или номеру в списке."""
    names = list(WORLDS)
    answer = answer.strip().lower()

    if answer in WORLDS:
        return answer

    if answer.isdigit() and 1 <= int(answer) <= len(names):
        return names[int(answer) - 1]

    return None


def parse_arguments(arguments):
    """Возвращает мир из командной строки (или None для главного меню) и нужен ли --new."""
    new_world = NEW_FLAG in arguments
    names = [argument for argument in arguments if argument != NEW_FLAG]

    if not names:
        return None, False

    name = find_world(names[0])

    if name is None:
        print(f"Мир '{names[0]}' не найден. Доступные миры:")

        for number, (world_name, world) in enumerate(WORLDS.items(), 1):
            print(f"  {number}. {world_name:8} {world.description}")

        raise SystemExit(1)

    return name, new_world
