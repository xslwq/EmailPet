/**
 * Electron 主进程
 * 职责：创建窗口、启动 Python 后端、处理窗口拖拽、后端崩溃重启
 */
import { app, BrowserWindow, dialog, ipcMain, Menu } from 'electron'
import { spawn, type ChildProcess } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

// ESM 兼容的 __dirname
const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

let mainWindow: BrowserWindow | null = null
let pythonProcess: ChildProcess | null = null
let crashCount = 0
let intentionalQuit = false

/**
 * 创建应用窗口
 * WSLg 下 transparent 窗口经常完全不可见；用 frame=false + 不透明背景做"圆角浮窗"效果
 */
function createWindow() {
  const useTransparent = process.platform === 'darwin' || process.env.EMAILPET_TRANSPARENT === '1'
  mainWindow = new BrowserWindow({
    width: 380,
    height: 500,
    frame: false,
    transparent: useTransparent,
    backgroundColor: useTransparent ? undefined : '#ffffff',
    alwaysOnTop: true,
    resizable: false,
    skipTaskbar: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  })

  if (process.env.VITE_DEV_SERVER_URL) {
    mainWindow.loadURL(process.env.VITE_DEV_SERVER_URL)
  } else {
    mainWindow.loadFile(path.join(__dirname, '../dist/index.html'))
  }

  // 拖拽处理：渲染进程报告鼠标位置，主进程移动窗口
  let dragging = false
  let dragStartScreenPos = { x: 0, y: 0 }
  let dragStartWindowPos: [number, number] = [0, 0]

  ipcMain.on('drag-start', (_e, pos: { x: number; y: number }) => {
    if (!mainWindow) return
    dragging = true
    dragStartScreenPos = pos
    dragStartWindowPos = mainWindow.getPosition() as [number, number]
  })
  ipcMain.on('drag-move', (_e, pos: { x: number; y: number }) => {
    if (!dragging || !mainWindow) return
    const dx = pos.x - dragStartScreenPos.x
    const dy = pos.y - dragStartScreenPos.y
    mainWindow.setPosition(
      dragStartWindowPos[0] + dx,
      dragStartWindowPos[1] + dy,
    )
  })
  ipcMain.on('drag-end', () => {
    dragging = false
  })

  // 右键菜单
  mainWindow.webContents.on('context-menu', () => {
    const menu = Menu.buildFromTemplate([
      {
        label: '退出',
        click: () => {
          intentionalQuit = true
          app.quit()
        },
      },
    ])
    if (mainWindow) menu.popup({ window: mainWindow })
  })
}

/**
 * 启动 Python 后端
 * 支持后端崩溃自动重启，连续崩溃 3 次后停止并提示用户
 */
function startPythonBackend() {
  const backendCwd = path.resolve(__dirname, '../../backend')
  const command =
    process.platform === 'win32'
      ? path.join(backendCwd, '.venv', 'Scripts', 'python.exe')
      : path.join(backendCwd, '.venv', 'bin', 'python')

  pythonProcess = spawn(command, ['-m', 'emailpet.main'], {
    cwd: backendCwd,
    stdio: ['ignore', 'pipe', 'pipe'],
  })
  pythonProcess.stdout?.on('data', (d) => process.stdout.write(`[backend] ${d}`))
  pythonProcess.stderr?.on('data', (d) => process.stderr.write(`[backend ERR] ${d}`))
  pythonProcess.on('exit', (code, signal) => {
    pythonProcess = null
    if (intentionalQuit) return
    crashCount += 1
    console.warn(
      `python backend exited (code=${code}, signal=${signal}); crash #${crashCount}`,
    )
    if (crashCount >= 3) {
      dialog.showErrorBox(
        'EmailPet 后端连续崩溃',
        '后端连续崩溃 3 次，已停止重启。请检查 config.yaml 是否正确，或查看日志。',
      )
      intentionalQuit = true
      app.quit()
      return
    }
    setTimeout(startPythonBackend, 2000)
  })
}

app.whenReady().then(() => {
  // 开发模式下设置 EMAILPET_NO_SPAWN=1 可跳过自动启动后端（手动运行后端）
  if (!process.env.EMAILPET_NO_SPAWN) {
    startPythonBackend()
  }
  createWindow()
})

app.on('window-all-closed', () => {
  intentionalQuit = true
  if (pythonProcess) {
    pythonProcess.kill()
    pythonProcess = null
  }
  if (process.platform !== 'darwin') app.quit()
})

app.on('before-quit', () => {
  intentionalQuit = true
  if (pythonProcess) {
    pythonProcess.kill()
    pythonProcess = null
  }
})
