"""Адские крепости, как в 1.0: длинные мосты из адского кирпича над морем лавы,
перекрёстки на колоннах, крытые коридоры сквозь камень и залы, где на песке
душ растёт адский нарост. В крепостях появляются ифриты (см. Game.spawn_hostiles).

Крепость задумывается целиком из сида: в каждой области REGION x REGION чанков
крепость есть или нет, и её план (список частей) один и тот же при каждой
постройке. Чанк рисует только то, что попало в его границы, поэтому крепость
сходится из чанков, построенных в любом порядке.

Ось Y направлена вниз: настил моста в y = deck, всё над ним имеет меньший y.
"""
import random
from typing import NamedTuple

from block import type_id
from chunk import Y_MIN, Chunk

SIZE = Chunk.SIZE

# Область в чанках и доля областей с крепостью.
REGION = 16
CHANCE = 0.5
# Крепость начинается не дальше этого от угла области (в чанках).
START_SPREAD = 8

# Высота настила: от этого y вверх ещё на DECK_SPREAD блоков. Море лавы ниже.
DECK_Y = 14
DECK_SPREAD = 14

# Сколько частей в крепости и как далеко она тянется от центра.
MAX_PIECES = 40
MAX_DEPTH = 6
MAX_REACH = 112

BRIDGE_LENGTH = (10, 22)
CROSSING = 7
ROOM = 11
# Опоры под мостом через столько блоков.
PILLAR_STEP = 5

AIR = 0
BRICK, SOUL_SAND, WART, LAVA = (type_id(name) for name in ("nether_bricks", "soul_sand", "nether_wart", "lava"))

DIRECTIONS = ((1, 0), (-1, 0), (0, 1), (0, -1))


class Piece(NamedTuple):
    kind: str
    # Границы по x и z (включительно) и настил.
    x0: int
    z0: int
    x1: int
    z1: int
    deck: int
    # Вдоль какой оси идёт мост или коридор: "x" или "z". У перекрёстка и зала None.
    axis: str = None
    # Стороны перекрёстка и зала, куда есть проход: набор направлений.
    openings: frozenset = frozenset()

    def overlaps(self, other, margin=0):
        return not (
            self.x1 + margin < other.x0 or other.x1 + margin < self.x0
            or self.z1 + margin < other.z0 or other.z1 + margin < self.z0
        )


class Fortress(NamedTuple):
    pieces: tuple
    # Границы всей крепости по x, z и по высоте (для ифритов).
    bounds: tuple


def box(x0, z0, x1, z1):
    return min(x0, x1), min(z0, z1), max(x0, x1), max(z0, z1)


class FortressPlanner:
    def __init__(self, seed):
        self.seed = seed
        self.plans = {}

    def region_rng(self, region_x, region_z, salt):
        return random.Random(f"{self.seed}:fortress:{salt}:{region_x}:{region_z}")

    def plan(self, region_x, region_z):
        """Крепость области или None."""
        key = (region_x, region_z)

        if key in self.plans:
            return self.plans[key]

        rng = self.region_rng(region_x, region_z, "plan")
        result = None

        if rng.random() < CHANCE:
            start_x = (region_x * REGION + 4 + rng.randrange(START_SPREAD)) * SIZE + rng.randrange(SIZE)
            start_z = (region_z * REGION + 4 + rng.randrange(START_SPREAD)) * SIZE + rng.randrange(SIZE)
            deck = DECK_Y - rng.randrange(DECK_SPREAD)
            result = self.layout(rng, start_x, start_z, deck)

        self.plans[key] = result

        return result

    def layout(self, rng, x, z, deck):
        half = CROSSING // 2
        hub = Piece("crossing", x - half, z - half, x + half, z + half, deck, openings=frozenset(DIRECTIONS))
        pieces = [hub]
        frontier = [(hub, direction, 1) for direction in DIRECTIONS]
        rng.shuffle(frontier)

        while frontier and len(pieces) < MAX_PIECES:
            parent, direction, depth = frontier.pop(0)
            added = self.grow(rng, pieces, parent, direction, depth, x, z)

            if added is None:
                continue

            for piece, next_direction in added:
                if depth + 1 <= MAX_DEPTH:
                    frontier.append((piece, next_direction, depth + 1))

        # Проходы перекрёстков и залов только туда, где действительно что-то пристроено.
        pieces = [self.trim_openings(piece, pieces) for piece in pieces]

        low_x = min(piece.x0 for piece in pieces)
        low_z = min(piece.z0 for piece in pieces)
        high_x = max(piece.x1 for piece in pieces)
        high_z = max(piece.z1 for piece in pieces)

        return Fortress(tuple(pieces), (low_x, low_z, high_x, high_z, deck - 8, deck + 1))

    def grow(self, rng, pieces, parent, direction, depth, center_x, center_z):
        """Пристраивает к стороне parent мост или коридор, а к его концу перекрёсток или зал.

        Возвращает [(часть, куда расти дальше)] или None, если места нет.
        """
        dx, dz = direction
        deck = parent.deck
        # Середина стороны parent, откуда выходит проход.
        mid_x = (parent.x0 + parent.x1) // 2
        mid_z = (parent.z0 + parent.z1) // 2
        edge_x = parent.x1 if dx > 0 else parent.x0 if dx < 0 else mid_x
        edge_z = parent.z1 if dz > 0 else parent.z0 if dz < 0 else mid_z

        length = rng.randint(*BRIDGE_LENGTH)
        start_x, start_z = edge_x + dx, edge_z + dz
        end_x, end_z = edge_x + dx * length, edge_z + dz * length
        axis = "x" if dx else "z"
        kind = "corridor" if rng.random() < 0.3 else "bridge"

        if axis == "x":
            span = Piece(kind, *box(start_x, mid_z - 2, end_x, mid_z + 2), deck, axis)
        else:
            span = Piece(kind, *box(mid_x - 2, start_z, mid_x + 2, end_z), deck, axis)

        # Что на конце: перекрёсток, зал с наростом или ничего (тупик с парапетом).
        roll = rng.random()
        end_kind = "crossing" if roll < 0.6 else "room" if roll < 0.75 and depth > 1 else None
        size = CROSSING if end_kind == "crossing" else ROOM
        half = size // 2
        tail = None

        if end_kind is not None:
            cx = end_x + dx * (half + 1) if dx else mid_x
            cz = end_z + dz * (half + 1) if dz else mid_z
            back = (-dx, -dz)
            tail = Piece(end_kind, cx - half, cz - half, cx + half, cz + half, deck, openings=frozenset(
                DIRECTIONS if end_kind == "crossing" else (back,)
            ))

        new = [span] + ([tail] if tail is not None else [])

        for piece in new:
            if max(abs(piece.x0 - center_x), abs(piece.x1 - center_x), abs(piece.z0 - center_z), abs(piece.z1 - center_z)) > MAX_REACH:
                return None

            for other in pieces:
                if other is parent:
                    continue

                if piece.overlaps(other, margin=1):
                    return None

        pieces.extend(new)

        if tail is None or tail.kind != "crossing":
            return []

        return [(tail, other) for other in DIRECTIONS if other != (-dx, -dz)]

    @staticmethod
    def trim_openings(piece, pieces):
        if piece.kind not in ("crossing", "room"):
            return piece

        openings = set()

        for direction in piece.openings:
            dx, dz = direction
            # Клетка сразу за серединой стороны.
            x = piece.x1 + 1 if dx > 0 else piece.x0 - 1 if dx < 0 else (piece.x0 + piece.x1) // 2
            z = piece.z1 + 1 if dz > 0 else piece.z0 - 1 if dz < 0 else (piece.z0 + piece.z1) // 2

            if any(other is not piece and other.x0 <= x <= other.x1 and other.z0 <= z <= other.z1 for other in pieces):
                openings.add(direction)

        return piece._replace(openings=frozenset(openings))

    # Постройка в чанке.

    def fortresses_near(self, chunk_x, chunk_z):
        region_x = chunk_x // REGION
        region_z = chunk_z // REGION
        found = []

        for rx in (region_x - 1, region_x, region_x + 1):
            for rz in (region_z - 1, region_z, region_z + 1):
                plan = self.plan(rx, rz)

                if plan is not None:
                    found.append(plan)

        return found

    def fortress_at(self, x, y, z):
        """Крепость, в границах которой точка, или None: там появляются ифриты."""
        for plan in self.fortresses_near(int(x) // SIZE, int(z) // SIZE):
            low_x, low_z, high_x, high_z, top, bottom = plan.bounds

            if low_x <= x <= high_x and low_z <= z <= high_z and top <= y <= bottom + 2:
                return plan

        return None

    def place(self, ids, chunk_x, chunk_z, generator=None):
        base_x = chunk_x * SIZE
        base_z = chunk_z * SIZE

        for plan in self.fortresses_near(chunk_x, chunk_z):
            low_x, low_z, high_x, high_z, _, _ = plan.bounds

            if high_x < base_x or low_x >= base_x + SIZE or high_z < base_z or low_z >= base_z + SIZE:
                continue

            painter = Painter(ids, base_x, base_z)

            for piece in plan.pieces:
                if piece.x1 < base_x or piece.x0 >= base_x + SIZE or piece.z1 < base_z or piece.z0 >= base_z + SIZE:
                    continue

                getattr(painter, piece.kind)(piece)


class Painter:
    """Рисует части крепости в массиве чанка, обрезая всё по его границам."""

    def __init__(self, ids, base_x, base_z):
        self.ids = ids
        self.base_x = base_x
        self.base_z = base_z

    def fill(self, x0, y0, z0, x1, y1, z1, value):
        """Заполняет коробку (включительно, в координатах мира). y0 <= y1."""
        lx0 = max(min(x0, x1) - self.base_x, 0)
        lx1 = min(max(x0, x1) - self.base_x, SIZE - 1)
        lz0 = max(min(z0, z1) - self.base_z, 0)
        lz1 = min(max(z0, z1) - self.base_z, SIZE - 1)
        ly0 = max(min(y0, y1) - Y_MIN, 0)
        ly1 = min(max(y0, y1) - Y_MIN, self.ids.shape[1] - 1)

        if lx0 > lx1 or lz0 > lz1 or ly0 > ly1:
            return

        self.ids[lx0:lx1 + 1, ly0:ly1 + 1, lz0:lz1 + 1] = value

    def pillar(self, x, z, top):
        """Колонна от top вниз сквозь пустоту и лаву, пока не упрётся в камень."""
        lx, lz = x - self.base_x, z - self.base_z

        if not (0 <= lx < SIZE and 0 <= lz < SIZE):
            return

        column = self.ids[lx, :, lz]

        for row in range(top - Y_MIN, column.shape[0]):
            if column[row] not in (AIR, LAVA):
                break

            column[row] = BRICK

    def deck(self, piece, clear_height=4):
        """Настил части и пустота над ним."""
        self.fill(piece.x0, piece.deck, piece.z0, piece.x1, piece.deck, piece.z1, BRICK)
        self.fill(piece.x0, piece.deck - clear_height, piece.z0, piece.x1, piece.deck - 1, piece.z1, AIR)

    def bridge(self, piece):
        self.deck(piece)
        # Под настилом балка в два слоя.
        self.fill(piece.x0, piece.deck + 1, piece.z0, piece.x1, piece.deck + 1, piece.z1, BRICK)

        if piece.axis == "x":
            for z in (piece.z0, piece.z1):
                self.fill(piece.x0, piece.deck - 1, z, piece.x1, piece.deck - 1, z, BRICK)

            for x in range(piece.x0, piece.x1 + 1):
                if (x - piece.x0) % PILLAR_STEP == 2:
                    for z in (piece.z0 + 1, piece.z1 - 1):
                        self.pillar(x, z, piece.deck + 2)
        else:
            for x in (piece.x0, piece.x1):
                self.fill(x, piece.deck - 1, piece.z0, x, piece.deck - 1, piece.z1, BRICK)

            for z in range(piece.z0, piece.z1 + 1):
                if (z - piece.z0) % PILLAR_STEP == 2:
                    for x in (piece.x0 + 1, piece.x1 - 1):
                        self.pillar(x, z, piece.deck + 2)

    def corridor(self, piece):
        """Крытый коридор: стены, крыша и окошки в стенах."""
        self.fill(piece.x0, piece.deck - 5, piece.z0, piece.x1, piece.deck + 1, piece.z1, BRICK)
        top = piece.deck - 4

        if piece.axis == "x":
            self.fill(piece.x0, top, piece.z0 + 1, piece.x1, piece.deck - 1, piece.z1 - 1, AIR)

            for x in range(piece.x0, piece.x1 + 1):
                if (x - piece.x0) % 4 == 2:
                    for z in (piece.z0, piece.z1):
                        self.fill(x, piece.deck - 3, z, x, piece.deck - 2, z, AIR)

                if (x - piece.x0) % PILLAR_STEP == 2:
                    for z in (piece.z0 + 1, piece.z1 - 1):
                        self.pillar(x, z, piece.deck + 2)
        else:
            self.fill(piece.x0 + 1, top, piece.z0, piece.x1 - 1, piece.deck - 1, piece.z1, AIR)

            for z in range(piece.z0, piece.z1 + 1):
                if (z - piece.z0) % 4 == 2:
                    for x in (piece.x0, piece.x1):
                        self.fill(x, piece.deck - 3, z, x, piece.deck - 2, z, AIR)

                if (z - piece.z0) % PILLAR_STEP == 2:
                    for x in (piece.x0 + 1, piece.x1 - 1):
                        self.pillar(x, z, piece.deck + 2)

    def openings_cut(self, piece, height):
        """Проходы шириной в настил моста (3 клетки) по середине сторон."""
        mid_x = (piece.x0 + piece.x1) // 2
        mid_z = (piece.z0 + piece.z1) // 2

        for dx, dz in piece.openings:
            if dx:
                x = piece.x1 if dx > 0 else piece.x0
                self.fill(x, piece.deck - height, mid_z - 1, x, piece.deck - 1, mid_z + 1, AIR)
            else:
                z = piece.z1 if dz > 0 else piece.z0
                self.fill(mid_x - 1, piece.deck - height, z, mid_x + 1, piece.deck - 1, z, AIR)

    def crossing(self, piece):
        self.deck(piece, 5)
        self.fill(piece.x0, piece.deck + 1, piece.z0, piece.x1, piece.deck + 1, piece.z1, BRICK)

        # Парапет по краю, проходы на стыках с мостами.
        for x0, z0, x1, z1 in (
            (piece.x0, piece.z0, piece.x1, piece.z0), (piece.x0, piece.z1, piece.x1, piece.z1),
            (piece.x0, piece.z0, piece.x0, piece.z1), (piece.x1, piece.z0, piece.x1, piece.z1),
        ):
            self.fill(x0, piece.deck - 1, z0, x1, piece.deck - 1, z1, BRICK)

        # Столбики по углам повыше.
        for x in (piece.x0, piece.x1):
            for z in (piece.z0, piece.z1):
                self.fill(x, piece.deck - 3, z, x, piece.deck - 1, z, BRICK)
                self.pillar(x + (1 if x == piece.x0 else -1), z + (1 if z == piece.z0 else -1), piece.deck + 2)

        self.openings_cut(piece, 1)

    def room(self, piece):
        """Зал с наростом: стены, крыша, окна и две грядки песка душ."""
        self.fill(piece.x0, piece.deck - 7, piece.z0, piece.x1, piece.deck + 1, piece.z1, BRICK)
        self.fill(piece.x0 + 1, piece.deck - 6, piece.z0 + 1, piece.x1 - 1, piece.deck - 1, piece.z1 - 1, AIR)

        for x in (piece.x0 + 1, piece.x1 - 1):
            for z in (piece.z0 + 1, piece.z1 - 1):
                self.pillar(x, z, piece.deck + 2)

        # Окна по середине стен.
        mid_x = (piece.x0 + piece.x1) // 2
        mid_z = (piece.z0 + piece.z1) // 2

        for x in (piece.x0, piece.x1):
            self.fill(x, piece.deck - 4, mid_z - 2, x, piece.deck - 3, mid_z - 2, AIR)
            self.fill(x, piece.deck - 4, mid_z + 2, x, piece.deck - 3, mid_z + 2, AIR)

        for z in (piece.z0, piece.z1):
            self.fill(mid_x - 2, piece.deck - 4, z, mid_x - 2, piece.deck - 3, z, AIR)
            self.fill(mid_x + 2, piece.deck - 4, z, mid_x + 2, piece.deck - 3, z, AIR)

        # Грядки: песок душ вровень с полом, нарост над ним.
        for offset in (-2, 2):
            if piece.openings and next(iter(piece.openings))[0]:
                x0, x1, z0, z1 = piece.x0 + 2, piece.x1 - 2, mid_z + offset, mid_z + offset
            else:
                x0, x1, z0, z1 = mid_x + offset, mid_x + offset, piece.z0 + 2, piece.z1 - 2

            self.fill(x0, piece.deck, z0, x1, piece.deck, z1, SOUL_SAND)
            self.fill(x0, piece.deck - 1, z0, x1, piece.deck - 1, z1, WART)

        self.openings_cut(piece, 4)
