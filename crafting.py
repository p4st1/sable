"""Рецепты верстака и сетки 2x2 в инвентаре.

Рецепт по форме можно сложить в любом месте сетки и зеркально по горизонтали.
Рецепт без формы требует только нужный набор предметов.
"""
from collections import Counter
from typing import NamedTuple

import armor


class Shaped(NamedTuple):
    pattern: tuple
    key: dict
    result: str
    count: int = 1


class Shapeless(NamedTuple):
    ingredients: tuple
    result: str
    count: int = 1


# Любые доски годятся там, где в рецепте доски. Ключ рецепта может быть набором.
PLANKS = frozenset({"oak_planks", "birch_planks", "spruce_planks"})

# Камень для инструментов и печки: булыжник, как в оригинале.
STONES = frozenset({"cobblestone"})


def tools(material, prefix):
    """Кирка, топор, лопата и меч: # материал, | палка."""
    return (
        Shaped(("###", " | ", " | "), {"#": material, "|": "stick"}, f"{prefix}_pickaxe"),
        Shaped(("##", "#|", " |"), {"#": material, "|": "stick"}, f"{prefix}_axe"),
        Shaped(("#", "|", "|"), {"#": material, "|": "stick"}, f"{prefix}_shovel"),
        Shaped(("#", "#", "|"), {"#": material, "|": "stick"}, f"{prefix}_sword"),
    )


RECIPES = (
    Shapeless(("oak_log",), "oak_planks", 4),
    Shapeless(("birch_log",), "birch_planks", 4),
    Shapeless(("spruce_log",), "spruce_planks", 4),
    Shaped(("#", "#"), {"#": PLANKS}, "stick", 4),
    Shaped(("##", "##"), {"#": PLANKS}, "crafting_table"),
    Shaped(("###", "# #", "###"), {"#": PLANKS}, "chest"),
    Shaped(("###", "# #", "###"), {"#": STONES}, "furnace"),
    # В 1.0 дверь одна, деревянная: из любых досок.
    Shaped(("##", "##", "##"), {"#": PLANKS}, "oak_door", 3),
    Shaped(("##", "##"), {"#": "sand"}, "sandstone"),
    Shaped(("###", "PPP"), {"#": "white_wool", "P": PLANKS}, "bed"),
    Shaped((" #S", "# S", " #S"), {"#": "stick", "S": "string"}, "bow"),
    Shaped(("I ", " F"), {"I": "iron_ingot", "F": "flint"}, "flint_and_steel"),
    Shaped(("# #", " # "), {"#": "iron_ingot"}, "bucket"),
    # Глина и кирпичи: комки обжигаются в печке в кирпич, четыре кирпича дают блок.
    Shaped(("##", "##"), {"#": "clay_ball"}, "clay"),
    Shaped(("##", "##"), {"#": "brick"}, "bricks"),
    # Блоки металлов и алмазов и обратно, как в 1.0.
    *(
        recipe
        for item, block in (("gold_ingot", "gold_block"), ("iron_ingot", "iron_block"), ("diamond", "diamond_block"))
        for recipe in (Shaped(("###", "###", "###"), {"#": item}, block), Shapeless((block,), item, 9))
    ),
    Shaped(("# #", "###", "# #"), {"#": "stick"}, "ladder", 2),
    Shaped(("###", "###"), {"#": "glass"}, "glass_pane", 16),
    Shaped(("###", "###"), {"#": "iron_ingot"}, "iron_bars", 16),
    # Плиты: три блока в ряд дают три плиты, как в 1.0.
    Shaped(("###",), {"#": "stone"}, "stone_slab", 3),
    Shaped(("###",), {"#": "sandstone"}, "sandstone_slab", 3),
    Shaped(("###",), {"#": PLANKS}, "oak_slab", 3),
    Shaped(("###",), {"#": "cobblestone"}, "cobblestone_slab", 3),
    Shaped(("###",), {"#": "bricks"}, "brick_slab", 3),
    Shaped(("###",), {"#": "stone_bricks"}, "stone_brick_slab", 3),
    Shaped(("#", "|"), {"#": frozenset({"coal", "charcoal"}), "|": "stick"}, "torch", 4),
    # Для построек, как в 1.0: ступенек выходит четыре, забора два.
    Shaped(("#  ", "## ", "###"), {"#": PLANKS}, "oak_stairs", 4),
    Shaped(("#  ", "## ", "###"), {"#": STONES}, "cobblestone_stairs", 4),
    Shaped(("###", "###"), {"#": "stick"}, "oak_fence", 2),
    Shaped(("#  ", "## ", "###"), {"#": "bricks"}, "brick_stairs", 4),
    Shaped(("#  ", "## ", "###"), {"#": "stone_bricks"}, "stone_brick_stairs", 4),
    Shaped(("|#|", "|#|"), {"|": "stick", "#": PLANKS}, "fence_gate"),
    # Как в 1.0: книга из трёх листов бумаги, без кожи.
    Shaped(("###",), {"#": "sugar_cane"}, "paper", 3),
    Shaped(("#", "#", "#"), {"#": "paper"}, "book"),
    Shaped(("###", "BBB", "###"), {"#": PLANKS, "B": "book"}, "bookshelf"),
    Shaped(("##", "##"), {"#": "stone"}, "stone_bricks", 4),
    # Ад: светокамень из пыли и золото из самородков, как в 1.0.
    Shaped(("##", "##"), {"#": "glowstone_dust"}, "glowstone"),
    Shaped(("###", "###", "###"), {"#": "gold_nugget"}, "gold_ingot"),
    Shapeless(("gold_ingot",), "gold_nugget", 9),
    *tools(PLANKS, "wooden"),
    *tools(STONES, "stone"),
    *tools("iron_ingot", "iron"),
    *tools("gold_ingot", "golden"),
    *tools("diamond", "diamond"),
    # Броня: шлем, нагрудник, поножи и ботинки из каждого материала.
    *(
        Shaped(shape, {"#": info.ingredient}, f"{material}_{slot}")
        for material, info in armor.MATERIALS.items()
        for slot, shape in armor.recipe_shapes().items()
    ),
)


def trim(grid, width):
    """Убирает пустые строки и столбцы по краям. grid это типы предметов построчно."""
    rows = [grid[index:index + width] for index in range(0, len(grid), width)]

    filled_rows = [index for index, row in enumerate(rows) if any(row)]
    filled_columns = [
        column for column in range(width)
        if any(row[column] for row in rows)
    ]

    if not filled_rows:
        return ()

    return tuple(
        tuple(rows[row][column] for column in range(filled_columns[0], filled_columns[-1] + 1))
        for row in range(filled_rows[0], filled_rows[-1] + 1)
    )


def shape_of(recipe):
    return tuple(
        tuple(recipe.key.get(char) for char in line)
        for line in recipe.pattern
    )


def fits(cell, wanted):
    """Подходит ли предмет в ячейке под клетку рецепта: тип или набор типов."""
    if isinstance(wanted, frozenset):
        return cell in wanted

    return cell == wanted


def same_shape(shape, wanted):
    return len(shape) == len(wanted) and all(
        len(row) == len(wanted_row) and all(fits(cell, want) for cell, want in zip(row, wanted_row))
        for row, wanted_row in zip(shape, wanted)
    )


def find_recipe(grid, width):
    """Рецепт для сетки или None. grid: список типов предметов (None для пустых ячеек)."""
    shape = trim(grid, width)

    if not shape:
        return None

    items = Counter(item for item in grid if item is not None)

    for recipe in RECIPES:
        if isinstance(recipe, Shapeless):
            if items == Counter(recipe.ingredients):
                return recipe

            continue

        wanted = shape_of(recipe)
        mirrored = tuple(tuple(reversed(row)) for row in wanted)

        if same_shape(shape, wanted) or same_shape(shape, mirrored):
            return recipe

    return None
