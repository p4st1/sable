import pygame
import math
import numpy as np
import time

import daytime
from textures import load_surface, water_frames

try:
    import raster
except ImportError:
    raise SystemExit("Модуль raster не собран. Запусти: python build_raster.py")


HAND_FOV = 70
HAND_DISTANCE = 1.0
HAND_X = 0.6
HAND_Y = 0.62

# Цвета неба и тумана по времени суток считает daytime.
# Выше этого угла над горизонтом небо уже полностью цвета зенита.
SKY_BLEND = math.radians(40)
# Туман начинается с этой доли дальности и густеет до неё линейно.
FOG_START = 0.5

# Светила на сфере такого радиуса вокруг глаз, размеры их квадратов (половина
# стороны) и звёзд, как в оригинале.
SKY_RADIUS = 100.0
SUN_SIZE = 30.0
MOON_SIZE = 20.0
STAR_COUNT = 1500
STAR_SIZE = (0.15, 0.25)
STAR_SEED = 10842
SUN_TEXTURE = "assets/minecraft/textures/environment/sun.png"
MOON_TEXTURE = "assets/minecraft/textures/environment/moon_phases.png"
MOON_COLUMNS, MOON_ROWS = 4, 2
# Под горизонтом светило гаснет за такую долю радиуса.
SET_FADE = 0.15

# Зарево: до какого угла над горизонтом оно поднимается и насколько узко
# собрано вокруг стороны солнца. Считается в малом размере и растягивается.
GLOW_HEIGHT = math.radians(30)
GLOW_SPREAD = 2
GLOW_COLUMNS = 96
GLOW_ROWS = 64

# Вода: доля её цвета в 1/256 и скорость анимации (кадр на тик, как в оригинале).
WATER_OPACITY = 150
WATER_FPS = 20
# Под водой всё тонет в синем тумане уже в нескольких блоках.
UNDERWATER_COLOR = (22, 40, 120)
UNDERWATER_FOG = 14


class Renderer:
    def __init__(self):
        self.font = pygame.font.Font('fonts/minecraft.ttf', 20)
        self.textures = {}

        self.transform_time = 0
        self.raster_time = 0
        self.visible_objects = 0
        self.total_triangles = 0

        self.texture_arrays = {}
        # Маска альфы для текстур с прозрачными пикселями, у остальных None.
        self.texture_alpha = {}
        self.depth_buffer = None

        # Дальше этого расстояния всё в тумане, и такие чанки даже не рисуются.
        self.fog_distance = 64
        self.fog_time = 0

        # Кадры анимации воды в формате пикселей экрана, загружаются при первой воде.
        self.water_frames = None

        # Кадры анимированных текстур (огонь) в формате растеризатора.
        self.animations = {}

        # Квадраты светил и звёзды в своей системе: солнце над головой, луна под ногами.
        self.sky_meshes = None
    
    def load_texture(self, path):
        if path not in self.textures:
            self.add_texture(path, load_surface(path).convert_alpha())

        return self.textures[path]

    def animate(self, key, frames, index):
        """Подменяет кадр анимированной текстуры key прямо в массивах растеризатора.

        Меши ссылаются на текстуру, а не на кадр, поэтому их не перестраиваем.
        frames: поверхности кадров, index: номер кадра.
        """
        if key not in self.textures:
            return

        if key not in self.animations:
            self.animations[key] = [
                (
                    np.ascontiguousarray(pygame.surfarray.map_array(pygame.Surface((1, 1)), pygame.surfarray.array3d(frame)).T, dtype=np.uint32),
                    np.ascontiguousarray(pygame.surfarray.array_alpha(frame).T, dtype=np.uint8),
                )
                for frame in frames
            ]

        texture = self.textures[key]
        colors, alpha = self.animations[key][index % len(self.animations[key])]
        np.copyto(self.texture_arrays[id(texture)], colors)

        if self.texture_alpha[id(texture)] is not None:
            np.copyto(self.texture_alpha[id(texture)], alpha)

    def add_texture(self, key, texture):
        """Готовит текстуру для растеризатора. key заменяет путь у созданных в коде."""
        if key not in self.textures:
            self.textures[key] = texture

            # Текстура сразу в формате пикселей экрана, строками (y, x):
            # растеризатор копирует пиксель одним 32-битным присваиванием.
            mapped = pygame.surfarray.map_array(
                pygame.Surface((1, 1)),
                pygame.surfarray.array3d(texture)
            )

            self.texture_arrays[id(texture)] = np.ascontiguousarray(
                mapped.T,
                dtype=np.uint32
            )

            alpha = pygame.surfarray.array_alpha(texture)

            self.texture_alpha[id(texture)] = (
                None if alpha.min() == 255
                else np.ascontiguousarray(alpha.T, dtype=np.uint8)
            )

        return self.textures[key]
    
    def render_text(self, screen, text, pos):
        text_surface = self.font.render(text, True, (255, 255, 255))
        screen.blit(text_surface, pos)

    def load_water_frames(self):
        if self.water_frames is None:
            self.water_frames = [
                np.ascontiguousarray(
                    pygame.surfarray.map_array(pygame.Surface((1, 1)), pygame.surfarray.array3d(frame)).T,
                    dtype=np.uint32
                )
                for frame in water_frames()
            ]

        return self.water_frames

    def render(self, world, screen, camera, extra=(), underwater=False, fog_light=1.0, sky=None):
        """Рисует мир. extra: дополнительные объекты поверх, например трещины на блоке.

        Сначала всё непрозрачное, потом вода от дальней к ближней: она смешивается
        с тем, что уже нарисовано. underwater: глаза под водой, туман синий и близкий.
        fog_light: насколько светло там, где глаза. В тёмной пещере даль тонет
        не в светлом тумане, а в темноте. sky: время суток (daytime.Sky), без него полдень.
        """
        if sky is None:
            sky = daytime.sky_at(daytime.TITLE_TIME)

        width = screen.get_width()
        height = screen.get_height()
        aspect = width / height

        self.transform_time = 0
        self.raster_time = 0
        self.visible_objects = 0
        self.total_triangles = 0

        if self.depth_buffer is None or self.depth_buffer.shape != (height, width):
            self.depth_buffer = np.zeros(
                (height, width),
                dtype=np.float32
            )
        else:
            self.depth_buffer.fill(0)

        focal_length = (height / 2) / math.tan(math.radians(camera.fov) / 2)

        if underwater:
            screen.fill(UNDERWATER_COLOR)
        else:
            self.draw_sky(screen, camera, focal_length, fog_light, sky)

        pixels = pygame.surfarray.pixels2d(screen).T

        camera_pitch = -camera.rotation[0]
        camera_yaw = -camera.rotation[1]

        cos_camera_pitch = math.cos(camera_pitch)
        sin_camera_pitch = math.sin(camera_pitch)

        cos_camera_yaw = math.cos(camera_yaw)
        sin_camera_yaw = math.sin(camera_yaw)

        camera_matrix = np.array([
            [
                cos_camera_yaw,
                0,
                sin_camera_yaw
            ],
            [
                sin_camera_pitch * sin_camera_yaw,
                cos_camera_pitch,
                -sin_camera_pitch * cos_camera_yaw
            ],
            [
                -cos_camera_pitch * sin_camera_yaw,
                sin_camera_pitch,
                cos_camera_pitch * cos_camera_yaw
            ]
        ])

        camera_position = np.asarray(
            camera.position,
            dtype=np.float64
        )

        fog_end = min(self.fog_distance, UNDERWATER_FOG) if underwater else self.fog_distance
        fog_start = 0 if underwater else fog_end * FOG_START
        fog_color = tuple(int(channel * fog_light) for channel in (UNDERWATER_COLOR if underwater else self.fog_color(camera, sky)))
        alpha_mask = screen.get_masks()[3]

        if not underwater:
            self.draw_celestial(pixels, camera_matrix, focal_length, camera.near, sky, fog_light, alpha_mask)
        eye_x, eye_y, eye_z = camera.position

        def visible(object):
            if not self.is_object_visible(object, camera, aspect):
                return None

            # Чанк целиком за туманом: он был бы просто цветом неба.
            center_x, center_y, center_z = object.center
            distance = math.sqrt((center_x - eye_x) ** 2 + (center_y - eye_y) ** 2 + (center_z - eye_z) ** 2)

            return None if distance - object.radius > fog_end else distance

        water = []

        for object in world.liquids:
            distance = visible(object)

            if distance is not None:
                water.append((distance, object))

        water.sort(key=lambda pair: -pair[0])

        if water:
            frames = self.load_water_frames()
            water_pixels = frames[int(time.perf_counter() * WATER_FPS) % len(frames)]

        opaque = [(object, 256) for object in [*world.objects, *extra] if visible(object) is not None]

        for object, opacity in opaque + [(object, WATER_OPACITY) for _, object in water]:
            self.visible_objects += 1

            if opacity < 256:
                texture_pixels = water_pixels
                texture_alpha = None
            else:
                texture_pixels = self.texture_arrays[id(object.mesh.texture)]
                texture_alpha = self.texture_alpha[id(object.mesh.texture)]

            start = time.perf_counter()

            world_points = object.world_points

            # Считаем в float64: вдали от начала мира у float32 мало знаков после
            # запятой, вершины соседних граней разъезжаются, и между блоками видны щели.
            # После вычитания позиции камеры числа маленькие, и float32 им хватает.
            camera_points = ((world_points - camera_position) @ camera_matrix.T).astype(np.float32)

            self.transform_time += time.perf_counter() - start

            start = time.perf_counter()

            self.total_triangles += raster.draw_mesh(
                camera_points,
                object.mesh.triangles,
                object.mesh.uvs,
                texture_pixels,
                pixels,
                self.depth_buffer,
                focal_length,
                camera.near,
                texture_alpha,
                opacity,
                object.mesh.shades,
                getattr(object, "brightness", 1.0),
                alpha_mask,
                object.mesh.night_shades,
                sky.night
            )

            self.raster_time += time.perf_counter() - start

        start = time.perf_counter()
        shift_r, shift_g, shift_b, _ = screen.get_shifts()

        raster.apply_fog(
            pixels,
            self.depth_buffer,
            shift_r, shift_g, shift_b,
            *fog_color,
            fog_start,
            fog_end,
            screen.get_masks()[3]
        )

        self.fog_time = time.perf_counter() - start

        del pixels

    def draw_sky(self, screen, camera, focal_length, light=1.0, sky=None):
        """Градиент неба по строкам: у каждой строки свой угол над горизонтом.

        Камера не наклоняется вбок, поэтому цвет вдоль строки один и тот же.
        На восходе и закате у горизонта со стороны солнца зарево: тогда цвет
        зависит и от столбца, его считаем в малом размере и растягиваем.
        light: в пещере небо темнеет вместе с туманом, иначе сквозь щели в
        незагруженную даль светило бы голубым.
        """
        if sky is None:
            sky = daytime.sky_at(daytime.TITLE_TIME)

        width, height = screen.get_size()
        rows = GLOW_ROWS if sky.glow > 0 else height

        rows_at = (np.arange(rows, dtype=np.float32) + 0.5) * (height / rows)
        elevation = camera.rotation[0] + np.arctan((height / 2 - rows_at) / focal_length)

        blend = np.clip(elevation / SKY_BLEND, 0, 1)[:, None]
        colors = np.array(sky.fog_color, dtype=np.float32) * (1 - blend) + np.array(sky.sky_color, dtype=np.float32) * blend

        if sky.glow <= 0:
            colors *= light
            column = pygame.Surface((1, height))
            pygame.surfarray.blit_array(column, colors[None, :, :].astype(np.uint8))
            pygame.transform.scale(column, screen.get_size(), screen)
            return

        # Сторона света каждого столбца и насколько она смотрит на солнце.
        columns_at = (np.arange(GLOW_COLUMNS, dtype=np.float32) + 0.5) * (width / GLOW_COLUMNS)
        azimuth = camera.rotation[1] + np.arctan((columns_at - width / 2) / focal_length)
        sun_x = daytime.sun_direction(sky.angle)[0]
        facing = np.clip(np.sin(azimuth) * math.copysign(1.0, sun_x), 0, 1) ** GLOW_SPREAD

        height_part = np.clip(1 - np.abs(elevation) / GLOW_HEIGHT, 0, 1) ** 2
        weight = (height_part[:, None] * facing[None, :] * sky.glow)[:, :, None]

        grid = colors[:, None, :] * (1 - weight) + np.array(sky.glow_color, dtype=np.float32) * weight
        grid *= light

        small = pygame.Surface((GLOW_COLUMNS, rows))
        pygame.surfarray.blit_array(small, np.transpose(grid, (1, 0, 2)).clip(0, 255).astype(np.uint8))
        pygame.transform.smoothscale(small, screen.get_size(), screen)

    def fog_color(self, camera, sky):
        """Цвет тумана: глядя на закатное солнце, туман краснеет, как в оригинале."""
        if sky.glow <= 0:
            return sky.fog_color

        forward_x = math.sin(camera.rotation[1])
        sun_x = daytime.sun_direction(sky.angle)[0]
        amount = max(0.0, forward_x * math.copysign(1.0, sun_x)) * sky.glow

        return tuple(int(fog + (glow - fog) * amount) for fog, glow in zip(sky.fog_color, sky.glow_color))

    def build_sky_meshes(self):
        """Квадраты солнца и луны (двусторонние) и звёзды. Ось Y вниз."""
        def quad(points, uvs):
            triangles = [(0, 1, 2), (0, 2, 3), (0, 2, 1), (0, 3, 2)]
            triangle_uvs = [tuple(uvs[index] for index in triangle) for triangle in triangles]

            return np.array(points, dtype=np.float64), np.array(triangles, dtype=np.int32), np.array(triangle_uvs, dtype=np.float32)

        def square(size, y, uvs):
            return quad([(-size, y, -size), (size, y, -size), (size, y, size), (-size, y, size)], uvs)

        sun = square(SUN_SIZE, -SKY_RADIUS, [(0, 0), (1, 0), (1, 1), (0, 1)])

        moons = []

        for phase in range(daytime.MOON_PHASES):
            u0, v0 = (phase % MOON_COLUMNS) / MOON_COLUMNS, (phase // MOON_COLUMNS) / MOON_ROWS
            u1, v1 = u0 + 1 / MOON_COLUMNS, v0 + 1 / MOON_ROWS
            moons.append(square(MOON_SIZE, SKY_RADIUS, [(u1, v1), (u0, v1), (u0, v0), (u1, v0)]))

        # Звёзды: случайные точки сферы, у каждой маленький квадрат лицом к центру.
        rng = np.random.default_rng(STAR_SEED)
        directions = rng.normal(size=(STAR_COUNT, 3))
        directions /= np.linalg.norm(directions, axis=1)[:, None]
        sizes = rng.uniform(*STAR_SIZE, STAR_COUNT)
        spins = rng.uniform(0, math.tau, STAR_COUNT)

        helper = np.where(np.abs(directions[:, 1:2]) < 0.9, [[0, 1, 0]], [[1, 0, 0]])
        side = np.cross(directions, helper)
        side /= np.linalg.norm(side, axis=1)[:, None]
        up = np.cross(directions, side)
        side, up = (
            side * np.cos(spins)[:, None] + up * np.sin(spins)[:, None],
            up * np.cos(spins)[:, None] - side * np.sin(spins)[:, None],
        )

        center = directions * SKY_RADIUS
        offsets = np.array([(-1, -1), (1, -1), (1, 1), (-1, 1)], dtype=np.float64)
        corners = center[:, None, :] + (
            offsets[None, :, 0, None] * side[:, None, :] + offsets[None, :, 1, None] * up[:, None, :]
        ) * sizes[:, None, None]

        star_points = corners.reshape(-1, 3)
        base = np.arange(STAR_COUNT, dtype=np.int32)[:, None, None] * 4
        local = np.array([(0, 1, 2), (0, 2, 3), (0, 2, 1), (0, 3, 2)], dtype=np.int32)
        star_triangles = (base + local).reshape(-1, 3)
        star_uvs = np.full((len(star_triangles), 3, 2), 0.5, dtype=np.float32)

        white = pygame.Surface((1, 1))
        white.fill((255, 255, 255))

        self.sky_meshes = {
            "sun": (*sun, self.load_texture(SUN_TEXTURE)),
            "moons": [(*moon, self.load_texture(MOON_TEXTURE)) for moon in moons],
            "stars": (star_points, star_triangles, star_uvs, self.add_texture("generated:star", white)),
        }

    def draw_celestial(self, pixels, camera_matrix, focal_length, near, sky, light, alpha_mask):
        """Солнце, луна и звёзды сложением поверх неба. Они вращаются вокруг оси x."""
        if self.sky_meshes is None:
            self.build_sky_meshes()

        turn = -sky.angle * math.tau
        cos, sin = math.cos(turn), math.sin(turn)
        rotation = np.array([[cos, -sin, 0], [sin, cos, 0], [0, 0, 1]])
        to_camera = camera_matrix.astype(np.float64) @ rotation

        sun_height = -daytime.sun_direction(sky.angle)[1]

        def draw(points, triangles, uvs, texture, brightness):
            if brightness <= 0.004:
                return

            raster.draw_mesh(
                np.ascontiguousarray(points @ to_camera.T, dtype=np.float32),
                triangles,
                uvs,
                self.texture_arrays[id(texture)],
                pixels,
                self.depth_buffer,
                focal_length,
                near,
                None,
                256,
                None,
                brightness,
                alpha_mask,
                None,
                0.0,
                True
            )

        def above_horizon(height):
            return min(1.0, max(0.0, 1 + height / SET_FADE))

        stars = self.sky_meshes["stars"]
        draw(*stars, sky.stars * light)

        draw(*self.sky_meshes["sun"], above_horizon(sun_height) * light)
        draw(*self.sky_meshes["moons"][sky.moon_phase], above_horizon(-sun_height) * light)

    def hand_offset(self, screen):
        """Точка в пространстве камеры, где держится блок. От неё отсчитываются меши руки.

        Положение задано долей экрана, чтобы блок оставался в углу при любых пропорциях.
        """
        tan_half_fov = math.tan(math.radians(HAND_FOV) / 2)

        return np.array([
            HAND_X * tan_half_fov * screen.get_width() / screen.get_height() * HAND_DISTANCE,
            HAND_Y * tan_half_fov * HAND_DISTANCE,
            HAND_DISTANCE
        ], dtype=np.float32)

    def render_held_block(self, meshes, screen, brightness=1.0):
        """Рисует меши в пространстве камеры поверх мира, без его буфера глубины.

        FOV здесь свой: иначе блок менялся бы вместе с настройкой обзора.
        brightness: свет там, где стоит игрок.
        """
        height = screen.get_height()

        tan_half_fov = math.tan(math.radians(HAND_FOV) / 2)
        focal_length = (height / 2) / tan_half_fov

        offset = self.hand_offset(screen)

        self.depth_buffer.fill(0)

        pixels = pygame.surfarray.pixels2d(screen).T

        for mesh, points in meshes:
            raster.draw_mesh(
                points + offset,
                mesh.triangles,
                mesh.uvs,
                self.texture_arrays[id(mesh.texture)],
                pixels,
                self.depth_buffer,
                focal_length,
                0.05,
                self.texture_alpha[id(mesh.texture)],
                256,
                mesh.shades,
                brightness,
                screen.get_masks()[3]
            )

        del pixels

    def rotate_x(self, x, y, z, angle):
        cos = math.cos(angle)
        sin = math.sin(angle)

        return x, y * cos - z * sin, y * sin + z * cos
    
    def rotate_y(self, x, y, z, angle):
        cos = math.cos(angle)
        sin = math.sin(angle)

        return x * cos + z * sin, y, -x * sin + z * cos
    
    def rotate_z(self, x, y, z, angle):
        cos = math.cos(angle)
        sin = math.sin(angle)

        return x * cos - y * sin, x * sin + y * cos, z
    

    def rotation_matrix(self, rotation):
        rx, ry, rz = rotation

        cx = math.cos(rx)
        sx = math.sin(rx)

        cy = math.cos(ry)
        sy = math.sin(ry)

        cz = math.cos(rz)
        sz = math.sin(rz)

        rotation_x = np.array([
            [1, 0, 0],
            [0, cx, -sx],
            [0, sx, cx]
        ], dtype=np.float32)

        rotation_y = np.array([
            [cy, 0, sy],
            [0, 1, 0],
            [-sy, 0, cy]
        ], dtype=np.float32)

        rotation_z = np.array([
            [cz, -sz, 0],
            [sz, cz, 0],
            [0, 0, 1]
        ], dtype=np.float32)

        return rotation_z @ rotation_y @ rotation_x
    
    def is_object_visible(self, object, camera, aspect):
        center_x, center_y, center_z = object.center
        radius = object.radius

        x = center_x - camera.position[0]
        y = center_y - camera.position[1]
        z = center_z - camera.position[2]

        yaw = -camera.rotation[1]
        pitch = -camera.rotation[0]

        cos_yaw = math.cos(yaw)
        sin_yaw = math.sin(yaw)

        cos_pitch = math.cos(pitch)
        sin_pitch = math.sin(pitch)

        new_x = x * cos_yaw + z * sin_yaw
        new_z = -x * sin_yaw + z * cos_yaw

        x = new_x
        z = new_z

        new_y = y * cos_pitch - z * sin_pitch
        new_z = y * sin_pitch + z * cos_pitch

        y = new_y
        z = new_z

        if z + radius <= 0:
            return False

        if z - radius <= 0:
            return True

        # Сферу сравниваем с настоящим расстоянием до наклонной плоскости обзора:
        # (|x| - z * tan) * cos. Без cos сфера у края экрана отсекается раньше времени.
        tan_vertical = math.tan(math.radians(camera.fov) / 2)
        tan_horizontal = tan_vertical * aspect

        cos_vertical = 1 / math.sqrt(1 + tan_vertical * tan_vertical)
        cos_horizontal = 1 / math.sqrt(1 + tan_horizontal * tan_horizontal)

        if (abs(y) - z * tan_vertical) * cos_vertical > radius:
            return False

        if (abs(x) - z * tan_horizontal) * cos_horizontal > radius:
            return False

        return True
