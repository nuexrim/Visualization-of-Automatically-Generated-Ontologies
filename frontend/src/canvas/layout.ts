import ELK from 'elkjs/lib/elk.bundled.js'
import type { Table } from '../types'

export const NODE_WIDTH = 280
export const HEADER_HEIGHT = 36
export const ROW_HEIGHT = 24

export type Positions = Record<string, { x: number; y: number }>

export const nodeHeight = (t: Table) => HEADER_HEIGHT + t.columns.length * ROW_HEIGHT + 2

const elk = new ELK()

export interface LayoutNode {
  id: string
  width: number
  height: number
}

/** 선의 방향(출발 → 도착)을 따라 왼쪽에서 오른쪽으로 층을 나눠 겹치지 않게 배치한다. */
export async function autoLayout(nodes: LayoutNode[], links: [string, string][], layerGap = 260): Promise<Positions> {
  const ids = new Set(nodes.map((n) => n.id))
  const seen = new Set<string>()
  const edges = []
  for (const [from, to] of links) {
    const key = `${from}->${to}`
    if (from === to || seen.has(key) || !ids.has(from) || !ids.has(to)) continue
    seen.add(key)
    edges.push({ id: key, sources: [from], targets: [to] })
  }
  const graph = await elk.layout({
    id: 'root',
    layoutOptions: {
      'elk.algorithm': 'layered',
      'elk.direction': 'RIGHT',
      'elk.layered.spacing.nodeNodeBetweenLayers': String(layerGap), // 선 라벨이 들어갈 자리
      'elk.spacing.nodeNode': '48',
      'elk.spacing.componentComponent': '120',
      'elk.layered.nodePlacement.strategy': 'NETWORK_SIMPLEX',
      'elk.layered.crossingMinimization.strategy': 'LAYER_SWEEP',
    },
    children: nodes.map((n) => ({ ...n })),
    edges,
  })
  const out: Positions = {}
  for (const n of graph.children ?? []) out[n.id] = { x: n.x ?? 0, y: n.y ?? 0 }
  return out
}

/** scope: 'erd' | 'onto' — 보기마다, DB마다 위치를 따로 저장한다. */
const key = (scope: string, db: string) => `ontolens:${scope}-positions:${db}`

export function loadPositions(scope: string, db: string, ids: string[]): Positions | null {
  try {
    const saved = JSON.parse(localStorage.getItem(key(scope, db)) ?? 'null') as Positions | null
    if (saved && ids.every((t) => saved[t] && Number.isFinite(saved[t].x) && Number.isFinite(saved[t].y))) return saved
  } catch {
    /* 저장된 값이 깨졌으면 자동 배치로 돌아간다 */
  }
  return null
}

export function savePositions(scope: string, db: string, positions: Positions) {
  try {
    localStorage.setItem(key(scope, db), JSON.stringify(positions))
  } catch {
    /* 저장 실패는 화면 동작에 영향이 없다 */
  }
}
