import math

from block import Block
from chunk import Chunk
from door import OPPOSITE, SIDES, DoorState, across, facing_side, is_door


def ray_box_distance(origin, direction, low, high):
    """Расстояние вдоль луча до коробки или None, если луч мимо (метод плит)."""
    near, far = 0.0, math.inf

    for axis in range(3):
        if direction[axis] == 0:
            if not low[axis] <= origin[axis] <= high[axis]:
                return None

            continue

        first = (low[axis] - origin[axis]) / direction[axis]
        second = (high[axis] - origin[axis]) / direction[axis]

        near = max(near, min(first, second))
        far = min(far, max(first, second))

        if near > far:
            return None

    return near


class World:
    def __init__(self):
        self.objects = []
        self.chunk_objects = {}
        self.chunks = {}

        # Содержимое сундуков и печек по координатам их блоков.
        self.containers = {}

        # Предметы, лежащие на земле (entities.ItemEntity).
        self.items = []

        # Меши воды по чанкам. Они рисуются вторым проходом, полупрозрачными.
        self.liquid_objects = {}
        self.liquids = []

        # Клетки, где вода должна пересчитаться на следующем шаге (water.tick).
        self.water_updates = set()

        # Бесконечный мир подгружает чанки сам (streaming.ChunkLoader). Тогда блок
        # в незагруженный чанк не ставится: иначе пустой чанк заменил бы настоящий.
        self.infinite = False

    def remove_chunk(self, key):
        """Выгружает чанк вместе с мешами. Сохранить его нужно до этого."""
        self.chunks.pop(key, None)

        if self.chunk_objects.pop(key, None) is not None:
            self.objects = [object for group in self.chunk_objects.values() for object in group]

        if self.liquid_objects.pop(key, None) is not None:
            self.liquids = [object for group in self.liquid_objects.values() for object in group]

        self.water_updates = {
            cell for cell in self.water_updates
            if (cell[0] // Chunk.SIZE, cell[2] // Chunk.SIZE) != key
        }

    def set_chunk_objects(self, chunk, objects):
        # Словарь хранит порядок ключей, так что перестроенный чанк не меняет
        # своего места в списке и порядок отрисовки остаётся стабильным.
        self.chunk_objects[(chunk.chunk_x, chunk.chunk_z)] = objects

        self.objects = [
            object
            for group in self.chunk_objects.values()
            for object in group
        ]

    def set_liquid_objects(self, chunk, objects):
        self.liquid_objects[(chunk.chunk_x, chunk.chunk_z)] = objects

        self.liquids = [
            object
            for group in self.liquid_objects.values()
            for object in group
        ]

    def notify(self, x, y, z):
        """Клетка поменялась: вода в ней и рядом пересчитается на следующем шаге."""
        for dx, dy, dz in ((0, 0, 0), (1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)):
            self.water_updates.add((x + dx, y + dy, z + dz))

    def add_chunk(self, chunk):
        self.chunks[(chunk.chunk_x, chunk.chunk_z)] = chunk

    def get_chunk(self, chunk_x, chunk_z):
        return self.chunks.get((chunk_x, chunk_z))

    def light_at(self, x, y, z):
        """Уровень света 0..15 в клетке. Где меша ещё нет, светло, как под небом."""
        chunk = self.get_chunk(x // Chunk.SIZE, z // Chunk.SIZE)

        if chunk is None:
            return 15

        return chunk.light_at(x % Chunk.SIZE, y, z % Chunk.SIZE)

    def sky_light_at(self, x, y, z):
        """Небесный свет 0..15 в клетке, без света факелов."""
        chunk = self.get_chunk(x // Chunk.SIZE, z // Chunk.SIZE)

        if chunk is None:
            return 15

        return chunk.sky_light_at(x % Chunk.SIZE, y, z % Chunk.SIZE)

    def get_block(self, x, y, z):
        chunk_x = x // Chunk.SIZE
        chunk_z = z // Chunk.SIZE

        chunk = self.get_chunk(chunk_x, chunk_z)

        if chunk is None:
            return None

        local_x = x % Chunk.SIZE
        local_z = z % Chunk.SIZE

        return chunk.get_block(local_x, y, local_z)

    def set_block(self, x, y, z, block):
        chunk_x = x // Chunk.SIZE
        chunk_z = z // Chunk.SIZE

        chunk = self.get_chunk(chunk_x, chunk_z)

        if chunk is None:
            if self.infinite:
                return

            chunk = Chunk(chunk_x, chunk_z)
            self.add_chunk(chunk)

        chunk.set_block(x % Chunk.SIZE, y, z % Chunk.SIZE, block)

    def remove_block(self, x, y, z):
        chunk = self.get_chunk(x // Chunk.SIZE, z // Chunk.SIZE)

        if chunk is not None:
            chunk.remove_block(x % Chunk.SIZE, y, z % Chunk.SIZE)

    def chunks_around(self, x, z):
        """Чанк с этим столбцом и соседи, которых касается его сторона."""
        positions = {
            ((x + dx) // Chunk.SIZE, (z + dz) // Chunk.SIZE)
            for dx, dz in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1))
        }

        return [
            self.chunks[position]
            for position in positions
            if position in self.chunks
        ]

    def raycast(self, origin, direction, max_distance, sources=False):
        """Идёт по лучу от блока к блоку (алгоритм Аманатидеса-Ву).

        Возвращает координаты первого блока и клетки перед ним (пустой или с водой).
        Если блока на пути нет, обе координаты равны None.
        Воду луч пропускает. sources: останавливаться на источниках воды, для ведра.
        """
        position = [math.floor(value) for value in origin]
        step = [0, 0, 0]
        next_border = [math.inf, math.inf, math.inf]
        border_distance = [math.inf, math.inf, math.inf]

        for axis in range(3):
            if direction[axis] > 0:
                step[axis] = 1
                next_border[axis] = (position[axis] + 1 - origin[axis]) / direction[axis]
                border_distance[axis] = 1 / direction[axis]

            elif direction[axis] < 0:
                step[axis] = -1
                next_border[axis] = (position[axis] - origin[axis]) / direction[axis]
                border_distance[axis] = -1 / direction[axis]

        previous = None

        while True:
            block = self.get_block(*position)

            if block is not None and self.ray_hits(block, position, origin, direction, max_distance, sources):
                return tuple(position), previous

            axis = next_border.index(min(next_border))

            if next_border[axis] > max_distance:
                return None, None

            previous = tuple(position)
            position[axis] += step[axis]
            next_border[axis] += border_distance[axis]

    def ray_hits(self, block, position, origin, direction, max_distance, sources=False):
        """Целый куб луч задевает всегда, а у створки двери проверяем саму коробку."""
        if block.is_liquid:
            return sources and block.state.is_source

        if block.is_cube:
            return True

        low, high = block.box()

        distance = ray_box_distance(
            origin,
            direction,
            [position[axis] + low[axis] for axis in range(3)],
            [position[axis] + high[axis] for axis in range(3)]
        )

        return distance is not None and distance <= max_distance

    def door_halves(self, x, y, z):
        """Координаты обеих половинок двери, начиная с нижней."""
        block = self.get_block(x, y, z)
        lower_y = y + 1 if block.state.upper else y

        return [
            (x, half_y, z)
            for half_y in (lower_y, lower_y - 1)
            if (half := self.get_block(x, half_y, z)) is not None and is_door(half.type)
        ]

    def toggle_door(self, x, y, z):
        opened = not self.get_block(x, y, z).state.open

        for position in self.door_halves(x, y, z):
            block = self.get_block(*position)
            self.set_block(*position, Block(block.type, block.state._replace(open=opened)))

    def remove_door(self, x, y, z):
        for position in self.door_halves(x, y, z):
            self.remove_block(*position)

    def place_door(self, position, door_type, forward, player_position):
        """Ставит дверь нижней половиной в position. Возвращает False, если места нет.

        Ось Y направлена вниз: верхняя половина стоит в клетке y - 1, опора в y + 1.
        """
        x, y, z = position

        ground = self.get_block(x, y + 1, z)

        upper = self.get_block(x, y - 1, z)

        if ground is None or not ground.is_cube or (upper is not None and not upper.is_liquid):
            return False

        side = facing_side(forward)
        first, second = across(side)

        # Петли с той стороны, где стоит игрок.
        dx, dz = SIDES[first]
        offset = (player_position[0] - (x + 0.5)) * dx + (player_position[2] - (z + 0.5)) * dz
        hinge = first if offset > 0 else second

        # Рядом такая же дверь: получится двойная. Петли у обеих по внешним краям,
        # поэтому соседнюю дверь при необходимости тоже перевешиваем.
        for neighbour_side in (first, second):
            dx, dz = SIDES[neighbour_side]
            neighbour = self.get_block(x + dx, y, z + dz)

            if neighbour is None or not is_door(neighbour.type) or neighbour.state.side != side:
                continue

            hinge = OPPOSITE[neighbour_side]

            if neighbour.state.hinge != neighbour_side:
                for half in self.door_halves(x + dx, y, z + dz):
                    block = self.get_block(*half)
                    self.set_block(*half, Block(block.type, block.state._replace(hinge=neighbour_side)))

            break

        state = DoorState(side, hinge)

        self.set_block(x, y, z, Block(door_type, state))
        self.set_block(x, y - 1, z, Block(door_type, state._replace(upper=True)))

        return True
