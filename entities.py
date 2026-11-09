"""Предметы, лежащие в мире: выпадают из сломанных блоков, их выбрасывают и подбирают.

Предмет это точка с маленькой коробкой: падает, скользит и останавливается на
блоках. Выглядит как уменьшенный блок или выдавленная картинка, медленно
вращается и покачивается. Ось Y направлена вниз, позиция это центр предмета.
"""
import itertools
import math
import random

import numpy as np

from block import Block
from chunk import Chunk
from hand import ITEM_THICKNESS, flat_item_geometry
from items import Stack, flat_texture
from mesh import Mesh
from water import LAVA, point_in_water
from world import World

TICKS = 20

# Физика как в оригинале, пересчитанная из тиков в секунды.
GRAVITY = 0.04 * TICKS * TICKS
AIR_DRAG = 0.98
GROUND_FRICTION = 0.6 * 0.98
VOID_Y = 128

HALF_SIZE = 0.125
# Подобрать можно не сразу: выпавший из блока через полсекунды, выброшенный через две.
PICKUP_DELAY = 0.5
THROW_DELAY = 2.0
LIFETIME = 300.0

# Номера предметов для сетевой игры: по ним клиент узнаёт тот же предмет в новом снимке.
_item_ids = itertools.count(1)

# Насколько коробка игрока расширяется, когда он подбирает предметы.
PICKUP_REACH_SIDE = 1.0
PICKUP_REACH_UP = 0.5

BLOCK_SCALE = 0.25
FLAT_SCALE = 0.5
SPIN = 1.0
BOB = 0.1
BOB_SPEED = 2.0

# В воде предмет всплывает с такой скоростью и тормозит, как в оригинале.
FLOAT_SPEED = 1.0
FLOAT_RESPONSE = 5.0
WATER_DRAG = 0.8


def solid_at(world, x, y, z):
    """Попадает ли точка внутрь коробки какого-нибудь блока."""
    cell = (math.floor(x), math.floor(y), math.floor(z))
    block = world.get_block(*cell)

    if block is None or not block.is_solid:
        return False

    return any(
        all(cell[axis] + low[axis] <= point <= cell[axis] + high[axis] for axis, point in enumerate((x, y, z)))
        for low, high in block.boxes(world, cell)
    )


class ItemEntity:
    def __init__(self, stack, position, velocity=(0.0, 0.0, 0.0), pickup_delay=PICKUP_DELAY, age=0.0):
        self.stack = stack
        self.position = tuple(position)
        self.velocity = list(velocity)
        self.pickup_delay = pickup_delay
        self.age = age
        self.on_ground = False
        self.id = next(_item_ids)

        # Чтобы соседние предметы не вращались и не качались в такт.
        self.phase = random.uniform(0, 2 * math.pi)

    @property
    def expired(self):
        return self.age >= LIFETIME or self.position[1] > VOID_Y or self.burnt

    burnt = False

    def update(self, world, dt):
        self.age += dt
        self.pickup_delay = max(0.0, self.pickup_delay - dt)

        x, y, z = self.position
        vx, vy, vz = self.velocity

        in_water = point_in_water(world, self.position)

        # Предмет, упавший в лаву, сгорает.
        if point_in_water(world, self.position, LAVA):
            self.burnt = True
            return

        if in_water:
            # Всплывает: скорость вверх (отрицательный y) плавно догоняет FLOAT_SPEED.
            vy += (-FLOAT_SPEED - vy) * min(1.0, dt * FLOAT_RESPONSE)
        else:
            vy += GRAVITY * dt

        # По вертикали: упёрлись низом в блок — легли на его верх.
        new_y = y + vy * dt
        self.on_ground = False

        if vy > 0 and solid_at(world, x, new_y + HALF_SIZE, z):
            new_y = math.floor(new_y + HALF_SIZE) - HALF_SIZE
            vy = 0.0
            self.on_ground = True
        elif vy < 0 and solid_at(world, x, new_y - HALF_SIZE, z):
            new_y = y
            vy = 0.0

        # Опираемся ли на блок, даже если скорость уже нулевая.
        if solid_at(world, x, new_y + HALF_SIZE + 0.01, z):
            self.on_ground = True

        new_x = x + vx * dt

        if solid_at(world, new_x + math.copysign(HALF_SIZE, vx), new_y, z):
            new_x, vx = x, 0.0

        new_z = z + vz * dt

        if solid_at(world, new_x, new_y, new_z + math.copysign(HALF_SIZE, vz)):
            new_z, vz = z, 0.0

        drag = (GROUND_FRICTION if self.on_ground else WATER_DRAG if in_water else AIR_DRAG) ** (dt * TICKS)
        vertical_drag = AIR_DRAG ** (dt * TICKS)

        self.position = (new_x, new_y, new_z)
        self.velocity = [vx * drag, vy * vertical_drag, vz * drag]

    def touches(self, low, high):
        """Касается ли коробка предмета коробки игрока, расширенной для подбора."""
        reach = (PICKUP_REACH_SIDE, PICKUP_REACH_UP, PICKUP_REACH_SIDE)

        return all(
            low[axis] - reach[axis] - HALF_SIZE <= self.position[axis] <= high[axis] + reach[axis] + HALF_SIZE
            for axis in range(3)
        )

    def to_json(self):
        return {
            "item": self.stack.to_json(),
            "position": list(self.position),
            "velocity": list(self.velocity),
            "age": self.age,
            "pickup_delay": self.pickup_delay,
        }

    @classmethod
    def from_json(cls, data):
        try:
            stack = Stack.from_json(data["item"])
            position = [float(value) for value in data["position"]]
            velocity = [float(value) for value in data.get("velocity", (0, 0, 0))]

            if stack is None or len(position) != 3 or len(velocity) != 3:
                return None

            return cls(stack, position, velocity, float(data.get("pickup_delay", 0)), float(data.get("age", 0)))

        except (KeyError, TypeError, ValueError):
            return None


def items_to_json(entities):
    return [entity.to_json() for entity in entities]


def items_from_json(value):
    if not isinstance(value, list):
        return []

    return [entity for entity in map(ItemEntity.from_json, value) if entity is not None]


class DrawObject:
    """То, что нужно растеризатору: меш и уже готовые вершины в мире."""

    def __init__(self, mesh, world_points, brightness=1.0):
        self.mesh = mesh
        self.world_points = world_points
        self.brightness = brightness

        low = world_points.min(axis=0)
        high = world_points.max(axis=0)

        self.center = tuple(float(value) for value in (low + high) / 2)
        self.radius = float(np.linalg.norm(high - low)) / 2


class ItemModels:
    """Модели лежащих предметов по типу: части меша и вершины вокруг нуля."""

    def __init__(self, engine):
        self.engine = engine
        self.models = {}

    def get(self, item):
        if item not in self.models:
            path = flat_texture(item)
            self.models[item] = self.flat_model(path) if path is not None else self.block_model(item)

        return self.models[item]

    def flat_model(self, path):
        points, triangles, uvs = flat_item_geometry()

        # Квадрат картинки (y вверх) переводим в мир (y вниз) и ставим центром в ноль.
        # Отражаются две оси, поэтому грани остаются обращены наружу.
        local = np.array([
            (x - 0.5, -(y - 0.5), -(z + ITEM_THICKNESS / 2))
            for x, y, z in points
        ], dtype=np.float32) * FLAT_SCALE

        mesh = Mesh(points, triangles, uvs, self.engine.load_texture(path))

        return [(mesh, local)]

    def block_model(self, block_type):
        chunk = Chunk(0, 0)
        chunk.set_block(0, 0, 0, Block(block_type))

        world = World()
        world.add_chunk(chunk)

        parts = chunk.build_mesh(world)
        every_point = np.concatenate([np.array(data["points"]) for data in parts.values()])
        center = (every_point.min(axis=0) + every_point.max(axis=0)) / 2

        model = []

        for texture_name, data in parts.items():
            mesh = Mesh(data["points"], data["triangles"], data["uvs"], self.engine.load_texture(texture_name), data.get("shades"))
            model.append((mesh, np.ascontiguousarray((mesh.points - center) * BLOCK_SCALE, dtype=np.float32)))

        return model

    def draw_objects(self, entity, brightness=1.0):
        """Предмет в этом кадре: повёрнут вокруг вертикали и чуть приподнят.

        brightness: свет в клетке предмета, в пещере он темнее.
        """
        angle = entity.age * SPIN + entity.phase
        cos, sin = math.cos(angle), math.sin(angle)
        turn = np.array([[cos, 0, sin], [0, 1, 0], [-sin, 0, cos]], dtype=np.float32)

        lift = math.sin(entity.age * BOB_SPEED + entity.phase) * BOB + BOB
        x, y, z = entity.position
        offset = np.array((x, y - lift, z), dtype=np.float32)

        return [
            DrawObject(mesh, np.ascontiguousarray(points @ turn.T + offset, dtype=np.float32), brightness)
            for mesh, points in self.get(entity.stack.type)
        ]


def scatter_velocity():
    """Как предмет вылетает из сломанного блока: чуть вверх и в случайную сторону."""
    return (
        random.uniform(-0.1, 0.1) * TICKS,
        -0.2 * TICKS,
        random.uniform(-0.1, 0.1) * TICKS,
    )
