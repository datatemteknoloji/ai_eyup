# Linux — SSH erişim / AI Ready

## Belirtiler
- ainew “SSH credential yok”, timeout, `Permission denied`, host key değişmiş.

## Kontroller
```bash
ss -lntp | grep :22
systemctl is-active sshd || systemctl is-active ssh
grep -E '^(PermitRootLogin|PasswordAuthentication|AllowUsers)' /etc/ssh/sshd_config /etc/ssh/sshd_config.d/* 2>/dev/null
journalctl -u sshd -n 40 --no-pager
```

## ainew tarafı
- Sunucu **AI Ready** + doğru IP + Global Credential (varsayılan işaretli).
- Port sunucu kaydındaki SSH portu ile aynı olmalı.
- Fail2ban / firewalld 22/tcp.
- Root login kapalıysa sudo kullanıcısı + `AGENT_FORCE_ROOT_PROMPT`.

## Host key
İlk bağlantıda known_hosts; sunucu rebuild sonrası key değişir — bilinçli kabul veya kaydı güncelle. Kör `StrictHostKeyChecking=no` üretimde önerme.

## WinRM karıştırmayın
Windows sunucular WinRM (5985/5986); Linux SSH. Unified chat platform ayırımı: Linux sorusunda OpenShift pod aracı kullanma.
