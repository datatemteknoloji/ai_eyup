"""GZip ara katmanı — akış (SSE) yanıtlarını SIKIŞTIRMAZ.

Neden: Starlette `GZipMiddleware` akış yanıtında her parçayı `gzip_file.write()` ile yazar ama `flush()` etmez;
zlib çıktıyı iç tamponda tutar → tarayıcı (`Accept-Encoding: gzip` gönderir) token'ları DAKİKALARCA görmez,
hepsi cevap bitince birden gelir. `curl` (gzip istemez) akışı doğru görür, bu yüzden hata geç fark edildi.
`text/event-stream` (ve ndjson) yanıtları sıkıştırılmadan geçirilir; diğer yanıtlar eskisi gibi sıkıştırılır (Adım 14).
"""
from __future__ import annotations

from starlette.datastructures import Headers
from starlette.middleware.gzip import GZipMiddleware, GZipResponder
from starlette.types import Message, Receive, Scope, Send

_PASSTHROUGH_TYPES = ("text/event-stream", "application/x-ndjson")


class _SSEAwareResponder(GZipResponder):
    async def send_with_gzip(self, message: Message) -> None:
        if message["type"] == "http.response.start":
            ct = (Headers(raw=message["headers"]).get("content-type") or "").lower()
            if ct.startswith(_PASSTHROUGH_TYPES):
                self.initial_message = message
                self.content_encoding_set = True   # üst sınıfta 'zaten kodlanmış' yolu = olduğu gibi geçir
                return
        await super().send_with_gzip(message)


class SSEAwareGZipMiddleware(GZipMiddleware):
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and "gzip" in Headers(scope=scope).get("Accept-Encoding", ""):
            responder = _SSEAwareResponder(self.app, self.minimum_size, compresslevel=self.compresslevel)
            await responder(scope, receive, send)
            return
        await self.app(scope, receive, send)
