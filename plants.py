"""Растения: цветы (роза и одуванчик), саженцы дуба, берёзы и ели, адский нарост
и тростник.

Тростник растёт у воды: на траве, земле или песке, рядом с которыми по
бокам есть вода, или на другом тростнике. Сам дорастает до трёх блоков, а без
воды рядом или без опоры ломается.

Растения рисуются крестом из двух плоскостей, сквозь них ходят, и стоят они
только на траве или земле. Цветы растут на равнинах и в лесах при генерации
мира, саженцы выпадают из листвы. Саженец со временем, если ему светло,
вырастает в дерево своей породы, если над ним хватает места.
"""
import random

BLOCK_TEXTURES = "assets/minecraft/textures/block/"

# Тип растения -> картинка в ресурс-паке.
PLANTS = {
    "rose": "poppy.png",
    "dandelion": "dandelion.png",
    "oak_sapling": "oak_sapling.png",
    "birch_sapling": "birch_sapling.png",
    "spruce_sapling": "spruce_sapling.png",
    # Адский нарост растёт в три стадии; предмет и спелый куст называются одинаково.
    "nether_wart_stage0": "nether_wart_stage0.png",
    "nether_wart_stage1": "nether_wart_stage1.png",
    "nether_wart": "nether_wart_stage2.png",
    "sugar_cane": "sugar_cane.png",
}
CANE = "sugar_cane"
CANE_GROUND = {"grass", "dirt", "sand"}
# Тростник дорастает до стольких блоков, новый блок в среднем за столько секунд.
CANE_HEIGHT = 3
CANE_GROW_TIME = 600.0
CANE_BOX = ((0.125, 0.0, 0.125), (0.875, 1.0, 0.875))
FLOWERS = {"rose", "dandelion"}
WART_STAGES = ("nether_wart_stage0", "nether_wart_stage1", "nether_wart")
WARTS = set(WART_STAGES)
# Что ставится в мир из предмета, если не он сам.
PLACED = {"nether_wart": "nether_wart_stage0"}
SAPLINGS = {"oak_sapling", "birch_sapling", "spruce_sapling"}

NAMES = {
    "rose": "Rose",
    "dandelion": "Dandelion",
    "oak_sapling": "Oak Sapling",
    "birch_sapling": "Birch Sapling",
    "spruce_sapling": "Spruce Sapling",
    "nether_wart": "Nether Wart",
    "sugar_cane": "Sugar Canes",
}

# На чём растения стоят. Нарост только на песке душ.
GROUND = {"grass", "dirt", "snowy_grass"}
WART_GROUND = {"soul_sand"}

# Коробки для луча и трещин (ось Y вниз, низ клетки это y = 1).
FLOWER_BOX = ((0.3, 0.4, 0.3), (0.7, 1.0, 0.7))
SAPLING_BOX = ((0.1, 0.2, 0.1), (0.9, 1.0, 0.9))

# Плоскости креста чуть короче диагонали клетки.
CROSS_INSET = 0.05

# Рост: в среднем через столько секунд при свете не ниже GROW_LIGHT.
GROW_TIME = 300.0
GROW_LIGHT = 9
# Нарост растёт в темноте и в любом измерении: стадия в среднем за столько секунд.
WART_GROW_TIME = 120.0
# Спелый нарост даёт столько наростов, незрелый один.
WART_HARVEST = (2, 4)

# Дерево из саженца: порода, бревно, листва и высота ствола.
TREES = {
    "oak_sapling": ("oak_log", "oak_leaves", (4, 6)),
    "birch_sapling": ("birch_log", "birch_leaves", (5, 7)),
    "spruce_sapling": ("spruce_log", "spruce_leaves", (6, 9)),
}

# Из листвы иногда выпадает саженец своей породы, как в оригинале.
SAPLING_DROPS = {
    "oak_leaves": "oak_sapling",
    "birch_leaves": "birch_sapling",
    "spruce_leaves": "spruce_sapling",
}
SAPLING_CHANCE = 1 / 20


def is_plant(block_type):
    return block_type in PLANTS


def plant_box(block_type):
    if block_type == CANE:
        return CANE_BOX

    return FLOWER_BOX if block_type in FLOWERS else SAPLING_BOX


def cane_supported(world, x, y, z):
    """Может ли стоять тростник в клетке: на тростнике или на земле у воды (ось Y вниз)."""
    below = world.get_block(x, y + 1, z)

    if below is None:
        return False

    if below.type == CANE:
        return True

    if below.type not in CANE_GROUND:
        return False

    return any(
        (side := world.get_block(x + dx, y + 1, z + dz)) is not None and side.type == "water"
        for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1))
    )


def cane_height(world, x, y, z):
    """Сколько блоков тростника в столбике до клетки (x, y, z) включительно, снизу."""
    count = 0

    while (block := world.get_block(x, y, z)) is not None and block.type == CANE:
        count += 1
        y += 1

    return count


def plant_texture(block_type):
    return BLOCK_TEXTURES + PLANTS[block_type]


def placed_type(item):
    """Блок, который появляется в мире из предмета растения."""
    return PLACED.get(item, item)


def can_stand_on(ground, plant=None):
    if ground is None:
        return False

    return ground.type in (WART_GROUND if plant in WARTS else GROUND)


def next_stage(block_type):
    """Следующая стадия нароста или None у спелого."""
    if block_type not in WARTS or block_type == WART_STAGES[-1]:
        return None

    return WART_STAGES[WART_STAGES.index(block_type) + 1]


def wart_harvest(block_type, rng=random):
    return rng.randint(*WART_HARVEST) if block_type == WART_STAGES[-1] else 1


def grow_tree(world, x, y, z, sapling, rng=random):
    """Выращивает дерево из саженца в клетке (x, y, z). Ось Y вниз.

    Возвращает изменённые клетки или None, если над саженцем не хватает места.
    """
    # block сам импортирует этот модуль, поэтому Block берём здесь.
    from block import Block

    log, leaves, (low, high) = TREES[sapling]
    height = rng.randint(low, high)
    ground = y + 1

    # Ствол растёт вверх (y меньше) от клетки саженца; там должно быть пусто.
    trunk = [(x, ground - step, z) for step in range(1, height + 1)]

    for cell in trunk[1:]:
        if world.get_block(*cell) is not None:
            return None

    changed = []

    def put(cell, block_type, replace=False):
        current = world.get_block(*cell)

        if replace or current is None:
            world.set_block(*cell, Block(block_type))
            changed.append(cell)

    top = ground - height

    if sapling == "spruce_sapling":
        spruce_crown(put, x, ground, z, height, leaves)
    else:
        round_crown(put, x, top, z, leaves, rng)

    for cell in trunk:
        put(cell, log, replace=True)

    # Под деревом земля, а не трава, как в оригинале.
    below = world.get_block(x, ground, z)

    if below is not None and below.type in ("grass", "snowy_grass"):
        world.set_block(x, ground, z, Block("dirt"))
        changed.append((x, ground, z))

    return changed


def round_crown(put, x, top, z, leaves, rng):
    """Крона дуба и берёзы: два широких слоя, узкий у верхушки и крестик над ней."""
    for y, radius in ((top + 2, 2), (top + 1, 2), (top, 1), (top - 1, 1)):
        for dx in range(-radius, radius + 1):
            for dz in range(-radius, radius + 1):
                if abs(dx) == radius and abs(dz) == radius:
                    if radius == 1 and y == top - 1:
                        continue

                    # Углы широких слоёв то есть, то нет.
                    if rng.random() < 0.5:
                        continue

                put((x + dx, y, z + dz), leaves)


def spruce_crown(put, x, ground, z, height, leaves):
    """Крона ели: ярусы, каждый книзу шире, а под ними голый ствол."""
    top = ground - height
    widest = 2 if height < 8 else 3
    bare = 1 + height % 2
    radius, peak = 0, 1

    for y in range(top - 1, ground - bare):
        for dx in range(-radius, radius + 1):
            for dz in range(-radius, radius + 1):
                if radius > 0 and abs(dx) == radius and abs(dz) == radius:
                    continue

                put((x + dx, y, z + dz), leaves)

        if radius < peak:
            radius += 1
        else:
            peak = min(peak + 1, widest)
            radius = 1
