"""Броня как в 1.0: шлем, нагрудник, поножи и ботинки из кожи, железа, золота и алмаза.

Каждая часть даёт очки защиты (полная алмазная броня 20 очков, это 10 значков
над сердечками). Каждое очко снимает 4% урона от мобов: урон умножается на
(25 - очки) / 25. От падения и воды броня не спасает. От каждого принятого
удара части брони изнашиваются и в конце ломаются.

Модели брони на персонаже берутся из ресурс-пака (models/armor/*_layer_1.png и
_layer_2.png, развёртка 64 x 32 как у скина). Кожаная броня там серая: в
оригинале её красят, у нас она всегда коричневая.
"""
import random
from typing import NamedTuple

SLOTS = ("helmet", "chestplate", "leggings", "boots")
SLOT_NAMES = {"helmet": "Helmet", "chestplate": "Chestplate", "leggings": "Leggings", "boots": "Boots"}
LEATHER_NAMES = {"helmet": "Leather Cap", "chestplate": "Leather Tunic", "leggings": "Leather Pants", "boots": "Leather Boots"}

# Прочность части: основа материала, умноженная на множитель части, как в 1.0.
SLOT_DURABILITY = {"helmet": 11, "chestplate": 16, "leggings": 15, "boots": 13}


class Material(NamedTuple):
    # Предмет для крафта.
    ingredient: str
    # Очки защиты шлема, нагрудника, поножей и ботинок.
    points: tuple
    durability: int
    # Имя развёртки в models/armor.
    layer: str
    title: str


MATERIALS = {
    "leather": Material("leather", (1, 3, 2, 1), 5, "leather", "Leather"),
    "golden": Material("gold_ingot", (2, 5, 3, 1), 7, "gold", "Golden"),
    "iron": Material("iron_ingot", (2, 6, 5, 2), 15, "iron", "Iron"),
    "diamond": Material("diamond", (3, 8, 6, 3), 33, "diamond", "Diamond"),
}

LEATHER_COLOR = (160, 101, 64)
ITEM_TEXTURES = "assets/minecraft/textures/item/"
ARMOR_TEXTURES = "assets/minecraft/textures/models/armor/"
GENERATED = "generated:"


class Piece(NamedTuple):
    material: str
    slot: int
    points: int
    uses: int


ARMOR = {}

for _material, _info in MATERIALS.items():
    for _slot, _name in enumerate(SLOTS):
        ARMOR[f"{_material}_{_name}"] = Piece(
            _material, _slot, _info.points[_slot], _info.durability * SLOT_DURABILITY[_name]
        )


def item_name(item):
    piece = ARMOR[item]
    slot = SLOTS[piece.slot]

    if piece.material == "leather":
        return LEATHER_NAMES[slot]

    return f"{MATERIALS[piece.material].title} {SLOT_NAMES[slot]}"


def item_texture(item):
    """Картинка предмета: путь в паке или ключ покрашенной в коде кожаной."""
    if ARMOR[item].material == "leather":
        return GENERATED + item

    return ITEM_TEXTURES + item + ".png"


def layer_texture(item, layer):
    """Развёртка брони на теле: слой 1 (шлем, нагрудник, ботинки) или 2 (поножи)."""
    material = MATERIALS[ARMOR[item].material]

    if material.layer == "leather":
        return GENERATED + f"leather_layer_{layer}"

    return ARMOR_TEXTURES + f"{material.layer}_layer_{layer}.png"


def leather_textures():
    """Кожаные текстуры, которые красятся в коде: {ключ: (путь в паке, цвет)}."""
    textures = {GENERATED + item: (ITEM_TEXTURES + item + ".png", LEATHER_COLOR) for item in ARMOR if ARMOR[item].material == "leather"}

    for layer in (1, 2):
        textures[GENERATED + f"leather_layer_{layer}"] = (ARMOR_TEXTURES + f"leather_layer_{layer}.png", LEATHER_COLOR)

    return textures


def recipe_shapes():
    """Формы рецептов по частям, # это материал."""
    return {
        "helmet": ("###", "# #"),
        "chestplate": ("# #", "###", "###"),
        "leggings": ("###", "# #", "# #"),
        "boots": ("# #", "# #"),
    }


def total_points(worn):
    """Очки защиты надетой брони. worn: четыре стака или None."""
    return sum(ARMOR[stack.type].points for stack in worn if stack is not None and stack.type in ARMOR)


def reduce(amount, points):
    """Урон после брони. Дробный остаток проходит с такой же вероятностью."""
    reduced = amount * (25 - min(points, 24)) / 25
    whole = int(reduced)

    return whole + (1 if random.random() < reduced - whole else 0)


def wear(worn, amount):
    """Износ брони от удара силой amount. Возвращает, сколько частей сломалось."""
    broken = 0

    for index, stack in enumerate(worn):
        if stack is None or stack.type not in ARMOR:
            continue

        stack.damage += max(1, amount // 4)

        if stack.damage >= ARMOR[stack.type].uses:
            worn[index] = None
            broken += 1

    return broken


# Модель брони на теле: какие части скина повторяет каждая часть брони, насколько
# она шире тела (в пикселях скина), с какого места развёртки и из какого слоя.
MODEL_PARTS = {
    "helmet": (("head", 1.0, (0, 0), 1),),
    "chestplate": (("body", 1.0, (16, 16), 1), ("right_arm", 1.0, (40, 16), 1), ("left_arm", 1.0, (40, 16), 1)),
    "leggings": (("body", 0.5, (16, 16), 2), ("right_leg", 0.5, (0, 16), 2), ("left_leg", 0.5, (0, 16), 2)),
    "boots": (("right_leg", 1.0, (0, 16), 1), ("left_leg", 1.0, (0, 16), 1)),
}
