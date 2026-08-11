"""Chat — selamlaşma / sohbet (chitchat) hızlı yolu.

Amaç: selam, hâl hatır, kimlik, teşekkür, vedâ, kısa onay, nezaket vb. için
SSH/WinRM/tool/filo/RAG olmadan anında yanıt.

Kapsam: TR + EN + yaygın kısaltmalar + bileşik kalıplar (ör. “merhaba nasılsın”).
Ortam/teşhis kelimesi varsa chitchat sayılmaz.
Pending filo onayı varken “ok/tamam” API katmanında full_scan’ten sonra gelir.
"""
from __future__ import annotations

import re
from typing import Optional, Tuple

# Ortam / teşhis — chitchat değil (selam + ops karışık mesajlar da buraya düşer)
_OPS_BLOCK = re.compile(
    r"("
    r"sunucu|server|host|vm\b|filo|cluster|pod|namespace|datastore|vcenter|esx|"
    r"ssh|winrm|cpu|ram|disk|alarm|log|metric|prometheus|openshift|linux|windows|"
    r"hata|error|fail|down|crash|pending|kontrol|incele|listele|kaç\s|kac\s|"
    r"rapor|migrasyon|taşıma|tasima|backup|snapshot|vlan|ip\s*adres|"
    r"servis|systemd|hyper-?v|vmware|kapasite|online|offline|reboot|restart|"
    r"deploy|pipeline|ticket|jira|grafana|node\b|container|docker|k8s|kubernetes"
    r")",
    re.IGNORECASE,
)

# Bileşik: selam + hâl hatır → wellbeing yanıtı
_GREETING_WELLBEING = re.compile(
    r"(?i)^\s*"
    r"(?:"
    r"m+erhaba(?:lar)?|selam(?:lar|ın|in)?|slm|selm|mrb|mrba|"
    r"g[uü]nayd[ıi]n|iyi\s*g[uü]nler|iyi\s*ak[sş]amlar|"
    r"hi+|hello|hey+|yo\b|good\s*(?:morning|afternoon|evening|day)"
    r")"
    r"[\s,!.:-]*"
    r"(?:"
    r"nas[ıi]ls[ıi]n(?:ız)?|naber|ne\s*haber|iyi\s*misin(?:iz)?|"
    r"keyifler\s*nas[ıi]l|nas[ıi]l\s*gidiyor|nap[ıi]yors?un|"
    r"how\s*are\s*you(?:\s*doing)?|how'?s\s*it\s*going|what'?s\s*up|sup\b"
    r")"
    r"[\s!.?]*$"
)

# Kategori → regex (sıra önemli — ilk eşleşen)
_CATEGORIES: Tuple[Tuple[str, re.Pattern[str]], ...] = (
    (
        "greeting",
        re.compile(
            r"^("
            # TR
            r"m+erhaba(?:lar)?|selam(?:lar|ın|in)?|"
            r"selam[uü]n?\s*(?:[aü]naleyk[uü]m|aleyk[uü]m)|"
            r"aleyk[uü]m\s*selam|sselam|slm|selm|mrb|mrba|sa\b|"
            r"g[uü]nayd[ıi]n|iyi\s*g[uü]nler|iyi\s*ak[sş]amlar|iyi\s*geceler|"
            r"hay[ıi]rl[ıi]\s*(?:sabahlar|ak[sş]amlar|geceler)|"
            r"ho[sş]\s*geldin(?:iz)?|kolay\s*gelsin|"
            # EN
            r"hi+|hello(?:\s*there)?|hey+(?:\s*there)?|howdy|"
            r"good\s*(?:morning|afternoon|evening|day)|"
            r"yo\b|sup\b|what'?s\s*up|greetings"
            r")[\s!.?]*$",
            re.IGNORECASE,
        ),
    ),
    (
        "presence",
        re.compile(
            r"^("
            r"burada\s*m[ıi]s[ıi]n(?:ız)?|orda\s*m[ıi]s[ıi]n|"
            r"dinliyor\s*musun(?:uz)?|orada\s*m[ıi]s[ıi]n|"
            r"uyan[ıi]k\s*m[ıi]s[ıi]n|haz[ıi]r\s*m[ıi]s[ıi]n|"
            r"are\s*you\s*(?:there|here|listening|ready)|you\s*there\??|"
            r"anyone\s*there|ping\b"
            r")[\s!.?]*$",
            re.IGNORECASE,
        ),
    ),
    (
        "wellbeing",
        re.compile(
            r"^("
            r"nas[ıi]ls[ıi]n(?:ız)?|naber|nbr+|ne\s*haber|iyi\s*misin(?:iz)?|"
            r"keyifler\s*nas[ıi]l|moralin\s*nas[ıi]l|nas[ıi]l\s*gidiyor|"
            r"nap[ıi]yors?un(?:uz)?|ne\s*yap[ıi]yors?un(?:uz)?|"
            r"iyi\s*misiniz|nasilsiniz|"
            r"how\s*are\s*you(?:\s*doing)?|how'?s\s*it\s*going|"
            r"how\s*do\s*you\s*do|you\s*ok\??|are\s*you\s*ok\??|"
            r"how\s*have\s*you\s*been"
            r")[\s!.?]*$",
            re.IGNORECASE,
        ),
    ),
    (
        "identity",
        re.compile(
            r"^("
            r"(?:sen\s*)?kimsin(?:\s*sen)?|(?:siz\s*)?kimsiniz|"
            r"ad[ıi]n\s*ne|ismin\s*ne|ad[ıi]nız\s*ne|isminiz\s*ne|"
            r"ne\s*sin|n[eé]\s*oldu[gğ]un|kendini\s*tan[ıi]t|"
            r"ne\s*yapars[ıi]n|ne\s*i[sş]e\s*yarars[ıi]n|ne\s*yapabilirsin(?:iz)?|"
            r"yeteneklerin(?:iz)?\s*neler|neler\s*yapabilirsin(?:iz)?|"
            r"bana\s*nas[ıi]l\s*yard[ıi]m|yard[ıi]mc[ıi]\s*olabilir\s*misin(?:iz)?|"
            r"ne\s*konularda\s*yard[ıi]m|ne\s*konularda\s*uzmans[ıi]n|"
            r"ainew\s*misin|sen\s*ainew\s*misin|"
            r"who\s*are\s*you|what(?:'?s|\s*is)\s*your\s*name|"
            r"what\s*can\s*you\s*do|what\s*are\s*you|introduce\s*yourself|"
            r"your\s*(?:role|purpose|job|capabilities)|"
            r"are\s*you\s*(?:an?\s*)?(?:ai|bot|assistant|llm)|"
            r"tell\s*me\s*about\s*yourself"
            r")[\s!.?]*$",
            re.IGNORECASE,
        ),
    ),
    (
        "thanks",
        re.compile(
            r"^("
            r"te[sş]ekk[uü]r(?:ler)?|çok\s*te[sş]ekk[uü]r(?:ler)?|"
            r"sa[gğ]ol(?:un)?|çok\s*sa[gğ]ol(?:un)?|saol|sagol|"
            r"eyvallah|eyw|t[sş]k+|minnettar[ıi]m|ellerine?\s*sa[gğ]l[ıi]k|"
            r"thanks?|thank\s*you(?:\s*so\s*much)?|thx|ty\b|"
            r"appreciate(?:\s*it)?|cheers|many\s*thanks"
            r")[\s!.?]*$",
            re.IGNORECASE,
        ),
    ),
    (
        "farewell",
        re.compile(
            r"^("
            r"g[uü]le\s*g[uü]le|ho[sş][cç]a\s*kal(?:ın)?|"
            r"g[oö]r[uü][sş]mek\s*[uü]zere|g[oö]r[uü][sş][uü]r[uü]z|"
            r"iyi\s*g[uü]nler|iyi\s*ak[sş]amlar|iyi\s*geceler|"
            r"allah'?a\s*emanet|bb\b|bye\s*bye|"
            r"bye+|goodbye|good\s*bye|see\s*you(?:\s*later)?|see\s*ya|"
            r"take\s*care|later|cya|farewell|catch\s*you\s*later"
            r")[\s!.?]*$",
            re.IGNORECASE,
        ),
    ),
    (
        "ack",
        re.compile(
            r"^("
            # Not: bare "evet"/"hayır" filo onayına bırakılır — burada yok
            r"tamam(?:d[ıi]r)?|ok+|okay|o\.?k\.?|"
            r"anlad[ıi]m|anla[sş][ıi]ld[ıi]|peki|pekala|peki\s*tamam|"
            r"oldu|olur|süper|harika|m[uü]kemmel|muhte[sş]em|"
            r"devam|devam\s*edelim|kabul|evet\s*anlad[ıi]m|"
            r"tabii|tabi|elbette|desene|"
            r"got\s*it|understood|roger|sure|alright|all\s*right|"
            r"cool|nice|great|perfect|awesome|makes\s*sense|sounds\s*good|"
            r"copy\s*that|noted|fair\s*enough"
            r")[\s!.?]*$",
            re.IGNORECASE,
        ),
    ),
    (
        "help_soft",
        re.compile(
            r"^("
            r"yard[ıi]m(?:\s*et)?|help(?:\s*me)?|"
            r"ne\s*yapmal[ıi]y[ıi]m\s*$|ba[sş]la(?:yal[ıi]m)?|"
            r"nas[ıi]l\s*ba[sş]lar[ıi]m|ne\s*sorabilirim|ne\s*sorulur|"
            r"[oö]rnek\s*soru(?:lar)?|bir\s*sorum\s*var|"
            r"soru\s*sorabilir\s*miyim|bir\s*[sş]ey\s*sorabilir\s*miyim|"
            r"ne\s*yapabilirim\s*burada|how\s*can\s*you\s*help|"
            r"what\s*can\s*i\s*ask|show\s*examples?"
            r")[\s!.?]*$",
            re.IGNORECASE,
        ),
    ),
    (
        "compliment",
        re.compile(
            r"^("
            r"aferin|bravo|helal|iyi\s*i[sş]|g[uü]zel\s*i[sş]|harikas[ıi]n|"
            r"well\s*done|good\s*job|nice\s*work|"
            r"you(?:'?re|\s*are)\s*(?:great|awesome|helpful|amazing)|"
            r"thanks?\s*for\s*(?:the\s*)?help"
            r")[\s!.?]*$",
            re.IGNORECASE,
        ),
    ),
    (
        "apology",
        re.compile(
            r"^("
            r"[oö]z[uü]r\s*dilerim|pardon|affedersin(?:iz)?|kusura\s*bakma(?:yın)?|"
            r"sorry|my\s*bad|excuse\s*me|apologies|i\s*apologize"
            r")[\s!.?]*$",
            re.IGNORECASE,
        ),
    ),
)

# Emoji + kısa selam
_LOOSE_GREETING = re.compile(
    r"^[\s]*(?:👋|🙏|🙂|😊|🙌|👋️)?\s*"
    r"(?:m+erhaba+|selam+|slm|mrb|hi+|hello+|hey+|yo+)\b"
    r"(?:\s*(?:👋|🙏|🙂|😊))?"
    r"[\s!.?]*$",
    re.IGNORECASE,
)

_LOOSE_IDENTITY = re.compile(
    r"(?i)^\s*("
    r"(?:sen\s+)?(?:bir\s+)?(?:ai|yapay\s*zeka|asistan|bot|chatbot)\s*(?:m[ıi]s[ıi]n|misin)|"
    r"are\s+you\s+(?:an?\s+)?(?:ai|bot|assistant|llm)|"
    r"what\s+model\s+are\s+you|"
    r"hangi\s+model(?:sin|i\s*kullanıyorsun)?|"
    r"llm\s*misin|gpt\s*misin"
    r")\s*[?.!]?\s*$"
)

# Çok kısa nezaket / dolgu (tek başına)
_SOFT_FILLER = re.compile(
    r"(?i)^\s*("
    r"hmm+|h[ıi]mm+|ee+|yani|işte|iste|"
    r"hmm\s*ok|well\b|um+\b|uh+\b"
    r")\s*[!.?]*$"
)

_CANNED = {
    "greeting": (
        "Merhaba! Ben **ainew** altyapı asistanıyım. "
        "Linux, Windows, sanallaştırma veya Unified sohbette ortamınızla ilgili "
        "sorularınıza yardımcı olurum. Ne bakmak istersiniz?"
    ),
    "presence": (
        "Buradayım — ainew hazır. "
        "Sunucu, VM, kapasite veya bir teşhis sorusu yazabilirsiniz."
    ),
    "wellbeing": (
        "Teşekkürler, iyiyim — hazırım. "
        "Sunucu, VM, kapasite veya bir teşhis konusunda yardımcı olayım mı?"
    ),
    "identity": (
        "Ben **ainew** — Datatem’in altyapı yönetim asistanıyım. "
        "Envanter, sağlık, metrik, log ve sanallaştırma sorularında "
        "okuma amaçlı araçlarla yardımcı olurum; değişiklik için onaylı akışlar kullanılır. "
        "Örn: “kaç Linux sunucu online?”, “datastore boş alan”, “failed servisler”."
    ),
    "thanks": "Rica ederim! Başka bir şey olursa yazmanız yeterli.",
    "farewell": "Görüşürüz! İhtiyacınız olursa buradayım.",
    "ack": "Tamam. Devam etmek istediğiniz konuyu yazabilirsiniz.",
    "help_soft": (
        "Tabii. Örnekler:\n"
        "- “Kaç sunucu AI Ready?”\n"
        "- “Datastore’larda boş alan ne kadar?”\n"
        "- “ahmet-test VM durumu”\n"
        "- “failed systemd servisleri”\n"
        "Hedef seçerek veya sunucu/VM adını yazarak daha net yanıt alırsınız."
    ),
    "compliment": "Teşekkürler! Başka bir konuda da yardımcı olayım.",
    "apology": "Sorun değil. Nasıl yardımcı olabilirim?",
    "filler": "Dinliyorum — ne sormak istersiniz?",
}


def _norm(message: str) -> str:
    m = (message or "").strip()
    m = re.sub(r"\s+", " ", m)
    # Uç noktalama yığınını sadeleştir (!!! ???)
    m = re.sub(r"([!?.,])\1+", r"\1", m)
    return m


def classify_chitchat(message: Optional[str]) -> Optional[str]:
    """Chitchat kategorisi veya None. Ops/teşhis kelimesi varsa None."""
    raw = _norm(message or "")
    if not raw or len(raw) > 160:
        return None

    # Ortam sorusu karışmışsa chitchat değil
    if _OPS_BLOCK.search(raw):
        return None

    if _GREETING_WELLBEING.match(raw):
        return "wellbeing"
    if _LOOSE_GREETING.match(raw):
        return "greeting"
    if _LOOSE_IDENTITY.match(raw):
        return "identity"
    if _SOFT_FILLER.match(raw):
        return "filler"

    for cat, pat in _CATEGORIES:
        if pat.match(raw):
            return cat
    return None


def is_chitchat(message: Optional[str]) -> bool:
    return classify_chitchat(message) is not None


def canned_chitchat_answer(message: Optional[str], *, platform: Optional[str] = None) -> Optional[str]:
    cat = classify_chitchat(message)
    if not cat:
        return None
    text = _CANNED.get(cat)
    if not text:
        return None
    plat = (platform or "").strip().lower()
    if cat == "greeting" and plat:
        labels = {
            "linux": "Linux",
            "windows": "Windows",
            "virt": "sanallaştırma",
            "hypervisor": "sanallaştırma",
            "openshift": "OpenShift",
            "unified": "Unified",
            "exadata": "Exadata",
        }
        label = labels.get(plat)
        if label:
            text = (
                f"Merhaba! Bu **{label}** sohbeti — ainew asistanıyım. "
                "Kısa selam için buradayım; ortam sorularınızda canlı/DB araçlarıyla yardımcı olurum. "
                "Ne sormak istersiniz?"
            )
    return text
