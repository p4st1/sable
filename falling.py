"""Падающие песок и гравий, как в 1.0.

Если под песком или гравием пусто (воздух, вода, лава или огонь), блок
срывается и летит вниз целым кубом. Долетев до опоры, он снова становится
блоком. Упав на факел, цветок или другой блок без опоры под ним, рассыпается
предметом. Проверяются клетки, рядом с которыми что-то поменялось
(World.notify), поэтому висящий над пещерой песок из генератора падает, только
когда его заденут, как в оригинале.

Ось Y направлена вниз: позиция падающего блока это его верхний угол.
"""
import math

import numpy as np

from chunk import Chunk, in_height
from mesh import Mesh

FALLING = {"sand", "gravel"}
GRAVITY = 0.04 * 20 * 20
TERMINAL_VELOCITY = 40.0


def is_falling_type(block):
    return block is not None and block.type in FALLING


def can_fall_into(block):
    return block is None or block.is_liquid or block.type == "fire"


class FallingBlock:
    def __init__(self, block, cell):
        self.block = block
        self.x, self.y, self.z = cell
        self.y = float(self.y)
        self.velocity = 0.0
        self.removed = False

    @property
    def position(self):
        return (self.x + 0.5, self.y + 0.5, self.z + 0.5)

    def update(self, world, dt):
        """Шаг падения. Возвращает ("land", клетка), ("break", клетка) или None."""
        self.velocity = min(self.velocity + GRAVITY * dt, TERMINAL_VELOCITY)
        target = self.y + self.velocity * dt
        row = math.floor(self.y)

        while True:
            below = (self.x, row + 1, self.z)

            if not in_height(below[1]):
                self.removed = True
                return None

            under = world.get_block(*below)

            if not can_fall_into(under):
                self.removed = True
                # Опора целая: встаём блоком. На факел, цветок и прочую мелочь рассыпаемся.
                return ("land" if under.is_solid else "break"), (self.x, row, self.z)

            if row + 1 > target:
                self.y = target
                return None

            row += 1
            self.y = float(row)

    def landing_cell(self, world):
        """Где блок лёг бы, если упасть сразу: для сохранения на ходу."""
        row = math.floor(self.y)

        while in_height(row + 1) and can_fall_into(world.get_block(self.x, row + 1, self.z)):
            row += 1

        return (self.x, row, self.z)


class FallingModels:
    """Меши падающих блоков: тот же куб, что в мире, вокруг нуля."""

    def __init__(self, engine):
        self.engine = engine
        self.models = {}

    def get(self, block):
        if block.type not in self.models:
            from world import World

            chunk = Chunk(0, 0)
            chunk.set_block(0, 0, 0, block)
            world = World()
            world.add_chunk(chunk)
            parts = []

            for texture_name, data in chunk.build_mesh(world).items():
                mesh = Mesh(data["points"], data["triangles"], data["uvs"], self.engine.load_texture(texture_name), data.get("shades"))
                parts.append((mesh, np.ascontiguousarray(mesh.points, dtype=np.float32)))

            self.models[block.type] = parts

        return self.models[block.type]

    def draw_objects(self, falling, brightness):
        from entities import DrawObject

        offset = np.array((falling.x, falling.y, falling.z), dtype=np.float32)

        return [DrawObject(mesh, points + offset, brightness) for mesh, points in self.get(falling.block)]
