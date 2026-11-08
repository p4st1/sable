"""Генератор бесконечного мира: рельеф, биомы, реки, пещеры, руды и деревья.

Пещеры вырезает caves.CaveCarver: тоннели, как в 1.0.

Всё зависит только от сида и координат, поэтому чанк можно построить в любой
момент и в любом порядке, и он выйдет одинаковым. Сохраняются только чанки,
которые игрок изменил, остальные строятся заново при подгрузке.

Ось Y направлена вниз. Высота столбца h считается вверх от уровня моря:
верхний блок столбца лежит в y = SEA_LEVEL - h. Вода заполняет всё ниже моря.

Шум — классический Перлин на numpy: столбцы и объём чанка считаются целиком.
"""
import math
import random
import zlib

import numpy as np

from block import Block, block_id, type_id
from caves import CaveCarver
from chunk import HEIGHT, Y_MIN, Chunk

SIZE = Chunk.SIZE

# Поверхность моря: верхний слой воды лежит в этом y.
SEA_LEVEL = 0
# Дно мира: сплошная коренная порода, над ней ещё несколько слоёв вперемешку с камнем.
BEDROCK_Y = 63
BEDROCK_LAYERS = 4
# Горы выше этого не растут: над ними ещё должно хватить места для деревьев.
MAX_HEIGHT = 100

# На столько столбцов вокруг чанка смотрим, чтобы достроить деревья соседей:
# крона ели шире всех, у неё радиус 3. Ещё один столбец нужен для сравнения соседей.
TREE_MARGIN = 3
MARGIN = TREE_MARGIN + 2

OCEAN, BEACH, PLAINS, FOREST, DESERT, TAIGA, MOUNTAINS, RIVER, PEAKS = range(9)

BIOME_NAMES = (
    "Ocean", "Beach", "Plains", "Forest", "Desert",
    "Snowy Taiga", "Mountains", "River", "Snowy Peaks",
)

# Холодные биомы: вода в них сверху замерзает.
COLD = (TAIGA, PEAKS)

# Доля столбцов с деревом (или кактусом в пустыне).
TREE_DENSITY = np.array([0, 0, 0.006, 0.045, 0.008, 0.03, 0.004, 0, 0], dtype=np.float64)


def ids(*names):
    return tuple(type_id(name) for name in names)


AIR = 0
ROSE, DANDELION, LAVA = (type_id(name) for name in ("rose", "dandelion", "lava"))

# Ниже этого (наш y больше) дно пещер залито лавой: в оригинале это y < 10 над дном мира.
CAVE_LAVA_Y = BEDROCK_Y - 9

# Озёра: водяное раз на столько чанков, лавовое раз на столько, высота ящика.
LAKE_WATER_CHANCE = 4
LAKE_LAVA_CHANCE = 8
LAKE_DEPTH = 8
# Уровень моря оригинала (его высота 63 это наш y = 0).
LAKE_SEA = 63

# Цветы: доля клеток с цветком внутри полянки, доля полянок и сколько из цветов розы.
FLOWER_PLAINS = 0.08
FLOWER_FOREST = 0.04
FLOWER_PATCHES = 0.3
FLOWER_PATCH_SIZE = 8
ROSE_SHARE = 0.3
(STONE, DIRT, GRASS, SAND, SANDSTONE, GRAVEL, CLAY, SNOWY_GRASS, SNOW, ICE,
 BEDROCK, WATER, OAK_LOG, OAK_LEAVES, BIRCH_LOG, BIRCH_LEAVES, SPRUCE_LOG,
 SPRUCE_LEAVES, CACTUS) = ids(
    "stone", "dirt", "grass", "sand", "sandstone", "gravel", "clay", "snowy_grass",
    "snow", "ice", "bedrock", "water", "oak_log", "oak_leaves", "birch_log",
    "birch_leaves", "spruce_log", "spruce_leaves", "cactus"
)

# Верхний блок и что под ним по биомам. Для глубины наполнителя см. surface_layers.
TOP = np.array([SAND, SAND, GRASS, GRASS, SAND, SNOWY_GRASS, GRASS, SAND, SNOW], dtype=np.uint16)
FILLER = np.array([SAND, SAND, DIRT, DIRT, SAND, DIRT, DIRT, SAND, STONE], dtype=np.uint16)


class Ore:
    def __init__(self, name, veins, size, top, bottom):
        self.id = type_id(name)
        # Сколько жил на чанк и сколько шагов делает каждая.
        self.veins = veins
        self.size = size
        # Жилы начинаются между этими y (top выше, ось вниз).
        self.top = top
        self.bottom = bottom


ORES = (
    Ore("gravel", 3, 24, -100, BEDROCK_Y),
    Ore("dirt", 3, 24, -100, 30),
    Ore("coal_ore", 18, 14, -100, BEDROCK_Y),
    Ore("iron_ore", 12, 8, 0, BEDROCK_Y),
    Ore("gold_ore", 3, 8, 30, BEDROCK_Y),
    Ore("diamond_ore", 2, 7, 46, BEDROCK_Y),
)


def smoothstep(low, high, value):
    t = np.clip((value - low) / (high - low), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def fade(t):
    return t * t * t * (t * (t * 6 - 15) + 10)


def lerp(t, a, b):
    return a + t * (b - a)


GRADIENTS_2D = np.array(
    [(math.cos(angle), math.sin(angle)) for angle in np.arange(8) * math.pi / 4],
    dtype=np.float64
)

GRADIENTS_3D = np.array([
    (1, 1, 0), (-1, 1, 0), (1, -1, 0), (-1, -1, 0),
    (1, 0, 1), (-1, 0, 1), (1, 0, -1), (-1, 0, -1),
    (0, 1, 1), (0, -1, 1), (0, 1, -1), (0, -1, -1),
    (1, 1, 0), (-1, 1, 0), (0, -1, 1), (0, -1, -1),
], dtype=np.float64)


def sub_seed(seed, name):
    """Свой поток случайных чисел у каждого шума: сид мира и имя шума."""
    return [seed & 0xFFFFFFFFFFFFFFFF, zlib.crc32(name.encode())]


class Perlin:
    def __init__(self, seed, name):
        rng = np.random.default_rng(sub_seed(seed, name))
        permutation = rng.permutation(256)
        self.perm = np.concatenate([permutation, permutation]).astype(np.int64)

        # Сдвиг октав: иначе в нуле все октавы дружно проходят через ноль.
        self.offsets = rng.uniform(0, 256, (8, 3))

    def noise2(self, x, z):
        x0 = np.floor(x)
        z0 = np.floor(z)
        fx = x - x0
        fz = z - z0
        xi = x0.astype(np.int64) & 255
        zi = z0.astype(np.int64) & 255

        perm = self.perm
        a = perm[xi]
        b = perm[xi + 1]

        def corner(hashed, dx, dz):
            gradient = GRADIENTS_2D[hashed & 7]
            return gradient[..., 0] * dx + gradient[..., 1] * dz

        n00 = corner(perm[a + zi], fx, fz)
        n10 = corner(perm[b + zi], fx - 1, fz)
        n01 = corner(perm[a + zi + 1], fx, fz - 1)
        n11 = corner(perm[b + zi + 1], fx - 1, fz - 1)

        u = fade(fx)
        v = fade(fz)

        # Перлин в 2D даёт примерно от -0.7 до 0.7, растягиваем до -1..1.
        return lerp(v, lerp(u, n00, n10), lerp(u, n01, n11)) * 1.41

    def noise3(self, x, y, z):
        x0 = np.floor(x)
        y0 = np.floor(y)
        z0 = np.floor(z)
        fx = x - x0
        fy = y - y0
        fz = z - z0
        xi = x0.astype(np.int64) & 255
        yi = y0.astype(np.int64) & 255
        zi = z0.astype(np.int64) & 255

        perm = self.perm
        a = perm[xi] + yi
        b = perm[xi + 1] + yi
        aa, ab = perm[a] + zi, perm[a + 1] + zi
        ba, bb = perm[b] + zi, perm[b + 1] + zi

        def corner(hashed, dx, dy, dz):
            gradient = GRADIENTS_3D[perm[hashed] & 15]
            return gradient[..., 0] * dx + gradient[..., 1] * dy + gradient[..., 2] * dz

        u = fade(fx)
        v = fade(fy)
        w = fade(fz)

        x1 = lerp(u, corner(aa, fx, fy, fz), corner(ba, fx - 1, fy, fz))
        x2 = lerp(u, corner(ab, fx, fy - 1, fz), corner(bb, fx - 1, fy - 1, fz))
        x3 = lerp(u, corner(aa + 1, fx, fy, fz - 1), corner(ba + 1, fx - 1, fy, fz - 1))
        x4 = lerp(u, corner(ab + 1, fx, fy - 1, fz - 1), corner(bb + 1, fx - 1, fy - 1, fz - 1))

        return lerp(w, lerp(v, x1, x2), lerp(v, x3, x4))

    def fbm2(self, x, z, octaves, persistence=0.5):
        total = np.zeros(np.broadcast(x, z).shape)
        amplitude = 1.0
        frequency = 1.0
        norm = 0.0

        for octave in range(octaves):
            dx, dz, _ = self.offsets[octave]
            total += amplitude * self.noise2(x * frequency + dx, z * frequency + dz)
            norm += amplitude
            amplitude *= persistence
            frequency *= 2

        return total / norm

    def fbm3(self, x, y, z, octaves, persistence=0.5):
        total = np.zeros(np.broadcast(x, y, z).shape)
        amplitude = 1.0
        frequency = 1.0
        norm = 0.0

        for octave in range(octaves):
            dx, dy, dz = self.offsets[octave]
            total += amplitude * self.noise3(x * frequency + dx, y * frequency + dy, z * frequency + dz)
            norm += amplitude
            amplitude *= persistence
            frequency *= 2

        return total / norm


def hash01(seed, salt, *coordinates):
    """Псевдослучайное число от 0 до 1 для целых координат (массивов numpy)."""
    value = np.uint64(seed & 0xFFFFFFFFFFFFFFFF) ^ np.uint64(salt * 0x9E3779B97F4A7C15 & 0xFFFFFFFFFFFFFFFF)
    multipliers = (0xBF58476D1CE4E5B9, 0x94D049BB133111EB, 0xD6E8FEB86659FD93)

    with np.errstate(over="ignore"):
        for coordinate, multiplier in zip(coordinates, multipliers):
            value = (value ^ np.asarray(coordinate).astype(np.int64).astype(np.uint64)) * np.uint64(multiplier)
            value ^= value >> np.uint64(31)

        value = (value ^ (value >> np.uint64(29))) * np.uint64(0xBF58476D1CE4E5B9)
        value ^= value >> np.uint64(32)

    return (value >> np.uint64(11)).astype(np.float64) / float(1 << 53)


def shift_max(values, radius):
    """Максимум по квадрату (2 * radius + 1) вокруг каждой клетки, края обрезаются."""
    result = values.copy()
    rows, columns = values.shape

    for dx in range(-radius, radius + 1):
        for dz in range(-radius, radius + 1):
            if dx == 0 and dz == 0:
                continue

            target = result[max(0, -dx):rows - max(0, dx), max(0, -dz):columns - max(0, dz)]
            source = values[max(0, dx):rows - max(0, -dx), max(0, dz):columns - max(0, -dz)]
            np.maximum(target, source, out=target)

    return result


class Columns:
    """Всё о столбцах прямоугольника мира: высота, биом, крутизна склона."""

    def __init__(self, height, biome, slope, entrance, top):
        self.height = height
        self.biome = biome
        self.slope = slope
        # Здесь пещера может выйти на поверхность.
        self.entrance = entrance
        # y верхнего блока.
        self.top = top


class TerrainGenerator:
    def __init__(self, seed):
        self.seed = seed

        names = ("continent", "erosion", "detail", "ridge", "river", "temperature",
                 "humidity", "entrance", "surface")

        self.noise = {name: Perlin(seed, name) for name in names}
        self.caves = CaveCarver(seed)
        # Озёра по чанкам: считаются один раз (см. lake_plan).
        self.lakes = {}

    # Столбцы.

    def shape(self, x, z):
        """Высота над морем, а заодно то, из чего она сложена: для выбора биома."""
        noise = self.noise

        continent = noise["continent"].fbm2(x / 700, z / 700, 5) * 1.3
        erosion = noise["erosion"].fbm2(x / 420, z / 420, 3) * 1.3
        detail = noise["detail"].fbm2(x / 90, z / 90, 4)
        ridge = 1 - np.abs(noise["ridge"].fbm2(x / 200, z / 200, 4) * 1.3)
        river = np.abs(noise["river"].fbm2(x / 520, z / 520, 4))

        # Континентальность задаёт основу: глубокий океан, берег, равнины, плато.
        base = np.interp(
            continent,
            [-1.0, -0.65, -0.42, -0.28, -0.18, -0.02, 0.4, 1.0],
            [-30, -22, -12, -4, 1, 4, 9, 16]
        )

        hills = detail * np.interp(continent, [-0.4, -0.1, 0.4], [1.5, 5.0, 10.0])

        # Горы там, где мало эрозии, и только на суше.
        mountain = smoothstep(0.0, 0.4, erosion) * smoothstep(-0.15, 0.05, continent)
        peaks = mountain * (ridge ** 2.2 * 70 + np.abs(detail) * 8)

        height = base + hills + peaks

        # Река прорезает сушу до трёх блоков ниже моря. В горах это ущелье.
        channel = (1 - smoothstep(0.009, 0.04, river)) * smoothstep(-0.3, -0.15, continent)
        river_bed = -3 + np.abs(detail) * 1.5
        height = np.where(height > river_bed, lerp(channel, height, river_bed), height)

        height = np.minimum(np.floor(height), MAX_HEIGHT).astype(np.int64)

        return height, continent, mountain, channel

    def climate(self, x, z):
        temperature = self.noise["temperature"].fbm2(x / 800, z / 800, 3) * 1.4
        humidity = self.noise["humidity"].fbm2(x / 650, z / 650, 3) * 1.4

        return temperature, humidity

    def biomes(self, height, continent, mountain, channel, temperature, humidity):
        biome = np.full(height.shape, PLAINS, dtype=np.int64)

        biome[humidity > 0.12] = FOREST
        biome[temperature < -0.3] = TAIGA
        biome[(temperature > 0.3) & (humidity < 0.15)] = DESERT

        cold = temperature < -0.3
        desert = biome == DESERT

        beach = (height <= 1) & ((continent < -0.12) | (channel > 0.25)) & ~desert
        biome[beach & ~cold] = BEACH

        biome[(height >= 34) & (mountain > 0.25)] = MOUNTAINS
        biome[(height >= 52) | ((height >= 34) & (mountain > 0.25) & cold)] = PEAKS

        under = height < SEA_LEVEL
        biome[under] = OCEAN
        biome[under & (channel > 0.5) & (continent > -0.3)] = RIVER

        return biome

    def columns(self, x, z):
        """Столбцы для сетки координат x, z (двумерные массивы целых)."""
        x = np.asarray(x)
        z = np.asarray(z)
        fx = x.astype(np.float64)
        fz = z.astype(np.float64)

        height, continent, mountain, channel = self.shape(fx, fz)
        temperature, humidity = self.climate(fx, fz)
        biome = self.biomes(height, continent, mountain, channel, temperature, humidity)

        if height.ndim == 2 and min(height.shape) > 2:
            slope = np.zeros_like(height)
            inner = height[1:-1, 1:-1]
            slope[1:-1, 1:-1] = np.maximum.reduce([
                np.abs(inner - height[2:, 1:-1]),
                np.abs(inner - height[:-2, 1:-1]),
                np.abs(inner - height[1:-1, 2:]),
                np.abs(inner - height[1:-1, :-2]),
            ])
        else:
            slope = np.zeros_like(height)

        entrance = self.noise["entrance"].fbm2(fx / 70, fz / 70, 2) > 0.5

        columns = Columns(height, biome, slope, entrance, SEA_LEVEL - height)

        # В холодных краях океан и река тоже холодные: сверху лёд.
        columns.frozen = (height < SEA_LEVEL) & (temperature < -0.3)

        return columns

    def biome_at(self, x, z):
        return BIOME_NAMES[int(self.columns(np.array([[x]]), np.array([[z]])).biome[0, 0])]

    def find_spawn(self):
        """Ближайший к нулю столбец суши, где можно спокойно начать. Возвращает (x, z)."""
        for radius in (64, 256, 1024, 4096):
            step = max(1, radius // 32)
            grid = np.arange(-radius, radius + 1, step)
            x, z = np.meshgrid(grid, grid, indexing="ij")
            columns = self.columns(x, z)

            good = np.isin(columns.biome, (PLAINS, FOREST, TAIGA, DESERT)) & (columns.height >= 2) & (columns.height <= 24)

            if good.any():
                distance = np.where(good, x * x + z * z, np.iinfo(np.int64).max)
                index = np.unravel_index(np.argmin(distance), distance.shape)
                return int(x[index]), int(z[index])

        return 0, 0

    # Чанк.

    def generate(self, chunk_x, chunk_z):
        base_x = chunk_x * SIZE
        base_z = chunk_z * SIZE

        span = np.arange(-MARGIN, SIZE + MARGIN)
        x, z = np.meshgrid(base_x + span, base_z + span, indexing="ij")
        area = self.columns(x, z)

        inside = (slice(MARGIN, MARGIN + SIZE), slice(MARGIN, MARGIN + SIZE))

        ids = np.zeros((SIZE, HEIGHT, SIZE), dtype=np.uint16)

        self.fill_terrain(ids, area, inside, x[inside], z[inside])
        # Пещеры как в 1.0: тоннели, а не залы. Вода и коренная порода не трогаются.
        self.caves.carve(ids, chunk_x, chunk_z, Y_MIN, (WATER, BEDROCK), (CAVE_LAVA_Y, LAVA))
        self.place_lakes(ids, chunk_x, chunk_z)
        self.add_ores(ids, chunk_x, chunk_z)
        self.plant_trees(ids, area, x, z, base_x, base_z)
        self.place_flowers(ids, area, inside, x[inside], z[inside])

        return Chunk(chunk_x, chunk_z, ids)

    def fill_terrain(self, ids, area, inside, x, z):
        top = area.top[inside]
        biome = area.biome[inside]
        slope = area.slope[inside]
        height = area.height[inside]

        top_id = TOP[biome].copy()
        filler_id = FILLER[biome].copy()

        # Под водой дно из песка, местами гравий и глина. На глубине гравий.
        under = height < SEA_LEVEL
        floor = self.noise["surface"].noise2(x / 12.0, z / 12.0)
        gravel = under & ((floor > 0.35) | (height < -14))
        clay = under & ~gravel & (floor < -0.45) & (height > -8)
        top_id[gravel] = GRAVEL
        filler_id[gravel] = GRAVEL
        top_id[clay] = CLAY

        # Крутые склоны голые: трава и песок на них не держатся.
        steep = (slope >= 3) & ~under
        top_id[steep & (biome != PEAKS)] = STONE
        filler_id[steep] = STONE

        # Горы ниже снеговой линии зелёные, если склон пологий.
        rocky = (biome == MOUNTAINS) & (height > 40 + (floor * 4).astype(np.int64))
        top_id[rocky] = STONE

        # На пляже песка больше, чтобы берег не обрывался сразу в камень.
        filler_depth = np.where(biome == BEACH, 4, 3)
        filler_depth[steep] = 0

        y = np.arange(Y_MIN, Y_MIN + HEIGHT)[None, :, None]
        top3 = top[:, None, :]
        depth = y - top3

        volume = np.where(depth == 0, top_id[:, None, :], STONE).astype(np.uint16)
        volume = np.where((depth > 0) & (depth <= filler_depth[:, None, :]), filler_id[:, None, :], volume)

        # Песок пустыни держится на песчанике.
        sandstone = (biome == DESERT)[:, None, :] & (depth > filler_depth[:, None, :]) & (depth <= filler_depth[:, None, :] + 3)
        volume = np.where(sandstone, SANDSTONE, volume)

        volume[depth < 0] = AIR

        water = (depth < 0) & (y >= SEA_LEVEL)
        volume[water] = WATER

        frozen = area.frozen[inside][:, None, :] & (y == SEA_LEVEL)
        volume[frozen & water] = ICE

        volume[:, BEDROCK_Y - Y_MIN + 1:, :] = AIR

        ys = np.arange(BEDROCK_Y - BEDROCK_LAYERS + 1, BEDROCK_Y + 1)
        chance = hash01(self.seed, 11, x[:, None, :], ys[None, :, None], z[:, None, :])
        layer = (ys - (BEDROCK_Y - BEDROCK_LAYERS))[None, :, None] / BEDROCK_LAYERS
        rows = slice(ys[0] - Y_MIN, ys[-1] - Y_MIN + 1)
        volume[:, rows, :] = np.where(chance < layer, BEDROCK, volume[:, rows, :])

        ids[:] = volume

    # Озёра.

    def lake_plan(self, chunk_x, chunk_z):
        """Озёра чанка до постройки: [(жидкость, наш y начала, форма 16x8x16, у поверхности ли)].

        Как в 1.0: водяное в четверти чанков, лавовое в восьмой части, лавовые
        почти всегда под землёй (выше моря только одно из десяти). Всё зависит
        только от сида и чанка, поэтому соседи знают, где у поверхности будет
        озеро, и не сажают туда деревьев.
        """
        key = (chunk_x, chunk_z)

        if key in self.lakes:
            return self.lakes[key]

        rng = random.Random((self.seed * 0x5DEECE66D + chunk_x * 341873128712 + chunk_z * 132897987541) & 0xFFFFFFFFFFFFFFFF)
        plans = []

        if rng.randrange(LAKE_WATER_CHANCE) == 0:
            plans.append((WATER, LAKE_SEA - rng.randrange(128), self.lake_shape(rng)))

        if rng.randrange(LAKE_LAVA_CHANCE) == 0:
            height = rng.randrange(rng.randrange(120) + 8)

            if height < LAKE_SEA or rng.randrange(10) == 0:
                plans.append((LAVA, LAKE_SEA - height, self.lake_shape(rng)))

        result = []

        if plans:
            center_x = chunk_x * SIZE + SIZE // 2
            center_z = chunk_z * SIZE + SIZE // 2
            ground = int(self.columns(np.array([[center_x]]), np.array([[center_z]])).top[0, 0])

            # Озеро, начатое выше земли, опустится на её поверхность.
            result = [(liquid, start, shape, start <= ground) for liquid, start, shape in plans]

        self.lakes[key] = result

        if len(self.lakes) > 4096:
            self.lakes.pop(next(iter(self.lakes)))

        return result

    @staticmethod
    def lake_shape(rng):
        """Форма озера: несколько сплюснутых шаров в ящике 16x8x16 (слой 0 сверху)."""
        shape = np.zeros((SIZE, LAKE_DEPTH, SIZE), dtype=bool)
        gx = np.arange(SIZE)[:, None, None]
        gy = np.arange(LAKE_DEPTH)[None, :, None]
        gz = np.arange(SIZE)[None, None, :]

        for _ in range(rng.randrange(4) + 4):
            width = rng.random() * 6 + 3
            depth = rng.random() * 4 + 2
            length = rng.random() * 6 + 3
            cx = rng.random() * (SIZE - width - 2) + 1 + width / 2
            # В оригинале y вверх: низ ящика это слой 0. У нас слой 0 сверху.
            cy = rng.random() * (LAKE_DEPTH - depth - 4) + 2 + depth / 2
            cz = rng.random() * (SIZE - length - 2) + 1 + length / 2

            shape |= (
                ((gx - cx) / (width / 2)) ** 2
                + ((LAKE_DEPTH - 1 - gy - cy) / (depth / 2)) ** 2
                + ((gz - cz) / (length / 2)) ** 2
            ) < 1

        shape[0, :, :] = shape[-1, :, :] = False
        shape[:, :, 0] = shape[:, :, -1] = False
        shape[:, 0, :] = shape[:, -1, :] = False

        return shape

    def lake_at_surface(self, x, z):
        """Есть ли в столбце мира озеро у поверхности: тогда дерево там не растёт."""
        chunk_x, chunk_z = x // SIZE, z // SIZE

        for _, _, shape, surface in self.lake_plan(chunk_x, chunk_z):
            if surface and shape[x - chunk_x * SIZE, :, z - chunk_z * SIZE].any():
                return True

        return False

    def place_lakes(self, ids, chunk_x, chunk_z):
        for index, (liquid, start, shape, _) in enumerate(self.lake_plan(chunk_x, chunk_z)):
            self.lake(ids, start, shape, liquid, (chunk_x, chunk_z, index))

    def lake(self, ids, y, shape, liquid, salt):
        """Озеро: нижние четыре слоя залиты, верхние пустые. Ящик опускается до первого
        не пустого блока. Если озеро вскрыло бы жидкость или пустоту сбоку, его нет."""
        center = SIZE // 2

        while y < BEDROCK_Y - 5 and ids[center, y - Y_MIN, center] == AIR:
            y += 1

        if y >= BEDROCK_Y - 4:
            return

        top = y - 4

        if top - Y_MIN < 0 or top + LAKE_DEPTH - Y_MIN > HEIGHT:
            return

        box = ids[:, top - Y_MIN:top - Y_MIN + LAKE_DEPTH, :]
        flooded = np.arange(LAKE_DEPTH)[None, :, None] >= LAKE_DEPTH - 4

        # Край озера: клетки рядом с ним, но не в нём.
        border = np.zeros_like(shape)
        border[1:] |= shape[:-1]
        border[:-1] |= shape[1:]
        border[:, 1:] |= shape[:, :-1]
        border[:, :-1] |= shape[:, 1:]
        border[:, :, 1:] |= shape[:, :, :-1]
        border[:, :, :-1] |= shape[:, :, 1:]
        border &= ~shape

        liquid_cells = (box == WATER) | (box == LAVA)

        # Над водой не должно быть жидкости, а у берега ниже воды пустоты.
        if np.any(border & ~flooded & liquid_cells) or np.any(border & flooded & (box == AIR)):
            return

        box[shape & flooded] = liquid
        box[shape & ~flooded] = AIR

        # Берег лавового озера каменный, как в оригинале: ниже лавы весь, выше через раз.
        if liquid == LAVA:
            coin = np.random.default_rng(abs(hash((self.seed, salt))) % (1 << 63)).random(shape.shape) < 0.5
            solid = (box != AIR) & (box != WATER) & (box != LAVA)
            box[border & solid & (flooded | coin)] = STONE

    def add_ores(self, ids, chunk_x, chunk_z):
        """Жилы руд и пород: случайное блуждание от точки, меняет только камень."""
        rng = np.random.default_rng(sub_seed(self.seed, f"ores {chunk_x} {chunk_z}"))

        for ore in ORES:
            for _ in range(ore.veins):
                start = np.array([
                    rng.integers(0, SIZE),
                    rng.integers(ore.top, ore.bottom + 1) - Y_MIN,
                    rng.integers(0, SIZE),
                ])

                steps = rng.integers(-1, 2, (ore.size, 3))
                cells = start + np.cumsum(steps, axis=0)

                keep = (
                    (cells[:, 0] >= 0) & (cells[:, 0] < SIZE) &
                    (cells[:, 1] >= 0) & (cells[:, 1] < HEIGHT) &
                    (cells[:, 2] >= 0) & (cells[:, 2] < SIZE)
                )
                cells = cells[keep]

                xs, ys, zs = cells[:, 0], cells[:, 1], cells[:, 2]
                stone = ids[xs, ys, zs] == STONE
                ids[xs[stone], ys[stone], zs[stone]] = ore.id

    # Цветы.

    def place_flowers(self, ids, area, inside, x, z):
        """Розы и одуванчики на траве: полянками, на равнинах гуще, чем в лесу."""
        biome = area.biome[inside]
        top = area.top[inside]

        roll = hash01(self.seed, 31, x, z)
        kind = hash01(self.seed, 32, x, z)
        # Полянки: часть квадратов 8x8 с цветами, остальные без них.
        patch = hash01(self.seed, 33, x // FLOWER_PATCH_SIZE, z // FLOWER_PATCH_SIZE)

        density = np.select([biome == PLAINS, biome == FOREST], [FLOWER_PLAINS, FLOWER_FOREST], 0.0)
        candidate = (roll < density) & (patch < FLOWER_PATCHES)

        for i, j in zip(*np.nonzero(candidate)):
            row = int(top[i, j]) - Y_MIN

            if not 1 <= row < HEIGHT:
                continue

            # Только на траве и только в пустую клетку над ней (ось Y вниз).
            if ids[i, row, j] != GRASS or ids[i, row - 1, j] != AIR:
                continue

            ids[i, row - 1, j] = ROSE if kind[i, j] < ROSE_SHARE else DANDELION

    # Деревья.

    def plant_trees(self, ids, area, x, z, base_x, base_z):
        """Деревья из этого чанка и из соседних, чьи кроны в него заходят."""
        biome = area.biome
        top = area.top
        roll = hash01(self.seed, 21, x, z)

        top_block = np.select(
            [biome == DESERT, biome == TAIGA],
            [SAND, SNOWY_GRASS],
            GRASS
        )

        candidate = (
            (roll < TREE_DENSITY[biome]) &
            (area.slope <= 1) &
            (area.height >= 1) &
            (area.height < 38) &
            ~area.entrance &
            (TOP[biome] == top_block)
        )

        # Деревья не растут ближе трёх блоков друг к другу, иначе кроны сливаются
        # в сплошную стену: из соседей остаётся то, у которого меньше число.
        score = np.where(candidate, -roll, -2.0)
        candidate &= score >= shift_max(score, 2)

        border = slice(MARGIN - TREE_MARGIN, MARGIN + SIZE + TREE_MARGIN)
        candidate[:border.start, :] = False
        candidate[border.stop:, :] = False
        candidate[:, :border.start] = False
        candidate[:, border.stop:] = False

        kind_roll = hash01(self.seed, 22, x, z)
        size_roll = hash01(self.seed, 23, x, z)

        for i, j in zip(*np.nonzero(candidate)):
            local_x = int(x[i, j]) - base_x
            local_z = int(z[i, j]) - base_z
            ground = int(top[i, j])
            kind = kind_roll[i, j]
            size = size_roll[i, j]
            column_biome = biome[i, j]

            # Над пещерой, которая вскрыла землю, и в озере дерево не растёт.
            if self.caves.carved_at(int(x[i, j]), ground, int(z[i, j])) or self.lake_at_surface(int(x[i, j]), int(z[i, j])):
                continue

            # Ствол растёт из блока, который сейчас в этом столбце сверху.
            if column_biome == DESERT:
                self.cactus(ids, local_x, ground, local_z, 1 + int(size * 3))
            elif column_biome == TAIGA:
                self.spruce(ids, local_x, ground, local_z, 6 + int(size * 4))
            elif column_biome == FOREST and kind < 0.3:
                self.round_tree(ids, local_x, ground, local_z, 5 + int(size * 3), BIRCH_LOG, BIRCH_LEAVES, base_x, base_z)
            else:
                self.round_tree(ids, local_x, ground, local_z, 4 + int(size * 3), OAK_LOG, OAK_LEAVES, base_x, base_z)

    @staticmethod
    def put(ids, x, y, z, block, replace=False):
        """Блок дерева в клетку чанка. Чужие клетки (соседних чанков) пропускаются."""
        if not (0 <= x < SIZE and 0 <= z < SIZE and Y_MIN <= y < Y_MIN + HEIGHT):
            return

        cell = (x, y - Y_MIN, z)

        if replace or ids[cell] == AIR:
            ids[cell] = block

    def ground_dirt(self, ids, x, ground, z):
        # Под деревом земля, а не трава: как в оригинале.
        if 0 <= x < SIZE and 0 <= z < SIZE and ids[x, ground - Y_MIN, z] in (GRASS, SNOWY_GRASS):
            ids[x, ground - Y_MIN, z] = DIRT

    def trunk(self, ids, x, ground, z, height, log):
        for y in range(ground - 1, ground - height - 1, -1):
            self.put(ids, x, y, z, log, replace=True)

    def round_tree(self, ids, x, ground, z, height, log, leaves, base_x, base_z):
        """Дуб и берёза: два широких слоя, узкий слой у верхушки и крестик над ней.

        Углы широких слоёв то есть, то нет. Решает хеш мировых координат угла:
        соседний чанк, достраивая ту же крону, получит те же углы.
        """
        top = ground - height

        for y, radius in ((top + 2, 2), (top + 1, 2), (top, 1), (top - 1, 1)):
            for dx in range(-radius, radius + 1):
                for dz in range(-radius, radius + 1):
                    corner = abs(dx) == radius and abs(dz) == radius

                    if corner:
                        if radius == 1 and y == top - 1:
                            continue

                        world_x = base_x + x + dx
                        world_z = base_z + z + dz

                        if ((world_x * 73856093) ^ (world_z * 19349663) ^ (y * 83492791) ^ self.seed) >> 5 & 1:
                            continue

                    self.put(ids, x + dx, y, z + dz, leaves)

        self.trunk(ids, x, ground, z, height, log)
        self.ground_dirt(ids, x, ground, z)

    def spruce(self, ids, x, ground, z, height):
        """Ель: ярусы листвы, каждый ярус книзу шире, а под ними голый ствол.

        Радиусы колец сверху вниз: 0, 1, 1, 2, 1, 2, 3, 1, 2, 3...
        """
        top = ground - height
        widest = 2 if height < 8 else 3
        bare = 1 + height % 2

        radius = 0
        peak = 1

        for y in range(top - 1, ground - bare):
            for dx in range(-radius, radius + 1):
                for dz in range(-radius, radius + 1):
                    if radius > 0 and abs(dx) == radius and abs(dz) == radius:
                        continue

                    self.put(ids, x + dx, y, z + dz, SPRUCE_LEAVES)

            if radius < peak:
                radius += 1
            else:
                peak = min(peak + 1, widest)
                radius = 1

        self.trunk(ids, x, ground, z, height, SPRUCE_LOG)
        self.ground_dirt(ids, x, ground, z)

    def cactus(self, ids, x, ground, z, height):
        for y in range(ground - 1, ground - height - 1, -1):
            self.put(ids, x, y, z, CACTUS)


def random_seed():
    return int(np.random.default_rng().integers(-(1 << 62), 1 << 62))


def parse_seed(text):
    """Сид из поля ввода: число как есть, текст через хеш, пустое поле — случайный."""
    text = text.strip()

    if not text:
        return random_seed()

    try:
        return int(text)
    except ValueError:
        # Как в оригинале у текстового сида: хеш строки в духе Java.
        value = 0

        for char in text:
            value = (31 * value + ord(char)) & 0xFFFFFFFF

        return value - (1 << 32) if value >= 1 << 31 else value
