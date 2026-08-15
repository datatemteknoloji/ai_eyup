# Linux — failed systemd / boot

## Belirtiler
- `systemctl --failed` dolu, servis `activating (auto-restart)`, boot sonrası unit timeout.

## Hızlı teşhis
```bash
systemctl --failed --no-pager
systemctl status UNIT --no-pager -l
journalctl -u UNIT -n 80 --no-pager
journalctl -b -p err --no-pager | tail
```

## Sık kökler
- Bağımlılık (network-online, mount) hazır olmadan start.
- SELinux AVC (`ausearch -m avc -ts recent`).
- Port/bind, soket zaten kullanımda.
- ExecStart yolu yok / permission (`status=203/EXEC`).
- Disk dolu — unit journal yazamaz.

## Müdahale
1. Unit’i durdurup log oku; kör `restart` döngüsünü kes.
2. `systemctl cat UNIT` ile gerçek ExecStart.
3. Config test (nginx -t, sshd -t, named-checkconf).
4. Kalıcı override: `systemctl edit UNIT` (drop-in), unit dosyasını paket güncellemesinde ezme.

## ainew
Linux Chat: “failed servisler” / unit adı. Mutating restart agent onayı ister.
