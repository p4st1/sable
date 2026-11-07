from engine import Engine
from camera import Camera
from object3D import Object3D
from world import World
from mesh import Mesh
from block import FACING_BLOCKS, TORCHES, Block, FacingState
import chunk as chunk_module
from chunk import BRIGHTNESS, Y_MAX, Y_MIN, Chunk, in_height
from config import Config
from renderer import Renderer
from gui import Gui
from menu import Menu
from chat import PLAYER_NAME, Chat
import commands
from entities import THROW_DELAY, ItemEntity, ItemModels, items_from_json, items_to_json, scatter_velocity
from collision import player_box
from mining import BREAK_COOLDOWN, HIT_INTERVAL, HIT_VOLUME, Mining, break_time, can_harvest, crack_object, wear_for
from containers import Furnace, containers_from_json, containers_to_json, make_container
from items import BUCKETS, FOODS, TOOLS, PlayerInventory, Stack, bonus_drops, drop_for, insert, is_placeable, slots_from_json, slots_to_json
from screens import ChestScreen, CraftingScreen, CreativeScreen, FurnaceScreen, InventoryScreen
from hand import Hand
from collision import FEET, GAP, box_touches_block
from door import facing_side, is_door
from player import HURT_TIME, MAX_AIR, MAX_HEALTH, Player
from settings import Settings
from sound import Music, Sounds
from worlds import WORLDS, parse_arguments

import storage
import streaming
import water
from terrain import TerrainGenerator, random_seed

import math
import pygame
import time
import random
import sys

# Маленький буфер звука: иначе звук удара отстаёт от взмаха руки.
pygame.mixer.pre_init(44100, -16, 2, 512)
pygame.init()

# За главным меню бесконечный мир с этим сидом, камера кружит над точкой появления.
TITLE_SEED = 11
TITLE_ORBIT_RADIUS = 30
TITLE_ORBIT_SPEED = 0.05
TITLE_ORBIT_HEIGHT = 14

# Где искать землю под точкой появления: вся высота мира сверху вниз. Ось Y вниз.
SPAWN_SEARCH = range(Y_MIN, Y_MAX + 1)

# Сколько секунд за кадр можно тратить на постройку новых чанков, и сколько
# при входе в мир, пока показывается экран загрузки.
CHUNK_BUDGET = 0.006
ENTER_BUDGET = 1.5

# Туман темнеет вдали от неба: при таком небесном свете у глаз и выше он ещё
# полной яркости. Факел туман не светлит, иначе дальние стены пещеры белели бы.
FOG_FULL_LIGHT = 12
# Как быстро туман догоняет новую яркость, доля за секунду.
FOG_LIGHT_SPEED = 3.0

# Верхний блок столбца, на который приятно встать при появлении (не листва, не вода).
SPAWN_GROUND = {"grass", "snowy_grass", "sand", "dirt", "stone", "snow", "gravel"}
HURT_FLASH = (255, 0, 0)
HURT_FLASH_ALPHA = 90
# Под водой весь экран чуть синее.
UNDERWATER_TINT = (10, 40, 140)
UNDERWATER_TINT_ALPHA = 70
BLINK_MS = 100

# Громкость звуков относительно полной.
STEP_VOLUME = 0.25
LAND_VOLUME = 0.5
CHEST_VOLUME = 0.5
EAT_VOLUME = 0.6
TOOL_BREAK_VOLUME = 0.8
PICKUP_VOLUME = 0.2
SPLASH_VOLUME = 0.6
SWIM_VOLUME = 0.15

# Бросок предмета: скорость (0.3 блока за тик), подъём и откуда он вылетает.
THROW_SPEED = 6.0
THROW_LIFT = 2.0
THROW_DROP = 0.3
CRACKLE_VOLUME = 0.6
# Печка потрескивает в среднем раз в столько секунд.
CRACKLE_INTERVAL = 5.0


class Game(Engine):
    def __init__(self, world_name=None, new_world=False):
        self.settings = Settings.load()

        self.screen = pygame.display.set_mode(
            (self.settings.screen_width, self.settings.screen_height)
        )
                
        pygame.display.set_caption("Sable")
        self.engine = Engine()
        self.hand = Hand(self.engine)

        self.clock = pygame.time.Clock()
        self.angle = 0
        self.FPS = self.settings.fps_limit
        self.running = True
        self.x = 0
        self.mouse_x, self.mouse_y = 0, 0

        self.render_scale = self.settings.render_scale
        self.engine.fog_distance = self.settings.fog_distance

        self.gui = Gui(self.settings.gui_scale, self.screen.get_size())
        self.sounds = Sounds(self.settings.sound_volume / 100)
        self.music = Music(self.sounds, self.settings.music_volume / 100)
        self.menu = Menu(self)
        self.mining = Mining()
        self.chat = Chat()
        self.item_models = ItemModels(self.engine)

        # Открытый экран с ячейками (инвентарь, верстак, сундук, печка) или None.
        self.open_screen = None

        self.inventory = PlayerInventory()
        self.game_mode = "creative"

        self.update_render_surface()

        self.x_velocity = 0
        self.z_velocity = 0

        self.reach = self.settings.reach
        self.selected_slot = self.settings.selected_slot
        self.forwad = 0
        self.right = 0

        self.menu_open = False

        # Папка открытого мира в saves; None значит главное меню.
        self.world_folder = None
        self.world_name = None
        self.world_generator = None

        # Генератор и загрузчик чанков бесконечного мира, у тестовых миров None.
        self.terrain = None
        self.loader = None
        self.seed = None
        self.title_center = (0, -16, 0)

        self.f3_open = False
        self.gui_hidden = False

        # Яркость тумана у глаз, плавно догоняет свет вокруг игрока.
        self.fog_light = 1.0

        # Чанки, свет которых мог измениться после правки рядом: их меши
        # перестраиваются понемногу в следующих кадрах.
        self.stale_chunks = set()
        chunk_module.smooth_lighting = self.settings.smooth_lighting
        
        if world_name is None:
            self.show_title()
        else:
            self.enter_world(world_name, world_name, new_world=new_world)

    @property
    def in_world(self):
        return self.world_folder is not None

    @property
    def survival(self):
        return self.game_mode == "survival"

    @property
    def hotbar(self):
        return self.inventory.hotbar

    def held_stack(self):
        return self.inventory.slots[self.selected_slot]

    def held_type(self):
        stack = self.held_stack()

        return None if stack is None else stack.type

    def create_world(self, position, rotation):
        self.world = World()
        self.water_time = 0.0
        self.stale_chunks = set()
        self.fog_light = 1.0
        self.terrain = None
        self.loader = None
        self.seed = None

        self.camera = Camera()
        self.camera.fov = self.settings.fov
        self.camera.sensitivity = self.settings.mouse_sensitivity
        self.camera.position = position
        self.camera.rotation = rotation

        self.player = Player(self.world, self.camera, self.settings)

    def start_terrain(self, seed, folder):
        """Бесконечный мир: генератор с сидом и загрузчик чанков вокруг игрока."""
        self.seed = seed
        self.terrain = TerrainGenerator(seed)
        self.loader = streaming.ChunkLoader(self.world, self.terrain, folder, self.build_chunk, self.unbuild_chunk)

    def show_loading(self, text):
        """Экран загрузки на время, пока мир строится и игра не отвечает."""
        self.screen.fill((0, 0, 0))
        self.gui.begin_frame()
        width, height = self.gui.units(self.screen)
        self.gui.draw_text(self.screen, text, (width // 2, height // 2))
        pygame.display.flip()
        pygame.event.pump()

    def terrain_spawn(self):
        """Точка появления нового бесконечного мира: на земле у найденного генератором места."""
        x, z = self.terrain.find_spawn()

        # В самом столбце может стоять дерево: ищем рядом открытую землю.
        for radius in range(8):
            for dx in range(-radius, radius + 1):
                for dz in range(-radius, radius + 1):
                    if max(abs(dx), abs(dz)) != radius:
                        continue

                    self.loader.ensure(x + dx, z + dz, 1)
                    spawn = self.ground_spawn((x + dx + 0.5, 0, z + dz + 0.5), fallback=False)

                    if spawn is not None and self.open_around(x + dx, spawn[1] + FEET + GAP, z + dz):
                        return spawn

        return self.ground_spawn((x + 0.5, 0, z + 0.5))

    def open_around(self, x, ground, z):
        """Вокруг клетки над землёй ground на два блока ни ствола, ни листвы на уровне головы."""
        for dx in range(-2, 3):
            for dz in range(-2, 3):
                for y in (ground - 1, ground - 2):
                    block = self.world.get_block(x + dx, round(y), z + dz)

                    if block is not None and block.is_solid:
                        return False

        return True

    def enter_world(self, folder, generator, name=None, new_world=False, game_mode="creative", seed=None):
        """Открывает мир из saves/<folder>. Новый мир строится генератором из WORLDS.

        game_mode и seed нужны только новому миру: у сохранённого они в world.json.
        """
        test_world = WORLDS.get(generator)
        load = storage.has_save(folder) and not new_world

        if test_world is None and not load:
            raise ValueError(f"неизвестный тип мира '{generator}'")

        infinite = test_world is not None and test_world.infinite

        if infinite:
            self.show_loading("Loading world..." if load else "Generating world...")

        if test_world is None:
            self.create_world((0, 0, 0), (0, 0, 0))
        else:
            self.create_world(test_world.position, test_world.rotation)

        if not load:
            # В папке могут остаться чанки прошлой версии мира (после --new или Re-Create).
            storage.clear_chunks(folder)

        if load:
            meta = storage.load_world(self.world, self.player, folder, load_chunks=not infinite)

            if infinite:
                saved_seed = meta.get("seed")

                if type(saved_seed) is not int:
                    raise SystemExit(f"В сохранении {storage.world_folder(folder)} нет сида мира")

                self.start_terrain(saved_seed, folder)
                self.loader.ensure(self.camera.position[0], self.camera.position[2])

            self.game_mode = storage.game_mode_of(meta)

            health = meta.get("health")
            self.player.health = health if type(health) is int and 1 <= health <= MAX_HEALTH else MAX_HEALTH
            self.world.containers = containers_from_json(meta.get("containers"))
            self.world.items = items_from_json(meta.get("items"))

            # Вода, которая текла в момент сохранения, дотекает.
            water.water_cells_to_settle(self.world)

            if "inventory" in meta:
                self.inventory = PlayerInventory(slots_from_json(meta["inventory"], len(self.inventory.slots)))
            else:
                self.inventory = self.starting_inventory()
        elif infinite:
            self.start_terrain(random_seed() if seed is None else seed, folder)
            self.game_mode = game_mode
            self.inventory = self.starting_inventory()
        else:
            test_world.generate(self.world)
            self.player.flying = test_world.flying and game_mode == "creative"
            self.game_mode = game_mode
            self.inventory = self.starting_inventory()

        # Точка возрождения: на земле под стартовой позицией генератора,
        # или та, что задана командой /spawnpoint и сохранена в мире.
        if test_world is None:
            self.spawn_point = self.camera.position
        elif infinite:
            # У сохранённого мира точка записана, искать заново незачем.
            self.spawn_point = self.camera.position if load else self.terrain_spawn()
        else:
            self.spawn_point = self.ground_spawn(test_world.position)

        saved_spawn = meta.get("spawn") if load else None

        if isinstance(saved_spawn, list) and len(saved_spawn) == 3 and all(type(value) in (int, float) for value in saved_spawn):
            self.spawn_point = tuple(saved_spawn)

        # Новый мир в выживании начинается на земле, а не в воздухе: иначе сразу урон от падения.
        # В бесконечном мире на земле начинают в любом режиме.
        if not load and (self.survival or infinite):
            self.camera.position = self.spawn_point

        self.player.survival = self.survival
        self.player.spawn = self.spawn_point

        self.world_folder = folder
        self.world_name = name or folder
        self.world_generator = generator

        if infinite:
            # Ближние чанки сразу, остальные достроятся за следующие кадры.
            x, _, z = self.camera.position
            self.loader.ensure(x, z)
            self.loader.update(x, z, self.chunk_radius(), ENTER_BUDGET)
        else:
            self.build_chunks()

        self.forwad = 0
        self.right = 0

        self.menu.show_pause()
        self.open_screen = None
        self.mining.stop()
        self.chat.close()
        self.chat.messages.clear()
        self.set_menu(False)

        pygame.mouse.get_rel()

    def ground_spawn(self, position, fallback=True):
        """Стоя на самом верхнем блоке столбца под position. Мир уже должен быть построен.

        У некоторых тестовых миров камера стоит за краем площадки, чтобы её было видно
        целиком. Тогда появляемся в центре мира, а не над пустотой.
        fallback=False: только на хорошей земле (SPAWN_GROUND) в этом столбце, иначе None.
        """
        x, y, z = position

        if not fallback:
            column_x, column_z = math.floor(x), math.floor(z)

            for top in SPAWN_SEARCH:
                block = self.world.get_block(column_x, top, column_z)

                if block is not None:
                    if block.type not in SPAWN_GROUND:
                        return None

                    return (column_x + 0.5, top - FEET - GAP, column_z + 0.5)

            return None

        for column_x, column_z in ((math.floor(x), math.floor(z)), (0, 0)):
            for top in SPAWN_SEARCH:
                if self.world.get_block(column_x, top, column_z) is not None:
                    return (column_x + 0.5, top - FEET - GAP, column_z + 0.5)

        return position

    def show_death(self):
        self.menu.show_death()
        self.set_menu(True)

        self.forwad = 0
        self.right = 0

    def respawn(self):
        self.player.respawn(self.spawn_point)
        self.menu.show_pause()
        self.set_menu(False)

    def starting_inventory(self):
        # В творческом режиме хотбар сразу заполнен, в выживании всё добывается.
        return PlayerInventory.creative_default() if not self.survival else PlayerInventory()

    def play_world(self, folder, generator, name):
        try:
            self.enter_world(folder, generator, name)

        except SystemExit as error:
            # Битое сохранение не должно закрывать игру, когда его открыли из меню.
            print(error)
            self.show_title()

    def create_new_world(self, folder, generator, name, game_mode="survival", seed=None):
        self.enter_world(folder, generator, name, new_world=True, game_mode=game_mode, seed=seed)

        # Мир сразу появляется в списке, даже если игра потом закроется аварийно.
        self.save_world()

    def leave_world(self):
        self.save_world()
        self.show_title()

    def quit(self):
        self.running = False

    def show_title(self):
        """Главное меню: за ним показывается мир, который нигде не сохраняется."""
        self.world_folder = None
        self.world_name = None
        self.world_generator = None

        self.create_world((0, 0, 0), (0, 0, 0))

        # Мир за меню не сохраняется. Рядом с центром сразу, остальное достроится.
        self.start_terrain(TITLE_SEED, None)
        x, z = self.terrain.find_spawn()
        self.loader.ensure(x, z, 0)

        top = next((y for y in SPAWN_SEARCH if self.world.get_block(x, y, z) is not None), 0)
        self.title_center = (x, top - TITLE_ORBIT_HEIGHT, z)
        self.update_title_camera()
        self.loader.update(x, z, self.chunk_radius(), ENTER_BUDGET / 3)

        self.menu.show_title()
        self.open_screen = None
        self.set_menu(True)

    def save_world(self):
        if not self.in_world:
            return

        # Предметы с курсора и из сетки крафта возвращаются в инвентарь до записи.
        if self.open_screen is not None:
            self.close_screen()

        # Погибший игрок выходит из мира уже возрождённым.
        if self.player.dead:
            self.player.respawn(self.spawn_point)

        written = storage.save_world(
            self.world,
            self.player,
            self.world_folder,
            self.world_name,
            self.world_generator,
            {
                **({"seed": self.seed} if self.seed is not None else {}),
                "game_mode": self.game_mode,
                "health": self.player.health,
                "spawn": list(self.spawn_point),
                "inventory": slots_to_json(self.inventory.slots),
                "containers": containers_to_json(self.world.containers),
                "items": items_to_json(self.world.items),
            }
        )

        print(f"Мир сохранён в {storage.world_folder(self.world_folder)}, записано чанков: {written}")

    def chunk_radius(self):
        """Сколько чанков вокруг игрока держать построенными: до края тумана."""
        return streaming.radius_for(self.engine.fog_distance)

    def build_chunks(self):
        for chunk in self.world.chunks.values():
            self.build_chunk(chunk)

    def unbuild_chunk(self, key):
        """Убирает меши дальнего чанка, сам чанк остаётся в мире."""
        chunk = self.world.chunks[key]
        chunk.meshed = False
        self.world.chunk_objects.pop(key, None)
        self.world.liquid_objects.pop(key, None)
        self.world.objects = [object for group in self.world.chunk_objects.values() for object in group]
        self.world.liquids = [object for group in self.world.liquid_objects.values() for object in group]

    def build_chunk(self, chunk):
        chunk.meshed = True
        objects = []

        for texture_name, data in chunk.build_mesh(self.world).items():
            texture = self.engine.load_texture(texture_name)

            mesh = Mesh(
                data['points'],
                data['triangles'],
                data['uvs'],
                texture,
                data['shades']
            )

            chunk_object = Object3D(mesh)

            chunk_object.position = (
                chunk.chunk_x * chunk.SIZE,
                0,
                chunk.chunk_z * chunk.SIZE
            )

            chunk_object.static = True
            chunk_object.build_world_points()

            objects.append(chunk_object)

        self.world.set_chunk_objects(chunk, objects)
        self.build_water(chunk)

    def build_water(self, chunk):
        """Меш воды чанка. Вода не закрывает граней блоков, поэтому её меш собирается отдельно."""
        data = water.build_water_mesh(chunk, self.world)
        objects = []

        if data is not None:
            water_object = Object3D(Mesh(data['points'], data['triangles'], data['uvs'], self.engine.load_texture(water.WATER_TEXTURE), data['shades']))
            water_object.position = (chunk.chunk_x * chunk.SIZE, 0, chunk.chunk_z * chunk.SIZE)
            water_object.static = True
            water_object.build_world_points()
            objects.append(water_object)

        self.world.set_liquid_objects(chunk, objects)

    def tick_water(self, dt):
        """Вода течёт шагами раз в water.TICK. Перестраиваются только меши воды."""
        self.water_time += dt

        if self.water_time < water.TICK:
            return

        self.water_time = 0.0

        if not self.world.water_updates:
            return

        for key in water.tick(self.world):
            chunk = self.world.chunks.get(key)

            if chunk is not None and chunk.meshed:
                self.build_water(chunk)

    def rebuild_around(self, x, z):
        # Блок на границе чанка меняет видимость граней и у соседнего чанка.
        # Чанки без меша (дальние в бесконечном мире) получат его позже сами.
        now = [chunk for chunk in self.world.chunks_around(x, z) if chunk.meshed]

        for chunk in now:
            self.build_chunk(chunk)
            self.stale_chunks.discard((chunk.chunk_x, chunk.chunk_z))

        # Свет от блока доходит на 15 клеток, то есть до всех соседних чанков.
        # Их перестроим чуть позже, по одному за кадр.
        center_x, center_z = x // Chunk.SIZE, z // Chunk.SIZE

        for dx in (-1, 0, 1):
            for dz in (-1, 0, 1):
                key = (center_x + dx, center_z + dz)
                chunk = self.world.chunks.get(key)

                if chunk is not None and chunk.meshed and chunk not in now:
                    self.stale_chunks.add(key)

    def rebuild_stale(self, budget):
        """Перестраивает чанки с устаревшим светом, ближние первыми, не дольше budget."""
        if not self.stale_chunks:
            return

        start = time.perf_counter()
        eye_x, _, eye_z = self.camera.position
        center = (math.floor(eye_x) // Chunk.SIZE, math.floor(eye_z) // Chunk.SIZE)

        for key in sorted(self.stale_chunks, key=lambda key: (key[0] - center[0]) ** 2 + (key[1] - center[1]) ** 2):
            self.stale_chunks.discard(key)
            chunk = self.world.chunks.get(key)

            if chunk is not None and chunk.meshed:
                self.build_chunk(chunk)

            if time.perf_counter() - start >= budget:
                break

    def eye_light(self):
        """Уровень света там, где глаза."""
        x, y, z = (math.floor(value) for value in self.camera.position)

        return self.world.light_at(x, y, z)

    def update_fog_light(self, dt):
        x, y, z = (math.floor(value) for value in self.camera.position)
        target = min(1.0, BRIGHTNESS[self.world.sky_light_at(x, y, z)] / BRIGHTNESS[FOG_FULL_LIGHT])
        self.fog_light += (target - self.fog_light) * min(1.0, dt * FOG_LIGHT_SPEED)

    def break_block(self, target=None):
        """Ломает блок target или тот, на который смотрим. В выживании сюда приходят после ломания."""
        # Рукой машем при любом ударе, даже по воздуху.
        self.hand.swing()

        if target is None:
            target, _ = self.world.raycast(self.camera.position, self.camera.forward(), self.reach)

        if target is None:
            return

        x, y, z = target
        block = self.world.get_block(x, y, z)

        if is_door(block.type):
            for half in self.world.door_halves(x, y, z):
                self.world.notify(*half)

            self.world.remove_door(x, y, z)
            self.block_sound(block.type, "break", target)
        else:
            self.block_sound(block.type, "break", target)

            self.world.remove_block(x, y, z)
            self.world.notify(x, y, z)

            # Сундук и печка высыпают содержимое.
            container = self.world.containers.pop(target, None)

            if container is not None:
                for stack in container.slots:
                    if stack is not None:
                        self.drop(stack.copy(), target)

            # Дверь без опоры не стоит: ломаем и её. Ось Y направлена вниз.
            above = self.world.get_block(x, y - 1, z)

            if above is not None and is_door(above.type):
                for half in self.world.door_halves(x, y - 1, z):
                    self.world.notify(*half)

                self.world.remove_door(x, y - 1, z)
                self.drop(Stack(above.type), (x, y - 1, z))

            # Факел тоже падает, если из-под него выбили блок.
            elif above is not None and above.type in TORCHES:
                self.world.remove_block(x, y - 1, z)
                self.world.notify(x, y - 1, z)
                self.drop(Stack(above.type), (x, y - 1, z))

        held = self.held_type()

        # Каменные блоки без кирки ломаются, но ничего не дают.
        dropped = drop_for(block.type)

        if dropped is not None and can_harvest(block.type, held):
            self.drop(Stack(dropped), target)

        for item in bonus_drops(block.type):
            self.drop(Stack(item), target)

        if self.survival:
            self.wear_tool()

        self.rebuild_around(x, z)

    def wear_tool(self):
        """Инструмент в руке изнашивается от сломанного блока и в конце ломается."""
        stack = self.held_stack()

        if stack is None or stack.type not in TOOLS:
            return

        stack.damage += wear_for(stack.type)

        if stack.damage >= TOOLS[stack.type].uses:
            self.inventory.slots[self.selected_slot] = None
            self.sounds.play("entity.item.break", TOOL_BREAK_VOLUME)

    def drop(self, stack, cell):
        """Добыча выпадает из клетки cell в мир. В творческом режиме блоки ничего не роняют."""
        if not self.survival:
            return

        x, y, z = cell
        position = (x + random.uniform(0.25, 0.75), y + random.uniform(0.25, 0.75), z + random.uniform(0.25, 0.75))

        self.world.items.append(ItemEntity(stack, position, scatter_velocity()))

    def throw(self, stack):
        """Бросает стак вперёд, куда смотрит игрок. Подобрать его можно через пару секунд."""
        x, y, z = self.camera.position
        dx, dy, dz = self.camera.forward()

        # Из-под глаз, со скоростью как в оригинале (0.3 блока за тик) и чуть вверх.
        speed = THROW_SPEED
        velocity = (
            dx * speed + random.uniform(-0.2, 0.2),
            dy * speed - THROW_LIFT,
            dz * speed + random.uniform(-0.2, 0.2),
        )

        self.world.items.append(ItemEntity(stack, (x, y + THROW_DROP, z), velocity, THROW_DELAY))

    def throw_held(self, whole_stack=False):
        """Q выбрасывает один предмет из руки, Ctrl+Q весь стак."""
        stack = self.held_stack()

        if stack is None:
            return

        thrown = stack.copy()
        thrown.count = stack.count if whole_stack else 1
        stack.count -= thrown.count

        if stack.count == 0:
            self.inventory.slots[self.selected_slot] = None

        self.throw(thrown)
        self.hand.swing()

    def update_items(self, dt):
        """Предметы падают, со временем исчезают, а рядом с игроком подбираются."""
        world = self.world
        low, high = player_box(self.camera.position)
        picked = False

        for entity in list(world.items):
            # В незагруженном чанке предмет замирает: иначе он провалился бы в пустоту.
            if self.loader is not None and not self.loader.is_loaded(entity.position[0], entity.position[2]):
                continue

            entity.update(world, dt)

            if entity.expired:
                world.items.remove(entity)
                continue

            if self.player.dead or entity.pickup_delay > 0 or not entity.touches(low, high):
                continue

            before = entity.stack.count
            left = insert(self.inventory.slots, entity.stack.copy())

            if left < before:
                picked = True
                entity.stack.count = left

                if left == 0:
                    world.items.remove(entity)

        if picked:
            self.sounds.play("entity.item.pickup", PICKUP_VOLUME)

    def item_objects(self):
        """Лежащие предметы в этом кадре, дальше тумана не рисуем."""
        eye = self.camera.position
        limit = self.engine.fog_distance
        objects = []

        for entity in self.world.items:
            if math.dist(entity.position, eye) < limit:
                level = self.world.light_at(*(math.floor(value) for value in entity.position))
                objects += self.item_models.draw_objects(entity, float(BRIGHTNESS[level]))

        return objects

    def use_block(self, position):
        """Правый клик по верстаку, сундуку или печке открывает их экран."""
        block = self.world.get_block(*position)

        if block.type == "crafting_table":
            self.show_screen(CraftingScreen(self))
            return True

        container = self.world.containers.get(position)

        if block.type == "chest":
            if container is None:
                container = self.world.containers[position] = make_container("chest")

            self.show_screen(ChestScreen(self, container))
            self.sounds.play_at("block.chest.open", self.cell_center(position), self.camera, CHEST_VOLUME)
            self.chest_position = position
            return True

        if block.type == "furnace":
            if container is None:
                container = self.world.containers[position] = make_container("furnace")

            self.show_screen(FurnaceScreen(self, container))
            return True

        return False

    def place_block(self):
        hit, target = self.world.raycast(self.camera.position, self.camera.forward(), self.reach)

        # Едят и глядя в небо: блок под прицелом для этого не нужен. Ведро черпает
        # и из глубокой воды, где дна не достать.
        if hit is None:
            if self.held_type() in FOODS:
                self.eat(self.held_type())

            elif self.held_type() in BUCKETS:
                self.use_bucket(self.held_type())

            return

        # Правый клик по двери открывает или закрывает её, что бы ни было в руке.
        if is_door(self.world.get_block(*hit).type):
            self.world.toggle_door(*hit)

            opened = self.world.get_block(*hit).state.open
            event = "block.wooden_door.open" if opened else "block.wooden_door.close"
            self.sounds.play_at(event, self.cell_center(hit), self.camera)
            self.rebuild_around(hit[0], hit[2])
            self.hand.swing()
            return

        # С зажатым Shift на верстак или сундук можно поставить блок, не открывая их.
        keys = pygame.key.get_pressed()
        sneaking = keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT]

        if not sneaking and self.use_block(hit):
            self.hand.swing()
            return

        held = self.held_type()

        if held in FOODS:
            self.eat(held)
            return

        if held in BUCKETS:
            self.use_bucket(held)
            return

        # Луч мог пройти мимо створки, тогда клетка перед блоком занята дверью.
        # Вода не мешает: блок её вытесняет. Выше потолка мира не строят.
        if held is None or not is_placeable(held) or target is None or not in_height(target[1]):
            return

        occupant = self.world.get_block(*target)

        if occupant is not None and not occupant.is_liquid:
            return

        # Факел стоит только на целом блоке, зато сквозь него можно ходить.
        if held in TORCHES:
            ground = self.world.get_block(target[0], target[1] + 1, target[2])

            if ground is None or not ground.is_cube:
                return

        elif box_touches_block(self.camera.position, target):
            return

        if is_door(held):
            x, y, z = target

            if box_touches_block(self.camera.position, (x, y - 1, z)):
                return

            if self.world.place_door(target, held, self.camera.forward(), self.camera.position):
                self.world.notify(x, y, z)
                self.world.notify(x, y - 1, z)
                self.rebuild_around(x, z)
                self.placed(held, target)

            return

        state = None

        # Печка и сундук встают лицом к игроку.
        if held in FACING_BLOCKS:
            state = FacingState(facing_side(self.camera.forward()))

        self.world.set_block(*target, Block(held, state))
        self.world.notify(*target)

        container = make_container(held)

        if container is not None:
            self.world.containers[target] = container

        self.rebuild_around(target[0], target[2])
        self.placed(held, target)

    def use_bucket(self, held):
        """Пустое ведро черпает источник воды, полное выливает его перед блоком."""
        eye, forward = self.camera.position, self.camera.forward()

        if held == "bucket":
            cell, _ = self.world.raycast(eye, forward, self.reach, sources=True)

            if cell is None or not self.world.get_block(*cell).is_liquid:
                return

            self.world.remove_block(*cell)
            result, sound = "water_bucket", "item.bucket.fill"
        else:
            _, cell = self.world.raycast(eye, forward, self.reach)

            if cell is None:
                return

            occupant = self.world.get_block(*cell)

            if occupant is not None and not occupant.is_liquid:
                return

            self.world.set_block(*cell, Block("water"))
            result, sound = "bucket", "item.bucket.empty"

        self.world.notify(*cell)
        self.rebuild_water_around(cell[0], cell[2])
        self.sounds.play_at(sound, self.cell_center(cell), self.camera)
        self.hand.swing()

        # В творческом режиме ведро в руке не меняется, как в оригинале.
        if not self.survival:
            return

        stack = self.held_stack()

        if stack.count == 1:
            self.inventory.slots[self.selected_slot] = Stack(result)
            return

        self.inventory.take_one(self.selected_slot)

        # Полное ведро не влезло в инвентарь: падает под ноги.
        if self.inventory.add(result):
            self.throw(Stack(result))

    def rebuild_water_around(self, x, z):
        for chunk in self.world.chunks_around(x, z):
            if chunk.meshed:
                self.build_water(chunk)

    def eat(self, food):
        """Съедает предмет в руке, если есть что лечить. На полном здоровье еда не тратится."""
        if not self.player.heal(FOODS[food]):
            return

        self.inventory.take_one(self.selected_slot)
        self.hand.swing()
        self.sounds.play("entity.generic.eat", EAT_VOLUME)

    def placed(self, block_type, position):
        """Блок поставлен: в выживании он уходит из стака в руке."""
        self.hand.swing()
        self.block_sound(block_type, "place", position)

        if self.survival:
            self.inventory.take_one(self.selected_slot)

    @staticmethod
    def cell_center(position):
        x, y, z = position

        return (x + 0.5, y + 0.5, z + 0.5)

    def block_sound(self, block_type, action, position, volume=1.0):
        """Звук блока в клетке position: break, place или step."""
        self.sounds.block_sound(block_type, action, self.cell_center(position), self.camera, volume)

    def play_player_sounds(self):
        """Шаги, приземление и урон, которые игрок записал за кадр."""
        for event in self.player.events:
            if event[0] == "hurt":
                self.sounds.play("entity.player.hurt")

            elif event[0] == "splash":
                self.sounds.play("entity.player.splash", SPLASH_VOLUME)

            elif event[0] == "swim":
                self.sounds.play("entity.player.swim", SWIM_VOLUME)

            elif event[1] is not None:
                block_type, position = event[1]
                volume = STEP_VOLUME if event[0] == "step" else LAND_VOLUME

                self.sounds.block_sound(block_type, "step", position, self.camera, volume)

        self.player.events.clear()

    def tick_containers(self, dt):
        """Печки работают и с закрытым экраном. Огонь меняет вид лицевой грани."""
        for position, container in self.world.containers.items():
            if not isinstance(container, Furnace):
                continue

            changed = container.tick(dt)

            if container.lit and random.random() < dt / CRACKLE_INTERVAL:
                self.sounds.play_at("block.furnace.fire_crackle", self.cell_center(position), self.camera, CRACKLE_VOLUME)

            if not changed:
                continue

            block = self.world.get_block(*position)

            if block is not None and block.type == "furnace":
                self.world.set_block(*position, Block("furnace", block.state._replace(lit=container.lit)))
                self.rebuild_around(position[0], position[2])

    def select_slot(self, slot):
        self.selected_slot = slot % Config.HOTBAR_SIZE
        self.save_settings()

    def update(self, dt):
        # Музыка идёт и в меню, и на паузе.
        self.music.update(dt)
        self.chat.update(dt)
        self.update_fog_light(dt)
        self.rebuild_stale(CHUNK_BUDGET)

        if not self.in_world:
            self.angle += TITLE_ORBIT_SPEED * dt
            self.update_title_camera()

            center_x, _, center_z = self.title_center
            self.loader.update(center_x, center_z, self.chunk_radius() + 2, CHUNK_BUDGET)
            return

        if self.loader is not None:
            x, _, z = self.camera.position
            self.loader.update(x, z, self.chunk_radius(), CHUNK_BUDGET)

        if self.menu_open:
            return

        self.tick_containers(dt)
        self.tick_water(dt)
        self.update_items(dt)

        # Пока открыт экран или чат, игрок стоит на месте.
        if self.open_screen is not None or self.chat.open:
            return

        # Под игроком всегда должна быть земля: после телепорта её строим сразу.
        if self.loader is not None:
            self.loader.ensure(self.camera.position[0], self.camera.position[2])

        keys = pygame.key.get_pressed()

        self.player.update(
            dt,
            self.forwad,
            self.right,
            keys[pygame.K_SPACE],
            keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT]
        )

        player = self.player
        walking = bool(self.forwad or self.right) and player.on_ground and not player.flying

        self.hand.update(dt, self.held_type(), walking)
        self.play_player_sounds()

        if self.survival:
            self.update_mining(dt)

        if player.dead:
            self.show_death()

    def update_title_camera(self):
        center_x, center_y, center_z = self.title_center

        self.camera.position = (
            center_x + math.sin(self.angle) * TITLE_ORBIT_RADIUS,
            center_y,
            center_z + math.cos(self.angle) * TITLE_ORBIT_RADIUS
        )
        self.camera.rotation = (-0.35, self.angle + math.pi, 0)

    def update_render_surface(self):
        render_width = max(1, int(self.screen.get_width() * self.render_scale))
        render_height = max(1, int(self.screen.get_height() * self.render_scale))

        self.render_surface = pygame.Surface((render_width, render_height))

    def apply_settings(self):
        """Переносит self.settings в камеру, частоту кадров и масштабы."""
        settings = self.settings

        self.camera.fov = settings.fov
        self.camera.sensitivity = settings.mouse_sensitivity
        self.FPS = settings.fps_limit
        self.engine.fog_distance = settings.fog_distance
        self.sounds.volume = settings.sound_volume / 100
        self.music.volume = settings.music_volume / 100

        if self.render_scale != settings.render_scale:
            self.render_scale = settings.render_scale
            self.update_render_surface()

        if self.gui.requested_scale != settings.gui_scale:
            self.gui.set_scale(settings.gui_scale, self.screen.get_size())

        # Мягкий свет поменялся: все построенные чанки перестроятся за несколько кадров.
        if chunk_module.smooth_lighting != settings.smooth_lighting:
            chunk_module.smooth_lighting = settings.smooth_lighting
            self.stale_chunks.update(key for key, chunk in self.world.chunks.items() if chunk.meshed)

    def save_settings(self):
        self.settings.selected_slot = self.selected_slot
        self.settings.save()

    def render(self):
        extra = self.crack_overlay() + self.item_objects() if self.in_world else []

        # Крадучись камера чуть ниже. Физика и прицел остаются на месте глаз стоя.
        eye = self.camera.position

        if self.in_world and self.player.eye_drop:
            self.camera.position = (eye[0], eye[1] + self.player.eye_drop, eye[2])

        underwater = self.in_world and water.point_in_water(self.world, self.camera.position)

        self.engine.render(self.world, self.render_surface, self.camera, extra, underwater, self.fog_light)
        self.camera.position = eye

        in_world = self.in_world and not self.gui_hidden

        if in_world:
            self.hand.render(self.held_type(), self.render_surface, float(BRIGHTNESS[self.eye_light()]))

        pygame.transform.scale(self.render_surface, self.screen.get_size(), self.screen)

        if underwater:
            self.gui.tint(self.screen, UNDERWATER_TINT, UNDERWATER_TINT_ALPHA)

        if in_world:
            player = self.player
            blink = player.hurt_time > 0 and pygame.time.get_ticks() // BLINK_MS % 2 == 0

            self.gui.render_hud(
                self.screen,
                self.hotbar,
                self.selected_slot,
                self.survival,
                player.health if self.survival else None,
                blink,
                # Пузырьки видны, только пока воздух тратится или восстанавливается.
                player.air / MAX_AIR if self.survival and (player.eyes_in_water or player.air < MAX_AIR) else None
            )

            # Красная вспышка при уроне, тает за время неуязвимости.
            if player.hurt_time > 0:
                self.gui.tint(self.screen, HURT_FLASH, int(HURT_FLASH_ALPHA * player.hurt_time / HURT_TIME))

        # F1 прячет и чат, кроме открытого.
        if self.in_world and (not self.gui_hidden or self.chat.open):
            self.chat.render(self.screen, self.gui)

        if self.open_screen is not None:
            self.open_screen.render(self.screen)

        if self.menu_open:
            self.menu.render(self.screen)

        if self.f3_open:
            self.engine.render_text(self.screen, str(self.clock.get_fps()), (0, 0))
            self.engine.render_text(self.screen, f"transform: {self.engine.transform_time * 1000:.2f} ms", (0, 20))
            self.engine.render_text(self.screen, f"raster: {self.engine.raster_time * 1000:.2f} ms, fog: {self.engine.fog_time * 1000:.2f} ms", (0, 40))
            self.engine.render_text(self.screen, f"visible object: {self.engine.visible_objects}", (0, 60))
            self.engine.render_text(self.screen, f"triangles: {self.engine.total_triangles}", (0, 80))
            self.engine.render_text(self.screen, f"menu opened: {self.menu_open}", (0, 100))
            x, height, z = self.player_position() if self.in_world else self.camera.position
            self.engine.render_text(self.screen, f"XYZ: {x:.2f} / {height:.2f} / {z:.2f}", (0, 120))
            self.engine.render_text(self.screen, f"flying: {self.player.flying}, light: {self.eye_light() if self.in_world else '-'}", (0, 140))

            if self.terrain is not None:
                meshed = sum(chunk.meshed for chunk in self.world.chunks.values())
                biome = self.terrain.biome_at(math.floor(x), math.floor(z))
                self.engine.render_text(self.screen, f"seed: {self.seed}  biome: {biome}", (0, 160))
                self.engine.render_text(self.screen, f"chunks: {len(self.world.chunks)} loaded, {meshed} meshed, {self.loader.generated} generated, work {self.loader.work_time * 1000:.1f} ms", (0, 180))


        pygame.display.flip()

    def set_menu(self, opened):
        self.menu_open = opened
        self.free_cursor(opened)

    def free_cursor(self, free):
        """Свободный курсор для меню и инвентаря, захваченный для управления камерой."""
        pygame.mouse.set_visible(free)
        pygame.event.set_grab(not free)

        # Сбрасываем накопленное смещение, чтобы камера не дёрнулась.
        pygame.mouse.get_rel()

    def update_mining(self, dt):
        """Пока зажата ЛКМ, блок под прицелом ломается. Сменил блок или отпустил — всё заново."""
        mining = self.mining
        mining.cooldown = max(0.0, mining.cooldown - dt)

        # Кнопку могли отпустить, пока был открыт экран, и событие ушло туда.
        if not mining.active or not pygame.mouse.get_pressed()[0]:
            mining.stop()
            return

        target, _ = self.world.raycast(self.camera.position, self.camera.forward(), self.reach)

        if target != mining.target:
            mining.target = target
            mining.progress = 0.0

        if target is None or mining.cooldown > 0:
            return

        block = self.world.get_block(*target)

        # Пока ломаем, рука машет без остановки, а блок глухо стучит.
        if self.hand.swing_time is None:
            self.hand.swing()

        mining.hit_time -= dt

        if mining.hit_time <= 0:
            mining.hit_time = HIT_INTERVAL
            self.block_sound(block.type, "hit", target, HIT_VOLUME)

        mining.progress += dt / break_time(block.type, self.held_type())

        if mining.progress >= 1:
            self.break_block(target)

            mining.target = None
            mining.progress = 0.0
            mining.cooldown = BREAK_COOLDOWN

    def crack_overlay(self):
        """Трещины на блоке, который сейчас ломается."""
        stage = self.mining.stage

        if stage is None:
            return []

        block = self.world.get_block(*self.mining.target)

        if block is None:
            return []

        return [crack_object(self.engine, self.mining.target, block.box(), stage)]

    def show_screen(self, screen):
        self.mining.stop()
        self.open_screen = screen
        self.free_cursor(True)

        self.forwad = 0
        self.right = 0

    def open_inventory(self):
        self.show_screen(InventoryScreen(self) if self.survival else CreativeScreen(self))

    def close_screen(self):
        if isinstance(self.open_screen, ChestScreen):
            self.sounds.play_at("block.chest.close", self.cell_center(self.chest_position), self.camera, CHEST_VOLUME)

        self.open_screen.close()
        self.open_screen = None
        self.free_cursor(False)

    def screen_events(self, event):
        screen = self.open_screen

        if event.type == pygame.MOUSEBUTTONDOWN and event.button in (1, 3):
            screen.press(event.pos, event.button, bool(pygame.key.get_mods() & pygame.KMOD_SHIFT))

        elif event.type == pygame.MOUSEBUTTONUP and event.button in (1, 3):
            screen.release(event.pos)

        elif event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_ESCAPE, pygame.K_e):
                self.close_screen()

            elif pygame.K_1 <= event.key <= pygame.K_9:
                screen.number_key(event.key - pygame.K_1, pygame.mouse.get_pos())


    def open_pause(self):
        self.mining.stop()
        self.menu.show_pause()
        self.set_menu(True)

        self.forwad = 0
        self.right = 0

    def menu_events(self, event):
        menu = self.menu

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            menu.click(event.pos)

        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            menu.release()

        elif event.type == pygame.MOUSEMOTION:
            menu.motion(event.pos)

        elif event.type == pygame.MOUSEWHEEL and event.y != 0:
            menu.wheel(event.y)

        elif event.type == pygame.KEYDOWN:
            menu.key(event)

        elif event.type == pygame.TEXTINPUT:
            menu.text(event.text)

    def game_events(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 1:
                # В выживании блок ломается, пока держишь кнопку, в творческом сразу.
                if self.survival:
                    self.mining.start()
                    self.hand.swing()
                else:
                    self.break_block()

            elif event.button == 3:
                self.place_block()

        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self.mining.stop()

        if event.type == pygame.MOUSEWHEEL and event.y != 0:
            self.select_slot(self.selected_slot + (-1 if event.y > 0 else 1))

        if event.type == pygame.MOUSEMOTION:
            dx, dy = event.rel
            self.camera.rotate(dx, dy)

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.open_pause()
                return

            if event.key == pygame.K_SPACE:
                self.player.press_space(pygame.time.get_ticks())

            if event.key == pygame.K_e:
                self.open_inventory()
                return

            if event.key == pygame.K_t:
                self.open_chat()
                return

            if event.key == pygame.K_q:
                self.throw_held(bool(event.mod & (pygame.KMOD_CTRL | pygame.KMOD_META)))
                return

            if event.key == pygame.K_SLASH:
                self.open_chat("/")
                return

            if pygame.K_1 <= event.key <= pygame.K_9:
                self.select_slot(event.key - pygame.K_1)

            if event.key == pygame.K_d:
                self.right = 1
            if event.key == pygame.K_a:
                self.right = -1

            if event.key == pygame.K_w:
                self.forwad = 1
            if event.key == pygame.K_s:
                self.forwad = -1

        if event.type == pygame.KEYUP:
            if event.key in (pygame.K_a, pygame.K_d):
                self.right = 0

            if event.key in (pygame.K_w, pygame.K_s):
                self.forwad = 0

    def events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False

            if self.menu_open:
                self.menu_events(event)
            elif self.open_screen is not None:
                self.screen_events(event)
            elif self.chat.open:
                self.chat_events(event)
            else:
                self.game_events(event)

            # Пока вводится текст (имя мира или чат), буквы i и h нужны для него.
            typing = (self.menu_open and self.menu.typing) or self.chat.open

            if event.type == pygame.KEYDOWN and not typing:
                if event.key in (pygame.K_F3, pygame.K_i):
                    self.f3_open = not self.f3_open

                if event.key in (pygame.K_F1, pygame.K_h):
                    self.gui_hidden = not self.gui_hidden

        self.chat.end_of_events()

    def open_chat(self, prefix=""):
        self.chat.show(prefix)
        self.mining.stop()
        self.free_cursor(True)

        self.forwad = 0
        self.right = 0

    def chat_events(self, event):
        if event.type == pygame.KEYDOWN:
            line = self.chat.key(event)

            if not self.chat.open:
                self.free_cursor(False)

            if line is not None:
                self.submit_chat(line)

        elif event.type == pygame.TEXTINPUT:
            self.chat.text(event.text)

    def submit_chat(self, line):
        if not line.startswith("/"):
            self.chat.add(f"<{PLAYER_NAME}> {line}")
            return

        for text, color in commands.run(self, line):
            self.chat.add(text, color)

    # Для команд: координаты как в оригинале, x, y вверх (высота ног), z.

    def player_position(self):
        x, y, z = self.camera.position

        return (x, -(y + FEET), z)

    def teleport(self, x, height, z):
        self.camera.position = (x, -height - FEET, z)
        self.player.velocity = 0.0

        # Телепорт не падение: урона при приземлении быть не должно.
        self.player.fall_start = None

    def set_game_mode(self, mode):
        self.game_mode = mode
        self.player.survival = self.survival

        if self.survival:
            self.player.set_flying(False)

    def kill_player(self):
        player = self.player
        player.health = 0
        player.dead = True
        player.events.append(("hurt",))

    def run(self):
        while self.running:
            dt = self.clock.tick(self.FPS) / 1000.0
            self.events()
            self.update(dt)
            self.render()

        self.save_world()

        pygame.quit()
        sys.exit()


if __name__ == "__main__":
    Game(*parse_arguments(sys.argv[1:])).run()
