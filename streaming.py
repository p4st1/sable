"""Подгрузка чанков бесконечного мира вокруг игрока.

Чанк сначала появляется в мире (читается с диска или строится генератором),
а меш получает, только когда загружены все восемь его соседей: иначе на краю
пришлось бы рисовать стенку разреза, а свет из соседей был бы неверным.
Поэтому чанки загружены на кольцо дальше, чем видны.

Работа идёт от ближних чанков к дальним и ограничена временем на кадр, чтобы
игра не замирала. Изменённые чанки перед выгрузкой записываются на диск,
нетронутые просто забываются: генератор построит их точно такими же.
"""
import math
import time

import storage
import water
from chunk import Chunk

# Меш строится, когда загружены все восемь соседей: свет считается и по ним.
NEIGHBOURS = tuple((dx, dz) for dx in (-1, 0, 1) for dz in (-1, 0, 1) if dx or dz)


def chunk_of(x, z):
    return math.floor(x) // Chunk.SIZE, math.floor(z) // Chunk.SIZE


def radius_for(fog_distance):
    """Сколько чанков от игрока должно быть видно, чтобы край мира прятался в тумане."""
    return fog_distance // Chunk.SIZE + 1


def ring_order(radius):
    """Смещения чанков внутри круга радиуса radius, от ближних к дальним."""
    offsets = [
        (dx, dz)
        for dx in range(-radius, radius + 1)
        for dz in range(-radius, radius + 1)
        if dx * dx + dz * dz <= (radius + 0.5) ** 2
    ]

    return sorted(offsets, key=lambda offset: offset[0] ** 2 + offset[1] ** 2)


class ChunkLoader:
    def __init__(self, world, generator, folder, build_chunk, unbuild_chunk):
        """folder: папка сохранения или None (мир за главным меню не сохраняется).

        build_chunk(chunk) строит меши чанка, unbuild_chunk(key) их убирает.
        """
        self.world = world
        self.generator = generator
        self.folder = folder
        self.build_chunk = build_chunk
        self.unbuild_chunk = unbuild_chunk

        world.infinite = True

        self.center = None
        self.radius = None
        self.order = []
        # Всё вокруг уже загружено и построено: до смены центра или радиуса искать нечего.
        self.settled = False

        # Для F3: сколько заняла последняя порция работы.
        self.work_time = 0.0
        self.generated = 0

    def load(self, key):
        """Чанк с диска или от генератора, сразу в мир. Меша у него ещё нет."""
        chunk = storage.read_chunk(self.folder, *key) if self.folder is not None else None

        if chunk is None:
            chunk = self.generator.generate(*key)
            self.generated += 1
        else:
            # Вода, которая текла в момент сохранения, дотекает.
            water.settle_chunk(self.world, chunk)

        self.world.add_chunk(chunk)

        return chunk

    def ensure(self, x, z, radius=1):
        """Чанки под точкой и вокруг неё нужны сейчас же: иначе игрок провалится."""
        center_x, center_z = chunk_of(x, z)

        for dx in range(-radius, radius + 1):
            for dz in range(-radius, radius + 1):
                key = (center_x + dx, center_z + dz)

                if key not in self.world.chunks:
                    self.load(key)

    def is_loaded(self, x, z):
        return chunk_of(x, z) in self.world.chunks

    def can_mesh(self, key):
        chunks = self.world.chunks

        return all((key[0] + dx, key[1] + dz) in chunks for dx, dz in NEIGHBOURS)

    def update(self, x, z, radius, budget):
        """Порция работы на этот кадр: не дольше budget секунд, но хотя бы один чанк."""
        center = chunk_of(x, z)

        if center != self.center or radius != self.radius:
            if radius != self.radius:
                self.order = ring_order(radius + 1)

            self.center = center
            self.radius = radius
            self.settled = False
            self.forget_far()

        if self.settled:
            self.work_time = 0.0
            return

        start = time.perf_counter()
        deadline = start + budget

        while True:
            task = self.next_task()

            if task is None:
                self.settled = True
                break

            action, key = task

            if action == "load":
                self.load(key)
            else:
                self.build_chunk(self.world.chunks[key])

            if time.perf_counter() >= deadline:
                break

        self.work_time = time.perf_counter() - start

    def next_task(self):
        """Ближайший незагруженный чанк или ближайший чанк без меша, что ближе."""
        center_x, center_z = self.center
        chunks = self.world.chunks
        mesh_limit = (self.radius + 0.5) ** 2

        for dx, dz in self.order:
            key = (center_x + dx, center_z + dz)
            chunk = chunks.get(key)

            if chunk is None:
                return "load", key

            if not chunk.meshed and dx * dx + dz * dz <= mesh_limit:
                if self.can_mesh(key):
                    return "mesh", key

                # Соседи дальше по списку: сначала загрузим их.
                for ndx, ndz in NEIGHBOURS:
                    neighbour = (key[0] + ndx, key[1] + ndz)

                    if neighbour not in chunks:
                        return "load", neighbour

        return None

    def forget_far(self):
        """Убирает меши у дальних чанков, а ещё более дальние выгружает совсем."""
        center_x, center_z = self.center
        mesh_limit = (self.radius + 1.5) ** 2
        # У чанка с мешем соседи по диагонали дальше на 1.5: их держим загруженными.
        keep_limit = (self.radius + 3.5) ** 2

        for key, chunk in list(self.world.chunks.items()):
            distance = (key[0] - center_x) ** 2 + (key[1] - center_z) ** 2

            if distance > keep_limit:
                self.unload(key)
            elif distance > mesh_limit and chunk.meshed:
                self.unbuild_chunk(key)

    def unload(self, key):
        chunk = self.world.chunks[key]

        if chunk.meshed:
            self.unbuild_chunk(key)

        if chunk.dirty and self.folder is not None:
            storage.write_chunk(self.folder, chunk)

        self.world.remove_chunk(key)
