import { useReactFlow, useStore as useFlowStore } from '@xyflow/react'
import { useCallback, useEffect } from 'react'
import { useStore } from '../store'
import { useCursor } from '../trace'

/**
 * 질의 경로 재생 중 강조된 노드가 화면에 들어오도록 맞춘다.
 * 사용자가 직접 화면을 움직이면(onMoveStart 에 event 가 있음) 자동 맞춤을 끈다.
 */
export function useTraceCamera(ids: string[]) {
  const { fitView } = useReactFlow()
  const camera = useStore((s) => s.trace.camera && s.trace.show)
  const selecting = useStore((s) => s.selection !== null)
  const setTrace = useStore((s) => s.setTrace)
  const cursor = useCursor()
  const width = useFlowStore((s) => s.width)
  const height = useFlowStore((s) => s.height)
  const key = ids.join('|')

  useEffect(() => {
    if (!camera || selecting || cursor === null || !key || width === 0 || height === 0) return
    // 레이아웃 쪽의 "화면에 맞추기"(창 크기 변경 시)보다 나중에 실행되게 조금 늦춘다
    const t = window.setTimeout(() => void fitView({ nodes: key.split('|').map((id) => ({ id })), padding: 0.25, maxZoom: 1, duration: 500 }), 120)
    return () => window.clearTimeout(t)
  }, [camera, selecting, cursor, key, width, height, fitView])

  return useCallback(
    (event: MouseEvent | TouchEvent | null) => {
      if (event && camera) setTrace({ camera: false })
    },
    [camera, setTrace],
  )
}
