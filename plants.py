"""Растения: цветы (роза и одуванчик) и саженцы дуба, берёзы и ели.

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
}
FLOWERS = {"rose", "dandelion"}
SAPLINGS = {"oak_sapling", "birch_sapling", "spruce_sapling"}

NAMES = {
    "rose": "Rose",
    "dandelion": "Dandelion",
    "oak_sapling": "Oak Sapling",
    "birch_sapling": "Birch Sapling",
    "spruce_sapling": "Spruce Sapling",
}

# На чём растения стоят.
GROUND = {"grass", "dirt", "snowy_grass"}

# Коробки для луча и трещин (ось Y вниз, низ клетки это y = 1).
FLOWER_BOX = ((0.3, 0.4, 0.3), (0.7, 1.0, 0.7))
SAPLING_BOX = ((0.1, 0.2, 0.1), (0.9, 1.0, 0.9))

# Плоскости креста чуть короче диагонали клетки.
CROSS_INSET = 0.05

# Рост: в среднем через столько секунд при свете не ниже GROW_LIGHT.
GROW_TIME = 300.0
GROW_LIGHT = 9

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
    return FLOWER_BOX if block_type in FLOWERS else SAPLING_BOX


def plant_texture(block_type):
    return BLOCK_TEXTURES + PLANTS[block_type]


def can_stand_on(ground):
    return ground is not None and ground.type in GROUND


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
