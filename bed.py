"""Кровать: две клетки (изножье и изголовье), ставится по взгляду игрока.

На ней спят ночью: ночь пропускается до утра, а кровать становится точкой
возрождения. Высота как в оригинале, 9/16 блока: матрас на коротких ножках.

Текстура берётся из ресурс-пака (entity/bed/red.png, развёртка 64 x 64): там
верх матраса, бока, торцы и ножки. Здесь только геометрия и UV, рисует её
chunk.add_bed, как двери.

Состояние неизменяемое, как у дверей: facing это сторона, куда смотрит
изголовье от изножья (north, south, west, east), head отличает половинки.
"""
from typing import NamedTuple

import numpy as np
import pygame

from door import SIDES

BEDS = {"bed"}
BED_TEXTURE = "assets/minecraft/textures/entity/bed/red.png"
BED_ICON = "generated:bed_item"

TEXTURE_SIZE = 64
PIXEL = 1 / 16

# Ось Y вниз: верх матраса на 9/16 над полом, низ матраса на 3/16 (там ножки).
TOP = 1 - 9 * PIXEL
MATTRESS_BOTTOM = 1 - 3 * PIXEL
LEG = 3 * PIXEL

BOX = ((0.0, TOP, 0.0), (1.0, 1.0, 1.0))

# Направо от того, кто стоит в изножье и смотрит на изголовье.
RIGHT = {"north": (1, 0), "south": (-1, 0), "west": (0, -1), "east": (0, 1)}

FACE_NORMALS = {
    "front": (0, 1), "back": (0, -1), "right": (1, 0), "left": (-1, 0),
}


class BedState(NamedTuple):
    facing: str
    head: bool = False

    def encode(self):
        return f"{self.facing},{int(self.head)}"

    @classmethod
    def decode(cls, text):
        facing, head = text.split(",")

        if facing not in SIDES or head not in "01":
            raise ValueError(f"неверное состояние кровати '{text}'")

        return cls(facing, head == "1")


DEFAULT_STATE = BedState("south")


def is_bed(block_type):
    return block_type in BEDS


def other_half(position, state):
    """Клетка второй половины кровати."""
    x, y, z = position
    dx, dz = SIDES[state.facing]

    return (x - dx, y, z - dz) if state.head else (x + dx, y, z + dz)


def to_local(facing, x, z):
    """Точка клетки в осях кровати: l от изножья к изголовью, w слева направо."""
    if facing == "north":
        return 1 - z, x
    if facing == "south":
        return z, 1 - x
    if facing == "west":
        return 1 - x, 1 - z

    return x, z


def from_local(facing, l, w):
    if facing == "north":
        return w, 1 - l
    if facing == "south":
        return 1 - w, l
    if facing == "west":
        return 1 - l, 1 - w

    return l, w


def local_box(facing, l0, l1, w0, w1, y0, y1):
    """Коробка в клетке по отрезкам в осях кровати."""
    x0, z0 = from_local(facing, l0, w0)
    x1, z1 = from_local(facing, l1, w1)

    return (min(x0, x1), y0, min(z0, z1)), (max(x0, x1), y1, max(z0, z1))


def face_role(facing, face):
    """Чем грань приходится кровати: top, bottom, head_end, foot_end, right или left."""
    if face in ("top", "bottom"):
        return face

    nx, nz = FACE_NORMALS[face]
    dx, dz = SIDES[facing]

    if nx * dx + nz * dz > 0:
        return "head_end"
    if nx * dx + nz * dz < 0:
        return "foot_end"

    rx, rz = RIGHT[facing]

    return "right" if nx * rx + nz * rz > 0 else "left"


def mattress_uv(state, face, x, y, z):
    """UV угла матраса в развёртке текстуры. Пиксели развёртки, потом доли."""
    l, w = to_local(state.facing, x, z)
    role = face_role(state.facing, face)
    # Верх изголовья и изножья в развёртке лежит двумя квадратами друг под другом.
    base = 6 if state.head else 28
    along = base + (1 - l) * 16
    depth = (y - TOP) * 16

    if role == "top":
        u, v = 6 + w * 16, along
    elif role == "bottom":
        u, v = 28 + w * 16, along
    elif role == "right":
        u, v = 6 - depth, along
    elif role == "left":
        u, v = 22 + depth, along
    elif role == "head_end":
        u, v = 6 + w * 16, 6 - depth
    else:
        u, v = 22 + w * 16, 22 + depth

    return u / TEXTURE_SIZE, v / TEXTURE_SIZE


def leg_uv(low, high):
    """Ножка: любая грань берёт деревянный квадрат 3 x 3 из развёртки."""
    def uv(face, x, y, z):
        if face in ("top", "bottom"):
            a, b = x, z
            a0, a1, b0, b1 = low[0], high[0], low[2], high[2]
        elif face in ("front", "back"):
            a, b = x, y
            a0, a1, b0, b1 = low[0], high[0], low[1], high[1]
        else:
            a, b = z, y
            a0, a1, b0, b1 = low[2], high[2], low[1], high[1]

        fa = (a - a0) / ((a1 - a0) or 1)
        fb = (b - b0) / ((b1 - b0) or 1)

        return (53 + fa * 3) / TEXTURE_SIZE, (3 + fb * 3) / TEXTURE_SIZE

    return uv


def bed_parts(state):
    """Коробки половинки кровати: (низ, верх, uv(face, x, y, z), скрытые грани)."""
    facing = state.facing
    hidden = set()

    # Между половинками торцы не видны.
    for face in FACE_NORMALS:
        role = face_role(facing, face)

        if (state.head and role == "foot_end") or (not state.head and role == "head_end"):
            hidden.add(face)

    parts = [(*local_box(facing, 0, 1, 0, 1, TOP, MATTRESS_BOTTOM), lambda face, x, y, z: mattress_uv(state, face, x, y, z), hidden)]

    # Ножки по углам дальнего торца этой половинки.
    l0, l1 = (1 - LEG, 1) if state.head else (0, LEG)

    for w0, w1 in ((0, LEG), (1 - LEG, 1)):
        low, high = local_box(facing, l0, l1, w0, w1, MATTRESS_BOTTOM, 1.0)
        parts.append((low, high, leg_uv(low, high), set()))

    return parts


def bed_icon():
    """Иконка предмета 16 x 16: кровать сбоку, нарисована в коде."""
    pixels = np.zeros((16, 16, 4), dtype=np.uint8)

    wood, dark_wood = (150, 104, 60, 255), (96, 64, 36, 255)
    blanket, blanket_dark = (178, 34, 34, 255), (128, 22, 22, 255)
    pillow, pillow_dark = (236, 236, 236, 255), (190, 190, 190, 255)

    # [x, y]: изголовье слева.
    pixels[1:15, 9:11] = wood
    pixels[1:15, 11] = dark_wood
    pixels[1:3, 12:14] = dark_wood
    pixels[13:15, 12:14] = dark_wood
    pixels[1:5, 6:9] = pillow
    pixels[1:5, 8] = pillow_dark
    pixels[5:15, 6:9] = blanket
    pixels[5:15, 8] = blanket_dark
    pixels[5, 6:9] = blanket_dark

    surface = pygame.Surface((16, 16), pygame.SRCALPHA)
    pygame.surfarray.pixels3d(surface)[:] = pixels[:, :, :3]
    pygame.surfarray.pixels_alpha(surface)[:] = pixels[:, :, 3]

    return surface
