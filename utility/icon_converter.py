#!/usr/bin/env python3
"""Script to convert .ico files to base64 encoded strings for use in icons.py."""

import argparse
import base64
from pathlib import Path
from PIL import Image
import io


def convert_icon_to_base64(ico_path: str, size: tuple = (32, 32)) -> str:
    """Convert an .ico file to a base64 encoded PNG string.

    Args:
        ico_path: Path to the .ico file
        size: Tuple of (width, height) to resize the icon to. Default is (32, 32)

    Returns:
        Base64 encoded string of the icon in PNG format
    """
    # Open and resize the icon
    with Image.open(ico_path) as img:
        if img.size != size:
            img = img.resize(size, Image.Resampling.LANCZOS)

        # Convert to PNG in memory
        buf = io.BytesIO()
        img.save(buf, format="PNG")

        # Convert to base64
        encoded = base64.b64encode(buf.getvalue()).decode("utf-8")

        # Format the output in chunks of 76 characters
        lines = [encoded[i : i + 76] for i in range(0, len(encoded), 76)]
        return "\n".join(lines)


def update_icons_file(icon_name: str, base64_data: str, icons_file: Path):
    """Update the icons.py file with a new icon.

    Args:
        icon_name: Name for the icon constant
        base64_data: Base64 encoded string of the icon
        icons_file: Path to the icons.py file
    """
    # Read existing content
    if icons_file.exists():
        content = icons_file.read_text()
    else:
        content = (
            '"""Module containing application icons as base64 encoded strings."""\n\n'
        )
        content += "# The following icons are stored as base64 encoded strings.\n"
        content += "# Use the icon_converter.py script to add new icons.\n\n"

    # Create the new icon constant
    new_icon = f'{icon_name} = """\n{base64_data}\n"""\n'

    # Add the new icon if it doesn't exist, or update it if it does
    if icon_name in content:
        # Replace existing icon
        import re

        pattern = f'{icon_name} = """[^"]*"""'
        content = re.sub(pattern, new_icon.strip(), content)
    else:
        # Add new icon
        content += "\n" + new_icon

    # Write back to file
    icons_file.write_text(content)


def main():
    parser = argparse.ArgumentParser(
        description="Convert .ico files to base64 encoded strings"
    )
    parser.add_argument("ico_file", help="Path to the .ico file to convert")
    parser.add_argument("--name", help="Name for the icon constant", required=True)
    parser.add_argument("--size", help="Icon size (default: 32x32)", default="32x32")
    parser.add_argument(
        "--output", help="Path to icons.py file", default="imagep/icons.py"
    )

    args = parser.parse_args()

    # Parse size
    width, height = map(int, args.size.split("x"))

    # Convert icon
    base64_data = convert_icon_to_base64(args.ico_file, (width, height))

    # Update icons.py
    update_icons_file(args.name, base64_data, Path(args.output))
    print(f"Successfully added/updated icon '{args.name}' in {args.output}")


if __name__ == "__main__":
    main()
