import math
import os
import xml.etree.ElementTree as ET
import xml.dom.minidom
from PIL import Image, ImageDraw, ImageFont


def create_sample(
    width,
    height,
    tile_size,
    overlap,
    filename,
    format="jpg",
    pixels_per_meter=None,
    color_bg="white",
):
    # Calculate max level
    max_dim = max(width, height)
    max_level = int(math.ceil(math.log2(max_dim)))
    # Create output dirs
    base = os.path.splitext(filename)[0]
    files_dir = f"{base}_files"
    os.makedirs(files_dir, exist_ok=True)

    # Compute image image size
    image_size = tile_size + overlap * 2

    # Create tiles for each level
    for level in range(max_level + 1):
        level_scale = 2 ** (max_level - level)
        level_width = int(math.ceil(width / level_scale))
        level_height = int(math.ceil(height / level_scale))
        level_dir = os.path.join(files_dir, str(level))
        os.makedirs(level_dir, exist_ok=True)
        cols = int(math.ceil(level_width / tile_size))
        rows = int(math.ceil(level_height / tile_size))
        for row in range(rows):
            for col in range(cols):
                x0 = col * tile_size
                y0 = row * tile_size
                x1 = min(x0 + tile_size, level_width) + 2 * overlap
                y1 = min(y0 + tile_size, level_height) + 2 * overlap
                img = Image.new("RGB", (x1 - x0, y1 - y0), "white")
                draw = ImageDraw.Draw(img)

                x_center = int(level_scale * (x0 + tile_size / 2))
                y_center = int(level_scale * (y0 + tile_size / 2))

                # Draw border
                draw.rectangle(
                    [(0, 0), (img.width - 1, img.height - 1)], outline="red", width=1
                )
                if img.width > 4 and img.height > 4:
                    draw.rectangle(
                        [(1, 1), (img.width - 2, img.height - 2)],
                        outline="blue",
                        width=1,
                    )

                # Draw center dot
                draw.circle(
                    ((img.width // 2) - 1, (img.height // 2) - 1),
                    2,
                    fill="black",
                    width=2,
                )

                # Draw label
                draw_label(
                    draw,
                    (img.width // 2, (img.height // 2) - 25),
                    f"L{level} R{row} C{col}",
                )
                draw_label(
                    draw,
                    (img.width // 2, (img.height // 2) + 25),
                    f"({x_center},{y_center})",
                )

                # Save tile
                tile_path = os.path.join(level_dir, f"{col}_{row}.{format}")
                save_format = "JPEG" if format.lower() == "jpg" else format.upper()
                img.save(tile_path, format=save_format)
    # Write DZI XML
    dzi = ET.Element(
        "Image",
        TileSize=str(tile_size),
        Overlap=str(overlap),
        Format=format,
        xmlns="http://schemas.microsoft.com/deepzoom/2008",
    )
    size_elem = ET.SubElement(dzi, "Size", Width=str(width), Height=str(height))
    if pixels_per_meter is not None:
        ET.SubElement(
            dzi,
            "Scale",
            PixelsPerMeter=str(pixels_per_meter),
        )
    tree = ET.ElementTree(dzi)

    # Pretty-print the XML
    dom = xml.dom.minidom.parseString(ET.tostring(dzi, encoding="utf-8"))
    pretty_xml_as_str = dom.toprettyxml(indent="  ")
    with open(filename, "w", encoding="utf-8") as f:
        f.write(pretty_xml_as_str)


def draw_label(draw, pos, label):
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 28)
    except Exception:
        font = ImageFont.load_default()
    # Calculate text size (Pillow >=8.0: use textbbox, else fallback to getsize)
    try:
        bbox = draw.textbbox((0, 0), label, font=font)
        text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    except AttributeError:
        text_w, text_h = font.getsize(label)

    draw.text(
        (pos[0] - (text_w // 2), pos[1] - (text_h) // 2),
        label,
        fill="black",
        font=font,
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Create a sample Deep Zoom image.")
    parser.add_argument("--width", type=int, required=True, help="Full image width")
    parser.add_argument("--height", type=int, required=True, help="Full image height")
    parser.add_argument("--tile-size", type=int, required=True, help="Tile size")
    parser.add_argument("--overlap", type=int, required=True, help="Tile overlap")
    parser.add_argument(
        "--filename", type=str, required=True, help="Output .dzi filename"
    )
    parser.add_argument(
        "--format",
        type=str,
        default="jpg",
        choices=["jpg", "png"],
        help="Tile image format",
    )
    args = parser.parse_args()
    create_sample(
        args.width,
        args.height,
        args.tile_size,
        args.overlap,
        args.filename,
        args.format,
    )
