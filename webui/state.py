"""Pipeline state container + global STATE singleton + pipeline tanımı."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import json


@dataclass
class PipelineState:
    """
    In-memory pipeline state — UI session boyunca yaşar (v0.1: persistence yok).

    Tab'lar `on_change` ile refresh callback kaydeder; Validate veya başka
    state-altering aksiyon `notify_change()` çağırır → kayıtlı tüm
    callback'ler tetiklenir (Observer pattern).
    """
    base_path: str = ""                     # kullanıcının işaret ettiği kök; header bunu gösterir
    last_report_paths: dict[int, str] = field(default_factory=dict)
    last_stage_params: dict[int, dict] = field(default_factory=dict)
    available_outputs: dict[int, str] = field(default_factory=dict)
    _dismissed_outputs: set[int] = field(default_factory=set)
    _refresh_callbacks: list = field(default_factory=list)

    def _resolve_active(self) -> Optional[str]:
        """Manifest'ten aktif çalışma klasörünü (en son output_dir) çöz. SADECE
        base_path okur (dataset_path'e DOKUNMAZ → recursion yok). Cache yok —
        manifest küçük, erişim kullanıcı-olayı tetikli."""
        base = self.base_path
        if not base:
            return None
        mpath = None
        for cand in (Path(base) / "report" / "_manifest.json",
                     Path(base).parent / "report" / "_manifest.json"):
            try:
                if cand.is_file():
                    mpath = cand
                    break
            except OSError:
                pass
        if mpath is None:
            return None
        try:
            data = json.loads(mpath.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        runs = data.get("runs") if isinstance(data, dict) else None
        active = None
        if isinstance(runs, list):
            for run in runs:
                if isinstance(run, dict) and run.get("output_dir"):
                    active = run["output_dir"]
        try:
            if active and not Path(active).is_dir():
                active = None
        except OSError:
            active = None
        return active

    @property
    def dataset_path(self) -> str:
        """Tab'ların İŞLEDİĞİ aktif çalışma klasörü = manifest'in son output_dir'i,
        yoksa kök (base_path). Header değil — header base_path gösterir (switch'siz)."""
        return self._resolve_active() or self.base_path

    @dataset_path.setter
    def dataset_path(self, value) -> None:
        # Geriye dönük uyum: dataset_path'e atama = kökü ayarla.
        self.base_path = value or ""

    def is_valid_dataset(self) -> bool:
        return bool(self.base_path) and Path(self.base_path).is_dir()

    def on_change(self, callback) -> None:
        """Bir tab'ı state değişikliği bildirimine abone et."""
        self._refresh_callbacks.append(callback)

    def notify_change(self) -> None:
        """Tüm abone tab'ları yeniden render et."""
        for cb in list(self._refresh_callbacks):
            try:
                cb()
            except Exception as e:
                print(f"[STATE] refresh callback hatası: {e}")

    def reset_callbacks(self) -> None:
        """Yeni page mount edildiğinde eski callback'leri temizle."""
        self._refresh_callbacks = []

    def register_output(self, step_idx: int, output_dir: str) -> None:
        """Output üreten adım (Organize copy/move, Resize copy, Golden-set) execute
        sonrası çağırır. dataset_path değişmez; banner ile kullanıcıya 'switch'
        teklif edilir. Aynı dizine register edilirse no-op."""
        if not output_dir:
            return
        try:
            norm = str(Path(output_dir).resolve())
            cur = str(Path(self.dataset_path).resolve()) if self.dataset_path else ""
        except OSError:
            return
        if norm == cur:
            return
        self.available_outputs[step_idx] = norm
        self._dismissed_outputs.discard(step_idx)
        self.notify_change()

    def latest_output(self) -> Optional[tuple[int, str]]:
        """En yeni (en yüksek step idx) dismiss edilmemiş output'u döndür."""
        active = {k: v for k, v in self.available_outputs.items()
                  if k not in self._dismissed_outputs}
        if not active:
            return None
        idx = max(active)
        return idx, active[idx]

    def switch_to(self, output_dir: str) -> None:
        """Banner'daki Switch butonu çağırır — dataset_path'i değiştirir."""
        self.dataset_path = output_dir
        self.notify_change()

    def dismiss_output(self, step_idx: int) -> None:
        """Banner'daki Dismiss butonu çağırır — output saklı kalır ama banner'da
        gösterilmez (re-register'da otomatik geri gelir)."""
        self._dismissed_outputs.add(step_idx)
        self.notify_change()

    def clear_output(self, step_idx: int) -> None:
        """Undo başarılı olduğunda çağrılır — output artık geçersiz, banner'dan
        tamamen temizle."""
        self.available_outputs.pop(step_idx, None)
        self._dismissed_outputs.discard(step_idx)
        self.notify_change()


STATE = PipelineState()


PIPELINE_STEPS: list[tuple[int, str, str, bool]] = [
    (0, "Organize", "Dosya isimlerini düzenli numaralandır", True),
    (1, "Validate", "Format ve dosya bütünlüğü kontrolü", True),
    (2, "Duplicate", "Birebir + benzer kopya tespiti", True),
    (3, "Quality", "Blur, brightness, contrast, BPP metrikleri", True),
    (4, "Watermark", "YOLOv8 ile filigran tespit + filtreleme", True),
    (5, "Resize", "Lanczos batch resize (copy/in-place)", True),
    (6, "Caption", "Qwen3-VL multi-pass caption + insan onayı", True),
    (7, "Golden Set", "Quality + caption-aware cherry-pick", True),
]
