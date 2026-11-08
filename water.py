"""Жидкости (вода и лава): растекание по тикам и меш поверхности. Ось Y направлена вниз.

Лава течёт по тем же правилам, что и вода, но как в оригинале медленнее (тик
раз в 1.5 секунды), на шаг уровень растёт на 2 (поэтому лава уходит всего на
три блока от источника), ищет спуск ближе и новых источников не даёт. Где лава
встречает воду, она застывает: источник в обсидиан, текущая лава в булыжник,
а лава, стекающая на воду, превращает её в камень.

Правила как в оригинале. Источник (уровень 0) стоит сам по себе. Текущая вода
каждый тик пересчитывает уровень от соседей: на единицу больше самого низкого
уровня рядом, а если сверху вода, то она падающая. Без подпитки вода пропадает.
Два источника рядом над опорой дают третий, поэтому лужу 2x1 можно черпать бесконечно.

Вниз вода течёт в первую очередь. В стороны растекается, только когда внизу опора,
и выбирает те стороны, где ближе всего (не дальше SLOPE_DISTANCE) можно стечь вниз.

Обновляются только клетки из world.water_updates: туда их кладёт world.notify, когда
рядом что-то поменялось. Поэтому стоячая вода ничего не стоит.
"""
import math
from typing import NamedTuple

from block import MAX_LEVEL, SOURCE, Block, WaterState, ids_where
from chunk import FACE_SHADE, Chunk, box_face, packed_shades

# Вода в оригинале обновляется раз в 5 тиков.
TICK = 0.25

# Глубже этого (больше y) вода не течёт: водопад с края мира не падает бесконечно.
FLOW_LIMIT_Y = 64

# На столько блоков в сторону вода ищет, где стечь вниз.
SLOPE_DISTANCE = 4

FALLING = WaterState(0, True)

HORIZONTAL = ((1, 0), (-1, 0), (0, 1), (0, -1))

# Сторона клетки, которую закрывает сосед в этом направлении.
SIDE_FACES = {(-1, 0): "left", (1, 0): "right", (0, -1): "back", (0, 1): "front"}

WATER_TEXTURE = "generated:water"
LAVA_TEXTURE = "generated:lava"


class Fluid(NamedTuple):
    name: str
    # Раз в сколько секунд шаг, на сколько уровень растёт за блок, как далеко
    # ищет спуск, дают ли два источника третий, текстура и светится ли сама.
    tick: float
    step: int
    slope: int
    infinite: bool
    texture: str
    bright: bool


WATER = Fluid("water", TICK, 1, SLOPE_DISTANCE, True, WATER_TEXTURE, False)
LAVA = Fluid("lava", 1.5, 2, 2, False, LAVA_TEXTURE, True)
FLUIDS = {"water": WATER, "lava": LAVA}


def is_fluid(block, fluid):
    return block is not None and block.type == fluid.name


def is_lava(block):
    return block is not None and block.type == "lava"


def is_water(block):
    return block is not None and block.type == "water"


def surface_height(world, x, y, z, block):
    """Высота жидкости в клетке от 1/9 до 1. Под той же жидкостью сверху клетка заполнена целиком."""
    above = world.get_block(x, y - 1, z)

    if above is not None and above.type == block.type:
        return 1.0

    level = 0 if block.state.falling else block.state.level

    return (8 - level) / 9


def can_flow_into(world, cell):
    """Пустая клетка внутри мира, куда может попасть вода."""
    x, y, z = cell

    if y > FLOW_LIMIT_Y or world.get_chunk(x // Chunk.SIZE, z // Chunk.SIZE) is None:
        return False

    return world.get_block(x, y, z) is None


def passable(world, cell, fluid=WATER):
    """Клетка, через которую жидкость может течь: пустая или с текущей той же жидкостью."""
    block = world.get_block(*cell)

    if block is None:
        return can_flow_into(world, cell)

    return is_fluid(block, fluid) and not block.state.is_source


def is_drop(world, cell, fluid=WATER):
    x, y, z = cell

    return passable(world, (x, y + 1, z), fluid)


def drop_distance(world, start, origin, fluid=WATER):
    """Сколько шагов по горизонтали от start до места, где можно стечь вниз, или None."""
    if is_drop(world, start, fluid):
        return 0

    frontier = [start]
    seen = {origin, start}

    for distance in range(1, fluid.slope):
        following = []

        for x, y, z in frontier:
            for dx, dz in HORIZONTAL:
                cell = (x + dx, y, z + dz)

                if cell in seen or not passable(world, cell, fluid):
                    continue

                if is_drop(world, cell, fluid):
                    return distance

                seen.add(cell)
                following.append(cell)

        frontier = following

    return None


def flow_directions(world, cell, fluid=WATER):
    """Стороны, куда растекаться: к ближайшему спуску, а если его нет, во все открытые."""
    x, y, z = cell
    open_sides = [
        (dx, dz) for dx, dz in HORIZONTAL
        if passable(world, (x + dx, y, z + dz), fluid)
    ]

    distances = {}

    for dx, dz in open_sides:
        distance = drop_distance(world, (x + dx, y, z + dz), cell, fluid)

        if distance is not None:
            distances[(dx, dz)] = distance

    if not distances:
        return open_sides

    nearest = min(distances.values())

    return [side for side, distance in distances.items() if distance == nearest]


class WaterTick:
    """Один шаг жидкости. Запоминает, какие чанки нужно перестроить."""

    def __init__(self, world, fluid=WATER):
        self.world = world
        self.fluid = fluid
        self.changed_chunks = set()
        # Клетки, поменявшиеся в этом шаге: их очередь в следующем.
        self.touched = set()

    def set(self, cell, state):
        x, y, z = cell

        if state is None:
            self.world.remove_block(x, y, z)
        elif isinstance(state, str):
            # Застывшая лава: обычный блок.
            self.world.set_block(x, y, z, Block(state))
        else:
            self.world.set_block(x, y, z, Block(self.fluid.name, state))

        self.world.notify(x, y, z)
        self.touched.add(cell)

        # От высоты воды зависят боковые грани соседей, и они могут быть в другом чанке.
        for dx, dz in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)):
            self.changed_chunks.add(((x + dx) // Chunk.SIZE, (z + dz) // Chunk.SIZE))

    def run(self, cells):
        for cell in cells:
            if cell in self.touched:
                # Уже поменялась в этом шаге и стоит в очереди на следующий.
                self.queue().add(cell)
                continue

            self.update(cell)

        return self.changed_chunks

    def queue(self):
        return self.world.lava_updates if self.fluid is LAVA else self.world.water_updates

    def update(self, cell):
        block = self.world.get_block(*cell)

        if not is_fluid(block, self.fluid):
            return

        state = block.state

        # Лава у воды застывает.
        if self.fluid is LAVA and self.harden(cell, state):
            return

        if not state.is_source:
            expected = self.expected_state(cell)

            if expected != state:
                self.set(cell, expected)

                if expected is None:
                    return

                state = expected

        self.spread(cell, state)

    def harden(self, cell, state):
        """Лава, которой касается вода (сбоку или сверху): источник в обсидиан, текущая в булыжник."""
        x, y, z = cell
        touching = any(
            is_water(self.world.get_block(x + dx, y + dy, z + dz))
            for dx, dy, dz in ((1, 0, 0), (-1, 0, 0), (0, 0, 1), (0, 0, -1), (0, -1, 0))
        )

        if not touching:
            return False

        if state.is_source:
            self.set(cell, "obsidian")
        elif state.falling or state.level <= 4:
            self.set(cell, "cobblestone")
        else:
            return False

        return True

    def expected_state(self, cell):
        """Каким должен быть уровень текущей жидкости, или None, если ей неоткуда взяться."""
        world = self.world
        fluid = self.fluid
        x, y, z = cell

        if is_fluid(world.get_block(x, y - 1, z), fluid):
            return FALLING

        sources = 0
        lowest = None

        for dx, dz in HORIZONTAL:
            neighbour = world.get_block(x + dx, y, z + dz)

            if not is_fluid(neighbour, fluid):
                continue

            if neighbour.state.is_source:
                sources += 1

            level = 0 if neighbour.state.falling else neighbour.state.level
            lowest = level if lowest is None else min(lowest, level)

        if sources >= 2 and fluid.infinite:
            below = world.get_block(x, y + 1, z)

            if below is not None and (below.is_solid or (below.is_liquid and below.state.is_source)):
                return SOURCE

        if lowest is None or lowest + fluid.step > MAX_LEVEL:
            return None

        return WaterState(lowest + fluid.step)

    def spread(self, cell, state):
        world = self.world
        fluid = self.fluid
        x, y, z = cell
        below = (x, y + 1, z)
        below_block = world.get_block(*below)

        # Лава, стекающая на воду, превращает её в камень.
        if fluid is LAVA and is_water(below_block):
            self.set(below, "stone")
            return

        # Сначала вниз. Пока есть куда падать, в стороны жидкость не идёт.
        if can_flow_into(world, below) or (is_fluid(below_block, fluid) and not below_block.state.is_source):
            if below_block is None or not below_block.state.falling:
                self.set(below, FALLING)

            return

        # Текущая жидкость на поверхности озера в стороны не растекается.
        if is_fluid(below_block, fluid) and not state.is_source:
            return

        level = fluid.step if state.is_source or state.falling else state.level + fluid.step

        if level > MAX_LEVEL:
            return

        for dx, dz in flow_directions(world, cell, fluid):
            target = (x + dx, y, z + dz)
            block = world.get_block(*target)

            if block is None:
                self.set(target, WaterState(level))

            # Падающую жидкость растекание не трогает: она питается сверху.
            elif is_fluid(block, fluid) and not block.state.is_source and not block.state.falling and block.state.level > level:
                self.set(target, WaterState(level))


def tick(world, fluid=WATER):
    """Обрабатывает накопившиеся клетки. Возвращает ключи чанков, где поменялась жидкость."""
    if fluid is LAVA:
        cells, world.lava_updates = world.lava_updates, set()
    else:
        cells, world.water_updates = world.water_updates, set()

    return WaterTick(world, fluid).run(cells)


def add_quad(data, corners, shade=(1.0, 1.0)):
    """Двусторонний четырёхугольник: воду видно и снаружи, и из-под воды.

    UV берутся из координат вершин, поэтому текстура не растягивается и
    стыкуется между соседними клетками. shade: яркость днём и ночью.
    """
    xs = {corner[0] for corner in corners}
    zs = {corner[2] for corner in corners}

    if len(xs) == 1:
        uvs = [(corner[2], corner[1]) for corner in corners]
    elif len(zs) == 1:
        uvs = [(corner[0], corner[1]) for corner in corners]
    else:
        uvs = [(corner[0], corner[2]) for corner in corners]

    start = len(data["points"])
    data["points"].extend(corners)
    data["shades"].extend([shade[0]] * 4)
    data["night_shades"].extend([shade[1]] * 4)

    for a, b, c in ((0, 1, 2), (0, 2, 3), (0, 2, 1), (0, 3, 2)):
        data["triangles"].append((start + a, start + b, start + c))
        data["uvs"].append((uvs[a], uvs[b], uvs[c]))


def shaded(light, face):
    return light[0] * FACE_SHADE[face], light[1] * FACE_SHADE[face]


def build_water_mesh(chunk, world, fluid=WATER):
    """Меш всей жидкости чанка в его локальных координатах или None, если её нет.

    Верх воды склеивается в прямоугольники одной высоты, как жадный меш блоков.
    Грани у соседней воды не рисуются, кроме полоски, где сосед ниже.
    """
    data = {"points": [], "triangles": [], "uvs": [], "shades": [], "night_shades": []}
    base_x = chunk.chunk_x * Chunk.SIZE
    base_z = chunk.chunk_z * Chunk.SIZE

    # Высота верха по слоям: из них потом склеиваются прямоугольники.
    # Яркость у каждой клетки своя, поэтому склеиваются только клетки одной яркости.
    tops = {}

    for (x, y, z), block in chunk.cells(water_ids(fluid)):
        world_x = base_x + x
        world_z = base_z + z
        height = surface_height(world, world_x, y, world_z, block)
        top = y + 1 - height
        # Лава светится сама: полная яркость и днём, и ночью.
        light = (1.0, 1.0) if fluid.bright else packed_shades(chunk.packed_light(x, y, z))

        if height < 1.0:
            tops.setdefault(y, [[None] * Chunk.SIZE for _ in range(Chunk.SIZE)])[x][z] = (height, light)

        below = world.get_block(world_x, y + 1, world_z)

        if below is None or (not is_fluid(below, fluid) and not below.is_opaque):
            add_quad(data, box_face("bottom", (x, top, z), (x + 1, y + 1, z + 1)), shaded(light, "bottom"))

        for (dx, dz), face in SIDE_FACES.items():
            neighbour = world.get_block(world_x + dx, y, world_z + dz)

            if neighbour is not None and neighbour.is_opaque:
                continue

            lower = y + 1

            if is_fluid(neighbour, fluid):
                neighbour_height = surface_height(world, world_x + dx, y, world_z + dz, neighbour)

                if neighbour_height >= height:
                    continue

                # Видна только полоска между нашей поверхностью и поверхностью соседа.
                lower = y + 1 - neighbour_height

            add_quad(data, box_face(face, (x, top, z), (x + 1, lower, z + 1)), shaded(light, face))

    for y, mask in tops.items():
        for x, z, width, depth, (height, light) in chunk.greedy_mask(mask, Chunk.SIZE, Chunk.SIZE):
            top = y + 1 - height
            add_quad(data, box_face("top", (x, top, z), (x + width, y + 1, z + depth)), light)

    return data if data["points"] else None


def water_ids(fluid=WATER):
    """Номера всех встречавшихся состояний жидкости."""
    return ids_where(lambda block: is_fluid(block, fluid))


def settle_chunk(world, chunk):
    """Текущая вода чанка из сохранения: после загрузки она дотекает, куда не успела."""
    flowing = ids_where(lambda block: is_water(block) and not block.state.is_source)

    if not flowing:
        return

    for (x, y, z), block in chunk.cells(flowing):
        world.water_updates.add((chunk.chunk_x * Chunk.SIZE + x, y, chunk.chunk_z * Chunk.SIZE + z))


def water_cells_to_settle(world):
    for chunk in world.chunks.values():
        settle_chunk(world, chunk)


def body_in_water(world, low, high, fluid=WATER):
    """Касается ли коробка от low до high жидкости (с учётом высоты её поверхности)."""
    for x in range(math.floor(low[0]), math.ceil(high[0])):
        for y in range(math.floor(low[1]), math.ceil(high[1])):
            for z in range(math.floor(low[2]), math.ceil(high[2])):
                block = world.get_block(x, y, z)

                if is_fluid(block, fluid) and high[1] > y + 1 - surface_height(world, x, y, z, block):
                    return True

    return False


def point_in_water(world, position, fluid=WATER):
    """Находится ли точка под поверхностью жидкости. Для глаз: подводный туман и воздух."""
    x, y, z = (math.floor(value) for value in position)
    block = world.get_block(x, y, z)

    return is_fluid(block, fluid) and position[1] > y + 1 - surface_height(world, x, y, z, block)
