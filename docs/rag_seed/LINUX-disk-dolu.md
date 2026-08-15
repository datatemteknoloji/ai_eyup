# Linux — disk dolu / inode

## Belirtiler
- `No space left on device`, servis yazamıyor, log kesilmiş, `df -h` %90+.

## Hızlı teşhis
```bash
df -hT
df -i
du -xhd1 /var /home /opt /tmp 2>/dev/null | sort -h
journalctl --disk-usage
```

## Müdahale sırası
1. Hangı dosya sistemi dolu (`/` vs `/var` vs `/home`) — inode doluysa küçük dosya patlaması (spool, session).
2. `/var/log`: rotate edilmemiş `*.log`, container overlay, audit.
3. `/tmp` ve `/var/tmp` eski paket/core dump.
4. Silmeden önce: hangi süreç dosyayı açık tutuyor (`lsof +L1` / `lsof | grep deleted`).
5. Kalıcı: logrotate, journal `SystemMaxUse`, container prune politikası.

## ainew
Linux AI Chat’te sunucu adı + “disk dolu” sorun; canlı SSH `df`/servis context gelir. Filo taraması için hedef seçin veya sunucu adını yazın.
