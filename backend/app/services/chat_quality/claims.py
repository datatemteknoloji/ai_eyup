"""Mutating komut kalıpları, "yapıldı" iddiası ve prompt-sızıntı kalıpları (saf fonksiyonlar).

Sohbet katmanı salt-okunurdur: hiçbir eylem aracı yoktur. Bu yüzden
  - bir eylemin gerçekleştiğini söyleyen cümle (güçlü iddia) HER ZAMAN yanlıştır,
  - zayıf iddia (edilgen geçmiş) yalnız kullanıcı eylem istediyse yanlıştır
    (aksi halde olay/log verisini aktarıyor olabilir: "3 gün önce yeniden başlatıldı").
"""
from __future__ import annotations

import re
import unicodedata
from typing import Iterable, List, Optional, Tuple

_TR_MAP = str.maketrans({
    "ı": "i", "İ": "i", "ş": "s", "Ş": "s", "ğ": "g", "Ğ": "g",
    "ü": "u", "Ü": "u", "ö": "o", "Ö": "o", "ç": "c", "Ç": "c",
})


def fold(s: str) -> str:
    """Küçük harf + Türkçe karakterleri ASCII'ye indir + görünmez/ayrık karakterleri temizle."""
    s = (s or "").translate(_TR_MAP)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    for ch in ("\u200b", "\u200c", "\u200d", "\u2060", "\ufeff", "\u00ad"):
        s = s.replace(ch, "")
    s = s.replace("\u2011", "-").replace("\u2010", "-").replace("\u2019", "'")
    return s.lower()


# ── Değişiklik yapan komut imzaları (kod bloğu / satır içi kod / mesaj içi) ─────────
_KUBE_MUT = (
    r"(?:delete|apply|create|patch|scale|replace|edit|rollout\s+(?:restart|undo|pause|resume)|"
    r"drain|cordon|uncordon|taint|label|annotate|set|run|expose|cp|exec|debug|"
    r"adm\s+(?:drain|cordon|uncordon|policy|upgrade|taint|new-project|groups|prune)|"
    r"new-app|start-build|import-image|tag|policy|process|rsh|patch)"
)
MUTATING_CMD_RE: List[re.Pattern] = [
    re.compile(rf"\b(?:kubectl|oc)\s+(?:-{{1,2}}[\w=./:-]+\s+)*{_KUBE_MUT}\b", re.I),
    re.compile(r"\bsystemctl\s+(?:-{1,2}[\w=-]+\s+)*(?:restart|stop|start|reload|enable|disable|mask|unmask|kill|daemon-reload|reboot|poweroff|halt|isolate|set-default)\b", re.I),
    re.compile(r"\bservice\s+\S+\s+(?:restart|stop|start|reload)\b", re.I),
    re.compile(r"\b(?:dnf|yum|apt|apt-get|zypper|snap|pip3?|npm)\s+(?:-{1,2}[\w=-]+\s+)*(?:update|upgrade|install|remove|erase|autoremove|localinstall|downgrade|dist-upgrade|uninstall|reinstall)\b", re.I),
    re.compile(r"\brpm\s+-[a-z]*[eiU][a-z]*\b", re.I),
    re.compile(r"(?:^|[\s;&|(`])(?:sudo\s+)?(?:rm|mv|cp|dd|mkfs(?:\.\w+)?|fdisk|parted|mkswap|swapoff|swapon|chmod|chown|chattr|truncate|shred|kill|killall|pkill|reboot|shutdown|halt|poweroff|useradd|userdel|usermod|groupdel|passwd|iptables|firewall-cmd|ufw|umount|visudo|crontab\s+-[re])(?=\s|$)", re.I),
    re.compile(r"\binit\s+[0-6]\b", re.I),
    re.compile(r"\bsed\s+(?:-\w+\s+)*-i\b", re.I),
    re.compile(r"\b(?:lvremove|lvextend|lvresize|lvreduce|vgextend|vgreduce|vgremove|pvremove|pvmove|resize2fs|xfs_growfs)\b", re.I),
    re.compile(r"\bjournalctl\b[^\n]*--(?:vacuum|rotate|flush)", re.I),
    re.compile(r"\b(?:docker|podman)\s+(?:rm|rmi|stop|kill|restart|prune|system\s+prune|volume\s+rm|run|exec)\b", re.I),
    re.compile(r"\bvmware-vim-cmd\b[^\n]*(?:power\.(?:off|on|reset|shutdown|reboot|suspend)|destroy|unregister|reload)", re.I),
    re.compile(r"\bgovc\s+vm\.(?:destroy|power|migrate|clone|create|change)", re.I),
    re.compile(r"\besxcli\b[^\n]*\b(?:set|remove|add|enable|disable|reset)\b", re.I),
    re.compile(r"\bhelm\s+(?:install|upgrade|uninstall|rollback|delete)\b", re.I),
    re.compile(r"\b(?:ansible-playbook|terraform\s+(?:apply|destroy))\b", re.I),
    re.compile(r"\bgit\s+(?:push|reset\s+--hard|clean\s+-f)\b", re.I),
]


def is_mutating_command_text(text: str) -> bool:
    return any(p.search(text or "") for p in MUTATING_CMD_RE)


# ── Cevaptaki kod blokları / satır içi kodlardan komut çıkarma ───────────────────
_FENCE_RE = re.compile(r"```[^\n]*\n(.*?)(?:```|\Z)", re.S)
_INLINE_RE = re.compile(r"(?<!`)`([^`\n]{3,200})`(?!`)")


def _command_lines(block: str) -> Iterable[str]:
    for raw in (block or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") and not line.startswith("#!"):
            # '# comment' satırı; ama root istemi '# systemctl restart x' olabilir → komutu da dene
            line = line.lstrip("# ").strip()
            if not line:
                continue
        line = re.sub(r"^[$>#]\s+", "", line)
        yield line


def _warning_noise(cmd: str, inline: bool) -> bool:
    """Öneri uyarısında gürültü sayılanlar: operandsız satır içi sözcük ("kill -9", "oc debug") ve
    `oc debug … -- [chroot /host] <salt-okunur komut>` (içteki komut salt-okunursa)."""
    toks = cmd.split()
    m = None
    for p in MUTATING_CMD_RE:
        m = p.search(cmd)
        if m:
            break
    if inline and m is not None:
        rest = cmd[m.end():].split()
        if not any(not t.startswith("-") for t in rest):
            return True
    mm = re.search(r"\boc\s+debug\b[^\n]*?\s--\s+(?:chroot\s+\S+\s+)?(.+)$", cmd)
    if mm:
        try:
            from app.services.agent.policy import RiskLevel, classify_command
            return classify_command(mm.group(1).strip()) == RiskLevel.READ_ONLY
        except Exception:
            return False
    return False


def extract_mutating_commands(answer: str, limit: int = 8) -> List[str]:
    """Cevaptaki kod blokları ve satır içi kodlarda geçen değişiklik yapan komutlar (benzersiz, sıralı)."""
    found: List[str] = []

    def _add(cmd: str, inline: bool = False) -> None:
        cmd = cmd.strip()
        if (cmd and cmd not in found and is_mutating_command_text(cmd) and len(found) < limit
                and not _warning_noise(cmd, inline)):
            found.append(cmd[:160])

    for m in _FENCE_RE.finditer(answer or ""):
        for line in _command_lines(m.group(1)):
            _add(line)
    stripped = _FENCE_RE.sub(" ", answer or "")
    for m in _INLINE_RE.finditer(stripped):
        _add(m.group(1), inline=True)
    return found


RISK_MARKER = "Değişiklik yapan komut uyarısı"


def risk_warning_block(cmds: List[str]) -> str:
    shown = ", ".join(f"`{c}`" for c in cmds[:5])
    return (
        f"\n\n> ⚠️ **{RISK_MARKER}:** Yukarıdaki yanıtta ortamda değişiklik yapan komut(lar) geçiyor: "
        f"{shown}. Bu sohbet bunları **çalıştırmaz**. Uygulamadan önce etkisini ve geri dönüş yolunu "
        "doğrulayın, yedek/anlık görüntü alın, önce test ortamında deneyin; değişiklik için onaylı "
        "Agent akışını kullanın."
    )


# ── "Yapıldı" iddiası ────────────────────────────────────────────────────────
# Fold'lanmış (ASCII, küçük harf) metinde çalışır.
_V_TR = (
    r"calistiril|silin|kapatil|durdurul|baslatil|yeniden baslatil|olusturul|kaldiril|guncellen|"
    r"uygulan|tasin|olceklen|eklen|degistiril|iptal edil|tetiklen|sifirlan|resetlen|gerceklestiril|"
    r"yedeklen|geri yuklen|tamamlan"
)
# Güçlü: birinci tekil şahıs / "başarıyla" / "komut ... çalıştırıldı"
_STRONG_TR = [
    re.compile(r"\b(?:sildim|kapattim|durdurdum|baslattim|yeniden baslattim|calistirdim|olusturdum|"
               r"kaldirdim|guncelledim|uyguladim|tasidim|olcekledim|ekledim|degistirdim|iptal ettim|"
               r"tetikledim|sifirladim|resetledim|gerceklestirdim|yedekledim|geri yukledim)\b"),
    re.compile(rf"\bbasariyla\s+(?:{_V_TR})(?:di|du|mis|mus)\b"),
    re.compile(r"\b(?:komut|islem|talep|istek)\w*\s+(?:\w+\s+){0,3}(?:basariyla\s+)?"
               r"(?:calistiril(?:di|mis)|uygulan(?:di|mis)|gerceklestiril(?:di|mis)|tamamlan(?:di|mis))\b"),
]
_WEAK_TR = [
    re.compile(rf"\b(?:{_V_TR})(?:di|du|mis|mus)\b"),
]
_STRONG_EN = [
    re.compile(r"\bi(?:'ve|\s+have)?\s+(?:successfully\s+)?(?:deleted|executed|restarted|stopped|created|removed|"
               r"rebooted|started|killed|terminated|applied|updated|scaled|shut\s+down|migrated|run|ran)\b"),
    re.compile(r"\bsuccessfully\s+(?:deleted|executed|restarted|stopped|created|removed|rebooted|started|killed|"
               r"terminated|applied|updated|scaled|migrated|ran|run)\b"),
    re.compile(r"\b(?:command|operation|request)\b[^.\n]{0,40}\b(?:was|has\s+been)\s+(?:successfully\s+)?"
               r"(?:executed|completed|run|applied)\b"),
]
_WEAK_EN = [
    re.compile(r"\b(?:was|were|has\s+been|have\s+been)\s+(?:deleted|executed|restarted|stopped|created|removed|"
               r"rebooted|started|killed|terminated|applied|scaled|shut\s+down|migrated)\b"),
]
# Olumsuzlama / niyet / hipotez: bu cümleler iddia değildir
_NEGATION = re.compile(
    r"\b(?:calistirilmadi|calistirilamaz|calistiramam|calistirmam|yapamam|yapilmadi|silinmedi|silmedim|"
    r"kapatilmadi|kapatmadim|baslatilmadi|degistirilmedi|degistirmedim|uygulanmadi|"
    r"not\s+(?:executed|run|deleted|performed)|was\s+not|were\s+not|has\s+not|have\s+not|did\s+not|didn't|cannot|can't|"
    r"calistirilmaz|silinmez|olmadi|olmaz|olursa|olsaydi|edilseydi|"
    r"calistirilirsa|silinirse|kapatilirsa|baslatilirsa|if\b)\b"
)


def claim_level(sentence: str, *, user_action_intent: bool) -> Optional[str]:
    """'strong' | 'weak' | None. Yalnız cümle düzeyinde çalışır; kod bloğu dışı metne uygulanır."""
    f = fold(sentence)
    if _NEGATION.search(f):
        return None
    if any(p.search(f) for p in _STRONG_TR + _STRONG_EN):
        return "strong"
    if user_action_intent and any(p.search(f) for p in _WEAK_TR + _WEAK_EN):
        return "weak"
    return None


# ── Sistem prompt'u sızıntısı (cevap tarafı) ───────────────────────────────────
LEAK_MARKERS: List[re.Pattern] = [
    re.compile(r"sen\s+15\+\s+y[ıi]ll[ıi]k\s+deneyime", re.I),
    re.compile(r"\b15\+\s+y[ıi]ll[ıi]k\s+deneyime\s+sahip\s+k[ıi]demli", re.I),
    re.compile(r"\bYANIT\s+KURALLARI\s*:", re.I),
    re.compile(r"\bMOD[ÜU]L\s+SINIRI\s*:", re.I),
    re.compile(r"\bTER[İI]M\s+AYRIMI\b", re.I),
    re.compile(r"\bVER[İI]\s+D[İI]S[İI]PL[İI]N[İI]\b", re.I),
    re.compile(r"\bKRİTİK\s+KURAL\s*:", re.I),
    re.compile(r"\bSAYI\s+KURALI\s*:", re.I),
    re.compile(r"\bNUMBER_RULE", re.I),
    re.compile(r"\bORTAM\s+KANITLI\s+UZMANLIK\b", re.I),
    re.compile(r"\bUZMANLIK\s*:\s*pod", re.I),
    re.compile(r"\bKARISTIRMA\s*:", re.I),
    re.compile(r"\bBAĞLAM\s+ve\s+ARAÇ\s+SONUÇLARI\b", re.I),
    re.compile(r"\bKULLANICI\s+SORUSU\s*:", re.I),
    re.compile(r"<\|im_start\|>|<\|system\|>", re.I),
    re.compile(r"\bsystem\s+prompt\s*:", re.I),
]


def find_leak(text: str, shingles: Optional[set] = None) -> Optional[str]:
    """Sızıntı kalıbını (veya kayıtlı prompt metninden 8 kelimelik örtüşmeyi) döner."""
    t = text or ""
    for p in LEAK_MARKERS:
        m = p.search(t)
        if m:
            return m.group(0)[:60]
    if shingles:
        words = re.findall(r"\w+", fold(t))
        for i in range(0, max(0, len(words) - 7)):
            if " ".join(words[i:i + 8]) in shingles:
                return " ".join(words[i:i + 8])
    return None


def make_shingles(text: str, n: int = 8) -> set:
    words = re.findall(r"\w+", fold(text))
    return {" ".join(words[i:i + n]) for i in range(0, max(0, len(words) - n + 1))}
