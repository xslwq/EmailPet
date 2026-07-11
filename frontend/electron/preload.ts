/**
 * Electron Preload 脚本
 * 职责：通过 contextBridge 安全地向渲染进程暴露主进程 API
 */
import { contextBridge, ipcRenderer } from 'electron'

// 向渲染进程暴露拖拽相关 API
contextBridge.exposeInMainWorld('electronAPI', {
  dragStart: (x: number, y: number) => ipcRenderer.send('drag-start', { x, y }),
  dragMove: (x: number, y: number) => ipcRenderer.send('drag-move', { x, y }),
  dragEnd: () => ipcRenderer.send('drag-end'),
})
