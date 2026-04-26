#!/usr/bin/env python3
"""Medal of Honor PS1 asset extraction pipeline.

The source tree is expected to be a locally extracted PS1 disc filesystem.
This script keeps the original dump untouched and writes derived assets into
artifacts/ps1_extract:

- RSC archives are unpacked using their internal file table.
- TIM images from standalone files, RSC entries and TAF streams are written as
  raw TIM chunks and PNG previews.
- TAF trailing payloads and BSD offset-table chunks are carved for later
  reverse engineering.
- STR movie files, VB/VAB audio banks and executable/overlay strings are
  cataloged.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import struct
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

try:
    from PIL import Image
except Exception:  # pragma: no cover - handled at runtime.
    Image = None  # type: ignore[assignment]


RSC_ENTRY_SIZE = 0x50
RSC_ENTRY_NAME_SIZE = 0x40
RSC_HEADER_SIZE = 0x48
TIM_MAGIC = b"\x10\x00\x00\x00"
ASCII_RE = re.compile(rb"[\x20-\x7e]{4,}")
STRING_EXTENSIONS = {".74", ".bin", ".sst", ".psx", ".bat", ".gfx"}


@dataclass
class TimBlock:
    offset: int
    end: int
    flags: int
    bpp: int
    has_clut: bool
    clut_rect: tuple[int, int, int, int] | None
    clut_data_offset: int | None
    image_rect: tuple[int, int, int, int]
    image_data_offset: int
    image_data_len: int


@dataclass
class TimExport:
    source: str
    kind: str
    index: int
    offset: int
    flags: int
    bpp: int
    has_clut: bool
    clut_rect: tuple[int, int, int, int] | None
    image_rect: tuple[int, int, int, int]
    pixel_size: tuple[int, int]
    raw_path: str
    png_paths: list[str]


@dataclass
class RscEntry:
    archive: str
    package: str
    index: int
    internal_path: str
    size: int
    offset: int
    flags: int
    output_path: str


@dataclass
class TafSummary:
    source: str
    size: int
    tim_count: int
    tim_bytes: int
    tail_offset: int | None
    tail_size: int
    tail_path: str | None


@dataclass
class BsdSummary:
    source: str
    size: int
    entry_count: int
    table_end: int
    first_offset: int | None
    unique_chunk_count: int
    header_body_path: str | None
    chunk_paths: list[str]


def project_root_from_script() -> Path:
    return Path(__file__).resolve().parents[1]


def default_source_dir(project_root: Path) -> Path:
    return project_root.parent / "[PS1] Medal of Honor (PT-BR) [Dublado e Traduzido]"


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def clean_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    ensure_dir(path)


def rel_to(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve()).replace("\\", "/")


def sanitize_part(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value)
    cleaned = cleaned.strip("._")
    return cleaned or "item"


def safe_relpath(value: str) -> Path:
    parts = re.split(r"[\\/]+", value.strip("\\/"))
    return Path(*[sanitize_part(part) for part in parts if part])


def add_name_suffix(path: Path, suffix: str) -> Path:
    if path.suffix:
        return path.with_name(f"{path.stem}__{suffix}{path.suffix}")
    return path.with_name(f"{path.name}__{suffix}")


def append_extension(path: Path, extension: str) -> Path:
    return path.with_name(f"{path.name}{extension}")


def is_disc_artifact(path: Path, source_root: Path) -> bool:
    if path.parent.resolve() != source_root.resolve():
        return False
    suffix = path.suffix.lower()
    if suffix in {".cue", ".jpg", ".rar"}:
        return True
    if suffix == ".bin":
        matching_cue = path.with_suffix(".cue")
        return matching_cue.exists() or path.stat().st_size > 100 * 1024 * 1024
    return False


def c_string(raw: bytes) -> str:
    raw = raw.split(b"\x00", 1)[0]
    raw = raw.replace(b"\xcd", b"")
    return raw.decode("ascii", errors="replace").strip()


def read_u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def read_u16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def psx555_to_rgba(value: int) -> tuple[int, int, int, int]:
    r = (value & 0x1F) << 3
    g = ((value >> 5) & 0x1F) << 3
    b = ((value >> 10) & 0x1F) << 3
    r |= r >> 5
    g |= g >> 5
    b |= b >> 5
    if value == 0:
        alpha = 0
    elif value & 0x8000:
        alpha = 160
    else:
        alpha = 255
    return (r, g, b, alpha)


def parse_tim_at(data: bytes, offset: int) -> TimBlock | None:
    if offset < 0 or offset + 20 > len(data):
        return None
    if data[offset:offset + 4] != TIM_MAGIC:
        return None

    flags = read_u32(data, offset + 4)
    bpp = flags & 0x07
    has_clut = bool(flags & 0x08)
    if bpp not in (0, 1, 2, 3):
        return None
    if flags & ~0x0F:
        return None

    pos = offset + 8
    clut_rect: tuple[int, int, int, int] | None = None
    clut_data_offset: int | None = None

    if has_clut:
        if pos + 12 > len(data):
            return None
        block_len, x, y, w, h = struct.unpack_from("<IHHHH", data, pos)
        if w == 0 or h == 0 or block_len < 12:
            return None
        if block_len != 12 + (w * h * 2):
            return None
        if pos + block_len > len(data):
            return None
        clut_rect = (x, y, w, h)
        clut_data_offset = pos + 12
        pos += block_len

    if pos + 12 > len(data):
        return None
    block_len, x, y, w, h = struct.unpack_from("<IHHHH", data, pos)
    if w == 0 or h == 0 or block_len < 12:
        return None
    image_data_len = block_len - 12
    if image_data_len != w * h * 2:
        return None
    if pos + block_len > len(data):
        return None

    pixel_w, pixel_h = tim_pixel_size(bpp, w, h)
    if pixel_w <= 0 or pixel_h <= 0 or pixel_w > 4096 or pixel_h > 4096:
        return None

    return TimBlock(
        offset=offset,
        end=pos + block_len,
        flags=flags,
        bpp=bpp,
        has_clut=has_clut,
        clut_rect=clut_rect,
        clut_data_offset=clut_data_offset,
        image_rect=(x, y, w, h),
        image_data_offset=pos + 12,
        image_data_len=image_data_len,
    )


def parse_sequential_tim(data: bytes) -> list[TimBlock]:
    blocks: list[TimBlock] = []
    pos = 0
    while pos < len(data):
        block = parse_tim_at(data, pos)
        if block is None:
            break
        blocks.append(block)
        pos = block.end
    return blocks


def tim_pixel_size(bpp: int, width_words: int, height: int) -> tuple[int, int]:
    if bpp == 0:
        return (width_words * 4, height)
    if bpp == 1:
        return (width_words * 2, height)
    if bpp == 2:
        return (width_words, height)
    row_bytes = width_words * 2
    return (row_bytes // 3, height)


def palette_rows(data: bytes, block: TimBlock) -> list[list[tuple[int, int, int, int]]]:
    if not block.has_clut or block.clut_rect is None or block.clut_data_offset is None:
        return []
    _, _, width, height = block.clut_rect
    rows: list[list[tuple[int, int, int, int]]] = []
    offset = block.clut_data_offset
    for row in range(height):
        colors = []
        for col in range(width):
            value = read_u16(data, offset + ((row * width + col) * 2))
            colors.append(psx555_to_rgba(value))
        rows.append(colors)
    return rows


def decode_tim_images(data: bytes, block: TimBlock) -> list[tuple[str, Any]]:
    if Image is None:
        return []

    x_words = block.image_rect[2]
    height = block.image_rect[3]
    image_data = data[block.image_data_offset:block.image_data_offset + block.image_data_len]
    width, pixel_h = tim_pixel_size(block.bpp, x_words, height)

    if block.bpp == 2:
        image = Image.new("RGBA", (width, pixel_h))
        pixels = image.load()
        cursor = 0
        for y in range(pixel_h):
            for x in range(width):
                value = struct.unpack_from("<H", image_data, cursor)[0]
                pixels[x, y] = psx555_to_rgba(value)
                cursor += 2
        return [("", image)]

    if block.bpp == 3:
        image = Image.new("RGBA", (width, pixel_h))
        pixels = image.load()
        row_bytes = x_words * 2
        for y in range(pixel_h):
            row = image_data[y * row_bytes:(y + 1) * row_bytes]
            for x in range(width):
                base = x * 3
                if base + 2 < len(row):
                    pixels[x, y] = (row[base], row[base + 1], row[base + 2], 255)
        return [("", image)]

    rows = palette_rows(data, block)
    if not rows:
        return []

    images: list[tuple[str, Any]] = []
    for palette_index, colors in enumerate(rows):
        image = Image.new("RGBA", (width, pixel_h))
        pixels = image.load()
        if block.bpp == 0:
            cursor = 0
            for y in range(pixel_h):
                for x_byte in range(x_words * 2):
                    value = image_data[cursor]
                    cursor += 1
                    x = x_byte * 2
                    pixels[x, y] = colors[value & 0x0F] if (value & 0x0F) < len(colors) else (255, 0, 255, 255)
                    if x + 1 < width:
                        idx = (value >> 4) & 0x0F
                        pixels[x + 1, y] = colors[idx] if idx < len(colors) else (255, 0, 255, 255)
        else:
            cursor = 0
            for y in range(pixel_h):
                for x in range(width):
                    idx = image_data[cursor]
                    cursor += 1
                    pixels[x, y] = colors[idx] if idx < len(colors) else (255, 0, 255, 255)
        suffix = "" if len(rows) == 1 else f"_pal{palette_index:02d}"
        images.append((suffix, image))
    return images


def write_bytes(path: Path, data: bytes) -> None:
    ensure_dir(path.parent)
    path.write_bytes(data)


def write_text(path: Path, text: str) -> None:
    ensure_dir(path.parent)
    path.write_text(text, encoding="utf-8", newline="\n")


def export_tim(
    *,
    source_rel: str,
    kind: str,
    index: int,
    data: bytes,
    block: TimBlock,
    raw_root: Path,
    png_root: Path,
    out_root: Path,
    logical_path: Path,
) -> TimExport:
    raw_name = append_extension(logical_path, ".tim")
    raw_path = raw_root / raw_name
    raw_payload = data[block.offset:block.end]
    write_bytes(raw_path, raw_payload)

    png_paths: list[str] = []
    for suffix, image in decode_tim_images(data, block):
        png_name = append_extension(logical_path.with_name(logical_path.name + suffix), ".png")
        png_path = png_root / png_name
        ensure_dir(png_path.parent)
        image.save(png_path)
        png_paths.append(rel_to(png_path, out_root))

    width, height = tim_pixel_size(block.bpp, block.image_rect[2], block.image_rect[3])
    return TimExport(
        source=source_rel,
        kind=kind,
        index=index,
        offset=block.offset,
        flags=block.flags,
        bpp=block.bpp,
        has_clut=block.has_clut,
        clut_rect=block.clut_rect,
        image_rect=block.image_rect,
        pixel_size=(width, height),
        raw_path=rel_to(raw_path, out_root),
        png_paths=png_paths,
    )


def parse_rsc_archive(path: Path, source_root: Path) -> tuple[str, list[dict[str, Any]]]:
    data = path.read_bytes()
    if len(data) < RSC_HEADER_SIZE:
        raise ValueError("RSC too small")

    package = c_string(data[:0x40])
    count = read_u32(data, 0x40)
    table_end = RSC_HEADER_SIZE + (count * RSC_ENTRY_SIZE)
    if count > 10000 or table_end > len(data):
        raise ValueError(f"Bad RSC entry count: {count}")

    entries: list[dict[str, Any]] = []
    for index in range(count):
        entry_offset = RSC_HEADER_SIZE + index * RSC_ENTRY_SIZE
        internal_path = c_string(data[entry_offset:entry_offset + RSC_ENTRY_NAME_SIZE])
        entry_id, size, payload_offset, flags = struct.unpack_from("<IIII", data, entry_offset + RSC_ENTRY_NAME_SIZE)
        if not internal_path:
            raise ValueError(f"RSC entry {index} has no name")
        if payload_offset + size > len(data):
            raise ValueError(f"RSC entry {index} exceeds archive size")
        entries.append(
            {
                "archive": rel_to(path, source_root),
                "package": package,
                "entry_id": entry_id,
                "internal_path": internal_path.replace("\\", "/"),
                "size": size,
                "offset": payload_offset,
                "flags": flags,
            }
        )
    return package, entries


def extract_rsc_archives(
    source_root: Path,
    out_root: Path,
    tim_raw_root: Path,
    tim_png_root: Path,
    tim_exports: list[TimExport],
) -> list[RscEntry]:
    rsc_root = out_root / "rsc_entries"
    extracted: list[RscEntry] = []

    for archive in sorted(source_root.rglob("*.RSC")):
        data = archive.read_bytes()
        package, entries = parse_rsc_archive(archive, source_root)
        archive_rel = rel_to(archive, source_root)
        archive_base = safe_relpath(str(Path(archive_rel).with_suffix("")))
        internal_totals = Counter(entry["internal_path"] for entry in entries)
        safe_totals = Counter(str(safe_relpath(entry["internal_path"])) for entry in entries)
        for entry_index, entry in enumerate(entries):
            internal_safe = safe_relpath(entry["internal_path"])
            safe_key = str(internal_safe)
            if internal_totals[entry["internal_path"]] > 1 or safe_totals[safe_key] > 1:
                internal_safe = add_name_suffix(internal_safe, f"entry{entry_index:04d}")
            output_path = rsc_root / archive_base / internal_safe
            payload = data[entry["offset"]:entry["offset"] + entry["size"]]
            write_bytes(output_path, payload)
            extracted.append(
                RscEntry(
                    archive=archive_rel,
                    package=package,
                    index=int(entry["entry_id"]),
                    internal_path=entry["internal_path"],
                    size=int(entry["size"]),
                    offset=int(entry["offset"]),
                    flags=int(entry["flags"]),
                    output_path=rel_to(output_path, out_root),
                )
            )

            if payload.startswith(TIM_MAGIC):
                block = parse_tim_at(payload, 0)
                if block is not None and block.end == len(payload):
                    logical = Path("rsc") / archive_base / internal_safe.with_suffix("")
                    tim_exports.append(
                        export_tim(
                            source_rel=f"{archive_rel}:{entry['internal_path']}",
                            kind="rsc",
                            index=entry_index,
                            data=payload,
                            block=block,
                            raw_root=tim_raw_root,
                            png_root=tim_png_root,
                            out_root=out_root,
                            logical_path=logical,
                        )
                    )
    return extracted


def extract_standalone_tim(
    source_root: Path,
    out_root: Path,
    tim_raw_root: Path,
    tim_png_root: Path,
    tim_exports: list[TimExport],
) -> None:
    for path in sorted(source_root.rglob("*.TIM")):
        data = path.read_bytes()
        block = parse_tim_at(data, 0)
        if block is None:
            continue
        rel = rel_to(path, source_root)
        logical = Path("standalone") / safe_relpath(str(Path(rel).with_suffix("")))
        tim_exports.append(
            export_tim(
                source_rel=rel,
                kind="standalone",
                index=0,
                data=data,
                block=block,
                raw_root=tim_raw_root,
                png_root=tim_png_root,
                out_root=out_root,
                logical_path=logical,
            )
        )


def extract_taf_files(
    source_root: Path,
    out_root: Path,
    tim_raw_root: Path,
    tim_png_root: Path,
    tim_exports: list[TimExport],
) -> list[TafSummary]:
    tail_root = out_root / "taf_tail"
    summaries: list[TafSummary] = []

    for path in sorted(source_root.rglob("*.TAF")):
        data = path.read_bytes()
        rel = rel_to(path, source_root)
        blocks = parse_sequential_tim(data)
        last_end = blocks[-1].end if blocks else 0
        logical_base = Path("taf") / safe_relpath(str(Path(rel).with_suffix("")))

        for index, block in enumerate(blocks):
            logical = logical_base / f"tim_{index:04d}"
            tim_exports.append(
                export_tim(
                    source_rel=rel,
                    kind="taf",
                    index=index,
                    data=data,
                    block=block,
                    raw_root=tim_raw_root,
                    png_root=tim_png_root,
                    out_root=out_root,
                    logical_path=logical,
                )
            )

        tail_path: str | None = None
        tail_size = len(data) - last_end
        if tail_size > 0:
            tail_output = tail_root / safe_relpath(str(Path(rel).with_suffix(""))).with_suffix(".tail.bin")
            write_bytes(tail_output, data[last_end:])
            tail_path = rel_to(tail_output, out_root)

        summaries.append(
            TafSummary(
                source=rel,
                size=len(data),
                tim_count=len(blocks),
                tim_bytes=last_end,
                tail_offset=last_end if tail_size else None,
                tail_size=tail_size,
                tail_path=tail_path,
            )
        )
    return summaries


def extract_bsd_chunks(source_root: Path, out_root: Path) -> list[BsdSummary]:
    bsd_root = out_root / "bsd_chunks"
    summaries: list[BsdSummary] = []

    for path in sorted(source_root.rglob("*.BSD")):
        data = path.read_bytes()
        rel = rel_to(path, source_root)
        if len(data) < 8:
            continue
        count = read_u32(data, 0)
        table_end = 4 + count * 4
        if count > 4096 or table_end > len(data):
            summaries.append(BsdSummary(rel, len(data), int(count), table_end, None, 0, None, []))
            continue

        offsets = [read_u32(data, 4 + i * 4) for i in range(count)]
        valid_offsets = [value for value in offsets if 0 <= value <= len(data)]
        unique_offsets = sorted(set(valid_offsets))
        base = bsd_root / safe_relpath(str(Path(rel).with_suffix("")))
        chunk_paths: list[str] = []
        header_body_path: str | None = None

        first_offset = unique_offsets[0] if unique_offsets else None
        if first_offset is not None and first_offset > table_end:
            header_body = base / "header_body.bin"
            write_bytes(header_body, data[table_end:first_offset])
            header_body_path = rel_to(header_body, out_root)

        for index, start in enumerate(unique_offsets):
            end = unique_offsets[index + 1] if index + 1 < len(unique_offsets) else len(data)
            if end <= start:
                continue
            chunk_path = base / f"chunk_{index:03d}_{start:06X}_{end:06X}.bin"
            write_bytes(chunk_path, data[start:end])
            chunk_paths.append(rel_to(chunk_path, out_root))

        summaries.append(
            BsdSummary(
                source=rel,
                size=len(data),
                entry_count=int(count),
                table_end=table_end,
                first_offset=first_offset,
                unique_chunk_count=len(chunk_paths),
                header_body_path=header_body_path,
                chunk_paths=chunk_paths,
            )
        )
    return summaries


def extract_strings(data: bytes, min_len: int = 4) -> list[str]:
    strings = []
    for match in ASCII_RE.finditer(data):
        if len(match.group(0)) >= min_len:
            strings.append(match.group(0).decode("ascii", errors="replace"))
    return strings


def write_string_reports(source_root: Path, out_root: Path, rsc_entries: Iterable[RscEntry]) -> dict[str, Any]:
    strings_root = out_root / "strings"
    reports: dict[str, Any] = {"files": []}

    source_candidates = [
        path for path in source_root.rglob("*")
        if path.is_file()
        and path.suffix.lower() in STRING_EXTENSIONS
        and not is_disc_artifact(path, source_root)
    ]

    for path in sorted(source_candidates):
        rel = rel_to(path, source_root)
        strings = extract_strings(path.read_bytes())
        if not strings:
            continue
        output_path = strings_root / "source" / safe_relpath(rel).with_suffix(".txt")
        write_text(output_path, "\n".join(strings) + "\n")
        reports["files"].append({"source": rel, "string_count": len(strings), "output_path": rel_to(output_path, out_root)})

    rsc_root = out_root / "rsc_entries"
    for entry in rsc_entries:
        suffix = Path(entry.internal_path).suffix.lower()
        if suffix not in STRING_EXTENSIONS:
            continue
        payload_path = rsc_root / Path(entry.output_path).relative_to("rsc_entries")
        if not payload_path.exists():
            continue
        strings = extract_strings(payload_path.read_bytes())
        if not strings:
            continue
        output_path = strings_root / "rsc" / safe_relpath(entry.output_path).with_suffix(".txt")
        write_text(output_path, "\n".join(strings) + "\n")
        reports["files"].append(
            {
                "source": f"{entry.archive}:{entry.internal_path}",
                "string_count": len(strings),
                "output_path": rel_to(output_path, out_root),
            }
        )

    reports["file_count"] = len(reports["files"])
    reports["string_count"] = sum(item["string_count"] for item in reports["files"])
    return reports


def file_inventory(source_root: Path, include_disc_images: bool) -> list[dict[str, Any]]:
    inventory = []
    for path in sorted(source_root.rglob("*")):
        if not path.is_file():
            continue
        if not include_disc_images and is_disc_artifact(path, source_root):
            continue
        inventory.append(
            {
                "path": rel_to(path, source_root),
                "size": path.stat().st_size,
                "extension": path.suffix.upper() if path.suffix else "",
            }
        )
    return inventory


def movie_inventory(source_root: Path) -> list[dict[str, Any]]:
    movies = []
    for path in sorted(source_root.rglob("*.STR")):
        movies.append({"path": rel_to(path, source_root), "size": path.stat().st_size})
    return movies


def audio_inventory(source_root: Path, rsc_entries: Iterable[RscEntry]) -> list[dict[str, Any]]:
    audio = []
    for path in sorted(source_root.rglob("*.VB")):
        audio.append({"path": rel_to(path, source_root), "size": path.stat().st_size, "kind": "source_vb"})
    for entry in rsc_entries:
        suffix = Path(entry.internal_path).suffix.lower()
        if suffix in {".vb", ".vab", ".vh"}:
            audio.append(
                {
                    "path": f"{entry.archive}:{entry.internal_path}",
                    "size": entry.size,
                    "kind": f"rsc{suffix}",
                    "output_path": entry.output_path,
                }
            )
    return audio


def write_report(
    report_path: Path,
    source_root: Path,
    out_root: Path,
    manifest: dict[str, Any],
) -> None:
    file_counts = Counter(item["extension"] or "<none>" for item in manifest["source_files"])
    rsc_ext_counts = Counter(Path(item["internal_path"]).suffix.lower() or "<none>" for item in manifest["rsc_entries"])
    tim_counts = Counter(item["kind"] for item in manifest["tim_exports"])

    lines = [
        "# Medal of Honor PS1 extraction report",
        "",
        f"- Source: `{source_root}`",
        f"- Output: `{out_root}`",
        f"- Generated: {manifest['generated_at']}",
        f"- Pillow PNG export: {'enabled' if Image is not None else 'disabled'}",
        "",
        "## Source file inventory",
        "",
        f"- Files cataloged: {len(manifest['source_files'])}",
        f"- Bytes cataloged: {sum(item['size'] for item in manifest['source_files'])}",
        "",
    ]

    for ext, count in sorted(file_counts.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"- {ext}: {count}")

    lines.extend(
        [
            "",
            "## RSC archives",
            "",
            f"- Archives: {manifest['rsc_archive_count']}",
            f"- Extracted entries: {len(manifest['rsc_entries'])}",
            "",
        ]
    )
    for ext, count in sorted(rsc_ext_counts.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"- {ext}: {count}")

    lines.extend(
        [
            "",
            "## TIM images",
            "",
            f"- TIM chunks exported: {len(manifest['tim_exports'])}",
            f"- PNG files written: {len(set(path for item in manifest['tim_exports'] for path in item['png_paths']))}",
            "",
        ]
    )
    for kind, count in sorted(tim_counts.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"- {kind}: {count}")

    lines.extend(
        [
            "",
            "## TAF streams",
            "",
            f"- Files: {len(manifest['taf_summaries'])}",
            f"- TIM chunks inside TAF: {sum(item['tim_count'] for item in manifest['taf_summaries'])}",
            f"- Tail bytes carved: {sum(item['tail_size'] for item in manifest['taf_summaries'])}",
            "",
            "## BSD chunks",
            "",
            f"- Files: {len(manifest['bsd_summaries'])}",
            f"- Chunks carved: {sum(item['unique_chunk_count'] for item in manifest['bsd_summaries'])}",
            "",
            "## Movie and audio",
            "",
            f"- STR movie files: {len(manifest['movies'])}",
            f"- STR bytes: {sum(item['size'] for item in manifest['movies'])}",
            f"- VB/VAB audio items: {len(manifest['audio'])}",
            f"- VB/VAB bytes cataloged: {sum(item['size'] for item in manifest['audio'])}",
            "",
            "## Strings",
            "",
            f"- Files with strings: {manifest['strings']['file_count']}",
            f"- Extracted strings: {manifest['strings']['string_count']}",
            "",
            "## Saturn port notes",
            "",
            "- Use `rsc_entries` and `tim_png` as the first visual asset pool.",
            "- TAF files contain sequential TIM images followed by non-TIM payloads; tails are preserved in `taf_tail`.",
            "- BSD files expose monotonic offset tables; carved chunks are exploratory until the map/object format is decoded.",
            "- STR movies are cataloged as source video streams. Convert them later to Saturn CPK/FILM after choosing target resolution/bitrate.",
            "- VB/VAB data is cataloged raw. Audio conversion needs the matching PS1 sound-bank semantics before Saturn PCM/ADPCM packing.",
        ]
    )
    write_text(report_path, "\n".join(lines) + "\n")


def run(args: argparse.Namespace) -> int:
    project_root = project_root_from_script()
    source_root = Path(args.source).resolve() if args.source else default_source_dir(project_root).resolve()
    out_root = Path(args.out).resolve() if args.out else (project_root / "artifacts" / "ps1_extract").resolve()

    if not source_root.exists():
        raise FileNotFoundError(f"Source directory not found: {source_root}")

    if args.clean:
        clean_dir(out_root)
    else:
        ensure_dir(out_root)

    reports_root = out_root / "reports"
    tim_raw_root = out_root / "tim_raw"
    tim_png_root = out_root / "tim_png"
    ensure_dir(reports_root)
    ensure_dir(tim_raw_root)
    ensure_dir(tim_png_root)

    tim_exports: list[TimExport] = []

    source_files = file_inventory(source_root, args.include_disc_image)
    extract_standalone_tim(source_root, out_root, tim_raw_root, tim_png_root, tim_exports)
    rsc_entries = extract_rsc_archives(source_root, out_root, tim_raw_root, tim_png_root, tim_exports)
    taf_summaries = extract_taf_files(source_root, out_root, tim_raw_root, tim_png_root, tim_exports)
    bsd_summaries = extract_bsd_chunks(source_root, out_root)
    strings = write_string_reports(source_root, out_root, rsc_entries)
    movies = movie_inventory(source_root)
    audio = audio_inventory(source_root, rsc_entries)

    manifest: dict[str, Any] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_root": str(source_root),
        "output_root": str(out_root),
        "source_files": source_files,
        "rsc_archive_count": len(list(source_root.rglob("*.RSC"))),
        "rsc_entries": [asdict(entry) for entry in rsc_entries],
        "tim_exports": [asdict(item) for item in tim_exports],
        "taf_summaries": [asdict(item) for item in taf_summaries],
        "bsd_summaries": [asdict(item) for item in bsd_summaries],
        "movies": movies,
        "audio": audio,
        "strings": strings,
    }

    manifest_path = reports_root / "moh_ps1_extraction_manifest.json"
    write_text(manifest_path, json.dumps(manifest, indent=2, ensure_ascii=False))
    report_path = reports_root / "moh_ps1_extraction_report.md"
    write_report(report_path, source_root, out_root, manifest)

    print(f"Source: {source_root}")
    print(f"Output: {out_root}")
    print(f"RSC entries: {len(rsc_entries)}")
    print(f"TIM chunks: {len(tim_exports)}")
    print(f"TAF files: {len(taf_summaries)}")
    print(f"BSD files: {len(bsd_summaries)}")
    print(f"STR movies: {len(movies)}")
    print(f"Audio items: {len(audio)}")
    print(f"Report: {report_path}")
    print(f"Manifest: {manifest_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract Medal of Honor PS1 assets for the Saturn port workspace.")
    parser.add_argument("--source", type=str, default=None, help="Extracted PS1 disc filesystem directory.")
    parser.add_argument("--out", type=str, default=None, help="Output directory. Defaults to artifacts/ps1_extract.")
    parser.add_argument("--clean", action="store_true", help="Delete the output directory before extraction.")
    parser.add_argument(
        "--include-disc-image",
        action="store_true",
        help="Include top-level .bin/.cue/.jpg/.rar disc dump files in the source manifest.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
