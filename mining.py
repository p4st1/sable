"""Ломание блоков в выживании: держишь ЛКМ, по блоку идут трещины, и он ломается.

Время как в оригинале: твёрдость x 1.5 секунды, а если блоку нужна кирка, а её
нет, то x 5, и такой блок ничего не даёт. Подходящий инструмент делит время на
свою скорость.
"""
import numpy as np

from items import TOOLS

from chunk import box_face
from mesh import Mesh
from object3D import Object3D

HARDNESS = {
    "grass": 0.6,
    "dirt": 0.5,
    "sand": 0.5,
    "glass": 0.3,
    "oak_leaves": 0.2,
    "oak_planks": 2.0,
    "oak_log": 2.0,
    "crafting_table": 2.5,
    "chest": 2.5,
    "oak_door": 3.0,
    "stone": 1.5,
    "cobblestone": 2.0,
    "bricks": 2.0,
    "furnace": 3.5,
    "netherrack": 0.4,
    "snowy_grass": 0.6,
    "snow": 0.2,
    "ice": 0.5,
    "gravel": 0.6,
    "clay": 0.6,
    "sandstone": 0.8,
    "cactus": 0.4,
    "birch_log": 2.0,
    "birch_planks": 2.0,
    "birch_leaves": 0.2,
    "spruce_log": 2.0,
    "spruce_planks": 2.0,
    "spruce_leaves": 0.2,
    "coal_ore": 3.0,
    "iron_ore": 3.0,
    "gold_ore": 3.0,
    "diamond_ore": 3.0,
    # Факел ломается сразу, за один кадр.
    "torch": 0.01,
    "glowstone": 0.3,
    "white_wool": 0.8,
    "bed": 0.2,
    # Цветы и саженцы ломаются сразу, как факел.
    "fire": 0.01,
    # Обсидиан ломается долго и только алмазной киркой.
    "obsidian": 50.0,
    "rose": 0.01,
    "dandelion": 0.01,
    "oak_sapling": 0.01,
    "birch_sapling": 0.01,
    "spruce_sapling": 0.01,
    "soul_sand": 0.5,
    "stone_bricks": 1.5,
    "oak_stairs": 2.0,
    "cobblestone_stairs": 2.0,
    "oak_fence": 2.0,
    "fence_gate": 2.0,
    "bookshelf": 1.5,
    "gold_block": 3.0,
    "iron_block": 5.0,
    "diamond_block": 5.0,
    "ladder": 0.4,
    "glass_pane": 0.3,
    "iron_bars": 5.0,
    **{slab: 2.0 for slab in ("stone_slab", "sandstone_slab", "oak_slab", "cobblestone_slab", "brick_slab", "stone_brick_slab")},
    **{double: 2.0 for double in ("double_stone_slab", "double_sandstone_slab", "double_oak_slab", "double_cobblestone_slab", "double_brick_slab", "double_stone_brick_slab")},
    "sugar_cane": 0.01,
    "brick_stairs": 2.0,
    "stone_brick_stairs": 1.5,
    "mossy_stone_bricks": 1.5,
    "cracked_stone_bricks": 1.5,
    "nether_bricks": 2.0,
    "nether_wart": 0.01,
    "nether_wart_stage0": 0.01,
    "nether_wart_stage1": 0.01,
}

# Коренную породу не сломать ничем: в выживании это дно мира.
UNBREAKABLE = {"bedrock", "nether_portal"}
DEFAULT_HARDNESS = 1.0

# Каменным блокам нужна кирка, а рудам ещё и достаточно прочная (см. Tool.level).
NEEDS_PICKAXE = {
    "stone", "cobblestone", "bricks", "furnace", "netherrack", "sandstone",
    "coal_ore", "iron_ore", "gold_ore", "diamond_ore", "obsidian", "nether_bricks",
    "stone_bricks", "cobblestone_stairs", "brick_stairs", "stone_brick_stairs",
    "mossy_stone_bricks", "cracked_stone_bricks", "gold_block", "iron_block", "diamond_block", "iron_bars",
    "stone_slab", "sandstone_slab", "cobblestone_slab", "brick_slab", "stone_brick_slab", "double_stone_slab", "double_sandstone_slab", "double_cobblestone_slab", "double_brick_slab", "double_stone_brick_slab",
}

# Какой уровень кирки нужен, как в оригинале: железную руду добывает каменная,
# золотую и алмазную железная. Остальному хватает деревянной.
HARVEST_LEVEL = {"iron_ore": 1, "gold_ore": 2, "diamond_ore": 2, "obsidian": 3, "iron_block": 1, "gold_block": 2, "diamond_block": 2}

LEAVES = {"oak_leaves", "birch_leaves", "spruce_leaves"}

HAND_FACTOR = 1.5
NO_TOOL_FACTOR = 5.0

# Звук удара раз в столько секунд и пауза после сломанного блока, как в оригинале.
HIT_INTERVAL = 0.2
BREAK_COOLDOWN = 0.25
HIT_VOLUME = 0.25

CRACK_STAGES = 10
CRACK_TEXTURE = "generated:destroy_stage_{}"
# Трещины чуть больше блока, чтобы не спорить с его гранями в буфере глубины.
CRACK_GROW = 0.003

FACES = ("top", "bottom", "front", "back", "right", "left")


# Какие блоки каждый вид инструмента ломает быстрее.
EFFECTIVE = {
    "pickaxe": NEEDS_PICKAXE,
    "axe": {
        "oak_planks", "oak_log", "crafting_table", "chest", "oak_door",
        "birch_log", "birch_planks", "spruce_log", "spruce_planks", "oak_stairs", "oak_fence", "fence_gate", "bookshelf", "ladder", "oak_slab", "double_oak_slab",
    },
    "shovel": {"grass", "dirt", "sand", "snowy_grass", "snow", "gravel", "clay", "soul_sand"},
    "sword": LEAVES | {"cactus"},
}

# Меч изнашивается от ломания блоков вдвое быстрее: он не для этого.
SWORD_WEAR = 2


def tool_of(item):
    return TOOLS.get(item)


def can_harvest(block_type, item):
    """Даст ли блок добычу. Каменным блокам нужна кирка, рудам кирка нужного уровня."""
    if block_type not in NEEDS_PICKAXE:
        return True

    tool = tool_of(item)

    return tool is not None and tool.kind == "pickaxe" and tool.level >= HARVEST_LEVEL.get(block_type, 0)


def break_time(block_type, item=None):
    """Секунды до того, как блок сломается, если бить его предметом item."""
    if block_type in UNBREAKABLE:
        return float("inf")

    factor = HAND_FACTOR if can_harvest(block_type, item) else NO_TOOL_FACTOR
    tool = tool_of(item)
    speed = tool.speed if tool is not None and block_type in EFFECTIVE[tool.kind] else 1.0

    return HARDNESS.get(block_type, DEFAULT_HARDNESS) * factor / speed


def wear_for(item):
    """Сколько прочности тратит один сломанный блок."""
    tool = tool_of(item)

    if tool is None:
        return 0

    return SWORD_WEAR if tool.kind == "sword" else 1


def face_uv(face, x, y, z):
    """UV точки грани по её координатам внутри клетки, в тех же направлениях, что у блоков."""
    if face == "top":
        return x, 1 - z
    if face == "bottom":
        return x, z
    if face == "front":
        return 1 - x, y
    if face == "back":
        return x, y
    if face == "right":
        return z, y

    return 1 - z, y


class Mining:
    """Что и насколько ломается сейчас."""

    def __init__(self):
        self.active = False
        self.target = None
        self.progress = 0.0
        self.hit_time = 0.0
        self.cooldown = 0.0

    def start(self):
        self.active = True

    def stop(self):
        self.active = False
        self.target = None
        self.progress = 0.0
        self.hit_time = 0.0

    @property
    def stage(self):
        """Стадия трещин от 0 до 9 или None, если ломать ещё не начали."""
        if self.target is None or self.progress <= 0:
            return None

        return min(CRACK_STAGES - 1, int(self.progress * CRACK_STAGES))


def crack_object(engine, position, box, stage):
    """Коробка с текстурой трещин вокруг блока. Прозрачные пиксели отсекает растеризатор."""
    low, high = box
    grown_low = [value - CRACK_GROW for value in low]
    grown_high = [value + CRACK_GROW for value in high]

    points, triangles, uvs = [], [], []

    for face in FACES:
        corners = box_face(face, grown_low, grown_high)

        # UV по координатам самой коробки, без запаса: иначе текстура сползёт за край.
        quad = [face_uv(face, *np.clip(corner, 0, 1)) for corner in corners]

        start = len(points)
        points.extend(corners)
        triangles += [(start, start + 1, start + 2), (start, start + 2, start + 3)]
        uvs += [(quad[0], quad[1], quad[2]), (quad[0], quad[2], quad[3])]

    mesh = Mesh(points, triangles, uvs, engine.load_texture(CRACK_TEXTURE.format(stage)))

    crack = Object3D(mesh)
    crack.position = position
    crack.static = True
    crack.build_world_points()

    return crack
