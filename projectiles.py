"""Летящие стрелы: их пускают скелеты.

Стрела летит с гравитацией и сопротивлением воздуха, как в оригинале
(пересчитано из тиков в секунды). За шаг она проверяет отрезок пути целиком:
и блоки, и тела, поэтому даже быстрая стрела не пролетит сквозь стену или игрока.
Попав в блок, стрела застревает и через минуту исчезает. Урон зависит от
скорости: удвоенная скорость в блоках за тик, с округлением вверх.

Модель как у классической стрелы: две скрещённые плоскости вдоль древка с
текстурой из ресурс-пака (entity/projectiles/arrow.png).
"""
import math
import random

import numpy as np

from mesh import Mesh
from world import ray_box_distance

TICKS = 20
GRAVITY = 0.05 * TICKS * TICKS
AIR_DRAG = 0.99
STUCK_LIFETIME = 60.0
FLIGHT_LIFETIME = 30.0
VOID_Y = 128

# Лук игрока: полностью натянут за секунду, тогда стрела летит 3 блока за тик.
BOW_DRAW_TIME = 1.0
BOW_SPEED = 3.0 * TICKS
BOW_SPREAD = 0.0075
# Слабее этой доли натяжения стрела не вылетает.
BOW_MIN_POWER = 0.1


def bow_power(seconds):
    """Сила выстрела от 0 до 1 по времени натяжения, как в оригинале."""
    part = seconds / BOW_DRAW_TIME
    part = (part * part + part * 2) / 3

    return min(1.0, part)


# Скорость стрелы скелета и разброс, как в оригинале: 1.6 блока за тик.
SKELETON_SPEED = 1.6 * TICKS
SKELETON_SPREAD = 0.05

ARROW_TEXTURE = "assets/minecraft/textures/entity/projectiles/arrow.png"
TEXTURE_SIZE = 32
LENGTH = 0.5
WIDTH = 5 / 32


class Arrow:
    def __init__(self, position, velocity, shooter=None, pickup=False, critical=False):
        self.position = tuple(position)
        self.velocity = list(velocity)
        # Кто выпустил: в него самого стрела не попадает.
        self.shooter = shooter
        # Застрявшую стрелу игрока можно подобрать. Стрелы скелетов нельзя, как в 1.0.
        self.pickup = pickup
        # Выстрел из полностью натянутого лука бьёт сильнее.
        self.critical = critical
        self.age = 0.0
        self.stuck = False
        self.removed = False
        self.direction = self.unit(velocity)

    @staticmethod
    def unit(vector):
        length = math.sqrt(sum(value * value for value in vector)) or 1.0

        return tuple(value / length for value in vector)

    @property
    def damage(self):
        speed = math.sqrt(sum(value * value for value in self.velocity)) / TICKS
        damage = max(1, math.ceil(speed * 2))

        if self.critical:
            damage += random.randint(0, damage // 2 + 1)

        return damage

    def update(self, world, dt, targets):
        """Шаг полёта. targets: [(цель, низ коробки, верх коробки)].

        Возвращает цель, в которую попала стрела, или None.
        """
        self.age += dt

        if self.stuck:
            self.removed = self.age > STUCK_LIFETIME
            return None

        if self.age > FLIGHT_LIFETIME or self.position[1] > VOID_Y:
            self.removed = True
            return None

        drag = AIR_DRAG ** (dt * TICKS)
        self.velocity[1] += GRAVITY * dt
        self.velocity = [value * drag for value in self.velocity]

        step = [value * dt for value in self.velocity]
        length = math.sqrt(sum(value * value for value in step))

        if length == 0:
            return None

        direction = tuple(value / length for value in step)
        self.direction = direction

        # Ближайшее тело на пути.
        hit, nearest = None, length

        for target, low, high in targets:
            if target is self.shooter:
                continue

            distance = ray_box_distance(self.position, direction, low, high)

            if distance is not None and distance <= nearest:
                hit, nearest = target, distance

        # Блок ближе тела: стрела застревает в нём.
        cell, _ = world.raycast(self.position, direction, nearest)

        if cell is not None:
            block = world.get_block(*cell)
            box_low, box_high = block.box()
            low = [cell[axis] + box_low[axis] for axis in range(3)]
            high = [cell[axis] + box_high[axis] for axis in range(3)]
            distance = ray_box_distance(self.position, direction, low, high) or 0.0

            self.position = tuple(self.position[axis] + direction[axis] * distance for axis in range(3))
            self.stuck = True
            self.age = 0.0
            self.velocity = [0.0, 0.0, 0.0]
            return "block"

        if hit is not None:
            self.removed = True
            return hit

        self.position = tuple(self.position[axis] + step[axis] for axis in range(3))

        return None


def aim(origin, target, speed, spread=0.0, rng=None):
    """Скорость стрелы из origin в target с поправкой на падение по дуге."""
    dx, dy, dz = (target[axis] - origin[axis] for axis in range(3))
    flat = math.hypot(dx, dz)
    flight = flat / speed
    # Стрела успеет упасть примерно на g t² / 2: целимся на столько выше (y вниз).
    dy -= GRAVITY * flight * flight / 2

    direction = Arrow.unit((dx, dy, dz))

    if rng is not None and spread:
        direction = Arrow.unit(tuple(value + rng.gauss(0, spread) for value in direction))

    return [value * speed for value in direction]


class ArrowModel:
    """Две скрещённые двусторонние плоскости вдоль оси z, длиной LENGTH."""

    def __init__(self, engine):
        self.engine = engine
        self.mesh = None

    def build(self):
        texture = self.engine.load_texture(ARROW_TEXTURE)
        half_length, half_width = LENGTH / 2, WIDTH / 2
        # Древко в развёртке: полоса 16 x 5 пикселей сверху слева.
        u0, u1, v0, v1 = 0.0, 16 / TEXTURE_SIZE, 0.0, 5 / TEXTURE_SIZE

        quads = [
            [(0, -half_width, -half_length), (0, -half_width, half_length), (0, half_width, half_length), (0, half_width, -half_length)],
            [(-half_width, 0, -half_length), (-half_width, 0, half_length), (half_width, 0, half_length), (half_width, 0, -half_length)],
        ]
        corner_uvs = [(u0, v0), (u1, v0), (u1, v1), (u0, v1)]

        points, triangles, uvs = [], [], []

        for quad in quads:
            start = len(points)
            points.extend(quad)

            for a, b, c in ((0, 1, 2), (0, 2, 3), (0, 2, 1), (0, 3, 2)):
                triangles.append((start + a, start + b, start + c))
                uvs.append((corner_uvs[a], corner_uvs[b], corner_uvs[c]))

        self.mesh = Mesh(points, triangles, uvs, texture)
        self.local = np.array(points, dtype=np.float64)

    def world_points(self, arrow):
        """Вершины стрелы в мире: ось модели вдоль направления полёта, остриё вперёд."""
        if self.mesh is None:
            self.build()

        dx, dy, dz = arrow.direction
        yaw = math.atan2(dx, dz)
        pitch = -math.asin(max(-1.0, min(1.0, dy)))

        cos_pitch, sin_pitch = math.cos(pitch), math.sin(pitch)
        cos_yaw, sin_yaw = math.cos(yaw), math.sin(yaw)
        tilt = np.array([[1, 0, 0], [0, cos_pitch, -sin_pitch], [0, sin_pitch, cos_pitch]])
        turn = np.array([[cos_yaw, 0, sin_yaw], [0, 1, 0], [-sin_yaw, 0, cos_yaw]])

        # Застрявшая стрела наполовину сидит в блоке.
        offset = np.array(arrow.direction) * (LENGTH * 0.25 if arrow.stuck else 0.0)

        return np.ascontiguousarray(self.local @ (turn @ tilt).T + np.array(arrow.position) - offset, dtype=np.float32)
