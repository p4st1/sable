"""Огненные шары гаста и ифрита.

Как в оригинале, шар не падает, а разгоняется вдоль своего направления и
вязнет в воздухе (пересчитано из тиков в секунды): большой шар гаста быстро
набирает скорость, а попав в блок или тело, взрывается и поджигает всё вокруг.
Малый шар ифрита не взрывается: он поджигает то, во что попал.

Шар можно отбить ударом: он полетит туда, куда смотрит игрок, и попадёт уже в
стрелявшего. Рисуется картинкой огненного заряда, всегда обращённой к камере.
"""
import math

import numpy as np

from mesh import Mesh
from world import ray_box_distance

TICKS = 20
# Разгон за тик вдоль направления и доля скорости, что остаётся за тик.
ACCELERATION = 0.1 * TICKS * TICKS
DRAG = 0.95
LIFETIME = 30.0
VOID_Y = 128

# Урон от прямого попадания, как в 1.0, и сила взрыва большого шара.
LARGE_DAMAGE = 4
SMALL_DAMAGE = 5
LARGE_POWER = 1.0
# Ифрит стреляет неточно.
SMALL_SPREAD = 0.08

TEXTURE = "assets/minecraft/textures/item/fire_charge.png"
LARGE_SIZE = 1.0
SMALL_SIZE = 0.3125


class Fireball:
    def __init__(self, position, direction, shooter=None, small=False):
        self.position = tuple(position)
        self.velocity = [0.0, 0.0, 0.0]
        self.direction = self.unit(direction)
        self.shooter = shooter
        self.small = small
        self.age = 0.0
        self.removed = False

    @staticmethod
    def unit(vector):
        length = math.sqrt(sum(value * value for value in vector)) or 1.0

        return tuple(value / length for value in vector)

    @property
    def size(self):
        return SMALL_SIZE if self.small else LARGE_SIZE

    def box(self):
        half = self.size / 2
        x, y, z = self.position

        return (x - half, y - half, z - half), (x + half, y + half, z + half)

    @property
    def damage(self):
        return SMALL_DAMAGE if self.small else LARGE_DAMAGE

    def deflect(self, direction, shooter):
        """Удар отбивает шар: он летит в новую сторону и уже от имени ударившего."""
        self.direction = self.unit(direction)
        speed = math.sqrt(sum(value * value for value in self.velocity))
        self.velocity = [value * speed for value in self.direction]
        self.shooter = shooter

    def update(self, world, dt, targets):
        """Шаг полёта. targets: [(цель, низ коробки, верх коробки)].

        Возвращает ("block", клетка), ("hit", цель) или None. Точка удара в self.position.
        """
        self.age += dt

        if self.age > LIFETIME or self.position[1] > VOID_Y:
            self.removed = True
            return None

        drag = DRAG ** (dt * TICKS)
        self.velocity = [(value + direction * ACCELERATION * dt) * drag for value, direction in zip(self.velocity, self.direction)]

        step = [value * dt for value in self.velocity]
        length = math.sqrt(sum(value * value for value in step))

        if length == 0:
            return None

        direction = tuple(value / length for value in step)
        hit, nearest = None, length
        half = self.size / 2

        for target, low, high in targets:
            if target is self.shooter:
                continue

            # Шар задевает тело своим размером: расширяем коробку цели.
            wide_low = tuple(value - half for value in low)
            wide_high = tuple(value + half for value in high)
            distance = ray_box_distance(self.position, direction, wide_low, wide_high)

            if distance is not None and distance <= nearest:
                hit, nearest = target, distance

        cell, before = world.raycast(self.position, direction, nearest)

        if cell is not None:
            block = world.get_block(*cell)
            box_low, box_high = block.box()
            low = [cell[axis] + box_low[axis] for axis in range(3)]
            high = [cell[axis] + box_high[axis] for axis in range(3)]
            distance = ray_box_distance(self.position, direction, low, high) or 0.0
            self.position = tuple(self.position[axis] + direction[axis] * max(0.0, distance - 0.05) for axis in range(3))
            self.removed = True

            return "block", cell

        if hit is not None:
            self.position = tuple(self.position[axis] + direction[axis] * nearest for axis in range(3))
            self.removed = True

            return "hit", hit

        self.position = tuple(self.position[axis] + step[axis] for axis in range(3))

        return None


class FireballModel:
    """Квадрат с картинкой заряда, развёрнутый к камере, с обеих сторон."""

    def __init__(self, engine):
        self.engine = engine
        self.mesh = None

    def build(self):
        texture = self.engine.load_texture(TEXTURE)
        points = [(-0.5, -0.5, 0), (0.5, -0.5, 0), (0.5, 0.5, 0), (-0.5, 0.5, 0)]
        corners = [(0, 0), (1, 0), (1, 1), (0, 1)]
        triangles, uvs = [], []

        for a, b, c in ((0, 1, 2), (0, 2, 3), (0, 2, 1), (0, 3, 2)):
            triangles.append((a, b, c))
            uvs.append((corners[a], corners[b], corners[c]))

        self.mesh = Mesh(points, triangles, uvs, texture)
        self.local = np.array(points, dtype=np.float64)

    def world_points(self, fireball, camera):
        if self.mesh is None:
            self.build()

        forward = np.array(camera.forward(), dtype=np.float64)
        # Ось Y вниз: «вверх» на экране это -y.
        right = np.cross(forward, (0.0, -1.0, 0.0))
        length = np.linalg.norm(right)
        right = right / length if length > 1e-6 else np.array((1.0, 0.0, 0.0))
        up = np.cross(right, forward)
        up /= np.linalg.norm(up) or 1.0

        size = fireball.size
        # Картинка: v растёт вниз экрана, то есть против «вверх».
        basis = np.array([right * size, -up * size, forward * 0.0])

        return np.ascontiguousarray(self.local @ basis + np.array(fireball.position), dtype=np.float32)
