"""Рука от первого лица: держит блок, а с пустым слотом видна сама рука.

Меши строятся один раз в пространстве руки: начало координат в точке, где
держится блок, ось Y вниз, Z вперёд. Взмах, смена предмета и покачивание
при ходьбе накладываются каждый кадр одним поворотом и сдвигом.
"""
import math
import os

import numpy as np
import pygame

from block import Block
from chunk import Chunk
from items import flat_texture
from mesh import Mesh
from world import World

SCALE = 0.42
YAW = math.radians(-12)
PITCH = math.radians(10)

# Рука: брусок модели игрока 4x12x4 пикселя (пиксель = 1/16 блока).
ARM_TEXTURE = "generated:arm"
ARM_BOX_LOW = (-3, -2, -2)
ARM_BOX_SIZE = (4, 12, 4)
# Точка крепления правой руки к телу в пикселях модели.
ARM_PIVOT = (-5, 2, 0)

# Как рука стоит от первого лица: цепочка сдвигов (в блоках) и поворотов
# (в градусах) в пространстве вида, где y вверх, а камера смотрит в -z.
# Это положение классической руки от первого лица: почти вертикально
# снизу справа, кулак тянется вверх и вглубь экрана.
ARM_VIEW_STEPS = (
    ("move", (0.64, -0.6, -0.72)),
    ("turn", "y", 45),
    ("move", (-1.0, 3.6, 3.5)),
    ("turn", "z", 120),
    ("turn", "x", 200),
    ("turn", "y", -135),
    ("move", (5.6, 0.0, 0.0)),
)

# Файл скина 64x64 (или старый 64x32). Берётся первый найденный:
# свой скин можно положить в textures/skin.png.
SKIN_FILES = (
    "textures/skin.png",
    "assets/minecraft/textures/entity/player/wide/steve.png",
)

# Боковины правой руки в развёртке скина: столбец нашей развёртки -> x в скине.
# Грань +a это +x модели (внутренняя сторона руки), +b это +z (спина),
# -a снаружи, -b спереди. Строки в скине идут от плеча (y = 20) к кисти.
SKIN_SIDES = {0: 48, 4: 52, 8: 40, 12: 44}
# Слой рукава в скинах 64x64 лежит на 16 пикселей ниже основного.
SKIN_SLEEVE_OFFSET = 16

SKIN = (201, 148, 112)
SLEEVE = (54, 92, 126)
SLEEVE_ROWS = 4

SWING_TIME = 0.3
EQUIP_TIME = 0.15
EQUIP_DROP = 0.6

# Покачивание при ходьбе: шагов в секунду и размах.
BOB_STEPS = 1.8
BOB_X = 0.035
BOB_Y = 0.03
BOB_RESPONSE = 8


def rotation_x(angle):
    cos, sin = math.cos(angle), math.sin(angle)

    return np.array([[1, 0, 0], [0, cos, -sin], [0, sin, cos]], dtype=np.float32)


def rotation_y(angle):
    cos, sin = math.cos(angle), math.sin(angle)

    return np.array([[cos, 0, sin], [0, 1, 0], [-sin, 0, cos]], dtype=np.float32)


def rotation_z(angle):
    cos, sin = math.cos(angle), math.sin(angle)

    return np.array([[cos, -sin, 0], [sin, cos, 0], [0, 0, 1]], dtype=np.float32)


def rotation():
    return rotation_x(PITCH) @ rotation_y(YAW)


def make_arm_texture():
    """Развёртка руки 16x16: четыре боковины по 4x12, под ними торцы 4x4.

    Боковины: строка 0 у кулака, последние строки у плеча закрыты рукавом.
    Торцы: кулак в (0, 12), плечо в (4, 12).
    """
    random = np.random.default_rng(7)

    # surfarray индексирует пиксели как [x, y].
    pixels = np.empty((16, 16, 3), dtype=np.float32)
    pixels[:] = SKIN

    pixels[:, 12 - SLEEVE_ROWS:12] = SLEEVE
    pixels[:, 12 - SLEEVE_ROWS] = np.array(SLEEVE) * 0.8
    pixels[4:8, 12:16] = SLEEVE

    # Костяшки на кулаке и у его края немного темнее.
    pixels[0:4, 12:16] *= 0.9
    pixels[:, 0] *= 0.94

    pixels *= random.uniform(0.94, 1.05, (16, 16, 1))

    surface = pygame.Surface((16, 16))
    pygame.surfarray.blit_array(surface, pixels.clip(0, 255).astype(np.uint8))

    return surface


def skin_arm_texture(path):
    """Развёртка руки из файла скина в том же формате, что make_arm_texture."""
    skin = pygame.image.load(path)

    if skin.get_width() != 64 or skin.get_height() not in (32, 64):
        print(f"Скин {path} должен быть 64x64 или 64x32, используется рука по умолчанию.")
        return None

    atlas = pygame.Surface((16, 16))
    layers = [0, SKIN_SLEEVE_OFFSET] if skin.get_height() == 64 else [0]

    # Второй слой (рукав) рисуется поверх основного с учётом прозрачности.
    for offset in layers:
        for column, skin_x in SKIN_SIDES.items():
            side = skin.subsurface((skin_x, 20 + offset, 4, 12))

            # В скине плечо сверху, а у нас строка 0 у кулака.
            atlas.blit(pygame.transform.flip(side, False, True), (column, 0))

        atlas.blit(skin.subsurface((48, 16 + offset, 4, 4)), (0, 12))
        atlas.blit(skin.subsurface((44, 16 + offset, 4, 4)), (4, 12))

    return atlas


def load_arm_texture():
    for path in SKIN_FILES:
        if os.path.exists(path):
            texture = skin_arm_texture(path)

            if texture is not None:
                return texture

    return make_arm_texture()


def texel(x, y):
    # Чуть меньше 16: UV = 1.0 растеризатор заворачивает в 0.
    return min(x, 15.99) / 16, min(y, 15.99) / 16


# Грани бруска в параметрах (a, b, t): a и b поперёк руки, t от кулака к плечу.
# Начало и два ребра выбраны так, что нормаль смотрит наружу,
# иначе растеризатор отбросит грань как заднюю.
ARM_FACES = (
    ("+a", (1, 0, 0), (0, 1, 0), (0, 0, 1)),
    ("-a", (0, 0, 0), (0, 0, 1), (0, 1, 0)),
    ("+b", (0, 1, 0), (0, 0, 1), (1, 0, 0)),
    ("-b", (0, 0, 0), (1, 0, 0), (0, 0, 1)),
    ("shoulder", (0, 0, 1), (1, 0, 0), (0, 1, 0)),
    ("fist", (0, 0, 0), (0, 1, 0), (1, 0, 0)),
)

SIDE_COLUMNS = {"+a": 0, "+b": 4, "-a": 8, "-b": 12}


def arm_uv(face, a, b, t):
    if face in ("+a", "-a"):
        return texel(SIDE_COLUMNS[face] + b * 4, t * 12)

    if face in ("+b", "-b"):
        return texel(SIDE_COLUMNS[face] + a * 4, t * 12)

    column = 4 if face == "shoulder" else 0

    return texel(column + a * 4, 12 + b * 4)


def view_turn(axis, degrees):
    angle = math.radians(degrees)
    cos, sin = math.cos(angle), math.sin(angle)
    matrix = np.identity(4)

    if axis == "x":
        matrix[1:3, 1:3] = [[cos, -sin], [sin, cos]]
    elif axis == "y":
        matrix[0, 0], matrix[0, 2], matrix[2, 0], matrix[2, 2] = cos, sin, -sin, cos
    else:
        matrix[0:2, 0:2] = [[cos, -sin], [sin, cos]]

    return matrix


def view_matrix(steps):
    """Цепочка сдвигов, поворотов и масштабов в одну матрицу 4x4 (как стек матриц)."""
    matrix = np.identity(4)

    for step in steps:
        if step[0] == "move":
            shift = np.identity(4)
            shift[:3, 3] = step[1]
            matrix = matrix @ shift
        elif step[0] == "scale":
            matrix = matrix @ np.diag([step[1], step[1], step[1], 1.0])
        else:
            matrix = matrix @ view_turn(step[1], step[2])

    return matrix


def to_camera(matrix, point):
    """Точку модели через матрицу в координаты камеры: y вниз и z вперёд вместо y вверх и -z."""
    x, y, z, _ = matrix @ np.array((*point, 1.0))

    return (x, -y, -z)


def arm_view_matrix():
    """Из пикселей модели руки в пространство вида (y вверх, взгляд в -z)."""
    matrix = view_matrix(ARM_VIEW_STEPS)

    # Крепление к телу и перевод пикселей в блоки.
    pivot = np.identity(4)
    pivot[:3, 3] = np.array(ARM_PIVOT) / 16
    scale = np.diag([1 / 16, 1 / 16, 1 / 16, 1])

    return matrix @ pivot @ scale


def make_arm_mesh(texture):
    """Брусок руки сразу в координатах камеры: x вправо, y вниз, z вперёд."""
    matrix = arm_view_matrix()
    (low_x, low_y, low_z), (size_x, size_y, size_z) = ARM_BOX_LOW, ARM_BOX_SIZE

    def corner(a, b, t):
        # a и b поперёк руки, t от кулака (низ модели) к плечу (верх модели).
        model = np.array((low_x + a * size_x, low_y + (1 - t) * size_y, low_z + b * size_z, 1.0))
        x, y, z, _ = matrix @ model

        # Вид: y вверх и взгляд в -z, у нас y вниз и z вперёд.
        return (x, -y, -z)

    points, triangles, uvs = [], [], []

    for face, origin, first, second in ARM_FACES:
        params = [
            np.add(origin, step)
            for step in ((0, 0, 0), first, np.add(first, second), second)
        ]

        start = len(points)
        points.extend(corner(*param) for param in params)

        quad = [arm_uv(face, *param) for param in params]

        triangles.append((start, start + 1, start + 2))
        triangles.append((start, start + 2, start + 3))

        uvs.append((quad[0], quad[1], quad[2]))
        uvs.append((quad[0], quad[2], quad[3]))

    mesh = Mesh(points, triangles, uvs, texture)

    # Вершины руки в координатах камеры. Блоки в руке хранятся относительно
    # точки, где их держат, поэтому эту точку вычитаем при отрисовке.
    return mesh, np.ascontiguousarray(mesh.points, dtype=np.float32)


# Как плоский предмет держат от первого лица в ранних версиях: та же цепочка, что
# у руки, в пространстве вида (y вверх, взгляд в -z). Сама картинка лежит в
# квадрате от 0 до 1 и выдавлена на пиксель назад.
ITEM_VIEW_STEPS = (
    ("move", (0.56, -0.52, -0.72)),
    ("turn", "y", 45),
    ("scale", 0.4),
    ("move", (0.0, -0.3, 0.0)),
    ("scale", 1.5),
    ("turn", "y", 50),
    ("turn", "z", 335),
    ("move", (-0.9375, -0.0625, 0.0)),
)

ITEM_PIXELS = 16
ITEM_THICKNESS = 1 / ITEM_PIXELS


def item_uv(u, v):
    # UV = 1.0 растеризатор заворачивает в 0, поэтому чуть меньше.
    return min(max(u, 0.0), 0.9999), min(max(v, 0.0), 0.9999)


def flat_item_quads():
    """Четырёхугольники выдавленной картинки: (углы, UV углов, наружная нормаль).

    Картинка лежит зеркально, как в исходном коде старых версий: x = 0 это правый
    край текстуры, y = 0 нижний. При этой постановке к камере обращена обратная
    сторона, поэтому в руке предмет выглядит как его иконка, наклонённая к экрану:
    рукоять внизу, клинок или голова инструмента вверху справа. Кроме лицевой и обратной стороны у каждого столбца и строки
    пикселей есть по два узких торца: прозрачные пиксели торцов отсекутся,
    и у предмета останутся рёбра ровно по его контуру.
    """
    depth = -ITEM_THICKNESS

    def face_uv(x, y):
        return item_uv(1 - x, 1 - y)

    square = [(0, 0), (1, 0), (1, 1), (0, 1)]
    quads = [
        ([(x, y, 0) for x, y in square], [face_uv(x, y) for x, y in square], (0, 0, 1)),
        ([(x, y, depth) for x, y in square], [face_uv(x, y) for x, y in square], (0, 0, -1)),
    ]

    for index in range(ITEM_PIXELS):
        middle = (index + 0.5) / ITEM_PIXELS

        for edge, normal in ((index / ITEM_PIXELS, -1), ((index + 1) / ITEM_PIXELS, 1)):
            # Торец вдоль y на этом столбце: текстура берётся из самого столбца.
            corners = [(edge, 0, depth), (edge, 0, 0), (edge, 1, 0), (edge, 1, depth)]
            quads.append((corners, [item_uv(1 - middle, 1 - y) for _, y, _ in corners], (normal, 0, 0)))

            # Торец вдоль x на этой строке.
            corners = [(0, edge, depth), (1, edge, depth), (1, edge, 0), (0, edge, 0)]
            quads.append((corners, [item_uv(1 - x, 1 - middle) for x, _, _ in corners], (0, normal, 0)))

    return quads


def flat_item_geometry():
    """Вершины, треугольники и UV выдавленной картинки в её квадрате (y вверх).

    Обход граней уже по наружной нормали: растеризатор рисует только грани,
    обращённые к камере. Используется и рукой, и предметами, лежащими в мире.
    """
    points, triangles, uvs = [], [], []

    for corners, quad_uv, normal in flat_item_quads():
        a, b, c = (np.array(corner, dtype=float) for corner in corners[:3])

        if np.dot(np.cross(b - a, c - a), normal) < 0:
            corners, quad_uv = corners[::-1], quad_uv[::-1]

        start = len(points)
        points.extend(corners)

        triangles += [(start, start + 1, start + 2), (start, start + 2, start + 3)]
        uvs += [(quad_uv[0], quad_uv[1], quad_uv[2]), (quad_uv[0], quad_uv[2], quad_uv[3])]

    return points, triangles, uvs


def make_flat_item(texture):
    """Предмет из картинки, выдавленный на пиксель, сразу в координатах камеры."""
    matrix = view_matrix(ITEM_VIEW_STEPS)
    points, triangles, uvs = flat_item_geometry()

    mesh = Mesh([to_camera(matrix, point) for point in points], triangles, uvs, texture)

    # Как и рука, вершины уже в координатах камеры.
    return [(mesh, np.ascontiguousarray(mesh.points, dtype=np.float32))]


class Hand:
    def __init__(self, engine):
        self.engine = engine
        self.meshes = {}

        self.held = None
        self.swing_time = None
        self.equip = 0.0
        self.bob_phase = 0.0
        self.bob_amount = 0.0

    def get_meshes(self, block_type):
        """Возвращает пары (меш, вершины) в пространстве руки. None значит пустую руку."""
        if block_type not in self.meshes:
            if block_type is None:
                texture = self.engine.add_texture(ARM_TEXTURE, load_arm_texture())
                self.meshes[None] = [make_arm_mesh(texture)]
            elif flat_texture(block_type) is not None:
                # Плоские предметы и двери: в руке это картинка, выдавленная на пиксель.
                texture = self.engine.load_texture(flat_texture(block_type))
                self.meshes[block_type] = make_flat_item(texture)
            else:
                self.meshes[block_type] = self.make_block_meshes(block_type)

        return self.meshes[block_type]

    def make_block_meshes(self, block_type):
        """Блок по центру, уже повёрнутый для руки. Меш тот же, что в мире."""
        chunk = Chunk(0, 0)
        scale = SCALE

        chunk.set_block(0, 0, 0, Block(block_type))

        world = World()
        world.add_chunk(chunk)

        parts = chunk.build_mesh(world)

        # Центр по всем вершинам: у тонкой створки он не в середине клетки.
        every_point = np.concatenate([np.array(data['points']) for data in parts.values()])
        center = (every_point.min(axis=0) + every_point.max(axis=0)) / 2

        meshes = []

        for texture_name, data in parts.items():
            mesh = Mesh(
                data['points'],
                data['triangles'],
                data['uvs'],
                self.engine.load_texture(texture_name),
                data.get('shades')
            )

            points = (mesh.points - center) * scale @ rotation().T

            meshes.append((mesh, np.ascontiguousarray(points, dtype=np.float32)))

        return meshes

    def swing(self):
        self.swing_time = 0.0

    def update(self, dt, held, walking):
        # Новый предмет поднимается снизу.
        if held != self.held:
            self.held = held
            self.equip = 1.0

        self.equip = max(0.0, self.equip - dt / EQUIP_TIME)

        if self.swing_time is not None:
            self.swing_time += dt

            if self.swing_time >= SWING_TIME:
                self.swing_time = None

        # Размах покачивания плавно растёт и затухает, а не обрывается.
        target = 1.0 if walking else 0.0
        self.bob_amount += (target - self.bob_amount) * min(1.0, dt * BOB_RESPONSE)

        if walking:
            self.bob_phase += dt * BOB_STEPS * math.pi

    def pose(self):
        """Поворот и сдвиг руки в этом кадре."""
        turn = np.identity(3, dtype=np.float32)
        x = y = z = 0.0

        if self.swing_time is not None:
            progress = self.swing_time / SWING_TIME
            arc = math.sin(progress * math.pi)
            fast = math.sin(math.sqrt(progress) * math.pi)

            # Быстрый выпад к центру экрана и вперёд, затем плавный возврат.
            x -= 0.32 * fast
            y -= 0.14 * math.sin(math.sqrt(progress) * 2 * math.pi)
            z += 0.12 * arc

            turn = rotation_y(-0.5 * fast) @ rotation_x(0.4 * arc) @ rotation_z(-0.25 * fast)

        x += BOB_X * math.sin(self.bob_phase) * self.bob_amount
        y += BOB_Y * abs(math.cos(self.bob_phase)) * self.bob_amount
        y += EQUIP_DROP * self.equip

        return turn, np.array((x, y, z), dtype=np.float32)

    def render(self, block_type, screen, brightness=1.0):
        """brightness: свет там, где стоит игрок. В темноте и рука тёмная."""
        turn, shift = self.pose()

        # Рука и плоские предметы заданы в координатах камеры, блоки — от точки хвата.
        absolute = block_type is None or flat_texture(block_type) is not None
        anchor = self.engine.hand_offset(screen) if absolute else 0

        meshes = [
            (mesh, np.ascontiguousarray((points - anchor) @ turn.T + shift, dtype=np.float32))
            for mesh, points in self.get_meshes(block_type)
        ]

        self.engine.render_held_block(meshes, screen, brightness)
