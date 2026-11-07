# cython: language_level=3, boundscheck=False, wraparound=False, cdivision=True, initializedcheck=False
"""Программный растеризатор: near-клиппинг, отсечение задних граней и заливка.

Прозрачность сделана альфа-тестом: тексель с альфой меньше половины не пишет
ни цвет, ни глубину. Сквозь такие дыры видно всё, что за ними, поэтому
сортировать треугольники не нужно.

Полупрозрачность (вода) рисуется отдельным проходом после всего непрозрачного:
с opacity меньше 256 тексель смешивается с тем, что уже на экране, а глубину
не пишет. Так видно и дно под водой, и вторую стенку воды за первой.

Свет: у каждой вершины может быть своя яркость от 0 до 1. Она интерполируется
по треугольнику так же перспективно-корректно, как UV, и умножает цвет текселя.

Алгоритм тот же, что был на numpy, но весь меш обрабатывается одним вызовом
без участия интерпретатора Python. После правок: python build_raster.py
"""

from libc.math cimport floor
from libc.stdint cimport int32_t, int64_t, uint8_t, uint32_t

# Тексель с альфой ниже порога считается дыркой.
# Вершины на экране хранятся с точностью до 1/SUBPIXEL пикселя: если округлять их
# до целых пикселей, на стыке большой грани с несколькими маленькими
# (T-образный стык) остаются щели в пиксель, сквозь которые видно небо.
cdef enum:
    ALPHA_THRESHOLD = 128
    SUBPIXEL = 256


cdef struct Vertex:
    # l: яркость вершины от 0 до 1.
    double x, y, z, u, v, l


cdef struct Target:
    char* pixels
    Py_ssize_t pitch
    float* depth
    int width, height
    const uint32_t* texture
    # NULL у непрозрачных текстур: тогда альфу не проверяем вовсе.
    const uint8_t* alpha
    int texture_width, texture_height
    double focal
    # 256 значит непрозрачно, меньше: доля цвета текстуры в 1/256.
    int opacity
    # Есть ли у вершин яркость. Без неё тексель пишется как есть.
    bint shaded
    # Биты альфы экрана: после затемнения их надо выставить заново.
    uint32_t alpha_mask


cdef inline int64_t floor_div(int64_t a, int64_t b) noexcept nogil:
    # Деление с округлением вниз при b > 0. В C оно округляет к нулю.
    cdef int64_t q = a / b
    if a % b != 0 and a < 0:
        q -= 1
    return q


cdef inline uint32_t blend(uint32_t source, uint32_t target, uint32_t amount) noexcept nogil:
    # Смешивает все четыре байта пикселя сразу, по два за умножение.
    cdef uint32_t keep = 256 - amount
    cdef uint32_t even = (((source & 0x00FF00FF) * amount + (target & 0x00FF00FF) * keep) >> 8) & 0x00FF00FF
    cdef uint32_t odd = ((((source >> 8) & 0x00FF00FF) * amount + ((target >> 8) & 0x00FF00FF) * keep) >> 8) & 0x00FF00FF
    return even | (odd << 8)


cdef inline uint32_t darken(uint32_t color, uint32_t amount, uint32_t alpha_mask) noexcept nogil:
    # Умножает каналы на amount / 256, тоже по два за умножение.
    cdef uint32_t even = (((color & 0x00FF00FF) * amount) >> 8) & 0x00FF00FF
    cdef uint32_t odd = (((color >> 8) & 0x00FF00FF) * amount) & 0xFF00FF00U
    return even | odd | alpha_mask


cdef inline Vertex clip_edge(const Vertex* a, const Vertex* b, double near) noexcept nogil:
    cdef double t = (near - a.z) / (b.z - a.z)
    cdef Vertex r
    r.x = a.x + (b.x - a.x) * t
    r.y = a.y + (b.y - a.y) * t
    r.z = near
    r.u = a.u + (b.u - a.u) * t
    r.v = a.v + (b.v - a.v) * t
    r.l = a.l + (b.l - a.l) * t
    return r


cdef void fill_triangle(const Target* t, const Vertex* a, const Vertex* b, const Vertex* c) noexcept nogil:
    cdef double half_w = t.width / 2.0
    cdef double half_h = t.height / 2.0

    # Координаты в долях пикселя. Пиксель (x, y) закрашивается, если его центр
    # (x + 1/2, y + 1/2) внутри треугольника или на ребре.
    cdef int64_t ax = <int64_t>floor((a.x / a.z * t.focal + half_w) * SUBPIXEL + 0.5)
    cdef int64_t ay = <int64_t>floor((a.y / a.z * t.focal + half_h) * SUBPIXEL + 0.5)
    cdef int64_t bx = <int64_t>floor((b.x / b.z * t.focal + half_w) * SUBPIXEL + 0.5)
    cdef int64_t by = <int64_t>floor((b.y / b.z * t.focal + half_h) * SUBPIXEL + 0.5)
    cdef int64_t cx = <int64_t>floor((c.x / c.z * t.focal + half_w) * SUBPIXEL + 0.5)
    cdef int64_t cy = <int64_t>floor((c.y / c.z * t.focal + half_h) * SUBPIXEL + 0.5)
    cdef int64_t half = SUBPIXEL / 2

    cdef int64_t area = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
    if area == 0:
        return

    # Приводим обход к одному направлению, чтобы внутри все рёбра были >= 0.
    cdef const Vertex* swap_v
    cdef int64_t swap_i
    if area < 0:
        swap_v = b; b = c; c = swap_v
        swap_i = bx; bx = cx; cx = swap_i
        swap_i = by; by = cy; cy = swap_i
        area = -area

    # Рамка в целых пикселях. Точные границы заливки потом считаются по рёбрам.
    cdef int64_t top = floor_div(min(ay, by, cy), SUBPIXEL)
    cdef int64_t bottom = floor_div(max(ay, by, cy), SUBPIXEL) + 1
    cdef int64_t left = floor_div(min(ax, bx, cx), SUBPIXEL)
    cdef int64_t right = floor_div(max(ax, bx, cx), SUBPIXEL)

    if top < 0:
        top = 0
    if bottom > t.height:
        bottom = t.height
    if left < 0:
        left = 0
    if right > t.width - 1:
        right = t.width - 1
    if left > right:
        return

    # 1/z, u/z и v/z линейны в экранных координатах (это и есть
    # перспективно-корректная интерполяция), поэтому вдоль строки их можно
    # не считать заново, а прибавлять постоянный шаг.
    cdef double inv_area = 1.0 / <double>area
    cdef double iz1 = 1.0 / a.z
    cdef double iz2 = 1.0 / b.z
    cdef double iz3 = 1.0 / c.z
    cdef double uz1 = a.u * iz1
    cdef double uz2 = b.u * iz2
    cdef double uz3 = c.u * iz3
    cdef double vz1 = a.v * iz1
    cdef double vz2 = b.v * iz2
    cdef double vz3 = c.v * iz3
    # Яркость в 1/256, деленная на z, как u и v.
    cdef double lz1 = a.l * 256.0 * iz1
    cdef double lz2 = b.l * 256.0 * iz2
    cdef double lz3 = c.l * 256.0 * iz3

    # Функция ребра E(x, y) = dx_coef * x + (её значение при x = 0).
    cdef int64_t e0_dx = by - cy
    cdef int64_t e1_dx = cy - ay
    cdef int64_t e2_dx = ay - by
    cdef int64_t e0_dy = cx - bx
    cdef int64_t e1_dy = ax - cx
    cdef int64_t e2_dy = bx - ax

    # Шаг на один пиксель вправо: SUBPIXEL долей.
    cdef double alpha_dx = e0_dx * SUBPIXEL * inv_area
    cdef double beta_dx = e1_dx * SUBPIXEL * inv_area
    cdef double gamma_dx = e2_dx * SUBPIXEL * inv_area
    cdef double iz_dx = alpha_dx * iz1 + beta_dx * iz2 + gamma_dx * iz3
    cdef double uz_dx = alpha_dx * uz1 + beta_dx * uz2 + gamma_dx * uz3
    cdef double vz_dx = alpha_dx * vz1 + beta_dx * vz2 + gamma_dx * vz3
    cdef double lz_dx = alpha_dx * lz1 + beta_dx * lz2 + gamma_dx * lz3

    # Каждому текселю достаётся равная доля [0, 1). Раньше множителем была
    # ширина минус один, и последний столбец и строка почти не рисовались.
    cdef int tex_w = t.texture_width
    cdef int tex_h = t.texture_height
    cdef const uint32_t* texture = t.texture
    cdef const uint8_t* texture_alpha = t.alpha
    cdef uint32_t opacity = <uint32_t>t.opacity
    cdef bint translucent = t.opacity < 256
    cdef bint shaded = t.shaded
    cdef uint32_t alpha_mask = t.alpha_mask
    cdef uint32_t color
    cdef int tu, tv, texel, light

    cdef int64_t y, x, x_start, x_end, e0, e1, e2, limit
    cdef int64_t coef[3]
    cdef int64_t rest[3]
    cdef int k
    cdef double alpha, beta, gamma, iz, uz, vz, lz, w, u, v
    cdef float depth_value
    cdef float* depth_row
    cdef uint32_t* pixel_row

    cdef int64_t sample_y

    for y in range(top, bottom):
        # Значения рёбер в центре пикселя x = 0 этой строки и их шаг на пиксель.
        sample_y = y * SUBPIXEL + half
        rest[0] = e0_dy * (sample_y - by) + e0_dx * (half - bx)
        rest[1] = e1_dy * (sample_y - cy) + e1_dx * (half - cx)
        rest[2] = e2_dy * (sample_y - ay) + e2_dx * (half - ax)
        coef[0] = e0_dx * SUBPIXEL
        coef[1] = e1_dx * SUBPIXEL
        coef[2] = e2_dx * SUBPIXEL

        # Границы заливки считаем точно из неравенств E(x) >= 0. Поэтому
        # внутри цикла по пикселям проверка "точка в треугольнике" не нужна.
        x_start = left
        x_end = right
        for k in range(3):
            if coef[k] > 0:
                limit = -floor_div(rest[k], coef[k])
                if limit > x_start:
                    x_start = limit
            elif coef[k] < 0:
                limit = floor_div(rest[k], -coef[k])
                if limit < x_end:
                    x_end = limit
            elif rest[k] < 0:
                x_end = x_start - 1

        if x_start > x_end:
            continue

        e0 = rest[0] + coef[0] * x_start
        e1 = rest[1] + coef[1] * x_start
        e2 = rest[2] + coef[2] * x_start

        alpha = e0 * inv_area
        beta = e1 * inv_area
        gamma = e2 * inv_area

        iz = alpha * iz1 + beta * iz2 + gamma * iz3
        uz = alpha * uz1 + beta * uz2 + gamma * uz3
        vz = alpha * vz1 + beta * vz2 + gamma * vz3
        lz = alpha * lz1 + beta * lz2 + gamma * lz3

        depth_row = t.depth + y * t.width
        pixel_row = <uint32_t*>(t.pixels + y * t.pitch)

        for x in range(x_start, x_end + 1):
            depth_value = <float>iz

            if depth_value > depth_row[x]:
                w = 1.0 / iz
                u = uz * w
                v = vz * w
                u -= floor(u)
                v -= floor(v)

                # u - floor(u) у крошечного отрицательного u округляется до 1.0.
                tu = <int>(u * tex_w)
                tv = <int>(v * tex_h)
                if tu >= tex_w:
                    tu = tex_w - 1
                if tv >= tex_h:
                    tv = tex_h - 1

                texel = tv * tex_w + tu
                color = texture[texel]

                if shaded:
                    light = <int>(lz * w)

                    if light < 0:
                        light = 0
                    elif light > 256:
                        light = 256

                    color = darken(color, light, alpha_mask)

                if translucent:
                    pixel_row[x] = blend(color, pixel_row[x], opacity)

                elif texture_alpha == NULL or texture_alpha[texel] >= ALPHA_THRESHOLD:
                    depth_row[x] = depth_value
                    pixel_row[x] = color

            iz += iz_dx
            uz += uz_dx
            vz += vz_dx
            lz += lz_dx


def draw_mesh(
    const float[:, ::1] points,
    const int32_t[:, ::1] triangles,
    const float[:, :, ::1] uvs,
    const uint32_t[:, ::1] texture,
    uint32_t[:, :] pixels,
    float[:, ::1] depth,
    double focal,
    double near,
    const uint8_t[:, ::1] alpha=None,
    int opacity=256,
    const float[::1] shades=None,
    double brightness=1.0,
    uint32_t alpha_mask=0
):
    """Рисует меш. points уже в пространстве камеры. Возвращает число треугольников.

    alpha: маска прозрачности той же формы, что texture, или None у непрозрачной.
    opacity: меньше 256 для полупрозрачного меша (глубину он не пишет).
    shades: яркость каждой точки от 0 до 1 или None. brightness: множитель всего
    меша, например для предмета в тёмной пещере. alpha_mask: биты альфы экрана.
    """
    if shades is not None and shades.shape[0] != points.shape[0]:
        raise ValueError("shades must have one value per point")

    if pixels.strides[1] != sizeof(uint32_t):
        raise ValueError("pixels must have contiguous rows")

    if alpha is not None and (alpha.shape[0] != texture.shape[0] or alpha.shape[1] != texture.shape[1]):
        raise ValueError("alpha must have the same shape as texture")

    cdef Target target
    target.pixels = <char*>&pixels[0, 0]
    target.pitch = pixels.strides[0]
    target.depth = &depth[0, 0]
    target.width = pixels.shape[1]
    target.height = pixels.shape[0]
    target.texture = &texture[0, 0]
    target.alpha = NULL

    if alpha is not None:
        target.alpha = &alpha[0, 0]
    target.texture_width = texture.shape[1]
    target.texture_height = texture.shape[0]
    target.focal = focal
    target.opacity = max(0, min(256, opacity))
    target.shaded = shades is not None or brightness != 1.0
    target.alpha_mask = alpha_mask

    cdef bint per_point = shades is not None

    cdef Py_ssize_t i, count = triangles.shape[0]
    cdef int k, n, inside, drawn = 0
    cdef int32_t index
    cdef Vertex tri[3]
    cdef Vertex clipped[4]
    cdef double abx, aby, abz, acx, acy, acz, nx, ny, nz
    cdef const Vertex* current
    cdef const Vertex* following

    with nogil:
        for i in range(count):
            inside = 0

            for k in range(3):
                index = triangles[i, k]
                tri[k].x = points[index, 0]
                tri[k].y = points[index, 1]
                tri[k].z = points[index, 2]
                tri[k].u = uvs[i, k, 0]
                tri[k].v = uvs[i, k, 1]
                tri[k].l = shades[index] * brightness if per_point else brightness

                if tri[k].z >= near:
                    inside += 1

            if inside == 0:
                continue

            # Задняя грань: нормаль смотрит от камеры (сама камера в начале координат).
            abx = tri[1].x - tri[0].x
            aby = tri[1].y - tri[0].y
            abz = tri[1].z - tri[0].z
            acx = tri[2].x - tri[0].x
            acy = tri[2].y - tri[0].y
            acz = tri[2].z - tri[0].z

            nx = aby * acz - abz * acy
            ny = abz * acx - abx * acz
            nz = abx * acy - aby * acx

            if nx * tri[0].x + ny * tri[0].y + nz * tri[0].z >= 0.0:
                continue

            drawn += 1

            if inside == 3:
                fill_triangle(&target, &tri[0], &tri[1], &tri[2])
                continue

            # Отсечение по ближней плоскости: выходит 3 или 4 вершины.
            n = 0
            for k in range(3):
                current = &tri[k]
                following = &tri[(k + 1) % 3]

                if current.z >= near:
                    clipped[n] = current[0]
                    n += 1

                if (current.z >= near) != (following.z >= near):
                    clipped[n] = clip_edge(current, following, near)
                    n += 1

            fill_triangle(&target, &clipped[0], &clipped[1], &clipped[2])

            if n == 4:
                fill_triangle(&target, &clipped[0], &clipped[2], &clipped[3])

    return drawn


def apply_fog(
    uint32_t[:, :] pixels,
    const float[:, ::1] depth,
    int shift_r,
    int shift_g,
    int shift_b,
    int fog_r,
    int fog_g,
    int fog_b,
    double start,
    double end,
    uint32_t alpha_mask=0
):
    """Линейный туман: дальше start цвет пикселя тянется к цвету тумана, после end он весь в тумане.

    Расстояние берётся из буфера глубины (там 1/z). Пиксели с нулевой глубиной это
    небо: их не трогаем. shift_* это сдвиги каналов в формате пикселей экрана.
    alpha_mask: биты альфы этого формата. Их надо выставить, иначе на экране
    с альфа-каналом затуманенный пиксель станет прозрачным и выйдет чёрным.
    """
    if pixels.shape[0] != depth.shape[0] or pixels.shape[1] != depth.shape[1]:
        raise ValueError("pixels and depth must have the same shape")

    cdef Py_ssize_t height = pixels.shape[0], width = pixels.shape[1]
    cdef Py_ssize_t y, x
    cdef float inverse
    cdef double distance, span = end - start
    cdef int amount, keep, r, g, b
    cdef uint32_t pixel
    cdef uint32_t fog = (
        (<uint32_t>fog_r << shift_r) | (<uint32_t>fog_g << shift_g) | (<uint32_t>fog_b << shift_b) | alpha_mask
    )

    # Ближе start тумана нет: в 1/z это граница сверху.
    cdef float near_limit = <float>(1.0 / start) if start > 0 else 1e30
    cdef float far_limit = <float>(1.0 / end)

    if span <= 0:
        span = 1e-6

    with nogil:
        for y in range(height):
            for x in range(width):
                inverse = depth[y, x]

                if inverse <= 0 or inverse >= near_limit:
                    continue

                if inverse <= far_limit:
                    pixels[y, x] = fog
                    continue

                distance = 1.0 / inverse
                # Доля тумана в 1/256, чтобы смешивать целыми числами.
                amount = <int>((distance - start) / span * 256.0)
                keep = 256 - amount

                pixel = pixels[y, x]
                r = (pixel >> shift_r) & 0xFF
                g = (pixel >> shift_g) & 0xFF
                b = (pixel >> shift_b) & 0xFF

                r = (r * keep + fog_r * amount) >> 8
                g = (g * keep + fog_g * amount) >> 8
                b = (b * keep + fog_b * amount) >> 8

                pixels[y, x] = (
                    (<uint32_t>r << shift_r) | (<uint32_t>g << shift_g) | (<uint32_t>b << shift_b) | alpha_mask
                )
