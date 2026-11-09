"""Экраны с ячейками: инвентарь игрока, верстак, сундук, печка и палитра творческого режима.

Правила кликов как в оригинале:
- левый клик берёт весь стак, кладёт весь стак, докладывает к такому же или меняет местами;
- правый клик берёт половину стака или кладёт по одному;
- Shift+клик перекладывает стак между инвентарём и контейнером;
- цифра над ячейкой меняет её со слотом хотбара;
- зажать кнопку на ячейке и отпустить на другой — перетащить стак.
Координаты ячеек в единицах интерфейса от левого верхнего угла окна, это угол рамки.
"""
import math

import pygame

from containers import FUEL, FUEL_SLOT, INPUT, OUTPUT, SMELT_TIME, SMELTING
from crafting import find_recipe
from gui import PANEL, PANEL_DARK, PANEL_LIGHT, PANEL_TITLE, SLOT_DARK
import armor
from items import ALL_ITEMS, HOTBAR_SIZE, Stack, item_name, max_stack
from textures import load_surface

WIDTH = 176
FIGURE_BACKGROUND = (40, 40, 40)
SLOT = 18
BIG_SLOT = 26


class Slot:
    """Ячейка, которая хранит стак в списке items под номером index."""
    output = False
    source = False

    def __init__(self, items, index, x, y, accepts=None, output=False, size=SLOT):
        self.items = items
        self.index = index
        self.x = x
        self.y = y
        self.accepts = accepts
        self.output = output
        self.size = size

    def get(self):
        return self.items[self.index]

    def set(self, stack):
        self.items[self.index] = stack

    def can_place(self, stack):
        return not self.output and (self.accepts is None or self.accepts(stack.type))


class ArmorSlot(Slot):
    """Ячейка брони: принимает только свою часть, пустая показывает силуэт."""

    def __init__(self, items, index, x, y):
        super().__init__(items, index, x, y, accepts=lambda item: item in armor.ARMOR and armor.ARMOR[item].slot == index)
        self.placeholder = f"assets/minecraft/textures/item/empty_armor_slot_{armor.SLOTS[index]}.png"


class ResultSlot:
    """Результат крафта: его можно только забрать, и тогда тратятся ингредиенты."""
    output = True
    source = False
    size = BIG_SLOT

    def __init__(self, screen, x, y, size=BIG_SLOT):
        self.screen = screen
        self.x = x
        self.y = y
        self.size = size

    def get(self):
        return self.screen.craft_result()

    def can_place(self, stack):
        return False

    def take(self):
        self.screen.consume_ingredients()


class SourceSlot:
    """Ячейка палитры творческого режима: отдаёт копию предмета и не кончается."""
    output = True
    source = True
    size = SLOT

    def __init__(self, item, x, y):
        self.item = item
        self.x = x
        self.y = y

    def get(self):
        return None if self.item is None else Stack(self.item)

    def can_place(self, stack):
        return False


def fits(slots, stack):
    """Поместится ли стак в эти ячейки целиком."""
    room = 0

    for slot in slots:
        held = slot.get()

        if held is None:
            room += max_stack(stack.type)
        elif held.type == stack.type:
            room += max_stack(stack.type) - held.count

    return room >= stack.count


def insert(slots, stack):
    """Кладёт стак в ячейки: сначала к таким же, потом в пустые. Возвращает остаток."""
    for slot in slots:
        held = slot.get()

        if held is not None and held.type == stack.type and held.count < max_stack(stack.type) and slot.can_place(stack):
            moved = min(stack.count, max_stack(stack.type) - held.count)
            held.count += moved
            stack.count -= moved

            if stack.count == 0:
                return 0

    for slot in slots:
        if slot.get() is None and slot.can_place(stack):
            slot.set(stack.copy())
            stack.count = 0
            return 0

    return stack.count


class ContainerScreen:
    title = ""
    width = WIDTH
    title_x = 8
    height = 166
    # Подпись "Inventory" и ячейки игрока: основной инвентарь и хотбар под ним.
    inventory_top = 83
    inventory_label = True
    # Стак, брошенный мимо окна, вылетает в мир, а из палитры творческого режима исчезает.
    discard_outside = False

    def __init__(self, game):
        self.game = game

        self.cursor = None
        self.pressed = None
        self.picked_up = False

        self.slots = []
        self.player_slots = []
        self.hotbar_slots = []

    @property
    def inventory(self):
        return self.game.inventory

    @property
    def show_counts(self):
        return self.game.survival

    def add_player_slots(self, top=None, main=True):
        top = self.inventory_top if top is None else top
        slots = self.inventory.slots

        if main:
            for row in range(3):
                for column in range(9):
                    index = HOTBAR_SIZE + row * 9 + column
                    self.player_slots.append(Slot(slots, index, 7 + column * SLOT, top + row * SLOT))

            top += 3 * SLOT + 4

        for column in range(HOTBAR_SIZE):
            slot = Slot(slots, column, 7 + column * SLOT, top)
            self.hotbar_slots.append(slot)
            self.player_slots.append(slot)

        self.slots += self.player_slots

    # Разметка.

    def corner(self):
        width, height = self.game.gui.units(self.game.screen)

        return (width - self.width) // 2, (height - self.height) // 2

    def slot_rect(self, slot):
        left, top = self.corner()

        return self.game.gui.to_pixels((left + slot.x, top + slot.y, slot.size, slot.size))

    def slot_at(self, position):
        for slot in self.slots:
            if self.slot_rect(slot).collidepoint(position):
                return slot

        return None

    def inside(self, position):
        left, top = self.corner()

        return self.game.gui.to_pixels((left, top, self.width, self.height)).collidepoint(position)

    # Ввод.

    def press(self, position, button, shift=False):
        slot = self.slot_at(position)
        self.pressed = slot
        self.picked_up = False

        if slot is None:
            if self.cursor is not None and not self.inside(position):
                self.drop_cursor(whole_stack=button == 1)

            return

        had_cursor = self.cursor is not None
        self.click(slot, button, shift)
        self.picked_up = not had_cursor and self.cursor is not None

    def release(self, position):
        pressed, self.pressed = self.pressed, None

        # Стак подняли нажатием и отпустили над другой ячейкой: это перетаскивание.
        if not self.picked_up or self.cursor is None:
            return

        slot = self.slot_at(position)

        if slot is not None and slot is not pressed:
            self.click(slot, 1, False)

        elif slot is None and not self.inside(position):
            self.drop_cursor()

    def drop_cursor(self, whole_stack=True):
        """Стак с курсора за окном: ЛКМ бросает весь, ПКМ по одному, как в оригинале."""
        if self.discard_outside:
            self.cursor = None
            return

        thrown = self.cursor.copy()

        if not whole_stack:
            thrown.count = 1

        self.cursor.count -= thrown.count

        if self.cursor.count == 0:
            self.cursor = None

        self.game.throw(thrown)

    def click(self, slot, button, shift):
        if slot.source:
            self.click_source(slot, shift)
        elif isinstance(slot, ResultSlot):
            self.click_result(slot, shift)
        elif shift:
            self.quick_move(slot)
        elif button == 1:
            self.left_click(slot)
        elif button == 3:
            self.right_click(slot)

    def left_click(self, slot):
        stack = slot.get()
        cursor = self.cursor

        if cursor is None:
            if stack is not None:
                self.cursor = stack
                slot.set(None)

        elif not slot.can_place(cursor):
            # Из выхода печки можно только забирать, докладывая к стаку на курсоре.
            if slot.output and stack is not None and stack.type == cursor.type:
                moved = min(stack.count, max_stack(cursor.type) - cursor.count)
                cursor.count += moved
                stack.count -= moved

                if stack.count == 0:
                    slot.set(None)

        elif stack is None:
            slot.set(cursor)
            self.cursor = None

        elif stack.type == cursor.type and stack.count < max_stack(stack.type):
            moved = min(cursor.count, max_stack(stack.type) - stack.count)
            stack.count += moved
            cursor.count -= moved

            if cursor.count == 0:
                self.cursor = None

        else:
            slot.set(cursor)
            self.cursor = stack

    def right_click(self, slot):
        stack = slot.get()
        cursor = self.cursor

        if cursor is None:
            if stack is not None:
                half = math.ceil(stack.count / 2)
                # Копия, а не новый стак: у инструмента сохраняется износ.
                self.cursor = stack.copy()
                self.cursor.count = half
                stack.count -= half

                if stack.count == 0:
                    slot.set(None)

            return

        if not slot.can_place(cursor):
            return

        if stack is None:
            placed = cursor.copy()
            placed.count = 1
            slot.set(placed)
        elif stack.type == cursor.type and stack.count < max_stack(stack.type):
            stack.count += 1
        else:
            return

        cursor.count -= 1

        if cursor.count == 0:
            self.cursor = None

    def click_source(self, slot, shift):
        # С предметом на курсоре палитра работает как мусорка.
        if self.cursor is not None:
            self.cursor = None
            return

        stack = slot.get()

        if stack is None:
            return

        if shift:
            empty = [hotbar for hotbar in self.hotbar_slots if hotbar.get() is None]
            target = empty[0] if empty else self.hotbar_slots[self.game.selected_slot]
            target.set(stack)
        else:
            self.cursor = stack

    def click_result(self, slot, shift):
        result = slot.get()

        if result is None:
            return

        if shift:
            # Крафтим, пока есть ингредиенты и место в инвентаре.
            while result is not None and fits(self.player_slots, result):
                insert(self.player_slots, result.copy())
                slot.take()
                result = slot.get()

            return

        if self.cursor is None:
            self.cursor = result
        elif self.cursor.type == result.type and self.cursor.count + result.count <= max_stack(result.type):
            self.cursor.count += result.count
        else:
            return

        slot.take()

    def quick_move(self, slot):
        stack = slot.get()

        if stack is None:
            return

        insert(self.quick_move_targets(slot), stack)

        if stack.count == 0:
            slot.set(None)

    def quick_move_targets(self, slot):
        """Куда Shift+клик переносит стак из этой ячейки."""
        if slot in self.player_slots:
            container = self.container_slots()

            if container:
                return container

            # Без контейнера стак прыгает между хотбаром и основным инвентарём.
            if slot in self.hotbar_slots:
                return [other for other in self.player_slots if other not in self.hotbar_slots]

            return self.hotbar_slots

        return self.player_slots

    def container_slots(self):
        """Ячейки контейнера, куда можно класть из инвентаря по Shift+клику."""
        return []

    def number_key(self, number, position):
        slot = self.slot_at(position)
        target = self.hotbar_slots[number]

        if slot is None or self.cursor is not None or slot is target:
            return

        if slot.source:
            target.set(slot.get())
            return

        if isinstance(slot, ResultSlot):
            result = slot.get()

            if result is not None and target.get() is None:
                target.set(result)
                slot.take()

            return

        stack, swapped = slot.get(), target.get()

        if (stack is None or target.can_place(stack)) and (swapped is None or slot.can_place(swapped)):
            slot.set(swapped)
            target.set(stack)

    def close(self):
        """Возвращает стак с курсора и всё из сетки крафта в инвентарь."""
        leftovers = [self.cursor] + self.returned_on_close()
        self.cursor = None

        for stack in leftovers:
            # Что не поместилось в инвентарь, выпадает под ноги, а не пропадает.
            if stack is not None and insert(self.hotbar_slots + self.player_slots, stack) > 0:
                self.game.throw(stack)

    def returned_on_close(self):
        return []

    # Отрисовка.

    def render(self, screen):
        gui = self.game.gui
        left, top = self.corner()
        mouse = pygame.mouse.get_pos()

        gui.darken(screen, 110)
        gui.draw_panel(screen, left, top, self.width, self.height)

        if self.title:
            gui.draw_text(screen, self.title, (left + self.title_x, top + 6), PANEL_TITLE, 'topleft', shadow=False)

        if self.inventory_label:
            gui.draw_text(screen, "Inventory", (left + 8, top + self.inventory_top - 11), PANEL_TITLE, 'topleft', shadow=False)

        self.render_extras(screen, left, top)

        hovered = self.slot_at(mouse)

        for slot in self.slots:
            gui.draw_slot(
                screen,
                left + slot.x,
                top + slot.y,
                slot.get(),
                slot is hovered,
                slot.size,
                self.show_counts or isinstance(slot, ResultSlot)
            )

            if isinstance(slot, ArmorSlot) and slot.get() is None:
                self.draw_placeholder(screen, left + slot.x, top + slot.y, slot.placeholder)

        if self.cursor is not None:
            icon = gui.get_block_icon(self.cursor.type)
            rect = icon.get_rect(center=mouse)
            screen.blit(icon, rect)

            if self.show_counts:
                gui.blit_count(screen, self.cursor.count, rect.bottomright)

        elif hovered is not None and hovered.get() is not None:
            gui.draw_tooltip(screen, item_name(hovered.get().type), mouse)

    def render_extras(self, screen, left, top):
        pass

    def draw_placeholder(self, screen, x, y, path):
        """Силуэт пустой ячейки брони из ресурс-пака, если он там есть."""
        gui = self.game.gui
        key = ('placeholder', path)

        if key not in gui.sprites:
            try:
                icon = load_surface(path).convert_alpha()
            except (FileNotFoundError, pygame.error):
                icon = None

            gui.sprites[key] = None if icon is None else pygame.transform.scale(icon, (16 * gui.scale, 16 * gui.scale))

        if gui.sprites[key] is not None:
            screen.blit(gui.sprites[key], gui.to_pixels((x + 1, y + 1, 16, 16)).topleft)


class CraftingGrid:
    """Сетка крафта и её результат. Предметы лежат в self.grid построчно."""

    def setup_grid(self, size, x, y, result_x, result_y, result_size):
        self.grid_size = size
        self.grid = [None] * (size * size)
        self.grid_slots = [
            Slot(self.grid, row * size + column, x + column * SLOT, y + row * SLOT)
            for row in range(size)
            for column in range(size)
        ]
        self.result_slot = ResultSlot(self, result_x, result_y, result_size)
        self.slots += self.grid_slots + [self.result_slot]

    def craft_result(self):
        recipe = find_recipe([None if stack is None else stack.type for stack in self.grid], self.grid_size)

        return None if recipe is None else Stack(recipe.result, recipe.count)

    def consume_ingredients(self):
        for index, stack in enumerate(self.grid):
            if stack is not None:
                stack.count -= 1

                if stack.count == 0:
                    self.grid[index] = None

    def returned_on_close(self):
        leftovers = [stack for stack in self.grid if stack is not None]
        self.grid[:] = [None] * len(self.grid)

        return leftovers


class InventoryScreen(CraftingGrid, ContainerScreen):
    """Инвентарь выживания: броня слева, фигурка игрока, сетка 2x2 справа сверху и все 36 ячеек."""
    title = "Crafting"
    title_x = 97
    inventory_label = False

    # Окошко с фигуркой между бронёй и крафтом, в единицах интерфейса.
    FIGURE = (26, 8, 49, 70)

    def __init__(self, game):
        super().__init__(game)
        self.setup_grid(2, 97, 17, 152, 26, SLOT)

        self.armor_slots = [ArmorSlot(self.inventory.armor, index, 7, 7 + index * SLOT) for index in range(len(armor.SLOTS))]
        self.slots += self.armor_slots
        self.add_player_slots()

    def quick_move_targets(self, slot):
        # Броня из инвентаря по Shift+клику надевается, если её место свободно.
        if slot in self.player_slots:
            stack = slot.get()

            if stack.type in armor.ARMOR:
                target = self.armor_slots[armor.ARMOR[stack.type].slot]

                if target.get() is None:
                    return [target]

        return super().quick_move_targets(slot)

    def render_extras(self, screen, left, top):
        gui = self.game.gui
        gui.draw_arrow(screen, left + 136, top + 28)

        x, y, width, height = self.FIGURE
        gui.fill(screen, (left + x - 1, top + y - 1, width + 2, height + 2), (0, 0, 0))
        gui.fill(screen, (left + x, top + y, width, height), FIGURE_BACKGROUND)

        rect = gui.to_pixels((left + x, top + y, width, height))
        mouse_x, mouse_y = pygame.mouse.get_pos()
        # Глаза фигурки примерно на пятой части высоты окошка.
        eyes = (rect.centerx, rect.y + rect.height * 0.2)

        image = self.game.figure.render(
            self.game.player_skin,
            self.inventory.armor,
            rect.width,
            rect.height,
            (mouse_x - eyes[0]) / gui.scale,
            (mouse_y - eyes[1]) / gui.scale,
        )
        screen.blit(image, rect.topleft)


class CraftingScreen(CraftingGrid, ContainerScreen):
    title = "Crafting"

    def __init__(self, game):
        super().__init__(game)
        self.setup_grid(3, 29, 16, 119, 30, BIG_SLOT)
        self.add_player_slots()

    def render_extras(self, screen, left, top):
        self.game.gui.draw_arrow(screen, left + 90, top + 35)


class ChestScreen(ContainerScreen):
    title = "Chest"
    height = 168
    inventory_top = 85

    def __init__(self, game, chest):
        super().__init__(game)
        self.chest = chest
        self.chest_slots = [
            Slot(chest.slots, row * 9 + column, 7 + column * SLOT, 17 + row * SLOT)
            for row in range(3)
            for column in range(9)
        ]
        self.slots += self.chest_slots
        self.add_player_slots()

    def container_slots(self):
        return self.chest_slots


class FurnaceScreen(ContainerScreen):
    title = "Furnace"

    def __init__(self, game, furnace):
        super().__init__(game)
        self.furnace = furnace

        self.input_slot = Slot(furnace.slots, INPUT, 55, 16)
        self.fuel_slot = Slot(furnace.slots, FUEL_SLOT, 55, 52, accepts=lambda item: item in FUEL)
        self.output_slot = Slot(furnace.slots, OUTPUT, 111, 30, output=True, size=BIG_SLOT)

        self.slots += [self.input_slot, self.fuel_slot, self.output_slot]
        self.add_player_slots()

    def quick_move_targets(self, slot):
        if slot in self.player_slots:
            stack = slot.get()

            # Топливо идёт в топку, то, что плавится, во вход.
            if stack.type in SMELTING:
                return [self.input_slot]
            if stack.type in FUEL:
                return [self.fuel_slot]

        return super().quick_move_targets(slot)

    def render_extras(self, screen, left, top):
        gui = self.game.gui
        furnace = self.furnace

        burning = furnace.burn_left / furnace.burn_total if furnace.burn_total else 0
        gui.draw_flame(screen, left + 57, top + 36, burning if furnace.lit else 0)
        gui.draw_arrow(screen, left + 79, top + 34, furnace.progress / SMELT_TIME)


# Полоса прокрутки палитры: справа от ячеек, ползунок как в оригинале 12 x 15.
SCROLL_X = 7 + 9 * SLOT + 4
SCROLL_WIDTH = 14
THUMB_HEIGHT = 15
# Сверху и снизу от окна остаётся хотя бы столько места.
SCREEN_MARGIN = 8


class CreativeScreen(ContainerScreen):
    """Палитра творческого режима: бесконечные предметы сверху и хотбар снизу.

    Рядов видно столько, сколько помещается на экране. Если предметов больше,
    справа полоса прокрутки: листают колесом мыши или ползунком. Где
    остановились, игра помнит до следующего открытия.
    """
    title = "Items"
    inventory_label = False
    discard_outside = True

    def __init__(self, game):
        super().__init__(game)

        total_rows = max(1, math.ceil(len(ALL_ITEMS) / 9))
        _, screen_height = game.gui.units(game.screen)
        fixed = 17 + 4 + SLOT + 7
        fit = max(3, (screen_height - fixed - 2 * SCREEN_MARGIN) // SLOT)

        self.rows = min(total_rows, fit)
        self.max_scroll = total_rows - self.rows
        self.scroll = min(getattr(game, "creative_scroll", 0), self.max_scroll)
        self.dragging = False
        self.height = 17 + self.rows * SLOT + 4 + SLOT + 7

        if self.max_scroll:
            self.width = SCROLL_X + SCROLL_WIDTH + 7

        self.grid = [SourceSlot(None, 7 + index % 9 * SLOT, 17 + index // 9 * SLOT) for index in range(self.rows * 9)]
        self.slots += self.grid
        self.fill_grid()

        self.add_player_slots(top=17 + self.rows * SLOT + 4, main=False)

    def fill_grid(self):
        for index, slot in enumerate(self.grid):
            item_index = self.scroll * 9 + index
            slot.item = ALL_ITEMS[item_index] if item_index < len(ALL_ITEMS) else None

    def scroll_to(self, row):
        self.scroll = max(0, min(self.max_scroll, row))
        self.game.creative_scroll = self.scroll
        self.fill_grid()

    def wheel(self, rows):
        """Колесо мыши: rows рядов вниз (отрицательное вверх)."""
        self.scroll_to(self.scroll + rows)

    def track_rect(self):
        """Полоса прокрутки в единицах интерфейса."""
        left, top = self.corner()

        return left + SCROLL_X, top + 17, SCROLL_WIDTH, self.rows * SLOT

    def drag_to(self, position):
        """Ползунок за мышью: середина ползунка под курсором."""
        x, y, width, height = self.track_rect()
        mouse_y = position[1] / self.game.gui.scale
        share = (mouse_y - y - THUMB_HEIGHT / 2) / max(1, height - THUMB_HEIGHT)
        self.scroll_to(round(share * self.max_scroll))

    def press(self, position, button, shift=False):
        if self.max_scroll and button == 1 and self.game.gui.to_pixels(self.track_rect()).collidepoint(position):
            self.dragging = True
            self.drag_to(position)
            return

        super().press(position, button, shift)

    def release(self, position):
        self.dragging = False
        super().release(position)

    def motion(self, position):
        if self.dragging:
            self.drag_to(position)

    def render_extras(self, screen, left, top):
        if not self.max_scroll:
            return

        gui = self.game.gui
        x, y, width, height = self.track_rect()

        # Желоб утоплен, как ячейка.
        gui.fill(screen, (x, y, width, height), PANEL_LIGHT)
        gui.fill(screen, (x, y, width - 1, height - 1), SLOT_DARK)
        gui.fill(screen, (x + 1, y + 1, width - 2, height - 2), (0, 0, 0))

        # Ползунок выпуклый, как кнопка.
        thumb_y = y + 1 + round((height - 2 - THUMB_HEIGHT) * self.scroll / self.max_scroll)
        thumb = (x + 1, thumb_y, width - 2, THUMB_HEIGHT)
        gui.fill(screen, thumb, PANEL_DARK)
        gui.fill(screen, (thumb[0], thumb[1], thumb[2] - 1, thumb[3] - 1), PANEL_LIGHT)
        gui.fill(screen, (thumb[0] + 1, thumb[1] + 1, thumb[2] - 2, thumb[3] - 2), PANEL)
