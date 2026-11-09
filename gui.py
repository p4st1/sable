"""Отрисовка интерфейса: HUD и элементы меню (кнопки, ползунки, текст, логотип).

Разметка меню задаётся в единицах интерфейса: одна единица равна self.scale
пикселей экрана. Сами экраны меню описаны в menu.py.
"""
import colorsys
import math
import os
import random

import numpy as np
import pygame

from block import Block
import shapes
from items import flat_texture, item_name, max_uses
from textures import load_surface


SLOTS = (0, 0, 182, 22)
SELECTED_SLOT = (0, 22, 24, 24)

RED_CIRCLE   = (192, 0, 15, 15)
GREEN_CIRCLE = (208, 0, 15, 15)
GRAY_CIRCLE  = (224, 0, 15, 15)

PLUS = (243, 3, 9, 9)

DISABLED_BAR = (1, 47, 198, 18)
BUTTON_BAR = (1, 67, 198, 18)
HOVER_BAR = (1, 87, 198, 18)

BAR_WIDTH = 198
BAR_HEIGHT = 18
HANDLE_WIDTH = 8
FONT_SIZE = 8

SLOT_STEP = 20
SLOT_PADDING = 3
ICON_SIZE = 16
NAME_OFFSET = 8

# Масштаб интерфейса ограничивается так, чтобы на экране помещалось
# не меньше 320x240 единиц: под этот размер рассчитана разметка меню.
MIN_UNITS = (320, 240)

WHITE = (255, 255, 255)
HOVER_TEXT = (255, 255, 160)
GRAY = (160, 160, 160)
SUBTEXT = (128, 128, 128)
YELLOW = (255, 255, 0)

# Цвета окна инвентаря: светлая панель с объёмной рамкой и вдавленные ячейки.
PANEL = (198, 198, 198)
PANEL_LIGHT = (255, 255, 255)
PANEL_DARK = (85, 85, 85)
PANEL_TITLE = (64, 64, 64)
SLOT = (139, 139, 139)
SLOT_DARK = (55, 55, 55)
ARROW_EMPTY = (139, 139, 139)
FLAME_OUTER = (230, 110, 20)
FLAME_INNER = (255, 220, 70)

# Пиксельные картинки для экранов крафта и печки.
ARROW = (
    "..............#.......",
    "..............##......",
    "..............###.....",
    "..............####....",
    "..............#####...",
    "###################...",
    "####################..",
    "#####################.",
    "####################..",
    "###################...",
    "..............#####...",
    "..............####....",
    "..............###.....",
    "..............##......",
    "..............#.......",
)

FLAME = (
    "......#.......",
    ".....##.......",
    ".....###......",
    "....####......",
    "....#####..#..",
    "...######.##..",
    "..##########..",
    "..###########.",
    ".############.",
    ".#####.######.",
    ".####...#####.",
    ".####....####.",
    "..###....###..",
    "...########...",
)

FLAME_CORE = (
    "..............",
    "..............",
    "..............",
    "..............",
    "..............",
    "......#.......",
    ".....##.......",
    ".....###......",
    "....#####.....",
    "....#...##....",
    "..............",
    "..............",
    "..............",
    "..............",
)

# Сердечко 9x9: контур и заливка. Половинка заливает только левые пять столбцов.
HEART_OUTLINE = (
    ".###.###.",
    "#...#...#",
    "#.......#",
    "#.......#",
    ".#.....#.",
    "..#...#..",
    "...#.#...",
    "....#....",
    ".........",
)

HEART_FILL = (
    ".........",
    ".###.###.",
    ".#######.",
    ".#######.",
    "..#####..",
    "...###...",
    "....#....",
    ".........",
    ".........",
)

HEART_SHINE = (
    ".........",
    ".##......",
    ".#.......",
)

HEART_RED = (220, 20, 30)
HEART_SHINE_COLOR = (255, 170, 170)
HEART_EMPTY = (45, 20, 20)
HEART_BLINK = (255, 255, 255)

# Спрайты сердечек из ресурс-пака, если они есть в assets. Новый формат: отдельные
# файлы; старый: общий атлас icons.png. Без них сердечки рисуются масками выше.
HEART_SPRITES = "assets/minecraft/textures/gui/sprites/hud/heart/"
ICONS = "assets/minecraft/textures/gui/icons.png"
ICON_HEARTS = {
    "container": (16, 0), "container_blinking": (25, 0),
    "full": (52, 0), "half": (61, 0),
    "full_blinking": (70, 0), "half_blinking": (79, 0),
}

# Значки брони из того же атласа: пустой, половинка и целый. Ряд над сердечками.
ICON_ARMOR = {"empty": (16, 9), "half": (25, 9), "full": (34, 9)}
ARMOR_ROW = 10

# Пузырьки воздуха из того же атласа: целый и лопающийся.
ICON_BUBBLES = {"full": (16, 18), "popping": (25, 18)}
BUBBLE_COLOR = (90, 170, 255)
# Лопающийся пузырёк виден столько от доли одного пузырька.
BUBBLE_POP = 0.2

DURABILITY_WIDTH = 13

HEART_SIZE = 9
HEART_STEP = 8
HEARTS_ABOVE_HOTBAR = 17
LOW_HEALTH = 4
JIGGLE_MS = 50

TOOLTIP = (16, 0, 16)
TOOLTIP_BORDER = (40, 0, 110)

LOGO_TEXT = "SABLE"
LOGO_CELL = 6
LOGO_DEPTH = 3
LOGO_TEXTURE = "assets/minecraft/textures/block/sand.png"
LOGO_SIDE = (122, 98, 64)
SPLASH_ANGLE = 20


def make_shape_icon(block_type, size):
    """Изометрическая иконка ступенек и забора: из каждого пикселя пускаем луч в коробки.

    Проекция та же, что у кубика: верх ромбом в верхней половине, грань +z слева
    (светлее), грань +x справа (темнее). Ось Y мира вниз.
    """

    sx, sy = np.meshgrid((np.arange(size) + 0.5) / size, (np.arange(size) + 0.5) / size, indexing='ij')
    # Точка на луче: z = 0, экран x = 0.5 + (x - z) / 2, экран y = (x + z) / 4 + y / 2.
    origin_x = 2 * (sx - 0.5)
    origin_y = 2 * (sy - origin_x / 4)
    origin = np.stack([origin_x, origin_y, np.zeros_like(sx)], axis=-1)
    direction = np.array([-1.0, 1.0, -1.0])

    nearest = np.full(sx.shape, np.inf)
    hit_face = np.full(sx.shape, -1)

    for low, high in shapes.icon_boxes(block_type):
        low, high = np.array(low), np.array(high)
        t1 = (low - origin) / direction
        t2 = (high - origin) / direction
        enter = np.minimum(t1, t2)
        leave = np.maximum(t1, t2)
        t_near = enter.max(axis=-1)
        hit = (t_near <= leave.min(axis=-1)) & (t_near < nearest)
        nearest[hit] = t_near[hit]
        hit_face[hit] = enter.argmax(axis=-1)[hit]

    icon = pygame.Surface((size, size), pygame.SRCALPHA)
    colors = pygame.surfarray.pixels3d(icon)
    alpha = pygame.surfarray.pixels_alpha(icon)
    point = origin + nearest[..., None] * direction

    # Грань по оси входа луча: x -> правая (+x), y -> верх, z -> левая (+z).
    for axis, (u_axis, v_axis, flip_u, shade) in enumerate(((2, 1, True, 0.6), (0, 2, False, 1.0), (0, 1, False, 0.8))):
        # У плит верх своей текстурой.
        image = load_surface(shapes.texture(block_type, "top" if axis == 1 else "side"))
        texture = pygame.surfarray.array3d(image)
        width, height = texture.shape[:2]
        inside = hit_face == axis
        u = point[..., u_axis][inside] % 1.0
        v = point[..., v_axis][inside] % 1.0
        u = 1 - u if flip_u else u
        texel_x = np.clip((u * width).astype(int), 0, width - 1)
        texel_y = np.clip((v * height).astype(int), 0, height - 1)
        colors[inside] = texture[texel_x, texel_y] * shade
        alpha[inside] = 255

    del colors, alpha

    return icon


def make_block_icon(block_type, size):
    """Рисует изометрический кубик: для каждого пикселя иконки ищет точку на грани."""
    if shapes.is_shaped(block_type):
        return make_shape_icon(block_type, size)

    block = Block(block_type)

    x, y = np.meshgrid(
        (np.arange(size) + 0.5) / size,
        (np.arange(size) + 0.5) / size,
        indexing='ij'
    )

    # a и b это координаты на грани от 0 до 1. Верхняя грань ромбом лежит в верхней
    # половине иконки, боковые занимают левую и правую часть низа.
    side_a = 2 * x
    right_a = 2 * (x - 0.5)

    faces = (
        ('right', right_a, 2 * (y - 0.5 + right_a / 4), 0.6),
        ('left', side_a, 2 * (y - 0.25 - side_a / 4), 0.8),
        ('top', x - 2 * (y - 0.25), x + 2 * (y - 0.25), 1.0),
    )

    icon = pygame.Surface((size, size), pygame.SRCALPHA)
    colors = pygame.surfarray.pixels3d(icon)
    alpha = pygame.surfarray.pixels_alpha(icon)

    for face, a, b, shade in faces:
        image = load_surface(Block.get_block_texture(block, face))
        texture = pygame.surfarray.array3d(image)
        texture_alpha = pygame.surfarray.array_alpha(image)

        width, height = texture.shape[:2]
        inside = (a >= 0) & (a < 1) & (b >= 0) & (b < 1)

        texel_x = (a[inside] * width).astype(int)
        texel_y = (b[inside] * height).astype(int)

        colors[inside] = texture[texel_x, texel_y] * shade

        # У стекла сквозь дырки в гранях видно фон слота.
        alpha[inside] = texture_alpha[texel_x, texel_y]

    del colors, alpha

    return icon


def make_logo():
    """Логотип из блоков: каждый пиксель надписи становится кубиком с текстурой и боком.

    Возвращает картинку в единицах интерфейса, масштабируется уже готовая.
    """
    font = pygame.font.Font('fonts/minecraft.ttf', FONT_SIZE)
    mask = pygame.mask.from_surface(font.render(LOGO_TEXT, False, WHITE))

    bounds = mask.get_bounding_rects()[0].unionall(mask.get_bounding_rects())
    cells = [
        (x - bounds.x, y - bounds.y)
        for x in range(bounds.left, bounds.right)
        for y in range(bounds.top, bounds.bottom)
        if mask.get_at((x, y))
    ]

    width = bounds.width * LOGO_CELL
    height = bounds.height * LOGO_CELL

    # Силуэт лицевой стороны: белый внутри, прозрачный снаружи.
    face = pygame.Surface((width, height), pygame.SRCALPHA)

    for x, y in cells:
        face.fill(WHITE, (x * LOGO_CELL, y * LOGO_CELL, LOGO_CELL, LOGO_CELL))

    side = face.copy()
    side.fill(LOGO_SIDE + (255,), special_flags=pygame.BLEND_RGBA_MULT)

    outline = face.copy()
    outline.fill((0, 0, 0, 255), special_flags=pygame.BLEND_RGBA_MULT)

    # Поле на единицу шире с каждой стороны под чёрную обводку.
    logo = pygame.Surface((width + LOGO_DEPTH + 2, height + LOGO_DEPTH + 2), pygame.SRCALPHA)

    for depth in range(LOGO_DEPTH + 1):
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                logo.blit(outline, (1 + depth + dx, 1 + depth + dy))

    for depth in range(LOGO_DEPTH, 0, -1):
        logo.blit(side, (1 + depth, 1 + depth))

    texture = pygame.image.load(LOGO_TEXTURE).convert_alpha()
    top = pygame.Surface((width, height), pygame.SRCALPHA)

    for x in range(0, width, texture.get_width()):
        for y in range(0, height, texture.get_height()):
            top.blit(texture, (x, y))

    top.blit(face, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)

    # Светлый верх и левый край, тёмный низ и правый: кубики видны по отдельности.
    for x, y in cells:
        left, upper = x * LOGO_CELL, y * LOGO_CELL
        last = LOGO_CELL - 1

        top.fill((255, 255, 255, 70), (left, upper, LOGO_CELL, 1), special_flags=pygame.BLEND_RGBA_ADD)
        top.fill((255, 255, 255, 40), (left, upper, 1, LOGO_CELL), special_flags=pygame.BLEND_RGBA_ADD)
        top.fill((50, 50, 50, 0), (left, upper + last, LOGO_CELL, 1), special_flags=pygame.BLEND_RGBA_SUB)
        top.fill((35, 35, 35, 0), (left + last, upper, 1, LOGO_CELL), special_flags=pygame.BLEND_RGBA_SUB)

    logo.blit(top, (1, 1))

    return logo


class Gui:
    def __init__(self, scale, screen_size):
        self.gui_texture = pygame.image.load(
            "assets/minecraft/textures/gui/advancements/backgrounds/widgets.png"
        ).convert_alpha()

        # Заполняются при каждой отрисовке меню: по ним меню узнаёт, куда кликнули.
        self.buttons = {}
        self.sliders = {}

        self.overlays = {}

        self.set_scale(scale, screen_size)

    @staticmethod
    def max_scale(screen_size):
        width, height = screen_size

        return max(1, min(width // MIN_UNITS[0], height // MIN_UNITS[1]))

    def set_scale(self, scale, screen_size):
        self.requested_scale = scale
        self.scale = max(1, min(scale, self.max_scale(screen_size)))
        self.sprites = {}
        self.font = pygame.font.Font('fonts/minecraft.ttf', FONT_SIZE * self.scale)

    def units(self, screen):
        """Размер экрана в единицах интерфейса."""
        return screen.get_width() // self.scale, screen.get_height() // self.scale

    def to_pixels(self, rect):
        x, y, width, height = rect

        return pygame.Rect(x * self.scale, y * self.scale, width * self.scale, height * self.scale)

    def begin_frame(self):
        self.buttons = {}
        self.sliders = {}

    def get_sprite(self, area):
        """Вырезает спрайт из атласа и масштабирует один раз: дальше он берётся из кэша."""
        if area not in self.sprites:
            self.sprites[area] = pygame.transform.scale_by(
                self.gui_texture.subsurface(area),
                self.scale
            )

        return self.sprites[area]

    def get_block_icon(self, block_type, size=ICON_SIZE):
        key = ('icon', block_type, size)

        if key not in self.sprites:
            flat = flat_texture(block_type)

            if flat is not None:
                # У дверей и простых предметов плоская картинка, как в инвентаре.
                self.sprites[key] = pygame.transform.scale(
                    load_surface(flat).convert_alpha(),
                    (size * self.scale, size * self.scale)
                )
            else:
                self.sprites[key] = make_block_icon(block_type, size * self.scale)

        return self.sprites[key]

    def get_logo(self):
        if 'logo' not in self.sprites:
            self.sprites['logo'] = pygame.transform.scale_by(make_logo(), self.scale)

        return self.sprites['logo']

    def render_hud(self, screen, hotbar, selected, show_counts=True, health=None, blink=False, air=None, armor=0):
        """hotbar: девять стаков или None. Количество и сердечки видны только в выживании.

        air: доля оставшегося воздуха от 0 до 1 или None, если пузырьки не нужны.
        armor: очки защиты брони, значки видны только когда они есть.
        """
        center_x = screen.get_width() // 2
        center_y = screen.get_height() // 2

        plus = self.get_sprite(PLUS)

        screen.blit(plus, plus.get_rect(center=(center_x, center_y)))

        slots = self.get_sprite(SLOTS)
        slots_rect = slots.get_rect(midbottom=(center_x, screen.get_height()))

        screen.blit(slots, slots_rect)

        for index, stack in enumerate(hotbar):
            if stack is None:
                continue

            x = slots_rect.x + (SLOT_PADDING + SLOT_STEP * index) * self.scale
            y = slots_rect.y + SLOT_PADDING * self.scale

            screen.blit(self.get_block_icon(stack.type), (x, y))
            self.blit_durability(screen, stack, (x, y))

            if show_counts:
                self.blit_count(screen, stack.count, (x + ICON_SIZE * self.scale, y + ICON_SIZE * self.scale))

        # Рамка на пиксель шире ячейки с каждой стороны.
        screen.blit(self.get_sprite(SELECTED_SLOT), (
            slots_rect.x + (SLOT_STEP * selected - 1) * self.scale,
            slots_rect.y - self.scale
        ))

        name_offset = NAME_OFFSET

        if health is not None:
            self.render_hearts(screen, slots_rect, health, blink)

            if armor > 0:
                self.render_armor(screen, slots_rect, armor)
                name_offset += ARMOR_ROW

        if air is not None:
            self.render_bubbles(screen, slots_rect, air)

            # Название предмета поднимается над сердечками.
            name_offset += HEARTS_ABOVE_HOTBAR + 4

        if hotbar[selected] is not None:
            self.blit_text(
                screen,
                item_name(hotbar[selected].type),
                (center_x, slots_rect.y - name_offset * self.scale)
            )

    def heart_sprite(self, name):
        """Спрайт сердечка из ресурс-пака по имени файла (без .png) или None."""
        path = HEART_SPRITES + name + ".png"

        if os.path.exists(path):
            return pygame.image.load(path).convert_alpha()

        if os.path.exists(ICONS):
            atlas = pygame.image.load(ICONS).convert_alpha()
            x, y = ICON_HEARTS[name]

            return atlas.subsurface((x, y, HEART_SIZE, HEART_SIZE)).copy()

        return None

    def heart_from_pack(self, fill, blink):
        """Контур и заливка из ресурс-пака одним спрайтом, как их накладывает оригинал."""
        suffix = "_blinking" if blink else ""
        container = self.heart_sprite("container" + suffix)

        if container is None:
            return None

        heart = container.copy()

        if fill != 'empty':
            filled = self.heart_sprite(fill + suffix)

            if filled is None:
                return None

            heart.blit(filled, (0, 0))

        return heart

    def get_heart(self, fill, blink):
        """Сердечко: fill это 'full', 'half' или 'empty'. Рисуется один раз на масштаб."""
        key = ('heart', fill, blink)

        if key not in self.sprites:
            pack = self.heart_from_pack(fill, blink)

            if pack is not None:
                self.sprites[key] = pygame.transform.scale_by(pack, self.scale)
                return self.sprites[key]

            heart = pygame.Surface((HEART_SIZE, HEART_SIZE), pygame.SRCALPHA)

            def paint(mask, color, columns=HEART_SIZE):
                for row, line in enumerate(mask):
                    for column, char in enumerate(line[:columns]):
                        if char == '#':
                            heart.set_at((column, row), color)

            paint(HEART_FILL, HEART_EMPTY)

            if fill != 'empty':
                paint(HEART_FILL, HEART_RED, HEART_SIZE if fill == 'full' else 5)
                paint(HEART_SHINE, HEART_SHINE_COLOR)

            paint(HEART_OUTLINE, HEART_BLINK if blink else (0, 0, 0))

            self.sprites[key] = pygame.transform.scale_by(heart, self.scale)

        return self.sprites[key]

    def render_hearts(self, screen, slots_rect, health, blink):
        """Десять сердечек над левым краем хотбара. Одно сердечко это 2 единицы здоровья."""
        top = slots_rect.y - HEARTS_ABOVE_HOTBAR * self.scale

        # Когда здоровья мало, сердечки подрагивают.
        jiggle = random.Random(pygame.time.get_ticks() // JIGGLE_MS) if health <= LOW_HEALTH else None

        for index in range(10):
            left = health - index * 2
            fill = 'full' if left >= 2 else 'half' if left == 1 else 'empty'

            y = top

            if jiggle is not None:
                y += jiggle.randint(-1, 1) * self.scale

            screen.blit(self.get_heart(fill, blink), (slots_rect.x + index * HEART_STEP * self.scale, y))

    def get_armor_icon(self, kind):
        """Значок брони: 'empty', 'half' или 'full'. Без атласа рисуется квадратиком."""
        key = ('armor', kind)

        if key not in self.sprites:
            if os.path.exists(ICONS):
                x, y = ICON_ARMOR[kind]
                icon = pygame.image.load(ICONS).convert_alpha().subsurface((x, y, HEART_SIZE, HEART_SIZE)).copy()
            else:
                icon = pygame.Surface((HEART_SIZE, HEART_SIZE), pygame.SRCALPHA)
                pygame.draw.rect(icon, (200, 200, 210), (1, 1, 7, 7), 0 if kind == 'full' else 1)

            self.sprites[key] = pygame.transform.scale_by(icon, self.scale)

        return self.sprites[key]

    def render_armor(self, screen, slots_rect, points):
        """Десять значков брони над сердечками: каждый это 2 очка защиты."""
        top = slots_rect.y - (HEARTS_ABOVE_HOTBAR + ARMOR_ROW) * self.scale

        for index in range(10):
            left = points - index * 2
            kind = 'full' if left >= 2 else 'half' if left == 1 else 'empty'
            screen.blit(self.get_armor_icon(kind), (slots_rect.x + index * HEART_STEP * self.scale, top))

    def get_bubble(self, kind):
        """Пузырёк воздуха: 'full' или 'popping'. Без атласа рисуется кружком."""
        key = ('bubble', kind)

        if key not in self.sprites:
            if os.path.exists(ICONS):
                x, y = ICON_BUBBLES[kind]
                bubble = pygame.image.load(ICONS).convert_alpha().subsurface((x, y, HEART_SIZE, HEART_SIZE)).copy()
            else:
                bubble = pygame.Surface((HEART_SIZE, HEART_SIZE), pygame.SRCALPHA)
                pygame.draw.circle(bubble, BUBBLE_COLOR, (4, 4), 4 if kind == 'full' else 3, 1)

            self.sprites[key] = pygame.transform.scale_by(bubble, self.scale)

        return self.sprites[key]

    def render_bubbles(self, screen, slots_rect, air):
        """Десять пузырьков над правым краем хотбара, тают справа налево, как в оригинале."""
        top = slots_rect.y - HEARTS_ABOVE_HOTBAR * self.scale
        right = slots_rect.right - HEART_SIZE * self.scale

        full = math.ceil(air * 10 - BUBBLE_POP)
        popping = math.ceil(air * 10) - full

        for index in range(full + popping):
            sprite = self.get_bubble('full' if index < full else 'popping')
            screen.blit(sprite, (right - index * HEART_STEP * self.scale, top))

    def tint(self, screen, color, alpha):
        """Заливает весь экран полупрозрачным цветом, например красным при уроне."""
        key = ('tint', screen.get_size(), color)

        # Один слой на цвет: прозрачность меняется у него, а не создаётся новый.
        if key not in self.overlays:
            overlay = pygame.Surface(screen.get_size())
            overlay.fill(color)
            self.overlays[key] = overlay

        overlay = self.overlays[key]
        overlay.set_alpha(alpha)
        screen.blit(overlay, (0, 0))

    def button_at(self, position):
        for action, rect in self.buttons.items():
            if rect.collidepoint(position):
                return action

        return None

    def slider_at(self, position):
        for name, rect in self.sliders.items():
            if rect.collidepoint(position):
                return name

        return None

    def darken(self, screen, alpha):
        self.shade(screen, (0, 0) + screen.get_size(), alpha, pixels=True)

    def shade(self, screen, rect, alpha, pixels=False, light=False):
        """Затемняет прямоугольник, а с light=True подсвечивает белым.

        Полупрозрачные поверхности кэшируются по размеру.
        """
        rect = pygame.Rect(rect) if pixels else self.to_pixels(rect)
        key = (rect.size, alpha, light)

        if key not in self.overlays:
            overlay = pygame.Surface(rect.size, pygame.SRCALPHA)
            overlay.fill((255, 255, 255, alpha) if light else (0, 0, 0, alpha))
            self.overlays[key] = overlay

        screen.blit(self.overlays[key], rect)

    def fill(self, screen, rect, color):
        screen.fill(color, self.to_pixels(rect))

    def render_text(self, text, color=WHITE, shadow=True):
        """Текст с тенью на единицу правее и ниже, как в пиксельных интерфейсах."""
        front = self.font.render(text, False, color)

        if not shadow:
            return front

        shadow_color = tuple(channel // 4 for channel in color)

        shadow = self.font.render(text, False, shadow_color)

        surface = pygame.Surface(
            (front.get_width() + self.scale, front.get_height() + self.scale),
            pygame.SRCALPHA
        )

        surface.blit(shadow, (self.scale, self.scale))
        surface.blit(front, (0, 0))

        return surface

    def blit_text(self, screen, text, position, color=WHITE, anchor='center', shadow=True):
        surface = self.render_text(text, color, shadow)
        rect = surface.get_rect(**{anchor: position})

        # Тень не должна сдвигать текст: выравниваем по самим буквам.
        if anchor in ('center', 'midtop', 'midbottom'):
            rect.x += self.scale // 2

        screen.blit(surface, rect)

    def draw_text(self, screen, text, position, color=WHITE, anchor='center', shadow=True):
        x, y = position

        self.blit_text(screen, text, (x * self.scale, y * self.scale), color, anchor, shadow)

    def draw_panel(self, screen, x, y, width, height):
        """Окно с чёрным контуром, светлым краем сверху-слева и тёмным снизу-справа."""
        self.fill(screen, (x + 1, y, width - 2, height), (0, 0, 0))
        self.fill(screen, (x, y + 1, width, height - 2), (0, 0, 0))
        self.fill(screen, (x + 1, y + 1, width - 2, height - 2), PANEL_LIGHT)
        self.fill(screen, (x + 3, y + 3, width - 4, height - 4), PANEL_DARK)
        self.fill(screen, (x + 3, y + 3, width - 6, height - 6), PANEL)

    def draw_slot(self, screen, x, y, stack, hovered=False, size=18, show_count=True):
        """Ячейка: тёмный край сверху-слева, светлый снизу-справа, предмет по центру.

        Обычная ячейка 18x18, у результата крафта и печки рамка 26x26.
        """
        self.fill(screen, (x, y, size, size), PANEL_LIGHT)
        self.fill(screen, (x, y, size - 1, size - 1), SLOT_DARK)
        self.fill(screen, (x + 1, y + 1, size - 2, size - 2), SLOT)

        item_x = x + (size - ICON_SIZE) // 2
        item_y = y + (size - ICON_SIZE) // 2

        if stack is not None:
            self.draw_stack(screen, stack, item_x, item_y, show_count)

        if hovered:
            self.shade(screen, (item_x, item_y, ICON_SIZE, ICON_SIZE), 128, light=True)

    def draw_stack(self, screen, stack, x, y, show_count=True):
        """Иконка в точке (x, y) в единицах и количество в правом нижнем углу."""
        screen.blit(self.get_block_icon(stack.type), (x * self.scale, y * self.scale))
        self.blit_durability(screen, stack, (x * self.scale, y * self.scale))

        if show_count:
            self.blit_count(screen, stack.count, ((x + ICON_SIZE) * self.scale, (y + ICON_SIZE) * self.scale))

    def blit_durability(self, screen, stack, corner):
        """Полоска прочности под иконкой поношенного инструмента. corner: левый верхний угол иконки в пикселях.

        Как в оригинале: чёрная подложка 13x2, сверху цветная полоска в пиксель
        высотой, она укорачивается и краснеет по мере износа.
        """
        uses = max_uses(stack.type)

        if uses is None or stack.damage <= 0:
            return

        fraction = max(0.0, (uses - stack.damage) / uses)

        red, green, blue = colorsys.hsv_to_rgb(fraction / 3, 1.0, 1.0)
        color = (round(red * 255), round(green * 255), round(blue * 255))

        unit = self.scale
        x, y = corner[0] + 2 * unit, corner[1] + 13 * unit

        screen.fill((0, 0, 0), (x, y, DURABILITY_WIDTH * unit, 2 * unit))
        screen.fill(color, (x, y, round(DURABILITY_WIDTH * fraction) * unit, unit))

    def blit_count(self, screen, count, corner):
        """Количество поверх иконки. corner: правый нижний угол иконки в пикселях."""
        if count > 1:
            x, y = corner
            self.blit_text(screen, str(count), (x + self.scale, y + self.scale), anchor='bottomright')

    def draw_mask(self, screen, mask, x, y, color, from_row=0):
        """Пиксельная картинка из строк: '#' закрашивается. Строки выше from_row пропускаются."""
        for row, line in enumerate(mask):
            if row < from_row:
                continue

            for column, char in enumerate(line):
                if char == '#':
                    self.fill(screen, (x + column, y + row, 1, 1), color)

    def draw_arrow(self, screen, x, y, progress=0.0):
        """Стрелка 22x15 между сеткой и результатом. progress от 0 до 1 закрашивает её белым."""
        self.draw_mask(screen, ARROW, x, y, ARROW_EMPTY)

        if progress > 0:
            clip = screen.get_clip()
            filled = self.to_pixels((x, y, 22, 15))
            filled.width = round(filled.width * min(1.0, progress))

            screen.set_clip(filled)
            self.draw_mask(screen, ARROW, x, y, WHITE)
            screen.set_clip(clip)

    def draw_flame(self, screen, x, y, fraction):
        """Огонь печки 14x14: снизу вверх закрашивается доля оставшегося топлива."""
        self.draw_mask(screen, FLAME, x, y, ARROW_EMPTY)

        if fraction > 0:
            rows = len(FLAME)
            first = rows - math.ceil(rows * min(1.0, fraction))

            self.draw_mask(screen, FLAME, x, y, FLAME_OUTER, first)
            self.draw_mask(screen, FLAME_CORE, x, y, FLAME_INNER, first)

    def draw_tooltip(self, screen, text, position):
        """Подсказка с названием у курсора. position в пикселях экрана."""
        unit = self.scale
        text_width = self.font.size(text)[0] // unit

        x = position[0] // unit + 12
        y = position[1] // unit - 12
        width, height = self.units(screen)

        # Не даём подсказке уйти за правый край экрана.
        x = min(x, width - text_width - 4)

        self.fill(screen, (x - 3, y - 4, text_width + 6, 16), TOOLTIP)
        self.fill(screen, (x - 4, y - 3, text_width + 8, 14), TOOLTIP)
        self.fill(screen, (x - 3, y - 3, text_width + 6, 1), TOOLTIP_BORDER)
        self.fill(screen, (x - 3, y + 10, text_width + 6, 1), TOOLTIP_BORDER)
        self.fill(screen, (x - 3, y - 3, 1, 14), TOOLTIP_BORDER)
        self.fill(screen, (x + text_width + 2, y - 3, 1, 14), TOOLTIP_BORDER)

        self.draw_text(screen, text, (x, y - 1), anchor='topleft')

    def fit_text(self, text, width):
        """Обрезает текст с многоточием, чтобы он поместился в width единиц."""
        limit = width * self.scale

        if self.font.size(text)[0] <= limit:
            return text

        while text and self.font.size(text + "...")[0] > limit:
            text = text[:-1]

        return text + "..."

    def draw_splash(self, screen, text, position):
        """Жёлтая надпись под углом, которая слегка пульсирует."""
        phase = pygame.time.get_ticks() % 1000 / 1000
        size = 1.8 - abs(math.sin(phase * 2 * math.pi)) * 0.1

        text_width = self.font.size(text)[0] / self.scale
        size *= 100 / (text_width + 32)

        surface = pygame.transform.scale_by(self.render_text(text, YELLOW), size)
        surface = pygame.transform.rotate(surface, SPLASH_ANGLE)

        x, y = position
        screen.blit(surface, surface.get_rect(center=(x * self.scale, y * self.scale)))

    def get_bar(self, bar, width):
        """Полоса нужной ширины: края без растяжения, чтобы сохранить рамку."""
        if width == BAR_WIDTH:
            return self.get_sprite(bar)

        key = ('bar', bar, width)

        if key not in self.sprites:
            x, y, bar_width, height = bar
            half = width // 2

            sprite = pygame.Surface((width, height), pygame.SRCALPHA)
            sprite.blit(self.gui_texture, (0, 0), (x, y, half, height))
            sprite.blit(self.gui_texture, (half, 0), (x + bar_width - (width - half), y, width - half, height))

            self.sprites[key] = pygame.transform.scale_by(sprite, self.scale)

        return self.sprites[key]

    def draw_button(self, screen, action, text, x, y, width=BAR_WIDTH, enabled=True, selected=False):
        rect = self.to_pixels((x, y, width, BAR_HEIGHT))
        hovered = enabled and rect.collidepoint(pygame.mouse.get_pos())

        if not enabled:
            bar, color = DISABLED_BAR, GRAY
        elif hovered or selected:
            bar, color = HOVER_BAR, HOVER_TEXT
        else:
            bar, color = BUTTON_BAR, WHITE

        screen.blit(self.get_bar(bar, width), rect)

        self.blit_text(screen, self.fit_text(text, width - 6), rect.center, color)

        if enabled:
            self.buttons[action] = rect

    def draw_slider(self, screen, name, text, x, y, width, fraction, active=False):
        rect = self.to_pixels((x, y, width, BAR_HEIGHT))
        hovered = active or rect.collidepoint(pygame.mouse.get_pos())

        handle = self.get_bar(HOVER_BAR if hovered else BUTTON_BAR, HANDLE_WIDTH)
        handle_x = rect.x + round((rect.width - handle.get_width()) * fraction)

        screen.blit(self.get_bar(DISABLED_BAR, width), rect)
        screen.blit(handle, (handle_x, rect.y))

        self.blit_text(screen, self.fit_text(text, width - 6), rect.center, HOVER_TEXT if hovered else WHITE)

        self.sliders[name] = rect

    def slider_fraction(self, name, mouse_x):
        """Положение мыши на ползунке от 0 до 1 с учётом ширины ручки."""
        rect = self.sliders[name]
        handle_width = HANDLE_WIDTH * self.scale
        position = (mouse_x - rect.x - handle_width / 2) / (rect.width - handle_width)

        return max(0.0, min(1.0, position))
