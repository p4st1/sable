"""Время суток: день и ночь, солнце, луна и звёзды.

Время мира идёт в тиках, как в оригинале: 20 тиков в секунду, сутки 24000 тиков
(20 минут). Тик 0 это восход, 6000 полдень, 12000 закат, 18000 полночь.
Каждые сутки луна меняет фазу, всего фаз восемь.

Отсюда только числа и цвета. Небо и светила рисует renderer, а затемнение
блоков ночью делает растеризатор: у мешей есть яркость днём и ночью.
"""
import math
from typing import NamedTuple

TICKS_PER_SECOND = 20
DAY_LENGTH = 24000
MOON_PHASES = 8

# Новый мир начинается с восхода, как в оригинале. За главным меню полдень.
START_TIME = 0
TITLE_TIME = 6000

# Дневное небо: насыщенный голубой в зените и светлый у горизонта.
# Туман того же цвета, что горизонт, поэтому дальние блоки растворяются в небе.
SKY_COLOR = (120, 167, 255)
FOG_COLOR = (192, 216, 255)


class Sky(NamedTuple):
    """Что нужно для кадра в этот момент суток."""
    # Угол светил: 0 полдень, 0.25 закат, 0.5 полночь, 0.75 восход (доли оборота).
    angle: float
    # Доля ночи для блоков: 0 днём, 1 глубокой ночью.
    night: float
    sky_color: tuple
    fog_color: tuple
    # Зарево на восходе и закате: цвет и сила у горизонта со стороны солнца.
    glow_color: tuple
    glow: float
    stars: float
    moon_phase: int


def celestial_angle(time):
    """Угол светил с небольшим ускорением днём, как в оригинале."""
    part = (time % DAY_LENGTH) / DAY_LENGTH - 0.25

    if part < 0:
        part += 1

    eased = 1 - (math.cos(part * math.pi) + 1) / 2

    return part + (eased - part) / 3


def daylight(angle):
    """Сила дневного света от 0 ночью до 1 днём."""
    return min(1.0, max(0.0, math.cos(angle * math.tau) * 2 + 0.5))


def star_brightness(angle):
    level = min(1.0, max(0.0, 1 - (math.cos(angle * math.tau) * 2 + 0.75)))

    return level * level * 0.5


def sunrise_glow(angle):
    """Цвет и сила зарева, когда солнце у горизонта."""
    height = math.cos(angle * math.tau)

    if not -0.4 <= height <= 0.4:
        return (0, 0, 0), 0.0

    part = height / 0.4 * 0.5 + 0.5
    strength = 1 - (1 - math.sin(part * math.pi)) * 0.99

    color = (part * 0.3 + 0.7, part * part * 0.7 + 0.2, 0.2)

    return tuple(int(channel * 255) for channel in color), strength * strength


def sun_direction(angle):
    """Куда смотреть на солнце, единичный вектор. Ось Y вниз, восход на востоке (+x)."""
    turn = -angle * math.tau

    return (math.sin(turn), -math.cos(turn), 0.0)


def sky_at(time):
    angle = celestial_angle(time)
    light = daylight(angle)

    sky = tuple(int(channel * light) for channel in SKY_COLOR)
    fog = (
        int(FOG_COLOR[0] * (light * 0.94 + 0.06)),
        int(FOG_COLOR[1] * (light * 0.94 + 0.06)),
        int(FOG_COLOR[2] * (light * 0.91 + 0.09)),
    )
    glow_color, glow = sunrise_glow(angle)

    return Sky(
        angle=angle,
        night=1 - light,
        sky_color=sky,
        fog_color=fog,
        glow_color=glow_color,
        glow=glow,
        stars=star_brightness(angle),
        moon_phase=int(time // DAY_LENGTH) % MOON_PHASES,
    )


def clock_text(time):
    """Время как на часах: тик 0 это 6:00."""
    minutes = int((time % DAY_LENGTH) / DAY_LENGTH * 24 * 60 + 6 * 60) % (24 * 60)

    return f"{minutes // 60:02d}:{minutes % 60:02d}"
