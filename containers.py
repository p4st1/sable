"""Содержимое сундуков и печек. Хранится в мире по координатам блока.

Печка работает в реальном времени: пока горит топливо и есть что плавить,
каждые SMELT_TIME секунд один предмет из входа превращается в результат.
"""
from items import Stack, max_stack, slots_from_json, slots_to_json

CHEST_SIZE = 27

SMELT_TIME = 10.0

# Сколько секунд горит единица топлива.
FUEL = {
    "oak_planks": 15.0,
    "oak_log": 15.0,
    "crafting_table": 15.0,
    "chest": 15.0,
    "stick": 5.0,
    "charcoal": 80.0,
    "coal": 80.0,
    "birch_planks": 15.0,
    "birch_log": 15.0,
    "spruce_planks": 15.0,
    "spruce_log": 15.0,
    "wooden_pickaxe": 10.0,
    "wooden_axe": 10.0,
    "wooden_shovel": 10.0,
    "wooden_sword": 10.0,
    # Ведро лавы горит дольше всего, а пустое ведро остаётся в печке.
    "lava_bucket": 1000.0,
}

SMELTING = {
    "sand": "glass",
    "clay_ball": "brick",
    "cobblestone": "stone",
    "oak_log": "charcoal",
    "birch_log": "charcoal",
    "spruce_log": "charcoal",
    "iron_ore": "iron_ingot",
    "gold_ore": "gold_ingot",
    "porkchop": "cooked_porkchop",
    "beef": "cooked_beef",
}

INPUT, FUEL_SLOT, OUTPUT = 0, 1, 2


class Chest:
    kind = "chest"

    def __init__(self, slots=None):
        self.slots = slots if slots is not None else [None] * CHEST_SIZE

    def to_json(self):
        return {"slots": slots_to_json(self.slots)}

    @classmethod
    def from_json(cls, data):
        return cls(slots_from_json(data.get("slots"), CHEST_SIZE))


class Furnace:
    kind = "furnace"

    def __init__(self, slots=None, burn_left=0.0, burn_total=0.0, progress=0.0):
        # Вход, топливо и результат.
        self.slots = slots if slots is not None else [None, None, None]
        self.burn_left = burn_left
        self.burn_total = burn_total
        self.progress = progress

    @property
    def lit(self):
        return self.burn_left > 0

    def result(self):
        """Что получится из входа сейчас, если на выходе есть место. Иначе None."""
        source = self.slots[INPUT]

        if source is None or source.type not in SMELTING:
            return None

        result = SMELTING[source.type]
        output = self.slots[OUTPUT]

        if output is not None and (output.type != result or output.count >= max_stack(output.type)):
            return None

        return result

    def tick(self, dt):
        """Продвигает плавку на dt секунд. Возвращает True, если печка зажглась или погасла."""
        was_lit = self.lit
        result = self.result()

        if self.burn_left > 0:
            self.burn_left = max(0.0, self.burn_left - dt)

        # Новое топливо берётся, только когда есть что плавить.
        fuel = self.slots[FUEL_SLOT]

        if not self.lit and result is not None and fuel is not None and fuel.type in FUEL:
            self.burn_total = self.burn_left = FUEL[fuel.type]

            fuel.count -= 1

            if fuel.count == 0:
                self.slots[FUEL_SLOT] = Stack("bucket") if fuel.type == "lava_bucket" else None

        if self.lit and result is not None:
            self.progress += dt

            if self.progress >= SMELT_TIME:
                self.progress = 0.0
                self.smelt(result)
        else:
            # Без огня недоплавленный предмет остывает.
            self.progress = max(0.0, self.progress - 2 * dt)

        return was_lit != self.lit

    def smelt(self, result):
        source = self.slots[INPUT]
        source.count -= 1

        if source.count == 0:
            self.slots[INPUT] = None

        if self.slots[OUTPUT] is None:
            self.slots[OUTPUT] = Stack(result)
        else:
            self.slots[OUTPUT].count += 1

    def to_json(self):
        return {
            "slots": slots_to_json(self.slots),
            "burn_left": self.burn_left,
            "burn_total": self.burn_total,
            "progress": self.progress,
        }

    @classmethod
    def from_json(cls, data):
        def number(name):
            value = data.get(name, 0.0)
            return float(value) if type(value) in (int, float) and value >= 0 else 0.0

        return cls(slots_from_json(data.get("slots"), 3), number("burn_left"), number("burn_total"), number("progress"))


KINDS = {"chest": Chest, "furnace": Furnace}


def make_container(block_type):
    return KINDS[block_type]() if block_type in KINDS else None


def containers_to_json(containers):
    return [
        {"position": list(position), "kind": container.kind, **container.to_json()}
        for position, container in containers.items()
    ]


def containers_from_json(value):
    containers = {}

    if not isinstance(value, list):
        return containers

    for entry in value:
        try:
            position = tuple(int(axis) for axis in entry["position"])
            kind = KINDS[entry["kind"]]

            if len(position) != 3:
                raise ValueError

        except (KeyError, TypeError, ValueError):
            continue

        containers[position] = kind.from_json(entry)

    return containers
