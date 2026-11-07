import pygame
import math
import numpy as np
import time

from textures import load_surface, water_frames

try:
    import raster
except ImportError:
    raise SystemExit("Модуль raster не собран. Запусти: python build_raster.py")


HAND_FOV = 70
HAND_DISTANCE = 1.0
HAND_X = 0.6
HAND_Y = 0.62

# Дневное небо: насыщенный голубой в зените и светлый у горизонта.
# Туман того же цвета, что горизонт, поэтому дальние блоки растворяются в небе.
SKY_COLOR = (120, 167, 255)
FOG_COLOR = (192, 216, 255)
# Выше этого угла над горизонтом небо уже полностью цвета зенита.
SKY_BLEND = math.radians(40)
# Туман начинается с этой доли дальности и густеет до неё линейно.
FOG_START = 0.5

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
    
    def load_texture(self, path):
        if path not in self.textures:
            self.add_texture(path, load_surface(path).convert_alpha())

        return self.textures[path]

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

    def render(self, world, screen, camera, extra=(), underwater=False, fog_light=1.0):
        """Рисует мир. extra: дополнительные объекты поверх, например трещины на блоке.

        Сначала всё непрозрачное, потом вода от дальней к ближней: она смешивается
        с тем, что уже нарисовано. underwater: глаза под водой, туман синий и близкий.
        fog_light: насколько светло там, где глаза. В тёмной пещере даль тонет
        не в светлом тумане, а в темноте.
        """
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
            self.draw_sky(screen, camera, focal_length, fog_light)

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
        ], dtype=np.float32)

        camera_position = np.asarray(
            camera.position,
            dtype=np.float32
        )

        fog_end = min(self.fog_distance, UNDERWATER_FOG) if underwater else self.fog_distance
        fog_start = 0 if underwater else fog_end * FOG_START
        fog_color = tuple(int(channel * fog_light) for channel in (UNDERWATER_COLOR if underwater else FOG_COLOR))
        alpha_mask = screen.get_masks()[3]
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

            camera_points = (world_points - camera_position) @ camera_matrix.T

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
                alpha_mask
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

    def draw_sky(self, screen, camera, focal_length, light=1.0):
        """Градиент неба по строкам: у каждой строки свой угол над горизонтом.

        Камера не наклоняется вбок, поэтому цвет вдоль строки один и тот же.
        light: в пещере небо темнеет вместе с туманом, иначе сквозь щели в
        незагруженную даль светило бы голубым.
        """
        height = screen.get_height()

        rows = np.arange(height, dtype=np.float32) + 0.5
        elevation = camera.rotation[0] + np.arctan((height / 2 - rows) / focal_length)

        blend = np.clip(elevation / SKY_BLEND, 0, 1)[:, None]
        colors = np.array(FOG_COLOR, dtype=np.float32) * (1 - blend) + np.array(SKY_COLOR, dtype=np.float32) * blend
        colors *= light

        column = pygame.Surface((1, height))
        pygame.surfarray.blit_array(column, colors[None, :, :].astype(np.uint8))

        pygame.transform.scale(column, screen.get_size(), screen)

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
