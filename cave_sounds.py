"""Страшные звуки пещер, синтезированные в коде.

В оригинале в темноте под землёй иногда раздаются жуткие звуки (ambient.cave).
В нашем ресурс-паке этих файлов нет, поэтому звуки собираются здесь из шума и
синусоид: далёкий гул, низкий стон, тоскливый ветер в тоннеле, капли с эхом
и скрежет. Если файлы пещерных звуков положить в пак (событие ambient.cave),
играть будут они.
"""
import numpy as np
import pygame

SECONDS = 4.0


def envelope(count, attack, release):
    """Плавное нарастание и затухание: доли длины на вход и выход."""
    shape = np.ones(count)
    rise = max(1, int(count * attack))
    fall = max(1, int(count * release))
    shape[:rise] = np.linspace(0, 1, rise) ** 2
    shape[-fall:] = np.linspace(1, 0, fall) ** 2

    return shape


def lowpass(signal, strength):
    """Фильтр низких частот, как одно звено с долей strength, но сразу через спектр.

    Пропускание по частоте то же, что у звена value += (x - value) * strength.
    """
    spectrum = np.fft.rfft(signal)
    frequency = np.fft.rfftfreq(len(signal))
    response = strength / (1 - (1 - strength) * np.exp(-2j * np.pi * frequency))

    return np.fft.irfft(spectrum * response, len(signal))


def echo(signal, rate, delays=(0.23, 0.41, 0.67), fade=0.45):
    """Эхо пещеры: несколько отражений, каждое тише."""
    out = signal.copy()
    level = 1.0

    for delay in delays:
        level *= fade
        shift = int(delay * rate)
        out[shift:] += signal[:-shift] * level if shift < len(signal) else 0

    return out


def rumble(rate, rng):
    """Далёкий гул: низкий бурый шум, медленно нарастает и уходит."""
    count = int(rate * SECONDS)
    noise = np.cumsum(rng.normal(0, 1, count))
    noise -= lowpass(noise, 0.001)
    noise = lowpass(noise, 0.02)

    return noise / (np.abs(noise).max() + 1e-9) * envelope(count, 0.4, 0.5)


def moan(rate, rng):
    """Низкий стон: тон медленно сползает вниз и дрожит, с призвуками и эхом."""
    count = int(rate * SECONDS * 0.8)
    t = np.arange(count) / rate
    start, end = rng.uniform(70, 110), rng.uniform(45, 65)
    pitch = start + (end - start) * (t / t[-1]) + 3 * np.sin(t * 2 * np.pi * rng.uniform(4, 6))
    phase = np.cumsum(pitch) / rate * 2 * np.pi
    tone = np.sin(phase) + 0.5 * np.sin(phase * 2.01) + 0.25 * np.sin(phase * 3.02)
    tone *= envelope(count, 0.3, 0.6)

    return echo(tone / 1.75, rate)


def wind(rate, rng):
    """Ветер в тоннеле: шум, у которого то поднимается, то опускается высота."""
    count = int(rate * SECONDS)
    noise = rng.normal(0, 1, count)
    t = np.arange(count) / rate
    # Высота ветра качается: смешиваем глухой и звонкий шум медленной волной.
    sweep = 0.5 + 0.5 * np.sin(t * 2 * np.pi * rng.uniform(0.2, 0.4))
    out = lowpass(noise, 0.015) * (1 - sweep) + lowpass(noise, 0.045) * sweep
    out -= lowpass(out, 0.002)

    return out / (np.abs(out).max() + 1e-9) * envelope(count, 0.35, 0.45)


def drips(rate, rng):
    """Капли где-то в темноте: короткие звонкие щелчки с долгим эхом."""
    count = int(rate * SECONDS)
    out = np.zeros(count)

    for _ in range(rng.integers(3, 6)):
        start = int(rng.uniform(0, SECONDS * 0.6) * rate)
        length = int(0.12 * rate)
        t = np.arange(length) / rate
        pitch = rng.uniform(900, 1500) * np.exp(-t * 6)
        drop = np.sin(np.cumsum(pitch) / rate * 2 * np.pi) * np.exp(-t * 35)
        out[start:start + length] += drop[:max(0, min(length, count - start))]

    return echo(out * 0.6, rate, delays=(0.31, 0.62, 0.93, 1.24), fade=0.55)


def scrape(rate, rng):
    """Скрежет камня: рваные толчки низкого шума."""
    count = int(rate * SECONDS * 0.7)
    t = np.arange(count) / rate
    grit = lowpass(rng.normal(0, 1, count), 0.08)
    pulses = (np.sin(t * 2 * np.pi * rng.uniform(5, 9)) > 0.3).astype(float)
    pulses = lowpass(pulses, 0.01)
    out = grit * pulses * envelope(count, 0.2, 0.5)

    return echo(out / (np.abs(out).max() + 1e-9), rate)


KINDS = (rumble, moan, wind, drips, scrape)


def make_sounds(seed=7):
    """Звуки пещер для текущих настроек микшера. Пустой список, если микшера нет."""
    settings = pygame.mixer.get_init()

    if settings is None:
        return []

    rate, size, channels = settings
    rng = np.random.default_rng(seed)
    sounds = []

    for kind in KINDS:
        wave = kind(rate, rng)
        wave = (np.clip(wave, -1, 1) * 0.8 * 32767).astype(np.int16)

        if channels > 1:
            wave = np.repeat(wave[:, None], channels, axis=1)

        if abs(size) != 16:
            # Микшер в другом формате: такие звуки не делаем, чтобы не испортить.
            return []

        sounds.append(pygame.sndarray.make_sound(np.ascontiguousarray(wave)))

    return sounds
