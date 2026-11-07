# cython: boundscheck=False, wraparound=False, cdivision=True, initializedcheck=False, language_level=3
"""Свет и жадный меш кубов чанка. Собирается вместе с raster: python build_raster.py

Свет как в оригинале: уровни от 0 до 15. Небесный свет идёт сверху столбом без
потерь через воздух, теряет по единице на листве и воде, а в стороны и под
навесы растекается, теряя единицу за шаг. Свет блоков (факел, светокамень,
горящая печка) растекается так же от источника. В клетке берётся больший из двух.

Меш строится из объёма номеров блоков [x, y, z] с рамкой в одну клетку со всех
сторон: в рамке лежат соседи из других чанков, сам чанк внутри. Для каждой
стороны грани собираются в маску по слоям, и одинаковые соседние клетки маски
склеиваются в прямоугольники. У каждой вершины своя яркость: свет клеток вокруг
неё и затенение углов (ambient occlusion). Склеиваются только клетки, у которых
все четыре угла одной яркости, иначе свет внутри прямоугольника потерялся бы.

Стороны: 0 top (y - 1, ось Y направлена вниз), 1 bottom (y + 1),
2 front (z + 1), 3 back (z - 1), 4 right (x + 1), 5 left (x - 1).
"""
import numpy as np

from libc.stdint cimport int32_t, uint8_t, uint16_t, uint32_t
from libc.stdlib cimport free, malloc, realloc
from libc.string cimport memset

cdef int FIELDS = 7

# Затенение угла по числу непрозрачных соседей у вершины: 3 значит угол открыт.
cdef double AO[4]
AO[:] = [0.5, 0.68, 0.84, 1.0]

cdef enum:
    MAX_LIGHT = 15


# Свет.

cdef struct Buckets:
    int32_t* items[MAX_LIGHT + 1]
    Py_ssize_t count[MAX_LIGHT + 1]
    Py_ssize_t capacity[MAX_LIGHT + 1]


cdef bint push(Buckets* buckets, int level, int32_t index) noexcept nogil:
    cdef Py_ssize_t capacity
    cdef int32_t* grown

    if buckets.count[level] == buckets.capacity[level]:
        capacity = buckets.capacity[level] * 2 if buckets.capacity[level] else 1024
        grown = <int32_t*>realloc(buckets.items[level], capacity * sizeof(int32_t))

        if grown == NULL:
            return False

        buckets.items[level] = grown
        buckets.capacity[level] = capacity

    buckets.items[level][buckets.count[level]] = index
    buckets.count[level] += 1
    return True


cdef int spread(uint8_t* level, const uint16_t* ids, const uint8_t* opacity, int sx, int sy, int sz) noexcept nogil:
    """Растекание света от ярких клеток к тёмным. Возвращает -1, если не хватило памяти.

    Свет только убывает, поэтому клетки обрабатываются по уровням от 15 вниз
    (по корзинам), и каждая клетка получает окончательный уровень с первого раза.
    """
    cdef Buckets buckets
    cdef Py_ssize_t n = <Py_ssize_t>sx * sy * sz
    cdef Py_ssize_t i, k
    cdef int l, nl, op, x, y, z, side, result = 0
    cdef int32_t index, neighbour
    cdef int layer = sy * sz

    memset(&buckets, 0, sizeof(Buckets))

    for i in range(n):
        if level[i] > 1 and not push(&buckets, level[i], <int32_t>i):
            result = -1

    if result == 0:
        for l in range(MAX_LIGHT, 1, -1):
            k = 0

            # Сюда кладутся только клетки слабее l, так что корзина l не растёт.
            while k < buckets.count[l]:
                index = buckets.items[l][k]
                k += 1

                if level[index] != l:
                    continue

                x = index / layer
                y = (index % layer) / sz
                z = index % sz

                for side in range(6):
                    if side == 0:
                        if x == 0:
                            continue
                        neighbour = index - layer
                    elif side == 1:
                        if x == sx - 1:
                            continue
                        neighbour = index + layer
                    elif side == 2:
                        if y == 0:
                            continue
                        neighbour = index - sz
                    elif side == 3:
                        if y == sy - 1:
                            continue
                        neighbour = index + sz
                    elif side == 4:
                        if z == 0:
                            continue
                        neighbour = index - 1
                    else:
                        if z == sz - 1:
                            continue
                        neighbour = index + 1

                    op = opacity[ids[neighbour]]

                    if op >= MAX_LIGHT:
                        continue

                    nl = l - (op if op > 1 else 1)

                    if nl > level[neighbour]:
                        level[neighbour] = nl

                        if nl > 1 and not push(&buckets, nl, neighbour):
                            result = -1

    for l in range(MAX_LIGHT + 1):
        free(buckets.items[l])

    return result


def compute_light(const uint16_t[:, :, ::1] ids, const uint8_t[::1] opacity, const uint8_t[::1] emission):
    """Свет для объёма [x, y, z], y = 0 сверху. Выше объёма открытое небо.

    В каждом байте два уровня 0..15: младшие четыре бита небесный свет, старшие
    свет блоков. Небесный нужен отдельно: по нему темнеет туман в пещерах.

    За боковыми краями объёма света нет, поэтому точным свет выходит только
    в середине, дальше 15 клеток от краёв. Для чанка берут его и восемь соседей.
    """
    cdef int sx = ids.shape[0], sy = ids.shape[1], sz = ids.shape[2]
    sky_array = np.zeros((sx, sy, sz), dtype=np.uint8)
    block_array = np.zeros((sx, sy, sz), dtype=np.uint8)
    cdef uint8_t[:, :, ::1] sky = sky_array
    cdef uint8_t[:, :, ::1] block = block_array
    cdef int x, y, z, op, level, failed

    with nogil:
        for x in range(sx):
            for z in range(sz):
                level = MAX_LIGHT

                for y in range(sy):
                    op = opacity[ids[x, y, z]]

                    if op >= MAX_LIGHT:
                        level = 0
                    elif level > op:
                        level -= op
                    else:
                        level = 0

                    sky[x, y, z] = level
                    block[x, y, z] = emission[ids[x, y, z]]

        failed = spread(&sky[0, 0, 0], &ids[0, 0, 0], &opacity[0], sx, sy, sz)
        failed |= spread(&block[0, 0, 0], &ids[0, 0, 0], &opacity[0], sx, sy, sz)

    if failed:
        raise MemoryError("не хватило памяти на расчёт света")

    return sky_array | (block_array << 4)


# Меш.

cdef inline int face_texture(
    const uint16_t[:, :, ::1] ids,
    int x, int y, int z,
    int dx, int dy, int dz,
    int face,
    const uint8_t[::1] cube,
    const uint8_t[::1] opaque,
    const int32_t[::1] kind,
    const int32_t[:, ::1] face_tex
) noexcept nogil:
    """Текстура видимой грани блока в клетке или -1, если грани нет."""
    cdef uint16_t block = ids[x, y, z]

    if not cube[block]:
        return -1

    cdef uint16_t neighbour = ids[x + dx, y + dy, z + dz]

    # Непрозрачный сосед закрывает грань. Одинаковые прозрачные кубы тоже
    # закрывают друг друга, иначе стекло было бы в сетке изнутри.
    if opaque[neighbour] or (cube[neighbour] and kind[neighbour] == kind[block]):
        return -1

    return face_tex[block, face]


cdef inline uint32_t corner_shades(
    const uint16_t[:, :, ::1] ids,
    const uint8_t[:, :, ::1] light,
    const uint8_t[::1] opaque,
    const double* brightness,
    double face_shade,
    int fx, int fy, int fz,
    int ax, int ay, int az,
    int bx, int by, int bz,
    bint smooth
) noexcept nogil:
    """Яркости четырёх углов грани, по байту на угол: (0,0), (1,0), (1,1), (0,1) по осям a и b.

    (fx, fy, fz) это клетка перед гранью, a и b это направления вдоль грани.
    """
    cdef double own = brightness[light[fx, fy, fz]]
    cdef uint32_t packed = 0, value
    cdef int corner, sa, sb, s1, s2, c, ao, count
    cdef double total
    cdef int x1, y1, z1, x2, y2, z2, x3, y3, z3

    if not smooth:
        value = <uint32_t>(own * face_shade * 255.0 + 0.5)
        return value | (value << 8) | (value << 16) | (value << 24)

    for corner in range(4):
        sa = 1 if corner == 1 or corner == 2 else -1
        sb = 1 if corner >= 2 else -1

        x1, y1, z1 = fx + sa * ax, fy + sa * ay, fz + sa * az
        x2, y2, z2 = fx + sb * bx, fy + sb * by, fz + sb * bz
        x3, y3, z3 = x1 + sb * bx, y1 + sb * by, z1 + sb * bz

        s1 = opaque[ids[x1, y1, z1]]
        s2 = opaque[ids[x2, y2, z2]]
        c = opaque[ids[x3, y3, z3]]

        total = own
        count = 1

        if s1 and s2:
            ao = 0
        else:
            ao = 3 - s1 - s2 - c

            if not c:
                total += brightness[light[x3, y3, z3]]
                count += 1

        if not s1:
            total += brightness[light[x1, y1, z1]]
            count += 1

        if not s2:
            total += brightness[light[x2, y2, z2]]
            count += 1

        value = <uint32_t>(total / count * face_shade * AO[ao] * 255.0 + 0.5)
        packed |= value << (8 * corner)

    return packed


cdef inline bint uniform(uint32_t packed) noexcept nogil:
    return packed == (packed & 0xFF) * 0x01010101


def greedy_quads(
    const uint16_t[:, :, ::1] ids,
    const uint8_t[:, :, ::1] light,
    const uint8_t[::1] cube,
    const uint8_t[::1] opaque,
    const int32_t[::1] kind,
    const int32_t[:, ::1] face_tex,
    const double[::1] brightness,
    const double[::1] face_shade,
    bint smooth
):
    """Прямоугольники граней и яркости их углов.

    Возвращает массив (n, 7) из face, fixed, a, b, size_a, size_b, texture и
    массив (n, 4) uint8 с яркостями углов (0,0), (1,0), (1,1), (0,1) по a и b.
    light: свет той же формы, что ids, как его отдаёт compute_light. brightness:
    яркость каждого значения байта света (256 штук), face_shade: множитель
    стороны (верх светлее боков, низ темнее всех).

    Координаты внутренние, без рамки. Для top и bottom fixed это y, a это x, b это z.
    Для front и back fixed это z, a это x, b это y. Для right и left fixed это x,
    a это z, b это y.
    """
    if light.shape[0] != ids.shape[0] or light.shape[1] != ids.shape[1] or light.shape[2] != ids.shape[2]:
        raise ValueError("light must have the same shape as ids")

    if brightness.shape[0] != 256:
        raise ValueError("brightness must have a value for every light byte")

    cdef int size_x = ids.shape[0] - 2
    cdef int size_y = ids.shape[1] - 2
    cdef int size_z = ids.shape[2] - 2

    cdef int largest = max(size_x, size_z) * max(size_x, size_y, size_z)
    mask_array = np.empty(largest, dtype=np.int32)
    shade_array = np.empty(largest, dtype=np.uint32)
    used_array = np.empty(largest, dtype=np.uint8)
    cdef int32_t[::1] mask = mask_array
    cdef uint32_t[::1] shades = shade_array
    cdef uint8_t[::1] used = used_array

    capacity = 1024
    result = np.empty((capacity, FIELDS), dtype=np.int32)
    corners = np.empty((capacity, 4), dtype=np.uint8)
    cdef int32_t[:, ::1] out = result
    cdef uint8_t[:, ::1] out_corners = corners
    cdef int count = 0

    cdef int face, fixed, slices, size_a, size_b
    cdef int a, b, da, db, width, height, texture, x, y, z, cell, other
    cdef int dx, dy, dz, ax, ay, az, bx, by, bz
    cdef uint32_t packed
    cdef bint expand, any_face

    for face in range(6):
        dx = dy = dz = 0

        if face == 0:
            dy = -1
        elif face == 1:
            dy = 1
        elif face == 2:
            dz = 1
        elif face == 3:
            dz = -1
        elif face == 4:
            dx = 1
        else:
            dx = -1

        # Оси a и b в объёме: те же, что у координат прямоугольника.
        if face < 2:
            slices, size_a, size_b = size_y, size_x, size_z
            ax, ay, az, bx, by, bz = 1, 0, 0, 0, 0, 1
        elif face < 4:
            slices, size_a, size_b = size_z, size_x, size_y
            ax, ay, az, bx, by, bz = 1, 0, 0, 0, 1, 0
        else:
            slices, size_a, size_b = size_x, size_z, size_y
            ax, ay, az, bx, by, bz = 0, 0, 1, 0, 1, 0

        for fixed in range(slices):
            any_face = False

            for b in range(size_b):
                for a in range(size_a):
                    if face < 2:
                        x, y, z = a, fixed, b
                    elif face < 4:
                        x, y, z = a, b, fixed
                    else:
                        x, y, z = fixed, b, a

                    texture = face_texture(ids, x + 1, y + 1, z + 1, dx, dy, dz, face, cube, opaque, kind, face_tex)
                    cell = a * size_b + b
                    mask[cell] = texture

                    if texture >= 0:
                        any_face = True
                        shades[cell] = corner_shades(
                            ids, light, opaque, &brightness[0], face_shade[face],
                            x + 1 + dx, y + 1 + dy, z + 1 + dz,
                            ax, ay, az, bx, by, bz, smooth
                        )

            if not any_face:
                continue

            memset(&used[0], 0, size_a * size_b)

            for b in range(size_b):
                for a in range(size_a):
                    cell = a * size_b + b
                    texture = mask[cell]

                    if texture < 0 or used[cell]:
                        continue

                    packed = shades[cell]
                    width = 1
                    height = 1

                    # Клетку с разной яркостью углов склеивать нельзя: свет внутри потеряется.
                    if uniform(packed):
                        while a + width < size_a:
                            other = (a + width) * size_b + b

                            if used[other] or mask[other] != texture or shades[other] != packed:
                                break

                            width += 1

                        while b + height < size_b:
                            expand = True

                            for da in range(width):
                                other = (a + da) * size_b + b + height

                                if used[other] or mask[other] != texture or shades[other] != packed:
                                    expand = False
                                    break

                            if not expand:
                                break

                            height += 1

                    for db in range(height):
                        for da in range(width):
                            used[(a + da) * size_b + b + db] = 1

                    if count == capacity:
                        capacity *= 2
                        result = np.resize(result, (capacity, FIELDS))
                        corners = np.resize(corners, (capacity, 4))
                        out = result
                        out_corners = corners

                    out[count, 0] = face
                    out[count, 1] = fixed
                    out[count, 2] = a
                    out[count, 3] = b
                    out[count, 4] = width
                    out[count, 5] = height
                    out[count, 6] = texture

                    out_corners[count, 0] = packed & 0xFF
                    out_corners[count, 1] = (packed >> 8) & 0xFF
                    out_corners[count, 2] = (packed >> 16) & 0xFF
                    out_corners[count, 3] = (packed >> 24) & 0xFF
                    count += 1

    return result[:count], corners[:count]
