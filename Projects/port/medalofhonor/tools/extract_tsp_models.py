#!/usr/bin/env python3
"""Extract Medal of Honor PS1 TSP stage-cell geometry to Wavefront OBJ.

The TSP files in DATA/MSN*/LVL*/TSP0 are stage/cell resources. The observed
layout starts with a 0x40-byte table:

- u32[0]  = 0x00020001 signature.
- u32[3]  = triangle count.
- u32[4]  = triangle table offset, 16 bytes per triangle.
- u32[5]  = vertex count.
- u32[6]  = vertex table offset, 8 bytes per vertex.
- u32[8]  = vertex color table offset.
- u32[9]  = vertex color count.

This extractor writes one OBJ per TSP. Invalid/sentinel triangle records are
skipped and documented in the manifest.
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


TSP_SIGNATURE = 0x00020001
TSP_HEADER_U32_COUNT = 16
TSP_HEADER_SIZE = TSP_HEADER_U32_COUNT * 4
TSP_VERTEX_STRIDE = 8
TSP_TRIANGLE_STRIDE = 16


@dataclass
class TspHeader:
    signature: int
    node_count: int
    node_offset: int
    triangle_count: int
    triangle_offset: int
    vertex_count: int
    vertex_offset: int
    unknown_07: int
    color_offset: int
    color_count: int
    color_offset_2: int
    unknown_11: int
    special_offset: int
    special_count: int
    special_offset_2: int
    trailing_offset: int


@dataclass
class TspTriangle:
    index: int
    file_offset: int
    vertex_indices: tuple[int, int, int]
    uvs: tuple[tuple[int, int], tuple[int, int], tuple[int, int]]
    material_word: int
    flags_word: int


@dataclass
class TspExport:
    source_path: str
    obj_path: str
    mtl_path: str
    csv_path: str
    vertex_count: int
    triangle_count: int
    skipped_triangle_count: int
    bounds: list[list[float]]
    header: dict[str, Any]


def project_root_from_script() -> Path:
    return Path(__file__).resolve().parents[1]


def default_source_dir(project_root: Path) -> Path:
    return project_root.parent / "[PS1] Medal of Honor (PT-BR) [Dublado e Traduzido]" / "DATA"


def default_output_dir(project_root: Path) -> Path:
    return project_root / "artifacts" / "ps1_extract" / "models" / "tsp_obj"


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


def read_header(data: bytes) -> TspHeader:
    if len(data) < TSP_HEADER_SIZE:
        raise ValueError("TSP file is smaller than the fixed header")
    values = struct.unpack_from("<" + "I" * TSP_HEADER_U32_COUNT, data, 0)
    header = TspHeader(*values)
    if header.signature != TSP_SIGNATURE:
        raise ValueError(f"Unexpected TSP signature 0x{header.signature:08X}")
    if header.triangle_offset + header.triangle_count * TSP_TRIANGLE_STRIDE > len(data):
        raise ValueError("Triangle table exceeds TSP file size")
    if header.vertex_offset + header.vertex_count * TSP_VERTEX_STRIDE > len(data):
        raise ValueError("Vertex table exceeds TSP file size")
    if header.color_count and header.color_offset + header.color_count * 4 > len(data):
        raise ValueError("Color table exceeds TSP file size")
    return header


def decode_vertices(data: bytes, header: TspHeader, scale: float) -> list[tuple[float, float, float]]:
    vertices = []
    for index in range(header.vertex_count):
        x, y, z, _tag = struct.unpack_from("<hhhh", data, header.vertex_offset + index * TSP_VERTEX_STRIDE)
        vertices.append((x * scale, -y * scale, z * scale))
    return vertices


def decode_vertex_colors(data: bytes, header: TspHeader) -> list[tuple[int, int, int, int]]:
    colors = []
    for index in range(header.color_count):
        r, g, b, a = struct.unpack_from("BBBB", data, header.color_offset + index * 4)
        colors.append((r, g, b, a))
    return colors


def decode_triangles(data: bytes, header: TspHeader) -> tuple[list[TspTriangle], list[dict[str, Any]]]:
    triangles: list[TspTriangle] = []
    skipped: list[dict[str, Any]] = []
    for index in range(header.triangle_count):
        offset = header.triangle_offset + index * TSP_TRIANGLE_STRIDE
        v0, v1, v2 = struct.unpack_from("<HHH", data, offset)
        uv_raw = data[offset + 6:offset + 12]
        material_word, flags_word = struct.unpack_from("<HH", data, offset + 12)
        vertices = (v0, v1, v2)
        if any(value >= header.vertex_count for value in vertices):
            skipped.append(
                {
                    "index": index,
                    "file_offset": offset,
                    "vertex_indices": vertices,
                    "reason": "vertex_index_out_of_range",
                }
            )
            continue
        if len(set(vertices)) < 3:
            skipped.append(
                {
                    "index": index,
                    "file_offset": offset,
                    "vertex_indices": vertices,
                    "reason": "degenerate_triangle",
                }
            )
            continue
        triangles.append(
            TspTriangle(
                index=index,
                file_offset=offset,
                vertex_indices=vertices,
                uvs=((uv_raw[0], uv_raw[1]), (uv_raw[2], uv_raw[3]), (uv_raw[4], uv_raw[5])),
                material_word=material_word,
                flags_word=flags_word,
            )
        )
    return triangles, skipped


def bounds_for(vertices: list[tuple[float, float, float]]) -> list[list[float]]:
    if not vertices:
        return [[0.0, 0.0], [0.0, 0.0], [0.0, 0.0]]
    return [[min(v[axis] for v in vertices), max(v[axis] for v in vertices)] for axis in range(3)]


def triangle_normal(
    a: tuple[float, float, float],
    b: tuple[float, float, float],
    c: tuple[float, float, float],
) -> tuple[float, float, float]:
    ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
    nx = uy * vz - uz * vy
    ny = uz * vx - ux * vz
    nz = ux * vy - uy * vx
    length = math.sqrt(nx * nx + ny * ny + nz * nz)
    if length < 0.000001:
        return (0.0, 1.0, 0.0)
    return (nx / length, ny / length, nz / length)


def write_obj(
    obj_path: Path,
    mtl_path: Path,
    source_rel: str,
    vertices: list[tuple[float, float, float]],
    triangles: list[TspTriangle],
    reverse_winding: bool,
) -> None:
    ensure_dir(obj_path.parent)
    with obj_path.open("w", encoding="utf-8", newline="\n") as out:
        out.write(f"# Extracted from {source_rel}\n")
        out.write(f"mtllib {mtl_path.name}\n")
        out.write("o tsp_cell\n")
        for x, y, z in vertices:
            out.write(f"v {x:.6f} {y:.6f} {z:.6f}\n")

        for triangle in triangles:
            for u, v in triangle.uvs:
                out.write(f"vt {u / 255.0:.6f} {1.0 - (v / 255.0):.6f}\n")

        for triangle in triangles:
            a, b, c = [vertices[index] for index in triangle.vertex_indices]
            nx, ny, nz = triangle_normal(a, b, c)
            out.write(f"vn {nx:.6f} {ny:.6f} {nz:.6f}\n")

        out.write("usemtl tsp_default\n")
        for triangle_index, triangle in enumerate(triangles):
            order = (0, 2, 1) if reverse_winding else (0, 1, 2)
            parts = []
            for local_index in order:
                vi = triangle.vertex_indices[local_index] + 1
                vt = triangle_index * 3 + local_index + 1
                vn = triangle_index + 1
                parts.append(f"{vi}/{vt}/{vn}")
            out.write("f " + " ".join(parts) + "\n")

    with mtl_path.open("w", encoding="utf-8", newline="\n") as out:
        out.write("newmtl tsp_default\n")
        out.write("Kd 0.70 0.70 0.70\n")
        out.write("Ka 0.08 0.08 0.08\n")
        out.write("Ks 0.00 0.00 0.00\n")


def write_triangle_csv(csv_path: Path, triangles: list[TspTriangle]) -> None:
    ensure_dir(csv_path.parent)
    with csv_path.open("w", encoding="utf-8", newline="") as out:
        writer = csv.writer(out)
        writer.writerow(["index", "file_offset", "v0", "v1", "v2", "u0", "v0_uv", "u1", "v1_uv", "u2", "v2_uv", "material_word", "flags_word"])
        for triangle in triangles:
            writer.writerow(
                [
                    triangle.index,
                    f"0x{triangle.file_offset:X}",
                    *triangle.vertex_indices,
                    triangle.uvs[0][0],
                    triangle.uvs[0][1],
                    triangle.uvs[1][0],
                    triangle.uvs[1][1],
                    triangle.uvs[2][0],
                    triangle.uvs[2][1],
                    f"0x{triangle.material_word:04X}",
                    f"0x{triangle.flags_word:04X}",
                ]
            )


def export_tsp(path: Path, source_root: Path, out_root: Path, scale: float, reverse_winding: bool) -> TspExport:
    data = path.read_bytes()
    header = read_header(data)
    vertices = decode_vertices(data, header, scale)
    triangles, skipped = decode_triangles(data, header)
    _colors = decode_vertex_colors(data, header)

    source_rel = rel_to(path, source_root)
    model_rel = safe_relpath(Path(source_rel).with_suffix(""))
    obj_path = out_root / model_rel.with_suffix(".obj")
    mtl_path = out_root / model_rel.with_suffix(".mtl")
    csv_path = out_root / model_rel.with_suffix(".triangles.csv")

    write_obj(obj_path, mtl_path, source_rel, vertices, triangles, reverse_winding)
    write_triangle_csv(csv_path, triangles)

    return TspExport(
        source_path=source_rel,
        obj_path=rel_to(obj_path, out_root),
        mtl_path=rel_to(mtl_path, out_root),
        csv_path=rel_to(csv_path, out_root),
        vertex_count=len(vertices),
        triangle_count=len(triangles),
        skipped_triangle_count=len(skipped),
        bounds=bounds_for(vertices),
        header={**asdict(header), "skipped_triangles": skipped[:64]},
    )


def write_report(path: Path, manifest: dict[str, Any]) -> None:
    lines = [
        "# Medal of Honor PS1 TSP geometry extraction report",
        "",
        f"- Generated: {manifest['generated_at']}",
        f"- Source: `{manifest['source_root']}`",
        f"- Output: `{manifest['output_root']}`",
        f"- TSP files exported: {len(manifest['models'])}",
        f"- Vertices: {sum(item['vertex_count'] for item in manifest['models'])}",
        f"- Triangles exported: {sum(item['triangle_count'] for item in manifest['models'])}",
        f"- Triangles skipped: {sum(item['skipped_triangle_count'] for item in manifest['models'])}",
        "",
        "## Largest Cells",
        "",
    ]
    for item in sorted(manifest["models"], key=lambda model: model["triangle_count"], reverse=True)[:24]:
        lines.append(
            f"- `{item['source_path']}` -> `{item['obj_path']}` "
            f"({item['vertex_count']} vertices, {item['triangle_count']} triangles, "
            f"{item['skipped_triangle_count']} skipped)"
        )
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- Each OBJ is one TSP stage cell from `DATA/MSN*/LVL*/TSP0`.",
            "- TSP texture/material words are preserved in triangle CSV sidecars.",
            "- Some triangle records contain out-of-range sentinel indices; those are skipped and listed in the manifest.",
        ]
    )
    ensure_dir(path.parent)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def run(args: argparse.Namespace) -> int:
    project_root = project_root_from_script()
    source_root = Path(args.source).resolve() if args.source else default_source_dir(project_root).resolve()
    out_root = Path(args.out).resolve() if args.out else default_output_dir(project_root).resolve()

    if not source_root.exists():
        raise FileNotFoundError(f"TSP source directory not found: {source_root}")

    if args.clean:
        clean_dir(out_root)
    else:
        ensure_dir(out_root)

    exports = []
    errors = []
    for path in sorted(source_root.rglob("*.TSP")):
        try:
            exports.append(export_tsp(path, source_root, out_root, args.scale, args.reverse_winding))
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
    manifest_path = reports_root / "moh_ps1_tsp_model_manifest.json"
    report_path = reports_root / "moh_ps1_tsp_model_report.md"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8", newline="\n")
    write_report(report_path, manifest)

    print(f"Source: {source_root}")
    print(f"Output: {out_root}")
    print(f"TSP files exported: {len(exports)}")
    print(f"Errors: {len(errors)}")
    print(f"Triangles exported: {sum(item.triangle_count for item in exports)}")
    print(f"Triangles skipped: {sum(item.skipped_triangle_count for item in exports)}")
    print(f"Report: {report_path}")
    print(f"Manifest: {manifest_path}")
    return 0 if not errors else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract Medal of Honor PS1 TSP stage-cell geometry to OBJ.")
    parser.add_argument("--source", type=str, default=None, help="Directory containing DATA/MSN*/LVL*/TSP0/*.TSP files.")
    parser.add_argument("--out", type=str, default=None, help="Output directory for OBJ/MTL/CSV files.")
    parser.add_argument("--clean", action="store_true", help="Delete model output before extraction.")
    parser.add_argument("--scale", type=float, default=1.0 / 256.0, help="Scale applied to s16 vertex coordinates.")
    parser.add_argument("--reverse-winding", action="store_true", help="Reverse exported triangle winding.")
    return parser


def main() -> int:
    return run(build_parser().parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
