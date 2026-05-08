# Pipeline Örnekleri

End-to-end demolar — sahte data ile pipeline'ın nasıl çalıştığını gösterir.

## İçerik

| Dosya / Klasör | Ne yapar |
|---|---|
| `sample-dataset/` | Telif sorunsuz örnek görseller (placeholder) |
| `run-pipeline.sh` | Örnek end-to-end pipeline scripti |

## Kullanım

```bash
# Önce kurulum (bir kez):
make install         # tools/ altına 7 repo
cp .env.example .env # .env'i düzenle

# Pipeline test:
make test
# veya:
./examples/run-pipeline.sh
```

## sample-dataset/

Buraya **kendi örnek görsellerinizi** koyabilirsiniz. Pipeline'ı denemek için yeterli birkaç görsel:
- 5-10 farklı format (jpg, png, webp)
- Birkaç bilerek bozuk/duplicate (validate ve dedupe test için)
- 1-2 filigranlı (watermark detection test için)
- Farklı çözünürlük (resize test için)

**Telif notu:** Public repo olduğu için yalnızca telif sorunsuz görseller (CC0, kendi çekiminiz, public domain) kullanın.

## Geçiş Yolu

Tool repos açıldıkça `run-pipeline.sh` somut komutlarla güncellenir. Şu an placeholder:

```bash
./examples/run-pipeline.sh
# Şu an output:
# "Adım 1/7: media-validator
#   cd tools/01-validate && python run.py ..."
```

Tool yayına alındıkça komutlar gerçek hale gelecek.
