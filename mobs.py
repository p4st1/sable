"""Мобы: мирные животные (свинья, корова, овца), враждебные зомби, скелет и паук
и жители ада: свинозомби, гаст и ифрит.

Животные появляются стайками на траве, когда генератор создаёт новый чанк
(как в оригинале: мирные мобы не появляются из воздуха рядом с игроком).
Бродят, иногда щиплют траву и смотрят на игрока, после удара убегают,
а умерев, роняют мясо или шерсть.

Модели из брусков в пикселях (1/16 блока), текстуры берутся из ресурс-пака.
Для новых видов доступны и процедурные материалы. Ось Y мира направлена вниз,
позиция моба это середина его ступней. Модель смотрит в +z.
"""
import math
import random
import zlib
from typing import NamedTuple

import numpy as np
import pygame

from chunk import FACE_SHADE, QUAD_TRIANGLES, Y_MIN, Chunk, box_face
from collision import box_touches_blocks, move
from entities import DrawObject
from items import TOOLS
from mesh import Mesh
from water import LAVA, point_in_water

PIXEL = 1 / 16

# Физика: как у игрока, но без настроек.
GRAVITY = 32.0
TERMINAL_VELOCITY = 60.0
JUMP_SPEED = 8.6
MAX_STEP = 0.1
# Насколько быстро скорость догоняет желаемую: на земле резко, в воздухе почти никак,
# поэтому отброс от удара пролетает по воздуху, а на земле гасится.
GROUND_GRIP = 10.0
AIR_GRIP = 0.5
# В воде животное всплывает и гребёт медленнее.
FLOAT_SPEED = 1.5
FLOAT_RESPONSE = 5.0
WATER_SLOWDOWN = 0.5
VOID_Y = 128

# Поворот тела, рад/с, и как далеко голова поворачивается относительно тела.
TURN_SPEED = 6.0
HEAD_TURN_SPEED = 5.0
HEAD_YAW_LIMIT = math.radians(60)
GRAZE_PITCH = math.radians(-50)

# Поведение.
WANDER_RADIUS = 7
WANDER_TIMEOUT = 8.0
IDLE_TIME = (2.0, 7.0)
GRAZE_CHANCE = 0.35
LOOK_DISTANCE = 6.0
LOOK_CHANCE = 0.4
PANIC_TIME = 5.0
PANIC_TURN_TIME = (0.8, 1.8)
STUCK_TIME = 1.0
# С обрыва выше этого животное спокойно не спрыгнет, а развернётся.
SAFE_DROP = 3

# Враждебные: за кем гонятся, с какого расстояния бьют и как часто.
FOLLOW_RANGE = 16.0
# Бьют, когда центр ближе своей полуширины плюс столько.
ATTACK_REACH = 0.9
ATTACK_HEIGHT = 1.5
ATTACK_COOLDOWN = 1.0
# Ближе этого к игроку не подходят: стоят и бьют.
CLOSE_ENOUGH = 0.8
# Скелет стреляет, если видит игрока не дальше SHOOT_RANGE, раз в SHOOT_COOLDOWN
# секунд. Ближе KEEP_DISTANCE не подходит: стоит и стреляет.
SHOOT_RANGE = 16.0
SHOOT_COOLDOWN = 2.0
KEEP_DISTANCE = 6.0
RANGED_APPROACH = 0.6

# Паук лезет по стенам с такой скоростью, а с 2-6 блоков прыгает на игрока.
CLIMB_SPEED = 2.4
LEAP_RANGE = (2.0, 6.0)
LEAP_CHANCE = 2.0
LEAP_SPEED = 8.0
LEAP_LIFT = 6.0
# Днём (свет не ниже NEUTRAL_LIGHT) паук не нападает первым. Разозлённый
# ударом днём иногда успокаивается.
NEUTRAL_LIGHT = 12
CALM_CHANCE = 0.2
# Ноги паука: длина, наклон вниз и как сильно ходят взад-вперёд.
SPIDER_LEG_SWING = 0.35

# На солнце горят: единица урона раз в секунду, вокруг тела пламя (burning.py).
BURN_INTERVAL = 1.0
# Руки зомби вытянуты вперёд и чуть покачиваются.
ARM_RAISE = math.pi / 2 * 0.92
ARM_SWAY = 0.08

# Звуки: голос раз в столько секунд (случайно в промежутке), шаг через
# столько блоков пути. События entity.<вид>.ambient/hurt/death/step из sounds.json.
AMBIENT_INTERVAL = (5.0, 14.0)
STEP_DISTANCE = 1.2

# Удар.
HURT_TIME = 0.5
FLASH_TIME = 0.35
KNOCKBACK = 6.0
KNOCKBACK_LIFT = 5.5
DEATH_TIME = 1.0
FALL_OVER_TIME = 0.4

# Ноги: размах в радианах и сколько радиан фазы на блок пути.
LEG_SWING = 0.8
STRIDE = 5.0

# Раздвигаем животных, стоящих друг в друге.
PUSH_SPEED = 2.0

# Появление: доля новых чанков со стайкой и размер стайки.
SPAWN_CHANCE = 0.2
GROUP_SIZE = (2, 4)
# Сколько мест пробуем для каждого животного: часть столбцов занята деревьями.
SPAWN_TRIES = 4
SPAWN_GROUND = {"grass"}

# Появление враждебных: раз в секунду несколько попыток в кольце вокруг игрока,
# в темноте (уровень света не выше SPAWN_LIGHT с учётом ночи), не больше MAX_HOSTILE
# рядом. Дальше DESPAWN_FAR исчезают сразу, дальше DESPAWN_NEAR иногда.
HOSTILE_SPAWN_INTERVAL = 1.0
HOSTILE_SPAWN_ATTEMPTS = 8
HOSTILE_SPAWN_DISTANCE = (18.0, 40.0)
HOSTILE_SPAWN_HEIGHT = 20
HOSTILE_SPAWN_SCAN = 16
SPAWN_LIGHT = 7
MAX_HOSTILE = 10
DESPAWN_FAR = 72.0
DESPAWN_NEAR = 32.0
DESPAWN_CHANCE = 1 / 30

# Урон по материалу и виду инструмента, рукой 1.
HAND_DAMAGE = 1
# Как в 1.0: меч 4 + уровень материала, топор на 1 слабее, кирка на 2, лопата на 3.
# Золото по урону как дерево.
MATERIAL_DAMAGE = {"wooden": 0, "golden": 0, "stone": 1, "iron": 2, "diamond": 3}
KIND_DAMAGE = {"sword": 4, "axe": 3, "pickaxe": 2, "shovel": 1}


def attack_damage(item):
    if item not in TOOLS:
        return HAND_DAMAGE

    material = item.split("_")[0]

    return KIND_DAMAGE[TOOLS[item].kind] + MATERIAL_DAMAGE.get(material, 0)


# Материалы текстур: основной цвет, сила шума и узор.

class Material(NamedTuple):
    color: tuple
    noise: float = 10.0
    # Пятна второго цвета (у коровы) и их доля.
    patches: tuple = None
    patch_share: float = 0.0
    # Крупные завитки (шерсть).
    curls: bool = False
    # Тёмные полосы через столько строк (рёбра скелета), 0 без них.
    stripes: int = 0


PIG_SKIN = (236, 158, 158)
COW_HIDE = (104, 66, 40)
SHEEP_FACE = (72, 60, 52)
ZOMBIE_SKIN = (128, 152, 112)
BONE = (214, 210, 194)
SPIDER = (40, 36, 34)

MATERIALS = {
    "pig_skin": Material(PIG_SKIN, 9),
    "cow_hide": Material(COW_HIDE, 9, patches=(228, 222, 210), patch_share=0.38),
    "cow_leg": Material((84, 52, 30), 8),
    "wool": Material((234, 230, 220), 7, curls=True),
    "sheep_face": Material(SHEEP_FACE, 7),
    "sheep_leg": Material((60, 50, 44), 6),
    "zombie_skin": Material(ZOMBIE_SKIN, 8),
    "tunic": Material((96, 72, 50), 10, patches=(70, 52, 38), patch_share=0.3),
    "trousers": Material((66, 68, 76), 8),
    "bone": Material(BONE, 7),
    "bone_dark": Material((150, 146, 132), 6),
    "ribs": Material(BONE, 7, stripes=2),
    "bow_wood": Material((112, 76, 40), 8),
    "spider_body": Material(SPIDER, 6, patches=(58, 46, 40), patch_share=0.35),
    "spider_leg": Material((36, 32, 30), 5),
}

TILE = 64
FACES = ("top", "bottom", "front", "back", "right", "left")


def smooth_noise(rng, size, cell):
    """Плавный шум: случайная сетка cell x cell, растянутая до size и сглаженная."""
    coarse = rng.random((cell + 1, cell + 1))
    positions = np.linspace(0, cell, size, endpoint=False)
    whole = positions.astype(int)
    part = positions - whole
    part = part * part * (3 - 2 * part)

    rows = coarse[whole] * (1 - part)[:, None] + coarse[whole + 1] * part[:, None]

    return rows[:, whole] * (1 - part)[None, :] + rows[:, whole + 1] * part[None, :]


def noise_tile(rng, color, noise):
    pixels = np.empty((TILE, TILE, 3), dtype=np.float64)
    pixels[:] = color
    pixels += rng.normal(0, noise, (TILE, TILE))[:, :, None]

    return pixels


# Процедурные морды рисуются прямо на передней грани головы.
# Массив [x, y]: x по ширине грани, y сверху вниз.
# Рисунки симметричны, поэтому не важно, с какой стороны грань развёрнута.

def paint_cow(pixels):
    pixels[3:5, 0:4] = (228, 222, 210)
    pixels[1:7, 4:7] = (206, 168, 138)
    pixels[2, 5] = pixels[5, 5] = (80, 46, 40)
    pixels[1, 2] = pixels[6, 2] = (18, 16, 20)


def paint_sheep(pixels):
    pixels[1, 2] = pixels[4, 2] = (226, 214, 170)
    pixels[2:4, 5] = (40, 32, 28)


def paint_zombie(pixels):
    # Тёмные впалые глазницы с тусклыми зрачками и кривой рот.
    pixels[1:3, 2:4] = (52, 60, 44)
    pixels[4:6, 2:4] = (52, 60, 44)
    pixels[1, 3] = pixels[5, 3] = (150, 40, 30)
    pixels[2:5, 5] = (60, 50, 40)
    pixels[5, 6] = (60, 50, 40)


def paint_skull(pixels):
    # Чёрные глазницы, провал носа и ряд зубов.
    pixels[1:3, 2:4] = (24, 22, 20)
    pixels[4:6, 2:4] = (24, 22, 20)
    pixels[3, 4] = (60, 56, 50)
    pixels[1:6, 6] = (90, 86, 76)
    pixels[2, 6] = pixels[4, 6] = (40, 38, 34)


def paint_spider(pixels):
    # Восемь красных глаз: два больших, шесть мелких, и светлые жвала внизу.
    pixels[1, 1] = pixels[4, 1] = (220, 30, 30)
    pixels[1, 2] = pixels[4, 2] = (150, 20, 20)
    pixels[0, 1] = pixels[5, 1] = (120, 16, 16)
    pixels[2, 0] = pixels[3, 0] = (120, 16, 16)
    pixels[2, 4] = pixels[3, 4] = (170, 160, 140)


# Нарисованная морда: (цвет основы, сила шума, рисунок).
PAINTED = {
    "spider_face": (SPIDER, 6, paint_spider),
    "skull_face": (BONE, 7, paint_skull),
    "zombie_face": (ZOMBIE_SKIN, 8, paint_zombie),
    "cow_face": (COW_HIDE, 9, paint_cow),
    "sheep_face_front": (SHEEP_FACE, 7, paint_sheep),
}


def material_tile(name):
    """Квадрат TILE x TILE пикселей материала: массив [x, y, rgb]."""
    rng = np.random.default_rng(zlib.crc32(name.encode("utf-8")))

    if name in PAINTED:
        color, noise, paint = PAINTED[name]
        pixels = noise_tile(rng, color, noise)
        # Рисунок поверх шума, но тоже чуть неровный.
        painted = pixels.copy()
        paint(painted)
        changed = np.any(painted != pixels, axis=2)
        pixels[changed] = painted[changed] + rng.normal(0, 4, (int(changed.sum()), 1))

        return pixels.clip(0, 255)

    material = MATERIALS[name]
    pixels = noise_tile(rng, (0, 0, 0), 0)
    pixels[:] = material.color

    if material.patches is not None:
        blobs = smooth_noise(rng, TILE, 5) * 0.7 + smooth_noise(rng, TILE, 11) * 0.3
        mask = blobs > np.quantile(blobs, 1 - material.patch_share)
        pixels[mask] = material.patches

    if material.curls:
        curls = smooth_noise(rng, TILE, 16)
        pixels *= (0.86 + 0.2 * curls)[:, :, None]

    if material.stripes:
        pixels[:, 1::material.stripes] *= 0.45

    pixels += rng.normal(0, material.noise, (TILE, TILE))[:, :, None]

    return pixels.clip(0, 255)


# Модели в кубическом стиле. Бруски в пикселях: начало, размер (y вверх от ног, +z вперёд),
# материал, группа и материалы отдельных граней. Группы поворачиваются вокруг своих точек.

class Part(NamedTuple):
    low: tuple
    size: tuple
    material: str
    group: str = "body"
    faces: dict = {}
    # Для готовой текстуры: четыре UV-угла каждой грани в порядке box_face.
    uvs: dict = None
    # Отдельная текстура детали (например, шерсть) и размер её развёртки.
    texture: str = None
    texture_size: tuple = (64, 32)

    def material_of(self, face):
        return self.faces.get(face, self.material)


def box_uvs(offset, size, mirror=False):
    """Развёртка кубоида Minecraft: UV в пикселях, передняя грань смотрит в +z."""
    u, v = offset
    w, h, d = size
    a, b, c, e = u + d, u + d + w, u + 2 * d + w, u + 2 * d + 2 * w
    top, bottom = v + d, v + d + h

    faces = {
        "top": ((a, v), (b, v), (b, top), (a, top)),
        "bottom": ((b, v), (b, top), (b + w, top), (b + w, v)),
        "front": ((a, top), (b, top), (b, bottom), (a, bottom)),
        "back": ((e, top), (e, bottom), (c, bottom), (c, top)),
        "right": ((c, top), (c, bottom), (b, bottom), (b, top)),
        "left": ((u, top), (a, top), (a, bottom), (u, bottom)),
    }

    if mirror:
        # Отражаем по x, в том числе меняем местами боковые грани конечностей.
        reflected = {
            "top": ("top", (1, 0, 3, 2)), "bottom": ("bottom", (3, 2, 1, 0)),
            "front": ("front", (1, 0, 3, 2)), "back": ("back", (3, 2, 1, 0)),
            "right": ("left", (0, 3, 2, 1)), "left": ("right", (0, 3, 2, 1)),
        }
        return {face: tuple(faces[source][index] for index in order) for face, (source, order) in reflected.items()}

    return faces


def horizontal_uvs(offset, size):
    """Развёртка вертикального туловища после поворота в горизонтальное положение."""
    upright = box_uvs(offset, size)

    return {
        "top": upright["back"][1:] + upright["back"][:1],
        "bottom": upright["front"][3:] + upright["front"][:3],
        "front": upright["top"],
        "back": upright["bottom"],
        "right": upright["right"][1:] + upright["right"][:1],
        "left": upright["left"][3:] + upright["left"][:3],
    }


def legs(size, xs, zs, material, uv=None):
    """Четыре ноги: группы leg0..leg3, у каждой точка поворота сверху посередине."""
    parts, pivots = [], {}
    index = 0

    for z in zs:
        for x in xs:
            name = f"leg{index}"
            uvs = None if uv is None else box_uvs(uv, size, mirror=bool(index % 2))
            parts.append(Part((x, 0, z), size, material, name, uvs=uvs))
            pivots[name] = (x + size[0] / 2, size[1], z + size[2] / 2)
            index += 1

    return parts, pivots


class Kind(NamedTuple):
    name: str
    health: int
    half_width: float
    height: float
    walk_speed: float
    panic_speed: float
    # Добыча: (предмет, от, до).
    drops: tuple
    parts: tuple
    pivots: dict
    # Враждебный: гонится за игроком в выживании и бьёт на attack единиц.
    hostile: bool = False
    attack: int = 0
    chase_speed: float = 0.0
    # Горит на солнце.
    burns: bool = False
    # Стреляет из лука вместо удара вблизи.
    ranged: bool = False
    # Паук: лезет по стенам, прыгает на игрока, днём не нападает первым.
    climbs: bool = False
    leaps: bool = False
    daylight_neutral: bool = False
    # Готовая текстура и размер её развёртки; None оставляет процедурные материалы.
    texture: str = None
    texture_size: tuple = (64, 32)
    # Летает (гаст, ифрит): без силы тяжести, плывёт к своей цели.
    flies: bool = False
    # Нейтральный (свинозомби): нападает, только если его или соседей ударили.
    neutral: bool = False
    # Не боится огня и лавы.
    fireproof: bool = False
    # Где появляется: "overworld" или "nether".
    dimension: str = "overworld"
    # Во сколько раз модель больше своих пикселей (гаст огромный).
    scale: float = 1.0
    # Стреляет огненными шарами: "large" как гаст или "small" как ифрит.
    fireballs: str = None
    # Текстура, пока моб готовится выстрелить (гаст открывает глаза).
    charging_texture: str = None


def pig_kind():
    """Классическая свинья: кубическая голова, отдельный пятачок и короткие ноги."""
    leg_parts, leg_pivots = legs((4, 6, 4), (-5, 1), (-9, 3), "pig_skin")
    leg_uvs = box_uvs((0, 16), (4, 6, 4))

    # В развёртке туловище стоит вертикально (10 x 16 x 8), в модели лежит.
    # Поворачиваем и грани, и их UV, чтобы хвост оказался сзади, а спина сверху.
    body_uvs = horizontal_uvs((28, 8), (10, 16, 8))
    # В этом паке область пятачка (16, 16) прозрачна: он нарисован на морде.
    # Берём нос и прилегающую кожу оттуда, сохраняя один texel на пиксель модели.
    snout_uvs = {
        "top": ((10, 11), (14, 11), (14, 12), (10, 12)),
        "bottom": ((10, 15), (10, 16), (14, 16), (14, 15)),
        "front": ((10, 12), (14, 12), (14, 15), (10, 15)),
        "back": ((14, 12), (14, 15), (10, 15), (10, 12)),
        "right": ((15, 12), (15, 15), (14, 15), (14, 12)),
        "left": ((9, 12), (10, 12), (10, 15), (9, 15)),
    }

    parts = (
        Part((-5, 6, -10), (10, 8, 16), "pig_skin", uvs=body_uvs),
        Part((-4, 8, 6), (8, 8, 8), "pig_skin", "head", uvs=box_uvs((0, 0), (8, 8, 8))),
        Part((-2, 9, 14), (4, 3, 1), "pig_skin", "head", uvs=snout_uvs),
        *(part._replace(uvs=leg_uvs) for part in leg_parts),
    )

    return Kind(
        "pig", 10, 0.45, 0.9, 1.2, 2.8, (("porkchop", 1, 3),), parts,
        {"head": (0, 12, 6), **leg_pivots},
        texture="assets/minecraft/textures/entity/pig/pig.png",
    )


def cow_kind():
    """Корова: длинное туловище, высокая голова, два рога и вымя под животом."""
    leg_parts, leg_pivots = legs((4, 12, 4), (-6, 2), (-9, 4), "cow_leg", uv=(0, 16))

    parts = (
        Part((-6, 12, -10), (12, 10, 18), "cow_hide", uvs=horizontal_uvs((18, 4), (12, 18, 10))),
        Part((-2, 11, -8), (4, 1, 6), "cow_hide", uvs=horizontal_uvs((52, 0), (4, 6, 1))),
        Part((-4, 16, 8), (8, 8, 6), "cow_hide", "head", uvs=box_uvs((0, 0), (8, 8, 6))),
        Part((-5, 22, 11), (1, 3, 1), "bone", "head", uvs=box_uvs((22, 0), (1, 3, 1))),
        Part((4, 22, 11), (1, 3, 1), "bone", "head", uvs=box_uvs((22, 0), (1, 3, 1), mirror=True)),
        *leg_parts,
    )

    drops = (("beef", 1, 3), ("leather", 0, 2))

    return Kind(
        "cow", 10, 0.45, 1.3, 1.0, 2.4, drops, parts, {"head": (0, 20, 8), **leg_pivots},
        texture="assets/minecraft/textures/entity/cow/cow.png",
    )


def sheep_kind():
    """Овца: базовая модель и увеличенные бруски шерсти с отдельной текстурой."""
    leg_parts, leg_pivots = legs((4, 12, 4), (-5, 1), (-9, 3), "sheep_leg", uv=(0, 16))
    wool = "assets/minecraft/textures/entity/sheep/sheep_fur.png"
    body_uvs = horizontal_uvs((28, 8), (8, 16, 6))
    wool_legs = tuple(
        Part(
            (part.low[0] - 0.5, 5.5, part.low[2] - 0.5), (5, 7, 5), "wool", part.group,
            uvs=box_uvs((0, 16), (4, 6, 4), mirror=bool(index % 2)), texture=wool,
        )
        for index, part in enumerate(leg_parts)
    )

    parts = (
        Part((-4, 12, -10), (8, 6, 16), "sheep_face", uvs=body_uvs),
        Part((-3, 16, 6), (6, 6, 8), "sheep_face", "head", uvs=box_uvs((0, 0), (6, 6, 8))),
        *leg_parts,
        # Шерсть выступает на 1.75 пикселя на теле, 0.6 на голове и 0.5 на ногах.
        Part((-5.75, 10.25, -11.75), (11.5, 9.5, 19.5), "wool", uvs=body_uvs, texture=wool),
        Part((-3.6, 15.4, 5.4), (7.2, 7.2, 7.2), "wool", "head", uvs=box_uvs((0, 0), (6, 6, 6)), texture=wool),
        *wool_legs,
    )

    drops = (("white_wool", 1, 1),)

    return Kind(
        "sheep", 8, 0.45, 1.2, 1.1, 2.6, drops, parts, {"head": (0, 18, 8), **leg_pivots},
        texture="assets/minecraft/textures/entity/sheep/sheep.png",
    )


def zombie_kind():
    """Зомби: голова 8 x 8, туловище 8 x 12 и конечности 4 x 12."""
    parts = (
        Part((-4, 0, -2), (4, 12, 4), "trousers", "leg0", uvs=box_uvs((0, 16), (4, 12, 4))),
        Part((0, 0, -2), (4, 12, 4), "trousers", "leg1", uvs=box_uvs((0, 16), (4, 12, 4), mirror=True)),
        Part((-4, 12, -2), (8, 12, 4), "tunic", uvs=box_uvs((16, 16), (8, 12, 4))),
        Part((-8, 12, -2), (4, 12, 4), "zombie_skin", "arm0", uvs=box_uvs((40, 16), (4, 12, 4))),
        Part((4, 12, -2), (4, 12, 4), "zombie_skin", "arm1", uvs=box_uvs((40, 16), (4, 12, 4), mirror=True)),
        Part((-4, 24, -4), (8, 8, 8), "zombie_skin", "head", uvs=box_uvs((0, 0), (8, 8, 8))),
    )

    pivots = {
        "leg0": (-2, 12, 0), "leg1": (2, 12, 0),
        "arm0": (-5, 22, 0), "arm1": (5, 22, 0),
        "head": (0, 24, 0),
    }

    return Kind(
        "zombie", 20, 0.3, 1.85, 1.0, 0.0, (("rotten_flesh", 0, 2),), parts, pivots,
        hostile=True, attack=3, chase_speed=2.3, burns=True,
        # В паке файл 64 x 64, но обе стороны используют старые руки и ноги сверху.
        texture="assets/minecraft/textures/entity/zombie/zombie.png", texture_size=(64, 64),
    )


def skeleton_bow():
    """Изогнутый лук с тетивой; цвета берём из текстуры предмета."""
    texture = "assets/minecraft/textures/item/bow.png"

    def part(low, size, pixel):
        u, v = pixel
        # Маленькие бруски лука однотонные, каждый с цветом пикселя предмета.
        uvs = {face: ((u, v), (u + 1, v), (u + 1, v + 1), (u, v + 1)) for face in FACES}
        return Part(low, size, "bow_wood", "arm1", uvs=uvs, texture=texture, texture_size=(16, 16))

    return (
        part((4.5, 11, -2), (1, 1, 4), (3, 9)),
        *(part((4.5, y, z), (1, 1, length), (2, 14)) for y, z, length in (
            (12, -5, 3), (12, 2, 3), (13, -7, 2), (13, 5, 2), (14, -8, 1), (14, 7, 1),
        )),
        part((4.75, 14.25, -7.5), (0.5, 0.5, 15), (5, 12)),
    )


def skeleton_kind():
    """Скелет: кубический череп, рёбра с прозрачными промежутками и тонкие кости."""
    parts = (
        Part((-3, 0, -1), (2, 12, 2), "bone", "leg0", uvs=box_uvs((0, 16), (2, 12, 2))),
        Part((1, 0, -1), (2, 12, 2), "bone", "leg1", uvs=box_uvs((0, 16), (2, 12, 2), mirror=True)),
        Part((-4, 12, -2), (8, 12, 4), "ribs", uvs=box_uvs((16, 16), (8, 12, 4))),
        Part((-6, 12, -1), (2, 12, 2), "bone", "arm0", uvs=box_uvs((40, 16), (2, 12, 2))),
        Part((4, 12, -1), (2, 12, 2), "bone", "arm1", uvs=box_uvs((40, 16), (2, 12, 2), mirror=True)),
        Part((-4, 24, -4), (8, 8, 8), "bone", "head", uvs=box_uvs((0, 0), (8, 8, 8))),
        *skeleton_bow(),
    )

    pivots = {
        "leg0": (-2, 12, 0), "leg1": (2, 12, 0),
        "arm0": (-5, 22, 0), "arm1": (5, 22, 0),
        "head": (0, 24, 0),
    }

    return Kind(
        "skeleton", 20, 0.3, 1.9, 1.0, 0.0, (("bone", 0, 2), ("arrow", 0, 2)), parts, pivots,
        hostile=True, chase_speed=2.3, burns=True, ranged=True,
        texture="assets/minecraft/textures/entity/skeleton/skeleton.png",
    )


# Ноги паука: (сторона, поворот вперёд в радианах). Ноги 0-3 справа, 4-7 слева, спереди назад.
SPIDER_LEGS = {
    f"sleg{index}": (side, base)
    for index, (side, base) in enumerate(
        [(1, base) for base in (0.7, 0.25, -0.25, -0.7)] + [(-1, base) for base in (0.7, 0.25, -0.25, -0.7)]
    )
}
SPIDER_LEG_LENGTH = 16
SPIDER_LEG_HEIGHT = 9
SPIDER_LEG_TILT = math.asin(SPIDER_LEG_HEIGHT / SPIDER_LEG_LENGTH)


def spider_kind():
    """Паук: брюшко 10 x 8 x 12, грудь 6 x 6 и голова 8 x 8 с восемью глазами."""
    parts = [
        Part((-5, 5, -15), (10, 8, 12), "spider_body", uvs=box_uvs((0, 12), (10, 8, 12))),
        Part((-3, 6, -3), (6, 6, 6), "spider_body", uvs=box_uvs((0, 0), (6, 6, 6))),
        Part((-4, 5, 3), (8, 8, 8), "spider_body", "head", uvs=box_uvs((32, 4), (8, 8, 8))),
    ]
    pivots = {"head": (0, 9, 3)}
    attach = (1, 0, -1, -2)

    for name, (side, _) in SPIDER_LEGS.items():
        z = attach[int(name[4:]) % 4]
        x = 3 if side > 0 else -3 - SPIDER_LEG_LENGTH
        parts.append(Part(
            (x, SPIDER_LEG_HEIGHT - 1, z - 1), (SPIDER_LEG_LENGTH, 2, 2), "spider_leg", name,
            uvs=box_uvs((18, 0), (SPIDER_LEG_LENGTH, 2, 2), mirror=side < 0),
        ))
        pivots[name] = (4 * side, SPIDER_LEG_HEIGHT, z)

    return Kind(
        "spider", 16, 0.7, 0.9, 1.0, 0.0, (("string", 0, 2),), tuple(parts), pivots,
        hostile=True, attack=2, chase_speed=3.0, climbs=True, leaps=True, daylight_neutral=True,
        texture="assets/minecraft/textures/entity/spider/spider.png",
    )


def golden_sword():
    """Золотой меч в руке свинозомби: кубики по диагонали картинки предмета.

    В опущенной руке клинок смотрит вниз и вперёд, а в вытянутой вперёд руке
    поднимается под углом, как в оригинале.
    """
    texture = "assets/minecraft/textures/item/golden_sword.png"
    image = pygame.image.load(texture)
    parts = []

    # Рукоять в левом нижнем углу картинки, остриё в правом верхнем.
    for step in range(16):
        u, v = step, 15 - step

        if image.get_at((u, v)).a == 0:
            continue

        uvs = {face: ((u, v), (u + 1, v), (u + 1, v + 1), (u, v + 1)) for face in FACES}
        # От кисти (y = 11) вперёд и вниз вдоль руки.
        low = (5.5, 12 - (step - 2) * 0.75, -1.5 + (step - 2) * 0.75)
        parts.append(Part(low, (1, 1, 1), "bone", "arm1", uvs=uvs, texture=texture, texture_size=(16, 16)))

    return tuple(parts)


def zombie_pigman_kind():
    """Свинозомби: модель зомби, слой «шляпы» с ухом и золотой меч."""
    parts = (
        Part((-4, 0, -2), (4, 12, 4), "trousers", "leg0", uvs=box_uvs((0, 16), (4, 12, 4))),
        Part((0, 0, -2), (4, 12, 4), "trousers", "leg1", uvs=box_uvs((0, 16), (4, 12, 4), mirror=True)),
        Part((-4, 12, -2), (8, 12, 4), "tunic", uvs=box_uvs((16, 16), (8, 12, 4))),
        Part((-8, 12, -2), (4, 12, 4), "zombie_skin", "arm0", uvs=box_uvs((40, 16), (4, 12, 4))),
        Part((4, 12, -2), (4, 12, 4), "zombie_skin", "arm1", uvs=box_uvs((40, 16), (4, 12, 4), mirror=True)),
        Part((-4, 24, -4), (8, 8, 8), "zombie_skin", "head", uvs=box_uvs((0, 0), (8, 8, 8))),
        Part((-4.5, 23.5, -4.5), (9, 9, 9), "zombie_skin", "head", uvs=box_uvs((32, 0), (8, 8, 8))),
        *golden_sword(),
    )

    pivots = {
        "leg0": (-2, 12, 0), "leg1": (2, 12, 0),
        "arm0": (-5, 22, 0), "arm1": (5, 22, 0),
        "head": (0, 24, 0),
    }

    # Как в 1.0: гнилая плоть и золотой самородок.
    drops = (("rotten_flesh", 0, 1), ("gold_nugget", 0, 1))

    return Kind(
        "zombie_pigman", 20, 0.3, 1.85, 1.0, 0.0, drops, parts, pivots,
        hostile=True, attack=5, chase_speed=3.6, neutral=True, fireproof=True, dimension="nether",
        texture="assets/minecraft/textures/entity/zombie_pigman.png", texture_size=(64, 64),
    )


# Щупальца гаста: (x, z, длина) в пикселях модели, как в оригинале девять штук.
GHAST_TENTACLES = tuple(
    (((index % 3 - index // 3 % 2 * 0.5 + 0.25) / 2 * 2 - 1) * 5, (index // 3 / 2 * 2 - 1) * 5, length)
    for index, length in enumerate((10, 13, 9, 12, 8, 14, 11, 9, 12))
)


def ghast_kind():
    """Гаст: куб 16 x 16 x 16 пикселей в четыре раза больше обычного и девять щупалец."""
    parts = [Part((-8, 0, -8), (16, 16, 16), "bone", uvs=box_uvs((0, 0), (16, 16, 16)))]
    pivots = {}

    for index, (x, z, length) in enumerate(GHAST_TENTACLES):
        name = f"tentacle{index}"
        parts.append(Part((x - 1, -length, z - 1), (2, length, 2), "bone", name, uvs=box_uvs((0, 0), (2, length, 2))))
        pivots[name] = (x, 0, z)

    drops = (("gunpowder", 0, 2), ("ghast_tear", 0, 1))

    return Kind(
        "ghast", 10, 2.0, 4.0, 1.6, 0.0, drops, tuple(parts), pivots,
        hostile=True, chase_speed=1.6, flies=True, fireproof=True, dimension="nether", scale=4.0,
        fireballs="large", texture="assets/minecraft/textures/entity/ghast/ghast.png",
        charging_texture="assets/minecraft/textures/entity/ghast/ghast_shooting.png",
    )


BLAZE_RODS = 12


def blaze_kind():
    """Ифрит: голова 8 x 8 и двенадцать огненных стержней в три кольца вокруг."""
    parts = [Part((-4, 16, -4), (8, 8, 8), "bone", "head", uvs=box_uvs((0, 0), (8, 8, 8)))]
    pivots = {"head": (0, 16, 0)}

    for index in range(BLAZE_RODS):
        name = f"rod{index}"
        ring = index // 4
        # Кольца на разной высоте: верхнее под головой, нижнее у земли.
        y = (14, 7, 0)[ring]
        radius = (9, 7, 5)[ring]
        parts.append(Part((radius - 1, y, -1), (2, 8, 2), "bone", name, uvs=box_uvs((0, 16), (2, 8, 2))))
        pivots[name] = (0, y, 0)

    return Kind(
        "blaze", 20, 0.3, 1.8, 1.4, 0.0, (("blaze_rod", 0, 1),), tuple(parts), pivots,
        hostile=True, attack=6, chase_speed=1.8, flies=True, fireproof=True, dimension="nether",
        fireballs="small", texture="assets/minecraft/textures/entity/blaze.png",
    )


KINDS = {kind.name: kind for kind in (
    pig_kind(), cow_kind(), sheep_kind(), zombie_kind(), skeleton_kind(), spider_kind(),
    zombie_pigman_kind(), ghast_kind(), blaze_kind(),
)}
# Кто пасётся стайками в новых чанках.
PASSIVE = sorted(name for name, kind in KINDS.items() if not kind.hostile and kind.dimension == "overworld")
HOSTILE = sorted(name for name, kind in KINDS.items() if kind.hostile and kind.dimension == "overworld")

# Ад: свинозомби бродят толпами, гасты летают в больших пещерах, ифриты живут в крепостях.
NETHER_HOSTILE = ("zombie_pigman", "ghast")
PIGMAN_GROUP = (2, 4)
GHAST_CHANCE = 0.08
MAX_GHASTS = 3
MAX_BLAZES = 4
# Свинозомби злится столько секунд, и злость передаётся всем вокруг на столько блоков.
ANGER_TIME = (20.0, 40.0)
ANGER_RANGE = 32.0

# Гаст: видит игрока издалека, бродит в пределах своего куба, стреляет раз в столько секунд.
GHAST_SIGHT = 64.0
GHAST_WANDER = 16.0
GHAST_CHARGE = 1.0
GHAST_COOLDOWN = 2.0
# Ифрит: держится рядом с игроком чуть выше него, стреляет очередями по три.
BLAZE_SIGHT = 32.0
BLAZE_HOVER = 3.0
BLAZE_BURST = 3
BLAZE_SHOT_GAP = 0.3
BLAZE_COOLDOWN = 3.0
BLAZE_FALL = 1.2
FLY_RESPONSE = 1.5


def angle_step(current, target, limit):
    """Поворот к target кратчайшим путём, не больше limit радиан."""
    difference = (target - current + math.pi) % (2 * math.pi) - math.pi

    return current + max(-limit, min(limit, difference))


def rotation_x(angle):
    cos, sin = math.cos(angle), math.sin(angle)

    return np.array([[1, 0, 0], [0, cos, -sin], [0, sin, cos]], dtype=np.float64)


def rotation_y(angle):
    cos, sin = math.cos(angle), math.sin(angle)

    return np.array([[cos, 0, sin], [0, 1, 0], [-sin, 0, cos]], dtype=np.float64)


def rotation_z(angle):
    cos, sin = math.cos(angle), math.sin(angle)

    return np.array([[cos, -sin, 0], [sin, cos, 0], [0, 0, 1]], dtype=np.float64)


class Mob:
    def __init__(self, kind, position, yaw=None, health=None):
        self.kind = KINDS[kind]
        self.position = tuple(position)
        self.velocity = [0.0, 0.0, 0.0]
        self.yaw = random.uniform(-math.pi, math.pi) if yaw is None else yaw
        self.health = self.kind.health if health is None else health

        self.on_ground = False
        self.in_water = False
        self.in_lava = False

        # Поведение: idle, wander или panic.
        self.state = "idle"
        self.timer = random.uniform(*IDLE_TIME)
        self.target = None
        self.heading = None
        self.flee_from = None
        self.turn_timer = 0.0
        self.walk = (0.0, 0.0)
        self.stuck = 0.0
        self.grazing = False
        self.looking = False

        self.head_yaw = 0.0
        self.head_pitch = 0.0

        self.hurt_time = 0.0
        self.flash = 0.0
        self.dying = None
        self.removed = False

        self.walk_phase = random.uniform(0, math.tau)
        self.walk_amount = 0.0
        self.age = 0.0

        # Враждебные: перезарядка удара и удары за этот шаг (направления от моба к цели).
        self.attack_cooldown = 0.0
        self.attacks = []
        # Выстрелы скелета за шаг: (откуда, куда целится). Их забирает игра.
        self.shots = []
        # Разозлённый ударом паук нападает и днём.
        self.provoked = False
        # Свинозомби злится столько секунд. alerted: только что ударили, игра злит соседей.
        self.anger = 0.0
        self.alerted = False
        # Огненные шары за шаг: (откуда, куда целится). Их забирает игра.
        self.fireballs = []
        # Гаст и ифрит: куда летят и сколько копят на выстрел.
        self.fly_target = None
        self.charge = 0.0
        self.burst = 0
        # Вид для модели: у заряжающего гаста другая текстура.
        self.model_kind = None

        # Звуки за шаг: "ambient", "hurt", "death", "step". Их забирает игра.
        self.sounds = []
        self.ambient_timer = random.uniform(*AMBIENT_INTERVAL)
        self.walked = 0.0
        self.chasing = False

        # Горит ли сейчас на солнце: ставит игра перед update. fire_time: сколько ещё горит после огня.
        self.sunlit = False
        self.fire_time = 0.0
        self.burning = False
        self.burn_time = 0.0

        # Загружен ли мир в точке (x, z): подставляется в update.
        self.loaded = lambda x, z: True

    # Тело.

    def box(self, position):
        x, y, z = position
        w = self.kind.half_width

        return (x - w, y - self.kind.height, z - w), (x + w, y, z + w)

    @property
    def center(self):
        x, y, z = self.position

        return (x, y - self.kind.height / 2, z)

    @property
    def dead(self):
        return self.dying is not None

    # Удар.

    def hurt(self, damage, source):
        """Удар из точки source (None: огонь, без отброса). Возвращает True, если удар прошёл."""
        if self.dead or self.hurt_time > 0:
            return False

        self.health -= damage
        self.hurt_time = HURT_TIME
        self.flash = FLASH_TIME
        self.sounds.append("death" if self.health <= 0 else "hurt")

        if source is not None:
            x, _, z = self.position
            dx, dz = x - source[0], z - source[2]
            length = math.hypot(dx, dz) or 1.0
            self.velocity = [dx / length * KNOCKBACK, -KNOCKBACK_LIFT, dz / length * KNOCKBACK]
            self.on_ground = False

        if source is not None and self.kind.neutral:
            self.anger = random.uniform(*ANGER_TIME)
            self.alerted = True

        if self.health <= 0:
            self.dying = 0.0
            self.walk = (0.0, 0.0)
        elif source is not None and not self.kind.hostile:
            # Враждебные не убегают, а продолжают идти на игрока.
            self.panic(source)
        elif source is not None:
            # Днём паук нейтрален, но удар его злит.
            self.provoked = True

        return True

    def panic(self, source):
        self.state = "panic"
        self.timer = PANIC_TIME
        self.grazing = False
        self.flee_from = source
        self.pick_flee_direction()

    def pick_flee_direction(self):
        x, _, z = self.position
        away = math.atan2(x - self.flee_from[0], z - self.flee_from[2])
        self.target = away + random.uniform(-0.9, 0.9)
        self.turn_timer = random.uniform(*PANIC_TURN_TIME)

    # Поведение.

    def think(self, world, dt, eye, target):
        self.timer -= dt
        self.attack_cooldown = max(0.0, self.attack_cooldown - dt)
        self.anger = max(0.0, self.anger - dt)

        if self.kind.flies:
            self.think_flying(world, dt, eye, target)
            return
        x, y, z = self.position
        speed = 0.0
        heading = self.yaw
        self.chasing = False

        if self.kind.hostile and target is not None and math.dist(target, self.position) < FOLLOW_RANGE:
            # Прямо на игрока, без поиска пути, как в старых версиях. Препятствие
            # в блок перепрыгивает сам шаг физики.
            self.chasing = True
            self.state = "idle"
            self.grazing = False
            self.looking = True
            dx, dz = target[0] - x, target[2] - z
            flat = math.hypot(dx, dz)
            heading = math.atan2(dx, dz)
            speed = 0.0 if flat < CLOSE_ENOUGH else self.kind.chase_speed

            if self.kind.ranged:
                speed = self.aim_and_shoot(world, target, flat, speed)

            elif flat < self.kind.half_width + ATTACK_REACH and abs(target[1] - y) < ATTACK_HEIGHT and self.attack_cooldown <= 0:
                self.attack_cooldown = ATTACK_COOLDOWN
                self.attacks.append((dx / (flat or 1.0), dz / (flat or 1.0)))

            # Паук с нескольких блоков прыгает на игрока.
            if self.kind.leaps and self.on_ground and LEAP_RANGE[0] < flat < LEAP_RANGE[1] and random.random() < dt * LEAP_CHANCE:
                self.velocity = [dx / flat * LEAP_SPEED, -LEAP_LIFT, dz / flat * LEAP_SPEED]
                self.on_ground = False

            self.walk = (math.sin(heading) * speed, math.cos(heading) * speed)
            self.heading = heading
            self.update_head(dt, eye)
            return

        if self.state == "panic":
            self.turn_timer -= dt

            if self.turn_timer <= 0 or self.stuck > STUCK_TIME:
                self.stuck = 0.0
                self.pick_flee_direction()

            heading = self.target
            speed = self.kind.panic_speed

            if self.timer <= 0:
                self.rest()

        elif self.state == "wander":
            tx, tz = self.target
            distance = math.hypot(tx - x, tz - z)

            if distance < 0.5 or self.timer <= 0 or self.stuck > STUCK_TIME:
                self.rest()
            else:
                heading = math.atan2(tx - x, tz - z)
                speed = self.kind.walk_speed

                # Не шагаем с обрыва и туда, где ещё нет мира.
                if not self.safe_ahead(world, heading):
                    self.rest()
                    speed = 0.0

        elif self.timer <= 0:
            self.grazing = False
            self.looking = False

            if random.random() < 0.6:
                angle = random.uniform(-math.pi, math.pi)
                reach = random.uniform(2, WANDER_RADIUS)
                self.state = "wander"
                self.target = (x + math.sin(angle) * reach, z + math.cos(angle) * reach)
                self.timer = WANDER_TIMEOUT
                self.stuck = 0.0
            else:
                self.rest()

        if speed > 0:
            self.grazing = False
            self.looking = False

        if self.kind.hostile:
            self.grazing = False

        self.walk = (math.sin(heading) * speed, math.cos(heading) * speed)
        self.heading = heading if speed > 0 else None
        self.update_head(dt, eye)

    def think_flying(self, world, dt, eye, target):
        """Гаст бродит по воздуху и стреляет издалека, ифрит висит рядом с игроком."""
        x, y, z = self.position
        center = self.center
        self.model_kind = None
        self.chasing = False
        sight = GHAST_SIGHT if self.kind.fireballs == "large" else BLAZE_SIGHT
        sees = False

        if target is not None:
            chest = (target[0], target[1] - 1.0, target[2])
            distance = math.dist(center, chest)
            sees = distance < sight and self.can_see(world, center, chest, distance)

        if self.kind.fireballs == "large":
            # Новая точка, когда долетели, застряли или давно летим.
            if self.fly_target is None or self.timer <= 0 or self.stuck > STUCK_TIME or math.dist(self.fly_target, self.position) < 1.0:
                self.fly_target = (
                    x + random.uniform(-GHAST_WANDER, GHAST_WANDER),
                    y + random.uniform(-GHAST_WANDER, GHAST_WANDER) * 0.5,
                    z + random.uniform(-GHAST_WANDER, GHAST_WANDER),
                )
                self.timer = WANDER_TIMEOUT
                self.stuck = 0.0

            if sees:
                self.heading = math.atan2(target[0] - x, target[2] - z)
                self.charge += dt
                self.chasing = True

                if self.charge >= GHAST_CHARGE * 0.5:
                    self.model_kind = "charging"

                if self.charge >= GHAST_CHARGE and "warn" not in self.sounds:
                    if self.charge - dt < GHAST_CHARGE:
                        self.sounds.append("warn")

                if self.charge >= GHAST_CHARGE + 0.5:
                    self.fireballs.append((center, chest))
                    self.sounds.append("shoot")
                    self.charge = -GHAST_COOLDOWN
            else:
                self.charge = max(0.0, self.charge - dt)
                tx, _, tz = self.fly_target
                self.heading = math.atan2(tx - x, tz - z)

            goal = self.fly_target
            speed = self.kind.walk_speed
        else:
            # Ифрит держится над игроком на несколько блоков и стреляет очередями.
            goal = None
            speed = self.kind.chase_speed

            if target is not None and math.dist(target, self.position) < sight:
                self.chasing = True
                self.heading = math.atan2(target[0] - x, target[2] - z)
                flat = math.hypot(target[0] - x, target[2] - z)
                goal = (target[0], target[1] - BLAZE_HOVER, target[2]) if flat > 4 else (x, target[1] - BLAZE_HOVER, z)

                if sees:
                    self.charge += dt

                    if self.burst > 0 and self.charge >= BLAZE_SHOT_GAP:
                        self.fireballs.append((center, (target[0], target[1] - 1.0, target[2])))
                        self.sounds.append("shoot")
                        self.burst -= 1
                        self.charge = 0.0 if self.burst else -BLAZE_COOLDOWN
                    elif self.burst == 0 and self.charge >= 0:
                        self.burst = BLAZE_BURST
                        self.charge = 0.0

                # Ближний бой: подлетел вплотную, бьёт как зомби.
                if flat < self.kind.half_width + ATTACK_REACH and abs(target[1] - y) < ATTACK_HEIGHT and self.attack_cooldown <= 0:
                    self.attack_cooldown = ATTACK_COOLDOWN
                    self.attacks.append(((target[0] - x) / (flat or 1.0), (target[2] - z) / (flat or 1.0)))
            else:
                self.charge = 0.0
                self.burst = 0

        if goal is None:
            self.walk = (0.0, 0.0)
            self.fly = (0.0, BLAZE_FALL if self.kind.fireballs == "small" else 0.0, 0.0)
        else:
            dx, dy, dz = (goal[axis] - self.position[axis] for axis in range(3))
            length = math.sqrt(dx * dx + dy * dy + dz * dz) or 1.0
            pace = min(speed, length * 2)
            self.fly = (dx / length * pace, dy / length * pace, dz / length * pace)
            self.walk = (self.fly[0], self.fly[2])

        self.update_head(dt, eye)

    @property
    def eye(self):
        x, y, z = self.position

        return (x, y - self.kind.height * 0.85, z)

    def aim_and_shoot(self, world, target, flat, speed):
        """Скелет: видит игрока, значит стреляет. Возвращает скорость шага."""
        eye = self.eye
        chest = (target[0], target[1] - 1.0, target[2])
        distance = math.dist(eye, chest)

        if distance >= SHOOT_RANGE or not self.can_see(world, eye, chest, distance):
            return speed

        if self.attack_cooldown <= 0:
            self.attack_cooldown = SHOOT_COOLDOWN
            self.shots.append((eye, chest))

        return 0.0 if flat < KEEP_DISTANCE else speed * RANGED_APPROACH

    @staticmethod
    def can_see(world, origin, target, distance):
        """Нет ли блоков между двумя точками."""
        if distance <= 0:
            return True

        direction = tuple((target[axis] - origin[axis]) / distance for axis in range(3))
        cell, _ = world.raycast(origin, direction, distance)

        return cell is None

    def rest(self):
        self.state = "idle"
        self.timer = random.uniform(*IDLE_TIME)
        self.walk = (0.0, 0.0)
        self.grazing = random.random() < GRAZE_CHANCE
        self.looking = not self.grazing and random.random() < LOOK_CHANCE

    def safe_ahead(self, world, heading):
        """Есть ли опора впереди не глубже SAFE_DROP блоков."""
        if not self.on_ground:
            return True

        x, y, z = self.position
        reach = self.kind.half_width + 0.4
        ahead = (x + math.sin(heading) * reach, z + math.cos(heading) * reach)

        if not self.loaded(*ahead):
            return False

        low, high = self.box((ahead[0], y + SAFE_DROP, ahead[1]))
        low = (low[0], y + 0.01, low[2])

        return box_touches_blocks(world, low, high) or point_in_water(world, (ahead[0], y + 0.5, ahead[1]))

    def update_head(self, dt, eye):
        """Голова смотрит на игрока или вниз, в траву. Остальное время прямо."""
        target_yaw, target_pitch = 0.0, 0.0

        if self.grazing:
            target_pitch = GRAZE_PITCH

        elif self.looking and eye is not None:
            hx, hy, hz = self.center
            hy -= self.kind.height * 0.3

            if math.dist((hx, hy, hz), eye) < LOOK_DISTANCE:
                look = math.atan2(eye[0] - hx, eye[2] - hz)
                relative = (look - self.yaw + math.pi) % math.tau - math.pi
                target_yaw = max(-HEAD_YAW_LIMIT, min(HEAD_YAW_LIMIT, relative))
                flat = math.hypot(eye[0] - hx, eye[2] - hz)
                # Глаза выше головы: y меньше, а поворот головы вверх положительный.
                target_pitch = max(-0.6, min(0.6, math.atan2(hy - eye[1], flat)))

        step = HEAD_TURN_SPEED * dt
        self.head_yaw += max(-step, min(step, target_yaw - self.head_yaw))
        self.head_pitch += max(-step, min(step, target_pitch - self.head_pitch))

    # Физика.

    def update(self, world, dt, eye, loaded, target=None):
        """Шаг жизни моба. loaded(x, z): загружен ли там мир.

        target: ноги игрока, за которым гонятся враждебные, или None (творческий
        режим, игрок мёртв). Удары за шаг копятся в attacks, их забирает игра.
        """
        self.loaded = loaded
        dt = min(dt, MAX_STEP)
        self.age += dt

        self.hurt_time = max(0.0, self.hurt_time - dt)
        self.flash = max(0.0, self.flash - dt)

        if self.dying is not None:
            self.dying += dt

            if self.dying >= DEATH_TIME:
                self.removed = True
        else:
            self.think(world, dt, eye, target)
            self.burn(dt)

        if not self.dead and self.heading is not None:
            self.yaw = angle_step(self.yaw, self.heading, TURN_SPEED * dt)

        x, y, z = self.position
        vx, vy, vz = self.velocity
        self.in_water = point_in_water(world, self.center)
        # В лаве моб всплывает, как в воде, но горит (урон считает игра).
        self.in_lava = point_in_water(world, self.center, LAVA)
        liquid = self.in_water or self.in_lava

        walk_x, walk_z = self.walk

        if self.kind.flies:
            # Летун плавно набирает нужную скорость по всем трём осям. Мёртвый висит.
            fly = getattr(self, "fly", (0.0, 0.0, 0.0)) if not self.dead else (0.0, 0.0, 0.0)
            response = min(1.0, dt * FLY_RESPONSE)
            vy += (fly[1] - vy) * response
            walk_x, walk_z = fly[0], fly[2]
        elif liquid:
            vy += (-FLOAT_SPEED - vy) * min(1.0, dt * FLOAT_RESPONSE)
            walk_x *= WATER_SLOWDOWN
            walk_z *= WATER_SLOWDOWN
        else:
            vy = min(TERMINAL_VELOCITY, vy + GRAVITY * dt)

        grip = min(1.0, dt * (FLY_RESPONSE if self.kind.flies else GROUND_GRIP if self.on_ground or liquid else AIR_GRIP))
        vx += (walk_x - vx) * grip
        vz += (walk_z - vz) * grip

        wanted = (vx * dt, vy * dt, vz * dt)

        # В незагруженный чанк не заходим: там нет блоков, и моб бы провалился.
        if not loaded(x + wanted[0], z + wanted[2]):
            wanted = (0.0, wanted[1], 0.0)
            vx = vz = 0.0

        new = move(world, self.position, wanted, self.box)
        moved = [new[axis] - self.position[axis] for axis in range(3)]

        self.on_ground = vy > 0 and moved[1] < wanted[1] - 1e-6

        if abs(moved[1] - wanted[1]) > 1e-6:
            vy = 0.0

        blocked = any(abs(moved[axis] - wanted[axis]) > 1e-6 for axis in (0, 2))

        if blocked and self.kind.flies:
            self.stuck += dt
        elif blocked:
            if self.kind.climbs and (walk_x or walk_z):
                # Паук упёрся в стену и лезет по ней вверх.
                vy = -CLIMB_SPEED
                self.on_ground = False
            elif self.on_ground and (walk_x or walk_z):
                vy = -JUMP_SPEED
                self.on_ground = False

            self.stuck += dt
        else:
            self.stuck = max(0.0, self.stuck - dt)

        self.velocity = [vx, vy, vz]
        self.position = new

        if new[1] > VOID_Y:
            self.removed = True

        stepped = math.hypot(moved[0], moved[2])
        self.walk_phase += stepped * STRIDE

        if self.on_ground and not self.dead:
            self.walked += stepped

            if self.walked >= STEP_DISTANCE:
                self.walked -= STEP_DISTANCE
                self.sounds.append("step")

        if not self.dead:
            self.ambient_timer -= dt

            if self.ambient_timer <= 0:
                self.ambient_timer = random.uniform(*AMBIENT_INTERVAL)
                self.sounds.append("ambient")
        moving = 1.0 if stepped > 0.2 * dt and self.on_ground else 0.0
        self.walk_amount += (moving - self.walk_amount) * min(1.0, dt * 8)

    def burn(self, dt):
        """Горит на солнце или после огня: урон раз в BURN_INTERVAL. Вода гасит."""
        self.fire_time = max(0.0, self.fire_time - dt)

        if self.in_water:
            self.fire_time = 0.0

        self.burning = ((self.kind.burns and self.sunlit) or self.fire_time > 0) and not self.in_water

        if self.kind.fireproof:
            self.burning = False
            self.fire_time = 0.0

        if not self.burning:
            self.burn_time = 0.0
            return

        self.burn_time += dt

        if self.burn_time >= BURN_INTERVAL:
            self.burn_time -= BURN_INTERVAL
            self.hurt(1, None)

    def push_apart(self, other, dt):
        """Два животных друг в друге расходятся."""
        ax, _, az = self.position
        bx, _, bz = other.position
        dx, dz = ax - bx, az - bz
        distance = math.hypot(dx, dz)
        limit = self.kind.half_width + other.kind.half_width

        if distance >= limit or abs(self.position[1] - other.position[1]) > 1:
            return

        if distance < 1e-4:
            angle = random.uniform(0, math.tau)
            dx, dz, distance = math.sin(angle), math.cos(angle), 1.0

        push = PUSH_SPEED * dt * (1 - distance / limit) / distance

        self.velocity[0] += dx * push * 10
        self.velocity[2] += dz * push * 10
        other.velocity[0] -= dx * push * 10
        other.velocity[2] -= dz * push * 10

    # Позы для модели.

    def group_rotation(self, group):
        if group == "head":
            return rotation_y(self.head_yaw) @ rotation_x(self.head_pitch)

        if group.startswith("tentacle"):
            # Как в оригинале: щупальца покачиваются, каждое в своей фазе.
            index = int(group[8:])
            return rotation_x(0.2 * math.sin(self.age * 6 + index) + 0.4)

        if group.startswith("rod"):
            # Стержни ифрита кружат вокруг него, кольца в разные стороны, и покачиваются.
            index = int(group[3:])
            ring = index // 4
            direction = (1, -1, 1)[ring]
            angle = direction * self.age * (1.6, 1.2, 0.9)[ring] + index % 4 * math.pi / 2
            bob = math.cos(self.age * 2.5 + index) * 0.08
            return rotation_y(angle) @ rotation_z(bob)

        if group.startswith("arm"):
            sign = 1 if group == "arm0" else -1
            return rotation_x(ARM_RAISE + math.sin(self.walk_phase) * ARM_SWAY * sign)

        if group in SPIDER_LEGS:
            side, base = SPIDER_LEGS[group]
            index = int(group[4:])
            swing = math.sin(self.walk_phase + index * math.pi / 2) * SPIDER_LEG_SWING * self.walk_amount
            # Нога торчит вбок: наклоняем её вниз к земле, потом разворачиваем вперёд или назад.
            return rotation_y(side * -(base + swing)) @ rotation_z(side * SPIDER_LEG_TILT)

        if group.startswith("leg"):
            index = int(group[3:])
            # Передняя левая и задняя правая идут вместе.
            sign = 1 if index in (0, 3) else -1
            return rotation_x(math.sin(self.walk_phase) * LEG_SWING * self.walk_amount * sign)

        return None

    def fall_over(self):
        """Угол, на который мёртвое животное завалилось на бок."""
        if self.dying is None:
            return 0.0

        return math.pi / 2 * min(1.0, self.dying / FALL_OVER_TIME)

    # Сохранение.

    def to_json(self):
        return {
            "kind": self.kind.name,
            "position": [round(value, 4) for value in self.position],
            "yaw": round(self.yaw, 4),
            "health": self.health,
            **({"anger": round(self.anger, 1)} if self.anger > 0 else {}),
        }

    @classmethod
    def from_json(cls, data):
        mob = cls.read_json(data)

        if mob is not None and isinstance(data.get("anger"), (int, float)):
            mob.anger = max(0.0, float(data["anger"]))

        return mob

    @classmethod
    def read_json(cls, data):
        try:
            kind = data["kind"]
            position = [float(value) for value in data["position"]]
            yaw = float(data.get("yaw", 0.0))
            health = data.get("health")

            if kind not in KINDS or len(position) != 3:
                return None

            if type(health) is not int or not 0 < health <= KINDS[kind].health:
                health = None

            return cls(kind, position, yaw, health)

        except (KeyError, TypeError, ValueError):
            return None


def mobs_to_json(mobs):
    return [mob.to_json() for mob in mobs if not mob.dead and not mob.removed]


def spawned_to_json(keys):
    return sorted([x, z] for x, z in keys)


def spawned_from_json(value):
    if not isinstance(value, list):
        return set()

    return {
        (key[0], key[1]) for key in value
        if isinstance(key, list) and len(key) == 2 and all(type(axis) is int for axis in key)
    }


def mobs_from_json(value):
    if not isinstance(value, list):
        return []

    return [mob for mob in map(Mob.from_json, value) if mob is not None]


def spawn_spot(world, x, z, top, depth):
    """Клетка для ног моба в столбце (x, z): от top вниз не глубже depth.

    Нужны две пустые клетки (ноги и голова) над непрозрачным целым блоком.
    Возвращает y клетки ног или None.
    """
    for y in range(top, top + depth):
        floor = world.get_block(x, y + 1, z)

        if floor is None or not floor.is_opaque:
            continue

        if world.get_block(x, y, z) is None and world.get_block(x, y - 1, z) is None:
            return y

    return None


def spawn_light(packed, darkness):
    """Уровень света для появления: небесный слабее ночью на darkness, свет блоков как есть."""
    return max((packed & 15) - darkness, packed >> 4)


def populate(world, chunk, seed):
    """Стайка животных в только что созданном чанке, если повезёт.

    Нетронутые чанки не сохраняются и при каждом входе в мир создаются заново,
    поэтому чанки, где стайка уже была, запоминаются в world.spawned_chunks:
    второй раз там никто не появится, даже если всех съели.
    """
    rng = random.Random((seed * 31 + chunk.chunk_x) * 1_000_003 + chunk.chunk_z)
    key = (chunk.chunk_x, chunk.chunk_z)

    if rng.random() > SPAWN_CHANCE or key in world.spawned_chunks:
        return []

    world.spawned_chunks.add(key)

    kind = rng.choice(PASSIVE)
    center_x = rng.randint(2, Chunk.SIZE - 3)
    center_z = rng.randint(2, Chunk.SIZE - 3)
    spawned = []

    for _ in range(rng.randint(*GROUP_SIZE)):
        ground = None

        for _ in range(SPAWN_TRIES):
            local_x = min(Chunk.SIZE - 1, max(0, center_x + rng.randint(-3, 3)))
            local_z = min(Chunk.SIZE - 1, max(0, center_z + rng.randint(-3, 3)))
            filled = np.flatnonzero(chunk.ids[local_x, :, local_z])

            if len(filled) == 0:
                continue

            y = int(filled[0]) + Y_MIN
            block = chunk.get_block(local_x, y, local_z)

            # Верхний блок столбца: если это листва или вода, на нём не пасутся.
            if block is not None and block.type in SPAWN_GROUND:
                ground = y
                break

        if ground is None:
            continue

        y = ground

        position = (
            chunk.chunk_x * Chunk.SIZE + local_x + rng.uniform(0.3, 0.7),
            float(y),
            chunk.chunk_z * Chunk.SIZE + local_z + rng.uniform(0.3, 0.7),
        )

        mob = Mob(kind, position, rng.uniform(-math.pi, math.pi))
        world.mobs.append(mob)
        spawned.append(mob)

    return spawned


class MobModels:
    """Меши животных: обычный и покрасневший от удара, общий набор вершин."""

    def __init__(self, engine):
        self.engine = engine
        self.models = {}

    def get(self, kind):
        if kind.name not in self.models:
            self.models[kind.name] = self.build(kind)

        return self.models[kind.name]

    def shown_kind(self, mob):
        """Вид для модели: заряжающий гаст с открытыми глазами."""
        if mob.model_kind == "charging" and mob.kind.charging_texture is not None:
            return mob.kind._replace(name=mob.kind.name + "_charging", texture=mob.kind.charging_texture)

        return mob.kind

    def atlas(self, kind):
        """Текстуры деталей в одном атласе; альфа шерсти, рёбер и прочих слоёв сохраняется."""

        if kind.texture is not None:
            paths = list(dict.fromkeys([kind.texture, *(part.texture for part in kind.parts if part.texture is not None)]))
            images = [pygame.image.load(path) for path in paths]
            regions, offset = {}, 0

            for path, image in zip(paths, images):
                regions[path] = (offset, image.get_width(), image.get_height())
                offset += image.get_width()

            # Один файл оставляем как есть: в частности, свинья сохраняет свой атлас.
            normal = images[0] if len(images) == 1 else pygame.Surface((offset, max(image.get_height() for image in images)), pygame.SRCALPHA)

            if len(images) > 1:
                for path, image in zip(paths, images):
                    normal.blit(image, (regions[path][0], 0))

            pixels = pygame.surfarray.array3d(normal).astype(np.float64)
        else:
            names = sorted({part.material_of(face) for part in kind.parts for face in FACES})
            regions = {name: index for index, name in enumerate(names)}
            pixels = np.concatenate([material_tile(name) for name in names], axis=0)
            normal = pygame.Surface(pixels.shape[:2])
            pygame.surfarray.blit_array(normal, pixels.astype(np.uint8))

        # Как в оригинале: при ударе животное краснеет.
        red = pixels * 0.55 + np.array((255, 0, 0)) * 0.45
        flashed = normal.copy()
        # Меняем только RGB: blit_array сбрасывает альфу готовой текстуры.
        flashed_pixels = pygame.surfarray.pixels3d(flashed)
        flashed_pixels[:] = red.clip(0, 255).astype(np.uint8)
        del flashed_pixels

        textures = (
            self.engine.add_texture(f"generated:mob_{kind.name}", normal),
            self.engine.add_texture(f"generated:mob_{kind.name}_hurt", flashed),
        )

        return textures, regions, normal.get_size()

    def build(self, kind):
        (normal, flashed), regions, (atlas_width, atlas_height) = self.atlas(kind)
        points, triangles, uvs, shades, groups = [], [], [], [], []

        # В грани берём кусок материала размером с саму грань (пиксель на пиксель),
        # каждый раз из другого места квадрата, чтобы грани не повторяли друг друга.
        axes = {"top": (0, 2), "bottom": (0, 2), "front": (0, 1), "back": (0, 1), "right": (2, 1), "left": (2, 1)}

        unit = PIXEL * kind.scale

        for part_index, part in enumerate(kind.parts):
            x0, y0, z0 = part.low
            sx, sy, sz = part.size
            low = (x0 * unit, -(y0 + sy) * unit, z0 * unit)
            high = ((x0 + sx) * unit, -y0 * unit, (z0 + sz) * unit)

            for face in FACES:
                corners = box_face(face, low, high)
                first = len(points)
                points.extend(corners)
                shades.extend([FACE_SHADE[face]] * 4)
                groups.extend([part.group] * 4)

                if kind.texture is not None:
                    # UV заданы в размере развёртки: работает и с HD ресурс-паком.
                    path = part.texture or kind.texture
                    reference_size = part.texture_size if part.texture is not None else kind.texture_size
                    offset, width, height = regions[path]
                    quad = np.array(part.uvs[face], dtype=np.float64)
                    quad += np.sign(quad.mean(axis=0) - quad) * 0.02
                    quad /= reference_size
                    quad *= (width / atlas_width, height / atlas_height)
                    quad[:, 0] += offset / atlas_width
                else:
                    material = part.material_of(face)
                    tile = regions[material] * TILE
                    axis_u, axis_v = axes[face]
                    width = (high[axis_u] - low[axis_u]) / unit
                    height = (high[axis_v] - low[axis_v]) / unit

                    # Морду рисуем с угла квадрата, остальное из случайного места.
                    if material in PAINTED:
                        offset_u = offset_v = 0
                    else:
                        seed = zlib.crc32(f"{kind.name}{part_index}{face}".encode("utf-8"))
                        offset_u = seed % max(1, int(TILE - width))
                        offset_v = (seed >> 8) % max(1, int(TILE - height))

                    quad = []

                    for corner in corners:
                        u = (corner[axis_u] - low[axis_u]) / unit
                        v = (corner[axis_v] - low[axis_v]) / unit
                        # Чуть внутрь, чтобы не задеть соседний материал.
                        u = min(max(u, 0.02), width - 0.02)
                        v = min(max(v, 0.02), height - 0.02)
                        quad.append(((tile + offset_u + u) / atlas_width, (offset_v + v) / TILE))

                for a, b, c in QUAD_TRIANGLES.tolist():
                    triangles.append((first + a, first + b, first + c))
                    uvs.append((quad[a], quad[b], quad[c]))

        mesh = Mesh(points, triangles, uvs, normal, shades)
        hurt_mesh = Mesh(points, triangles, uvs, flashed, shades)

        local = np.array(points, dtype=np.float64)
        group_names = np.array(groups)
        parts = []

        for name in dict.fromkeys(groups):
            indices = np.flatnonzero(group_names == name)
            pivot = kind.pivots.get(name)
            center = None if pivot is None else np.array((pivot[0] * unit, -pivot[1] * unit, pivot[2] * unit))
            parts.append((name, indices, center))

        # Мёртвое животное заваливается на правый бок: вокруг его нижнего правого края.
        side = max(part.low[0] + part.size[0] for part in kind.parts) * unit

        return (mesh, hurt_mesh), local, parts, side

    def draw_object(self, mob, brightness):
        (mesh, hurt_mesh), local, parts, side = self.get(self.shown_kind(mob))
        posed = local.copy()

        for name, indices, center in parts:
            turn = mob.group_rotation(name)

            if turn is not None and center is not None:
                posed[indices] = (local[indices] - center) @ turn.T + center

        roll = mob.fall_over()

        if roll:
            pivot = np.array((side, 0.0, 0.0))
            posed = (posed - pivot) @ rotation_z(roll).T + pivot

        body = rotation_y(mob.yaw)
        world_points = posed @ body.T + np.array(mob.position)
        # Горящий моб не перекрашивается: вокруг него рисуется пламя (burning.py).
        shown = hurt_mesh if mob.flash > 0 or mob.dead else mesh

        return DrawObject(shown, np.ascontiguousarray(world_points, dtype=np.float32), brightness)
