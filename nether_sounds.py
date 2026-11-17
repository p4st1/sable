"""Звуки ада, синтезированные в коде: портал, гаст, свинозомби и ифрит.

В нашем ресурс-паке есть описания этих событий (sounds.json), но нет самих
файлов. Пока их нет, звучат эти: гул и вихрь портала, жалобный плач и визг
гаста, хрюканье свинозомби, дыхание ифрита и хлопок огненного шара. Если
файлы положить в пак, Sounds возьмёт их, а не эти.
"""
import numpy as np
import pygame

from cave_sounds import echo, envelope, lowpass


def normalized(wave):
    return wave / (np.abs(wave).max() + 1e-9)


def tone(rate, seconds, pitch, harmonics=(1.0, 0.5, 0.25)):
    """Тон с плавающей высотой: pitch(t) в герцах, призвуки на кратных частотах."""
    count = int(rate * seconds)
    t = np.arange(count) / rate
    phase = np.cumsum(pitch(t)) / rate * 2 * np.pi
    wave = sum(level * np.sin(phase * (index + 1) * 1.003 ** index) for index, level in enumerate(harmonics))

    return wave, t


# Портал.

def portal_hum(rate, rng):
    """Гул портала: низкое дрожащее жужжание, то громче, то тише."""
    count = int(rate * 3.0)
    t = np.arange(count) / rate
    noise = lowpass(rng.normal(0, 1, count), 0.03)
    wobble = 0.6 + 0.4 * np.sin(t * 2 * np.pi * rng.uniform(1.5, 2.5))
    drone, _ = tone(rate, 3.0, lambda t: 55 + 6 * np.sin(t * 2 * np.pi * 3.1), (1.0, 0.6, 0.3, 0.2))

    return normalized(noise * 2 + drone * 0.6) * wobble * envelope(count, 0.25, 0.35) * 0.7


def portal_whoosh(rate, rng, seconds, rising):
    """Вихрь: шум, высота которого плавно растёт (вход) или падает (переход)."""
    count = int(rate * seconds)
    t = np.arange(count) / rate
    noise = rng.normal(0, 1, count)
    share = t / t[-1]
    sweep = share if rising else 1 - share
    out = lowpass(noise, 0.01) * (1 - sweep) + lowpass(noise, 0.08) * sweep
    swirl = 0.7 + 0.3 * np.sin(t * 2 * np.pi * (3 + 5 * sweep))
    drone, _ = tone(rate, seconds, lambda t: 70 + 90 * (t / seconds if rising else 1 - t / seconds), (1.0, 0.4))

    return normalized(normalized(out) * swirl + drone * 0.25) * envelope(count, 0.3 if rising else 0.05, 0.4)


# Гаст.

def ghast_wail(rate, rng, seconds=1.6, high=None):
    """Плач гаста: высокий жалобный тон с дрожью, сползающий вниз, с эхом."""
    start = high or rng.uniform(560, 720)
    end = start * rng.uniform(0.55, 0.7)
    vibrato = rng.uniform(5, 7)
    wave, t = tone(
        rate, seconds,
        lambda t: start + (end - start) * (t / seconds) ** 0.8 + 18 * np.sin(t * 2 * np.pi * vibrato),
        (1.0, 0.35, 0.15),
    )
    breath = lowpass(rng.normal(0, 1, len(t)), 0.2) * 0.15

    return echo(normalized(wave + breath) * envelope(len(t), 0.15, 0.5), rate, delays=(0.18, 0.37), fade=0.35)


def ghast_scream(rate, rng):
    """Визг от удара: короткий, резкий, с хрипом."""
    wave, t = tone(rate, 0.6, lambda t: 900 + 300 * np.sin(t * 2 * np.pi * 9) - 500 * t, (1.0, 0.6, 0.4, 0.2))
    grit = lowpass(rng.normal(0, 1, len(t)), 0.35) * 0.4

    return normalized(wave + grit) * envelope(len(t), 0.03, 0.5)


def ghast_charge(rate, rng):
    """Предупреждение перед выстрелом: визгливый подъём."""
    wave, t = tone(rate, 0.7, lambda t: 400 + 900 * (t / 0.7) ** 1.5, (1.0, 0.5, 0.3))

    return normalized(wave) * envelope(len(t), 0.1, 0.25)


def fireball_shot(rate, rng, size=1.0):
    """Выстрел огненным шаром: глухой хлопок и шипящий шлейф."""
    count = int(rate * 0.9 * size)
    t = np.arange(count) / rate
    thump = np.sin(np.cumsum(120 * np.exp(-t * 8) + 40) / rate * 2 * np.pi) * np.exp(-t * 10)
    hiss = lowpass(rng.normal(0, 1, count), 0.12) * np.exp(-t * 4) * 0.6

    return normalized(thump + hiss) * envelope(count, 0.01, 0.4)


# Свинозомби.

def grunt(rate, rng, pitch=None, angry=False):
    """Хрюканье: гнусавый низкий тон в рваных толчках."""
    seconds = rng.uniform(0.35, 0.6) * (1.4 if angry else 1)
    base = pitch or rng.uniform(95, 130) * (1.25 if angry else 1)
    wave, t = tone(rate, seconds, lambda t: base * (1 + 0.15 * np.sin(t * 2 * np.pi * 3)), (1.0, 0.8, 0.7, 0.5, 0.4, 0.3))
    pulses = lowpass((np.sin(t * 2 * np.pi * rng.uniform(16, 24)) > -0.2).astype(float), 0.02)
    snort = lowpass(rng.normal(0, 1, len(t)), 0.15) * (0.6 if angry else 0.3)

    return normalized(lowpass(wave * pulses + snort, 0.25)) * envelope(len(t), 0.05, 0.35)


def squeal(rate, rng, falling=False):
    """Визг свинозомби от удара или при смерти."""
    seconds = 0.9 if falling else 0.45
    start = rng.uniform(700, 900)
    wave, t = tone(rate, seconds, lambda t: start * (1 - 0.5 * t / seconds if falling else 1 + 0.2 * np.sin(t * 2 * np.pi * 7)), (1.0, 0.7, 0.5))
    grit = lowpass(rng.normal(0, 1, len(t)), 0.3) * 0.3

    return normalized(wave + grit) * envelope(len(t), 0.03, 0.5)


# Ифрит.

def breath(rate, rng):
    """Дыхание ифрита: шипящий вдох и выдох с треском огня."""
    count = int(rate * 1.4)
    t = np.arange(count) / rate
    noise = lowpass(rng.normal(0, 1, count), 0.06)
    shape = np.sin(np.pi * t / t[-1]) ** 2
    crackle = (rng.random(count) > 0.997) * rng.normal(0, 3, count)

    return normalized(noise * shape + lowpass(crackle, 0.5) * 0.4) * 0.8


def crackle_hurt(rate, rng):
    count = int(rate * 0.5)
    pops = lowpass((rng.random(count) > 0.99) * rng.normal(0, 4, count), 0.4)
    wave, _ = tone(rate, 0.5, lambda t: 300 - 150 * t, (1.0, 0.5))

    return normalized(pops + wave * 0.4) * envelope(count, 0.02, 0.5)


# Событие -> как сделать варианты звука.
EVENTS = {
    "block.portal.ambient": lambda rate, rng: [portal_hum(rate, rng) for _ in range(2)],
    "block.portal.trigger": lambda rate, rng: [portal_whoosh(rate, rng, 3.5, rising=True)],
    "block.portal.travel": lambda rate, rng: [portal_whoosh(rate, rng, 3.0, rising=False)],
    "entity.ghast.ambient": lambda rate, rng: [ghast_wail(rate, rng) for _ in range(4)],
    "entity.ghast.hurt": lambda rate, rng: [ghast_scream(rate, rng) for _ in range(3)],
    "entity.ghast.death": lambda rate, rng: [ghast_wail(rate, rng, 2.4, high=820)],
    "entity.ghast.warn": lambda rate, rng: [ghast_charge(rate, rng)],
    "entity.ghast.shoot": lambda rate, rng: [fireball_shot(rate, rng)],
    "entity.blaze.shoot": lambda rate, rng: [fireball_shot(rate, rng, 0.6)],
    "entity.blaze.ambient": lambda rate, rng: [breath(rate, rng) for _ in range(3)],
    "entity.blaze.hurt": lambda rate, rng: [crackle_hurt(rate, rng) for _ in range(2)],
    "entity.blaze.death": lambda rate, rng: [crackle_hurt(rate, rng)],
    "entity.zombie_pigman.ambient": lambda rate, rng: [grunt(rate, rng) for _ in range(4)],
    "entity.zombie_pigman.angry": lambda rate, rng: [grunt(rate, rng, angry=True) for _ in range(3)],
    "entity.zombie_pigman.hurt": lambda rate, rng: [squeal(rate, rng) for _ in range(2)],
    "entity.zombie_pigman.death": lambda rate, rng: [squeal(rate, rng, falling=True)],
}


def make(event, seed=11):
    """Варианты звука события для текущего микшера. Пустой список, если сделать нельзя."""
    settings = pygame.mixer.get_init()

    if settings is None or event not in EVENTS:
        return []

    rate, size, channels = settings

    if abs(size) != 16:
        return []

    rng = np.random.default_rng(seed + sum(map(ord, event)))
    sounds = []

    for wave in EVENTS[event](rate, rng):
        wave = (np.clip(wave, -1, 1) * 0.8 * 32767).astype(np.int16)

        if channels > 1:
            wave = np.repeat(wave[:, None], channels, axis=1)

        sounds.append(pygame.sndarray.make_sound(np.ascontiguousarray(wave)))

    return sounds
