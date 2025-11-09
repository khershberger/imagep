import os
import xml.etree.ElementTree as ET
import logging
import math
import requests
from io import BytesIO
from math import log2, ceil
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

        self.tile_cache = {}  # (level, col, row): QImage
        self.cache_limit = 128  # default number of non-visible tiles to keep
        self.cache_hit_rate = 0.0  # Initial cache hit percentage
        self.cache_hit_rate_alpha = 0.05  # Alpha factor for exponential averaging

        self.level_threshold = 0.0  # Threshold adjustment for level switching

        self.image_converter = self._convert_qimage

    def set_tile_cache_limit(self, limit):
        self.cache_limit = limit
        self._enforce_cache_limit()

    def set_level_threshold(self, threshold):
        self.level_threshold = threshold

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

    def level_scale(self, level):
        return 2 ** (level - self.max_level)

    def choose_level(self, scale):
        # Choose level based on scale and threshold
        level = ceil(self.max_level + self.level_threshold + log2(scale))
        level = max(0, min(self.max_level, level))
        return level

    def get_tile_path(self, level, col, row):
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

    def _load_tile_from_source(self, level, col, row) -> bytes:
        tile_path = self.get_tile_path(level, col, row)
        if self.is_url:
            resp = requests.get(tile_path)
            resp.raise_for_status()
            return resp.content
        else:
            if not os.path.exists(tile_path):
                raise FileNotFoundError(f"Tile not found: {tile_path}")
            with open(tile_path, "rb") as f:
                return f.read()

    def _update_cache_hit(self, is_hit: bool):
        self.cache_hit_rate = (
            1.0 if is_hit else 0.0
        ) * self.cache_hit_rate_alpha + self.cache_hit_rate * (
            1 - self.cache_hit_rate_alpha
        )

    def get_tile(self, level, col, row):
        key = (level, col, row)

        if key in self.tile_cache:
            # self.log.debug(f"Cache hit for tile {key}")
            self._update_cache_hit(True)
            return self.tile_cache[key]

        # self.log.debug(f"Loading tile {key}")
        self._update_cache_hit(False)
        data = self.image_converter(self._load_tile_from_source(level, col, row))

        self.tile_cache[key] = data
        self._enforce_cache_limit()
        return data

    def cache_tiles(self, tile_list: list):
        num_tiles = len(tile_list)
        # Check that tile cache is large enough:
        if num_tiles > self.cache_limit:
            self.log.warning("Number of tiles in cache requests exceeds cache limit")
        self.log.debug("Pre-loading %d tiles.", num_tiles)

        t_start = time()
        for item in tile_list:
            self.get_tile(item["level"], item["col"], item["row"])
        t_finish = time()
        self.log.debug(
            "Pre-load operation took %f seconds. Hit-rate: %f",
            t_finish - t_start,
            self.cache_hit_rate,
        )

    def get_visible_tiles(self, x, y, width, height, level):
        # Determine visible tiles
        max_col, max_row = self.max_tile_index(level)
        col0, row0 = self.image_coords_to_tile_index(x, y, level)
        col1, row1 = self.image_coords_to_tile_index(x + width, y + height, level)
        row0 = max(0, row0)
        col0 = max(0, col0)
        row1 = min(max_row, row1)
        col1 = min(max_col, col1)

        # Tile list:
        tile_list = []
        for row in range(row0, row1 + 1):
            for col in range(col0, col1 + 1):
                tile_list.append({"level": level, "col": col, "row": row})

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

    def _enforce_cache_limit(self):
        if len(self.tile_cache) > self.cache_limit:
            # Remove oldest
            keys = list(self.tile_cache.keys())
            for k in keys[: len(self.tile_cache) - self.cache_limit]:
                # self.log.debug(f"Evicting tile {k} from cache")
                del self.tile_cache[k]

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
