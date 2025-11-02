import os
import xml.etree.ElementTree as ET
import math
import requests
from io import BytesIO
from math import log2, ceil
from urllib.parse import urlparse

from PIL import Image

from PySide6.QtGui import QImage


class DeepzoomImage:
    """
    Loads and parses Deep Zoom .dzi files, provides metadata, and loads image tiles (local or remote).
    """

    def __init__(self, source):
        self.source = source
        self.is_url = self._is_url(source)

        self._parse_dzi()

        self.tile_cache = {}  # (level, col, row): QImage
        self.cache_limit = 128  # default number of non-visible tiles to keep
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

    def load_tile(self, level, col, row) -> bytes:
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

    def get_tile(self, level, col, row):
        key = (level, col, row)
        if key in self.tile_cache:
            # self.log.debug(f"Cache hit for tile {key}")
            return self.tile_cache[key]

        # self.log.debug(f"Loading tile {key}")
        data = self.image_converter(self.load_tile(level, col, row))

        self.tile_cache[key] = data
        self._enforce_cache_limit()
        return data

    def render_region(self, x, y, width, height, level):
        # Determine visible tiles
        max_col, max_row = self.max_tile_index(level)
        col0, row0 = self.image_coords_to_tile_index(x, y, level)
        col1, row1 = self.image_coords_to_tile_index(x + width, y + height, level)
        row0 = max(0, row0)
        col0 = max(0, col0)
        row1 = min(max_row, row1)
        col1 = min(max_col, col1)

        for row in range(row0, row1 + 1):
            for col in range(col0, col1 + 1):
                img = self.reader.get_tile(level, col, row)

                if img:
                    # ToDo: Peform rendering
                    pass
                else:
                    self.log.warning("Error loading tile (R%d, C%d)", row, col)

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
