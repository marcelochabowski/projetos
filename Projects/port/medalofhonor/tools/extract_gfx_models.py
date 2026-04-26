#!/usr/bin/env python3
"""Extract Medal of Honor PS1 .GFX model resources to Wavefront OBJ.

This decodes the menu/model GFX container found inside RSC archives. The format
observed in this dump uses:

- 10 little-endian u32 header fields.
- A small u32 group/count table.
- s16 vertex records: x, y, z, tag.
- s16 normal records: x, y, z, tag.
- 36-byte triangle records beginning with type 0x0013.

The later bytes after the base triangle table appear to hold animation/morph or
render-support data. They are preserved by the manifest but not interpreted yet.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
import struct
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


GFX_HEADER_U32_COUNT = 10
GFX_HEADER_SIZE = GFX_HEADER_U32_COUNT * 4
GFX_VERTEX_STRIDE = 8
GFX_NORMAL_STRIDE = 8
GFX_TRIANGLE_STRIDE = 36
GFX_TRIANGLE_TYPE = 0x0013


@dataclass
class GfxHeader:
    vertex_count: int
    normal_count: int
    triangle_count: int
    unknown_03: int
    group_count: int
    unknown_05: int
    vertex_ptr: int
    normal_ptr: int
    pointer_08: int
    unknown_09: int
    group_table: list[int]
    vertex_offset: int
    normal_offset: int
    triangle_offset: int
    triangle_end: int
    trailing_size: int


@dataclass
class GfxTriangle:
    index: int
    file_offset: int
    vertex_indices: tuple[int, int, int]
    normal_indices: tuple[int, int, int]
    uvs: tuple[tuple[int, int], tuple[int, int], tuple[int, int]]
    colors: tuple[tuple[int, int, int, int], tuple[int, int, int, int], tuple[int, int, int, int]]
    gpu_word: int


@dataclass
class GfxModelExport:
    source_path: str
    obj_path: str
    mtl_path: str
    csv_path: str
    vertex_count: int
    normal_count: int
    triangle_count: int
    bounds: list[list[float]]
    header: dict[str, Any]


def project_root_from_script() -> Path:
    return Path(__file__).resolve().parents[1]


def default_source_dir(project_root: Path) -> Path:
    return project_root / "artifacts" / "ps1_extract" / "rsc_entries"


def default_output_dir(project_root: Path) -> Path:
    return project_root / "artifacts" / "ps1_extract" / "models" / "gfx_obj"


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


def safe_relpath(path: Path) -> Path:
    return Path(*[sanitize_part(part) for part in path.parts if part])


def read_header(data: bytes) -> GfxHeader:
    if len(data) < GFX_HEADER_SIZE:
        raise ValueError("GFX file is smaller than the fixed header")

    values = list(struct.unpack_from("<" + "I" * GFX_HEADER_U32_COUNT, data, 0))
    group_count = values[4]
    group_table_offset = GFX_HEADER_SIZE
    vertex_offset = group_table_offset + group_count * 4
    normal_offset = vertex_offset + values[0] * GFX_VERTEX_STRIDE
    triangle_offset = normal_offset + values[1] * GFX_NORMAL_STRIDE
    triangle_end = triangle_offset + values[2] * GFX_TRIANGLE_STRIDE

    if group_count > 4096:
        raise ValueError(f"Unreasonable GFX group count: {group_count}")
    if triangle_end > len(data):
        raise ValueError(
            f"GFX geometry tables exceed file size: triangle_end=0x{triangle_end:X}, size=0x{len(data):X}"
        )

    group_table = list(struct.unpack_from("<" + "I" * group_count, data, group_table_offset)) if group_count else []

    return GfxHeader(
        vertex_count=values[0],
        normal_count=values[1],
        triangle_count=values[2],
        unknown_03=values[3],
        group_count=values[4],
        unknown_05=values[5],
        vertex_ptr=values[6],
        normal_ptr=values[7],
        pointer_08=values[8],
        unknown_09=values[9],
        group_table=group_table,
        vertex_offset=vertex_offset,
        normal_offset=normal_offset,
        triangle_offset=triangle_offset,
        triangle_end=triangle_end,
        trailing_size=len(data) - triangle_end,
    )


def read_s16_record(data: bytes, offset: int) -> tuple[int, int, int, int]:
    return struct.unpack_from("<hhhh", data, offset)


def decode_vertices(data: bytes, header: GfxHeader, scale: float) -> list[tuple[float, float, float]]:
    vertices = []
    for index in range(header.vertex_count):
        x, y, z, _tag = read_s16_record(data, header.vertex_offset + index * GFX_VERTEX_STRIDE)
        vertices.append((x * scale, -y * scale, z * scale))
    return vertices


def decode_normals(data: bytes, header: GfxHeader) -> list[tuple[float, float, float]]:
    normals = []
    for index in range(header.normal_count):
        x, y, z, _tag = read_s16_record(data, header.normal_offset + index * GFX_NORMAL_STRIDE)
        nx = x / 4096.0
        ny = -y / 4096.0
        nz = z / 4096.0
        length = math.sqrt(nx * nx + ny * ny + nz * nz)
        if length > 0.000001:
            normals.append((nx / length, ny / length, nz / length))
        else:
            normals.append((0.0, 1.0, 0.0))
    return normals


def decode_triangles(data: bytes, header: GfxHeader) -> list[GfxTriangle]:
    triangles = []
    for index in range(header.triangle_count):
        offset = header.triangle_offset + index * GFX_TRIANGLE_STRIDE
        record_type = struct.unpack_from("<H", data, offset)[0]
        if record_type != GFX_TRIANGLE_TYPE:
            raise ValueError(f"Unexpected GFX triangle type 0x{record_type:04X} at 0x{offset:X}")

        v0, v1, v2 = struct.unpack_from("<HHH", data, offset + 2)
        n0, n1, n2 = struct.unpack_from("<HHH", data, offset + 8)
        uv_raw = data[offset + 14:offset + 20]
        colors_raw = data[offset + 20:offset + 32]
        gpu_word = struct.unpack_from("<I", data, offset + 32)[0]

        vertices = (v0, v1, v2)
        normals = (n0, n1, n2)
        if any(value >= header.vertex_count for value in vertices):
            raise ValueError(f"Triangle {index} has invalid vertex indices: {vertices}")
        if header.normal_count and any(value >= header.normal_count for value in normals):
            raise ValueError(f"Triangle {index} has invalid normal indices: {normals}")

        triangles.append(
            GfxTriangle(
                index=index,
                file_offset=offset,
                vertex_indices=vertices,
                normal_indices=normals,
                uvs=((uv_raw[0], uv_raw[1]), (uv_raw[2], uv_raw[3]), (uv_raw[4], uv_raw[5])),
                colors=(
                    tuple(colors_raw[0:4]),  # type: ignore[arg-type]
                    tuple(colors_raw[4:8]),  # type: ignore[arg-type]
                    tuple(colors_raw[8:12]),  # type: ignore[arg-type]
                ),
                gpu_word=gpu_word,
            )
        )
    return triangles


def bounds_for(vertices: list[tuple[float, float, float]]) -> list[list[float]]:
    if not vertices:
        return [[0.0, 0.0], [0.0, 0.0], [0.0, 0.0]]
    return [[min(v[axis] for v in vertices), max(v[axis] for v in vertices)] for axis in range(3)]


def write_obj(
    obj_path: Path,
    mtl_path: Path,
    source_rel: str,
    vertices: list[tuple[float, float, float]],
    normals: list[tuple[float, float, float]],
    triangles: list[GfxTriangle],
    reverse_winding: bool,
) -> None:
    ensure_dir(obj_path.parent)
    mtl_name = mtl_path.name
    with obj_path.open("w", encoding="utf-8", newline="\n") as out:
        out.write(f"# Extracted from {source_rel}\n")
        out.write(f"mtllib {mtl_name}\n")
        out.write("o gfx_model\n")
        for x, y, z in vertices:
            out.write(f"v {x:.6f} {y:.6f} {z:.6f}\n")
        for nx, ny, nz in normals:
            out.write(f"vn {nx:.6f} {ny:.6f} {nz:.6f}\n")
        for triangle in triangles:
            for u, v in triangle.uvs:
                out.write(f"vt {u / 255.0:.6f} {1.0 - (v / 255.0):.6f}\n")

        out.write("usemtl gfx_default\n")
        for triangle in triangles:
            order = (0, 2, 1) if reverse_winding else (0, 1, 2)
            parts = []
            for local_index in order:
                vi = triangle.vertex_indices[local_index] + 1
                vt = triangle.index * 3 + local_index + 1
                ni = triangle.normal_indices[local_index] + 1 if normals else 0
                if normals:
                    parts.append(f"{vi}/{vt}/{ni}")
                else:
                    parts.append(f"{vi}/{vt}")
            out.write("f " + " ".join(parts) + "\n")

    with mtl_path.open("w", encoding="utf-8", newline="\n") as out:
        out.write("newmtl gfx_default\n")
        out.write("Kd 0.80 0.80 0.80\n")
        out.write("Ka 0.10 0.10 0.10\n")
        out.write("Ks 0.00 0.00 0.00\n")


def write_triangle_csv(csv_path: Path, triangles: list[GfxTriangle]) -> None:
    ensure_dir(csv_path.parent)
    with csv_path.open("w", encoding="utf-8", newline="") as out:
        writer = csv.writer(out)
        writer.writerow(
            [
                "index",
                "file_offset",
                "v0",
                "v1",
                "v2",
                "n0",
                "n1",
                "n2",
                "u0",
                "v0_uv",
                "u1",
                "v1_uv",
                "u2",
                "v2_uv",
                "rgb0",
                "rgb1",
                "rgb2",
                "gpu_word",
            ]
        )
        for triangle in triangles:
            writer.writerow(
                [
                    triangle.index,
                    f"0x{triangle.file_offset:X}",
                    *triangle.vertex_indices,
                    *triangle.normal_indices,
                    triangle.uvs[0][0],
                    triangle.uvs[0][1],
                    triangle.uvs[1][0],
                    triangle.uvs[1][1],
                    triangle.uvs[2][0],
                    triangle.uvs[2][1],
                    " ".join(f"{value:02X}" for value in triangle.colors[0]),
                    " ".join(f"{value:02X}" for value in triangle.colors[1]),
                    " ".join(f"{value:02X}" for value in triangle.colors[2]),
                    f"0x{triangle.gpu_word:08X}",
                ]
            )


def export_gfx(path: Path, source_root: Path, out_root: Path, scale: float, reverse_winding: bool) -> GfxModelExport:
    data = path.read_bytes()
    header = read_header(data)
    vertices = decode_vertices(data, header, scale)
    normals = decode_normals(data, header)
    triangles = decode_triangles(data, header)

    source_rel = rel_to(path, source_root)
    model_rel = safe_relpath(Path(source_rel).with_suffix(""))
    obj_path = out_root / model_rel.with_suffix(".obj")
    mtl_path = out_root / model_rel.with_suffix(".mtl")
    csv_path = out_root / model_rel.with_suffix(".triangles.csv")

    write_obj(obj_path, mtl_path, source_rel, vertices, normals, triangles, reverse_winding)
    write_triangle_csv(csv_path, triangles)

    return GfxModelExport(
        source_path=source_rel,
        obj_path=rel_to(obj_path, out_root),
        mtl_path=rel_to(mtl_path, out_root),
        csv_path=rel_to(csv_path, out_root),
        vertex_count=len(vertices),
        normal_count=len(normals),
        triangle_count=len(triangles),
        bounds=bounds_for(vertices),
        header=asdict(header),
    )


def write_report(path: Path, manifest: dict[str, Any]) -> None:
    lines = [
        "# Medal of Honor PS1 GFX model extraction report",
        "",
        f"- Generated: {manifest['generated_at']}",
        f"- Source: `{manifest['source_root']}`",
        f"- Output: `{manifest['output_root']}`",
        f"- Models exported: {len(manifest['models'])}",
        f"- Vertices: {sum(model['vertex_count'] for model in manifest['models'])}",
        f"- Triangles: {sum(model['triangle_count'] for model in manifest['models'])}",
        "",
        "## Models",
        "",
    ]
    for model in manifest["models"]:
        lines.append(
            f"- `{model['source_path']}` -> `{model['obj_path']}` "
            f"({model['vertex_count']} vertices, {model['triangle_count']} triangles)"
        )
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- OBJ geometry uses the base vertex/normal/triangle tables from each `.gfx` file.",
            "- Texture pages and animation/morph bytes after the base triangle table are not decoded yet.",
            "- UVs are exported from triangle records as normalized OBJ texture coordinates for later texture matching.",
        ]
    )
    ensure_dir(path.parent)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def run(args: argparse.Namespace) -> int:
    project_root = project_root_from_script()
    source_root = Path(args.source).resolve() if args.source else default_source_dir(project_root).resolve()
    out_root = Path(args.out).resolve() if args.out else default_output_dir(project_root).resolve()

    if not source_root.exists():
        raise FileNotFoundError(f"GFX source directory not found: {source_root}")

    if args.clean:
        clean_dir(out_root)
    else:
        ensure_dir(out_root)

    exports = []
    errors = []
    for path in sorted(source_root.rglob("*.gfx")):
        try:
            exports.append(export_gfx(path, source_root, out_root, args.scale, args.reverse_winding))
        except Exception as exc:
            errors.append({"source_path": rel_to(path, source_root), "error": str(exc)})

    manifest = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_root": str(source_root),
        "output_root": str(out_root),
        "scale": args.scale,
        "reverse_winding": args.reverse_winding,
        "models": [asdict(item) for item in exports],
        "errors": errors,
    }

    reports_root = out_root / "reports"
    ensure_dir(reports_root)
    manifest_path = reports_root / "moh_ps1_gfx_model_manifest.json"
    report_path = reports_root / "moh_ps1_gfx_model_report.md"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8", newline="\n")
    write_report(report_path, manifest)

    print(f"Source: {source_root}")
    print(f"Output: {out_root}")
    print(f"Models exported: {len(exports)}")
    print(f"Errors: {len(errors)}")
    print(f"Report: {report_path}")
    print(f"Manifest: {manifest_path}")
    return 0 if not errors else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract Medal of Honor PS1 .GFX models to OBJ.")
    parser.add_argument("--source", type=str, default=None, help="Directory containing extracted .gfx files.")
    parser.add_argument("--out", type=str, default=None, help="Output directory for OBJ/MTL/CSV files.")
    parser.add_argument("--clean", action="store_true", help="Delete model output before extraction.")
    parser.add_argument("--scale", type=float, default=1.0 / 64.0, help="Scale applied to s16 vertex coordinates.")
    parser.add_argument("--reverse-winding", action="store_true", help="Reverse exported triangle winding.")
    return parser


def main() -> int:
    return run(build_parser().parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
