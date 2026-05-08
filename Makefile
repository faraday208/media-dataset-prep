.PHONY: help install install-local install-hybrid update clean test check sync

help:
	@echo "dataset-prep — Meta-orchestrator for AI image dataset pipeline"
	@echo ""
	@echo "Kurulum modları:"
	@echo "  make install         - PRODUCTION: 7 tool'u GitHub'dan clone'la"
	@echo "  make install-local   - DEVELOPMENT: Yerel ai-visual-lab/dataset-prep/'tan symlink"
	@echo "  make install-hybrid  - HİBRİT: GitHub varsa clone, yoksa yerelden symlink"
	@echo ""
	@echo "Diğer komutlar:"
	@echo "  make update    - tools/'taki repolari güncelle (git pull) + uv sync"
	@echo "  make sync      - Sadece uv sync (venv güncelle)"
	@echo "  make check     - Tool'ların API health check"
	@echo "  make test      - Örnek pipeline çalıştır"
	@echo "  make clean     - tools/ klasörünü temizle (uyarı sorar)"

install:
	@./scripts/install-tools.sh github
	@echo ""
	@echo "→ uv sync ile workspace venv kuruluyor..."
	@uv sync 2>/dev/null || echo "  (uv sync atlandı — workspace member'ları henüz hazır olmayabilir)"
	@echo ""
	@echo "✅ Kurulum tamamlandı"

install-local:
	@./scripts/install-tools.sh local
	@echo ""
	@echo "→ Geliştirme modunda kuruldu (yerel symlink'ler)"
	@echo "  uv sync atlandı — tool'lar pyproject.toml'a sahip olunca aktif edilir"
	@echo ""
	@echo "✅ Yerel kurulum tamamlandı"

install-hybrid:
	@./scripts/install-tools.sh hybrid
	@uv sync 2>/dev/null || echo "  (uv sync atlandı)"

update:
	@./scripts/update-tools.sh
	@uv sync 2>/dev/null || true

sync:
	@uv sync

check:
	@./scripts/check-tools.sh

test:
	@./examples/run-pipeline.sh

clean:
	@read -p "tools/ silinecek (symlink'ler ve clone'lar). Emin misin? [y/N] " ans; \
	if [ "$$ans" = "y" ] || [ "$$ans" = "Y" ]; then \
		find tools/ -mindepth 1 -maxdepth 1 \( -type d -o -type l \) -exec rm -rf {} +; \
		echo "✓ tools/ temizlendi (.gitkeep korundu)"; \
	else \
		echo "İptal edildi"; \
	fi
