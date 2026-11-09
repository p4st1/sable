"""Огонь как в 1.0: зажигается огнивом, перекидывается на горючие блоки и гаснет.

Каждый огонь живёт по своим тикам (раз в 1.5-2 секунды). С каждым тиком он
стареет. Горючие соседи (доски, брёвна, листва, шерсть) с некоторым шансом
сгорают: исчезают или сами загораются. В пустые клетки рядом с горючим, в
том числе до четырёх блоков вверх, огонь перекидывается тем охотнее, чем он
моложе и чем горючее соседи. Без горючего рядом старый огонь гаснет, а на
адском камне горит вечно.

Числа (насколько блок разжигает огонь рядом и как легко загорается сам)
взяты из оригинала. Ось Y направлена вниз.
"""
import random

import numpy as np
import pygame

FIRE = "fire"
FIRE_TEXTURE = "generated:fire"
FIRE_FRAMES = "assets/minecraft/textures/block/fire_0.png"
FRAME_RATE = 20

# Блок: (как разжигает огонь рядом, как легко загорается сам).
FLAMMABLE = {
    "oak_planks": (5, 20), "birch_planks": (5, 20), "spruce_planks": (5, 20),
    "oak_log": (5, 5), "birch_log": (5, 5), "spruce_log": (5, 5),
    "oak_leaves": (30, 60), "birch_leaves": (30, 60), "spruce_leaves": (30, 60),
    "white_wool": (30, 60),
    "oak_stairs": (5, 20), "oak_fence": (5, 20),
    # Книжная полка горит, как листва.
    "bookshelf": (30, 20),
    "oak_slab": (5, 20), "double_oak_slab": (5, 20),
}

# На этом огонь не гаснет никогда.
ETERNAL = {"netherrack"}

TICK = 1.5
TICK_SPREAD = 0.5
MAX_AGE = 15

# Шанс сгореть соседу: из этого числа, по бокам и сверху-снизу, как в оригинале.
SIDE_CHANCE = 300
VERTICAL_CHANCE = 250

# Коробка огня для луча: тонкий слой у пола, чтобы щелчок по горящей земле гасил огонь.
BOX = ((0.0, 15 / 16, 0.0), (1.0, 1.0, 1.0))

# Сколько секунд горит тот, кто постоял в огне, и урон раз в секунду.
BURN_TIME = 8.0

SIDES = ((1, 0, 0), (-1, 0, 0), (0, 0, 1), (0, 0, -1), (0, -1, 0), (0, 1, 0))


def is_fire(block):
    return block is not None and block.type == FIRE


def flammability(block):
    return 0 if block is None else FLAMMABLE.get(block.type, (0, 0))[1]


def encouragement(block):
    return 0 if block is None else FLAMMABLE.get(block.type, (0, 0))[0]


def fire_frames():
    """Кадры пламени из ресурс-пака в порядке анимации (файл это столбец квадратов)."""
    image = pygame.image.load(FIRE_FRAMES)
    image = image.convert_alpha() if pygame.display.get_surface() else image
    size = image.get_width()
    count = max(1, image.get_height() // size)

    return [image.subsurface((0, index * size, size, size)).copy() for index in range(count)]


class FireSystem:
    def __init__(self, world, rng=None):
        self.world = world
        self.rng = rng or random.Random()
        # Клетка огня -> (через сколько секунд её следующий тик, возраст).
        self.fires = {}

    # Где огонь может гореть.

    def has_fuel_around(self, cell):
        x, y, z = cell
        return any(flammability(self.world.get_block(x + dx, y + dy, z + dz)) > 0 for dx, dy, dz in SIDES)

    def can_burn_at(self, cell):
        """Огню нужен целый блок снизу или горючий сосед."""
        x, y, z = cell
        below = self.world.get_block(x, y + 1, z)

        return (below is not None and below.is_cube) or self.has_fuel_around(cell)

    def add(self, cell, age=0):
        self.fires[cell] = (TICK + self.rng.random() * TICK_SPREAD, age)

    def ignite(self, cell, age=0):
        """Ставит огонь в пустую клетку. Возвращает True, если загорелось."""
        from block import Block

        if self.world.get_block(*cell) is not None or not self.can_burn_at(cell):
            return False

        self.world.set_block(*cell, Block(FIRE))
        self.add(cell, age)

        return True

    def scan(self, chunk, fire_ids):
        """Огонь в загруженном чанке (из сохранения) тоже начинает жить."""
        if not fire_ids:
            return

        for local_x, row, local_z in np.argwhere(np.isin(chunk.ids, fire_ids)):
            from chunk import Chunk, Y_MIN

            cell = (chunk.chunk_x * Chunk.SIZE + int(local_x), int(row) + Y_MIN, chunk.chunk_z * Chunk.SIZE + int(local_z))
            self.fires.setdefault(cell, (TICK + self.rng.random() * TICK_SPREAD, 0))

    # Тики.

    def update(self, dt, loaded):
        """Шаг огня. loaded(x, z): загружен ли там мир. Возвращает изменённые клетки."""
        changed = []

        for cell, (left, age) in list(self.fires.items()):
            if cell not in self.fires:
                continue

            if not loaded(cell[0], cell[2]):
                continue

            left -= dt

            if left > 0:
                self.fires[cell] = (left, age)
                continue

            changed += self.tick(cell, age)

        return changed

    def tick(self, cell, age):
        world = self.world
        rng = self.rng
        x, y, z = cell

        # Огонь потушили или сломали чем-то другим.
        if not is_fire(world.get_block(*cell)):
            self.fires.pop(cell, None)
            return []

        if not self.can_burn_at(cell):
            return self.put_out(cell)

        below = world.get_block(x, y + 1, z)
        eternal = below is not None and below.type in ETERNAL

        age = min(MAX_AGE, age + rng.randint(0, 2))
        self.fires[cell] = (TICK + rng.random() * TICK_SPREAD, age)

        if not eternal:
            if not self.has_fuel_around(cell):
                if below is None or not below.is_cube or age > 3:
                    return self.put_out(cell)

            elif flammability(below) == 0 and age == MAX_AGE and rng.random() < 0.25:
                return self.put_out(cell)

        changed = []

        # Горючие соседи сгорают или загораются.
        for dx, dy, dz in SIDES:
            chance = VERTICAL_CHANCE if dy else SIDE_CHANCE
            changed += self.catch(x + dx, y + dy, z + dz, chance, age)

        # Пламя перекидывается в пустые клетки рядом с горючим, вверх до четырёх блоков.
        for dx in (-1, 0, 1):
            for dz in (-1, 0, 1):
                for dy in range(-4, 2):
                    if dx == 0 and dy == 0 and dz == 0:
                        continue

                    target = (x + dx, y + dy, z + dz)

                    if world.get_block(*target) is not None:
                        continue

                    # Выше одного блока шанс падает.
                    height = -dy
                    chance = 100 + (height - 1) * 100 if height > 1 else 100
                    heat = max(encouragement(world.get_block(target[0] + sx, target[1] + sy, target[2] + sz)) for sx, sy, sz in SIDES)

                    if heat <= 0:
                        continue

                    spread = (heat + 40) // (age + 30)

                    if spread > 0 and rng.randrange(chance) <= spread:
                        if self.ignite(target, min(MAX_AGE, age + rng.randint(0, 4) // 4)):
                            changed.append(target)

        return changed

    def catch(self, x, y, z, chance, age):
        """Сосед с горючестью сгорает: исчезает или загорается сам."""
        from block import Block

        block = self.world.get_block(x, y, z)

        if self.rng.randrange(chance) >= flammability(block):
            return []

        cell = (x, y, z)

        if self.rng.randrange(age + 10) < 5:
            self.world.set_block(x, y, z, Block(FIRE))
            self.add(cell, min(MAX_AGE, age + self.rng.randint(0, 4) // 4))
        else:
            self.world.remove_block(x, y, z)

        return [cell]

    def put_out(self, cell):
        self.fires.pop(cell, None)
        self.world.remove_block(*cell)

        return [cell]
