from typing import NamedTuple

from bed import BEDS, BedState
from bed import BOX as BED_BOX
from bed import DEFAULT_STATE as BED_STATE
from door import DEFAULT_STATE, DOORS, DoorState, door_box
from plants import PLANTS, plant_box
from fire import BOX as FIRE_BOX
from fire import FIRE
from portal import PORTAL, PortalState, portal_box
import shapes
from shapes import GateState, LadderState, StairState
from textures import texture_path

FACES = {
    "left":  (-1, 0, 0),
    "right": (1, 0, 0),
    "bottom": (0, 1, 0),
    "top":    (0, -1, 0),
    "back":   (0, 0, -1),
    "front":  (0, 0, 1),
}

FACE_VERTICES = {
    "back": [
        (0, 0, 0),
        (0, 1, 0),
        (1, 1, 0),
        (1, 0, 0),
    ],

    "front": [
        (0, 0, 1),
        (1, 0, 1),
        (1, 1, 1),
        (0, 1, 1),
    ],

    "left": [
        (0, 0, 0),
        (0, 0, 1),
        (0, 1, 1),
        (0, 1, 0),
    ],

    "right": [
        (1, 0, 0),
        (1, 1, 0),
        (1, 1, 1),
        (1, 0, 1),
    ],

    "top": [
        (0, 0, 0),
        (1, 0, 0),
        (1, 0, 1),
        (0, 0, 1),
    ],

    "bottom": [
        (0, 1, 0),
        (0, 1, 1),
        (1, 1, 1),
        (1, 1, 0),
    ],
}

FACE_UVS = {
    "front": [
    (1, 0),
    (0, 0),
    (0, 1),
    (1, 1),
    ],

    "back": [
        (0, 0),
        (0, 1),
        (1, 1),
        (1, 0),
    ],

    "left": [
        (1, 0),
        (0, 0),
        (0, 1),
        (1, 1),
    ],

    "right": [
        (0, 0),
        (0, 1),
        (1, 1),
        (1, 0),
    ],

    "top": [
        (0, 0),
        (0, 1),
        (1, 1),
        (1, 0),
    ],

    "bottom": [
        (0, 1),
        (1, 1),
        (1, 0),
        (0, 0),
    ],
}


CUBE_BOX = ((0, 0, 0), (1, 1, 1))

# Факел: тонкая палочка посреди клетки, стоит на блоке снизу. Ось Y вниз.
TORCHES = {"torch"}
TORCH_BOX = ((7 / 16, 6 / 16, 7 / 16), (9 / 16, 1, 9 / 16))
TORCH_TEXTURE = "torch.png"

# Свет. Блок с непрозрачностью 15 не пропускает его вовсе, листва и вода
# гасят по единице за блок, остальное пропускает как воздух.
MAX_LIGHT = 15
DIMMING = {"oak_leaves", "birch_leaves", "spruce_leaves", "water"}

# Сколько света даёт блок сам. У печки только горящей, см. light_emission.
EMISSION = {"torch": 14, "glowstone": 15, "fire": 15, "lava": 15, PORTAL: 11}
LIT_FURNACE_LIGHT = 13

# Кубы с дырками в текстуре: сквозь них видны соседние грани.
TRANSPARENT = {"glass", "oak_leaves", "birch_leaves", "spruce_leaves", "cactus"}

# Жидкости: сквозь них ходят, луч их не видит, а рисуются они отдельным мешем.
LIQUIDS = {"water", "lava"}

# Дальше этого уровня текущая вода не растекается: у источника 0, у края 7.
MAX_LEVEL = 7


class WaterState(NamedTuple):
    """Уровень воды: 0 у источника, дальше от него на единицу больше.

    falling: вода падает сверху. Такая течёт в стороны так же, как источник,
    но сама источником не является и без подпитки сверху пропадает.
    """
    level: int = 0
    falling: bool = False

    @property
    def is_source(self):
        return self.level == 0 and not self.falling

    def encode(self):
        return f"{self.level},{int(self.falling)}"

    @classmethod
    def decode(cls, text):
        level, falling = text.split(",")

        if not level.isdigit() or not 0 <= int(level) <= MAX_LEVEL or falling not in "01":
            raise ValueError(f"неверное состояние воды '{text}'")

        return cls(int(level), falling == "1")


SOURCE = WaterState()


class FacingState(NamedTuple):
    """Состояние блока с лицевой стороной: печка и сундук."""
    # Сторона клетки, куда смотрит лицо: north, south, west или east.
    facing: str
    # Горит ли печка: тогда у неё другая лицевая текстура.
    lit: bool = False

    def encode(self):
        return f"{self.facing},{int(self.lit)}"

    @classmethod
    def decode(cls, text):
        facing, lit = text.split(",")

        if facing not in SIDE_FACE or lit not in "01":
            raise ValueError(f"неверное состояние блока '{text}'")

        return cls(facing, lit == "1")


# Грань меша, которая смотрит на эту сторону клетки.
SIDE_FACE = {"south": "front", "north": "back", "west": "left", "east": "right"}

FACING_BLOCKS = {"furnace", "chest"}

# В иконке видны левая, правая и верхняя грани: лицом влево лицо попадёт в кадр.
DEFAULT_FACING = FacingState("west")


def default_state(block_type):
    if block_type in DOORS:
        return DEFAULT_STATE

    if block_type in BEDS:
        return BED_STATE

    if block_type in FACING_BLOCKS:
        return DEFAULT_FACING

    if block_type in LIQUIDS:
        return SOURCE

    if block_type == PORTAL:
        return PortalState()

    if block_type in shapes.STAIRS:
        return shapes.DEFAULT_STAIRS

    if block_type in shapes.GATES:
        return shapes.DEFAULT_GATE

    if block_type in shapes.LADDERS:
        return shapes.DEFAULT_LADDER

    return None


def decode_state(block_type, text):
    if block_type in DOORS:
        return DoorState.decode(text)

    if block_type in BEDS:
        return BedState.decode(text)

    if block_type in LIQUIDS:
        return WaterState.decode(text)

    if block_type == PORTAL:
        return PortalState.decode(text)

    if block_type in shapes.STAIRS:
        return StairState.decode(text)

    if block_type in shapes.GATES:
        return GateState.decode(text)

    if block_type in shapes.LADDERS:
        return LadderState.decode(text)

    return FacingState.decode(text)


class Block:
    def __init__(self, block_type, state=None):
        self.type = block_type

        # Состояние есть у дверей, печки и сундука. Блоки не меняются после создания.
        self.state = state if state is not None else default_state(block_type)

    @property
    def is_cube(self):
        """Целый куб: закрывает соседние грани и попадает в жадный меш."""
        return (
            self.type not in DOORS and self.type not in LIQUIDS and self.type not in TORCHES
            and self.type not in BEDS and self.type not in PLANTS and self.type != FIRE
            and self.type != PORTAL and not shapes.is_shaped(self.type)
        )

    @property
    def is_liquid(self):
        return self.type in LIQUIDS

    @property
    def is_solid(self):
        """Твёрдый блок упирается в игрока и предметы. Сквозь факел и растения проходят."""
        return (
            self.type not in LIQUIDS and self.type not in TORCHES and self.type not in PLANTS
            and self.type != FIRE and self.type != PORTAL
        )

    @property
    def light_opacity(self):
        """Сколько уровней света теряется в этом блоке (15: не проходит совсем)."""
        if self.is_opaque:
            return MAX_LIGHT

        return 1 if self.type in DIMMING else 0

    @property
    def light_emission(self):
        if self.type == "furnace":
            return LIT_FURNACE_LIGHT if self.state.lit else 0

        return EMISSION.get(self.type, 0)

    @property
    def is_opaque(self):
        """Непрозрачный куб прячет грани соседей, которые к нему прилегают."""
        return self.is_cube and self.type not in TRANSPARENT

    def hides_face_of(self, block):
        """Закрывает ли этот блок грань соседа block, которая смотрит на него.

        Между двумя одинаковыми прозрачными кубами грани тоже не нужны:
        иначе стена из стекла была бы в сетке изнутри.
        """
        return self.is_opaque or (self.is_cube and self.type == block.type)

    def box(self):
        """Коробка блока в координатах клетки, для столкновений и луча."""
        if self.type in DOORS:
            return door_box(self.state)

        if self.type in BEDS:
            return BED_BOX

        if self.type in PLANTS:
            return plant_box(self.type)

        if self.type == FIRE:
            return FIRE_BOX

        if self.type == PORTAL:
            return portal_box(self.state)

        # Ступеньки и забор выделяются целым блоком, как в 1.0, плита и лестница своей формой.
        if shapes.is_shaped(self.type):
            return shapes.selection_box(self)

        return TORCH_BOX if self.type in TORCHES else CUBE_BOX

    def boxes(self, world=None, cell=None):
        """Коробки, в которые упирается тело: у ступенек две, у забора высокая.

        Панели тянутся к соседям, поэтому им нужны мир и клетка."""
        if shapes.is_shaped(self.type):
            return shapes.collision_boxes(self, world, cell)

        return [self.box()]

    def key(self):
        """Строка для палитры сохранения: тип и, если есть, состояние."""
        return self.type if self.state is None else f"{self.type}|{self.state.encode()}"

    def get_block_texture(block, face):
        if shapes.is_shaped(block.type):
            return shapes.texture(block.type, face)

        textures = BLOCKS[block.type]

        # У печки и сундука лицо там, куда они повёрнуты, остальные бока одинаковые.
        if block.type in FACING_BLOCKS and face not in ("top", "bottom"):
            if face != SIDE_FACE[block.state.facing]:
                return texture_path(textures["side"])

            return texture_path(textures["front_lit" if block.state.lit else "front"])

        return texture_path(textures[face])


# Блоки, которых больше нет в игре, и чем они становятся в старых сохранениях.
REMOVED = {"granite": "stone", "diorite": "stone", "andesite": "stone", "spruce_door": "oak_door"}


def is_known_type(block_type):
    return (
        block_type in BLOCKS or block_type in DOORS or block_type in LIQUIDS
        or block_type in TORCHES or block_type in BEDS or block_type in PLANTS or block_type == FIRE
        or block_type == PORTAL or shapes.is_shaped(block_type)
    )


# Номера блоков для массивов чанков. Номер выдаётся паре "тип и состояние" при
# первой встрече и живёт до конца запуска; в сохранениях вместо номеров ключи.
# 0 это воздух. Блоки неизменяемые, поэтому один экземпляр на номер делят все клетки.
PALETTE = [None]
_ids = {}


def block_id(block):
    if block is None:
        return 0

    key = block.key()
    number = _ids.get(key)

    if number is None:
        number = len(PALETTE)
        _ids[key] = number
        PALETTE.append(block)

    return number


def type_id(block_type):
    """Номер блока без состояния (или с состоянием по умолчанию)."""
    return block_id(Block(block_type))


def ids_where(predicate):
    """Номера всех уже встречавшихся блоков, для которых predicate(block) истинно."""
    return [number for number, block in enumerate(PALETTE) if block is not None and predicate(block)]


def double_slab(slab):
    """Две плиты одна на другой: целый блок с текстурами плиты."""
    top, side, _ = shapes.SLABS[slab]

    return {**all_sides(side), "top": top, "bottom": top}


def all_sides(texture):
    return {face: texture for face in FACES}


def column(side, ends):
    """Блок со своей текстурой сверху и снизу, как бревно."""
    return {**all_sides(side), "top": ends, "bottom": ends}


BLOCKS = {
    "grass": {
        "top": "grass_block_top.png",
        "bottom": "dirt.png",
        "left": "grass_block_side.png",
        "right": "grass_block_side.png",
        "front": "grass_block_side.png",
        "back": "grass_block_side.png",
    },

    "dirt": all_sides("dirt.png"),
    "netherrack": all_sides("netherrack.png"),
    "danilEfail": all_sides("1.png"),

    "oak_planks": all_sides("oak_planks.png"),
    "oak_log": column("oak_log.png", "oak_log_top.png"),
    "oak_leaves": all_sides("generated:oak_leaves"),
    "stone": all_sides("stone.png"),
    "cobblestone": all_sides("cobblestone.png"),
    "sand": all_sides("sand.png"),
    "bricks": all_sides("bricks.png"),
    "glass": all_sides("glass.png"),

    "crafting_table": {
        "top": "crafting_table_top.png",
        "bottom": "oak_planks.png",
        "front": "crafting_table_front.png",
        "left": "crafting_table_front.png",
        "back": "crafting_table_side.png",
        "right": "crafting_table_side.png",
    },

    # У блоков из FACING_BLOCKS текстуры по ролям, а не по граням.
    "furnace": {
        "front": "furnace_front.png",
        "front_lit": "furnace_front_on.png",
        "side": "furnace_side.png",
        "top": "furnace_top.png",
        "bottom": "furnace_top.png",
    },

    "chest": {
        "front": "generated:chest_front",
        "side": "generated:chest_side",
        "top": "generated:chest_top",
        "bottom": "generated:chest_top",
    },

    # Блоки, которые появились вместе с генератором мира.
    "snowy_grass": {**column("grass_block_snow.png", "snow.png"), "bottom": "dirt.png"},
    "snow": all_sides("snow.png"),
    "ice": all_sides("ice.png"),
    "gravel": all_sides("gravel.png"),
    "clay": all_sides("clay.png"),
    "sandstone": {**all_sides("sandstone.png"), "top": "sandstone_top.png", "bottom": "sandstone_bottom.png"},
    "cactus": {**all_sides("cactus_side.png"), "top": "cactus_top.png", "bottom": "cactus_bottom.png"},
    "bedrock": all_sides("bedrock.png"),
    "glowstone": all_sides("glowstone.png"),
    "obsidian": all_sides("obsidian.png"),
    "stone_bricks": all_sides("stone_bricks.png"),
    # Замшелые и треснувшие бывают только в постройках мира, рецепта нет, как в 1.0.
    "mossy_stone_bricks": all_sides("mossy_stone_bricks.png"),
    "cracked_stone_bricks": all_sides("cracked_stone_bricks.png"),
    "bookshelf": column("bookshelf.png", "oak_planks.png"),
    "gold_block": all_sides("gold_block.png"),
    "iron_block": all_sides("iron_block.png"),
    "diamond_block": all_sides("diamond_block.png"),

    # Ад.
    "soul_sand": all_sides("soul_sand.png"),
    "nether_bricks": all_sides("nether_bricks.png"),
    "white_wool": all_sides("white_wool.png"),

    "coal_ore": all_sides("coal_ore.png"),
    "iron_ore": all_sides("iron_ore.png"),
    "gold_ore": all_sides("gold_ore.png"),
    "diamond_ore": all_sides("diamond_ore.png"),

    "birch_log": column("birch_log.png", "birch_log_top.png"),
    "birch_leaves": all_sides("generated:birch_leaves"),
    "birch_planks": all_sides("birch_planks.png"),
    "spruce_log": column("spruce_log.png", "spruce_log_top.png"),
    "spruce_leaves": all_sides("generated:spruce_leaves"),
    "spruce_planks": all_sides("spruce_planks.png"),
}

# Двойные плиты: их не бывает в инвентаре, они получаются из двух плит.
for _slab, (_, _, _double) in shapes.SLABS.items():
    BLOCKS[_double] = double_slab(_slab)
