"""Шаблоны построек: куски мира, построенные руками и сохранённые в файл.

Дома для деревень строятся в творческом режиме, а генератор потом ставит их
в мир, поворачивая как нужно. Шаблон хранится в structures/<имя>.npz в том же
виде, что и чанк: своя палитра (тип и состояние блока) и массив номеров. Пустые
клетки тоже часть шаблона: там, где он встанет, будет пусто.

У шаблона есть лицо (front): сторона, где вход. При сохранении это сторона,
обращённая к игроку. Нижний слой шаблона это пол или фундамент: генератор
кладёт его вровень с землёй.

Поворот на четверть оборота по часовой стрелке, если смотреть сверху (север
наверху): север становится востоком. Вместе с клетками поворачиваются двери,
кровати, печки, сундуки и порталы. Ось Y направлена вниз: строка 0 это верх
шаблона, последняя строка его низ.
"""
import re
from pathlib import Path
from typing import NamedTuple

import numpy as np

from bed import BedState
from block import PALETTE, Block, FacingState, block_id
from door import DoorState
from shapes import GateState, LadderState, StairState

FOLDER = Path("structures")
# Больше этого по любой оси шаблон не бывает: деревенские дома небольшие.
MAX_SIZE = 32
NAME = re.compile(r"^[a-z0-9_\-]{1,32}$")

SIDES = ("north", "east", "south", "west")


def turn_side(side, turns):
    """Сторона после turns четвертей оборота по часовой стрелке."""
    return SIDES[(SIDES.index(side) + turns) % 4]


def side_of(forward):
    """Сторона, куда смотрит горизонтальный вектор (x, z): север это -z."""
    dx, _, dz = forward

    if abs(dx) > abs(dz):
        return "east" if dx > 0 else "west"

    return "south" if dz > 0 else "north"


def turns_between(source, target):
    """Сколько четвертей по часовой стрелке поворачивают сторону source в target."""
    return (SIDES.index(target) - SIDES.index(source)) % 4


def rotate_block(block, turns):
    """Тот же блок, повёрнутый вместе с постройкой."""
    if block is None or turns % 4 == 0 or block.state is None:
        return block

    state = block.state

    if isinstance(state, DoorState):
        state = state._replace(side=turn_side(state.side, turns), hinge=turn_side(state.hinge, turns))
    elif isinstance(state, BedState):
        state = state._replace(facing=turn_side(state.facing, turns))
    elif isinstance(state, FacingState):
        state = state._replace(facing=turn_side(state.facing, turns))
    elif isinstance(state, (StairState, GateState, LadderState)):
        state = state._replace(facing=turn_side(state.facing, turns))
    elif block.type == "nether_portal" and turns % 2:
        state = state._replace(axis="z" if state.axis == "x" else "x")
    else:
        return block

    return Block(block.type, state)


class Template(NamedTuple):
    name: str
    # Номера блоков block.PALETTE, оси [x, y, z]; строка y = 0 сверху.
    ids: np.ndarray
    # Сторона со входом.
    front: str

    @property
    def size(self):
        return self.ids.shape

    def rotated(self, turns):
        """Шаблон, повёрнутый на turns четвертей по часовой стрелке."""
        turns %= 4

        if turns == 0:
            return self

        # Четверть по часовой (север -> восток): клетка (x, z) уходит в (size_z - 1 - z, x).
        ids = self.ids

        for _ in range(turns):
            ids = np.ascontiguousarray(np.flip(ids.transpose(2, 1, 0), axis=0))

        # Состояния поворачиваются через палитру: у каждого номера свой повёрнутый блок.
        numbers = np.unique(ids)
        mapping = np.zeros(len(PALETTE), dtype=np.uint16)

        for number in numbers.tolist():
            mapping[number] = block_id(rotate_block(PALETTE[number], turns))

        # Повёрнутые блоки могли получить новые номера в конце палитры: это просто значения.
        ids = mapping[ids]

        return Template(self.name, ids, turn_side(self.front, turns))

    def facing(self, side):
        """Шаблон, повёрнутый входом в сторону side."""
        return self.rotated(turns_between(self.front, side))

    def paste(self, world, origin):
        """Ставит шаблон в мир, origin: клетка с наименьшими x, y, z. Возвращает клетки."""
        x0, y0, z0 = origin
        cells = []

        for (x, y, z), number in np.ndenumerate(self.ids):
            cell = (x0 + x, y0 + y, z0 + z)

            if number:
                world.set_block(*cell, PALETTE[number])
            elif world.get_block(*cell) is not None:
                world.remove_block(*cell)
            else:
                continue

            cells.append(cell)

        return cells

    def stamp(self, ids, base_x, base_z, y_min, origin):
        """Рисует шаблон в массиве чанка (для генератора), обрезая по его границам.

        ids: массив чанка [x, y - y_min, z], base_x и base_z: угол чанка в мире.
        """
        x0, y0, z0 = origin
        size_x, size_y, size_z = self.size
        chunk_size = ids.shape[0]

        low_x, high_x = max(x0, base_x), min(x0 + size_x, base_x + chunk_size)
        low_z, high_z = max(z0, base_z), min(z0 + size_z, base_z + ids.shape[2])
        low_y, high_y = max(y0, y_min), min(y0 + size_y, y_min + ids.shape[1])

        if low_x >= high_x or low_z >= high_z or low_y >= high_y:
            return

        ids[low_x - base_x:high_x - base_x, low_y - y_min:high_y - y_min, low_z - base_z:high_z - base_z] = \
            self.ids[low_x - x0:high_x - x0, low_y - y0:high_y - y0, low_z - z0:high_z - z0]


def path_for(name):
    return FOLDER / f"{name}.npz"


def check_name(name):
    if not NAME.match(name):
        raise ValueError("Name may use only a-z, 0-9, _ and - (up to 32 characters)")


def capture(world, first, second, name, front):
    """Шаблон из коробки мира между двумя углами (включительно)."""
    low = [min(first[axis], second[axis]) for axis in range(3)]
    high = [max(first[axis], second[axis]) for axis in range(3)]
    size = [high[axis] - low[axis] + 1 for axis in range(3)]

    if max(size) > MAX_SIZE:
        raise ValueError(f"Too big: {size[0]}x{size[1]}x{size[2]}, at most {MAX_SIZE} per side")

    ids = np.zeros(size, dtype=np.uint16)

    for x in range(size[0]):
        for y in range(size[1]):
            for z in range(size[2]):
                ids[x, y, z] = block_id(world.get_block(low[0] + x, low[1] + y, low[2] + z))

    return Template(name, ids, front)


def save(template):
    """Записывает шаблон в structures/<имя>.npz, как чанк: своя палитра и номера."""
    FOLDER.mkdir(exist_ok=True)
    numbers = np.unique(template.ids)
    numbers = numbers[numbers != 0]

    local = np.zeros(len(PALETTE), dtype=np.uint16)
    local[numbers] = np.arange(1, len(numbers) + 1, dtype=np.uint16)

    path = path_for(template.name)
    temporary = path.with_suffix(".tmp")

    with open(temporary, "wb") as file:
        np.savez_compressed(
            file,
            volume=local[template.ids],
            palette=np.array([PALETTE[number].key() for number in numbers.tolist()], dtype=str),
            front=np.array(template.front),
        )

    temporary.replace(path)


def load(name):
    """Шаблон из файла. ValueError, если файла нет или он испорчен."""
    from storage import block_from_key

    check_name(name)
    path = path_for(name)

    if not path.is_file():
        raise ValueError(f"No structure named '{name}'")

    try:
        with np.load(path, allow_pickle=False) as data:
            volume = data["volume"]
            palette = data["palette"].tolist()
            front = str(data["front"])

    except (OSError, KeyError, ValueError) as error:
        raise ValueError(f"Structure '{name}' is damaged: {error!r}")

    if front not in SIDES or volume.ndim != 3:
        raise ValueError(f"Structure '{name}' is damaged")

    numbers = np.array([0] + [block_id(block_from_key(key)) for key in palette], dtype=np.uint16)

    return Template(name, numbers[volume], front)


def names():
    """Сохранённые шаблоны по алфавиту."""
    if not FOLDER.is_dir():
        return []

    return sorted(path.stem for path in FOLDER.glob("*.npz"))
