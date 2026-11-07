"""Предметы и стаки: блоки, которые можно поставить, простые предметы вроде палки и еда.

Стак — тип предмета и количество. Ячейка инвентаря хранит стак или None.
У инструмента в стаке ещё есть износ: сколько раз им уже пользовались.
"""
import random
from typing import NamedTuple

from block import BLOCKS
from block import REMOVED, TORCHES
from door import DOORS, is_door

ITEM_TEXTURES = 'assets/minecraft/textures/item/'
MAX_STACK = 64

NAMES = {
    "oak_planks": "Oak Planks",
    "oak_log": "Oak Log",
    "stone": "Stone",
    "cobblestone": "Cobblestone",
    "sand": "Sand",
    "grass": "Grass Block",
    "dirt": "Dirt",
    "netherrack": "Netherrack",
    "bricks": "Bricks",
    "glass": "Glass",
    "oak_leaves": "Oak Leaves",
    "crafting_table": "Crafting Table",
    "furnace": "Furnace",
    "chest": "Chest",
    "oak_door": "Oak Door",
    "spruce_door": "Spruce Door",
    "stick": "Stick",
    "charcoal": "Charcoal",
    "danilEfail": "danilEfail",
    "apple": "Apple",
    "bread": "Bread",
    "porkchop": "Raw Porkchop",
    "cooked_porkchop": "Cooked Porkchop",
    "cookie": "Cookie",
    "golden_apple": "Golden Apple",
    "wooden_pickaxe": "Wooden Pickaxe",
    "wooden_axe": "Wooden Axe",
    "wooden_shovel": "Wooden Shovel",
    "wooden_sword": "Wooden Sword",
    "stone_pickaxe": "Stone Pickaxe",
    "stone_axe": "Stone Axe",
    "stone_shovel": "Stone Shovel",
    "stone_sword": "Stone Sword",
    "bucket": "Bucket",
    "water_bucket": "Water Bucket",

    # Из генератора мира: природные блоки, руды и то, что из них получается.
    "snowy_grass": "Snowy Grass Block",
    "snow": "Snow Block",
    "ice": "Ice",
    "gravel": "Gravel",
    "clay": "Clay",
    "sandstone": "Sandstone",
    "cactus": "Cactus",
    "bedrock": "Bedrock",
    "birch_log": "Birch Log",
    "birch_planks": "Birch Planks",
    "birch_leaves": "Birch Leaves",
    "spruce_log": "Spruce Log",
    "spruce_planks": "Spruce Planks",
    "spruce_leaves": "Spruce Leaves",
    "coal_ore": "Coal Ore",
    "iron_ore": "Iron Ore",
    "gold_ore": "Gold Ore",
    "diamond_ore": "Diamond Ore",
    "coal": "Coal",
    "iron_ingot": "Iron Ingot",
    "gold_ingot": "Gold Ingot",
    "diamond": "Diamond",
    "torch": "Torch",
    "glowstone": "Glowstone",
}

# Порядок в палитре творческого режима. Первые девять лежат в хотбаре нового мира.
ALL_ITEMS = tuple(NAMES)

# Предметы, которые нельзя поставить: в руке и в инвентаре они плоские картинки.
FLAT_ITEMS = {
    "stick": "stick.png",
    "charcoal": "charcoal.png",
    "coal": "coal.png",
    "iron_ingot": "iron_ingot.png",
    "gold_ingot": "gold_ingot.png",
    "diamond": "diamond.png",
    # У факела нет отдельной картинки предмета: в руке и в инвентаре текстура блока.
    "torch": "../block/torch.png",
}

# Еда: сколько единиц здоровья возвращает (2 единицы = 1 сердечко). Как в ранних
# версиях, без голода: съел, и здоровье сразу прибавилось.
FOODS = {
    "apple": 4,
    "bread": 5,
    "porkchop": 3,
    "cooked_porkchop": 8,
    "cookie": 1,
    "golden_apple": 20,
}

for _food in FOODS:
    FLAT_ITEMS[_food] = _food + ".png"


class Tool(NamedTuple):
    # pickaxe, axe, shovel или sword: от вида зависит, какие блоки он ломает быстрее.
    kind: str
    # Во сколько раз быстрее ломаются подходящие блоки.
    speed: float
    # Сколько раз можно воспользоваться, прежде чем инструмент сломается.
    uses: int


# Как в оригинале: деревянные вдвое быстрее руки и служат 60 раз,
# каменные вчетверо быстрее и служат 132 раза.
TOOLS = {
    "wooden_pickaxe": Tool("pickaxe", 2.0, 60),
    "wooden_axe": Tool("axe", 2.0, 60),
    "wooden_shovel": Tool("shovel", 2.0, 60),
    "wooden_sword": Tool("sword", 1.5, 60),
    "stone_pickaxe": Tool("pickaxe", 4.0, 132),
    "stone_axe": Tool("axe", 4.0, 132),
    "stone_shovel": Tool("shovel", 4.0, 132),
    "stone_sword": Tool("sword", 1.5, 132),
}

for _tool in TOOLS:
    FLAT_ITEMS[_tool] = _tool + ".png"

# Пустое ведро черпает воду, полное выливает. Пустые складываются по 16, полные нет.
BUCKETS = {"bucket": 16, "water_bucket": 1}

for _bucket in BUCKETS:
    FLAT_ITEMS[_bucket] = _bucket + ".png"


def max_stack(item):
    """Инструменты не складываются, вёдра по-своему, остальное до MAX_STACK."""
    if item in TOOLS:
        return 1

    return BUCKETS.get(item, MAX_STACK)

# Редкая добыча сверх основной: (предмет, вероятность). В оригинале яблоко падает
# с листвы с шансом 1/200, но у нас листва не опадает сама, её ломают руками,
# поэтому шанс выше.
BONUS_DROPS = {
    "oak_leaves": [("apple", 1 / 20)],
}

# Из всей листвы иногда выпадает палка, как в оригинале.
for _leaves in ("oak_leaves", "birch_leaves", "spruce_leaves"):
    BONUS_DROPS.setdefault(_leaves, []).append(("stick", 1 / 25))

# Что выпадает в выживании, если не сам блок. None значит, что не выпадает ничего.
DROPS = {
    "grass": "dirt",
    "snowy_grass": "dirt",
    "stone": "cobblestone",
    "glass": None,
    "ice": None,
    "oak_leaves": None,
    "birch_leaves": None,
    "spruce_leaves": None,
    "coal_ore": "coal",
    "diamond_ore": "diamond",
}

INVENTORY_SIZE = 36
HOTBAR_SIZE = 9


def item_name(item):
    return NAMES.get(item, item)


def is_known_item(item):
    return item in NAMES


def is_placeable(item):
    return item in BLOCKS or is_door(item) or item in TORCHES


def flat_texture(item):
    """Плоская картинка предмета: у дверей и простых предметов. У кубов None."""
    if item in FLAT_ITEMS:
        return ITEM_TEXTURES + FLAT_ITEMS[item]

    if is_door(item):
        return ITEM_TEXTURES + DOORS[item][2]

    return None


def drop_for(block_type):
    return DROPS.get(block_type, block_type)


def bonus_drops(block_type):
    """Предметы, которым повезло выпасть вдобавок к основной добыче."""
    return [item for item, chance in BONUS_DROPS.get(block_type, []) if random.random() < chance]


class Stack:
    __slots__ = ("type", "count", "damage")

    def __init__(self, item, count=1, damage=0):
        self.type = item
        self.count = count
        # Износ инструмента: сколько использований уже потрачено.
        self.damage = damage

    def copy(self):
        return Stack(self.type, self.count, self.damage)

    def __repr__(self):
        wear = f", damage={self.damage}" if self.damage else ""
        return f"Stack({self.type!r}, {self.count}{wear})"

    def to_json(self):
        return [self.type, self.count, self.damage] if self.damage else [self.type, self.count]

    @classmethod
    def from_json(cls, value):
        """Стак из сохранения или None, если ячейка пуста или запись испорчена."""
        if not isinstance(value, list) or len(value) not in (2, 3):
            return None

        item, count, *rest = value
        damage = rest[0] if rest else 0

        # Предмет убранного из игры блока превращается в то, чем блок стал.
        item = REMOVED.get(item, item)

        if not is_known_item(item) or type(count) is not int or not 1 <= count <= max_stack(item):
            return None

        uses = TOOLS[item].uses if item in TOOLS else 1

        if type(damage) is not int or not 0 <= damage < uses:
            return None

        return cls(item, count, damage)


def slots_to_json(slots):
    return [None if stack is None else stack.to_json() for stack in slots]


def slots_from_json(value, size):
    slots = [None] * size

    if isinstance(value, list):
        for index, item in enumerate(value[:size]):
            slots[index] = Stack.from_json(item)

    return slots


def insert(slots, stack, indices=None):
    """Кладёт стак в ячейки: сначала докладывает к таким же, потом в пустые.

    Меняет stack.count и возвращает остаток (0, если поместилось всё).
    """
    indices = range(len(slots)) if indices is None else indices
    limit = max_stack(stack.type)

    for index in indices:
        held = slots[index]

        if held is not None and held.type == stack.type and held.count < limit:
            moved = min(stack.count, limit - held.count)
            held.count += moved
            stack.count -= moved

            if stack.count == 0:
                return 0

    # В пустые ячейки не больше стака за раз: инструменты ложатся по одному.
    for index in indices:
        if slots[index] is None:
            placed = stack.copy()
            placed.count = min(stack.count, limit)
            slots[index] = placed
            stack.count -= placed.count

            if stack.count == 0:
                return 0

    return stack.count


class PlayerInventory:
    """36 ячеек: 0-8 это хотбар, 9-35 основной инвентарь."""

    def __init__(self, slots=None):
        self.slots = slots if slots is not None else [None] * INVENTORY_SIZE

    @property
    def hotbar(self):
        return self.slots[:HOTBAR_SIZE]

    def add(self, item, count=1):
        """Возвращает, сколько не поместилось. Сначала хотбар, потом основной."""
        return insert(self.slots, Stack(item, count))

    def take_one(self, index):
        stack = self.slots[index]

        if stack is not None:
            stack.count -= 1

            if stack.count == 0:
                self.slots[index] = None

    @classmethod
    def creative_default(cls):
        inventory = cls()

        for index, item in enumerate(ALL_ITEMS[:HOTBAR_SIZE]):
            inventory.slots[index] = Stack(item)

        return inventory
