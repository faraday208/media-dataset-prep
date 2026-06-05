"""Paylaşılan saf yardımcılar: safe-UI, rapor/manifest yolları, dataset tarama, görsel metrik etiketleri."""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Optional
import json
import os
import time

from nicegui import ui
import media_organizer


MEDIA_EXTENSIONS = media_organizer.MEDIA_EXTENSIONS

from webui.state import STATE


def _safe_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except RuntimeError:
        return None


def _safe_set_value(element, value):
    return _safe_call(element.set_value, value)


def _safe_set_text(element, text):
    return _safe_call(element.set_text, text)


def _safe_set_visible(element, visible: bool):
    try:
        element.visible = visible
    except RuntimeError:
        pass


def _safe_enable(element):
    return _safe_call(element.enable)


def _safe_disable(element):
    return _safe_call(element.disable)


def _safe_notify(message: str, *, type: str = "info", timeout: int = 5000):
    try:
        ui.notify(message, type=type, timeout=timeout)
    except RuntimeError:
        pass


def _resolve_dataset_relative(value: Optional[str]) -> Optional[str]:
    """Kullanıcı invalid_dir / rejected-dir gibi alanlara relative path girerse
    Python'ın cwd'sini (media-dataset-prep) değil, **dataset_path**'i baz al.

    - None / boş string  → None
    - Absolute path      → olduğu gibi (str)
    - Relative path      → STATE.dataset_path ile birleştir, resolve et
    - dataset_path yoksa → cwd-resolve fallback (eski davranış)
    """
    if not value:
        return None
    v = value.strip()
    if not v:
        return None
    p = Path(v)
    if p.is_absolute():
        return str(p)
    if STATE.dataset_path:
        return str((Path(STATE.dataset_path) / p).resolve())
    return str(p.resolve())


def _report_dir_for(base: Optional[str]) -> str:
    """Tüm stage raporları PROJE KÖKÜNÜN içindeki ortak 'report/' klasöründe:
    <base_path>/report. base = proje kökü (STATE.base_path); çağıranlar aktif
    dataset_path veya output_dir DEĞİL, base_path verir — böylece stage organized/
    resized üzerinde çalışsa bile rapor tek yerde (proje kökü/report) birikir ve
    _find_manifest hepsini bulur. Recursive scan report'u atlar (collect_images
    _EXCLUDED_SCAN_DIRS), içeride güvenli — dataset self-contained (reject ile
    tutarlı)."""
    root = Path(base) if base else Path(STATE.base_path or ".")
    rdir = root.resolve() / "report"
    try:
        rdir.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return str(rdir)


def _report_path(filename: str, base: Optional[str]) -> str:
    """report/<filename> yolu. Yazımdan ÖNCE, varsa eski raporu report/_archive/'e
    mtime timestamp'iyle taşır (A: overwrite yerine history korunur). Canonical isim
    sabit kalır (undo + 03→07 kuplajı bozulmaz)."""
    rdir = Path(_report_dir_for(base))
    dest = rdir / filename
    if dest.exists():
        try:
            adir = rdir / "_archive"
            adir.mkdir(parents=True, exist_ok=True)
            ts = time.strftime("%Y%m%d-%H%M%S", time.localtime(dest.stat().st_mtime))
            archived = adir / f"{dest.stem}_{ts}{dest.suffix}"
            n = 1
            while archived.exists():
                archived = adir / f"{dest.stem}_{ts}_{n}{dest.suffix}"
                n += 1
            dest.replace(archived)
        except OSError:
            pass
    return str(dest)


def _append_manifest_from_report(idx: int, report_path, output_dir=None, params=None) -> None:
    """B: yazılmış raporu okuyup report/_manifest.json'a append-only lineage kaydı
    ekler (dataset 'üretim reçetesi' — A/B yöntem kıyaslaması için provenance).
    Stage'e özel değişken gerektirmez; rapor zaten tool/summary/config taşır.
    Hata pipeline'ı asla bozmaz."""
    try:
        rp = Path(report_path)
        try:
            info = json.loads(rp.read_text(encoding="utf-8"))
            if not isinstance(info, dict):
                info = {}
        except (OSError, ValueError):
            info = {}
        mpath = rp.parent / "_manifest.json"
        data = {"version": 1, "runs": []}
        if mpath.exists():
            try:
                loaded = json.loads(mpath.read_text(encoding="utf-8"))
                if isinstance(loaded, dict) and isinstance(loaded.get("runs"), list):
                    data = loaded
            except (OSError, ValueError):
                pass
        data["runs"].append({
            "idx": idx,
            "stage": info.get("tool", rp.stem),
            "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
            "report": rp.name,
            "output_dir": str(output_dir) if output_dir else None,
            "params": params,
            "summary": info.get("summary"),
            "config": info.get("config"),
            "source_root": info.get("source_root"),
        })
        mpath.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except Exception:  # noqa: BLE001
        pass


def _reject_dir_for(stage: str) -> str:
    """Reject klasörü PROJE KÖKÜNÜN içinde: <base_path>/_rejected/<stage>.
    base_path = kullanıcının seçtiği değişmez kök (Pics); dataset_path DEĞİL —
    o aktif iş klasörüdür (örn. organized) ve stage'den stage'e değişir. Reject
    hep proje kökünde toplanır. Recursive scan _rejected'ı atlar (collect_images
    _EXCLUDED_SCAN_DIRS), içeride güvenli — dataset self-contained."""
    root = Path(STATE.base_path) if STATE.base_path else Path(".")
    return str(root.resolve() / "_rejected" / stage)


def _find_manifest(path: Optional[str]):
    """Verilen yolda VEYA bir üstünde report/_manifest.json ara (working folder ya da
    proje kökü verilmiş olabilir)."""
    if not path:
        return None
    p = Path(path)
    for cand in (p / "report" / "_manifest.json",
                 p.parent / "report" / "_manifest.json"):
        try:
            if cand.is_file():
                return cand
        except OSError:
            pass
    return None


def _load_project_memory(path: Optional[str]) -> Optional[dict]:
    """C: bir yol verilince report/_manifest.json'dan 'kaldığımız yer'i geri yükler:
    Overview ✓ işaretlerini (last_report_paths) restore eder + özet döndürür. Aktif
    klasörü/akışı OTOMATİK DEĞİŞTİRMEZ (manuel akış). None → hafıza yok."""
    mpath = _find_manifest(path)
    if not mpath:
        return None
    try:
        data = json.loads(mpath.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    runs = data.get("runs") if isinstance(data, dict) else None
    if not isinstance(runs, list) or not runs:
        return None
    rdir = mpath.parent
    done = set()
    active_folder = None
    for run in runs:
        if not isinstance(run, dict):
            continue
        idx = run.get("idx")
        rep = run.get("report")
        if isinstance(idx, int) and isinstance(rep, str):
            rp = rdir / rep
            try:
                if rp.is_file():
                    STATE.last_report_paths[idx] = str(rp)
                    done.add(idx)
            except OSError:
                pass
        out = run.get("output_dir")
        if out:
            active_folder = out
        prm = run.get("params")
        if isinstance(idx, int) and isinstance(prm, dict):
            STATE.last_stage_params[idx] = prm
    last = runs[-1] if isinstance(runs[-1], dict) else {}
    return {
        "runs": len(runs),
        "done": sorted(done),
        "active_folder": active_folder,
        "last_stage": last.get("stage"),
        "last_time": last.get("time"),
    }


def step_status(idx: int) -> str:
    """Bir step için durum sembolü döndür: ✓ done / ○ pending / ⚠ error."""
    if idx in STATE.last_report_paths and Path(STATE.last_report_paths[idx]).exists():
        return "✓"
    return "○"


def scan_dataset_stats(path: str) -> dict:
    """Bir dataset dizinini tara — toplam dosya, tip dağılımı, total boyut."""
    if not path or not Path(path).is_dir():
        return {"total": 0, "by_ext": {}, "size_bytes": 0, "subdirs": 0}

    by_ext: Counter[str] = Counter()
    total_size = 0
    subdirs = 0
    total = 0

    for entry in Path(path).rglob('*'):
        if entry.is_file():
            ext = entry.suffix.lower()
            if ext in MEDIA_EXTENSIONS:
                by_ext[ext] += 1
                total += 1
                try:
                    total_size += entry.stat().st_size
                except OSError:
                    pass
        elif entry.is_dir() and entry != Path(path):
            subdirs += 1

    return {
        "total": total,
        "by_ext": dict(by_ext.most_common()),
        "size_bytes": total_size,
        "subdirs": subdirs,
    }


def humanize_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def _list_subdirs(path: str) -> list[str]:
    """Bir dizinin alt klasörlerini sıralı döndür. Hidden ve hata olanları atla."""
    try:
        entries = []
        for entry in sorted(os.listdir(path)):
            if entry.startswith('.'):
                continue
            full = os.path.join(path, entry)
            if os.path.isdir(full):
                entries.append(entry)
        return entries
    except (PermissionError, FileNotFoundError, NotADirectoryError):
        return []


def _path_to_url(path: str) -> str:
    """Lokal dosya path'ini UI'nın static mount'una göre URL'e çevir.
    /fs prefix'i main()'de mount edildi."""
    p = Path(path).resolve()
    return f"/fs{p}"


def _aspect_label(width: int, height: int) -> str:
    """Aspect ratio etiketi — yaygın oranlara match (16:9, 4:3, 3:4, 1:1...)
    veya decimal fallback (örn. 1.42).

    Aynı grupta farklı aspect'ler varsa kullanıcı görsel olarak crop/pad/
    upscale şüphesi yapabilir."""
    if not (width and height):
        return ""
    ratio = width / height
    presets = [
        ((16, 9), "16:9"),
        ((9, 16), "9:16"),
        ((4, 3), "4:3"),
        ((3, 4), "3:4"),
        ((3, 2), "3:2"),
        ((2, 3), "2:3"),
        ((1, 1), "1:1"),
        ((5, 4), "5:4"),
        ((4, 5), "4:5"),
        ((21, 9), "21:9"),
        ((9, 21), "9:21"),
        ((2, 1), "2:1"),
        ((1, 2), "1:2"),
    ]
    for (a, b), label in presets:
        target = a / b
        if abs(ratio - target) / target < 0.02:  # %2 tolerans
            return label
    return f"{ratio:.2f}:1"


def _bpp_label(width: int, height: int, size_bytes: int) -> tuple[str, str] | None:
    """BPP (bytes per pixel) etiketi + Tailwind renk class — AI training context.

    Eşikler **AI/VAE encoder** için (göz değil): JPG q40-60 (0.05-0.5 aralığı)
    gözle temiz ama block-artifact'leri model'e training noise olarak gözükür.

    - < 0.05 → red    (DİSKALİFİYE — yıkıcı, q<10)
    - < 0.5  → yellow (suboptimal — JPG q70 altı, AI için ideal değil)
    - ≥ 0.5  → green  (AI training-ready — JPG q90+ / WebP q90+ / PNG)

    Eşikler core/actions.py BEST stratejisiyle aynı (DISQUALIFY_BPP=0.05,
    FULL_SCORE_BPP=0.5).
    """
    if not (width and height) or size_bytes <= 0:
        return None
    bpp = size_bytes / (width * height)
    if bpp < 0.05:
        color = "text-red-600"
        suffix = " ⚠"
    elif bpp < 0.5:
        color = "text-yellow-600"
        suffix = ""
    else:
        color = "text-green-600"
        suffix = ""
    return f"BPP {bpp:.3f}{suffix}", color
