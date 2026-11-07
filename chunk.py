"""Чанк: столб мира 16x16 блоков на всю высоту мира.

Блоки хранятся массивом номеров из block.PALETTE, по осям [x, y - Y_MIN, z].
Ось Y направлена вниз: Y_MIN это потолок мира, Y_MAX его дно.

Свет не хранится: он считается заново при каждой постройке меша по самому
чанку и восьми соседям. Дальше 15 блоков свет не доходит, поэтому соседей
хватает, чтобы свет внутри чанка вышел точным.
"""
import numpy as np

import mesher
from block import MAX_LIGHT, PALETTE, TORCH_BOX, TORCH_TEXTURE, TORCHES, Block, block_id, ids_where
from door import DOORS, door_box, door_texture, door_uv
from textures import texture_path

# Высота мира. Ниже Y_MAX пустота (см. VOID_Y у игрока), выше Y_MIN строить нельзя.
Y_MIN = -128
Y_MAX = 127
HEIGHT = Y_MAX - Y_MIN + 1


def in_height(y):
    return Y_MIN <= y <= Y_MAX


def box_face(face, low, high):
    """Вершины грани коробки в том же порядке обхода, что и у граней жадного меша."""
    x0, y0, z0 = low
    x1, y1, z1 = high

    return {
        "top":    [(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)],
        "bottom": [(x0, y1, z0), (x0, y1, z1), (x1, y1, z1), (x1, y1, z0)],
        "front":  [(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)],
        "back":   [(x0, y0, z0), (x0, y1, z0), (x1, y1, z0), (x1, y0, z0)],
        "right":  [(x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1)],
        "left":   [(x0, y0, z0), (x0, y0, z1), (x0, y1, z1), (x0, y1, z0)],
    }[face]


# Стороны в том порядке, в каком их перебирает mesher.greedy_quads.
MESH_FACES = ("top", "bottom", "front", "back", "right", "left")

# Как прямоугольник маски превращается в четырёхугольник: для каждой стороны
# какая ось у size_a и size_b, углы в долях размеров и UV в тех же долях.
# Порядок вершин и UV такой же, как был у меша на Python: текстуры лежат как раньше.
QUAD_SHAPES = {
    "top":    ((1, 0, 0), (0, 0, 1), ((0, 0), (1, 0), (1, 1), (0, 1)), ((0, 1), (1, 1), (1, 0), (0, 0))),
    "bottom": ((1, 0, 0), (0, 0, 1), ((0, 0), (0, 1), (1, 1), (1, 0)), ((0, 0), (0, 1), (1, 1), (1, 0))),
    "front":  ((1, 0, 0), (0, 1, 0), ((0, 0), (1, 0), (1, 1), (0, 1)), ((1, 0), (0, 0), (0, 1), (1, 1))),
    "back":   ((1, 0, 0), (0, 1, 0), ((0, 0), (0, 1), (1, 1), (1, 0)), ((0, 0), (0, 1), (1, 1), (1, 0))),
    "right":  ((0, 0, 1), (0, 1, 0), ((0, 0), (0, 1), (1, 1), (1, 0)), ((0, 0), (0, 1), (1, 1), (1, 0))),
    "left":   ((0, 0, 1), (0, 1, 0), ((0, 0), (1, 0), (1, 1), (0, 1)), ((1, 0), (0, 0), (0, 1), (1, 1))),
}

QUAD_TRIANGLES = np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int32)
# Тот же четырёхугольник, разрезанный по другой диагонали. Её выбирают, когда
# яркость сильнее меняется вдоль первой: иначе тень в углу легла бы косо.
FLIPPED_TRIANGLES = np.array([[0, 1, 3], [1, 2, 3]], dtype=np.int32)

# Множитель стороны грани, как в оригинале: верх светлее всех, низ темнее всех.
FACE_SHADE = {"top": 1.0, "bottom": 0.5, "front": 0.8, "back": 0.8, "right": 0.6, "left": 0.6}
FACE_SHADES = np.array([FACE_SHADE[face] for face in MESH_FACES], dtype=np.float64)

# Яркость уровня света. Кривая как в оригинале (тусклые уровни темнее
# линейных), наполовину смешанная с прямой, чтобы полумрак был различим.
# Даже в полной темноте немного видно.
AMBIENT = 0.08


def light_curve(level):
    dark = 1 - level / MAX_LIGHT
    curve = (1 - dark) / (dark * 3 + 1)
    mixed = 0.6 * curve + 0.4 * level / MAX_LIGHT

    return AMBIENT + (1 - AMBIENT) * mixed


BRIGHTNESS = np.array([light_curve(level) for level in range(MAX_LIGHT + 1)], dtype=np.float64)

# Свет в чанке хранится байтом: младшие четыре бита от неба, старшие от блоков.
# Яркость байта: по большему из двух уровней.
PACKED_BRIGHTNESS = np.array([BRIGHTNESS[max(value & 15, value >> 4)] for value in range(256)], dtype=np.float64)


def light_level(packed):
    return max(packed & 15, packed >> 4)

# Мягкий свет: яркость плавно меняется по грани и в углах ложится тень.
# Без него у каждой грани одна яркость, как в старых версиях. Меняет игра.
smooth_lighting = True

# Половина области света: чанк и по 15 клеток соседей с каждой стороны.
LIGHT_MARGIN = 15

# Углы четырёхугольника в долях (a, b) и их номера у яркостей из мешера.
CORNER_INDEX = {(0, 0): 0, (1, 0): 1, (1, 1): 2, (0, 1): 3}

# Пути текстур граней по номерам: в таблицах мешера вместо строк номера.
TEXTURES = []
_texture_numbers = {}
_tables = None


def texture_number(path):
    if path not in _texture_numbers:
        _texture_numbers[path] = len(TEXTURES)
        TEXTURES.append(path)

    return _texture_numbers[path]


def mesh_tables():
    """Свойства блоков по номерам для мешера. Пересобираются, когда палитра выросла."""
    global _tables

    if _tables is not None and _tables[0] == len(PALETTE):
        return _tables[1:]

    count = len(PALETTE)
    opacity = np.zeros(count, dtype=np.uint8)
    emission = np.zeros(count, dtype=np.uint8)
    cube = np.zeros(count, dtype=np.uint8)
    opaque = np.zeros(count, dtype=np.uint8)
    kind = np.zeros(count, dtype=np.int32)
    face_tex = np.full((count, len(MESH_FACES)), -1, dtype=np.int32)
    kinds = {}

    for number, block in enumerate(PALETTE):
        if block is None:
            continue

        cube[number] = block.is_cube
        opaque[number] = block.is_opaque
        opacity[number] = block.light_opacity
        emission[number] = block.light_emission
        kind[number] = kinds.setdefault(block.type, len(kinds) + 1)

        if block.is_cube:
            for index, face in enumerate(MESH_FACES):
                face_tex[number, index] = texture_number(Block.get_block_texture(block, face))

    _tables = (count, cube, opaque, kind, face_tex, opacity, emission)

    return _tables[1:]


def quads_to_mesh(quads, corner_shades, y_base):
    """Прямоугольники мешера в данные мешей по текстурам: {путь: {points, triangles, uvs, shades}}."""
    points, uvs, shades, textures = [], [], [], []

    for index, face in enumerate(MESH_FACES):
        selected = quads[:, 0] == index
        rows = quads[selected]

        if not len(rows):
            continue

        fixed, a, b, size_a, size_b = (rows[:, column].astype(np.float32) for column in range(1, 6))

        if index < 2:
            y = fixed + y_base
            origin = np.stack([a, y + (index == 1), b], axis=1)
        elif index < 4:
            origin = np.stack([a, b + y_base, fixed + (index == 2)], axis=1)
        else:
            origin = np.stack([fixed + (index == 4), b + y_base, a], axis=1)

        axis_a, axis_b, corners, corner_uvs = (np.array(part, dtype=np.float32) for part in QUAD_SHAPES[face])

        along_a = corners[None, :, 0, None] * size_a[:, None, None] * axis_a
        along_b = corners[None, :, 1, None] * size_b[:, None, None] * axis_b

        points.append(origin[:, None, :] + along_a + along_b)
        uvs.append(corner_uvs[None, :, :] * np.stack([size_a, size_b], axis=1)[:, None, :])
        order = [CORNER_INDEX[tuple(corner)] for corner in QUAD_SHAPES[face][2]]
        shades.append(corner_shades[selected][:, order])
        textures.append(rows[:, 6])

    if not points:
        return {}

    points = np.concatenate(points)
    uvs = np.concatenate(uvs)
    shades = np.concatenate(shades).astype(np.float32) / 255
    textures = np.concatenate(textures)

    mesh_data = {}

    for texture in np.unique(textures):
        selected = textures == texture
        quad_points = points[selected]
        quad_uvs = uvs[selected]
        quad_shades = shades[selected]
        count = len(quad_points)

        # Диагональ, вдоль которой яркость меняется меньше.
        flip = np.abs(quad_shades[:, 0] - quad_shades[:, 2]) > np.abs(quad_shades[:, 1] - quad_shades[:, 3])
        local = np.where(flip[:, None, None], FLIPPED_TRIANGLES, QUAD_TRIANGLES)

        triangles = (np.arange(count, dtype=np.int32)[:, None, None] * 4 + local).reshape(-1, 3)
        triangle_uvs = np.take_along_axis(quad_uvs[:, None, :, :], local[:, :, :, None], axis=2).reshape(-1, 3, 2)

        mesh_data[TEXTURES[texture]] = {
            "points": quad_points.reshape(-1, 3),
            "triangles": triangles,
            "uvs": triangle_uvs,
            "shades": quad_shades.reshape(-1),
        }

    return mesh_data


def add_box(mesh_data, texture, low, high, position, uv_of, shade_of, hidden=()):
    """Коробка (дверь, факел) гранями в данные меша. Текстур таких моделей у кубов
    не бывает, поэтому здесь всегда списки, а не массивы мешера.

    uv_of(face, x, y, z): UV угла по его координатам в клетке, shade_of(face): яркость грани.
    """
    data = mesh_data.setdefault(texture, {"points": [], "triangles": [], "uvs": [], "shades": []})
    x, y, z = position

    for face in MESH_FACES:
        if face in hidden:
            continue

        corners = box_face(face, low, high)
        uvs = [uv_of(face, *corner) for corner in corners]
        shade = shade_of(face)

        start = len(data["points"])

        data["points"].extend((x + cx, y + cy, z + cz) for cx, cy, cz in corners)
        data["shades"].extend([shade] * 4)

        data["triangles"].append((start, start + 1, start + 2))
        data["triangles"].append((start, start + 2, start + 3))

        data["uvs"].append((uvs[0], uvs[1], uvs[2]))
        data["uvs"].append((uvs[0], uvs[2], uvs[3]))


def cell_uv(face, x, y, z):
    """UV точки грани по её координатам внутри клетки, в тех же направлениях, что у блоков."""
    if face == "top":
        return x, 1 - z
    if face == "bottom":
        return x, z
    if face == "front":
        return 1 - x, y
    if face == "back":
        return x, y
    if face == "right":
        return z, y

    return 1 - z, y


class Chunk:
    SIZE = 16

    def __init__(self, chunk_x, chunk_z, ids=None):
        self.chunk_x = chunk_x
        self.chunk_z = chunk_z
        self.ids = ids if ids is not None else np.zeros((self.SIZE, HEIGHT, self.SIZE), dtype=np.uint16)
        self.dirty = False

        # Построены ли меши чанка. В бесконечном мире у дальних чанков их нет.
        self.meshed = False

        # Свет с последней постройки меша: [x + 1, y - light_top, z + 1], с рамкой
        # в клетку из соседей. None, пока меша не было.
        self.light = None
        self.light_top = 0

    def packed_light(self, x, y, z):
        """Байт света клетки (x, z от -1 до 16 считая рамку): небо в младших битах."""
        if self.light is None:
            return MAX_LIGHT

        row = y - self.light_top

        if row < 0:
            return MAX_LIGHT

        if row >= self.light.shape[1]:
            return 0

        return int(self.light[x + 1, row, z + 1])

    def light_at(self, x, y, z):
        """Уровень света 0..15 в клетке: больший из небесного и от блоков. Выше всего небо."""
        return light_level(self.packed_light(x, y, z))

    def sky_light_at(self, x, y, z):
        return self.packed_light(x, y, z) & 15

    def set_block(self, x, y, z, block):
        """Выше потолка и ниже дна мира блоки не ставятся."""
        if Y_MIN <= y <= Y_MAX:
            self.ids[x, y - Y_MIN, z] = block_id(block)
            self.dirty = True

    def remove_block(self, x, y, z):
        if Y_MIN <= y <= Y_MAX:
            self.ids[x, y - Y_MIN, z] = 0
            self.dirty = True

    def get_block(self, x, y, z):
        if Y_MIN <= y <= Y_MAX:
            return PALETTE[self.ids[x, y - Y_MIN, z]]

        return None

    def cells(self, numbers=None):
        """Клетки ((x, y, z), блок) со всеми блоками или только с номерами из numbers."""
        if numbers is None:
            xs, ys, zs = np.nonzero(self.ids)
        else:
            xs, ys, zs = np.nonzero(np.isin(self.ids, numbers))

        values = self.ids[xs, ys, zs].tolist()

        for x, y, z, number in zip(xs.tolist(), ys.tolist(), zs.tolist(), values):
            yield (x, y + Y_MIN, z), PALETTE[number]

    def is_empty(self):
        return not self.ids.any()

    def light_region(self, world):
        """Номера блоков чанка и восьми соседей с запасом строк сверху и снизу.

        Возвращает (объём [x, y, z] шириной 48, y первой строки) или None,
        если в чанке и вокруг пусто. Незагруженные соседи считаются воздухом.
        """
        size = self.SIZE
        neighbours = []
        first, last = HEIGHT, -1

        for dx in (-1, 0, 1):
            for dz in (-1, 0, 1):
                chunk = world.get_chunk(self.chunk_x + dx, self.chunk_z + dz)

                if chunk is None:
                    continue

                filled = np.flatnonzero(chunk.ids.any(axis=(0, 2)))

                if len(filled):
                    first = min(first, int(filled[0]))
                    last = max(last, int(filled[-1]))
                    neighbours.append((dx, dz, chunk))

        if last < 0 or not self.ids.any():
            return None

        # Строка воздуха над всем и под всем: и для света, и для граней у краёв.
        low, high = max(first - 1, 0), min(last + 1, HEIGHT - 1)
        start = low - (first - 1)
        rows = slice(start, start + high - low + 1)

        region = np.zeros((size * 3, last - first + 3, size * 3), dtype=np.uint16)

        for dx, dz, chunk in neighbours:
            x0 = (dx + 1) * size
            z0 = (dz + 1) * size
            region[x0:x0 + size, rows, z0:z0 + size] = chunk.ids[:, low:high + 1, :]

        return region, first - 1 + Y_MIN

    def build_mesh(self, world):
        found = self.light_region(world)

        if found is None:
            self.light = None
            return {}

        region, top = found
        cube, opaque, kind, face_tex, opacity, emission = mesh_tables()

        light = mesher.compute_light(region, opacity, emission)

        # Сам чанк с рамкой в клетку: мешеру нужны соседние клетки граней и углов.
        inner = slice(self.SIZE - 1, 2 * self.SIZE + 1)
        volume = np.ascontiguousarray(region[inner, :, inner])
        self.light = np.ascontiguousarray(light[inner, :, inner])
        self.light_top = top

        quads, shades = mesher.greedy_quads(
            volume, self.light, cube, opaque, kind, face_tex, PACKED_BRIGHTNESS, FACE_SHADES, smooth_lighting
        )
        mesh_data = quads_to_mesh(quads, shades, top + 1)

        for (x, y, z), block in self.cells(ids_where(lambda block: block.type in DOORS or block.type in TORCHES)):
            if block.type in TORCHES:
                self.add_torch(mesh_data, x, y, z)
            else:
                self.add_door(mesh_data, world, x, y, z, block)

        return mesh_data

    def flat_shade(self, x, y, z):
        """Яркость грани модели в клетке: свет самой клетки и множитель стороны."""
        brightness = BRIGHTNESS[self.light_at(x, y, z)]

        return lambda face: float(brightness * FACE_SHADE[face])

    def add_torch(self, mesh_data, x, y, z):
        """Факел светится сам, поэтому темнее своей клетки он не бывает."""
        add_box(mesh_data, texture_path(TORCH_TEXTURE), *TORCH_BOX, (x, y, z), cell_uv, lambda face: 1.0)

    def add_door(self, mesh_data, world, x, y, z, block):
        """Створка двери отдельной коробкой: в жадный меш она не попадает."""
        state = block.state
        low, high = door_box(state)

        world_x = self.chunk_x * self.SIZE + x
        world_z = self.chunk_z * self.SIZE + z

        above = world.get_block(world_x, y - 1, world_z)
        below = world.get_block(world_x, y + 1, world_z)

        hidden = set()

        # Между половинками двери грани не видны, а снизу дверь стоит на блоке.
        if state.upper:
            if below is not None and not below.is_cube:
                hidden.add("bottom")
            if above is not None and above.is_opaque:
                hidden.add("top")
        else:
            if above is not None and not above.is_cube:
                hidden.add("top")
            if below is not None and below.is_opaque:
                hidden.add("bottom")

        add_box(
            mesh_data,
            door_texture(block.type, state),
            low,
            high,
            (x, y, z),
            lambda face, cx, cy, cz: door_uv(state, face, cx, cy, cz),
            self.flat_shade(x, y, z),
            hidden
        )

    def greedy_mask(self, mask, size_a, size_b):
        rectangles = []

        used = [
            [False for b in range(size_b)]
            for a in range(size_a)
        ]

        for b in range(size_b):
            for a in range(size_a):

                texture = mask[a][b]

                if texture is None or used[a][b]:
                    continue

                width = 1

                while a + width < size_a:
                    if used[a + width][b]:
                        break

                    if mask[a + width][b] != texture:
                        break

                    width += 1

                height = 1

                while b + height < size_b:
                    can_expand = True

                    for da in range(width):
                        if used[a + da][b + height]:
                            can_expand = False
                            break

                        if mask[a + da][b + height] != texture:
                            can_expand = False
                            break

                    if not can_expand:
                        break

                    height += 1

                for db in range(height):
                    for da in range(width):
                        used[a + da][b + db] = True

                rectangles.append(
                    (a, b, width, height, texture)
                )

        return rectangles
