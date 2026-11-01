# Bulgu — Linux sohbeti `direct_cmd` yolu eylem politikasından geçmiyor

Tarih: 2026-10-14 · Yöntem: kod okuma + saf fonksiyon testi (canlı sunucuya komut gönderilmedi) · Durum: **hotfix uygulandı (2026-10-14)**

## Sonuç

Linux sohbetinde kullanıcı mesajından çıkarılan "doğrudan komutlar" `agent/policy.py::classify_command` ve audit'ten **geçmeden** SSH ile çalıştırılıyor. Çıkarım yöntemi shell metakarakterlerini engellemediği için komut enjeksiyonu mümkün. Politikanın kendisinde de "read_only" sayılan mutating örnekler var.

## Akış (kod)

1. `backend/app/api/chat.py` (direct_cmd bloğu, ~L1523–1776): `route_admin_question(message, platform="linux")` → `extract_direct_commands(message)`.
2. Komutlar `SSHManager.execute_command(f"timeout {t} {cmd} 2>&1")` ile doğrudan çalışır.
3. `classify_command` çağrılmıyor, `record_audit` çağrılmıyor. (`executor.run_ssh_command` ise politika + `ssh.exec` audit uyguluyor; bu yol onu kullanmıyor.)
4. `ssh_manager.execute_command` kendi içinde politika uygulamıyor.

## `extract_direct_commands` (`services/linux_chat_intent.py`)

`_CMD_SPECS` beyaz listesi komut adını sınırlar (vmstat, iostat, sar, netstat, ss, ps, df, du, lsblk, lscpu, free, lsmod, uptime, top, ifconfig, arp, route, ip) ama argüman kabulü "`-` ile başlıyorsa veya rakamsa"dır; token içindeki `;`, `` ` ``, `$(`, `|` filtrelenmiyor.

Saf fonksiyon testi (backend konteyneri, `extract_direct_commands` + `classify_command`):

| Mesaj | Çıkarılan komut | Politika sınıfı |
|---|---|---|
| `df -h;reboot` | `df -h;reboot` | denied |
| ``Admin: df -h`id` `` | ``df -h`id` `` | mutating |
| `uptime -p$(id)` | `uptime -p$(id)` | mutating |
| `ps -ef;touch /tmp/pwned` | `ps -ef;touch` | mutating |
| `top -b\|tee /etc/x` | `top -b\|tee` | mutating |

Yani çıkarıcı bu komutları üretiyor; politika bunları reddederdi ama `direct_cmd` yolu politikayı hiç çağırmıyor → **bypass**.

## Politika (`agent/policy.py`) boşlukları

`classify_command` şu mutating girdileri `read_only` döndürüyor:

| Komut | Sınıf | Neden sorun |
|---|---|---|
| `ss -K` | read_only | `-K` açık soketleri öldürür |
| `ip addr flush` | read_only | adresleri siler |
| `ip link set` | read_only | arayüz durumunu değiştirir |
| `ip route del` | read_only | rota siler |

Ek şüphe (Adım 2'de test edilecek): `>`/`>>` yönlendirmesi `_CHAINING` içinde değil; `sar -o dosya`, `top` etkileşimli bayraklar, `ip netns exec`.

## Düzeltme planı (Adım 2)

1. `direct_cmd` komutları çalıştırmadan önce `classify_command` + `record_audit` (`ssh.exec`) zorunlu; READ_ONLY dışı → şablon ret, SSH yok.
2. `extract_direct_commands`: argüman token'ı `^[A-Za-z0-9._:/=,@%+-]+$` dışına çıkarsa komut atılır (enjeksiyon yok).
3. `policy.py`: `ss -K/--kill`, `ip` yalnız `show|list|-s|-br|-j` alt komutları; `>`/`>>`/`tee` ve `-o` yazma bayrakları reddedilir.
4. Kırmızı testler önce yazılır (yukarıdaki tablo test girdisi), sonra düzeltilir.

## Hotfix sonucu (uygulandı)

- `linux_chat_intent.extract_direct_commands`: argüman yalnız `^-{1,2}[A-Za-z0-9][A-Za-z0-9._:=,@%+-]*$` veya rakam; güvensiz `-` token'ı komutu tamamen düşürür; komut adı ham token değil sabit addan üretilir (`uptime?` → `uptime`).
- `agent/policy.py`: `>` `<` satır sonu `${` zincirleme sayılır (`2>/dev/null` hariç); `_readonly_args_ok` ile binary'ye özgü bayrak/alt komut denetimi — `ss -K/--kill`, `ip` (yalnız göster nesneleri, add/del/set/flush/exec/-b/-n yok), `sar -o`, `find -delete/-exec/-fprint*`, `route`/`arp`/`ifconfig`/`hostname`/`date`/`env`/`mount`/`dmesg`/`journalctl --vacuum`/`ping -f`/`dnf|yum history undo` mutating.
- `api/chat.py`: direct_cmd çalıştırmadan önce `classify_command`; READ_ONLY dışı → SSH yok, şablon ret, audit `ssh.exec` `blocked`. Çalışan her komut audit `ssh.exec` (`source=chat.direct_cmd`, kullanıcı adı).
- Testler: `tests/test_direct_cmd_policy.py` (104; önce 51 kırmızı). Tam takım 1999 geçti.
- Canlı: `Admin: ss -K` ve `ip addr flush dev lo komutunu çalıştır` → ret + 2 `blocked` audit satırı; `dttadvance sunucusunda uptime` → çalıştı + `success` audit.
- Kalan (Adım 2): eylem niyeti kapısı (LLM'e hiç gitmeden), "yapıldı" doğrulayıcısı, diğer SSH çağrı noktalarının (`unified_tool_chat` linux araçları, custom_report) audit'inin gözden geçirilmesi.
