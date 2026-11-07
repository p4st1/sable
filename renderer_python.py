import pygame
import math
import numpy as np
import time

from vertex import Vertex


class Renderer:
    def __init__(self):
        self.font = pygame.font.Font('fonts/minecraft.ttf', 20)
        self.textures = {}

        self.transform_time = 0
        self.raster_time = 0
        self.visible_objects = 0
        self.total_triangles = 0

        self.texture_arrays = {}
    
    def load_texture(self, path):
        if path not in self.textures:
            texture = pygame.image.load(path).convert_alpha()

            self.textures[path] = texture

            self.texture_arrays[id(texture)] = (
                pygame.surfarray.array3d(texture)
            )

        return self.textures[path]
    
    def render_text(self, screen, text, pos):
        text_surface = self.font.render(text, True, (255, 255, 255))
        screen.blit(text_surface, pos)

    def project(self, x, y, z, width, height, fov):
        fov_rad = math.radians(fov)

        focal_length = (height / 2) / math.tan(fov_rad / 2)

        screen_x = x / z * focal_length + width / 2
        screen_y = y / z * focal_length + height / 2

        return int(screen_x), int(screen_y)
    
    def normal(self, a, b, c):
        ab_x = b[0] - a[0]
        ab_y = b[1] - a[1]
        ab_z = b[2] - a[2]

        ac_x = c[0] - a[0]
        ac_y = c[1] - a[1]
        ac_z = c[2] - a[2]

        nx = ab_y * ac_z - ab_z * ac_y
        ny = ab_z * ac_x - ab_x * ac_z
        nz = ab_x * ac_y - ab_y * ac_x

        return nx, ny, nz

    def dot(self, a, b):
        return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
    
    def normalize(self, vector):
        x, y, z = vector

        length = math.sqrt(x * x + y * y + z * z)

        if length == 0:
            return (0, 0, 0)
        
        return (
            x / length,
            y / length,
            z / length
        )

    def render(self, world, screen, camera):
        width = screen.get_width()
        height = screen.get_height()
        aspect = width / height

        self.transform_time = 0
        self.raster_time = 0
        self.visible_objects = 0

        depth_buffer = np.zeros(
            (height, width),
            dtype=np.float32
        )

        pixels = pygame.surfarray.pixels3d(screen)

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

        for object in world.objects:
            if not self.is_object_visible(object, camera, aspect):
                continue

            self.total_triangles += len(object.mesh.triangles)
            
            self.visible_objects += 1

            texture_pixels = self.texture_arrays[id(object.mesh.texture)]

            start = time.perf_counter()

            world_points = object.world_points

            camera_points = (world_points - camera_position) @ camera_matrix.T

            self.transform_time += time.perf_counter() - start

            for triangle_index, triangle in enumerate(object.mesh.triangles):
                uv1, uv2, uv3 = object.mesh.uvs[triangle_index]

                i1, i2, i3 = triangle

                world1 = world_points[i1]
                world2 = world_points[i2]
                world3 = world_points[i3]

                camera1 = camera_points[i1]
                camera2 = camera_points[i2]
                camera3 = camera_points[i3]

                near = 0.1

                z1 = camera1[2]
                z2 = camera2[2]
                z3 = camera3[2]

                if z1 < near and z2 < near and z3 < near:
                    continue
                
                p1 = Vertex(world1, camera1, uv1)
                p2 = Vertex(world2, camera2, uv2)
                p3 = Vertex(world3, camera3, uv3)
                
                if z1 >= near and z2 >= near and z3 >= near:
                    clipped_triangles = [(p1, p2, p3)]

                else:
                    clipped_triangles = self.clip_triangle_near(
                        p1,
                        p2,
                        p3,
                        near
                    )

                for p1, p2, p3 in clipped_triangles:
                    a = p1.camera
                    b = p2.camera
                    c = p3.camera

                    normal = self.normalize(
                        self.normal(a, b, c)
                    )

                    to_camera = (
                        -a[0],
                        -a[1],
                        -a[2]
                    )

                    if self.dot(normal, to_camera) <= 0:
                        continue

                    a_world = p1.world
                    b_world = p2.world
                    c_world = p3.world

                    normal_world = self.normalize(self.normal(a_world, b_world, c_world))

                    light = self.normalize((-1, 0, -1))
                    brightness = max(0.2, self.dot(normal_world, light))

                    color = (
                        int(210 * brightness),
                        int(210 * brightness),
                        int(210 * brightness)

                    )

                    p1.screen = self.project(*p1.camera, width, height, camera.fov)
                    p2.screen = self.project(*p2.camera, width, height, camera.fov)
                    p3.screen = self.project(*p3.camera, width, height, camera.fov)

                    polygon = [
                        p1.screen,
                        p2.screen,
                        p3.screen
                    ]

                    z_values = (
                        a[2],
                        b[2],
                        c[2]
                    )

                    uv_values = (
                        p1.uv,
                        p2.uv,
                        p3.uv
                    )

                    start = time.perf_counter()

                    self.draw_triangle(
                        screen,
                        pixels,
                        polygon[0],
                        polygon[1],
                        polygon[2],
                        z_values,
                        uv_values,
                        color,
                        depth_buffer,
                        object.mesh.texture,
                        texture_pixels
                        
                    )

                    self.raster_time += time.perf_counter() - start
    
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
    
    def intersect_near(self, v1, v2, near=0.1):
        z1 = v1.camera[2]
        z2 = v2.camera[2]

        t = (near - z1) / (z2 - z1)

        vertex = self.interpolate_vertex(v1, v2, t)

        vertex.camera = (
            vertex.camera[0],
            vertex.camera[1],
            near
        )
    
        return vertex
    
    def clip_triangle_near(self, v1, v2, v3, near=0.1):
        vertices = [v1, v2, v3]
        clipped = []

        for i in range(3):
            current = vertices[i]
            next_vertex = vertices[(i + 1) % 3]

            current_inside = current.camera[2] >= near
            next_inside = next_vertex.camera[2] >= near

            if current_inside:
                clipped.append(current)
            
            if current_inside != next_inside:
                intersection = self.intersect_near(
                    current,
                    next_vertex,
                    near
                )

                clipped.append(intersection)

        if len(clipped) < 3:
            return []
        
        if len(clipped) == 3:
            return [
                (clipped[0], clipped[1], clipped[2])
            ]
        
        if len(clipped) == 4:
            return [
                (clipped[0], clipped[1], clipped[2]),
                (clipped[0], clipped[2], clipped[3])
            ]
        
        return []
        
    def interpolate_vertex(self, v1, v2, t):
        world = (
            v1.world[0] + (v2.world[0] - v1.world[0]) * t,
            v1.world[1] + (v2.world[1] - v1.world[1]) * t,
            v1.world[2] + (v2.world[2] - v1.world[2]) * t
        )

        camera = (
            v1.camera[0] + (v2.camera[0] - v1.camera[0]) * t,
            v1.camera[1] + (v2.camera[1] - v1.camera[1]) * t,
            v1.camera[2] + (v2.camera[2] - v1.camera[2]) * t
        )

        uv = (
            v1.uv[0] + (v2.uv[0] - v1.uv[0]) * t,
            v1.uv[1] + (v2.uv[1] - v1.uv[1]) * t
        )

        return Vertex(world, camera, uv)
    
    def edge(self, a, b, p):
        return ((b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) *(p[0] - a[0]))
    
    def draw_triangle(self, screen, pixels, a, b, c, z_values, uv_values, color, depth_buffer, texture, texture_pixels):
        width = screen.get_width()
        height = screen.get_height()

        texture_width = texture.get_width()
        texture_height = texture.get_height()

        min_x = max(0, min(a[0], b[0], c[0]))
        max_x = min(width - 1, max(a[0], b[0], c[0]))

        min_y = max(0, min(a[1], b[1], c[1]))
        max_y = min(height - 1, max(a[1], b[1], c[1]))

        if min_x > max_x or min_y > max_y:
            return

        area = self.edge(a, b, c)

        if area == 0:
            return

        inv_area = 1.0 / area

        z1, z2, z3 = z_values

        u1, v1 = uv_values[0]
        u2, v2 = uv_values[1]
        u3, v3 = uv_values[2]

        inv_z1 = 1.0 / z1
        inv_z2 = 1.0 / z2
        inv_z3 = 1.0 / z3

        u_z1 = u1 * inv_z1
        u_z2 = u2 * inv_z2
        u_z3 = u3 * inv_z3

        v_z1 = v1 * inv_z1
        v_z2 = v2 * inv_z2
        v_z3 = v3 * inv_z3

        alpha_dx = -(c[1] - b[1])
        beta_dx = -(a[1] - c[1])
        gamma_dx = -(b[1] - a[1])

        alpha_dy = c[0] - b[0]
        beta_dy = a[0] - c[0]
        gamma_dy = b[0] - a[0]

        for y in range(min_y, max_y + 1):
            span = self.triangle_scanline(a, b, c, y)

            if span is None:
                continue

            x_left, x_right = span

            x_start = max(0, int(math.ceil(x_left)))

            x_end = min(width - 1, int(math.floor(x_right)))

            if x_start > x_end:
                continue

            span_width = x_end - x_start + 1

            xs = np.arange(x_start, x_end + 1, dtype=np.float32)

            offsets = np.arange(span_width, dtype=np.float32)

            alpha_start = self.edge(
                b, c, (x_start, y)
            )

            beta_start = self.edge(
                c, a, (x_start, y)
            )

            gamma_start = self.edge(
                a, b, (x_start, y)
            )

            alpha_edge = alpha_start + offsets * alpha_dx
            beta_edge = beta_start + offsets * beta_dx
            gamma_edge = gamma_start + offsets * gamma_dx

            alpha = alpha_edge * inv_area
            beta = beta_edge * inv_area
            gamma = gamma_edge * inv_area

            inside = (
                (alpha >= 0.0) &
                (beta >= 0.0) &
                (gamma >= 0.0)
            )

            if not np.any(inside):
                continue

            inv_z = (
                alpha * inv_z1 +
                beta * inv_z2 +
                gamma * inv_z3
            )

            depth_row = depth_buffer[
                y,
                x_start:x_end + 1
            ]

            visible = (
                inside &
                (inv_z > 0.0) &
                (inv_z > depth_row)
            )

            if not np.any(visible):
                continue

            u_over_z = (
                alpha * u_z1 +
                beta * u_z2 +
                gamma * u_z3
            )

            v_over_z = (
                alpha * v_z1 +
                beta * v_z2 +
                gamma * v_z3
            )

            visible_inv_z = inv_z[visible]

            u = u_over_z[visible] / visible_inv_z
            v = v_over_z[visible] / visible_inv_z

            u = np.mod(u, 1.0)
            v = np.mod(v, 1.0)

            texture_x = (
                u * (texture_width - 1)
            ).astype(np.int32)

            texture_y = (
                v * (texture_height - 1)
            ).astype(np.int32)

            screen_x = xs[visible].astype(np.int32)

            depth_row[visible] = visible_inv_z

            pixels[screen_x, y] = texture_pixels[texture_x, texture_y]

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
        half_size = 8.0

        center_x = object.position[0] + half_size
        center_y = object.position[1]
        center_z = object.position[2] + half_size

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

        radius = 12.0

        if z + radius <= 0:
            return False

        if z - radius <= 0:
            return True

        half_vertical_fov = math.radians(camera.fov) / 2

        vertical_limit = z * math.tan(half_vertical_fov)

        if y - radius > vertical_limit:
            return False

        if y + radius < -vertical_limit:
            return False

        horizontal_limit = vertical_limit * aspect

        if x - radius > horizontal_limit:
            return False

        if x + radius < -horizontal_limit:
            return False

        return True
    
    def scanline_intersection(self, p1, p2, y):
        y1 = p1[1]
        y2 = p2[1]

        if y1 == y2:
            return None

        if y < min(y1, y2) or y >= max(y1, y2):
            return None

        t = (y - y1) / (y2 - y1)

        return p1[0] + (p2[0] - p1[0]) * t
    
    def triangle_scanline(self, a, b, c, y):
        intersections = []

        x = self.scanline_intersection(a, b, y)
        if x is not None:
            intersections.append(x)

        x = self.scanline_intersection(b, c, y)
        if x is not None:
            intersections.append(x)

        x = self.scanline_intersection(c, a, y)
        if x is not None:
            intersections.append(x)

        if len(intersections) < 2:
            return None

        return min(intersections), max(intersections)