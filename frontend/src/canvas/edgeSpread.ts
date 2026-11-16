/**
 * 같은 두 층 사이를 지나는 꺾은선들은 세로 구간이 한가운데에 겹친다.
 * 세로 구간이 지나는 위치(stepPosition, 0~1)를 선마다 조금씩 다르게 줘서 서로 다른 길로 지나가게 한다.
 */
export interface SpreadItem {
  id: string
  /** 출발점·도착점의 x 좌표 */
  x1: number
  x2: number
  /** 같은 묶음 안에서 순서를 정할 때 쓰는 출발점 y 좌표 (위에서 나가는 선이 왼쪽 길로) */
  y: number
}

const BUCKET = 60

export function spreadSteps(items: SpreadItem[]): Map<string, number> {
  const groups = new Map<string, SpreadItem[]>()
  for (const it of items) {
    const lo = Math.round(Math.min(it.x1, it.x2) / BUCKET)
    const hi = Math.round(Math.max(it.x1, it.x2) / BUCKET)
    const key = `${lo}:${hi}`
    groups.set(key, [...(groups.get(key) ?? []), it])
  }
  const out = new Map<string, number>()
  for (const list of groups.values()) {
    list.sort((a, b) => a.y - b.y)
    const n = list.length
    const step = Math.min(0.14, 0.6 / n)
    list.forEach((it, i) => {
      const t = 0.5 + (i - (n - 1) / 2) * step
      // 오른쪽에서 왼쪽으로 가는 선은 0~1이 반대 방향이므로 뒤집는다
      out.set(it.id, it.x1 <= it.x2 ? t : 1 - t)
    })
  }
  return out
}
