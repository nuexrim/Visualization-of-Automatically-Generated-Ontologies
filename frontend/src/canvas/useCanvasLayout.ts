import { useNodesInitialized, useReactFlow, useStore as useFlowStore, type Node } from '@xyflow/react'
import { useCallback, useEffect, useRef, type Dispatch, type SetStateAction } from 'react'
import { useStore } from '../store'
import { autoLayout, loadPositions, savePositions, type LayoutNode, type Positions } from './layout'

interface Args<N extends Node> {
  /** 위치 저장 구분. 'gen'(생성 중 미리보기)은 저장하지 않는다 */
  scope: 'erd' | 'onto' | 'gen'
  db: string
  /** 내용이 바뀌면 다시 배치·복원한다 (예: DB 이름, 온톨로지 파일 이름) */
  contentKey: string
  layoutNodes: LayoutNode[]
  links: [string, string][]
  layerGap?: number
  build: (positions: Positions) => N[]
  setNodes: Dispatch<SetStateAction<N[]>>
}

/** 저장된 위치 복원 / 자동 배치 / 화면에 맞추기 / 드래그 후 저장 — 두 캔버스가 함께 쓴다. */
export function useCanvasLayout<N extends Node>({ scope, db, contentKey, layoutNodes, links, layerGap, build, setNodes }: Args<N>) {
  const { fitView } = useReactFlow()
  const fitSignal = useStore((s) => s.fitSignal)
  const relayoutSignal = useStore((s) => s.relayoutSignal)
  const latest = useRef({ layoutNodes, links, build })
  latest.current = { layoutNodes, links, build }

  // 노드 크기가 측정된 뒤에만 맞춘다 (그 전에 부르면 뷰포트가 NaN이 된다)
  const initialized = useNodesInitialized()
  const fitSoon = useCallback(() => {
    window.setTimeout(() => void fitView({ padding: 0.12, duration: 300 }), 60)
  }, [fitView])
  // 캔버스 크기가 바뀌어도(보기 전환, 창 크기 조절) 다시 맞춘다
  const paneWidth = useFlowStore((s) => s.width)
  const paneHeight = useFlowStore((s) => s.height)
  useEffect(() => {
    if (initialized && paneWidth > 0 && paneHeight > 0) void fitView({ padding: 0.12 })
  }, [initialized, fitView, contentKey, paneWidth, paneHeight])

  useEffect(() => {
    let cancelled = false
    const { layoutNodes, links, build } = latest.current
    const saved = scope === 'gen' ? null : loadPositions(scope, db, layoutNodes.map((n) => n.id))
    void (saved ? Promise.resolve(saved) : autoLayout(layoutNodes, links, layerGap)).then((positions) => {
      if (cancelled) return
      setNodes(build(positions))
      if (scope === 'gen') window.setTimeout(() => void fitView({ padding: 0.15, duration: 400 }), 120)
      else if (!saved) savePositions(scope, db, positions)
    })
    return () => {
      cancelled = true
    }
  }, [scope, db, contentKey, layerGap, setNodes, fitView])

  // "자동 배치" 버튼
  const seenRelayout = useRef(relayoutSignal)
  useEffect(() => {
    if (relayoutSignal === seenRelayout.current) return
    seenRelayout.current = relayoutSignal
    const { layoutNodes, links } = latest.current
    void autoLayout(layoutNodes, links, layerGap).then((positions) => {
      setNodes((ns) => ns.map((n) => ({ ...n, position: positions[n.id] ?? n.position })))
      if (scope !== 'gen') savePositions(scope, db, positions)
      fitSoon()
    })
  }, [relayoutSignal, scope, db, layerGap, setNodes, fitSoon])

  // "화면에 맞추기" 버튼
  const seenFit = useRef(fitSignal)
  useEffect(() => {
    if (fitSignal === seenFit.current) return
    seenFit.current = fitSignal
    fitSoon()
  }, [fitSignal, fitSoon])

  // 드래그가 끝난 시점의 최신 위치를 저장한다
  const onNodeDragStop = useCallback(() => {
    if (scope === 'gen') return
    setNodes((ns) => {
      savePositions(scope, db, Object.fromEntries(ns.map((n) => [n.id, n.position])))
      return ns
    })
  }, [scope, db, setNodes])

  return { onNodeDragStop }
}
