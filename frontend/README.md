# EmailPet Frontend

Electron + React + TypeScript + Vite scaffolding for the EmailPet desktop pet UI.

## Install

```bash
npm install
```

## Develop (renderer only, in browser)

```bash
npm run dev
```

## Build (renderer)

```bash
npm run build
```

## Launch Electron app (dev)

```bash
npm run electron:dev
```

This builds the renderer and launches Electron pointing at the built bundle.

## Layout

- `electron/` — Electron main + preload sources
- `src/` — React renderer sources
  - `components/` — UI components (added in Task 3-x)
  - `hooks/` — React hooks (added in Task 3-x)
  - `store/` — Zustand stores (added in Task 3-x)
- `assets/pet/` — pet sprite assets
