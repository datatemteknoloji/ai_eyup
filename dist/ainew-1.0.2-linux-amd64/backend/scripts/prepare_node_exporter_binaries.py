#!/usr/bin/env python3
"""
Node Exporter binary'lerini backend sunucusunda hazırla
"""
import os
import sys
import requests
import tarfile
import shutil
from pathlib import Path

# Project root'a ekle
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.config import settings

NODE_EXPORTER_VERSION = "1.7.0"
ARCHITECTURES = ["amd64", "arm64", "armv7"]
BASE_URL = f"https://github.com/prometheus/node_exporter/releases/download/v{NODE_EXPORTER_VERSION}"

def download_and_extract(arch: str, storage_path: Path) -> bool:
    """Node Exporter binary'sini indir ve çıkart"""
    try:
        arch_dir = storage_path / arch
        arch_dir.mkdir(parents=True, exist_ok=True)
        
        tar_filename = f"node_exporter-{NODE_EXPORTER_VERSION}.linux-{arch}.tar.gz"
        download_url = f"{BASE_URL}/{tar_filename}"
        temp_tar = storage_path / tar_filename
        
        print(f"📥 İndiriliyor: {arch} ({download_url})")
        
        # İndir
        response = requests.get(download_url, stream=True, timeout=60)
        response.raise_for_status()
        
        with open(temp_tar, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        print(f"   ✅ İndirme tamamlandı: {temp_tar.stat().st_size / 1024 / 1024:.2f} MB")
        
        # Çıkart
        with tarfile.open(temp_tar, 'r:gz') as tar:
            binary_name = f"node_exporter-{NODE_EXPORTER_VERSION}.linux-{arch}/node_exporter"
            tar.extract(binary_name, path=storage_path)
            
            # Binary'yi arch dizinine kopyala
            extracted_binary = storage_path / binary_name
            target_binary = arch_dir / "node_exporter"
            
            shutil.move(str(extracted_binary), str(target_binary))
            os.chmod(target_binary, 0o755)
            
            print(f"   ✅ Binary hazır: {target_binary} ({target_binary.stat().st_size / 1024:.2f} KB)")
            
            # Temp dosyaları temizle
            temp_tar.unlink()
            extract_dir = storage_path / f"node_exporter-{NODE_EXPORTER_VERSION}.linux-{arch}"
            if extract_dir.exists():
                shutil.rmtree(extract_dir)
            
            return True
            
    except Exception as e:
        print(f"   ❌ Hata ({arch}): {e}")
        return False

def main():
    """Ana fonksiyon"""
    print("🚀 Node Exporter binary'leri hazırlanıyor...\n")
    
    storage_path = Path(settings.NODE_EXPORTER_STORAGE_PATH)
    storage_path.mkdir(parents=True, exist_ok=True)
    
    print(f"📁 Storage path: {storage_path}\n")
    
    success_count = 0
    fail_count = 0
    
    for arch in ARCHITECTURES:
        if download_and_extract(arch, storage_path):
            success_count += 1
        else:
            fail_count += 1
        print()
    
    print(f"📊 Özet:")
    print(f"   ✅ Başarılı: {success_count}")
    print(f"   ❌ Başarısız: {fail_count}")
    print(f"   📦 Toplam: {len(ARCHITECTURES)}")
    
    if success_count > 0:
        print(f"\n✅ Binary'ler hazır: {storage_path}")
        return 0
    else:
        print(f"\n❌ Hiçbir binary hazırlanamadı!")
        return 1

if __name__ == "__main__":
    sys.exit(main())
