"""Движение игрока: ходьба с гравитацией и полёт. Ось Y направлена вниз.

В выживании у игрока есть здоровье: 20 единиц, на экране это 10 сердечек.
Урон наносит падение с высоты больше SAFE_FALL блоков и падение в пустоту.
Само здоровье не восстанавливается, только едой (см. heal).
"""
import math

from collision import FEET, has_support, move, player_box
from water import body_in_water, point_in_water

TERMINAL_VELOCITY = 60
VOID_Y = 128
DOUBLE_TAP_MS = 300

# При долгой паузе кадра физика делает один короткий шаг, а не прыгает на секунды вперёд.
MAX_STEP = 0.1

MAX_HEALTH = 20
SAFE_FALL = 3
# После удара игрок полсекунды неуязвим, а сердечки мигают.
HURT_TIME = 0.5

# Подкрадывание (Shift): медленнее, с края не упасть, шагов не слышно,
# а глаза чуть ниже, как в версии 1.0.
SNEAK_SPEED = 0.3
SNEAK_EYE_DROP = 0.08
SNEAK_EYE_SPEED = 10.0
# С таким шагом укорачивается движение, пока под ногами не появится опора.
EDGE_STEP = 0.05

# Шаг слышен раз в столько блоков пройденного по земле пути.
STEP_DISTANCE = 1.6
# Приземление после падения выше этого слышно как шаг.
LAND_SOUND_FALL = 0.5

# Вода, пересчитанная из тиков оригинала (20 в секунду) в блоки и секунды.
TICKS = 20
WATER_SPEED = 0.5
# Тянет вниз вчетверо слабее, чем в воздухе, а пробел тянет вверх вдвое сильнее.
WATER_GRAVITY = 0.02 * TICKS * TICKS
SWIM_UP = 0.04 * TICKS * TICKS
# Доля скорости, что остаётся за тик: вода быстро гасит любое движение.
WATER_DRAG = 0.8
# Скорость, с которой выталкивает на берег, когда в него упираешься из воды.
WATER_CLIMB_SPEED = 0.3 * TICKS
# Падение в воду быстрее этого слышно как плеск.
SPLASH_SPEED = 4.0
# Плеск рук при плавании раз в столько блоков пути.
SWIM_DISTANCE = 2.5

# Воздух под водой: 15 секунд, потом урон раз в секунду. Наверху воздух
# восстанавливается впятеро быстрее, чем тратился.
MAX_AIR = 15.0
AIR_REFILL = 5.0
DROWN_INTERVAL = 1.0
DROWN_DAMAGE = 2


class Player:
    def __init__(self, world, camera, settings):
        self.world = world
        self.camera = camera

        self.speed = settings.speed
        self.gravity = settings.gravity
        self.jump_speed = settings.jump_speed

        self.flying = False
        self.on_ground = False
        self.velocity = 0.0

        self.spawn = camera.position
        self.last_space = None

        self.survival = False
        self.health = MAX_HEALTH
        self.hurt_time = 0.0
        self.dead = False

        # Самая высокая точка с тех пор, как ноги оторвались от земли (меньший y).
        self.fall_start = None

        # Что случилось за кадр, для звуков: ("step", блок), ("land", блок), ("hurt",).
        # Игра забирает список после update.
        self.events = []
        self.walked = 0.0

        self.sneaking = False
        # Насколько сейчас опущена камера: плавно догоняет SNEAK_EYE_DROP.
        self.eye_drop = 0.0

        # Тело в воде (плавает) и глаза под водой (тратится воздух, синий туман).
        self.in_water = False
        self.eyes_in_water = False
        self.air = MAX_AIR
        self.drown_time = 0.0

    def set_flying(self, flying):
        self.flying = flying
        self.on_ground = False
        self.velocity = 0.0
        self.fall_start = None

    def damage(self, amount):
        """Наносит урон в выживании. Во время неуязвимости после удара урон не проходит."""
        if not self.survival or self.dead or amount <= 0 or self.hurt_time > 0:
            return

        self.health = max(0, self.health - amount)
        self.hurt_time = HURT_TIME
        self.events.append(("hurt",))

        if self.health == 0:
            self.dead = True

    def respawn(self, position):
        self.camera.position = position
        self.air = MAX_AIR
        self.drown_time = 0.0
        self.health = MAX_HEALTH
        self.dead = False
        self.hurt_time = 0.0
        self.velocity = 0.0
        self.fall_start = None

    def heal(self, amount):
        """Лечит едой. Возвращает False, если лечить некого или нечего."""
        if not self.survival or self.dead or self.health >= MAX_HEALTH:
            return False

        self.health = min(MAX_HEALTH, self.health + amount)
        return True

    def update_health(self, dt):
        self.hurt_time = max(0.0, self.hurt_time - dt)

    def update_air(self, dt):
        """Под водой воздух кончается, и тогда раз в секунду идёт урон. В творческом не тонут."""
        if not (self.survival and self.eyes_in_water) or self.dead:
            self.air = min(MAX_AIR, self.air + dt * AIR_REFILL)
            self.drown_time = 0.0
            return

        self.air = max(0.0, self.air - dt)

        if self.air > 0:
            return

        self.drown_time += dt

        if self.drown_time >= DROWN_INTERVAL:
            self.drown_time -= DROWN_INTERVAL
            self.damage(DROWN_DAMAGE)

    def swim(self, dt, space, shift):
        """Шаг по вертикали в воде. Пробел всплывает, Shift топит, без них медленно тонешь."""
        acceleration = WATER_GRAVITY

        if space:
            acceleration -= SWIM_UP

        if shift:
            acceleration += SWIM_UP

        self.velocity += acceleration * dt
        self.velocity *= WATER_DRAG ** (dt * TICKS)

        return self.velocity * dt

    def track_fall(self):
        """Урон при приземлении: по блоку за каждый блок падения сверх SAFE_FALL."""
        y = self.camera.position[1]

        if self.on_ground:
            if self.fall_start is not None:
                fall = y - self.fall_start

                if fall > LAND_SOUND_FALL:
                    self.events.append(("land", self.ground_block()))

                self.damage(math.ceil(fall - SAFE_FALL))

            self.fall_start = None

        elif self.fall_start is None or y < self.fall_start:
            self.fall_start = y

    def ground_block(self):
        """Тип блока под ногами или None. Ось Y направлена вниз."""
        x, y, z = self.camera.position
        block = self.world.get_block(math.floor(x), math.floor(y + FEET + 0.01), math.floor(z))

        return None if block is None else (block.type, (math.floor(x) + 0.5, y + FEET, math.floor(z) + 0.5))

    def count_steps(self, start):
        """Пройденный по земле путь превращается в звуки шагов. Крадучись не слышно.

        В воде вместо шагов плеск, и считается путь во все стороны.
        """
        if self.in_water:
            self.walked += math.dist(self.camera.position, start)

            if self.walked >= SWIM_DISTANCE:
                self.walked -= SWIM_DISTANCE
                self.events.append(("swim",))

            return

        if not self.on_ground or self.sneaking:
            return

        x, _, z = self.camera.position
        self.walked += math.hypot(x - start[0], z - start[2])

        if self.walked >= STEP_DISTANCE:
            self.walked -= STEP_DISTANCE
            self.events.append(("step", self.ground_block()))

    def back_off_edge(self, x, z):
        """Укорачивает шаг так, чтобы под ногами осталась опора, как у оригинала.

        Сначала по каждой оси отдельно, потом вместе: идти вдоль края можно, сойти нельзя.
        """
        position = self.camera.position

        def supported(dx, dz):
            return has_support(self.world, position, dx, dz)

        def shorter(value):
            return 0.0 if abs(value) < EDGE_STEP else value - math.copysign(EDGE_STEP, value)

        while x != 0 and not supported(x, 0):
            x = shorter(x)

        while z != 0 and not supported(0, z):
            z = shorter(z)

        while x != 0 and z != 0 and not supported(x, z):
            x, z = shorter(x), shorter(z)

        return x, z

    def press_space(self, time_ms):
        """Двойное нажатие пробела переключает полёт. В выживании летать нельзя."""
        if self.survival:
            return

        if self.last_space is not None and time_ms - self.last_space <= DOUBLE_TAP_MS:
            self.set_flying(not self.flying)
            self.last_space = None
        else:
            self.last_space = time_ms

    def update(self, dt, forward, right, space, shift):
        dt = min(dt, MAX_STEP)

        self.update_health(dt)

        was_in_water = self.in_water
        self.in_water = not self.flying and body_in_water(self.world, *player_box(self.camera.position))
        self.eyes_in_water = point_in_water(self.world, self.camera.position)
        self.update_air(dt)

        # В полёте Shift опускает вниз, в воде топит, а на земле это подкрадывание.
        self.sneaking = shift and not self.flying and not self.in_water

        target_drop = SNEAK_EYE_DROP if self.sneaking else 0.0
        self.eye_drop += (target_drop - self.eye_drop) * min(1.0, dt * SNEAK_EYE_SPEED)

        speed = self.speed * (SNEAK_SPEED if self.sneaking else 1.0) * (WATER_SPEED if self.in_water else 1.0)
        x, z = self.camera.horizontal_move(forward, right, speed * dt)

        if self.sneaking and self.on_ground:
            x, z = self.back_off_edge(x, z)

        if self.flying:
            # Подъём уменьшает y, потому что ось направлена вниз.
            y = (shift - space) * self.speed * dt
            self.camera.position = move(self.world, self.camera.position, (x, y, z))
            return

        if self.in_water:
            # Плеск, когда игрок падает в воду с разгона.
            if not was_in_water and self.velocity > SPLASH_SPEED:
                self.events.append(("splash",))

            y = self.swim(dt, space, shift)
        else:
            if space and self.on_ground:
                self.velocity = -self.jump_speed
                self.on_ground = False

            # Точная формула равноускоренного движения: высота прыжка не зависит от FPS.
            y = self.velocity * dt + self.gravity * dt * dt / 2
            self.velocity = min(self.velocity + self.gravity * dt, TERMINAL_VELOCITY)

        start = self.camera.position
        start_y = start[1]

        self.camera.position = move(self.world, self.camera.position, (x, y, z))

        if y != 0:
            blocked = abs(self.camera.position[1] - (start_y + y)) > 1e-9

            self.on_ground = blocked and y > 0

            if blocked:
                self.velocity = 0.0

        # Упёрлись в берег из воды: выталкивает наверх, как в оригинале, чтобы вылезти.
        if self.in_water and (x or z):
            blocked_x = abs(self.camera.position[0] - (start[0] + x)) > 1e-9
            blocked_z = abs(self.camera.position[2] - (start[2] + z)) > 1e-9

            if blocked_x or blocked_z:
                self.velocity = -WATER_CLIMB_SPEED

        # Вода гасит падение: урона при приземлении не будет.
        if self.in_water:
            self.fall_start = None

        self.track_fall()
        self.count_steps(start)

        if self.camera.position[1] > VOID_Y:
            if self.survival:
                # Из пустоты не возвращаются: игрок погибает.
                self.hurt_time = 0.0
                self.damage(self.health)
            else:
                self.camera.position = self.spawn
                self.set_flying(True)
