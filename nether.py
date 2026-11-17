"""Ад: второе измерение, как в 1.0.

Огромные пещеры в адском камне между коренной породой снизу и сверху, море
лавы, отмели из песка душ и гравия, грозди светокамня под сводами и вечный
огонь на адском камне. Неба нет: вместо него тёмно-красный туман, нет ни
солнца, ни ночи, а свет даёт только лава, огонь и светокамень, поэтому
полная темнота в аду светлее, чем в пещерах верхнего мира.

Блок в аду соответствует восьми блокам верхнего мира по горизонтали.

Всё строится из сида и координат, как у верхнего мира (terrain.py): чанк
можно построить в любом порядке, и он выйдет тем же. Изменённые чанки ада
лежат в saves/<мир>/DIM-1/chunks.

Ось Y направлена вниз: пол ада в y = FLOOR_Y, свод в y = CEILING_Y.
"""
import math
import random

import numpy as np

import fortress
from block import type_id
from chunk import HEIGHT, Y_MIN, Chunk
from terrain import Perlin, hash01

OVERWORLD = "overworld"
NETHER = "nether"
DIMENSIONS = (OVERWORLD, NETHER)

# Папка чанков ада внутри папки мира и ключ его состояния в world.json.
FOLDER = "DIM-1"

# Во сколько раз в аду короче путь, чем наверху.
SCALE = 8

SIZE = Chunk.SIZE

# Высота ада 128 блоков, как в оригинале: пол на уровне дна верхнего мира.
FLOOR_Y = 63
CEILING_Y = FLOOR_Y - 127
# Море лавы: всё пустое ниже 31-го блока над полом.
LAVA_SEA_Y = FLOOR_Y - 31
BEDROCK_LAYERS = 5

# Песок душ и гравий лежат на отмелях вокруг 64-го блока над полом.
SHORE = (FLOOR_Y - 66, FLOOR_Y - 58)

# Туман и «небо» ада: тёмно-красные, как в 1.0.
FOG_COLOR = (51, 8, 8)
# Яркость полной темноты: как в оригинале, ад светлее пещер наверху.
AMBIENT = 0.22

# Плотность считается в узлах решётки через CELL_XZ и CELL_Y блоков и
# сглаживается между ними, как в оригинале (там узлы через 4 и 8 блоков).
CELL_XZ = 4
CELL_Y = 4

# Грозди светокамня: попыток на чанк и шагов роста у каждой.
GLOWSTONE_TRIES = 6
GLOWSTONE_STEPS = 300
GLOWSTONE_REACH = 7
# Вечный огонь на адском камне: попыток на чанк.
FIRE_TRIES = 6

AIR = 0
NETHERRACK, SOUL_SAND, GRAVEL, GLOWSTONE, LAVA, BEDROCK, FIRE = (
    type_id(name) for name in ("netherrack", "soul_sand", "gravel", "glowstone", "lava", "bedrock", "fire")
)


def chunk_folder(folder, dimension):
    """Папка сохранения чанков измерения (для storage), или None у мира без сохранения."""
    if folder is None:
        return None

    return folder if dimension == OVERWORLD else f"{folder}/{FOLDER}"


def to_dimension(position, source, target):
    """Точка в другом измерении: в аду по горизонтали в SCALE раз ближе к началу."""
    x, y, z = position

    if source == target:
        return position

    factor = 1 / SCALE if target == NETHER else SCALE

    return (x * factor, y, z * factor)


def nether_seed(seed):
    """Свой поток случайности у ада, чтобы его шум не повторял верхний мир."""
    return (seed * 6364136223846793005 + 1442695040888963407) & ((1 << 63) - 1)


def vertical_bias(height):
    """Тяга к камню по высоте над полом: у пола и у свода камень, посередине пещеры."""
    floor = np.exp(-height / 10.0) * 1.6
    ceiling = np.exp(-(127 - height) / 10.0) * 1.8

    return floor + ceiling - 0.2


class NetherGenerator:
    """Генератор чанков ада. Интерфейс как у terrain.TerrainGenerator."""

    def __init__(self, seed):
        self.seed = seed
        own = nether_seed(seed)
        self.own_seed = own

        self.noise = {name: Perlin(own, name) for name in ("caverns", "detail", "pillars", "soul", "gravel")}
        self.fortresses = fortress.FortressPlanner(own)
        # Грозди светокамня по чанкам-источникам: каждую нужно и девяти соседям.
        self.clusters = {}

    # Камень.

    def density(self, x0, y0, z0, size_x, size_y, size_z):
        """Плотность в клетках коробки: > 0 камень. Узлы решётки общие для всего мира,
        поэтому соседние чанки сходятся без швов."""
        lx0, lx1 = math.floor(x0 / CELL_XZ), math.floor((x0 + size_x - 1) / CELL_XZ) + 1
        lz0, lz1 = math.floor(z0 / CELL_XZ), math.floor((z0 + size_z - 1) / CELL_XZ) + 1
        ly0, ly1 = math.floor(y0 / CELL_Y), math.floor((y0 + size_y - 1) / CELL_Y) + 1

        gx = np.arange(lx0, lx1 + 1) * CELL_XZ
        gy = np.arange(ly0, ly1 + 1) * CELL_Y
        gz = np.arange(lz0, lz1 + 1) * CELL_XZ
        X, Y, Z = np.meshgrid(gx.astype(np.float64), gy.astype(np.float64), gz.astype(np.float64), indexing="ij")
        height = FLOOR_Y - Y

        caverns = self.noise["caverns"].fbm3(X / 56.0, Y / 30.0, Z / 56.0, 4)
        detail = self.noise["detail"].fbm3(X / 17.0, Y / 13.0, Z / 17.0, 2)
        pillars = self.noise["pillars"].fbm2(X[:, 0, :] / 34.0, Z[:, 0, :] / 34.0, 3)

        values = caverns * 3.0 + detail * 0.9 + vertical_bias(height)
        # Изредка колонны от пола до свода.
        values += np.clip(pillars - 0.42, 0, None)[:, None, :] * 3.5

        # Трилинейно до каждой клетки коробки.
        def axis_weights(start, size, cell, origin):
            coordinates = np.arange(start, start + size)
            index = np.floor(coordinates / cell).astype(np.int64) - origin
            fraction = (coordinates / cell) - np.floor(coordinates / cell)

            return index, fraction

        ix, fx = axis_weights(x0, size_x, CELL_XZ, lx0)
        iy, fy = axis_weights(y0, size_y, CELL_Y, ly0)
        iz, fz = axis_weights(z0, size_z, CELL_XZ, lz0)

        # Сначала по x, потом по z, потом по y.
        along_x = values[ix] * (1 - fx)[:, None, None] + values[ix + 1] * fx[:, None, None]
        along_z = along_x[:, :, iz] * (1 - fz)[None, None, :] + along_x[:, :, iz + 1] * fz[None, None, :]
        result = along_z[:, iy, :] * (1 - fy)[None, :, None] + along_z[:, iy + 1, :] * fy[None, :, None]

        return result

    def solid_box(self, x0, y0, z0, size_x, size_y, size_z):
        """Где в коробке камень (без коренной породы и отмелей)."""
        solid = self.density(x0, y0, z0, size_x, size_y, size_z) > 0
        ys = np.arange(y0, y0 + size_y)
        outside = (ys < CEILING_Y) | (ys > FLOOR_Y)
        solid[:, outside, :] = False

        return solid

    # Чанк.

    def generate(self, chunk_x, chunk_z):
        base_x = chunk_x * SIZE
        base_z = chunk_z * SIZE

        ids = np.zeros((SIZE, HEIGHT, SIZE), dtype=np.uint16)
        rows = slice(CEILING_Y - Y_MIN, FLOOR_Y - Y_MIN + 1)
        span = FLOOR_Y - CEILING_Y + 1

        solid = self.solid_box(base_x, CEILING_Y, base_z, SIZE, span, SIZE)
        volume = np.where(solid, NETHERRACK, AIR).astype(np.uint16)

        # Море лавы.
        heights = FLOOR_Y - np.arange(CEILING_Y, FLOOR_Y + 1)
        sea = (heights <= FLOOR_Y - LAVA_SEA_Y)[None, :, None] & ~solid
        volume[sea] = LAVA

        self.shores(volume, base_x, base_z)
        self.bedrock(volume, base_x, base_z)

        ids[:, rows, :] = volume

        self.fortresses.place(ids, chunk_x, chunk_z, self)
        self.glowstone(ids, chunk_x, chunk_z)
        self.fire(ids, chunk_x, chunk_z)

        return Chunk(chunk_x, chunk_z, ids)

    def bedrock(self, volume, base_x, base_z):
        """Сплошной слой у пола и под сводом, над ним ещё несколько вперемешку с камнем."""
        x, z = np.meshgrid(base_x + np.arange(SIZE), base_z + np.arange(SIZE), indexing="ij")
        last = volume.shape[1] - 1

        for layer in range(BEDROCK_LAYERS):
            # Чем дальше от края, тем реже коренная порода.
            floor = hash01(self.own_seed, 101 + layer, x, z) < 1 - layer / BEDROCK_LAYERS
            ceiling = hash01(self.own_seed, 201 + layer, x, z) < 1 - layer / BEDROCK_LAYERS
            volume[:, last - layer, :][floor] = BEDROCK
            volume[:, layer, :][ceiling] = BEDROCK

    def shores(self, volume, base_x, base_z):
        """Песок душ и гравий на верхних слоях камня у отмелей."""
        x, z = np.meshgrid(base_x + np.arange(SIZE), base_z + np.arange(SIZE), indexing="ij")
        soul = self.noise["soul"].fbm2(x / 24.0, z / 24.0, 3) + hash01(self.own_seed, 7, x, z) * 0.12 > 0.12
        gravel = self.noise["gravel"].fbm2(x / 20.0, z / 20.0, 3) + hash01(self.own_seed, 8, x, z) * 0.12 > 0.28

        top_row = SHORE[0] - CEILING_Y
        bottom_row = SHORE[1] - CEILING_Y

        rock = volume == NETHERRACK
        # Камень, над которым пусто: поверхность.
        surface = rock.copy()
        surface[:, 1:, :] &= volume[:, :-1, :] != NETHERRACK
        surface[:, 0, :] = False

        for row in range(top_row, bottom_row + 1):
            for depth in range(3):
                target = row + depth

                if target >= volume.shape[1]:
                    break

                layer = surface[:, row, :] & rock[:, target, :]

                # Гравий только на самых нижних отмелях, как в оригинале.
                volume[:, target, :][layer & gravel & (row >= bottom_row - 3)] = GRAVEL
                volume[:, target, :][layer & soul & ~(gravel & (row >= bottom_row - 3))] = SOUL_SAND

    # Украшения: зависят от соседних чанков, поэтому строятся из их семян.

    def glowstone(self, ids, chunk_x, chunk_z):
        """Грозди светокамня под сводами. Гроздь может свеситься в соседний чанк,
        поэтому смотрим и на грозди соседей."""
        for source_x in range(chunk_x - 1, chunk_x + 2):
            for source_z in range(chunk_z - 1, chunk_z + 2):
                for cell in self.glowstone_cluster_cells(source_x, source_z):
                    local_x = cell[0] - chunk_x * SIZE
                    local_z = cell[2] - chunk_z * SIZE

                    if 0 <= local_x < SIZE and 0 <= local_z < SIZE:
                        row = cell[1] - Y_MIN

                        if ids[local_x, row, local_z] == AIR:
                            ids[local_x, row, local_z] = GLOWSTONE

    def glowstone_cluster_cells(self, chunk_x, chunk_z):
        key = (chunk_x, chunk_z)

        if key not in self.clusters:
            if len(self.clusters) > 512:
                self.clusters.clear()

            self.clusters[key] = self.grow_clusters(chunk_x, chunk_z)

        return self.clusters[key]

    def grow_clusters(self, chunk_x, chunk_z):
        rng = random.Random(f"{self.own_seed}:glowstone:{chunk_x}:{chunk_z}")
        cells = []

        for _ in range(GLOWSTONE_TRIES):
            x = chunk_x * SIZE + rng.randrange(SIZE)
            z = chunk_z * SIZE + rng.randrange(SIZE)
            # Ищем свод: камень, под которым пусто.
            column = self.solid_box(x, CEILING_Y, z, 1, FLOOR_Y - CEILING_Y + 1, 1)[0, :, 0]
            start = rng.randrange(BEDROCK_LAYERS + 2, len(column) - 40)
            anchor = None

            for row in range(start, len(column) - 1):
                if column[row] and not column[row + 1]:
                    anchor = row + 1 + CEILING_Y
                    break

            if anchor is None or anchor > LAVA_SEA_Y - 4:
                continue

            reach = GLOWSTONE_REACH
            box_solid = self.solid_box(x - reach, anchor - 1, z - reach, 2 * reach + 1, reach + 3, 2 * reach + 1)
            cluster = {(x, anchor, z)}
            cells.append((x, anchor, z))

            # Как в оригинале: новый блок ставится в пустоту рядом ровно с одним блоком грозди.
            for _ in range(GLOWSTONE_STEPS):
                cx = x + rng.randint(-reach, reach)
                cy = anchor + rng.randint(0, reach)
                cz = z + rng.randint(-reach, reach)
                local = (cx - x + reach, cy - anchor + 1, cz - z + reach)

                if (cx, cy, cz) in cluster or box_solid[local]:
                    continue

                around = sum(
                    (cx + dx, cy + dy, cz + dz) in cluster
                    for dx, dy, dz in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1))
                )

                if around == 1:
                    cluster.add((cx, cy, cz))
                    cells.append((cx, cy, cz))

        return cells

    def fire(self, ids, chunk_x, chunk_z):
        """Вечный огонь местами на адском камне."""
        rng = random.Random(f"{self.own_seed}:fire:{chunk_x}:{chunk_z}")

        for _ in range(rng.randint(0, FIRE_TRIES)):
            x = rng.randrange(SIZE)
            z = rng.randrange(SIZE)
            column = ids[x, :, z]
            rock = np.flatnonzero(column == NETHERRACK)
            rng.shuffle(rock_list := rock.tolist())

            for row in rock_list[:6]:
                if row > 0 and column[row - 1] == AIR:
                    ids[x, row - 1, z] = FIRE
                    break

    # Для игры.

    def biome_at(self, x, z):
        return "Hell"

    def find_spawn(self):
        return 0, 0


class NetherSky:
    """Небо ада для рендерера: на месте daytime.Sky, без светил и ночи."""

    @staticmethod
    def make():
        import daytime

        return daytime.Sky(
            angle=0.0,
            night=0.0,
            sky_color=FOG_COLOR,
            fog_color=FOG_COLOR,
            glow_color=(0, 0, 0),
            glow=0.0,
            stars=0.0,
            moon_phase=0,
            celestial=False,
        )


# Состояние измерений в world.json: верхний мир хранит его в корне файла
# (так было до появления ада), ад в разделе "nether".

STATE_KEYS = ("containers", "items", "mobs", "spawned_chunks")


def state_of(meta, dimension):
    """Сырые поля состояния измерения из world.json."""
    if dimension == OVERWORLD:
        return {key: meta.get(key) for key in STATE_KEYS}

    section = meta.get(NETHER)

    if not isinstance(section, dict):
        return {key: None for key in STATE_KEYS}

    return {key: section.get(key) for key in STATE_KEYS}


def write_states(extra, dimension, active, inactive):
    """Поля world.json для обоих измерений: active текущего, inactive другого."""
    overworld, nether = (active, inactive) if dimension == OVERWORLD else (inactive, active)

    extra.update({key: value for key, value in overworld.items() if value is not None})
    extra[NETHER] = {key: value for key, value in nether.items() if value is not None}
    extra["dimension"] = dimension

    return extra
