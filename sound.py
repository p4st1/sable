"""Звуки по событиям из assets/minecraft/sounds.json, как их описывает ресурс-пак.

Событие (например block.stone.break) ссылается на несколько файлов, и каждый раз
играет случайный из них. Звук в мире тише с расстоянием и смещается влево или
вправо в зависимости от того, где он относительно взгляда.
Если звуковое устройство недоступно, всё молча отключается.
"""
import json
import math
import os
import random

import pygame

SOUNDS_JSON = "assets/minecraft/sounds.json"
SOUNDS_DIR = "assets/minecraft/sounds/"

CHANNELS = 24
# Дальше этого расстояния в блоках звук не слышен.
HEARING_DISTANCE = 16

# Чем звучит блок: материал выбирает события block.<материал>.break/place/step.
MATERIALS = {
    "grass": "grass",
    "oak_leaves": "grass",
    "dirt": "gravel",
    "sand": "sand",
    "glass": "glass",
    "oak_planks": "wood",
    "oak_log": "wood",
    "crafting_table": "wood",
    "chest": "wood",
    "oak_door": "wood",
    "spruce_door": "wood",
    "netherrack": "netherrack",
    "snowy_grass": "grass",
    "birch_leaves": "grass",
    "spruce_leaves": "grass",
    "gravel": "gravel",
    "clay": "gravel",
    "snow": "snow",
    "cactus": "wool",
    "birch_log": "wood",
    "birch_planks": "wood",
    "spruce_log": "wood",
    "spruce_planks": "wood",
    "torch": "wood",
    "glowstone": "glass",
    "white_wool": "wool",
    "bed": "wool",
    "rose": "grass",
    "dandelion": "grass",
    "oak_sapling": "grass",
    "birch_sapling": "grass",
    "spruce_sapling": "grass",
}
DEFAULT_MATERIAL = "stone"

# Если у события нет ни одного файла в assets, берём замену: другое событие
# или файлы напрямую (путь внутри sounds без .ogg).
FALLBACKS = {
    "ui.button.click": ["random/clickclassic"],
    "block.glass.break": "block.stone.break",
    "block.furnace.fire_crackle": ["fire/fire"],
    "entity.player.death": "entity.player.hurt",
    # В старом наборе звуков нет отдельных звуков ведра и плавания.
    "item.bucket.fill": ["liquid/splash"],
    "item.bucket.empty": ["liquid/splash2"],
    "entity.player.swim": ["liquid/splash", "liquid/splash2"],
    "item.bucket.fill_lava": "item.bucket.fill",
    "item.bucket.empty_lava": "item.bucket.empty",
}


def material_of(block_type):
    return MATERIALS.get(block_type, DEFAULT_MATERIAL)


class Sounds:
    def __init__(self, volume=1.0):
        self.volume = volume
        self.cache = {}
        self.events = {}
        # Свои звуки пещер: собираются при первом страшном звуке (cave_sounds).
        self.cave_sounds = None
        self.enabled = self.start_mixer()

        if self.enabled:
            self.events = self.read_events()

    @staticmethod
    def start_mixer():
        try:
            if pygame.mixer.get_init() is None:
                pygame.mixer.init()

            pygame.mixer.set_num_channels(CHANNELS)
            return True

        except pygame.error as error:
            print(f"Звук отключён: {error}")
            return False

    @staticmethod
    def read_events():
        try:
            with open(SOUNDS_JSON, encoding="utf-8") as file:
                data = json.load(file)

        except (OSError, ValueError) as error:
            print(f"Не удалось прочитать {SOUNDS_JSON}: {error}")
            return {}

        events = {}

        for name, entry in data.items():
            files = []

            for sound in entry.get("sounds", []):
                if isinstance(sound, dict):
                    # Ссылки на другие события и потоковую музыку пропускаем.
                    if sound.get("type") == "event" or sound.get("stream"):
                        continue

                    sound = sound.get("name")

                if isinstance(sound, str) and os.path.exists(SOUNDS_DIR + sound + ".ogg"):
                    files.append(sound)

            if files:
                events[name] = files

        return events

    def files_for(self, event):
        if event in self.events:
            return self.events[event]

        fallback = FALLBACKS.get(event)

        if isinstance(fallback, str):
            return self.files_for(fallback)

        if fallback:
            return [name for name in fallback if os.path.exists(SOUNDS_DIR + name + ".ogg")]

        return []

    def has(self, event):
        """Есть ли у события хоть один файл (своим или через замену)."""
        return bool(self.files_for(event))

    def load(self, name):
        if name not in self.cache:
            try:
                self.cache[name] = pygame.mixer.Sound(SOUNDS_DIR + name + ".ogg")
            except pygame.error as error:
                print(f"Не удалось загрузить звук {name}: {error}")
                self.cache[name] = None

        return self.cache[name]

    def play(self, event, volume=1.0, pan=0.0):
        """pan от -1 (слева) до 1 (справа). Возвращает False, если играть нечего."""
        if not self.enabled or self.volume <= 0:
            return False

        files = self.files_for(event)

        if not files:
            return False

        sound = self.load(random.choice(files))

        if sound is None:
            return False

        return self.play_sound(sound, volume, pan)

    def play_sound(self, sound, volume=1.0, pan=0.0):
        """Играет готовый звук (pygame.mixer.Sound) с громкостью и стороной."""
        if not self.enabled or self.volume <= 0:
            return False

        channel = sound.play()

        if channel is None:
            return False

        level = max(0.0, min(1.0, volume * self.volume))
        channel.set_volume(level * min(1.0, 1.0 - pan), level * min(1.0, 1.0 + pan))

        return True

    def spatial(self, position, listener, volume):
        """Громкость и сторона звука в точке мира, или None, если он не слышен."""
        x, y, z = position
        eye_x, eye_y, eye_z = listener.position

        dx, dy, dz = x - eye_x, y - eye_y, z - eye_z
        distance = math.sqrt(dx * dx + dy * dy + dz * dz)

        if distance >= HEARING_DISTANCE:
            return None

        volume *= 1.0 - distance / HEARING_DISTANCE

        # Вектор "вправо" от взгляда, тот же, что у ходьбы стрейфом.
        yaw = listener.rotation[1]
        horizontal = math.hypot(dx, dz)
        pan = 0.0

        if horizontal > 1e-6:
            pan = (dx * math.cos(yaw) - dz * math.sin(yaw)) / horizontal
            # Совсем в одно ухо не уводим: так звучит естественнее.
            pan *= 0.7

        return volume, pan

    def play_at(self, event, position, listener, volume=1.0):
        """Звук в точке мира: тише с расстоянием, громче в том ухе, с чьей он стороны."""
        heard = self.spatial(position, listener, volume)

        return heard is not None and self.play(event, *heard)

    def cave_sound(self, position, listener, volume=1.0):
        """Страшный звук пещеры: из пака (ambient.cave), а если его там нет, свой синтезированный."""
        if self.has("ambient.cave"):
            return self.play_at("ambient.cave", position, listener, volume)

        if self.cave_sounds is None:
            import cave_sounds
            self.cave_sounds = cave_sounds.make_sounds() if self.enabled else []

        heard = self.spatial(position, listener, volume)

        if not self.cave_sounds or heard is None:
            return False

        return self.play_sound(random.choice(self.cave_sounds), *heard)

    def block_sound(self, block_type, action, position, listener, volume=1.0):
        """action: break, place или step."""
        event = f"block.{material_of(block_type)}.{action}"

        if event not in self.events and event not in FALLBACKS:
            event = f"block.{DEFAULT_MATERIAL}.{action}"

        return self.play_at(event, position, listener, volume)


MUSIC_DIR = SOUNDS_DIR + "music/"

# Паузы между треками в секундах. В оригинале первая была до 10 минут, а следующие
# по 10-20 минут; здесь короче, чтобы музыку было слышно.
FIRST_TRACK_DELAY = (5, 30)
TRACK_GAP = (120, 360)


class Music:
    """Фоновая музыка: случайный трек из MUSIC_DIR, потом тишина и следующий.

    Играет потоком через pygame.mixer.music, поэтому файл не грузится в память целиком.
    """

    def __init__(self, sounds, volume=1.0):
        self.sounds = sounds
        self.volume = volume
        self.tracks = self.find_tracks() if sounds.enabled else []
        self.current = None
        self.wait = random.uniform(*FIRST_TRACK_DELAY)

    @staticmethod
    def find_tracks():
        if not os.path.isdir(MUSIC_DIR):
            return []

        return sorted(name for name in os.listdir(MUSIC_DIR) if name.endswith(".ogg"))

    def level(self):
        return max(0.0, min(1.0, self.sounds.volume * self.volume))

    def update(self, dt):
        if not self.tracks:
            return

        pygame.mixer.music.set_volume(self.level())

        if pygame.mixer.music.get_busy():
            return

        # Трек доиграл: ждём паузу и запускаем следующий.
        if self.current is not None:
            self.current = None
            self.wait = random.uniform(*TRACK_GAP)

        self.wait -= dt

        if self.wait <= 0 and self.level() > 0:
            self.play_next()

    def play_next(self):
        choices = [track for track in self.tracks if track != self.current] or self.tracks
        track = random.choice(choices)

        try:
            pygame.mixer.music.load(MUSIC_DIR + track)
            pygame.mixer.music.set_volume(self.level())
            pygame.mixer.music.play()
            self.current = track

        except pygame.error as error:
            print(f"Не удалось включить музыку {track}: {error}")
            self.wait = random.uniform(*TRACK_GAP)
