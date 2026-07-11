/**
 * Electron API 类型声明
 * 职责：为 preload 暴露的 API 提供 TypeScript 类型支持
 */
export {}

declare global {
  interface Window {
    electronAPI?: {
      dragStart: (x: number, y: number) => void
      dragMove: (x: number, y: number) => void
      dragEnd: () => void
    }
  }
}
