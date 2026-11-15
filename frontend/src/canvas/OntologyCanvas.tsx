import { Background, BackgroundVariant, Controls, MarkerType, MiniMap, ReactFlow, ReactFlowProvider, useNodesState, type Edge } from '@xyflow/react'
import { useCallback, useMemo } from 'react'
import { useOntologyIndex } from '../links'
import { useCanvasHighlight } from '../trace'
import { useTraceCamera } from './useTraceCamera'
import { PREVIEW, shownOntology, useStore } from '../store'
import type { Ontology } from '../types'
import { CLASS_WIDTH, ClassNode, classNodeHeight, inHandle, outHandle, type ClassNodeType } from './ClassNode'
import type { Positions } from './layout'
import { useCanvasLayout } from './useCanvasLayout'

const nodeTypes = { class: ClassNode }
const ONTO = '#0f766e'
const EDGE = '#8aa5a1'
const SUB = '#7c3aed'

function Canvas({ db, ontology }: { db: string; ontology: Ontology }) {
  const select = useStore((s) => s.select)
  const hl = useCanvasHighlight()
  const idx = useOntologyIndex()
  const [nodes, setNodes, onNodesChange] = useNodesState<ClassNodeType>([])
  const preview = ontology.filename === PREVIEW

  // 클래스마다 나가는 객체 속성 목록 (선의 출발 위치를 정하는 데 쓴다)
  const outgoing = useMemo(() => {
    const m = new Map<string, string[]>()
    for (const p of ontology.object_properties) for (const d of p.domains) m.set(d, [...(m.get(d) ?? []), p.iri])
    return m
  }, [ontology])

  const propsOf = useCallback((iri: string) => idx?.dataPropsByClass.get(iri) ?? [], [idx])

  const build = useCallback(
    (positions: Positions): ClassNodeType[] =>
      ontology.classes.map((c) => ({
        id: c.iri,
        type: 'class',
        className: 'node-enter',
        position: positions[c.iri] ?? { x: 0, y: 0 },
        width: CLASS_WIDTH,
        height: classNodeHeight(c, propsOf(c.iri).length),
        data: { cls: c, dataProps: propsOf(c.iri), outgoing: outgoing.get(c.iri)?.length ?? 0, dimmed: false, glow: false, hlProps: [] },
      })),
    [ontology, outgoing, propsOf],
  )

  const links = useMemo(() => {
    const out: [string, string][] = []
    for (const p of ontology.object_properties) for (const d of p.domains) for (const r of p.ranges) out.push([d, r])
    for (const c of ontology.classes) for (const parent of c.parents) out.push([c.iri, parent])
    return out
  }, [ontology])

  const { onNodeDragStop } = useCanvasLayout({
    scope: preview ? 'gen' : 'onto',
    db,
    // 생성 중에는 클래스가 늘어날 때마다 다시 배치한다
    contentKey: `${db}/${ontology.filename}/${preview ? ontology.classes.length : ''}`,
    layoutNodes: useMemo(() => ontology.classes.map((c) => ({ id: c.iri, width: CLASS_WIDTH, height: classNodeHeight(c, propsOf(c.iri).length) })), [ontology, propsOf]),
    links,
    layerGap: 220,
    build,
    setNodes,
  })

  // 또렷하게 보일 클래스: 강조된 것 + (클래스 하나를 골랐으면) 관계로 이어진 이웃
  const visible = useMemo(() => {
    // 대응하는 클래스가 없는 선택(예: 아직 클래스가 안 만들어진 테이블)이면 흐리게 하지 않는다
    if (!hl.active || (hl.classes.size === 0 && hl.props.size === 0)) return null
    const set = new Set(hl.classes)
    if (hl.focusClass) {
      for (const p of ontology.object_properties) {
        if (p.domains.includes(hl.focusClass)) p.ranges.forEach((r) => set.add(r))
        if (p.ranges.includes(hl.focusClass)) p.domains.forEach((d) => set.add(d))
      }
      for (const c of ontology.classes) {
        if (c.iri === hl.focusClass) c.parents.forEach((x) => set.add(x))
        if (c.parents.includes(hl.focusClass)) set.add(c.iri)
      }
    }
    return set
  }, [hl, ontology])

  const shownNodes = useMemo(
    () =>
      nodes.map((n) => ({
        ...n,
        selected: hl.classes.has(n.id),
        data: { ...n.data, dimmed: visible ? !visible.has(n.id) : false, glow: hl.now?.classes.has(n.id) ?? false, hlProps: n.data.dataProps.filter((p) => hl.props.has(p.iri)).map((p) => p.iri) },
      })),
    [nodes, hl, visible],
  )

  const edges = useMemo<Edge[]>(() => {
    const centerX = new Map(nodes.map((n) => [n.id, n.position.x + CLASS_WIDTH / 2]))
    const out: Edge[] = []
    const label = { fontSize: 10, fontFamily: 'ui-monospace, Menlo, monospace' }
    const labelBg = { labelBgPadding: [4, 2] as [number, number], labelBgBorderRadius: 3, labelBgStyle: { fill: '#f4f6f9', fillOpacity: 0.92 } }

    // 객체 속성: 도메인 → 범위
    for (const p of ontology.object_properties) {
      for (const d of p.domains) {
        const i = outgoing.get(d)?.indexOf(p.iri) ?? 0
        for (const r of p.ranges) {
          if (!centerX.has(d) || !centerX.has(r)) continue
          const leftToRight = (centerX.get(d) ?? 0) <= (centerX.get(r) ?? 0)
          const active = hl.props.has(p.iri) || (hl.focusClass !== null && (hl.focusClass === d || hl.focusClass === r))
          const faded = visible !== null && !active
          const color = active ? ONTO : EDGE
          // 지금 단계에서 따라간 관계: 순서대로 흐르는 애니메이션
          const order = hl.now?.props.has(p.iri) ? hl.propOrder?.get(p.iri) : undefined
          out.push({
            id: `op:${p.iri}:${d}:${r}`,
            source: d,
            target: r,
            sourceHandle: outHandle(leftToRight ? 'r' : 'l', i),
            targetHandle: inHandle(leftToRight ? 'l' : 'r'),
            type: 'smoothstep',
            data: { kind: 'objprop', iri: p.iri },
            label: faded ? undefined : p.name,
            labelStyle: { ...label, fill: active ? ONTO : '#4b635f' },
            ...labelBg,
            markerEnd: { type: MarkerType.ArrowClosed, color, width: 16, height: 16 },
            animated: order !== undefined,
            className: order !== undefined ? 'trace-edge' : undefined,
            style: { stroke: color, strokeWidth: order !== undefined ? 2.75 : active ? 2 : 1.25, opacity: faded ? 0.15 : 1, cursor: 'pointer', ...(order !== undefined ? { animationDelay: `${order * 0.35}s` } : {}) },
            zIndex: active ? 10 : 0,
            interactionWidth: 14,
            focusable: false,
          })
        }
      }
    }
    // 상위 클래스 관계: 점선
    for (const c of ontology.classes) {
      for (const parent of c.parents) {
        if (!centerX.has(parent)) continue
        const active = hl.focusClass === c.iri || hl.focusClass === parent
        const faded = visible !== null && !active
        out.push({
          id: `sub:${c.iri}:${parent}`,
          source: c.iri,
          target: parent,
          sourceHandle: 'sub:out',
          targetHandle: 'sub:in',
          type: 'default',
          label: faded ? undefined : 'subClassOf',
          labelStyle: { ...label, fill: SUB },
          ...labelBg,
          markerEnd: { type: MarkerType.Arrow, color: SUB, width: 18, height: 18 },
          style: { stroke: SUB, strokeWidth: active ? 2 : 1.25, strokeDasharray: '6 4', opacity: faded ? 0.15 : 1 },
          selectable: false,
          focusable: false,
        })
      }
    }
    return out
  }, [nodes, ontology, outgoing, hl, visible])

  const traceIds = useMemo(() => [...(hl.now?.classes ?? [])].filter((c) => nodes.some((n) => n.id === c)), [hl, nodes])
  const onMoveStart = useTraceCamera(traceIds)

  return (
    <ReactFlow
      className={preview ? 'gen-anim' : undefined}
      onMoveStart={onMoveStart}
      nodes={shownNodes}
      edges={edges}
      nodeTypes={nodeTypes}
      onNodesChange={onNodesChange}
      onNodeClick={(_, n) => select({ kind: 'class', iri: n.id })}
      onEdgeClick={(_, e) => {
        const d = e.data as { kind: 'objprop'; iri: string } | undefined
        if (d) select(d)
      }}
      onPaneClick={() => select(null)}
      onNodeDragStop={onNodeDragStop}
      nodesConnectable={false}
      minZoom={0.03}
      maxZoom={2.5}
      proOptions={{ hideAttribution: true }}
    >
      <Background variant={BackgroundVariant.Dots} gap={24} size={1.2} color="#c5d6d3" />
      <Controls showInteractive={false} position="bottom-left" />
      <MiniMap pannable zoomable position="bottom-right" nodeColor={(n) => (hl.classes.has(n.id) ? ONTO : '#5f8f89')} nodeStrokeWidth={0} maskColor="rgba(244,246,249,0.7)" />
    </ReactFlow>
  )
}

export function OntologyCanvas() {
  const db = useStore((s) => s.db)
  const ontology = useStore(shownOntology)
  const generating = useStore((s) => s.gen !== null)
  if (!db || !ontology) {
    return <div className="flex h-full items-center justify-center px-6 text-center text-muted">{generating ? '첫 테이블을 처리하는 중입니다. 완성된 클래스가 여기에 하나씩 나타납니다.' : '불러온 온톨로지가 없습니다'}</div>
  }
  return (
    <ReactFlowProvider key={`${db}/${ontology.filename}`}>
      <Canvas db={db} ontology={ontology} />
    </ReactFlowProvider>
  )
}
