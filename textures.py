"""Текстуры блоков, которые собираются в коде, а не лежат готовыми файлами.

Ключ такой текстуры начинается с "generated:" и используется везде вместо пути:
в мешах чанков, в иконках и в рендерере. load_surface открывает и то, и другое.
"""
import numpy as np
import pygame

BLOCK_TEXTURES = 'assets/minecraft/textures/block/'
GENERATED = "generated:"

# Листва в файле серая: в оригинале её красят цветом биома. У берёзы и ели
# цвет свой и от биома не зависит.
FOLIAGE = (72, 181, 24)
BIRCH_FOLIAGE = (128, 167, 85)
SPRUCE_FOLIAGE = (97, 153, 97)


def tinted(path, color):
    image = pygame.image.load(path)
    image = image.convert_alpha() if pygame.display.get_surface() else image

    surface = image.copy()
    surface.fill(color + (255,), special_flags=pygame.BLEND_RGBA_MULT)

    return surface


def chest_texture(part):
    """Сундук из досок: тёмная окантовка, шов крышки и защёлка спереди."""
    planks = pygame.image.load(BLOCK_TEXTURES + "oak_planks.png")
    pixels = pygame.surfarray.array3d(planks).astype(np.float32) * 0.85

    edge = np.zeros((16, 16), dtype=bool)
    edge[0, :] = edge[15, :] = edge[:, 0] = edge[:, 15] = True

    if part in ("front", "side"):
        # Шов между крышкой и коробом.
        edge[:, 5] = True

    pixels[edge] *= 0.55

    if part == "front":
        pixels[7:9, 4:8] = (190, 190, 200)
        pixels[7:9, 7] = (120, 120, 130)

    surface = pygame.Surface((16, 16))
    pygame.surfarray.blit_array(surface, pixels.clip(0, 255).astype(np.uint8))

    return surface


# Оригинал умножает трещины на цвет блока: тёмные пиксели затемняют его, а светлые
# почти ничего не меняют. Смешивания у нас нет, поэтому оставляем только тёмные
# пиксели и рисуем их почти чёрными, остальное прозрачно.
CRACK_COLOR = (32, 32, 32)
CRACK_DARK_LIMIT = 128


def crack_texture(stage):
    image = pygame.image.load(BLOCK_TEXTURES + f"destroy_stage_{stage}.png")

    brightness = pygame.surfarray.array3d(image).mean(axis=2)
    alpha = pygame.surfarray.array_alpha(image)
    dark = (alpha >= 128) & (brightness < CRACK_DARK_LIMIT)

    surface = pygame.Surface(image.get_size(), pygame.SRCALPHA)
    pixels = pygame.surfarray.pixels3d(surface)
    pixels_alpha = pygame.surfarray.pixels_alpha(surface)

    pixels[dark] = CRACK_COLOR
    pixels_alpha[:] = 0
    pixels_alpha[dark] = 255

    del pixels, pixels_alpha

    return surface


WATER_STILL = BLOCK_TEXTURES + "water_still.png"

# Вода в ресурс-паке тёмно-синяя с фиолетовым: множители сдвигают её к голубому.
WATER_TINT = (1.6, 1.9, 1.05)


def water_frames():
    """Кадры анимации воды: файл это столбец квадратных кадров друг под другом."""
    image = pygame.image.load(WATER_STILL)
    size = image.get_width()
    count = max(1, image.get_height() // size)

    pixels = pygame.surfarray.array3d(image).astype(np.float32) * np.array(WATER_TINT, dtype=np.float32)
    tinted = pygame.Surface(image.get_size())
    pygame.surfarray.blit_array(tinted, pixels.clip(0, 255).astype(np.uint8))

    return [tinted.subsurface((0, index * size, size, size)).copy() for index in range(count)]


GENERATORS = {
    GENERATED + "water": lambda: water_frames()[0],
    GENERATED + "oak_leaves": lambda: tinted(BLOCK_TEXTURES + "oak_leaves.png", FOLIAGE),
    GENERATED + "birch_leaves": lambda: tinted(BLOCK_TEXTURES + "birch_leaves.png", BIRCH_FOLIAGE),
    GENERATED + "spruce_leaves": lambda: tinted(BLOCK_TEXTURES + "spruce_leaves.png", SPRUCE_FOLIAGE),
    GENERATED + "chest_front": lambda: chest_texture("front"),
    GENERATED + "chest_side": lambda: chest_texture("side"),
    GENERATED + "chest_top": lambda: chest_texture("top"),
}

for _stage in range(10):
    GENERATORS[GENERATED + f"destroy_stage_{_stage}"] = lambda stage=_stage: crack_texture(stage)

_cache = {}


def texture_path(name):
    """Полный путь блока или ключ созданной в коде текстуры."""
    return name if name.startswith(GENERATED) else BLOCK_TEXTURES + name


def load_surface(path):
    """Поверхность текстуры по пути или ключу generated:. Кэшируется."""
    if path not in _cache:
        if path.startswith(GENERATED):
            _cache[path] = GENERATORS[path]()
        else:
            _cache[path] = pygame.image.load(path)

    return _cache[path]
