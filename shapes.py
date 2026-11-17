"""Блоки непростой формы: ступеньки, забор, калитка, плиты, лестница,
стеклянная панель и железные прутья, как в 1.0.

Плиты: нижняя половина блока. Плита на такую же плиту (щелчок по её верху)
превращается в двойную плиту, которая роняет две плиты.

Лестница прислоняется к стене сбоку: facing это сторона клетки со стеной.
По ней лезут вверх, упираясь в стену (см. Player.update).

Панель и прутья: тонкая перегородка, которая тянется к соседним панелям и
целым блокам. Одинокая панель стоит крестом. Упираются в неё по её форме.

Ступеньки: нижняя половина блока целиком и верхняя половина со стороны
подъёма. Ставятся так, чтобы подниматься от игрока: facing это сторона, где
высокая часть. По ступенькам заходят без прыжка (см. Player.update).

Забор: столбик посередине и по две перекладины к соседним заборам. Как в 1.0,
он соединяется только с другими заборами, а упирается в него игрок и мобы на
полтора блока в высоту: перепрыгнуть забор нельзя.

Калитка: створки между двумя столбиками. Закрытая держит, как забор, на
полтора блока, открытая пропускает. Открывается от того, кто её открыл:
facing это сторона, куда смотрят распахнутые створки, а сама калитка стоит
поперёк этой стороны. Соединяется с заборами по своей длине.

Ось Y направлена вниз: низ клетки это y = 1.
"""
from typing import NamedTuple

BLOCK_TEXTURES = "assets/minecraft/textures/block/"

# Тип -> текстура, из которой он сделан.
STAIRS = {
    "oak_stairs": "oak_planks.png",
    "cobblestone_stairs": "cobblestone.png",
    "brick_stairs": "bricks.png",
    "stone_brick_stairs": "stone_bricks.png",
}
FENCES = {
    "oak_fence": "oak_planks.png",
}
GATES = {
    "fence_gate": "oak_planks.png",
}
# Плита -> (верх и низ, бока, двойная плита).
SLABS = {
    "stone_slab": ("smooth_stone.png", "smooth_stone_slab_side.png", "double_stone_slab"),
    "sandstone_slab": ("sandstone_top.png", "sandstone.png", "double_sandstone_slab"),
    "oak_slab": ("oak_planks.png", "oak_planks.png", "double_oak_slab"),
    "cobblestone_slab": ("cobblestone.png", "cobblestone.png", "double_cobblestone_slab"),
    "brick_slab": ("bricks.png", "bricks.png", "double_brick_slab"),
    "stone_brick_slab": ("stone_bricks.png", "stone_bricks.png", "double_stone_brick_slab"),
}
DOUBLE_SLABS = {double: slab for slab, (_, _, double) in SLABS.items()}
LADDERS = {"ladder": "ladder.png"}
# Панель -> (грань, торец).
PANES = {
    "glass_pane": ("glass.png", "glass_pane_top.png"),
    "iron_bars": ("iron_bars.png", "iron_bars.png"),
}

SIDES = ("north", "east", "south", "west")
OFFSETS = {"north": (0, -1), "south": (0, 1), "west": (-1, 0), "east": (1, 0)}

PIXEL = 1 / 16
POST = ((6 * PIXEL, 0.0, 6 * PIXEL), (10 * PIXEL, 1.0, 10 * PIXEL))
# Перекладины: на высоте 12-15 и 6-9 пикселей от низа клетки.
RAILS = ((1 - 15 * PIXEL, 1 - 12 * PIXEL), (1 - 9 * PIXEL, 1 - 6 * PIXEL))
RAIL_LOW, RAIL_HIGH = 7 * PIXEL, 9 * PIXEL
# Забор держит тело на полблока выше своей клетки.
FENCE_COLLISION = ((0.0, -0.5, 0.0), (1.0, 1.0, 1.0))
CUBE = ((0.0, 0.0, 0.0), (1.0, 1.0, 1.0))


class StairState(NamedTuple):
    """facing: сторона клетки, где высокая часть ступенек (куда идёт подъём)."""
    facing: str = "east"

    def encode(self):
        return self.facing

    @classmethod
    def decode(cls, text):
        if text not in OFFSETS:
            raise ValueError(f"неверное состояние ступенек '{text}'")

        return cls(text)


DEFAULT_STAIRS = StairState()


class GateState(NamedTuple):
    """facing: куда открываются створки; калитка стоит поперёк этой стороны."""
    facing: str = "south"
    open: bool = False

    def encode(self):
        return f"{self.facing},{int(self.open)}"

    @classmethod
    def decode(cls, text):
        facing, opened = text.split(",")

        if facing not in OFFSETS or opened not in "01":
            raise ValueError(f"неверное состояние калитки '{text}'")

        return cls(facing, opened == "1")


DEFAULT_GATE = GateState()


class LadderState(NamedTuple):
    """facing: сторона клетки, у которой стена (и к которой прибита лестница)."""
    facing: str = "north"

    def encode(self):
        return self.facing

    @classmethod
    def decode(cls, text):
        if text not in OFFSETS:
            raise ValueError(f"неверное состояние лестницы '{text}'")

        return cls(text)


DEFAULT_LADDER = LadderState()
SLAB_BOX = ((0.0, 0.5, 0.0), (1.0, 1.0, 1.0))
LADDER_THICKNESS = 2 * PIXEL
PANE_LOW, PANE_HIGH = 7 * PIXEL, 9 * PIXEL


def is_stairs(block_type):
    return block_type in STAIRS


def is_fence(block_type):
    return block_type in FENCES


def is_gate(block_type):
    return block_type in GATES


def is_slab(block_type):
    return block_type in SLABS


def is_ladder(block_type):
    return block_type in LADDERS


def is_pane(block_type):
    return block_type in PANES


def is_shaped(block_type):
    return (
        block_type in STAIRS or block_type in FENCES or block_type in GATES
        or block_type in SLABS or block_type in LADDERS or block_type in PANES
    )


def texture(block_type, face="side"):
    """Текстура формы. У плит верх и низ свои, у панели торцы свои (face="edge")."""
    if block_type in SLABS:
        top, side, _ = SLABS[block_type]
        return BLOCK_TEXTURES + (top if face in ("top", "bottom") else side)

    if block_type in PANES:
        flat, edge = PANES[block_type]
        return BLOCK_TEXTURES + (edge if face == "edge" else flat)

    return BLOCK_TEXTURES + (
        STAIRS.get(block_type) or FENCES.get(block_type) or GATES.get(block_type) or LADDERS[block_type]
    )


def ladder_box(state):
    """Тонкая доска у стены."""
    dx, dz = OFFSETS[state.facing]
    low, high = [0.0, 0.0, 0.0], [1.0, 1.0, 1.0]

    if dx:
        low[0], high[0] = (1 - LADDER_THICKNESS, 1.0) if dx > 0 else (0.0, LADDER_THICKNESS)
    else:
        low[2], high[2] = (1 - LADDER_THICKNESS, 1.0) if dz > 0 else (0.0, LADDER_THICKNESS)

    return tuple(low), tuple(high)


def pane_attaches(neighbour):
    """Тянется ли панель к соседу: к панелям и прутьям, к целым непрозрачным блокам и стеклу."""
    if neighbour is None:
        return False

    return neighbour.type in PANES or neighbour.is_opaque or neighbour.type == "glass"


def pane_sides(world, cell):
    """Стороны, куда тянется панель. Одинокая панель стоит крестом."""
    x, y, z = cell
    sides = [side for side, (dx, dz) in OFFSETS.items() if pane_attaches(world.get_block(x + dx, y, z + dz))]

    return sides or list(OFFSETS)


def pane_boxes(sides):
    """Середина и рукава к сторонам sides, во всю высоту клетки."""
    boxes = [((PANE_LOW, 0.0, PANE_LOW), (PANE_HIGH, 1.0, PANE_HIGH))]

    for side in sides:
        dx, dz = OFFSETS[side]

        if dx:
            x0, x1 = (PANE_HIGH, 1.0) if dx > 0 else (0.0, PANE_LOW)
            boxes.append(((x0, 0.0, PANE_LOW), (x1, 1.0, PANE_HIGH)))
        else:
            z0, z1 = (PANE_HIGH, 1.0) if dz > 0 else (0.0, PANE_LOW)
            boxes.append(((PANE_LOW, 0.0, z0), (PANE_HIGH, 1.0, z1)))

    return boxes


def selection_box(block):
    """Коробка для прицела и трещин."""
    if block.type in SLABS:
        return SLAB_BOX

    if block.type in LADDERS:
        return ladder_box(block.state)

    return CUBE


def gate_along_x(state):
    """Стоит ли калитка вдоль оси x (открывается на север или юг)."""
    return state.facing in ("north", "south")


def connects(neighbour, side):
    """Тянется ли забор к соседу со стороны side: к забору всегда, к калитке по её длине."""
    if neighbour is None:
        return False

    if neighbour.type in FENCES:
        return True

    if neighbour.type in GATES:
        return gate_along_x(neighbour.state) == (side in ("east", "west"))

    return False


def rotate_box(box, turns):
    """Коробка клетки после turns четвертей по часовой стрелке (север -> восток)."""
    (x0, y0, z0), (x1, y1, z1) = box

    for _ in range(turns % 4):
        # Точка (x, z) уходит в (1 - z, x).
        x0, z0, x1, z1 = 1 - z1, x0, 1 - z0, x1

    return (x0, y0, z0), (x1, y1, z1)


def height(pixels):
    """y клетки на такой высоте от низа в пикселях (ось Y вниз)."""
    return 1 - pixels * PIXEL


def gate_boxes(state):
    """Коробки калитки для меша. Сначала строим открытую на юг, потом поворачиваем."""
    def box(x0, x1, bottom, top, z0, z1):
        return ((x0 * PIXEL, height(top), z0 * PIXEL), (x1 * PIXEL, height(bottom), z1 * PIXEL))

    boxes = [box(0, 2, 5, 16, 7, 9), box(14, 16, 5, 16, 7, 9)]

    if not state.open:
        boxes += [
            box(6, 8, 6, 15, 7, 9), box(8, 10, 6, 15, 7, 9),
            box(2, 6, 12, 15, 7, 9), box(2, 6, 6, 9, 7, 9),
            box(10, 14, 12, 15, 7, 9), box(10, 14, 6, 9, 7, 9),
        ]
    else:
        # Створки распахнуты к югу и прижаты к столбикам.
        for x0, x1 in ((0, 2), (14, 16)):
            boxes += [box(x0, x1, 12, 15, 9, 13), box(x0, x1, 6, 9, 9, 13), box(x0, x1, 6, 15, 13, 15)]

    turns = (SIDES.index(state.facing) - SIDES.index("south")) % 4

    return [rotate_box(part, turns) for part in boxes]


def stair_boxes(state):
    """Нижняя плита и верхняя половина со стороны подъёма."""
    upper = {
        "north": ((0.0, 0.0, 0.0), (1.0, 0.5, 0.5)),
        "south": ((0.0, 0.0, 0.5), (1.0, 0.5, 1.0)),
        "west": ((0.0, 0.0, 0.0), (0.5, 0.5, 1.0)),
        "east": ((0.5, 0.0, 0.0), (1.0, 0.5, 1.0)),
    }[state.facing]

    return [((0.0, 0.5, 0.0), (1.0, 1.0, 1.0)), upper]


def fence_parts(connected):
    """Коробки забора для меша: столбик и перекладины к соседям из connected."""
    boxes = [POST]

    for side in connected:
        dx, dz = OFFSETS[side]

        for top, bottom in RAILS:
            if dx:
                x0, x1 = (10 * PIXEL, 1.0) if dx > 0 else (0.0, 6 * PIXEL)
                boxes.append(((x0, top, RAIL_LOW), (x1, bottom, RAIL_HIGH)))
            else:
                z0, z1 = (10 * PIXEL, 1.0) if dz > 0 else (0.0, 6 * PIXEL)
                boxes.append(((RAIL_LOW, top, z0), (RAIL_HIGH, bottom, z1)))

    return boxes


def collision_boxes(block, world=None, cell=None):
    """Во что упирается тело: у ступенек две коробки, у забора одна высокая,
    у закрытой калитки тонкая высокая доска, открытая не мешает. Плита это
    нижняя половина, лестница не мешает вовсе, панель по своей форме."""
    if block.type in STAIRS:
        return stair_boxes(block.state)

    if block.type in SLABS:
        return [SLAB_BOX]

    if block.type in LADDERS:
        return []

    if block.type in PANES:
        return pane_boxes(pane_sides(world, cell) if world is not None else list(OFFSETS))

    if block.type in GATES:
        if block.state.open:
            return []

        plank = ((0.0, -0.5, 6 * PIXEL), (1.0, 1.0, 10 * PIXEL))

        return [plank if gate_along_x(block.state) else rotate_box(plank, 1)]

    return [FENCE_COLLISION]


def icon_boxes(block_type):
    """Как форма выглядит в инвентаре: ступеньки подъёмом вглубь, забор из двух столбиков."""
    if block_type in STAIRS:
        return stair_boxes(StairState("north"))

    if block_type in GATES:
        return gate_boxes(GateState("west"))

    if block_type in SLABS:
        return [SLAB_BOX]

    left = ((0.0, 0.0, 6 * PIXEL), (4 * PIXEL, 1.0, 10 * PIXEL))
    right = ((12 * PIXEL, 0.0, 6 * PIXEL), (1.0, 1.0, 10 * PIXEL))
    rails = [((4 * PIXEL, top, 7 * PIXEL), (12 * PIXEL, bottom, 9 * PIXEL)) for top, bottom in RAILS]

    return [left, right, *rails]


def turn(state, turns):
    """Ступеньки, повёрнутые вместе с постройкой на turns четвертей по часовой стрелке."""
    return state._replace(facing=SIDES[(SIDES.index(state.facing) + turns) % 4])
