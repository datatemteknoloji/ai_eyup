/// <reference types="vite/client" />

declare module '@novnc/novnc' {
  export default class RFB {
    constructor(
      target: HTMLElement,
      url: string,
      options?: { wsProtocols?: string[]; credentials?: { password?: string } },
    )
    scaleViewport: boolean
    background: string
    disconnect(): void
    sendCtrlAltDel(): void
    addEventListener(type: string, listener: (e: Event) => void): void
  }
}
