"""Пещеры и ущелья как в 1.0: извилистые тоннели, а не огромные залы из шума.

Как это устроено в оригинале. В каждом чанке с вероятностью 1/15 начинаются
несколько систем пещер. Из точки старта иногда раздувается комната, а потом
расходятся тоннели. Тоннель идёт шагами по блоку: направление понемногу
виляет, ширина плавно растёт к середине и спадает к концу, на середине пути
широкий тоннель раздваивается на два поуже. Каждый шаг вырезает эллипсоид
с плоским полом. Тоннель тянется на сотню блоков, поэтому чанк вырезают
пещеры, начавшиеся до RANGE чанков от него.

Пути пещер зависят только от сида и чанка, где они начались, поэтому их
считаем один раз и храним: соседние чанки вырезают те же эллипсоиды.

Высоты пересчитываются из оригинала (y вверх, море на 63, низ мира 0) в наши
(y вниз, море на 0): наш y = SEA - y оригинала.
"""
import math
import random
from collections import OrderedDict

import numpy as np

RANGE = 8
CHUNK = 16
# Уровень моря оригинала: его y = 63 это наш y = 0.
SEA = 63
# Шансы и размеры, как в оригинале.
SYSTEM_CHANCE = 15
ROOM_CHANCE = 4
WIDE_CHANCE = 10
SKIP_CHANCE = 4
FLOOR = 0.7

CACHE_SIZE = 2048

# Ущелья, как в 1.0: одно на 50 чанков, глубокие и узкие, со стенками-уступами.
RAVINE_CHANCE = 50
RAVINE_HEIGHT = 3.0


def java_like_int(rng, bound):
    return rng.randrange(bound) if bound > 0 else 0


class CaveCarver:
    def __init__(self, seed):
        self.seed = seed
        self.cache = OrderedDict()

    def source_rng(self, chunk_x, chunk_z):
        # Свой поток случайных чисел у каждого чанка-источника.
        mixed = (self.seed * 341873128712 + chunk_x * 132897987541 + chunk_z * 0x9E3779B1) & 0xFFFFFFFFFFFFFFFF
        return random.Random(mixed)

    def ellipsoids(self, chunk_x, chunk_z):
        """Все эллипсоиды пещер, начавшихся в этом чанке: массив (n, 5) x, y, z, r, rv в наших осях."""
        key = (chunk_x, chunk_z)

        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]

        rng = self.source_rng(chunk_x, chunk_z)
        result = []

        systems = java_like_int(rng, java_like_int(rng, java_like_int(rng, 40) + 1) + 1)

        if java_like_int(rng, SYSTEM_CHANCE) != 0:
            systems = 0

        for _ in range(systems):
            x = chunk_x * CHUNK + java_like_int(rng, CHUNK)
            y = java_like_int(rng, java_like_int(rng, 120) + 8)
            z = chunk_z * CHUNK + java_like_int(rng, CHUNK)
            tunnels = 1

            if java_like_int(rng, ROOM_CHANCE) == 0:
                self.tunnel(rng.getrandbits(64), x, y, z, 1.0 + rng.random() * 6.0, 0.0, 0.0, -1, -1, 0.5, result)
                tunnels += java_like_int(rng, 4)

            for _ in range(tunnels):
                yaw = rng.random() * math.tau
                pitch = (rng.random() - 0.5) * 2.0 / 8.0
                width = rng.random() * 2.0 + rng.random()

                if java_like_int(rng, WIDE_CHANCE) == 0:
                    width *= rng.random() * rng.random() * 3.0 + 1.0

                self.tunnel(rng.getrandbits(64), x, y, z, width, yaw, pitch, 0, 0, 1.0, result)

        array = np.array(result, dtype=np.float64).reshape(-1, 5)

        # Из высоты оригинала (вверх) в нашу (вниз).
        array[:, 1] = SEA - array[:, 1]

        self.cache[key] = array

        if len(self.cache) > CACHE_SIZE:
            self.cache.popitem(last=False)

        return array

    def tunnel(self, seed, x, y, z, width, yaw, pitch, step, length, height_scale, result):
        """Один тоннель (или комната при step == -1) шагами, с развилкой посередине."""
        rng = random.Random(seed)
        yaw_change = 0.0
        pitch_change = 0.0

        if length <= 0:
            longest = RANGE * CHUNK - CHUNK
            length = longest - java_like_int(rng, longest // 4)

        room = False

        if step == -1:
            step = length // 2
            room = True

        branch = java_like_int(rng, length // 2) + length // 4
        steep = java_like_int(rng, 6) == 0

        while step < length:
            radius = 1.5 + math.sin(step * math.pi / length) * width
            vertical = radius * height_scale

            cos_pitch = math.cos(pitch)
            x += math.cos(yaw) * cos_pitch
            y += math.sin(pitch)
            z += math.sin(yaw) * cos_pitch

            pitch *= 0.92 if steep else 0.7
            pitch += pitch_change * 0.1
            yaw += yaw_change * 0.1
            pitch_change *= 0.9
            yaw_change *= 0.75
            pitch_change += (rng.random() - rng.random()) * rng.random() * 2.0
            yaw_change += (rng.random() - rng.random()) * rng.random() * 4.0

            if not room and step == branch and width > 1.0 and length > 0:
                for side in (-1, 1):
                    self.tunnel(
                        rng.getrandbits(64), x, y, z, rng.random() * 0.5 + 0.5,
                        yaw + side * math.pi / 2, pitch / 3.0, step, length, 1.0, result
                    )
                return

            step += 1

            if not room and java_like_int(rng, SKIP_CHANCE) == 0:
                continue

            result.append((x, y, z, radius, vertical))

            if room:
                break

    def nearby(self, chunk_x, chunk_z):
        """Эллипсоиды всех пещер, которые могут задеть этот чанк."""
        key = ("near", chunk_x, chunk_z)

        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]

        result = self.collect_nearby(chunk_x, chunk_z)
        self.cache[key] = result

        if len(self.cache) > CACHE_SIZE:
            self.cache.popitem(last=False)

        return result

    def collect_nearby(self, chunk_x, chunk_z):
        parts = [
            self.ellipsoids(chunk_x + dx, chunk_z + dz)
            for dx in range(-RANGE, RANGE + 1)
            for dz in range(-RANGE, RANGE + 1)
        ]
        everything = np.concatenate(parts) if parts else np.zeros((0, 5))

        if len(everything) == 0:
            return everything

        x0, z0 = chunk_x * CHUNK, chunk_z * CHUNK
        x, z, r = everything[:, 0], everything[:, 2], everything[:, 3]
        touches = (x + r > x0) & (x - r < x0 + CHUNK) & (z + r > z0) & (z - r < z0 + CHUNK)

        return everything[touches]

    def carve(self, ids, chunk_x, chunk_z, y_min, keep, lava=None):
        """Вырезает пещеры в объёме чанка ids [x, y - y_min, z].

        keep: номера блоков, которые не трогаем (вода, коренная порода). Как в
        оригинале, эллипсоид, в чьей рамке есть вода, пропускается целиком:
        пещеры не затапливаются из морей и рек. lava: (y, номер блока) — ниже
        этого y (у нас больше y) пещеры залиты лавой, как у дна мира в оригинале.
        """
        x0, z0 = chunk_x * CHUNK, chunk_z * CHUNK
        height = ids.shape[1]
        water = keep[0]

        for cx, cy, cz, radius, vertical in self.nearby(chunk_x, chunk_z):
            lx0 = max(0, math.floor(cx - radius) - x0)
            lx1 = min(CHUNK, math.ceil(cx + radius) - x0 + 1)
            lz0 = max(0, math.floor(cz - radius) - z0)
            lz1 = min(CHUNK, math.ceil(cz + radius) - z0 + 1)
            ly0 = max(1, math.floor(cy - vertical) - y_min)
            ly1 = min(height - 1, math.ceil(cy + vertical) - y_min + 1)

            if lx0 >= lx1 or lz0 >= lz1 or ly0 >= ly1:
                continue

            box = ids[lx0:lx1, ly0 - 1:ly1 + 1, lz0:lz1]

            if np.any(box == water):
                continue

            gx = (np.arange(lx0, lx1) + x0 + 0.5 - cx) / radius
            gy = (np.arange(ly0, ly1) + y_min + 0.5 - cy) / vertical
            gz = (np.arange(lz0, lz1) + z0 + 0.5 - cz) / radius

            inside = (gx[:, None, None] ** 2 + gy[None, :, None] ** 2 + gz[None, None, :] ** 2 < 1.0)
            # Плоский пол: нижняя часть эллипсоида (у нас y вниз, это gy > FLOOR) не вырезается.
            inside &= gy[None, :, None] < FLOOR

            region = ids[lx0:lx1, ly0:ly1, lz0:lz1]
            carve = inside & ~np.isin(region, keep)
            region[carve] = 0

            if lava is not None:
                lava_y, lava_id = lava
                deep = (np.arange(ly0, ly1) + y_min >= lava_y)[None, :, None]
                region[carve & deep] = lava_id

        self.carve_ravines(ids, chunk_x, chunk_z, y_min, keep, lava)

    # Ущелья.

    def ravines(self, chunk_x, chunk_z):
        """Ущелье, начатое в этом чанке: (отрезки (n, 5) в наших осях, множители стенок по высоте) или None."""
        key = ("ravine", chunk_x, chunk_z)

        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]

        rng = self.source_rng(chunk_x * 7 + 3, chunk_z * 11 + 5)
        result = None

        if java_like_int(rng, RAVINE_CHANCE) == 0:
            x = chunk_x * CHUNK + java_like_int(rng, CHUNK)
            y = java_like_int(rng, java_like_int(rng, 40) + 8) + 20
            z = chunk_z * CHUNK + java_like_int(rng, CHUNK)
            yaw = rng.random() * math.tau
            pitch = (rng.random() - 0.5) * 2.0 / 8.0
            width = (rng.random() * 2.0 + rng.random()) * 2.0
            result = self.ravine(rng.getrandbits(64), x, y, z, width, yaw, pitch)

        self.cache[key] = result

        if len(self.cache) > CACHE_SIZE:
            self.cache.popitem(last=False)

        return result

    @staticmethod
    def ravine(seed, x, y, z, width, yaw, pitch):
        """Ущелье шагами, как тоннель, но в RAVINE_HEIGHT раз выше и без развилок."""
        rng = random.Random(seed)
        yaw_change = pitch_change = 0.0
        longest = RANGE * CHUNK - CHUNK
        length = longest - java_like_int(rng, longest // 4)

        # Неровные стены: у каждой высоты свой множитель ширины, меняется уступами.
        walls = np.empty(128)
        factor = 1.0

        for level in range(128):
            if level == 0 or java_like_int(rng, 3) == 0:
                factor = 1.0 + rng.random() * rng.random()

            walls[level] = factor * factor

        segments = []

        for step in range(length):
            radius = 1.5 + math.sin(step * math.pi / length) * width
            vertical = radius * RAVINE_HEIGHT
            radius *= rng.random() * 0.25 + 0.75
            vertical *= rng.random() * 0.25 + 0.75

            cos_pitch = math.cos(pitch)
            x += math.cos(yaw) * cos_pitch
            y += math.sin(pitch)
            z += math.sin(yaw) * cos_pitch

            pitch *= 0.7
            pitch += pitch_change * 0.05
            yaw += yaw_change * 0.05
            pitch_change *= 0.8
            yaw_change *= 0.5
            pitch_change += (rng.random() - rng.random()) * rng.random() * 2.0
            yaw_change += (rng.random() - rng.random()) * rng.random() * 4.0

            if java_like_int(rng, 4) == 0:
                continue

            segments.append((x, SEA - y, z, radius, vertical))

        return np.array(segments, dtype=np.float64).reshape(-1, 5), walls

    def nearby_ravines(self, chunk_x, chunk_z):
        x0, z0 = chunk_x * CHUNK, chunk_z * CHUNK
        found = []

        for dx in range(-RANGE, RANGE + 1):
            for dz in range(-RANGE, RANGE + 1):
                ravine = self.ravines(chunk_x + dx, chunk_z + dz)

                if ravine is None:
                    continue

                segments, walls = ravine
                x, z, r = segments[:, 0], segments[:, 2], segments[:, 3]
                touches = (x + r > x0) & (x - r < x0 + CHUNK) & (z + r > z0) & (z - r < z0 + CHUNK)

                if touches.any():
                    found.append((segments[touches], walls))

        return found

    def carve_ravines(self, ids, chunk_x, chunk_z, y_min, keep, lava):
        x0, z0 = chunk_x * CHUNK, chunk_z * CHUNK
        height = ids.shape[1]
        water = keep[0]

        for segments, walls in self.nearby_ravines(chunk_x, chunk_z):
            for cx, cy, cz, radius, vertical in segments:
                lx0 = max(0, math.floor(cx - radius) - x0)
                lx1 = min(CHUNK, math.ceil(cx + radius) - x0 + 1)
                lz0 = max(0, math.floor(cz - radius) - z0)
                lz1 = min(CHUNK, math.ceil(cz + radius) - z0 + 1)
                ly0 = max(1, math.floor(cy - vertical) - y_min)
                ly1 = min(height - 1, math.ceil(cy + vertical) - y_min + 1)

                if lx0 >= lx1 or lz0 >= lz1 or ly0 >= ly1:
                    continue

                if np.any(ids[lx0:lx1, ly0 - 1:ly1 + 1, lz0:lz1] == water):
                    continue

                gx = (np.arange(lx0, lx1) + x0 + 0.5 - cx) / radius
                world_y = np.arange(ly0, ly1) + y_min
                gy = (world_y + 0.5 - cy) / vertical
                gz = (np.arange(lz0, lz1) + z0 + 0.5 - cz) / radius

                # Множитель стенки берётся по высоте оригинала.
                wall = walls[np.clip(SEA - world_y, 0, 127)]
                flat = gx[:, None, None] ** 2 + gz[None, None, :] ** 2
                inside = flat * wall[None, :, None] + (gy ** 2 / 6.0)[None, :, None] < 1.0

                region = ids[lx0:lx1, ly0:ly1, lz0:lz1]
                carve = inside & ~np.isin(region, keep)
                region[carve] = 0

                if lava is not None:
                    lava_y, lava_id = lava
                    region[carve & (world_y >= lava_y)[None, :, None]] = lava_id

    def carved_at(self, x, y, z):
        """Вырезана ли пещерой клетка мира: чтобы деревья не росли над пустотой."""
        for cx, cy, cz, radius, vertical in self.nearby(x // CHUNK, z // CHUNK):
            gx = (x + 0.5 - cx) / radius
            gy = (y + 0.5 - cy) / vertical
            gz = (z + 0.5 - cz) / radius

            if gx * gx + gy * gy + gz * gz < 1.0 and gy < FLOOR:
                return True

        for segments, walls in self.nearby_ravines(x // CHUNK, z // CHUNK):
            wall = walls[min(127, max(0, SEA - y))]

            for cx, cy, cz, radius, vertical in segments:
                gx = (x + 0.5 - cx) / radius
                gy = (y + 0.5 - cy) / vertical
                gz = (z + 0.5 - cz) / radius

                if (gx * gx + gz * gz) * wall + gy * gy / 6.0 < 1.0:
                    return True

        return False
