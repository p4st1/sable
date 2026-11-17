"""Взрыв, как в 1.0: огненный шар гаста и кровать в аду.

Из центра расходятся лучи к поверхности куба 16 x 16 x 16. У каждого луча
своя сила (мощность взрыва x 0.7..1.3), она тает с каждым шагом в 0.3 блока
и тем быстрее, чем прочнее блок на пути. Пока сила есть, блок на пути
разрушается. Камень и кирпич держат удар, адский камень нет, обсидиан и
коренную породу взрыв не берёт, жидкость гасит луч.

Тела рядом получают урон по тому, насколько они близко и насколько их видно
из центра взрыва, и их отбрасывает. Огненный взрыв поджигает пустые клетки
над твёрдыми блоками с шансом в треть.
"""
import math

from mining import HARDNESS

# Взрывостойкость: сколько силы луча съедает блок. По умолчанию это его
# твёрдость, у каменных блоков больше (как setResistance в оригинале).
RESISTANCE = {
    "stone": 6.0, "cobblestone": 6.0, "bricks": 6.0, "nether_bricks": 6.0,
    "obsidian": 1200.0, "bedrock": 3600000.0,
    "water": 60.0, "lava": 60.0,
    "coal_ore": 3.0, "iron_ore": 3.0, "gold_ore": 3.0, "diamond_ore": 3.0,
    "oak_planks": 3.0, "birch_planks": 3.0, "spruce_planks": 3.0,
    "sandstone": 0.8, "furnace": 3.5, "chest": 2.5, "crafting_table": 2.5,
    "nether_portal": 0.0, "fire": 0.0,
    "stone_bricks": 6.0, "cobblestone_stairs": 6.0, "oak_stairs": 3.0, "oak_fence": 3.0,
    "mossy_stone_bricks": 6.0, "cracked_stone_bricks": 6.0, "brick_stairs": 6.0, "stone_brick_stairs": 6.0,
    "fence_gate": 3.0,
    "bookshelf": 1.5,
    "gold_block": 6.0, "iron_block": 6.0, "diamond_block": 6.0, "iron_bars": 6.0,
    "stone_slab": 6.0, "double_stone_slab": 6.0, "cobblestone_slab": 6.0, "double_cobblestone_slab": 6.0,
    "brick_slab": 6.0, "double_brick_slab": 6.0, "stone_brick_slab": 6.0, "double_stone_brick_slab": 6.0,
    "oak_slab": 3.0, "double_oak_slab": 3.0,
}
DEFAULT_RESISTANCE = 1.0

STEP = 0.3
GRID = 16
# Доля разрушенных блоков, что выпадает предметом.
DROP_CHANCE = 0.3
FIRE_CHANCE = 1 / 3


def resistance(block):
    if block is None:
        return 0.0

    return RESISTANCE.get(block.type, HARDNESS.get(block.type, DEFAULT_RESISTANCE))


def ray_directions():
    """Лучи к клеткам на поверхности куба GRID x GRID x GRID."""
    directions = []

    for i in range(GRID):
        for j in range(GRID):
            for k in range(GRID):
                if not (i in (0, GRID - 1) or j in (0, GRID - 1) or k in (0, GRID - 1)):
                    continue

                vector = (i / (GRID - 1) * 2 - 1, j / (GRID - 1) * 2 - 1, k / (GRID - 1) * 2 - 1)
                length = math.sqrt(sum(value * value for value in vector))
                directions.append(tuple(value / length for value in vector))

    return directions


DIRECTIONS = ray_directions()


def affected_cells(world, center, power, rng):
    """Клетки, до которых дошла сила взрыва (и пустые тоже: там может вспыхнуть огонь)."""
    cells = set()
    get_block = world.get_block

    for dx, dy, dz in DIRECTIONS:
        strength = power * (0.7 + rng.random() * 0.6)
        x, y, z = center

        while strength > 0:
            cell = (math.floor(x), math.floor(y), math.floor(z))
            block = get_block(*cell)

            if block is not None:
                strength -= (resistance(block) + 0.3) * STEP

            if strength > 0:
                cells.add(cell)

            x += dx * STEP
            y += dy * STEP
            z += dz * STEP
            strength -= STEP * 0.75

    return cells


def exposure(world, center, low, high):
    """Какая доля тела видна из центра взрыва: лучи к углам и середине коробки."""
    points = [
        (low[0] if i else high[0], low[1] if j else high[1], low[2] if k else high[2])
        for i in (0, 1) for j in (0, 1) for k in (0, 1)
    ]
    points.append(tuple((low[axis] + high[axis]) / 2 for axis in range(3)))
    seen = 0

    for point in points:
        # Чуть внутрь тела, чтобы луч не упирался в блок, на котором оно стоит.
        target = tuple(point[axis] * 0.9 + (low[axis] + high[axis]) / 2 * 0.1 for axis in range(3))
        distance = math.dist(center, target)

        if distance < 1e-6:
            seen += 1
            continue

        direction = tuple((target[axis] - center[axis]) / distance for axis in range(3))
        cell, _ = world.raycast(center, direction, distance)

        if cell is None:
            seen += 1

    return seen / len(points)


def impact(world, center, power, low, high):
    """Сила удара по телу 0..1 и направление от взрыва к нему, или None, если далеко."""
    middle = tuple((low[axis] + high[axis]) / 2 for axis in range(3))
    distance = math.dist(center, middle)
    reach = power * 2

    if distance >= reach:
        return None

    strength = (1 - distance / reach) * exposure(world, center, low, high)

    if strength <= 0:
        return None

    direction = tuple((middle[axis] - center[axis]) / (distance or 1.0) for axis in range(3))

    return strength, direction


def damage_for(strength, power):
    """Урон по формуле оригинала."""
    return int((strength * strength + strength) / 2 * 8 * power + 1)
