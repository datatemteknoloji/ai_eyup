# datatem AI — Design System

> **Aesthetic:** Industrial Precision  
> **Tone:** Powerful · Corporate · User-Friendly  
> **Theme:** Dark (primary)  
> **UI Type:** Data-dense Admin Dashboard  

---

## 1. Aesthetic Rationale

"Saate bakıyorsun gibi güven veren, ama alarm çaldığında seni uyandıran bir arayüz."

**Referanslar:** Datadog · Linear · IBM Carbon · PagerDuty  
**Anti-pattern:** Cyber/neon dekorasyonlar, renk parlaması, emoji, AI Slop default'ları

---

## 2. Color Tokens

```css
:root {
  /* Surfaces — elevation via lightness, not hue shift */
  --bg-base:     #080d16;   /* Page background */
  --bg-surface:  #0d1422;   /* Card / panel */
  --bg-elevated: #131c2f;   /* Hover state, dropdown */
  --bg-overlay:  #1a2540;   /* Selected row, active nav */

  /* Text */
  --text-primary:   #e8edf5;  /* Body copy */
  --text-secondary: #8a9bbf;  /* Labels, metadata */
  --text-muted:     #3d4f6e;  /* Placeholder, disabled */

  /* Single accent — blue, not purple */
  --accent:        #3b82f6;
  --accent-glow:   rgba(59,130,246,0.25);
  --accent-hover:  #2563eb;
  --accent-muted:  #1a3057;   /* Active nav bg */
  --accent-subtle: rgba(59,130,246,0.12);

  /* Semantic */
  --success:     #22c55e;
  --success-bg:  rgba(34,197,94,0.10);
  --success-glow:rgba(34,197,94,0.20);
  --warning:     #f59e0b;
  --warning-bg:  rgba(245,158,11,0.10);
  --warning-glow:rgba(245,158,11,0.20);
  --error:       #ef4444;
  --error-bg:    rgba(239,68,68,0.10);
  --error-glow:  rgba(239,68,68,0.20);
  --info:        #38bdf8;
  --info-bg:     rgba(56,189,248,0.10);

  /* Borders */
  --border:        rgba(255,255,255,0.06);
  --border-strong: rgba(255,255,255,0.11);
}
```

**Kurallar:**
- Mor (`purple`, `violet`) kullanılmaz — blue-600 tek aksan rengidir
- Yüzey ayrımı opacity ile yapılır, farklı hue ile değil
- Neon glow animasyonları yasaktır

---

## 3. Typography

| Rol | Font | Boyut | Ağırlık |
|-----|------|-------|---------|
| Display / H1 | DM Sans | 26px | 800 |
| H2 / Bölüm başlığı | DM Sans | 20px | 700 |
| H3 / Kart başlığı | DM Sans | 15px | 600 |
| Body | DM Sans | 14px | 400 |
| Küçük / Meta | DM Sans | 12px | 400 |
| Badge / Label | DM Sans | 10–11px | 700 + uppercase |
| Data / Mono | DM Mono | 13px | 400–500 |

**Özel kullanım:**
- IP adresleri, kernel versiyonları, port numaraları → `font-family: 'DM Mono'`
- Metrik rakamları (CPU%, bellek) → `font-family: 'DM Mono', font-weight: 700`
- Tablo içeriği → `14px / DM Sans`

**Google Fonts import:**
```html
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700;800&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
```

---

## 4. Spacing

Base: **4px**  
Scale: `4 · 8 · 12 · 16 · 24 · 32 · 48 · 64px`

Yoğunluk: **Compact** — admin aracı, her piksel değerli.

---

## 5. Border Radius

| Öğe | Değer | Tailwind |
|-----|-------|---------|
| Sayfa paneli / modal | 16px | `rounded-2xl` |
| Kart | 12px | `rounded-xl` |
| Input / buton | 8px | `rounded-lg` |
| Badge | 6px | `rounded-md` |
| Dot indicator | 50% | `rounded-full` |

**Anti-pattern:** `rounded-full` butonlar için yasaktır.

---

## 6. Buttons

```
Primary   → bg-accent, white text, box-shadow: 0 2px 10px accent-glow
Secondary → bg-elevated, border: border-strong, text-primary
Ghost     → transparent, border-transparent, text-secondary
Danger    → bg-error-bg, color-error, border: error 25%
```

**Boyut:**
- Default: `px-4 py-2` (16px/8px) — 36px tall
- Small: `px-3 py-1.5` (12px/6px) — 30px tall
- Icon: `p-2` (32px square)

**Touch target minimum:** 32px tall (admin araçları için kabul edilebilir)

---

## 7. Badge / Status

```
Active/Online → badge-green: success-bg + success color + border
Critical      → badge-red
Warning       → badge-amber
AI Ready      → badge-blue (info color)
Neutral/OS    → badge-neutral: white 6% opacity
```

**Format:** `<dot> Label` — metin her zaman kısa (max 2 kelime)

---

## 8. Dashboard Visual Components

### 8.1 Health Gauge
Yarı daire gauge, ibre + renk zonu (kırmızı→amber→yeşil).
- SVG tabanlı, pure CSS animasyon yok
- Değer altında büyük rakam + açıklama metni

### 8.2 Ring / Donut Chart
- SVG `stroke-dasharray` ile
- Merkez: büyük rakam + küçük label
- Sağ/altında legend: dot + label + değer

### 8.3 Sparkline Trend
- SVG `<path>` + gradient fill
- Alt eksende gün etiketleri
- Sağ üstte yüzde badge (renk kodlu)

### 8.4 Progress Bar (Tablo satırı)
- `bar-track` (thin, 4px height) + `bar-fill` (color-coded)
- Renk: yeşil ≤ 60%, amber 60–85%, kırmızı > 85%
- Yanında mono font ile yüzde değeri

---

## 9. Layout

```
Sidebar:  230px sabit genişlik, bg-surface, border-right
Content:  flex-1, overflow-y: auto
Topbar:   54px sabit yükseklik, sticky, bg-surface
```

**Sidebar navigasyon:**
- Nav item: `8px 18px`, `border-radius: 8px`, `margin: 1px 8px`
- Aktif item: `bg-overlay`, `color-accent`, sol kenarda 2px border yok — sadece bg
- Section label: 9px / uppercase / muted

**Grid (içerik):**
- Gap: `20px`
- Stat/gauge row: `grid-template-columns` responsive

---

## 10. Motion

```css
/* Standart hover */
transition: all 0.12s ease;

/* Renk geçişleri */
transition: background 0.1s, color 0.1s;

/* Canlı indicator */
@keyframes blink { 0%,100%{opacity:1} 50%{opacity:.3} }
```

**Kurallar:**
- `prefers-reduced-motion` için tüm animasyonlar kapatılır
- Sayfa geçişleri animasyonsuz
- Sadece state değişikliği ileten geçişler (hover, focus, loading) kullanılır

---

## 11. Icons

**Kütüphane:** `lucide-react` (zaten kurulu)  
**Boyut:** `16px` nav'da, `18px` action butonlarda  
**Stroke width:** `1.8–2`  
**Kural:** Emoji kullanılmaz, her ikon fonksiyonel anlam taşımalı

---

## 12. Anti-patterns (Yasak)

| ❌ Yasak | ✅ Doğrusu |
|---------|-----------|
| Emoji UI elementleri | Lucide-react SVG ikonlar |
| `purple` / `violet` aksan | `blue-500` / `#3b82f6` |
| `rounded-full` butonlar | `rounded-lg` (8px) |
| Neon glow / border-glow animasyonları | Statik `box-shadow` |
| AI Slop badge'leri (🤖 AI Ready) | `badge-blue` text only |
| "Günaydın" / happy talk | Sistem durumu mesajı |
| Raw API path gösterimi (UI'da) | Kullanıcı dostu label |
| Tüm başlıklar aynı boyut | Type scale kullanımı |

---

## 13. Dashboard Bileşen Mimarisi

```
Dashboard
├── Hero Banner (kritik durum / sistem normal)
│   └── Title (renk: error/success) + 4x metrik
├── Visual Row (grid)
│   ├── Health Gauge SVG
│   ├── Server Status Ring
│   ├── AI Ready Ring
│   └── Monitoring Coverage Ring
├── Chart Row (grid 1fr 1fr)
│   ├── Event Trend Sparkline
│   └── Incident Resolution Sparkline
└── Server Table
    └── Rows: Name/IP · Status badge · CPU bar · OS · Action btn
```

---

*Bu belge `/design-consultation` çıktısıdır. Değişiklikler önce DESIGN.md'de güncellenmeli, sonra koda yansıtılmalıdır.*
