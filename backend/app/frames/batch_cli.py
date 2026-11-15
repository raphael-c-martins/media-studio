"""CLI em lote do Media Studio para preparar carrosséis (1.png, 2.png, 3.mp4...) com segurança."""
import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.downloads.storage import StorageError, resolve_download_folder, safe_filename, unique_path
from app.frames import engine, image_engine

IMAGE_EXT_MAP = {"png": "png", "jpeg": "jpg", "webp": "webp"}
VIDEO_COPY_EXTENSIONS = {".mp4", ".mov", ".m4v"}


def _resolve_target_dir(raw_dir: str) -> Path:
    """Valida que a pasta de destino não é raiz nem pasta protegida do sistema."""
    try:
        return resolve_download_folder(raw_dir)
    except StorageError as exc:
        raise ValueError(str(exc)) from exc


def _resolve_source_path(raw_source: str, base_dir: Path) -> Path:
    candidate = Path(raw_source)
    if not candidate.is_absolute():
        candidate = base_dir / candidate
    resolved = candidate.resolve()
    if not resolved.is_file():
        raise ValueError(f"Arquivo de origem não encontrado: {resolved.name}")
    return resolved


def _next_output_path(out_dir: Path, stem: str, ext: str, overwrite: bool) -> Path:
    clean_stem = safe_filename(stem, fallback="item")
    clean_ext = ext.lstrip(".").lower()
    if overwrite:
        return out_dir / f"{clean_stem}.{clean_ext}"
    return unique_path(out_dir, clean_stem, clean_ext)


def _infer_kind(source: Path, item: Dict[str, Any]) -> str:
    explicit = item.get("kind")
    if explicit in ("image", "video_frame", "video_copy"):
        return str(explicit)
    suffix = source.suffix.lower()
    if suffix in image_engine.STATIC_IMAGE_EXTENSIONS or suffix in image_engine.RAW_IMAGE_EXTENSIONS:
        return "image"
    if "time" in item:
        return "video_frame"
    return "video_copy"


def _parse_output_size(value: Any) -> Optional[Tuple[int, int]]:
    if not value:
        return None
    if isinstance(value, (list, tuple)) and len(value) == 2:
        w, h = int(value[0]), int(value[1])
        if w > 0 and h > 0:
            return w, h
    raise ValueError("output_size inválido: use [largura, altura] positivos.")


def _process_single_item(
    item: Dict[str, Any],
    *,
    base_dir: Path,
    out_dir: Path,
    defaults: Dict[str, Any],
    dry_run: bool,
    overwrite: bool,
) -> Dict[str, Any]:
    index_label = str(item.get("index", "item"))
    source = _resolve_source_path(str(item["source"]), base_dir)
    kind = _infer_kind(source, item)

    aspect_ratio = str(item.get("aspect_ratio", defaults["aspect_ratio"]))
    fmt = str(item.get("format", defaults["format"])).lower()
    focus_x = float(item.get("focus_x", defaults["focus_x"]))
    focus_y = float(item.get("focus_y", defaults["focus_y"]))
    zoom = float(item.get("zoom", defaults["zoom"]))
    fit_mode = str(item.get("fit_mode", defaults["fit_mode"]))
    standardize = bool(item.get("standardize", defaults["standardize"]))
    explicit_size = _parse_output_size(item.get("output_size") or defaults.get("output_size"))
    target_size = engine.resolve_output_size(aspect_ratio, standardize=standardize, output_size=explicit_size)

    if kind == "video_copy":
        suffix = source.suffix.lower()
        if suffix not in VIDEO_COPY_EXTENSIONS:
            raise ValueError(f"Extensão de vídeo não suportada para cópia: {suffix}")
        out_ext = "mp4" if suffix == ".mp4" else suffix.lstrip(".")
        target_path = _next_output_path(out_dir, index_label, out_ext, overwrite=overwrite)
        warnings = ["source_not_mp4"] if out_ext != "mp4" else []
        if not dry_run:
            out_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target_path)
        return {
            "index": index_label,
            "kind": kind,
            "source": str(source),
            "output": str(target_path),
            "status": "planned" if dry_run else "ok",
            "warnings": warnings,
        }

    if kind == "image":
        if fmt not in IMAGE_EXT_MAP:
            raise ValueError(f"Formato de saída inválido: {fmt}")
        out_ext = IMAGE_EXT_MAP[fmt]
        target_path = _next_output_path(out_dir, index_label, out_ext, overwrite=overwrite)
        content, _, info = image_engine.process_image(
            source,
            fmt=fmt,
            aspect_ratio=aspect_ratio,
            focus_x=focus_x,
            focus_y=focus_y,
            zoom=zoom,
            standardize=standardize,
            output_size=target_size,
            fit_mode=fit_mode,
        )
        if not dry_run:
            out_dir.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(content)
        return {
            "index": index_label,
            "kind": kind,
            "source": str(source),
            "output": str(target_path),
            "status": "planned" if dry_run else "ok",
            "src_width": info["width"],
            "src_height": info["height"],
            "out_width": info["out_width"],
            "out_height": info["out_height"],
            "orientation_applied": info["orientation_applied"],
            "color_profile": info["color_profile"],
            "warnings": info["warnings"],
        }

    # kind == "video_frame"
    if fmt not in IMAGE_EXT_MAP:
        raise ValueError(f"Formato de saída inválido: {fmt}")
    out_ext = IMAGE_EXT_MAP[fmt]
    seconds = float(item.get("time", 0.0))
    meta = engine.probe_video(str(source))
    geometry = engine.analyze_crop_geometry(
        meta["width"],
        meta["height"],
        aspect_ratio,
        focus_x=focus_x,
        focus_y=focus_y,
        zoom=zoom,
        output_size=target_size,
        fit_mode=fit_mode,
    )
    target_path = _next_output_path(out_dir, index_label, out_ext, overwrite=overwrite)
    if not dry_run:
        content, _ = engine.extract_frame(
            str(source),
            min(max(0.0, seconds), meta["duration"] or seconds),
            meta["rotation"],
            fmt,
            aspect_ratio,
            focus_x=focus_x,
            focus_y=focus_y,
            zoom=zoom,
            standardize=standardize,
            output_size=target_size,
            fit_mode=fit_mode,
        )
        out_dir.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(content)
    return {
        "index": index_label,
        "kind": kind,
        "source": str(source),
        "output": str(target_path),
        "status": "planned" if dry_run else "ok",
        "time": seconds,
        "src_width": meta["width"],
        "src_height": meta["height"],
        "out_width": geometry["out_width"],
        "out_height": geometry["out_height"],
        "warnings": geometry["warnings"],
    }


def run_batch(
    *,
    items: List[Dict[str, Any]],
    base_dir: Path,
    output_dir: Path,
    defaults: Dict[str, Any],
    dry_run: bool = False,
    overwrite: bool = False,
) -> Dict[str, Any]:
    """Executa ou simula (dry_run) o processamento em lote preservando originais intactos."""
    resolved_out = _resolve_target_dir(str(output_dir))
    results: List[Dict[str, Any]] = []
    warnings_count = 0
    errors_count = 0

    for pos, raw_item in enumerate(items, start=1):
        item = dict(raw_item)
        item.setdefault("index", pos)
        try:
            entry = _process_single_item(
                item,
                base_dir=base_dir,
                out_dir=resolved_out,
                defaults=defaults,
                dry_run=dry_run,
                overwrite=overwrite,
            )
            warnings_count += len(entry.get("warnings") or [])
        except Exception as exc:
            errors_count += 1
            entry = {
                "index": str(item["index"]),
                "source": str(item.get("source", "")),
                "status": "error",
                "error": str(exc),
                "warnings": [],
            }
        results.append(entry)

    return {
        "output_dir": str(resolved_out),
        "dry_run": dry_run,
        "total": len(items),
        "processed": len(items) - errors_count,
        "warnings_count": warnings_count,
        "errors_count": errors_count,
        "items": results,
    }


def _load_manifest_job(manifest_path: Path) -> Tuple[Path, Path, List[Dict[str, Any]], Dict[str, Any], bool, bool]:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    base_dir = Path(payload.get("post_dir") or manifest_path.parent).resolve()
    output_dir = Path(payload.get("output_dir") or payload.get("post_dir") or manifest_path.parent)
    defaults = {
        "aspect_ratio": payload.get("default_aspect_ratio", "4:5"),
        "format": payload.get("default_format", "png"),
        "focus_x": payload.get("default_focus_x", 0.5),
        "focus_y": payload.get("default_focus_y", 0.5),
        "zoom": payload.get("default_zoom", 1.0),
        "fit_mode": payload.get("default_fit_mode", "crop"),
        "standardize": payload.get("default_standardize", True),
        "output_size": payload.get("default_output_size"),
    }
    return (
        base_dir,
        output_dir,
        list(payload.get("items") or []),
        defaults,
        bool(payload.get("dry_run", False)),
        bool(payload.get("overwrite", False)),
    )


def _scan_input_dir(input_dir: Path) -> List[Dict[str, Any]]:
    allowed = image_engine.STATIC_IMAGE_EXTENSIONS | image_engine.RAW_IMAGE_EXTENSIONS
    files = sorted(p for p in input_dir.iterdir() if p.is_file() and p.suffix.lower() in allowed)
    return [{"index": idx, "source": str(path), "kind": "image"} for idx, path in enumerate(files, start=1)]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepara imagens e frames em lote para o Relíquias Itaboraí.")
    parser.add_argument("--manifest", type=Path, help="Arquivo JSON descrevendo a lista do carrossel e focos.")
    parser.add_argument("--input-dir", type=Path, help="Pasta com fotos originais para lote uniforme.")
    parser.add_argument("--output-dir", type=Path, help="Pasta de destino para gravar 1.png, 2.png...")
    parser.add_argument("--aspect-ratio", default="4:5", choices=("original", "4:5", "1:1", "9:16", "16:9"))
    parser.add_argument("--format", default="png", choices=("png", "jpeg", "webp"))
    parser.add_argument("--focus-x", type=float, default=0.5)
    parser.add_argument("--focus-y", type=float, default=0.5)
    parser.add_argument("--zoom", type=float, default=1.0)
    parser.add_argument("--fit-mode", default="crop", choices=("crop", "contain_blur"))
    parser.add_argument("--no-standardize", action="store_true", help="Mantém a resolução nativa do corte sem escalar.")
    parser.add_argument("--dry-run", action="store_true", help="Valida e calcula dimensões/alertas sem gravar.")
    parser.add_argument("--overwrite", action="store_true", help="Permite sobrescrever arquivos com o mesmo índice.")
    parser.add_argument("--strict", action="store_true", help="Sai com código 2 se houver avisos wide_crop/low_resolution.")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.manifest:
        manifest_path = args.manifest.resolve()
        if not manifest_path.is_file():
            print(json.dumps({"error": f"Manifesto não encontrado: {manifest_path}"}, ensure_ascii=False))
            return 1
        base_dir, out_dir, items, defaults, m_dry, m_over = _load_manifest_job(manifest_path)
        dry_run = args.dry_run or m_dry
        overwrite = args.overwrite or m_over
        if args.output_dir:
            out_dir = args.output_dir
    elif args.input_dir and args.output_dir:
        in_dir = args.input_dir.resolve()
        if not in_dir.is_dir():
            print(json.dumps({"error": f"Pasta de entrada não encontrada: {in_dir}"}, ensure_ascii=False))
            return 1
        base_dir = in_dir
        out_dir = args.output_dir
        items = _scan_input_dir(in_dir)
        defaults = {
            "aspect_ratio": args.aspect_ratio,
            "format": args.format,
            "focus_x": args.focus_x,
            "focus_y": args.focus_y,
            "zoom": args.zoom,
            "fit_mode": args.fit_mode,
            "standardize": not args.no_standardize,
            "output_size": None,
        }
        dry_run = args.dry_run
        overwrite = args.overwrite
    else:
        parser.error("Informe --manifest OU (--input-dir e --output-dir).")
        return 1

    try:
        report = run_batch(
            items=items,
            base_dir=base_dir,
            output_dir=out_dir,
            defaults=defaults,
            dry_run=dry_run,
            overwrite=overwrite,
        )
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 1

    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["errors_count"] > 0:
        return 1
    if args.strict and report["warnings_count"] > 0:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
