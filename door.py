"""Двери: две половинки по блоку и тонкая створка, которая открывается правым кликом.

Состояние двери неизменяемое: чтобы открыть её, в мир ставятся новые блоки.
Поэтому одно состояние может безопасно делиться между блоками, как типы в палитре.
"""
from typing import NamedTuple

BLOCK_TEXTURES = 'assets/minecraft/textures/block/'
ITEM_TEXTURES = 'assets/minecraft/textures/item/'

# Тип двери: (нижняя половина, верхняя половина, иконка предмета).
DOORS = {
    "oak_door": ("oak_door_bottom.png", "oak_door_top.png", "oak_door.png"),
    "spruce_door": ("spruce_door_bottom.png", "spruce_door_top.png", "spruce_door.png"),
}

THICKNESS = 3 / 16

# Стороны клетки и смещение к соседу по x и z.
SIDES = {
    "north": (0, -1),
    "south": (0, 1),
    "west": (-1, 0),
    "east": (1, 0),
}

OPPOSITE = {"north": "south", "south": "north", "west": "east", "east": "west"}


class DoorState(NamedTuple):
    # Сторона клетки, у которой стоит закрытая створка.
    side: str
    # Сторона с петлями: к ней прижимается открытая створка.
    hinge: str
    open: bool = False
    upper: bool = False

    def encode(self):
        return f"{self.side},{self.hinge},{int(self.open)},{int(self.upper)}"

    @classmethod
    def decode(cls, text):
        side, hinge, opened, upper = text.split(",")

        if side not in SIDES or hinge not in SIDES or opened not in "01" or upper not in "01":
            raise ValueError(f"неверное состояние двери '{text}'")

        return cls(side, hinge, opened == "1", upper == "1")


DEFAULT_STATE = DoorState("north", "west")


def is_door(block_type):
    return block_type in DOORS


def slab_box(side):
    """Створка у стороны клетки: нижний и верхний угол в координатах клетки от 0 до 1."""
    x0, z0, x1, z1 = 0, 0, 1, 1

    if side == "north":
        z1 = THICKNESS
    elif side == "south":
        z0 = 1 - THICKNESS
    elif side == "west":
        x1 = THICKNESS
    else:
        x0 = 1 - THICKNESS

    return (x0, 0, z0), (x1, 1, z1)


def door_box(state):
    return slab_box(state.hinge if state.open else state.side)


def wall_distance(wall, x, z):
    """Расстояние от стенки клетки до точки (x, z) внутри неё."""
    return {"north": z, "south": 1 - z, "west": x, "east": 1 - x}[wall]


def door_uv(state, face, x, y, z):
    """UV точки створки по её координатам в клетке.

    В текстуре петли слева (u = 0), а ручка ближе к правому краю. Поэтому u
    отсчитывается от края с петлями: ручка всегда на свободном краю, открыта
    дверь или нет. Узкие торцы берут полоску текстуры шириной в толщину створки.
    """
    if state.open:
        width_wall, thickness_wall = state.side, state.hinge
    else:
        width_wall, thickness_wall = state.hinge, state.side

    width = wall_distance(width_wall, x, z)
    thickness = wall_distance(thickness_wall, x, z)

    if face in ("top", "bottom"):
        return width, thickness

    face_axis = "x" if face in ("left", "right") else "z"
    width_axis = "x" if width_wall in ("west", "east") else "z"

    if face_axis == width_axis:
        return thickness, y

    return width, y


def door_texture(block_type, state):
    bottom, top, _ = DOORS[block_type]

    return BLOCK_TEXTURES + (top if state.upper else bottom)


def item_texture(block_type):
    return ITEM_TEXTURES + DOORS[block_type][2]


def facing_side(forward):
    """Сторона клетки, обращённая к игроку: он смотрит вдоль forward."""
    x, _, z = forward

    if abs(x) > abs(z):
        return "west" if x > 0 else "east"

    return "north" if z > 0 else "south"


def across(side):
    """Две стороны поперёк створки: у одной из них будут петли."""
    return ("west", "east") if side in ("north", "south") else ("north", "south")
