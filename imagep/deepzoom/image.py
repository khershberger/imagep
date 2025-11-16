from __future__ import annotations

import logging
import math
import os
import queue
import requests
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from io import BytesIO
from math import log2, ceil
from threading import Lock, Thread
from time import time
from urllib.parse import urlparse

from PIL import Image
from PySide6.QtGui import QImage


class DeepzoomImage:
    """
    Loads and parses Deep Zoom .dzi files, provides metadata, and loads image tiles (local or remote).
    """

    def __init__(self, source):
        self.log = logging.getLogger("DeepzoomImage")

        self.source = source
        self.is_url = self._is_url(source)

        self._parse_dzi()

        self.log = logging.getLogger("DeepzoomImage")

        self.use_threading = True
        self.max_threads = 8
        self.allow_background = True
        self.timeout = 10.0
        self.thread_io = None
        self.tile_queue = queue.Queue()

        self.tile_cache: dict[DeepzoomTile] = {}  # (level, col, row): QImage
        self.tile_cache_lock = Lock()
        self.cache_limit = 128  # default number of non-visible tiles to keep

        self.level_threshold = 0.0  # Threshold adjustment for level switching

        self.image_converter = self._convert_qimage

    def set_tile_cache_limit(self, limit):
        self.cache_limit = limit
        self._enforce_cache_limit()

    def set_level_threshold(self, threshold):
        self.level_threshold = threshold

    def level_scale(self, level):
        return 2 ** (level - self.max_level)

    def _is_url(self, path):
        return urlparse(path).scheme in ("http", "https")

    def _parse_dzi(self):
        if self.is_url:
            resp = requests.get(self.source)
            resp.raise_for_status()
            xml_data = resp.content
        else:
            with open(self.source, "rb") as f:
                xml_data = f.read()
        tree = ET.fromstring(xml_data)

        self.tile_size = int(tree.attrib["TileSize"])
        self.tile_overlap = int(tree.attrib["Overlap"])
        self.image_format = tree.attrib["Format"]
        size_elem = tree.find("{http://schemas.microsoft.com/deepzoom/2008}Size")
        self.width = int(size_elem.attrib["Width"])
        self.height = int(size_elem.attrib["Height"])
        self.max_level = self._calc_max_level(self.width, self.height)

    def _calc_max_level(self, width, height):
        return int(math.ceil(math.log2(max(width, height))))

    def max_tile_index(self, level):
        scale_level = self.level_scale(level)
        max_idx_x = int(((self.width - 1) * scale_level) // self.tile_size)
        max_idx_y = int(((self.height - 1) * scale_level) // self.tile_size)
        return (max_idx_x, max_idx_y)

    def choose_level(self, scale):
        # Choose level based on scale and threshold
        level = ceil(self.max_level + self.level_threshold + log2(scale))
        level = max(0, min(self.max_level, level))
        return level

    def _get_tile_source_path(self, level, col, row):
        base = self.source
        if self.is_url:
            base = base[: base.rfind(".")]
            files_url = f"{base}_files/{level}/{col}_{row}.{self.image_format}"
            return files_url
        else:
            base = os.path.splitext(base)[0]
            files_path = os.path.join(
                f"{base}_files", str(level), f"{col}_{row}.{self.image_format}"
            )
            return files_path

    def _load_tile_source(self, level, col, row) -> bytes:
        tile_path = self._get_tile_source_path(level, col, row)
        if self.is_url:
            resp = requests.get(tile_path)
            resp.raise_for_status()
            return resp.content
        else:
            if not os.path.exists(tile_path):
                raise FileNotFoundError(f"Tile not found: {tile_path}")
            with open(tile_path, "rb") as f:
                return f.read()

    def get_tile_data(self, tile: DeepzoomTile, callback=None):
        # Check if tile is in tile_cache and data exists
        # This is likely vestigial at this point
        if tile.key in self.tile_cache and tile.data is not None:
            return tile.data

        # Load tile source since not available in cache
        # self.log.debug(f"Loading tile {tile.key}")

        tile.data = self.image_converter(
            self._load_tile_source(tile.level, tile.col, tile.row)
        )
        self._add_tile_to_cache(tile)
        if callback is not None:
            callback(tile)
        return tile

    def cache_tiles(self, tile_list: list):
        # Check that tile cache is large enough:
        num_tiles = len(tile_list)
        if num_tiles > self.cache_limit:
            self.log.warning("Number of tiles in cache requests exceeds cache limit")
        # self.log.debug("Pre-loading %d tiles.", num_tiles)

        t_start = time()
        if self.use_threading:
            # Empty queue of prior requests
            num_purged = 0
            while not self.tile_queue.empty():
                try:
                    self.tile_queue.get_nowait()
                    self.tile_queue.task_done()
                    num_purged += 1
                except queue.Empty:
                    break
            # if num_purged > 0:
            #   self.log.debug("Purged %d tiles from queue", num_purged)

            # Put new items in queue:
            for tile in tile_list:
                if tile.data is None:
                    self.tile_queue.put(tile)

            if self.allow_background:
                self._start_io_thread(timeout=self.timeout)
            else:
                self.worker_io(timeout=0)
        else:
            for tile in tile_list:
                self.get_tile_data(tile)

    def get_visible_tiles(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        display_width: int = None,
        display_height: int = None,
        load_data=True,
    ) -> list[DeepzoomImage]:
        # Determine scale
        if display_width is not None and display_height is not None:
            scale = ((display_width / width) + (display_height / height)) / 2
        else:
            scale = 1.0

        # Determine deepzoom level
        level_stop = self.choose_level(scale)
        level_start = max(0, level_stop - 2)
        levels = list(range(level_start, level_stop + 1))

        # Determine visible tiles
        tile_list = []
        for level in levels:
            max_col, max_row = self.max_tile_index(level)
            col0, row0 = self.image_coords_to_tile_index(x, y, level)
            col1, row1 = self.image_coords_to_tile_index(x + width, y + height, level)
            row0 = max(0, row0)
            col0 = max(0, col0)
            row1 = min(max_row, row1)
            col1 = min(max_col, col1)

            # Add to Tile list:
            for row in range(row0, row1 + 1):
                for col in range(col0, col1 + 1):
                    # Get tile from cache if possible, otherwise create new
                    tile = self.tile_cache.get(
                        (level, row, col),
                        DeepzoomTile(image=self, row=row, col=col, level=level),
                    )
                    tile_list.append(tile)

        if load_data:
            self.cache_tiles(tile_list)

        return tile_list

    def render_region(self, x, y, width, height, level):
        tile_list = self._get_visible_tiles(x, y, width, height, level)
        # Preload all tiles to facilitate parallel IO operations
        self.cache_tiles(tile_list)

        for item in tile_list:
            # This should always be pulling from cache
            img = self.get_tile(item["level"], item["col"], item["row"])
            scale_level = self.level_scale(level)

            if img:
                rx = int(item["col"] * self.tile_size / scale_level)
                ry = int(item["row"] * self.tile_size / scale_level)
                rw = int(img.width() / scale_level)
                rh = int(img.height() / scale_level)

                # ToDo: Peform rendering
            else:
                self.log.warning(
                    "Error loading tile (R%d, C%d)", item["row"], item["col"]
                )

    def _convert_qimage(self, data: bytes):
        img = Image.open(BytesIO(data)).convert("RGBA")
        qimg = QImage(
            img.tobytes("raw", "RGBA"),
            img.width,
            img.height,
            QImage.Format_RGBA8888,
        )
        return qimg

    def _add_tile_to_cache(self, tile):
        with self.tile_cache_lock:
            self.tile_cache[tile.key] = tile
        self._enforce_cache_limit()

    def _enforce_cache_limit(self):
        with self.tile_cache_lock:
            if len(self.tile_cache) > self.cache_limit:
                # Remove oldest
                keys = list(self.tile_cache.keys())
                for key in keys[: len(self.tile_cache) - self.cache_limit]:
                    # self.log.debug(f"Evicting tile {k} from cache")
                    # Dereference tile data
                    self.tile_cache[key].data = None
                    # Remove tile from cache
                    del self.tile_cache[key]

    def _start_io_thread(self, timeout=5):
        if self.thread_io is None or not self.thread_io.is_alive():
            self.log.debug("Starting new IO worker thread")
            self.thread_io = Thread(target=self.worker_io, kwargs={"timeout": timeout})
            self.thread_io.start()

    def worker_io(self, timeout=5):
        self.log.debug("Worker started")

        active_threads = []
        while True:
            # Clear completed threads from active_threads
            num_prior = len(active_threads)
            active_threads = list(filter(lambda x: x.is_alive(), active_threads))
            num_active = len(active_threads)
            num_completed = num_prior - num_active

            # Mark queue tasks as completed
            for k in range(num_completed):
                self.tile_queue.task_done()

            # Fetch new tasks from queue
            try:
                for k in range(self.max_threads - num_active):
                    tile = self.tile_queue.get(timeout=timeout)

                    if tile.data is None:
                        new_thread = Thread(target=self.get_tile_data, args=[tile])
                        new_thread.start()
                        active_threads.append(new_thread)
            except queue.Empty:
                break

        self.log.debug("Queue empty, waiting for active threads to finish")
        for thread in active_threads:
            thread.join()

        self.log.debug("Worker sopping due to queue timeout")

    def image_coords_to_tile_index(self, x, y, level):
        tile_scale = self.level_scale(level)
        return (
            int((x * tile_scale) // self.tile_size),
            int((y * tile_scale) // self.tile_size),
        )

    def tile_index_to_image_coords(self, idx_x, idx_y, level):
        tile_scale = self.level_scale(level)
        return (
            (idx_x * self.tile_size) / tile_scale,
            (idx_y * self.tile_size) / tile_scale,
        )


@dataclass
class DeepzoomTile:
    image: DeepzoomImage = field(repr=False)
    level: int
    row: int
    col: int
    x0: int = field(default=None, repr=False)
    y0: int = field(default=None, repr=False)
    width: int = field(default=None, repr=False)
    height: int = field(default=None, repr=False)
    data: object = None

    def __post_init__(self):
        scale = self.image.level_scale(self.level)

        self.x0 = int(self.col * self.image.tile_size / scale)
        self.y0 = int(self.row * self.image.tile_size / scale)

        scaled_tile_img_size = (self.image.tile_size + self.image.tile_overlap) / scale

        # Calculate tile width, accounting for smaller tiles along edges
        self.width = min(self.image.width - self.x0, scaled_tile_img_size)
        self.height = min(self.image.height - self.y0, scaled_tile_img_size)

    @property
    def available(self):
        return False if self.data is None else True

    @property
    def key(self):
        return (self.level, self.row, self.col)

    def set_data(self, new_data):
        self.data = new_data
