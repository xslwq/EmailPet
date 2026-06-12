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
