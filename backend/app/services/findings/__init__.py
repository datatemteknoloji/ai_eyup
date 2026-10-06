"""Ortak kontrol → bulgu → kanıt motoru (sanallaştırma karar katmanı).

registry : kontrol kataloğu (başlık, önem, öneri, uyum referansı)
store    : bulgu upsert / çözüldü işaretleme / istisna / config snapshot
runner   : platform başına toplama + değerlendirme turu (fleet job)
collectors/ : vCenter, OLVM Manager, OCP Virt (kube API) salt-okunur toplayıcılar
"""
