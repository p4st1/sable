from engine import Engine
from camera import Camera
from object3D import Object3D
from world import World, ray_box_distance
from mesh import Mesh
from block import FACING_BLOCKS, TORCHES, Block, FacingState, ids_where
import chunk as chunk_module
from chunk import BRIGHTNESS, NIGHT_DARKNESS, Y_MAX, Y_MIN, Chunk, in_height, packed_brightness
from config import Config
from renderer import Renderer
from gui import Gui
from menu import Menu
from chat import GRAY, RED, YELLOW, Chat
import commands
import daytime
import mobs
import plants
import textures
from fire import FIRE, FIRE_TEXTURE, FireSystem, fire_frames
import fire as fire_module
import burning
import projectiles
from entities import PICKUP_DELAY, THROW_DELAY, DrawObject, ItemEntity, ItemModels, items_from_json, items_to_json, scatter_velocity
from collision import player_box
from mining import BREAK_COOLDOWN, HIT_INTERVAL, HIT_VOLUME, Mining, break_time, can_harvest, crack_object, wear_for
from containers import Furnace, containers_from_json, containers_to_json, make_container
import armor
from figure import PlayerFigure, skin_for
from items import BUCKETS, FOODS, TOOLS, PlayerInventory, Stack, armor_from_json, bonus_drops, drop_for, insert, is_placeable, max_uses, slots_from_json, slots_to_json
from screens import ChestScreen, CraftingScreen, CreativeScreen, FurnaceScreen, InventoryScreen
from hand import Hand
from collision import FEET, GAP, box_touches_block, box_touches_blocks
from bed import TOP as BED_TOP
from bed import is_bed, other_half
from door import facing_side, is_door
from player import HURT_TIME, MAX_AIR, MAX_HEALTH, Player
from settings import Settings
from sound import Music, Sounds
from worlds import WORLDS, parse_arguments
from multiplayer import HOST_ID, ClientSession, ConnectError, HostSession, clean_name, load_player_data, vector, world_time

import storage
import streaming
import water
from terrain import TerrainGenerator, random_seed

import math
import numpy as np
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

# Сколько при входе на сервер ждать изменённых чанков под ногами.
TERRAIN_WAIT = 5.0

# Громкость звуков относительно полной.
STEP_VOLUME = 0.25
LAND_VOLUME = 0.5
CHEST_VOLUME = 0.5
EAT_VOLUME = 0.6
TOOL_BREAK_VOLUME = 0.8
PICKUP_VOLUME = 0.2
# Саженцы: раз в столько секунд осматриваем столько чанков.
PLANT_TICK = 1.0
# Лава пробует поджечь горючее рядом в среднем раз в столько секунд на клетку.
LAVA_FIRE_TIME = 60.0
# Страшные звуки: раз в столько секунд, если вокруг темно и над головой не небо,
# с расстояния в столько блоков.
MOOD_INTERVAL = (45.0, 150.0)
MOOD_LIGHT = 5
MOOD_DISTANCE = (4.0, 10.0)
MOOD_VOLUME = 0.9
# Лава и огонь рядом: раз в столько секунд пробуем, что-нибудь звучит, и откуда.
AMBIENT_TICK = 0.5
AMBIENT_RADIUS = 12
LAVA_POP_VOLUME = 0.3
LAVA_AMBIENT_VOLUME = 0.45
FIRE_AMBIENT_VOLUME = 0.6
LAVA_FRAME_RATE = 10
# Лава жжёт: урон за касание и сколько секунд потом горишь, как в оригинале.
LAVA_DAMAGE = 4
LAVA_BURN_TIME = 15.0
# Лава в глазах: экран заливает оранжевым.
LAVA_VIEW = (210, 70, 10)
LAVA_VIEW_ALPHA = 225
PLANT_CHUNKS_PER_TICK = 8
# Размытие мира за главным меню: во сколько раз уменьшаем и радиус размытия в малом размере.
TITLE_BLUR_SCALE = 4
TITLE_BLUR_RADIUS = 3
# Лук: пока натянут, игрок идёт впятеро медленнее, а вид чуть приближается.
BOW_SLOWDOWN = 0.2
BOW_ZOOM = 0.15
# Натянутый лук в руке: стадии картинки по доле натяжения.
BOW_STAGES = (0.65, 0.9)
# Застрявшую стрелу подбирают, подойдя на столько.
ARROW_PICKUP_REACH = 1.0
# Вещи погибшего разлетаются во все стороны с такой скоростью и чуть вверх,
# а подобрать их можно через пару секунд.
DEATH_SCATTER = 6.0
DEATH_LIFT = 4.0
# Сон: столько секунд экран темнеет, после чего наступает утро. Глаза лёжа
# чуть выше матраса. Спать можно, когда небо потемнело хотя бы на SLEEP_DARKNESS
# уровней, и если рядом нет враждебных мобов.
SLEEP_TIME = 5.0
SLEEP_FADE = 2.0
SLEEP_DARK = 0.9
LYING_EYE = 0.25
SLEEP_DARKNESS = 4
MONSTER_RANGE = (8.0, 5.0)
# Животных бьют ближе, чем ломают блоки, как в оригинале.
MOB_REACH = 3.5
CREATIVE_MOB_REACH = 5.0
MOB_VOLUME = 0.6
MOB_STEP_VOLUME = 0.15
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
    def __init__(self, world_name=None, new_world=False, options=None):
        self.settings = Settings.load()
        options = options or {}

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
        self.mob_models = mobs.MobModels(self.engine)
        self.burning_model = burning.BurningModel(self.engine)
        # Кадры пламени и лавы: загружаются при первом кадре.
        self.fire_frames = None
        self.lava_frames = None
        # Сколько секунд натягивается лук, или None.
        self.bow_draw = None
        self.arrow_model = projectiles.ArrowModel(self.engine)
        self.figure = PlayerFigure(self.engine)

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

        # Сетевая игра: multiplayer.HostSession у хозяина, ClientSession у гостя, иначе None.
        self.net = None
        # Игроки, заходившие в этот мир по сети, по именам (их хранит хозяин).
        self.saved_players = {}

        if options.get("name"):
            self.settings.player_name = clean_name(options["name"])

        if world_name is None:
            self.show_title()
        else:
            self.enter_world(world_name, world_name, new_world=new_world)

            if options.get("lan"):
                self.open_to_lan()

        if options.get("join"):
            self.join_server(options["join"], self.settings.player_name)

    @property
    def in_world(self):
        return self.world_folder is not None or self.net is not None

    @property
    def is_client(self):
        """Игра в чужом мире: мир ведёт хозяин, а мы присылаем ему свои правки."""
        return self.net is not None and not self.net.is_host

    @property
    def player_name(self):
        return self.net.name if self.net is not None else self.settings.player_name

    @property
    def player_skin(self):
        return skin_for(self.player_name)

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
        self.hostile_timer = 0.0
        # Огонь: где горит и когда у каждого следующий тик.
        self.fire = FireSystem(self.world)
        # Звуки вокруг: страшные звуки пещер и бульканье лавы, треск огня.
        self.mood_timer = random.uniform(*MOOD_INTERVAL)
        self.ambient_timer = 0.0
        # Рост саженцев: таймер и какой чанк осматривать следующим.
        self.plant_timer = 0.0
        self.plant_cursor = 0
        # Правило мира keepInventory: погибший игрок сохраняет вещи. По умолчанию нет.
        self.keep_inventory = False
        # Сон: None или {"head": клетка изголовья, "time": сколько спим}. bed: где возрождаться.
        self.sleeping = None
        self.bed = None
        self.water_time = 0.0
        self.lava_time = 0.0
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
        self.loader.on_generate = self.populate_chunk

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
            self.saved_players = {}

        if load:
            meta = storage.load_world(self.world, self.player, folder, load_chunks=not infinite)

            # Животные до первых чанков: иначе в уже заселённых чанках появились бы снова.
            self.world.mobs = mobs.mobs_from_json(meta.get("mobs"))
            self.world.spawned_chunks = mobs.spawned_from_json(meta.get("spawned_chunks"))

            rules = meta.get("game_rules")
            self.keep_inventory = isinstance(rules, dict) and rules.get("keepInventory") is True

            saved_bed = meta.get("bed")

            if isinstance(saved_bed, list) and len(saved_bed) == 3 and all(type(value) is int for value in saved_bed):
                self.bed = tuple(saved_bed)

            saved_time = meta.get("time")
            self.world.time = float(saved_time) if type(saved_time) in (int, float) and saved_time >= 0 else daytime.START_TIME

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

            players = meta.get("players")
            self.saved_players = players if isinstance(players, dict) else {}

            # Вода, которая текла в момент сохранения, дотекает.
            water.water_cells_to_settle(self.world)

            if "inventory" in meta:
                self.inventory = PlayerInventory(slots_from_json(meta["inventory"], len(self.inventory.slots)), armor_from_json(meta.get("armor")))
            else:
                self.inventory = self.starting_inventory()
        elif infinite:
            self.start_terrain(random_seed() if seed is None else seed, folder)
            self.game_mode = game_mode
            self.inventory = self.starting_inventory()
        else:
            test_world.generate(self.world)

            for chunk in list(self.world.chunks.values()):
                self.populate_chunk(chunk)

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

        self.finish_entering(infinite)

    def finish_entering(self, infinite):
        """Общее окончание входа в мир, свой или по сети."""
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
        # Без keepInventory вещи погибшего в выживании разлетаются вокруг.
        if self.survival and not self.keep_inventory:
            self.drop_everything()

        self.menu.show_death()
        self.set_menu(True)

        self.forwad = 0
        self.right = 0

    def drop_everything(self):
        """Весь инвентарь и броня вылетают в мир там, где погиб игрок."""
        x, y, z = self.camera.position
        center = (x, y + 0.7, z)

        for slots in (self.inventory.slots, self.inventory.armor):
            for index, stack in enumerate(slots):
                if stack is None:
                    continue

                angle = random.uniform(0, math.tau)
                speed = random.uniform(0, DEATH_SCATTER)
                velocity = (math.sin(angle) * speed, -DEATH_LIFT * random.uniform(0.5, 1.0), math.cos(angle) * speed)

                self.add_item(stack, center, velocity, THROW_DELAY)
                slots[index] = None

    def set_game_rule(self, name, value):
        """Команда /gamerule. В сетевой игре правило хозяин рассылает гостям."""
        if name == "keepInventory":
            self.keep_inventory = value

        if self.net is not None and self.net.is_host:
            self.net.send_rules()

    def respawn(self):
        position = self.spawn_point

        # Возрождение у кровати, если она ещё стоит.
        if self.bed is not None:
            block = self.world.get_block(*self.bed)

            if block is not None and is_bed(block.type):
                position = self.wake_spot(self.bed)
            else:
                self.chat.add("Your home bed was missing or obstructed", GRAY)
                self.bed = None

        self.player.respawn(position)
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
        self.stop_network()
        self.show_title()

    def stop_network(self):
        if self.net is not None:
            self.net.stop()
            self.net = None

    # Сетевая игра.

    def open_to_lan(self):
        """Кнопка Open to LAN: свой мир становится сервером для игроков в локальной сети."""
        if self.net is not None or self.world_folder is None:
            return

        try:
            self.net = HostSession(self)
        except OSError as error:
            self.chat.add(f"Could not open the game to LAN: {error}", RED)
            return

        self.chat.add(f"Local game hosted on {self.net.address}", YELLOW)
        self.set_menu(False)

    def join_server(self, address, name):
        name = clean_name(name)
        self.settings.player_name = name
        self.settings.last_server = address.strip()[:64]
        self.save_settings()

        self.show_loading(f"Connecting to {address}...")

        try:
            session = ClientSession.connect(self, address, name, wait=pygame.event.pump)
        except ConnectError as error:
            self.menu.show_message("Failed to connect to the server", str(error), 'multiplayer')
            return

        try:
            self.enter_remote_world(session)
        except (KeyError, TypeError, ValueError) as error:
            session.connection.close()
            self.net = None
            self.show_title()
            self.menu.show_message("Failed to connect to the server", f"Bad world data: {error}", 'multiplayer')

    def enter_remote_world(self, session):
        """Входит в мир хозяина по его приветствию (см. HostSession.hello)."""
        welcome = session.welcome
        infinite = welcome["infinite"] is True
        spawn = vector(welcome["spawn"])

        if infinite and type(welcome["seed"]) is not int:
            raise ValueError("у бесконечного мира нет сида")

        self.create_world(spawn, (0, 0, 0))
        self.world.time = world_time(welcome.get("time", daytime.START_TIME))
        self.keep_inventory = welcome.get("keep_inventory") is True
        self.saved_players = {}
        self.net = session
        session.attach(self.world)

        if infinite:
            self.start_terrain(welcome["seed"], None)
            self.loader.remote = session
        else:
            for chunk in session.initial_chunks:
                self.world.add_chunk(chunk)

        data = load_player_data(welcome.get("player"), len(self.inventory.slots))
        mode = welcome.get("game_mode")
        self.game_mode = data.get("game_mode", mode if mode in storage.GAME_MODES else "survival")

        self.camera.position = data.get("position", spawn)
        self.camera.rotation = data.get("rotation", (0, 0, 0))
        self.player.flying = data.get("flying", False) and not self.survival
        self.player.health = min(data.get("health", MAX_HEALTH), MAX_HEALTH)
        self.inventory = PlayerInventory(data["inventory"], data.get("armor")) if "inventory" in data else self.starting_inventory()
        self.spawn_point = data.get("spawn", spawn)

        self.player.survival = self.survival
        self.player.spawn = self.spawn_point

        self.world_folder = None
        self.world_name = str(welcome.get("world_name", "Server"))
        self.world_generator = welcome.get("generator")

        if infinite:
            self.wait_for_terrain(session)

            if self.net is not session:
                return

        self.finish_entering(infinite)

    def wait_for_terrain(self, session):
        """Изменённые чанки под ногами приходят с сервера: ждём их, чтобы не упасть."""
        self.show_loading("Downloading terrain...")
        deadline = time.monotonic() + TERRAIN_WAIT
        x, _, z = self.camera.position

        while time.monotonic() < deadline:
            self.loader.ensure(x, z)

            if all(self.loader.is_loaded(x + dx * Chunk.SIZE, z + dz * Chunk.SIZE) for dx in (-1, 0, 1) for dz in (-1, 0, 1)):
                return

            session.update(0.0)

            if self.net is not session:
                return

            pygame.event.pump()
            time.sleep(0.01)

    def connection_lost(self, reason):
        """Сервер закрылся, выгнал нас или пропала сеть."""
        session, self.net = self.net, None

        if session is not None:
            session.detach()

        self.open_screen = None
        self.show_title()
        self.menu.show_message("Connection Lost", reason or "Disconnected", 'title')

    def player_data(self):
        """Что хозяин хранит о нас в своём мире."""
        return {
            "position": list(self.camera.position),
            "rotation": list(self.camera.rotation),
            "health": self.player.health,
            "inventory": slots_to_json(self.inventory.slots),
            "armor": slots_to_json(self.inventory.armor),
            "flying": self.player.flying,
            "spawn": list(self.spawn_point),
            "game_mode": self.game_mode,
        }

    def receive_stack(self, stack):
        """Хозяин отдал нам подобранный предмет. Что не влезло, выпадает обратно."""
        self.sounds.play("entity.item.pickup", PICKUP_VOLUME)

        if insert(self.inventory.slots, stack) > 0:
            self.throw(stack)

    def open_remote_container(self, position, container):
        """Хозяин прислал сундук или печку, которые мы открыли."""
        if self.open_screen is not None or self.menu_open or self.player.dead:
            self.net.close_container(position, container)
            return

        self.world.containers[position] = container

        if container.kind == "chest":
            self.show_screen(ChestScreen(self, container))
            self.sounds.play_at("block.chest.open", self.cell_center(position), self.camera, CHEST_VOLUME)
            self.chest_position = position
        else:
            self.show_screen(FurnaceScreen(self, container))

    def world_sound(self, event, position, volume=1.0):
        """Звук в мире, который слышат и другие игроки."""
        self.sounds.play_at(event, position, self.camera, volume)

        if self.net is not None:
            self.net.sound(position, event=event, volume=volume)

    def quit(self):
        self.running = False

    def show_title(self):
        """Главное меню: за ним показывается мир, который нигде не сохраняется."""
        self.world_folder = None
        self.world_name = None
        self.world_generator = None

        self.create_world((0, 0, 0), (0, 0, 0))
        self.world.time = daytime.TITLE_TIME

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

        # Спящий встаёт с кровати, иначе загрузился бы внутри неё.
        self.wake_up()

        # Погибший игрок выходит из мира уже возрождённым.
        if self.player.dead:
            self.player.respawn(self.spawn_point)

        # Чужой мир сохраняет хозяин, ему же уходят наши инвентарь и место.
        if self.is_client:
            self.net.send_save()
            return

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
                "armor": slots_to_json(self.inventory.armor),
                "containers": containers_to_json(self.world.containers),
                "items": items_to_json(self.world.items),
                "mobs": mobs.mobs_to_json(self.world.mobs),
                "time": round(self.world.time, 2),
                "bed": list(self.bed) if self.bed is not None else None,
                "game_rules": {"keepInventory": self.keep_inventory},
                "spawned_chunks": mobs.spawned_to_json(self.world.spawned_chunks),
                "players": self.saved_players,
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
                data['shades'],
                data.get('night_shades')
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

        # Лава непрозрачная и светится сама: рисуется вместе с блоками, а не с водой.
        lava = water.build_water_mesh(chunk, self.world, water.LAVA)

        if lava is not None:
            lava_object = Object3D(Mesh(lava['points'], lava['triangles'], lava['uvs'], self.engine.load_texture(water.LAVA_TEXTURE), lava['shades'], lava['night_shades']))
            lava_object.position = (chunk.chunk_x * chunk.SIZE, 0, chunk.chunk_z * chunk.SIZE)
            lava_object.static = True
            lava_object.build_world_points()
            objects.append(lava_object)

        # Огонь из сохранения или с сервера тоже начинает жить.
        self.fire.scan(chunk, ids_where(lambda block: block.type == FIRE))

        self.world.set_chunk_objects(chunk, objects)
        self.build_water(chunk)

    def build_water(self, chunk):
        """Меш воды чанка. Вода не закрывает граней блоков, поэтому её меш собирается отдельно."""
        data = water.build_water_mesh(chunk, self.world)
        objects = []

        if data is not None:
            water_object = Object3D(Mesh(data['points'], data['triangles'], data['uvs'], self.engine.load_texture(water.WATER_TEXTURE), data['shades'], data['night_shades']))
            water_object.position = (chunk.chunk_x * chunk.SIZE, 0, chunk.chunk_z * chunk.SIZE)
            water_object.static = True
            water_object.build_world_points()
            objects.append(water_object)

        self.world.set_liquid_objects(chunk, objects)

    def tick_water(self, dt):
        """Вода течёт шагами раз в water.TICK. Перестраиваются только меши воды.

        В чужом мире воду считает хозяин и присылает изменённые клетки.
        """
        if self.is_client:
            self.world.water_updates.clear()
            self.world.lava_updates.clear()
            return

        self.tick_lava(dt)
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

    def tick_lava(self, dt):
        """Лава течёт реже воды. Её меш входит в меш чанка (она непрозрачная и светится),
        поэтому меняется весь чанк, а свет от неё задевает и соседей."""
        self.lava_time += dt

        if self.lava_time < water.LAVA.tick:
            return

        self.lava_time = 0.0

        if not self.world.lava_updates:
            return

        for key in water.tick(self.world, water.LAVA):
            self.rebuild_around(key[0] * Chunk.SIZE + 8, key[1] * Chunk.SIZE + 8)

    def tick_fire(self, dt):
        """Огонь горит, перекидывается и гаснет. В чужом мире его считает хозяин."""
        if self.is_client:
            return

        changed = self.fire.update(dt, self.mob_loaded)

        for cell in changed:
            self.world.notify(*cell)

        for key in {(cell[0] // Chunk.SIZE, cell[2] // Chunk.SIZE) for cell in changed}:
            self.rebuild_around(key[0] * Chunk.SIZE + 8, key[1] * Chunk.SIZE + 8)

    def use_flint_and_steel(self, target):
        """Огниво поджигает клетку перед блоком, если огню там есть на чём гореть."""
        self.hand.swing()

        if target is None or not in_height(target[1]):
            return

        if self.fire.ignite(target):
            self.world.notify(*target)
            self.rebuild_around(target[0], target[2])
            self.world_sound("item.flintandsteel.use", self.cell_center(target))

            if self.survival:
                stack = self.held_stack()
                stack.damage += 1

                if stack.damage >= max_uses("flint_and_steel"):
                    self.inventory.slots[self.selected_slot] = None
                    self.sounds.play("entity.item.break", TOOL_BREAK_VOLUME)

    def touches_fire(self, low, high):
        """Касается ли коробка от low до high клетки с огнём."""
        for x in range(math.floor(low[0]), math.floor(high[0]) + 1):
            for y in range(math.floor(low[1]), math.floor(high[1]) + 1):
                for z in range(math.floor(low[2]), math.floor(high[2]) + 1):
                    block = self.world.get_block(x, y, z)

                    if block is not None and block.type == FIRE:
                        return True

        return False

    def update_player_fire(self, dt):
        """Игрок в огне получает урон и загорается на несколько секунд. Вода гасит."""
        player = self.player

        if player.dead:
            player.fire_time = 0.0
            return

        if self.touches_fire(*player_box(self.camera.position)):
            player.fire_time = fire_module.BURN_TIME
            player.damage(1)

        if player.in_lava:
            player.fire_time = LAVA_BURN_TIME
            player.damage(LAVA_DAMAGE)

        if player.in_water:
            player.fire_time = 0.0

        if player.fire_time <= 0:
            player.burn_clock = 0.0
            return

        player.fire_time = max(0.0, player.fire_time - dt)
        player.burn_clock += dt

        if player.burn_clock >= 1.0:
            player.burn_clock -= 1.0
            player.damage(1)

    def lava_ignites(self, chunk, lava_ids, lap):
        """Лава поджигает горючее рядом, как в оригинале: в среднем раз в LAVA_FIRE_TIME
        каждая клетка лавы пробует зажечь пустую клетку над собой, рядом с горючим."""
        chance = lap / LAVA_FIRE_TIME
        changed = []

        for local_x, row, local_z in np.argwhere(np.isin(chunk.ids, lava_ids)):
            if random.random() >= chance:
                continue

            x = chunk.chunk_x * Chunk.SIZE + int(local_x) + random.randint(-1, 1)
            y = int(row) + Y_MIN - random.randint(1, 3)
            z = chunk.chunk_z * Chunk.SIZE + int(local_z) + random.randint(-1, 1)

            if self.fire.has_fuel_around((x, y, z)) and self.fire.ignite((x, y, z)):
                changed.append((x, y, z))

        for cell in changed:
            self.world.notify(*cell)
            self.rebuild_around(cell[0], cell[2])

    def update_ambient_sounds(self, dt):
        """Звуки вокруг игрока: жуткие звуки в темноте пещер, лава и огонь поблизости."""
        if not self.in_world or self.player.dead:
            return

        eye = self.camera.position
        self.mood_timer -= dt

        if self.mood_timer <= 0:
            self.mood_timer = random.uniform(*MOOD_INTERVAL)
            x, y, z = (math.floor(value) for value in eye)
            packed = self.world.packed_light_at(x, y, z)
            darkness = round(self.night_amount() * NIGHT_DARKNESS)

            # Под крышей (небо не видно) и темно: в пещере что-то звучит.
            if (packed & 15) < 15 and mobs.spawn_light(packed, darkness) <= MOOD_LIGHT:
                angle = random.uniform(0, math.tau)
                distance = random.uniform(*MOOD_DISTANCE)
                where = (eye[0] + math.sin(angle) * distance, eye[1] + random.uniform(-2, 2), eye[2] + math.cos(angle) * distance)
                self.sounds.cave_sound(where, self.camera, MOOD_VOLUME)

        self.ambient_timer += dt

        if self.ambient_timer < AMBIENT_TICK:
            return

        self.ambient_timer = 0.0
        lava_cells, fire_cells = self.nearby_cells(("lava",), (FIRE,))

        # Чем больше лавы рядом, тем чаще она булькает. Звучит только открытая сверху.
        lava_cells = [cell for cell in lava_cells if self.world.get_block(cell[0], cell[1] - 1, cell[2]) is None]

        if lava_cells and random.random() < min(0.6, len(lava_cells) * 0.02):
            cell = self.cell_center(random.choice(lava_cells))

            if random.random() < 0.7:
                self.sounds.play_at("block.lava.pop", cell, self.camera, LAVA_POP_VOLUME)
            else:
                self.sounds.play_at("block.lava.ambient", cell, self.camera, LAVA_AMBIENT_VOLUME)

        if fire_cells and random.random() < min(0.7, len(fire_cells) * 0.1):
            self.sounds.play_at("block.fire.ambient", self.cell_center(random.choice(fire_cells)), self.camera, FIRE_AMBIENT_VOLUME)

    def nearby_cells(self, *groups):
        """Клетки блоков из каждой группы типов в радиусе AMBIENT_RADIUS от глаз."""
        x, y, z = (math.floor(value) for value in self.camera.position)
        results = []

        for types in groups:
            numbers = np.array(ids_where(lambda block, types=types: block.type in types), dtype=np.uint16)
            found = []

            if len(numbers):
                for chunk_x in range((x - AMBIENT_RADIUS) // Chunk.SIZE, (x + AMBIENT_RADIUS) // Chunk.SIZE + 1):
                    for chunk_z in range((z - AMBIENT_RADIUS) // Chunk.SIZE, (z + AMBIENT_RADIUS) // Chunk.SIZE + 1):
                        chunk = self.world.chunks.get((chunk_x, chunk_z))

                        if chunk is None:
                            continue

                        low = max(0, y - AMBIENT_RADIUS - Y_MIN)
                        rows = chunk.ids[:, low:y + AMBIENT_RADIUS - Y_MIN + 1, :]

                        for local_x, row, local_z in np.argwhere(np.isin(rows, numbers)):
                            cell = (chunk_x * Chunk.SIZE + int(local_x), int(row) + low + Y_MIN, chunk_z * Chunk.SIZE + int(local_z))

                            if abs(cell[0] - x) <= AMBIENT_RADIUS and abs(cell[2] - z) <= AMBIENT_RADIUS:
                                found.append(cell)

            results.append(found)

        return results

    def tick_plants(self, dt):
        """Саженцы растут: каждую секунду осматриваем несколько загруженных чанков по кругу.

        Каждый чанк осматривается раз в несколько секунд, поэтому шанс вырасти за
        осмотр пропорционален этому промежутку: в среднем дерево через GROW_TIME.
        В чужом мире деревья растит хозяин.
        """
        if self.is_client:
            return

        self.plant_timer += dt

        if self.plant_timer < PLANT_TICK:
            return

        self.plant_timer = 0.0
        keys = list(self.world.chunks)

        if not keys:
            return

        sapling_ids = np.array(ids_where(lambda block: block.type in plants.SAPLINGS), dtype=np.uint16)
        lava_ids = np.array(water.water_ids(water.LAVA), dtype=np.uint16)

        # За сколько секунд чанки обходятся полностью.
        lap = PLANT_TICK * max(1, math.ceil(len(keys) / PLANT_CHUNKS_PER_TICK))
        chance = lap / plants.GROW_TIME
        darkness = round(self.night_amount() * NIGHT_DARKNESS)

        for _ in range(min(PLANT_CHUNKS_PER_TICK, len(keys))):
            self.plant_cursor = (self.plant_cursor + 1) % len(keys)
            chunk = self.world.chunks[keys[self.plant_cursor]]

            if len(lava_ids):
                self.lava_ignites(chunk, lava_ids, lap)

            if len(sapling_ids) == 0:
                continue

            for local_x, row, local_z in np.argwhere(np.isin(chunk.ids, sapling_ids)):
                if random.random() >= chance:
                    continue

                x = chunk.chunk_x * Chunk.SIZE + int(local_x)
                z = chunk.chunk_z * Chunk.SIZE + int(local_z)
                y = int(row) + Y_MIN

                if mobs.spawn_light(self.world.packed_light_at(x, y, z), darkness) < plants.GROW_LIGHT:
                    continue

                sapling = self.world.get_block(x, y, z).type
                changed = plants.grow_tree(self.world, x, y, z, sapling)

                if changed:
                    for cell in changed:
                        self.world.notify(*cell)

                    for dx in (-3, 0, 3):
                        for dz in (-3, 0, 3):
                            self.rebuild_around(x + dx, z + dz)

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

    def rebuild_cells(self, full, water_only=()):
        """Перестраивает меши после пачки правок с сервера: каждый чанк один раз.

        full: столбцы (x, z) с изменёнными блоками, water_only: где поменялась
        только вода, там хватит меша воды.
        """
        sides = ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1))
        now, stale, water_keys = set(), set(), set()

        for x, z in full:
            now.update(((x + dx) // Chunk.SIZE, (z + dz) // Chunk.SIZE) for dx, dz in sides)
            stale.update((x // Chunk.SIZE + dx, z // Chunk.SIZE + dz) for dx in (-1, 0, 1) for dz in (-1, 0, 1))

        for x, z in water_only:
            water_keys.update(((x + dx) // Chunk.SIZE, (z + dz) // Chunk.SIZE) for dx, dz in sides)

        for key in now:
            chunk = self.world.chunks.get(key)

            if chunk is not None and chunk.meshed:
                self.build_chunk(chunk)
                self.stale_chunks.discard(key)

        for key in stale - now:
            chunk = self.world.chunks.get(key)

            if chunk is not None and chunk.meshed:
                self.stale_chunks.add(key)

        for key in water_keys - now:
            chunk = self.world.chunks.get(key)

            if chunk is not None and chunk.meshed:
                self.build_water(chunk)

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

    # Кровать и сон.

    def remove_bed(self, x, y, z):
        """Убирает обе половинки кровати. Кто на ней спал, просыпается."""
        halves = self.world.bed_halves(x, y, z)

        for half in halves:
            self.world.notify(*half)

        self.world.remove_bed(x, y, z)

        for half in halves:
            self.rebuild_around(half[0], half[2])

        if self.sleeping is not None and self.sleeping["head"] in halves:
            self.wake_up()

    def try_sleep(self, position, block):
        """Правый клик по кровати: ложимся, если ночь и рядом нет монстров."""
        if self.sleeping is not None or self.player.dead:
            return

        if self.net is not None:
            self.chat.add("You can't sleep in a LAN game yet", GRAY)
            return

        if round(self.night_amount() * NIGHT_DARKNESS) < SLEEP_DARKNESS:
            self.chat.add("You can only sleep at night", GRAY)
            return

        head = position if block.state.head else other_half(position, block.state)
        foot = other_half(head, block.state._replace(head=True))
        across, up = MONSTER_RANGE

        for mob in self.world.mobs:
            dx, dy, dz = (mob.position[axis] - (head[axis] + 0.5) for axis in range(3))

            if mob.kind.hostile and not mob.dead and abs(dx) < across and abs(dz) < across and abs(dy) < up:
                self.chat.add("You may not rest now, there are monsters nearby", GRAY)
                return

        # Кровать становится точкой возрождения, как в оригинале.
        self.bed = head
        self.sleeping = {"head": head, "time": 0.0}
        self.mining.stop()
        self.player.velocity = 0.0
        self.player.push = [0.0, 0.0]

        # Лёжа на подушке, лицом к изножью.
        self.camera.position = (head[0] + 0.5, head[1] + BED_TOP - LYING_EYE, head[2] + 0.5)
        self.camera.rotation = (0.25, math.atan2(foot[0] - head[0], foot[2] - head[2]), 0)

    def update_sleep(self, dt):
        """Спим: экран темнеет, а потом наступает утро. Удар или сломанная кровать будят."""
        sleeping = self.sleeping
        sleeping["time"] += dt
        block = self.world.get_block(*sleeping["head"])

        if block is None or not is_bed(block.type) or self.player.hurt_time > 0 or self.player.dead:
            self.wake_up()
            return

        if sleeping["time"] >= SLEEP_TIME:
            # Утро следующего дня: тик 0 новых суток.
            day = math.floor(self.world.time / daytime.DAY_LENGTH)
            self.world.time = (day + 1) * daytime.DAY_LENGTH
            self.wake_up()

    def wake_up(self):
        if self.sleeping is None:
            return

        head = self.sleeping["head"]
        self.sleeping = None
        self.camera.position = self.wake_spot(head)
        self.player.velocity = 0.0
        self.player.fall_start = None

    def wake_spot(self, head):
        """Где встать после сна или возродиться: на кровати, если над ней есть место,
        иначе в свободной клетке рядом. Возвращает положение глаз."""
        x, y, z = head
        on_bed = (x + 0.5, y + BED_TOP - FEET - GAP, z + 0.5)
        low, high = player_box(on_bed)

        if not box_touches_blocks(self.world, low, (high[0], y + BED_TOP - GAP, high[2])):
            return on_bed

        for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1), (2, 0), (-2, 0), (0, 2), (0, -2)):
            cx, cz = x + dx, z + dz
            ground = self.world.get_block(cx, y + 1, cz)

            if ground is None or not ground.is_cube:
                continue

            if self.world.get_block(cx, y, cz) is None and self.world.get_block(cx, y - 1, cz) is None:
                return (cx + 0.5, y + 1 - FEET - GAP, cz + 0.5)

        return on_bed

    def night_amount(self):
        """Доля ночи сейчас: 0 днём, 1 глубокой ночью."""
        return 1 - daytime.daylight(daytime.celestial_angle(self.world.time))

    def brightness_at(self, x, y, z):
        """Яркость модели в точке (предмет, животное, рука) с учётом времени суток."""
        packed = self.world.packed_light_at(math.floor(x), math.floor(y), math.floor(z))

        return packed_brightness(packed, self.night_amount())

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
        elif is_bed(block.type):
            self.remove_bed(x, y, z)
            self.block_sound(block.type, "break", target)
        else:
            self.block_sound(block.type, "break", target)

            self.world.remove_block(x, y, z)
            self.world.notify(x, y, z)

            # Сундук и печка высыпают содержимое. Если его держит открытым
            # другой игрок, высыплется то, что он вернёт при закрытии.
            held_by_other = self.net is not None and self.net.is_host and self.net.container_broken(target)
            container = self.world.containers.pop(target, None)

            if container is not None and not held_by_other:
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

            # Кровать без опоры тоже падает.
            elif above is not None and is_bed(above.type):
                self.remove_bed(x, y - 1, z)
                self.drop(Stack(above.type), (x, y - 1, z))

            # Огонь без опоры гаснет сразу.
            elif above is not None and above.type == FIRE:
                self.world.remove_block(x, y - 1, z)
                self.world.notify(x, y - 1, z)

            # Факел и растения тоже падают, если из-под них выбили блок.
            elif above is not None and (above.type in TORCHES or plants.is_plant(above.type)):
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

        self.add_item(stack, position, scatter_velocity(), PICKUP_DELAY)

    def add_item(self, stack, position, velocity, delay):
        """Предмет в мир. В чужом мире предметы живут у хозяина."""
        if self.is_client:
            self.net.drop_item(stack, position, velocity, delay)
        else:
            self.world.items.append(ItemEntity(stack, position, velocity, delay))

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

        self.add_item(stack, (x, y + THROW_DROP, z), velocity, THROW_DELAY)

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
        """Предметы падают, со временем исчезают, а рядом с игроком подбираются.

        В чужом мире предметы считает хозяин, а клиент их только рисует.
        """
        if self.is_client:
            return

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

            if entity.pickup_delay > 0:
                continue

            if not self.player.dead and entity.touches(low, high):
                before = entity.stack.count
                left = insert(self.inventory.slots, entity.stack.copy())

                if left < before:
                    picked = True
                    entity.stack.count = left

                    if left == 0:
                        world.items.remove(entity)
                        continue

            # Рядом с другим игроком: предмет уходит ему.
            if self.net is not None and self.net.pickup(entity):
                world.items.remove(entity)

        if picked:
            self.sounds.play("entity.item.pickup", PICKUP_VOLUME)

    # Животные. В сетевой игре их пока нет: ни у хозяина, ни у гостей.

    @property
    def mobs_enabled(self):
        return self.net is None

    def populate_chunk(self, chunk):
        """Новый чанк от генератора: может быть, в нём пасётся стайка."""
        mobs.populate(self.world, chunk, self.seed or 0)

    def mob_loaded(self, x, z):
        return self.loader is None or self.loader.is_loaded(x, z)

    def update_mobs(self, dt):
        if not self.mobs_enabled:
            return

        self.spawn_hostiles(dt)

        eye = None if self.player.dead else self.camera.position
        x, y, z = self.camera.position
        feet = (x, y + FEET, z)
        # За игроком гонятся только в выживании и пока он жив.
        target = feet if self.survival and not self.player.dead else None
        daytime_now = self.night_amount() < 0.5
        darkness = round(self.night_amount() * NIGHT_DARKNESS)
        active = []

        for mob in list(self.world.mobs):
            # Враждебные вдали от игрока исчезают, как в оригинале.
            if mob.kind.hostile and not mob.dead:
                distance = math.dist(mob.position, feet)

                if distance > mobs.DESPAWN_FAR or (
                    distance > mobs.DESPAWN_NEAR and random.random() < dt * mobs.DESPAWN_CHANCE
                ):
                    self.world.mobs.remove(mob)
                    continue

            # В незагруженном чанке моб замирает до возвращения игрока.
            if not self.mob_loaded(mob.position[0], mob.position[2]):
                continue

            if mob.kind.burns:
                head_x, head_y, head_z = (math.floor(value) for value in mob.center)
                mob.sunlit = daytime_now and self.world.sky_light_at(head_x, head_y - 1, head_z) >= 15

            # В огне моб получает урон и загорается, в лаве сильнее.
            if not mob.dead and water.body_in_water(self.world, *mob.box(mob.position), water.LAVA):
                mob.fire_time = LAVA_BURN_TIME
                mob.hurt(LAVA_DAMAGE, None)

            elif not mob.dead and self.touches_fire(*mob.box(mob.position)):
                mob.fire_time = fire_module.BURN_TIME
                mob.hurt(1, None)

            mob.update(self.world, dt, eye, self.mob_loaded, self.target_for(mob, target, darkness, dt))
            self.play_mob_sounds(mob)

            for dx, dz in mob.attacks:
                self.hurt_by_mob(mob.kind.attack, dx, dz)

            for origin, aim_at in mob.shots:
                velocity = projectiles.aim(origin, aim_at, projectiles.SKELETON_SPEED, projectiles.SKELETON_SPREAD, random)
                self.world.arrows.append(projectiles.Arrow(origin, velocity, mob))
                self.sounds.play_at("entity.skeleton.shoot", origin, self.camera, MOB_VOLUME)

            mob.shots.clear()

            mob.attacks.clear()

            if mob.removed:
                self.world.mobs.remove(mob)

                if mob.dead:
                    self.mob_died(mob)

                continue

            active.append(mob)

        for index, mob in enumerate(active):
            for other in active[index + 1:]:
                mob.push_apart(other, dt)

        self.update_arrows(dt, feet)

    def update_arrows(self, dt, feet):
        """Стрелы летят и попадают в игрока (в выживании) или в мобов."""
        targets = [(mob, *mob.box(mob.position)) for mob in self.world.mobs if not mob.dead]

        if self.survival and not self.player.dead:
            targets.append((self.player, *player_box(self.camera.position)))

        low, high = player_box(self.camera.position)
        picked = False

        for arrow in list(self.world.arrows):
            if not self.mob_loaded(arrow.position[0], arrow.position[2]):
                self.world.arrows.remove(arrow)
                continue

            # Свою застрявшую стрелу игрок подбирает, подойдя к ней.
            if arrow.stuck and arrow.pickup and not self.player.dead and all(
                low[axis] - ARROW_PICKUP_REACH <= arrow.position[axis] <= high[axis] + ARROW_PICKUP_REACH for axis in range(3)
            ):
                if insert(self.inventory.slots, Stack("arrow")) == 0:
                    self.world.arrows.remove(arrow)
                    picked = True
                    continue

            hit = arrow.update(self.world, dt, targets)

            if hit == "block":
                self.sounds.play_at("entity.arrow.hit", arrow.position, self.camera, MOB_VOLUME)

            elif hit is self.player:
                dx, _, dz = arrow.direction
                flat = math.hypot(dx, dz) or 1.0
                self.hurt_by_mob(arrow.damage, dx / flat, dz / flat)

            elif hit is not None:
                # Отброс от стрелы вдоль её полёта: источник позади моба.
                x, y, z = hit.position
                source = (x - arrow.direction[0], y, z - arrow.direction[2])

                hit.hurt(arrow.damage, source)

            if arrow.removed:
                self.world.arrows.remove(arrow)

        if picked:
            self.sounds.play("entity.item.pickup", PICKUP_VOLUME)

    def armor_points(self):
        return armor.total_points(self.inventory.armor)

    def hurt_by_mob(self, amount, dx, dz):
        """Удар моба: броня снижает урон и изнашивается, игрока отбрасывает."""
        if self.player.dead or self.player.hurt_time > 0 or not self.survival:
            return

        # Отбрасывает даже тогда, когда броня погасила весь урон.
        self.player.knock(dx, dz)

        if not self.player.damage(armor.reduce(amount, self.armor_points())):
            # Броня погасила весь урон: удар всё равно был, и неуязвимость как после обычного.
            self.player.hurt_time = HURT_TIME

        if armor.wear(self.inventory.armor, amount):
            self.sounds.play("entity.item.break", TOOL_BREAK_VOLUME)

    def target_for(self, mob, target, darkness, dt):
        """За кем гонится моб. Паук на свету не нападает первым, пока его не ударили."""
        if target is None or not mob.kind.daylight_neutral:
            return target

        x, y, z = (math.floor(value) for value in mob.center)

        if mobs.spawn_light(self.world.packed_light_at(x, y, z), darkness) < mobs.NEUTRAL_LIGHT:
            return target

        # Разозлённый паук днём со временем успокаивается.
        if mob.provoked and random.random() < dt * mobs.CALM_CHANCE:
            mob.provoked = False

        return target if mob.provoked else None

    def spawn_hostiles(self, dt):
        """Раз в секунду пробуем поставить зомби где-нибудь в темноте вокруг игрока."""
        self.hostile_timer += dt

        if self.hostile_timer < mobs.HOSTILE_SPAWN_INTERVAL:
            return

        self.hostile_timer = 0.0
        eye_x, eye_y, eye_z = self.camera.position

        nearby = sum(
            1 for mob in self.world.mobs
            if mob.kind.hostile and math.dist(mob.position, (eye_x, eye_y, eye_z)) < mobs.DESPAWN_FAR
        )

        if nearby >= mobs.MAX_HOSTILE:
            return

        darkness = round(self.night_amount() * NIGHT_DARKNESS)

        for _ in range(mobs.HOSTILE_SPAWN_ATTEMPTS):
            angle = random.uniform(0, math.tau)
            distance = random.uniform(*mobs.HOSTILE_SPAWN_DISTANCE)
            x = math.floor(eye_x + math.sin(angle) * distance)
            z = math.floor(eye_z + math.cos(angle) * distance)

            if not self.mob_loaded(x, z):
                continue

            top = math.floor(eye_y) + random.randint(-mobs.HOSTILE_SPAWN_HEIGHT, mobs.HOSTILE_SPAWN_HEIGHT)
            y = mobs.spawn_spot(self.world, x, z, top, mobs.HOSTILE_SPAWN_SCAN)

            if y is None or mobs.spawn_light(self.world.packed_light_at(x, y, z), darkness) > mobs.SPAWN_LIGHT:
                continue

            self.world.mobs.append(mobs.Mob(random.choice(mobs.HOSTILE), (x + 0.5, float(y + 1), z + 0.5)))
            return

    def play_mob_sounds(self, mob):
        """Голос, удар, смерть и шаги моба из событий entity.<вид>.* ресурс-пака.

        Если у вида нет своего звука удара или смерти, играет общий. Без своих
        шагов слышен шаг по блоку под ногами, как в оригинале.
        """
        for kind in mob.sounds:
            event = f"entity.{mob.kind.name}.{kind}"

            if kind == "step":
                if self.sounds.has(event):
                    self.sounds.play_at(event, mob.position, self.camera, MOB_STEP_VOLUME)
                    continue

                x, y, z = mob.position
                ground = self.world.get_block(math.floor(x), math.floor(y + 0.01), math.floor(z))

                if ground is not None:
                    self.sounds.block_sound(ground.type, "step", mob.position, self.camera, MOB_STEP_VOLUME)

            elif self.sounds.has(event):
                self.sounds.play_at(event, mob.center, self.camera, MOB_VOLUME)

            elif kind in ("hurt", "death"):
                self.sounds.play_at(f"entity.generic.{kind}", mob.center, self.camera, MOB_VOLUME)

        mob.sounds.clear()

    def mob_died(self, mob):
        """Моб упал и исчез: на его месте добыча."""
        x, y, z = mob.center

        for item, low, high in mob.kind.drops:
            count = random.randint(low, high)

            if count > 0:
                self.add_item(Stack(item, count), (x, y, z), scatter_velocity(), PICKUP_DELAY)


    def mob_in_cell(self, cell):
        """Стоит ли животное там, куда хотят поставить блок."""
        for mob in self.world.mobs:
            low, high = mob.box(mob.position)

            if all(low[axis] < cell[axis] + 1 and high[axis] > cell[axis] for axis in range(3)):
                return True

        return False

    def attack_mob(self):
        """Удар по животному под прицелом. Возвращает True, если было по кому бить."""
        if not self.mobs_enabled or self.player.dead:
            return False

        eye = self.camera.position
        forward = self.camera.forward()
        reach = MOB_REACH if self.survival else CREATIVE_MOB_REACH
        nearest, distance = None, reach

        for mob in self.world.mobs:
            if mob.dead:
                continue

            hit = ray_box_distance(eye, forward, *mob.box(mob.position))

            if hit is not None and hit < distance:
                nearest, distance = mob, hit

        if nearest is None:
            return False

        # Блок между нами и животным закрывает его.
        block, _ = self.world.raycast(eye, forward, distance)

        if block is not None:
            return False

        self.hand.swing()

        if nearest.hurt(mobs.attack_damage(self.held_type()), eye) and self.survival:
            self.wear_tool()

        return True

    # Лук.

    def has_arrows(self):
        return any(stack is not None and stack.type == "arrow" for stack in self.inventory.slots)

    def start_bow(self):
        """Правая кнопка с луком: натягиваем, если есть стрелы (в творческом они не нужны)."""
        if self.bow_draw is None and not self.player.dead and (not self.survival or self.has_arrows()):
            self.bow_draw = 0.0

    def cancel_bow(self):
        self.bow_draw = None
        self.player.slowdown = 1.0

    def update_bow(self, dt):
        if self.bow_draw is None:
            return

        # Лук убрали из руки или игрок погиб: тетива отпущена без выстрела.
        if self.held_type() != "bow" or self.player.dead or not pygame.mouse.get_pressed()[2]:
            if self.held_type() == "bow" and not self.player.dead:
                self.release_bow()
            else:
                self.cancel_bow()
            return

        self.bow_draw += dt
        self.player.slowdown = BOW_SLOWDOWN

    def release_bow(self):
        """Отпустили правую кнопку: стрела летит с силой по времени натяжения."""
        if self.bow_draw is None:
            return

        power = projectiles.bow_power(self.bow_draw)
        self.cancel_bow()

        if power < projectiles.BOW_MIN_POWER or self.held_type() != "bow":
            return

        if self.survival:
            index = next((index for index, stack in enumerate(self.inventory.slots) if stack is not None and stack.type == "arrow"), None)

            if index is None:
                return

            self.inventory.take_one(index)
            self.wear_bow()

        forward = self.camera.forward()
        x, y, z = self.camera.position
        origin = (x, y + 0.1, z)
        direction = projectiles.Arrow.unit(tuple(value + random.gauss(0, projectiles.BOW_SPREAD) for value in forward))
        velocity = [value * projectiles.BOW_SPEED * power for value in direction]

        self.world.arrows.append(projectiles.Arrow(origin, velocity, self.player, pickup=self.survival, critical=power >= 1.0))
        self.sounds.play("entity.arrow.shoot", MOB_VOLUME)

    def wear_bow(self):
        stack = self.held_stack()
        stack.damage += 1

        if stack.damage >= max_uses("bow"):
            self.inventory.slots[self.selected_slot] = None
            self.sounds.play("entity.item.break", TOOL_BREAK_VOLUME)

    def shown_held(self):
        """Что видно в руке: натянутый лук показывается стадией натяжения."""
        held = self.held_type()

        if held == "bow" and self.bow_draw is not None:
            power = self.bow_draw / projectiles.BOW_DRAW_TIME
            stage = sum(power >= limit for limit in BOW_STAGES)
            return f"bow_pulling_{stage}"

        return held

    def arrow_objects(self):
        eye = self.camera.position
        limit = self.engine.fog_distance + 2

        return [
            # Свет берём чуть позади острия: у застрявшей стрелы оно внутри блока, а там темно.
            DrawObject(self.arrow_model.mesh, points, self.brightness_at(*(arrow.position[axis] - arrow.direction[axis] * 0.3 for axis in range(3))))
            for arrow in self.world.arrows
            if math.dist(arrow.position, eye) < limit and (points := self.arrow_model.world_points(arrow)) is not None
        ]

    def mob_objects(self):
        if not self.mobs_enabled:
            return []

        eye = self.camera.position
        limit = self.engine.fog_distance + 2
        objects = []

        for mob in self.world.mobs:
            if math.dist(mob.position, eye) < limit:
                objects.append(self.mob_models.draw_object(mob, self.brightness_at(*mob.center)))

                # Горящий моб окутан пламенем, как в оригинале.
                if mob.burning and not mob.dead:
                    objects.append(self.burning_model.draw_object(mob.position, mob.kind.half_width * 2, mob.kind.height, self.camera))

        return objects

    def item_objects(self):
        """Лежащие предметы в этом кадре, дальше тумана не рисуем."""
        eye = self.camera.position
        limit = self.engine.fog_distance
        objects = []

        for entity in self.world.items:
            if math.dist(entity.position, eye) < limit:
                objects += self.item_models.draw_objects(entity, self.brightness_at(*entity.position))

        return objects

    def use_block(self, position):
        """Правый клик по верстаку, сундуку или печке открывает их экран, по кровати укладывает спать."""
        block = self.world.get_block(*position)

        if is_bed(block.type):
            self.try_sleep(position, block)
            return True

        if block.type == "crafting_table":
            self.show_screen(CraftingScreen(self))
            return True

        # Сундуки и печки в сетевой игре хранит хозяин, а открыть их может только один игрок.
        if block.type in ("chest", "furnace") and self.net is not None:
            if self.is_client:
                self.net.request_container(position)
                return True

            if self.net.container_busy(position, HOST_ID):
                self.chat.add(f"This {block.type} is being used by someone else", GRAY)
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
            self.world_sound(event, self.cell_center(hit))
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

        if held == "flint_and_steel":
            self.use_flint_and_steel(target)
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

        # Цветы и саженцы сажают только на траву или землю. Сквозь них тоже ходят.
        elif plants.is_plant(held):
            if not plants.can_stand_on(self.world.get_block(target[0], target[1] + 1, target[2])):
                return

        elif box_touches_block(self.camera.position, target) or self.mob_in_cell(target):
            return

        if is_bed(held):
            def free(cell):
                return not box_touches_block(self.camera.position, cell) and not self.mob_in_cell(cell)

            if self.world.place_bed(target, held, self.camera.forward(), free):
                head = other_half(target, self.world.get_block(*target).state)

                for cell in (target, head):
                    self.world.notify(*cell)
                    self.rebuild_around(cell[0], cell[2])

                self.placed(held, target)

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

            lava = self.world.get_block(*cell).type == "lava"
            self.world.remove_block(*cell)
            result, sound = ("lava_bucket", "item.bucket.fill_lava") if lava else ("water_bucket", "item.bucket.fill")
        else:
            _, cell = self.world.raycast(eye, forward, self.reach)

            if cell is None:
                return

            occupant = self.world.get_block(*cell)

            if occupant is not None and not occupant.is_liquid:
                return

            self.world.set_block(*cell, Block("lava" if held == "lava_bucket" else "water"))
            result, sound = "bucket", "item.bucket.empty_lava" if held == "lava_bucket" else "item.bucket.empty"

        self.world.notify(*cell)
        self.rebuild_water_around(cell[0], cell[2])
        self.world_sound(sound, self.cell_center(cell))
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
        """Звук блока в клетке position: break, place или step. Ломание и постройку слышат все."""
        self.sounds.block_sound(block_type, action, self.cell_center(position), self.camera, volume)

        if self.net is not None and action in ("break", "place"):
            self.net.sound(self.cell_center(position), block=block_type, action=action, volume=volume)

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
        for position, container in list(self.world.containers.items()):
            if not isinstance(container, Furnace):
                continue

            # Печку, открытую другим игроком, считает он.
            if self.net is not None and self.net.is_host and position in self.net.locks:
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
        self.cancel_bow()
        self.selected_slot = slot % Config.HOTBAR_SIZE
        self.save_settings()

    def update(self, dt):
        if self.net is not None:
            self.net.update(dt)

        self.update_world(dt)

        if self.net is not None and self.in_world:
            self.net.flush(dt)

    def update_world(self, dt):
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

        # Мир стоит только на паузе в одиночной игре. В сетевой игре меню его не
        # останавливает, а экран смерти не останавливает никогда, как в оригинале.
        if self.menu_open and self.net is None and self.menu.page != 'death':
            return

        self.world.time += dt * daytime.TICKS_PER_SECOND
        self.tick_containers(dt)
        self.tick_water(dt)
        self.tick_plants(dt)
        self.tick_fire(dt)
        self.update_ambient_sounds(dt)
        self.update_items(dt)
        self.update_mobs(dt)

        if self.menu_open:
            return

        # Пока открыт экран или чат, игрок не управляет собой, но мир на него
        # действует: он падает, тонет и получает урон.
        blocked = self.open_screen is not None or self.chat.open

        # Под игроком всегда должна быть земля: после телепорта её строим сразу.
        # В чужом мире изменённый чанк может быть ещё в пути: тогда ждём его на месте.
        if self.loader is not None:
            x, _, z = self.camera.position
            self.loader.ensure(x, z)

            if not self.loader.is_loaded(x, z):
                return

        if self.sleeping is not None:
            self.update_sleep(dt)
            return

        if blocked:
            forward = right = 0
            space = shift = False
        else:
            keys = pygame.key.get_pressed()
            forward, right = self.forwad, self.right
            space = keys[pygame.K_SPACE]
            shift = keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT]
            self.update_bow(dt)

        self.player.update(dt, forward, right, space, shift)

        player = self.player
        walking = bool(forward or right) and player.on_ground and not player.flying

        self.update_player_fire(dt)
        self.hand.update(dt, self.held_type(), walking)
        self.play_player_sounds()

        if self.survival and not blocked:
            self.update_mining(dt)

        if player.dead:
            # Смерть с открытым инвентарём или чатом: закрываем их, предметы с курсора возвращаются.
            if self.open_screen is not None:
                self.close_screen()

            if self.chat.open:
                self.chat.close()

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
        extra = self.crack_overlay() + self.item_objects() + self.mob_objects() + self.arrow_objects() if self.in_world else []

        if self.net is not None:
            extra += self.net.draw_objects()

        # Крадучись камера чуть ниже. Физика и прицел остаются на месте глаз стоя.
        eye = self.camera.position

        if self.in_world and self.player.eye_drop:
            self.camera.position = (eye[0], eye[1] + self.player.eye_drop, eye[2])

        underwater = self.in_world and water.point_in_water(self.world, self.camera.position)

        # Натянутый лук чуть приближает вид.
        fov = self.camera.fov

        if self.bow_draw is not None:
            self.camera.fov = fov * (1 - BOW_ZOOM * projectiles.bow_power(self.bow_draw))

        # Кадр пламени: 20 в секунду, как в оригинале. Лава переливается вдвое медленнее.
        self.engine.animate(FIRE_TEXTURE, self.fire_frame_surfaces(), int(time.perf_counter() * fire_module.FRAME_RATE))
        self.engine.animate(water.LAVA_TEXTURE, self.lava_frame_surfaces(), int(time.perf_counter() * LAVA_FRAME_RATE))

        sky = daytime.sky_at(self.world.time)
        self.engine.render(self.world, self.render_surface, self.camera, extra, underwater, self.fog_light, sky)
        self.camera.position = eye
        self.camera.fov = fov

        in_world = self.in_world and not self.gui_hidden

        if in_world and self.sleeping is None:
            self.hand.render(self.shown_held(), self.render_surface, self.brightness_at(*self.camera.position))

        if self.in_world:
            pygame.transform.scale(self.render_surface, self.screen.get_size(), self.screen)
        else:
            self.draw_blurred_background()

        if self.net is not None and in_world:
            self.net.render_nametags(self.screen, self.camera, self.gui)

        if underwater:
            self.gui.tint(self.screen, UNDERWATER_TINT, UNDERWATER_TINT_ALPHA)

        # Глаза в лаве: почти ничего не видно, всё оранжевое.
        if self.in_world and self.player.eyes_in_lava:
            self.gui.tint(self.screen, LAVA_VIEW, LAVA_VIEW_ALPHA)

        # Игрок горит: внизу экрана языки пламени, как в оригинале.
        if self.in_world and self.player.fire_time > 0 and self.sleeping is None:
            frames = self.fire_frame_surfaces()
            burning.draw_overlay(self.screen, frames[int(time.perf_counter() * fire_module.FRAME_RATE) % len(frames)])

        # Сон: экран плавно темнеет.
        if self.in_world and self.sleeping is not None:
            fade = min(1.0, self.sleeping["time"] / SLEEP_FADE) * SLEEP_DARK
            self.gui.tint(self.screen, (0, 0, 0), int(255 * fade))

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
                player.air / MAX_AIR if self.survival and (player.eyes_in_water or player.air < MAX_AIR) else None,
                self.armor_points() if self.survival else 0
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
            self.engine.render_text(self.screen, f"flying: {self.player.flying}, light: {self.eye_light() if self.in_world else '-'}, time: {int(self.world.time)} ({daytime.clock_text(self.world.time)}, day {int(self.world.time // daytime.DAY_LENGTH) + 1})", (0, 140))

            if self.terrain is not None:
                meshed = sum(chunk.meshed for chunk in self.world.chunks.values())
                biome = self.terrain.biome_at(math.floor(x), math.floor(z))
                self.engine.render_text(self.screen, f"seed: {self.seed}  biome: {biome}", (0, 160))
                self.engine.render_text(self.screen, f"chunks: {len(self.world.chunks)} loaded, {meshed} meshed, {self.loader.generated} generated, work {self.loader.work_time * 1000:.1f} ms", (0, 180))


        pygame.display.flip()

    def lava_frame_surfaces(self):
        if self.lava_frames is None:
            self.lava_frames = textures.lava_frames()

        return self.lava_frames

    def fire_frame_surfaces(self):
        if self.fire_frames is None:
            self.fire_frames = fire_frames()

        return self.fire_frames

    def draw_blurred_background(self):
        """Мир за главным меню размыт: уменьшаем, размываем и растягиваем обратно.

        В малом размере размытие стоит долей миллисекунды, а растяжение с
        сглаживанием само добавляет мягкости.
        """
        width, height = self.screen.get_size()
        small_size = (max(1, width // TITLE_BLUR_SCALE), max(1, height // TITLE_BLUR_SCALE))

        small = pygame.transform.smoothscale(self.render_surface, small_size)
        small = pygame.transform.gaussian_blur(small, TITLE_BLUR_RADIUS)

        self.screen.blit(pygame.transform.smoothscale(small, (width, height)), (0, 0))

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
        self.cancel_bow()
        self.open_screen = screen
        self.free_cursor(True)

        self.forwad = 0
        self.right = 0

    def open_inventory(self):
        self.show_screen(InventoryScreen(self) if self.survival else CreativeScreen(self))

    def close_screen(self):
        if isinstance(self.open_screen, ChestScreen):
            self.sounds.play_at("block.chest.close", self.cell_center(self.chest_position), self.camera, CHEST_VOLUME)

        screen = self.open_screen
        screen.close()
        self.open_screen = None
        self.free_cursor(False)

        # Сундук или печка хозяина: возвращаем ему содержимое.
        container = getattr(screen, "chest", None) or getattr(screen, "furnace", None)

        if self.is_client and container is not None:
            for position, held in list(self.world.containers.items()):
                if held is container:
                    del self.world.containers[position]
                    self.net.close_container(position, container)

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
        self.cancel_bow()
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
        # В кровати: любая клавиша движения или щелчок поднимают, утро не наступит.
        if self.sleeping is not None and (
            event.type == pygame.MOUSEBUTTONDOWN
            or (event.type == pygame.KEYDOWN and event.key not in (pygame.K_ESCAPE, pygame.K_t, pygame.K_SLASH, pygame.K_F1, pygame.K_F3))
        ):
            self.wake_up()
            return

        if event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 1:
                # Животное под прицелом ближе блока: бьём его, а не блок.
                if self.attack_mob():
                    pass

                # В выживании блок ломается, пока держишь кнопку, в творческом сразу.
                elif self.survival:
                    self.mining.start()
                    self.hand.swing()
                else:
                    self.break_block()

            elif event.button == 3:
                if self.held_type() == "bow":
                    self.start_bow()
                else:
                    self.place_block()

        if event.type == pygame.MOUSEBUTTONUP and event.button == 3:
            self.release_bow()

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
        self.cancel_bow()
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
            if self.net is not None:
                self.net.chat(line)
            else:
                self.chat.add(f"<{self.player_name}> {line}")

            return

        for text, color in commands.run(self, line):
            self.chat.add(text, color)

    # Для команд: координаты как в оригинале, x, y вверх (высота ног), z.

    def player_position(self):
        x, y, z = self.camera.position

        return (x, -(y + FEET), z)

    def set_time(self, time):
        """Команда /time. В сетевой игре время меняет только хозяин и сразу рассылает его."""
        self.world.time = max(0.0, time)

        if self.net is not None:
            self.net.send_time()

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
        self.stop_network()

        pygame.quit()
        sys.exit()


if __name__ == "__main__":
    Game(*parse_arguments(sys.argv[1:])).run()
