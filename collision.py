"""Столкновения тела игрока с блоками. Ось Y направлена вниз, глаза стоят в camera.position."""
import math

HALF_WIDTH = 0.3
HEAD = 0.18
FEET = 1.62

# Зазор до грани. Без него округление оставит коробку на волосок внутри стены,
# и скольжение вдоль неё будет цепляться за блоки.
GAP = 0.001

# Допуск при сравнении с краем коробки, которая уже остановлена на GAP от грани.
EPSILON = 1e-9


def player_box(position):
    x, y, z = position

    return (
        (x - HALF_WIDTH, y - HEAD, z - HALF_WIDTH),
        (x + HALF_WIDTH, y + FEET, z + HALF_WIDTH)
    )


def box_touches_block(position, block_position):
    low, high = player_box(position)

    return all(
        low[axis] < block_position[axis] + 1 and high[axis] > block_position[axis]
        for axis in range(3)
    )


def move_axis(world, position, axis, delta, box=player_box):
    """Двигает коробку вдоль оси и возвращает новую координату глаз.

    Проверяются все слои блоков на пути, поэтому большой шаг за кадр не проскочит
    сквозь стену. Мешает не вся клетка, а коробка блока: у двери это тонкая створка.
    Блоки, в которых коробка уже стоит, не мешают из них выйти.
    box(position) даёт коробку тела: у игрока player_box, у мобов своя.
    """
    if delta == 0:
        return position[axis]

    low, high = box(position)

    first_axis, second_axis = (other for other in range(3) if other != axis)

    # Забор выше своей клетки на полблока: по высоте смотрим и на клетку под телом.
    first_cells = range(math.floor(low[first_axis]), math.ceil(high[first_axis]) + (first_axis == 1))
    second_cells = range(math.floor(low[second_axis]), math.ceil(high[second_axis]) + (second_axis == 1))

    # Клетка, в которой сейчас край коробки, тоже нужна: в ней может стоять створка.
    if delta > 0:
        edge = high[axis]
        layers = range(math.floor(edge), math.floor(edge + delta + GAP) + 1 + (axis == 1))
    else:
        edge = low[axis]
        layers = range(math.floor(edge), math.floor(edge + delta - GAP) - 1, -1)

    allowed = delta
    cell = [0, 0, 0]

    for layer in layers:
        cell[axis] = layer

        for first in first_cells:
            cell[first_axis] = first

            for second in second_cells:
                cell[second_axis] = second

                block = world.get_block(*cell)

                if block is None or not block.is_solid:
                    continue

                for box_low, box_high in block.boxes(world, tuple(cell)):
                    box_low = [cell[index] + box_low[index] for index in range(3)]
                    box_high = [cell[index] + box_high[index] for index in range(3)]

                    overlaps = all(
                        box_low[other] < high[other] and box_high[other] > low[other]
                        for other in (first_axis, second_axis)
                    )

                    if not overlaps:
                        continue

                    if delta > 0 and box_low[axis] >= edge - EPSILON:
                        allowed = min(allowed, box_low[axis] - GAP - edge)

                    elif delta < 0 and box_high[axis] <= edge + EPSILON:
                        allowed = max(allowed, box_high[axis] + GAP - edge)

    return position[axis] + allowed


def move(world, position, delta, box=player_box):
    """Двигает по осям отдельно: упор в стену гасит только одну ось, по другим едем дальше."""
    position = list(position)

    for axis in (0, 2, 1):
        position[axis] = move_axis(world, position, axis, delta[axis], box)

    return tuple(position)


# Опора под ногами ищется не глубже этого: так в оригинале работает подкрадывание.
SUPPORT_DEPTH = 0.6


def box_touches_blocks(world, low, high):
    """Задевает ли коробка от low до high коробку хоть одного блока."""
    for x in range(math.floor(low[0]), math.ceil(high[0])):
        for y in range(math.floor(low[1]), math.ceil(high[1]) + 1):
            for z in range(math.floor(low[2]), math.ceil(high[2])):
                block = world.get_block(x, y, z)

                if block is None or not block.is_solid:
                    continue

                cell = (x, y, z)

                for box_low, box_high in block.boxes(world, cell):
                    if all(
                        cell[axis] + box_low[axis] < high[axis] and cell[axis] + box_high[axis] > low[axis]
                        for axis in range(3)
                    ):
                        return True

    return False


def has_support(world, position, dx, dz):
    """Будет ли опора под ногами после шага (dx, dz): коробку опускаем на SUPPORT_DEPTH."""
    x, y, z = position
    low, high = player_box((x + dx, y + SUPPORT_DEPTH, z + dz))

    return box_touches_blocks(world, low, high)
