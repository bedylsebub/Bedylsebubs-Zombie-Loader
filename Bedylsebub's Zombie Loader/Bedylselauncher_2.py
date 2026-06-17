import customtkinter as ctk
from tkinter import filedialog
from PIL import Image
import os
import sys
import json
import subprocess
import webbrowser
import re
import shutil

try:
    import pygame
except ImportError:
    pygame = None


ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")


APP_BG = "#080303"
HEADER_BG = "#120606"
PANEL_BG = "#130808"
CARD_BG = "#1c0d0d"
INPUT_BG = "#1a0b0b"

DARK_RED = "#6f1010"
RED = "#a81919"
BRIGHT_RED = "#e33131"
BORDER_RED = "#4d0b0b"

TEXT = "#f5e8e8"
MUTED_TEXT = "#a98c8c"


MAPS_DATA = {
    "World at War": ["Nacht der Untoten", "Verruckt", "Shi No Numa", "Der Riese"],
    "Black Ops": ["Kino der Toten", "Five", "Dead Ops Arcade", "Ascension", "Call of the Dead", "Shangri-La", "Moon"],
    "Black Ops II": ["TranZit", "Nuketown Zombies", "Die Rise", "Mob of the Dead", "Buried", "Origins"],
    "Black Ops III": [
        "Shadows of Evil", "The Giant", "Der Eisendrache", "Zetsubou No Shima", "Gorod Krovi", "Revelations",
        "Nacht der Untoten", "Verruckt", "Shi No Numa", "Kino der Toten", "Ascension", "Shangri-La", "Moon", "Origins"
    ],
    "Black Ops 4": ["Voyage of Despair", "IX", "Blood of the Dead", "Classified", "Dead of the Night", "Ancient Evil", "Alpha Omega", "Tag der Toten"],
    "Black Ops Cold War": ["Die Maschine", "Firebase Z", "Mauer der Toten", "Forsaken"],
}


DEFAULT_LAUNCH_CONFIG = {
    "World at War": {"platform": "steam", "steam_app_id": "10090", "path": "", "url": "", "args": ""},
    "Black Ops": {"platform": "steam", "steam_app_id": "42700", "path": "", "url": "", "args": ""},
    "Black Ops II": {"platform": "steam", "steam_app_id": "212910", "path": "", "url": "", "args": ""},
    "Black Ops III": {"platform": "steam", "steam_app_id": "311210", "path": "", "url": "", "args": ""},
    "Black Ops 4": {"platform": "battlenet", "steam_app_id": "", "path": "", "url": "", "args": ""},
    "Black Ops Cold War": {"platform": "battlenet", "steam_app_id": "", "path": "", "url": "", "args": ""},
}


MAP_LAUNCH_ARGS = {
    "World at War": {
        "Nacht der Untoten": "nazi_zombie_prototype",
        "Verruckt": "nazi_zombie_asylum",
        "Shi No Numa": "nazi_zombie_sumpf",
        "Der Riese": "nazi_zombie_factory",
    }
}

MAP_DESCRIPTIONS = {
    "World at War": {
        "Nacht der Untoten": "Where it all began: an abandoned airfield suspended in space and plagued by infinite hordes of undead",
        "Verruckt": "Electroshock therapy. Chemically engineered beverages. Hordes of Undead Nazis. Find the power to unite and send them back to their graves!",
        "Shi No Numa": "Maggot ridden corpses. Bug infested swamp. Hundreds of undead Imperial Army. Choose your tactic and defend for your lives!",
        "Der Riese": "The Giant is rising. Face the might of the Nazi Zombies in their heartland. This is where it all began. This is where the master plan took shape. Is this where it all ends?",
    }
}


class ZombiesMapLoader(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("BDB Zombies Launcher")
        self.iconbitmap(os.path.join(self.base_dir(), "assets", "icon.ico"))
        self.geometry("1350x800")
        self.minsize(1150, 700)
        self.configure(fg_color=APP_BG)

        try:
            self.attributes("-alpha", 0.95)
        except Exception:
            pass

        self.selected_game = "ALL"
        self.selected_map = None
        self.selected_map_game = None

        self.image_cache = {}
        self.sound_cache = {}

        self.master_volume = 0.35
        self.is_muted = False

        self.waw_tracker_refresh_running = False
        self.last_waw_tracker_mtime = 0
        self.waw_tracker_process = None

        self.setup_audio()
        self.start_menu_music()

        self.launch_config = self.load_launch_config()
        self.leaderboard = self.load_leaderboard()

        self.create_layout()
        self.load_games()
        self.load_maps("ALL")

        self.after(300, self.open_welcome_screen)

    def base_dir(self):
        return os.path.dirname(os.path.abspath(__file__))

    def get_title_font(self):
        return ("Brutalworld", 38, "normal")

    def setup_audio(self):
        self.audio_enabled = False

        if pygame is None:
            print("pygame not installed. Sounds disabled.")
            return

        try:
            pygame.mixer.pre_init(44100, -16, 2, 128)
            pygame.mixer.init()
            pygame.mixer.set_num_channels(16)
            self.audio_enabled = True
            self.preload_sounds()
        except Exception as error:
            print(f"Could not initialise audio: {error}")

    def preload_sounds(self):
        if not self.audio_enabled:
            return

        for sound_name in ["click.wav", "launch.wav", "save.wav", "error.wav"]:
            path = os.path.join(self.base_dir(), "assets", "sounds", sound_name)

            if os.path.exists(path):
                try:
                    sound = pygame.mixer.Sound(path)
                    sound.set_volume(self.master_volume)
                    self.sound_cache[sound_name] = sound
                except Exception as error:
                    print(f"Could not preload sound {sound_name}: {error}")

    def start_menu_music(self):
        if not self.audio_enabled:
            return

        music_files = [
            os.path.join(self.base_dir(), "assets", "sounds", "menu_music.mp3"),
            os.path.join(self.base_dir(), "assets", "sounds", "menu_music.wav"),
            os.path.join(self.base_dir(), "assets", "sounds", "menu_music.ogg")
        ]

        for music_path in music_files:
            if os.path.exists(music_path):
                try:
                    pygame.mixer.music.load(music_path)
                    pygame.mixer.music.set_volume(self.master_volume)
                    pygame.mixer.music.play(-1)
                    return
                except Exception as error:
                    print(f"Could not play menu music: {error}")

    def set_volume(self, value):
        self.master_volume = float(value)

        if not self.audio_enabled:
            return

        if not self.is_muted:
            pygame.mixer.music.set_volume(self.master_volume)

        for sound in self.sound_cache.values():
            sound.set_volume(self.master_volume if not self.is_muted else 0)

    def mute_launcher_audio(self):
        self.is_muted = True

        if not self.audio_enabled:
            return

        pygame.mixer.music.set_volume(0)

        for sound in self.sound_cache.values():
            sound.set_volume(0)

        if hasattr(self, "mute_button"):
            self.mute_button.configure(text="Unmute")

    def unmute_launcher_audio(self):
        self.is_muted = False

        if not self.audio_enabled:
            return

        pygame.mixer.music.set_volume(self.master_volume)

        for sound in self.sound_cache.values():
            sound.set_volume(self.master_volume)

        if hasattr(self, "mute_button"):
            self.mute_button.configure(text="Mute")

    def toggle_mute(self):
        if self.is_muted:
            self.unmute_launcher_audio()
        else:
            self.mute_launcher_audio()

    def play_sound(self, sound_name):
        if not self.audio_enabled or self.is_muted:
            return

        try:
            if sound_name in self.sound_cache:
                self.sound_cache[sound_name].play()
                return

            path = os.path.join(self.base_dir(), "assets", "sounds", sound_name)

            if not os.path.exists(path):
                return

            sound = pygame.mixer.Sound(path)
            sound.set_volume(self.master_volume)
            self.sound_cache[sound_name] = sound
            sound.play()
        except Exception as error:
            print(f"Could not play sound {sound_name}: {error}")

    def make_button(self, parent, text, command=None, width=120, height=32):
        return ctk.CTkButton(
            parent,
            text=text,
            command=command,
            width=width,
            height=height,
            fg_color=RED,
            hover_color=BRIGHT_RED,
            text_color=TEXT,
            border_width=1,
            border_color=DARK_RED
        )

    def create_layout(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self.header = ctk.CTkFrame(
            self,
            height=78,
            corner_radius=0,
            fg_color=HEADER_BG,
            border_width=1,
            border_color=BORDER_RED
        )
        self.header.grid(row=0, column=0, columnspan=3, sticky="ew")
        self.header.grid_columnconfigure(1, weight=1)

        self.title_label = ctk.CTkLabel(
            self.header,
            text="Bedylsebub's Easy Zombie Loader",
            font=self.get_title_font(),
            text_color=TEXT
        )
        self.title_label.grid(row=0, column=0, padx=25, pady=20, sticky="w")

        audio_frame = ctk.CTkFrame(self.header, fg_color="transparent")
        audio_frame.grid(row=0, column=1, padx=10, pady=12, sticky="e")

        ctk.CTkLabel(audio_frame, text="Volume", text_color=MUTED_TEXT).pack(side="left", padx=(0, 8))

        self.volume_slider = ctk.CTkSlider(
            audio_frame,
            from_=0,
            to=1,
            width=130,
            command=self.set_volume,
            button_color=RED,
            button_hover_color=BRIGHT_RED,
            progress_color=RED,
            fg_color="#2a1111"
        )
        self.volume_slider.set(self.master_volume)
        self.volume_slider.pack(side="left", padx=(0, 8))

        self.mute_button = self.make_button(
            audio_frame,
            text="Mute",
            width=70,
            command=self.toggle_mute
        )
        self.mute_button.pack(side="left", padx=(0, 8))

        self.settings_button = self.make_button(
            self.header,
            text="Game Settings",
            width=140,
            command=self.open_settings_window
        )
        self.settings_button.grid(row=0, column=2, padx=(0, 360), pady=18, sticky="e")

        self.search_entry = ctk.CTkEntry(
            self.header,
            placeholder_text="Search maps...",
            width=320,
            fg_color=INPUT_BG,
            border_color=DARK_RED,
            text_color=TEXT,
            placeholder_text_color=MUTED_TEXT
        )
        self.search_entry.grid(row=0, column=2, padx=25, pady=18, sticky="e")
        self.search_entry.bind("<KeyRelease>", self.search_maps)

        self.sidebar = ctk.CTkFrame(
            self,
            width=230,
            corner_radius=0,
            fg_color=PANEL_BG,
            border_width=1,
            border_color=BORDER_RED
        )
        self.sidebar.grid(row=1, column=0, sticky="nsw")
        self.sidebar.grid_propagate(False)

        self.sidebar_title = ctk.CTkLabel(
            self.sidebar,
            text="Games",
            font=("Arial", 22, "bold"),
            text_color=TEXT
        )
        self.sidebar_title.pack(pady=(20, 10))

        self.game_buttons_frame = ctk.CTkScrollableFrame(
            self.sidebar,
            fg_color=PANEL_BG,
            scrollbar_button_color=DARK_RED,
            scrollbar_button_hover_color=RED
        )
        self.game_buttons_frame.pack(fill="both", expand=True, padx=10, pady=10)

        self.maps_area = ctk.CTkScrollableFrame(
            self,
            fg_color=APP_BG,
            scrollbar_button_color=DARK_RED,
            scrollbar_button_hover_color=RED
        )
        self.maps_area.grid(row=1, column=1, sticky="nsew", padx=15, pady=15)

        self.details_panel = ctk.CTkFrame(
            self,
            width=330,
            fg_color=PANEL_BG,
            border_width=1,
            border_color=BORDER_RED
        )
        self.details_panel.grid(row=1, column=2, sticky="nse", padx=(0, 15), pady=15)
        self.details_panel.grid_propagate(False)

        self.details_image_label = ctk.CTkLabel(self.details_panel, text="")
        self.details_image_label.pack(pady=(25, 10))

        self.details_title = ctk.CTkLabel(
            self.details_panel,
            text="Select a Map",
            font=("Arial", 24, "bold"),
            wraplength=280,
            text_color=TEXT
        )
        self.details_title.pack(pady=(10, 5))

        self.details_game = ctk.CTkLabel(
            self.details_panel,
            text="",
            font=("Arial", 16),
            text_color=MUTED_TEXT
        )
        self.details_game.pack(pady=5)

        self.details_description = ctk.CTkLabel(
            self.details_panel,
            text="Choose a Zombies map from the list.",
            font=("Arial", 14),
            wraplength=280,
            justify="center",
            text_color=TEXT
        )
        self.details_description.pack(pady=15)

        self.details_round_frame = ctk.CTkFrame(self.details_panel, fg_color="transparent")
        self.details_round_frame.pack(pady=(5, 5))

        self.refresh_rounds_button = self.make_button(
            self.details_panel,
            text="Refresh WaW Rounds",
            width=190,
            command=self.refresh_verified_rounds
        )
        self.refresh_rounds_button.pack(pady=5)

        self.launch_status = ctk.CTkLabel(
            self.details_panel,
            text="",
            font=("Arial", 12),
            text_color=MUTED_TEXT,
            wraplength=280
        )
        self.launch_status.pack(pady=5)

        self.launch_button = self.make_button(
            self.details_panel,
            text="Launch Map",
            height=45,
            command=self.launch_map
        )
        self.launch_button.pack(side="bottom", fill="x", padx=25, pady=25)

    def get_leaderboard_path(self):
        return os.path.join(self.base_dir(), "waw_round_tracker.json")

    def load_leaderboard(self):
        path = self.get_leaderboard_path()

        if not os.path.exists(path):
            return {}

        try:
            with open(path, "r", encoding="utf-8") as file:
                data = json.load(file)

            if not isinstance(data, dict):
                return {}

            return data

        except Exception as error:
            print(f"Could not load waw_round_tracker.json: {error}")
            return {}

    def refresh_verified_rounds(self):
        self.leaderboard = self.load_leaderboard()
        self.image_cache.clear()
        self.load_maps(self.selected_game, self.search_entry.get())

        if self.selected_map and self.selected_map_game:
            self.select_map(self.selected_map, self.selected_map_game)

        self.launch_status.configure(text="WaW rounds refreshed.")
        self.play_sound("click.wav")

    def start_waw_tracker_ui_refresh(self):
        if self.waw_tracker_refresh_running:
            return

        self.waw_tracker_refresh_running = True
        self.after(2000, self.poll_waw_tracker_file)

    def write_waw_current_map(self):
        path = os.path.join(self.base_dir(), "waw_current_map.json")

        try:
            with open(path, "w", encoding="utf-8") as file:
                json.dump({"current_map": self.selected_map}, file, indent=4)

            print(f"WaW current map written: {self.selected_map}")
            return True

        except Exception as error:
            self.launch_status.configure(
                text=f"Could not write WaW current map: {error}"
            )
            return False

    def poll_waw_tracker_file(self):
        path = self.get_leaderboard_path()

        try:
            if os.path.exists(path):
                current_mtime = os.path.getmtime(path)

                if current_mtime != self.last_waw_tracker_mtime:
                    self.last_waw_tracker_mtime = current_mtime
                    self.leaderboard = self.load_leaderboard()
                    self.image_cache.clear()
                    self.load_maps(self.selected_game, self.search_entry.get())

                    if self.selected_map and self.selected_map_game:
                        self.select_map(self.selected_map, self.selected_map_game)

        except Exception as error:
            print(f"Could not refresh WaW tracker file: {error}")

        if self.waw_tracker_refresh_running:
            self.after(3000, self.poll_waw_tracker_file)

    def start_waw_round_tracker_script(self):
        print("start_waw_round_tracker_script was called")

        tracker_path = os.path.join(self.base_dir(), "waw_master_round_tracker.py")

        print(f"Tracker path: {tracker_path}")
        print(f"Tracker exists: {os.path.exists(tracker_path)}")

        if not os.path.exists(tracker_path):
            self.launch_status.configure(text="WaW master round tracker not found.")
            return

        try:
            if not hasattr(self, "waw_tracker_process"):
                self.waw_tracker_process = None

            if self.waw_tracker_process is not None and self.waw_tracker_process.poll() is None:
                print("WaW tracker already running.")
                self.start_waw_tracker_ui_refresh()
                return

            self.waw_tracker_process = subprocess.Popen(
                [sys.executable, tracker_path],
                cwd=self.base_dir()
            )

            print("Started WaW master round tracker.")
            self.start_waw_tracker_ui_refresh()

        except Exception as error:
            print(f"Could not start WaW tracker: {error}")
            self.launch_status.configure(text=f"Could not start WaW tracker: {error}")

    def leaderboard_key(self, map_name, game_name):
        return f"{game_name}::{map_name}"

    def get_highest_round(self, map_name, game_name):
        if game_name == "World at War":
            return int(self.leaderboard.get(map_name, 0))

        return int(
            self.leaderboard.get(
                self.leaderboard_key(map_name, game_name),
                0
            )
        )

    def load_round_digit_pil(self, character, size):
        filename = "dash.png" if character == "-" else f"{character}.png"
        path = os.path.join(self.base_dir(), "assets", "round_numbers", filename)

        if not os.path.exists(path):
            return None

        try:
            return Image.open(path).convert("RGBA").resize(size)
        except Exception as error:
            print(f"Could not load round digit {filename}: {error}")
            return None

    def load_round_digit_image(self, character, size=(22, 32)):
        cache_key = f"round_digit_{character}_{size[0]}x{size[1]}"

        if cache_key in self.image_cache:
            return self.image_cache[cache_key]

        pil_image = self.load_round_digit_pil(character, size)

        if pil_image is None:
            return None

        ctk_image = ctk.CTkImage(light_image=pil_image, dark_image=pil_image, size=size)
        self.image_cache[cache_key] = ctk_image
        return ctk_image

    def render_round_number(self, parent, round_number, digit_size=(22, 32)):
        for widget in parent.winfo_children():
            widget.destroy()

        text = str(round_number) if round_number and round_number > 0 else "-"

        for character in text:
            digit_image = self.load_round_digit_image(character, size=digit_size)

            if digit_image:
                label = ctk.CTkLabel(parent, image=digit_image, text="")
                label.image = digit_image
                label.pack(side="left", padx=1)
            else:
                fallback = ctk.CTkLabel(
                    parent,
                    text=character,
                    font=("Arial", digit_size[1] - 4, "bold"),
                    text_color=BRIGHT_RED
                )
                fallback.pack(side="left", padx=1)

    def paste_round_number_onto_image(self, base_image, round_number, digit_size, margin=8):
        text = str(round_number) if round_number and round_number > 0 else "-"
        digit_images = []

        for character in text:
            digit = self.load_round_digit_pil(character, digit_size)

            if digit:
                digit_images.append(digit)

        if not digit_images:
            return base_image

        total_width = sum(digit.width for digit in digit_images) + (len(digit_images) - 1) * 2
        max_height = max(digit.height for digit in digit_images)

        start_x = base_image.width - total_width - margin
        start_y = base_image.height - max_height - margin
        current_x = start_x

        for digit in digit_images:
            base_image.alpha_composite(digit, dest=(current_x, start_y))
            current_x += digit.width + 2

        return base_image

    def load_games(self):
        all_button = self.make_button(
            self.game_buttons_frame,
            text="ALL",
            height=40,
            command=lambda: self.select_game("ALL")
        )
        all_button.configure(anchor="w")
        all_button.pack(fill="x", pady=5)

        for game in MAPS_DATA:
            button = self.make_button(
                self.game_buttons_frame,
                text=game,
                height=40,
                command=lambda g=game: self.select_game(g)
            )
            button.configure(anchor="w")
            button.pack(fill="x", pady=5)

    def select_game(self, game):
        self.play_sound("click.wav")

        self.selected_game = game
        self.selected_map = None
        self.selected_map_game = None

        self.search_entry.delete(0, "end")
        self.load_maps(game)

        self.details_image_label.configure(image=None, text="")
        self.details_title.configure(text="Select a Map")
        self.details_game.configure(text=game, image=None)
        self.details_description.configure(text="Choose a Zombies map from the list.")
        self.render_round_number(self.details_round_frame, 0, digit_size=(38, 56))
        self.launch_status.configure(text="")

    def get_all_maps(self):
        all_maps = []

        for game, maps in MAPS_DATA.items():
            for map_name in maps:
                all_maps.append({"name": map_name, "game": game})

        all_maps.sort(key=lambda item: item["name"].lower())
        return all_maps

    def get_maps_for_game(self, game):
        if game == "ALL":
            return self.get_all_maps()

        return sorted(
            [{"name": map_name, "game": game} for map_name in MAPS_DATA[game]],
            key=lambda item: item["name"].lower()
        )

    def load_maps(self, game, search_text=""):
        for widget in self.maps_area.winfo_children():
            widget.destroy()

        maps = self.get_maps_for_game(game)

        if search_text:
            maps = [
                item for item in maps
                if search_text.lower() in item["name"].lower()
                or search_text.lower() in item["game"].lower()
            ]

        for index, map_info in enumerate(maps):
            card = self.create_map_card(map_info["name"], map_info["game"])
            card.grid(row=index // 2, column=index % 2, padx=14, pady=14, sticky="nsew")

        for column in range(2):
            self.maps_area.grid_columnconfigure(column, weight=1)

    def create_map_card(self, map_name, game_name):
        card = ctk.CTkFrame(
            self.maps_area,
            width=365,
            height=300,
            corner_radius=14,
            fg_color=CARD_BG,
            border_width=1,
            border_color=BORDER_RED,
            cursor="hand2"
        )
        card.grid_propagate(False)

        highest_round = self.get_highest_round(map_name, game_name)

        image = self.load_map_image_with_overlays(
            map_name=map_name,
            game_name=game_name,
            highest_round=highest_round,
            map_size=(330, 185),
            icon_size=(82, 82),
            digit_size=(34, 48)
        )

        if image:
            image_label = ctk.CTkLabel(
                card,
                image=image,
                text="",
                cursor="hand2"
            )
            image_label.image = image
            image_label.pack(pady=(14, 8))
        else:
            placeholder = ctk.CTkFrame(
                card,
                width=330,
                height=185,
                fg_color="#100808",
                border_width=1,
                border_color=BORDER_RED,
                cursor="hand2"
            )
            placeholder.pack(pady=(14, 8))
            placeholder.pack_propagate(False)

            placeholder_label = ctk.CTkLabel(
                placeholder,
                text="No Image",
                text_color=MUTED_TEXT,
                cursor="hand2"
            )
            placeholder_label.pack(expand=True)

        title_label = ctk.CTkLabel(
            card,
            text=map_name,
            font=("Arial", 19, "bold"),
            wraplength=320,
            text_color=TEXT,
            cursor="hand2"
        )
        title_label.pack(pady=(5, 2))

        game_label = ctk.CTkLabel(
            card,
            text=game_name,
            font=("Arial", 14),
            text_color=MUTED_TEXT,
            cursor="hand2"
        )
        game_label.pack(pady=2)

        def select_this_card(event=None):
            self.select_map(map_name, game_name)

        card.bind("<Button-1>", select_this_card)

        for child in card.winfo_children():
            child.bind("<Button-1>", select_this_card)

            try:
                child.configure(cursor="hand2")
            except Exception:
                pass

            for grandchild in child.winfo_children():
                grandchild.bind("<Button-1>", select_this_card)

                try:
                    grandchild.configure(cursor="hand2")
                except Exception:
                    pass

        return card

    def image_filename_from_map_name(self, map_name):
        filename = map_name.lower()
        filename = filename.replace(" ", "_").replace("-", "_").replace(":", "").replace("'", "")
        filename = filename.replace(".", "").replace(",", "").replace("(", "").replace(")", "").replace("&", "and")
        return filename + ".png"

    def game_icon_filename_from_game_name(self, game_name):
        filename = game_name.lower()
        filename = filename.replace(" ", "_").replace("-", "_").replace(":", "").replace("'", "")
        filename = filename.replace(".", "").replace(",", "").replace("(", "").replace(")", "").replace("&", "and")
        return filename + ".png"

    def load_map_image_with_overlays(self, map_name, game_name, highest_round, map_size, icon_size, digit_size):
        cache_key = (
            f"combined_{map_name}_{game_name}_{highest_round}_"
            f"{map_size[0]}x{map_size[1]}_{icon_size[0]}x{icon_size[1]}_{digit_size[0]}x{digit_size[1]}"
        )

        if cache_key in self.image_cache:
            return self.image_cache[cache_key]

        map_path = os.path.join(
            self.base_dir(),
            "assets",
            "map_images",
            self.image_filename_from_map_name(map_name)
        )
        icon_path = os.path.join(
            self.base_dir(),
            "assets",
            "game_icons",
            self.game_icon_filename_from_game_name(game_name)
        )

        if not os.path.exists(map_path):
            return None

        try:
            map_image = Image.open(map_path).convert("RGBA").resize(map_size)

            if os.path.exists(icon_path):
                icon_image = Image.open(icon_path).convert("RGBA").resize(icon_size)
                icon_x = 8
                icon_y = map_size[1] - icon_size[1] - 8
                map_image.alpha_composite(icon_image, dest=(icon_x, icon_y))

            map_image = self.paste_round_number_onto_image(
                map_image,
                highest_round,
                digit_size=digit_size,
                margin=8
            )

            ctk_image = ctk.CTkImage(light_image=map_image, dark_image=map_image, size=map_size)
            self.image_cache[cache_key] = ctk_image
            return ctk_image

        except Exception as error:
            print(f"Could not load image/icon/round for {map_name}: {error}")
            return None

    def load_game_icon(self, game_name, size=(40, 40)):
        cache_key = f"icon_{game_name}_{size[0]}x{size[1]}"

        if cache_key in self.image_cache:
            return self.image_cache[cache_key]

        path = os.path.join(
            self.base_dir(),
            "assets",
            "game_icons",
            self.game_icon_filename_from_game_name(game_name)
        )

        if not os.path.exists(path):
            return None

        try:
            image = Image.open(path).convert("RGBA").resize(size)
            ctk_image = ctk.CTkImage(light_image=image, dark_image=image, size=size)
            self.image_cache[cache_key] = ctk_image
            return ctk_image
        except Exception as error:
            print(f"Could not load icon for {game_name}: {error}")
            return None

    def select_map(self, map_name, game_name):
        self.play_sound("click.wav")

        self.selected_map = map_name
        self.selected_map_game = game_name

        highest_round = self.get_highest_round(map_name, game_name)

        image = self.load_map_image_with_overlays(
            map_name=map_name,
            game_name=game_name,
            highest_round=highest_round,
            map_size=(290, 165),
            icon_size=(74, 74),
            digit_size=(36, 52)
        )

        if image:
            self.details_image_label.configure(image=image, text="")
            self.details_image_label.image = image
        else:
            self.details_image_label.configure(image=None, text="No Image")

        game_icon = self.load_game_icon(game_name, size=(42, 42))

        if game_icon:
            self.details_game.configure(text="  " + game_name, image=game_icon, compound="left")
            self.details_game.image = game_icon
        else:
            self.details_game.configure(text=game_name, image=None)

        platform = self.launch_config.get(game_name, {}).get("platform", "not set")
        map_internal_name = MAP_LAUNCH_ARGS.get(game_name, {}).get(map_name, "")

        self.details_title.configure(text=map_name)
        description = MAP_DESCRIPTIONS.get(game_name, {}).get(
            map_name,
            f"{map_name} from {game_name}."
        )

        self.details_description.configure(
            text=f"{description}\n\nPlatform: {platform}\nInternal Map: {map_internal_name if map_internal_name else 'None'}\nVerified Highest Round:"
        )

        self.render_round_number(self.details_round_frame, highest_round, digit_size=(38, 56))
        self.launch_status.configure(text="")

    def get_launch_config_path(self):
        return os.path.join(self.base_dir(), "launch_config.json")

    def load_launch_config(self):
        config_path = self.get_launch_config_path()

        if not os.path.exists(config_path):
            self.save_default_launch_config()
            return DEFAULT_LAUNCH_CONFIG.copy()

        try:
            with open(config_path, "r", encoding="utf-8") as file:
                config = json.load(file)

            for game, default_settings in DEFAULT_LAUNCH_CONFIG.items():
                if game not in config:
                    config[game] = default_settings

            return config

        except Exception as error:
            print(f"Could not load launch_config.json: {error}")
            return DEFAULT_LAUNCH_CONFIG.copy()

    def save_default_launch_config(self):
        try:
            with open(self.get_launch_config_path(), "w", encoding="utf-8") as file:
                json.dump(DEFAULT_LAUNCH_CONFIG, file, indent=4)
            print("Created default launch_config.json.")
        except Exception as error:
            print(f"Could not create launch_config.json: {error}")

    def save_launch_config(self):
        try:
            with open(self.get_launch_config_path(), "w", encoding="utf-8") as file:
                json.dump(self.launch_config, file, indent=4)
            print("launch_config.json saved.")
        except Exception as error:
            print(f"Could not save launch_config.json: {error}")

    def get_waw_mods_folder(self):
        return os.path.join(
            os.environ.get("LOCALAPPDATA", ""),
            "Activision",
            "CoDWaW",
            "mods"
        )

    def get_bundled_waw_helper_mod_folder(self):
        return os.path.join(
            self.base_dir(),
            "assets",
            "waw_helper_mod",
            "launcher_helper"
        )

    def get_installed_waw_helper_mod_folder(self):
        return os.path.join(
            self.get_waw_mods_folder(),
            "launcher_helper"
        )

    def install_waw_helper_mod(self):
        source_folder = self.get_bundled_waw_helper_mod_folder()
        destination_folder = self.get_installed_waw_helper_mod_folder()

        if not os.path.exists(source_folder):
            self.launch_status.configure(text=f"Bundled WaW helper mod not found: {source_folder}")
            return False

        try:
            os.makedirs(self.get_waw_mods_folder(), exist_ok=True)

            if os.path.exists(destination_folder):
                shutil.rmtree(destination_folder)

            shutil.copytree(source_folder, destination_folder)

            self.launch_status.configure(text="WaW helper mod installed.")
            return True

        except Exception as error:
            self.launch_status.configure(text=f"Could not install WaW helper mod: {error}")
            return False

    def write_waw_selected_map(self, map_internal_name):
        installed_folder = self.get_installed_waw_helper_mod_folder()
        config_path = os.path.join(installed_folder, "launcher_selected_map.cfg")

        try:
            os.makedirs(installed_folder, exist_ok=True)

            with open(config_path, "w", encoding="utf-8") as file:
                file.write(f'set launcher_selected_map "{map_internal_name}"\n')

            return True

        except Exception as error:
            self.launch_status.configure(text=f"Could not write WaW selected map config: {error}")
            return False

    def open_settings_window(self):
        self.play_sound("click.wav")

        window = ctk.CTkToplevel(self)
        window.title("Game Platform Settings")
        window.geometry("560x540")
        window.minsize(500, 420)
        window.configure(fg_color=APP_BG)
        window.grab_set()

        selected_game = ctk.StringVar(value=list(MAPS_DATA.keys())[0])
        platform_value = ctk.StringVar(value="steam")
        steam_app_id_value = ctk.StringVar(value="")
        path_value = ctk.StringVar(value="")
        url_value = ctk.StringVar(value="")
        args_value = ctk.StringVar(value="")

        window.grid_columnconfigure(0, weight=1)
        window.grid_rowconfigure(0, weight=1)

        scroll_frame = ctk.CTkScrollableFrame(
            window,
            fg_color=PANEL_BG,
            scrollbar_button_color=DARK_RED,
            scrollbar_button_hover_color=RED
        )
        scroll_frame.grid(row=0, column=0, sticky="nsew", padx=15, pady=(15, 5))

        bottom_frame = ctk.CTkFrame(window, fg_color=PANEL_BG)
        bottom_frame.grid(row=1, column=0, sticky="ew", padx=15, pady=(5, 15))
        bottom_frame.grid_columnconfigure(0, weight=1)

        def load_game_settings(*args):
            game = selected_game.get()
            config = self.launch_config.get(game, DEFAULT_LAUNCH_CONFIG.get(game, {}))

            platform_value.set(config.get("platform", "steam"))
            steam_app_id_value.set(config.get("steam_app_id", ""))
            path_value.set(config.get("path", ""))
            url_value.set(config.get("url", ""))
            args_value.set(config.get("args", ""))

        def browse_file():
            self.play_sound("click.wav")

            file_path = filedialog.askopenfilename(
                title="Select launcher, game exe, or shortcut",
                filetypes=[
                    ("Executable or shortcut", "*.exe *.lnk"),
                    ("Executable", "*.exe"),
                    ("Shortcut", "*.lnk"),
                    ("All files", "*.*")
                ]
            )

            if file_path:
                path_value.set(file_path.replace("\\", "/"))

        def save_settings():
            game = selected_game.get()

            self.launch_config[game] = {
                "platform": platform_value.get(),
                "steam_app_id": steam_app_id_value.get(),
                "path": path_value.get(),
                "url": url_value.get(),
                "args": args_value.get()
            }

            self.save_launch_config()
            self.launch_status.configure(text="Platform settings saved.")
            self.play_sound("save.wav")
            window.destroy()

        ctk.CTkLabel(scroll_frame, text="Game", font=("Arial", 16, "bold"), text_color=TEXT).pack(pady=(10, 5))

        game_dropdown = ctk.CTkOptionMenu(
            scroll_frame,
            values=list(MAPS_DATA.keys()),
            variable=selected_game,
            command=load_game_settings,
            fg_color=RED,
            button_color=DARK_RED,
            button_hover_color=BRIGHT_RED
        )
        game_dropdown.pack(fill="x", padx=15, pady=5)

        ctk.CTkLabel(scroll_frame, text="Platform", font=("Arial", 16, "bold"), text_color=TEXT).pack(pady=(15, 5))

        platform_dropdown = ctk.CTkOptionMenu(
            scroll_frame,
            values=["steam", "battlenet", "xbox", "epic", "exe", "shortcut", "url"],
            variable=platform_value,
            fg_color=RED,
            button_color=DARK_RED,
            button_hover_color=BRIGHT_RED
        )
        platform_dropdown.pack(fill="x", padx=15, pady=5)

        ctk.CTkLabel(scroll_frame, text="Steam App ID", text_color=MUTED_TEXT).pack(pady=(15, 5))

        ctk.CTkEntry(
            scroll_frame,
            textvariable=steam_app_id_value,
            placeholder_text="Used only when platform is steam",
            fg_color=INPUT_BG,
            border_color=DARK_RED,
            text_color=TEXT,
            placeholder_text_color=MUTED_TEXT
        ).pack(fill="x", padx=15, pady=5)

        ctk.CTkLabel(scroll_frame, text="Path / Launcher / Shortcut", text_color=MUTED_TEXT).pack(pady=(15, 5))

        ctk.CTkEntry(
            scroll_frame,
            textvariable=path_value,
            placeholder_text="Used for battlenet, xbox, epic, exe, shortcut",
            fg_color=INPUT_BG,
            border_color=DARK_RED,
            text_color=TEXT,
            placeholder_text_color=MUTED_TEXT
        ).pack(fill="x", padx=15, pady=5)

        self.make_button(scroll_frame, text="Browse", command=browse_file).pack(padx=15, pady=5)

        ctk.CTkLabel(scroll_frame, text="URL", text_color=MUTED_TEXT).pack(pady=(15, 5))

        ctk.CTkEntry(
            scroll_frame,
            textvariable=url_value,
            placeholder_text="Used only when platform is url",
            fg_color=INPUT_BG,
            border_color=DARK_RED,
            text_color=TEXT,
            placeholder_text_color=MUTED_TEXT
        ).pack(fill="x", padx=15, pady=5)

        ctk.CTkLabel(scroll_frame, text="Launch Args", text_color=MUTED_TEXT).pack(pady=(15, 5))

        ctk.CTkEntry(
            scroll_frame,
            textvariable=args_value,
            placeholder_text="Optional launch arguments",
            fg_color=INPUT_BG,
            border_color=DARK_RED,
            text_color=TEXT,
            placeholder_text_color=MUTED_TEXT
        ).pack(fill="x", padx=15, pady=5)

        save_button = self.make_button(
            bottom_frame,
            text="Save Settings",
            height=42,
            command=save_settings
        )
        save_button.grid(row=0, column=0, sticky="ew", padx=10, pady=10)

        load_game_settings()

    def get_selected_map_args(self):
        return MAP_LAUNCH_ARGS.get(self.selected_map_game, {}).get(self.selected_map, "")

    def launch_map(self):
        if not self.selected_map or not self.selected_map_game:
            self.launch_status.configure(text="No map selected.")
            self.play_sound("error.wav")
            return

        game_config = self.launch_config.get(self.selected_map_game)

        if not game_config:
            self.launch_status.configure(text=f"No launch config found for {self.selected_map_game}.")
            self.play_sound("error.wav")
            return

        platform = game_config.get("platform", "").lower()
        base_args = game_config.get("args", "")
        map_internal_name = self.get_selected_map_args()

        try:
            if self.selected_map_game == "World at War" and map_internal_name:
                self.install_waw_helper_mod()
                self.write_waw_selected_map(map_internal_name)
                self.write_waw_current_map()
                self.start_waw_round_tracker_script()

            if platform == "steam":
                steam_app_id = game_config.get("steam_app_id", "")

                if not steam_app_id:
                    self.launch_status.configure(text="No Steam App ID set.")
                    self.play_sound("error.wav")
                    return

                if self.selected_map_game == "World at War" and map_internal_name:
                    steam_url = f"steam://run/{steam_app_id}//+map {map_internal_name}"
                else:
                    steam_url = f"steam://run/{steam_app_id}"
                webbrowser.open(steam_url)

                self.launch_status.configure(text=f"Launching {self.selected_map_game}...")
                self.play_sound("launch.wav")
                self.after(400, self.mute_launcher_audio)

            elif platform in ["battlenet", "xbox", "epic", "exe"]:
                path = game_config.get("path", "")

                if not path:
                    self.launch_status.configure(text="No path set for this platform.")
                    self.play_sound("error.wav")
                    return

                if not os.path.exists(path):
                    self.launch_status.configure(text=f"Path not found: {path}")
                    self.play_sound("error.wav")
                    return

                command = [path]

                if base_args:
                    command.extend(base_args.split())

                subprocess.Popen(command)

                self.launch_status.configure(text=f"Launching {self.selected_map_game}...")
                self.play_sound("launch.wav")
                self.after(400, self.mute_launcher_audio)

            elif platform == "shortcut":
                path = game_config.get("path", "")

                if not path:
                    self.launch_status.configure(text="No shortcut path set.")
                    self.play_sound("error.wav")
                    return

                if not os.path.exists(path):
                    self.launch_status.configure(text=f"Shortcut not found: {path}")
                    self.play_sound("error.wav")
                    return

                os.startfile(path)
                self.launch_status.configure(text=f"Opening shortcut for {self.selected_map_game}...")
                self.play_sound("launch.wav")
                self.after(400, self.mute_launcher_audio)

            elif platform == "url":
                url = game_config.get("url", "")

                if not url:
                    self.launch_status.configure(text="No URL set.")
                    self.play_sound("error.wav")
                    return

                webbrowser.open(url)
                self.launch_status.configure(text=f"Opening URL for {self.selected_map_game}...")
                self.play_sound("launch.wav")
                self.after(400, self.mute_launcher_audio)

            else:
                self.launch_status.configure(text=f"Unknown platform: {platform}")
                self.play_sound("error.wav")

        except Exception as error:
            self.launch_status.configure(text=f"Failed to launch: {error}")
            self.play_sound("error.wav")

    def search_maps(self, event=None):
        self.load_maps(self.selected_game, self.search_entry.get())

    def open_welcome_screen(self):
        window = ctk.CTkToplevel(self)
        window.title("Welcome to BDB Zombies Launcher")
        window.geometry("620x520")
        window.minsize(560, 460)
        window.configure(fg_color=APP_BG)
        window.grab_set()

        window.grid_columnconfigure(0, weight=1)
        window.grid_rowconfigure(1, weight=1)

        title = ctk.CTkLabel(
            window,
            text="Bedylsebub's Easy Zombie Loader",
            font=("Arial", 28, "bold"),
            text_color=TEXT
        )
        title.grid(row=0, column=0, padx=25, pady=(25, 10), sticky="ew")

        info_box = ctk.CTkTextbox(
            window,
            wrap="word",
            fg_color=PANEL_BG,
            text_color=TEXT,
            border_color=DARK_RED,
            border_width=1
        )
        info_box.grid(row=1, column=0, padx=25, pady=10, sticky="nsew")

        info_box.insert(
            "end",
            "This launcher can automatically look for your installed COD Zombies games.\n\n"
            "Steam games are detected using Steam library folders and app manifests.\n"
            "WaW round tracking reads from waw_round_tracker.json.\n\n"
            "For now, this welcome screen appears every time so we can keep tweaking it.\n"
        )
        info_box.configure(state="disabled")

        button_frame = ctk.CTkFrame(window, fg_color=PANEL_BG)
        button_frame.grid(row=2, column=0, padx=25, pady=(10, 25), sticky="ew")
        button_frame.grid_columnconfigure((0, 1), weight=1)

        def run_auto_detect():
            self.play_sound("click.wav")
            info_box.configure(state="normal")
            info_box.delete("1.0", "end")
            results = self.auto_detect_games()
            info_box.insert("end", "Auto detection complete.\n\n")

            for line in results:
                info_box.insert("end", line + "\n")

            info_box.configure(state="disabled")

        self.make_button(
            button_frame,
            text="Auto Detect Games",
            height=42,
            command=run_auto_detect
        ).grid(row=0, column=0, padx=(0, 8), pady=10, sticky="ew")

        self.make_button(
            button_frame,
            text="Continue",
            height=42,
            command=lambda: (self.play_sound("click.wav"), window.destroy())
        ).grid(row=0, column=1, padx=(8, 0), pady=10, sticky="ew")

    def auto_detect_games(self):
        results = []
        steam_results = self.detect_steam_games()

        for game, detected in steam_results.items():
            if detected:
                default_config = DEFAULT_LAUNCH_CONFIG.get(game, {})
                self.launch_config[game] = {
                    "platform": "steam",
                    "steam_app_id": default_config.get("steam_app_id", ""),
                    "path": "",
                    "url": "",
                    "args": ""
                }
                results.append(f"FOUND Steam: {game}")
            else:
                results.append(f"NOT FOUND on Steam: {game}")

        battlenet_path = self.find_battlenet_launcher()

        if battlenet_path:
            for game in ["Black Ops 4", "Black Ops Cold War"]:
                if game in MAPS_DATA:
                    self.launch_config[game] = {
                        "platform": "battlenet",
                        "steam_app_id": "",
                        "path": battlenet_path,
                        "url": "",
                        "args": ""
                    }
            results.append(f"FOUND Battle.net launcher: {battlenet_path}")
        else:
            results.append("NOT FOUND: Battle.net launcher")

        epic_path = self.find_epic_launcher()

        if epic_path:
            results.append(f"FOUND Epic launcher: {epic_path}")
        else:
            results.append("NOT FOUND: Epic launcher")

        self.save_launch_config()
        self.play_sound("save.wav")
        return results

    def detect_steam_games(self):
        steam_libraries = self.find_steam_libraries()

        steam_games = {
            "World at War": "10090",
            "Black Ops": "42700",
            "Black Ops II": "212910",
            "Black Ops III": "311210"
        }

        results = {}

        for game, app_id in steam_games.items():
            results[game] = False

            for library in steam_libraries:
                manifest_path = os.path.join(library, "steamapps", f"appmanifest_{app_id}.acf")

                if os.path.exists(manifest_path):
                    results[game] = True
                    break

        return results

    def find_steam_libraries(self):
        possible_paths = [
            "C:/Program Files (x86)/Steam",
            "C:/Program Files/Steam"
        ]

        libraries = []

        for steam_path in possible_paths:
            if os.path.exists(steam_path):
                libraries.append(steam_path)

                library_file = os.path.join(steam_path, "steamapps", "libraryfolders.vdf")

                if os.path.exists(library_file):
                    try:
                        with open(library_file, "r", encoding="utf-8", errors="ignore") as file:
                            content = file.read()

                        found_paths = re.findall(r'"path"\s+"([^"]+)"', content)

                        for path in found_paths:
                            clean_path = path.replace("\\\\", "/").replace("\\", "/")

                            if os.path.exists(clean_path):
                                libraries.append(clean_path)

                    except Exception as error:
                        print(f"Could not read Steam libraryfolders.vdf: {error}")

        unique_libraries = []

        for library in libraries:
            if library not in unique_libraries:
                unique_libraries.append(library)

        return unique_libraries

    def find_battlenet_launcher(self):
        possible_paths = [
            "C:/Program Files (x86)/Battle.net/Battle.net Launcher.exe",
            "C:/Program Files/Battle.net/Battle.net Launcher.exe"
        ]

        for path in possible_paths:
            if os.path.exists(path):
                return path.replace("\\", "/")

        return ""

    def find_epic_launcher(self):
        possible_paths = [
            "C:/Program Files (x86)/Epic Games/Launcher/Portal/Binaries/Win64/EpicGamesLauncher.exe",
            "C:/Program Files/Epic Games/Launcher/Portal/Binaries/Win64/EpicGamesLauncher.exe"
        ]

        for path in possible_paths:
            if os.path.exists(path):
                return path.replace("\\", "/")

        return ""


if __name__ == "__main__":
    app = ZombiesMapLoader()
    app.mainloop()