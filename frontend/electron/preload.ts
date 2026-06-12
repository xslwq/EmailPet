import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('electronAPI', {
  dragStart: (x: number, y: number) => ipcRenderer.send('drag-start', { x, y }),
  dragMove: (x: number, y: number) => ipcRenderer.send('drag-move', { x, y }),
  dragEnd: () => ipcRenderer.send('drag-end'),
})
