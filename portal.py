"""Портал в ад, как в 1.0: рамка из обсидиана 4 x 5 с проёмом 2 x 3.

Огниво внутри пустой рамки зажигает портал: проём заполняется блоками портала,
повёрнутыми вдоль рамки. Постоявший в портале переносится в другое измерение
(см. Game.travel). Блок портала держится, пока вокруг него в плоскости рамки
портал или обсидиан; стоит выбить один блок рамки, и гаснет весь портал.

Порталы обоих измерений записаны в мире (Portals): так при переходе быстро
находится ближайший портал на той стороне, без перебора тысяч чанков. Если
рядом его нет, он строится там, где есть место, или на обсидиановой площадке.

Ось Y направлена вниз: пол рамки в y, проём над ним в y - 1 .. y - 3.
"""
import math
from typing import NamedTuple

import numpy as np

PORTAL = "nether_portal"
PORTAL_TEXTURE = "generated:nether_portal"
PORTAL_FRAMES = "assets/minecraft/textures/block/nether_portal.png"
FRAME = "obsidian"

# Проём рамки: ширина и высота, как в 1.0 (рамка ровно 4 x 5 вместе с углами).
WIDTH = 2
HEIGHT = 3

# Толщина пластины портала: 4/16 посередине клетки.
THICKNESS = 4 / 16
LOW = (1 - THICKNESS) / 2
HIGH = 1 - LOW

# Ближе этого (по горизонтали в блоках измерения назначения) берём готовый портал.
SEARCH_RADIUS = 128
# Где ищем место под новый портал вокруг точки назначения.
BUILD_RADIUS = 16

# Направление ширины проёма по оси рамки.
ALONG = {"x": (1, 0), "z": (0, 1)}
ACROSS = {"x": (0, 1), "z": (1, 0)}


class PortalState(NamedTuple):
    """axis: вдоль какой оси вытянута пластина ("x" или "z")."""
    axis: str = "x"

    def encode(self):
        return self.axis

    @classmethod
    def decode(cls, text):
        if text not in ALONG:
            raise ValueError(f"неверное состояние портала '{text}'")

        return cls(text)


def portal_box(state):
    if state.axis == "x":
        return ((0.0, 0.0, LOW), (1.0, 1.0, HIGH))

    return ((LOW, 0.0, 0.0), (HIGH, 1.0, 1.0))


def is_portal(block):
    return block is not None and block.type == PORTAL


def is_frame(block):
    return block is not None and block.type == FRAME


def is_open(block):
    """В проёме может быть пусто или гореть огонь от огнива."""
    return block is None or block.type == "fire"


# Рамка.

def interior(left, bottom, axis):
    """Клетки проёма: left — нижняя клетка проёма с меньшей координатой вдоль рамки."""
    dx, dz = ALONG[axis]
    x, z = left

    return [(x + dx * i, bottom - j, z + dz * i) for j in range(HEIGHT) for i in range(WIDTH)]


def frame_cells(left, bottom, axis):
    """Блоки рамки вокруг проёма, без углов (углы в 1.0 не обязательны)."""
    dx, dz = ALONG[axis]
    x, z = left
    cells = []

    for i in range(WIDTH):
        cells.append((x + dx * i, bottom + 1, z + dz * i))
        cells.append((x + dx * i, bottom - HEIGHT, z + dz * i))

    for j in range(HEIGHT):
        cells.append((x - dx, bottom - j, z - dz))
        cells.append((x + dx * WIDTH, bottom - j, z + dz * WIDTH))

    return cells


def find_frame(world, cell):
    """Рамка вокруг клетки cell, где щёлкнули огнивом.

    Возвращает (ось, клетки проёма) или None, если рамки нет или проём занят.
    """
    x, y, z = cell

    if not is_open(world.get_block(x, y, z)):
        return None

    for axis in ("x", "z"):
        dx, dz = ALONG[axis]

        # Опускаемся к полу проёма.
        bottom = y

        for _ in range(HEIGHT - 1):
            if not is_open(world.get_block(x, bottom + 1, z)):
                break

            bottom += 1

        if not is_frame(world.get_block(x, bottom + 1, z)):
            continue

        for shift in range(-(WIDTH - 1), 1):
            left = (x + dx * shift, z + dz * shift)
            cells = interior(left, bottom, axis)

            if cell not in cells:
                continue

            if all(is_open(world.get_block(*inside)) for inside in cells) and all(
                is_frame(world.get_block(*edge)) for edge in frame_cells(left, bottom, axis)
            ):
                return axis, cells

    return None


def light(world, axis, cells):
    """Заполняет проём порталом."""
    from block import Block

    for cell in cells:
        world.set_block(*cell, Block(PORTAL, PortalState(axis)))


def holds(world, cell):
    """Держится ли блок портала: в плоскости рамки вокруг него портал или обсидиан."""
    block = world.get_block(*cell)

    if not is_portal(block):
        return True

    dx, dz = ALONG[block.state.axis]
    x, y, z = cell

    for nx, ny, nz in ((x + dx, y, z + dz), (x - dx, y, z - dz), (x, y - 1, z), (x, y + 1, z)):
        neighbour = world.get_block(nx, ny, nz)

        if not (is_frame(neighbour) or (is_portal(neighbour) and neighbour.state.axis == block.state.axis)):
            return False

    return True


def connected(world, cell):
    """Все блоки портала, связанные с cell в его плоскости."""
    block = world.get_block(*cell)

    if not is_portal(block):
        return []

    dx, dz = ALONG[block.state.axis]
    seen = {cell}
    stack = [cell]

    while stack:
        x, y, z = stack.pop()

        for neighbour in ((x + dx, y, z + dz), (x - dx, y, z - dz), (x, y - 1, z), (x, y + 1, z)):
            if neighbour not in seen and is_portal(world.get_block(*neighbour)):
                seen.add(neighbour)
                stack.append(neighbour)

                # Порталы не бывают огромными: это защита от бесконечного обхода.
                if len(seen) > 64:
                    return sorted(seen)

    return sorted(seen)


def collapse_around(world, cell):
    """После изменения клетки cell: гасит порталы рядом, которым больше не на чем держаться.

    Возвращает погасшие клетки.
    """
    x, y, z = cell
    removed = []

    for nx, ny, nz in ((x, y, z), (x + 1, y, z), (x - 1, y, z), (x, y + 1, z), (x, y - 1, z), (x, y, z + 1), (x, y, z - 1)):
        neighbour = (nx, ny, nz)

        if is_portal(world.get_block(*neighbour)) and not holds(world, neighbour):
            for portal_cell in connected(world, neighbour):
                world.remove_block(*portal_cell)
                removed.append(portal_cell)

    return removed


def bottom_left(world, cell):
    """Нижняя клетка проёма с меньшей координатой: по ней портал записан в Portals."""
    block = world.get_block(*cell)
    dx, dz = ALONG[block.state.axis]
    x, y, z = cell

    while is_portal(world.get_block(x, y + 1, z)):
        y += 1

    while is_portal(world.get_block(x - dx, y, z - dz)):
        x -= dx
        z -= dz

    return (x, y, z)


def arrival_point(left, axis, feet):
    """Где встаёт прибывший: на полу проёма посередине. feet: расстояние от глаз до ног."""
    x, y, z = left
    dx, dz = ALONG[axis]
    gap = 0.001

    return (x + 0.5 + dx * 0.5, y + 1 - feet - gap, z + 0.5 + dz * 0.5)


class Portals:
    """Записанные порталы обоих измерений: {измерение: {(x, y, z): ось}}."""

    def __init__(self, data=None):
        self.places = {}

        if isinstance(data, dict):
            for dimension, cells in data.items():
                if not isinstance(cells, list):
                    continue

                for entry in cells:
                    if (
                        isinstance(entry, list) and len(entry) == 4 and entry[3] in ALONG
                        and all(type(value) is int for value in entry[:3])
                    ):
                        self.places.setdefault(dimension, {})[tuple(entry[:3])] = entry[3]

    def to_json(self):
        return {
            dimension: [[*cell, axis] for cell, axis in sorted(cells.items())]
            for dimension, cells in self.places.items() if cells
        }

    def add(self, dimension, cell, axis):
        self.places.setdefault(dimension, {})[cell] = axis

    def remove(self, dimension, cell):
        self.places.get(dimension, {}).pop(cell, None)

    def nearest(self, dimension, x, y, z, radius=SEARCH_RADIUS):
        """Ближайшие к точке порталы в пределах radius по горизонтали, сначала ближние."""
        found = []

        for cell, axis in self.places.get(dimension, {}).items():
            if abs(cell[0] - x) <= radius and abs(cell[2] - z) <= radius:
                found.append((math.dist(cell, (x, y, z)), cell, axis))

        return [(cell, axis) for _, cell, axis in sorted(found)]


# Место под новый портал.

def find_site(world, x, y, z, y_range, radius=BUILD_RADIUS):
    """Ровное место для рамки рядом с (x, y, z): пол из твёрдых блоков 4 x 3 и
    пустота над ним в 5 блоков. Возвращает (левый нижний угол проёма, ось) или None.

    Мир должен быть загружен в радиусе radius + 2. y_range: допустимые y пола рамки.
    """
    from chunk import Chunk, Y_MIN
    from block import PALETTE

    size = Chunk.SIZE
    low_x, high_x = x - radius - 2, x + radius + 3
    low_z, high_z = z - radius - 2, z + radius + 3
    chunk_xs = range(low_x // size, (high_x - 1) // size + 1)
    chunk_zs = range(low_z // size, (high_z - 1) // size + 1)

    width_x = len(chunk_xs) * size
    width_z = len(chunk_zs) * size
    sample = next(iter(world.chunks.values()), None)

    if sample is None:
        return None

    ids = np.zeros((width_x, sample.ids.shape[1], width_z), dtype=np.uint16)
    present = np.zeros((width_x, width_z), dtype=bool)

    for i, chunk_x in enumerate(chunk_xs):
        for k, chunk_z in enumerate(chunk_zs):
            chunk = world.get_chunk(chunk_x, chunk_z)

            if chunk is not None:
                ids[i * size:(i + 1) * size, :, k * size:(k + 1) * size] = chunk.ids
                present[i * size:(i + 1) * size, k * size:(k + 1) * size] = True

    solid_of = np.array([block is not None and block.is_opaque for block in PALETTE], dtype=bool)
    solid = solid_of[ids]
    air = ids == 0
    base_x = chunk_xs[0] * size
    base_z = chunk_zs[0] * size

    best = None

    for axis in ("x", "z"):
        along = (1, 0) if axis == "x" else (0, 1)
        across = (0, 1) if axis == "x" else (1, 0)
        # Пол рамки в строке r: под ней твёрдое (r + 1), над ней пусто (r .. r - 4).
        good = np.ones((width_x - 4, ids.shape[1] - 6, width_z - 4), dtype=bool)

        for i in range(-1, 3):
            for k in range(-1, 2):
                ox = 1 + along[0] * i + across[0] * k
                oz = 1 + along[1] * i + across[1] * k
                column_solid = solid[ox:ox + width_x - 4, :, oz:oz + width_z - 4]
                column_air = air[ox:ox + width_x - 4, :, oz:oz + width_z - 4]
                column_present = present[ox:ox + width_x - 4, oz:oz + width_z - 4]

                good &= column_present[:, None, :]
                good &= column_solid[:, 6:, :]

                for up in range(5):
                    good &= column_air[:, 5 - up:5 - up + good.shape[1], :]

        rows = np.arange(good.shape[1]) + 5 + Y_MIN
        good &= ((rows >= y_range[0]) & (rows <= y_range[1]))[None, :, None]

        candidates = np.argwhere(good)

        if len(candidates) == 0:
            continue

        cx = candidates[:, 0] + 1 + base_x
        cy = candidates[:, 1] + 5 + Y_MIN
        cz = candidates[:, 2] + 1 + base_z
        inside = (np.abs(cx - x) <= radius) & (np.abs(cz - z) <= radius)

        if not inside.any():
            continue

        distance = (cx - x) ** 2 + ((cy - y) * 2) ** 2 + (cz - z) ** 2
        distance = np.where(inside, distance, np.iinfo(np.int64).max)
        index = int(np.argmin(distance))

        if best is None or distance[index] < best[0]:
            best = (int(distance[index]), (int(cx[index]), int(cy[index]), int(cz[index])), axis)

    if best is None:
        return None

    # Найден пол рамки в (x, y, z): проём начинается строкой выше.
    _, (fx, fy, fz), axis = best

    return (fx, fy - 1, fz), axis


def build(world, left, axis, platform=False):
    """Строит рамку и зажигает портал. left: нижняя клетка проёма с меньшей координатой.

    platform: под рамкой и по бокам от неё обсидиановый пол, а вокруг расчищено место,
    как в оригинале, когда подходящего места не нашлось. Возвращает изменённые клетки.
    """
    from block import Block

    dx, dz = ALONG[axis]
    ax, az = ACROSS[axis]
    x, bottom, z = left
    changed = []

    def put(cell, block):
        world.set_block(*cell, block)
        changed.append(cell)

    if platform:
        for i in range(-1, WIDTH + 1):
            for k in (-1, 1):
                base = (x + dx * i + ax * k, z + dz * i + az * k)
                put((base[0], bottom + 1, base[1]), Block(FRAME))

                for j in range(HEIGHT + 1):
                    cell = (base[0], bottom - j, base[1])

                    if world.get_block(*cell) is not None:
                        world.remove_block(*cell)
                        changed.append(cell)

    for cell in frame_cells((x, z), bottom, axis):
        put(cell, Block(FRAME))

    # Углы рамки тоже из обсидиана: так она выглядит как построенная в оригинале.
    for i in (-1, WIDTH):
        put((x + dx * i, bottom + 1, z + dz * i), Block(FRAME))
        put((x + dx * i, bottom - HEIGHT, z + dz * i), Block(FRAME))

    cells = interior((x, z), bottom, axis)
    light(world, axis, cells)
    changed += cells

    return changed
