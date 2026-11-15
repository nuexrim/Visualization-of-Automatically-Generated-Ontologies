import type { ChatEvent, ResultTable } from '../types'

function Table({ table }: { table: ResultTable }) {
  return (
    <div className="max-h-full overflow-auto rounded-lg border border-line">
      <table className="w-full border-collapse text-[11.5px]">
        <thead className="sticky top-0 bg-slate-100">
          <tr>
            {table.columns.map((c, i) => (
              <th key={i} className="whitespace-nowrap border-b border-line px-2.5 py-1.5 text-left font-mono font-semibold">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.map((row, r) => (
            <tr key={r} className="odd:bg-white even:bg-slate-50/60">
              {row.map((v, c) => (
                <td key={c} className={`whitespace-nowrap border-b border-slate-100 px-2.5 py-1 ${typeof v === 'number' ? 'text-right font-mono tabular-nums' : ''} ${v === null ? 'text-slate-400' : ''}`}>
                  {v === null ? 'NULL' : String(v)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** 최종 답변, 마지막으로 실행한 SQL, 결과 표(최대 50행). */
export function ResultView({ events, running }: { events: ChatEvent[]; running: boolean }) {
  const answer = events.find((e): e is Extract<ChatEvent, { type: 'answer' }> => e.type === 'answer')
  if (!answer) {
    return <div className="flex h-full items-center justify-center text-[12px] text-muted">{running ? '에이전트가 실행 중입니다. 끝나면 답변과 결과 표가 여기에 나옵니다.' : '아직 답변이 없습니다.'}</div>
  }
  return (
    <div className="flex h-full min-h-0 flex-col gap-2.5">
      <section>
        <h3 className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted">답변</h3>
        <p className="whitespace-pre-wrap text-[13px] leading-relaxed">{answer.text || '(모델이 답변 문장을 내놓지 않았습니다)'}</p>
        {!answer.searched_ontology && <p className="mt-1 text-[11.5px] text-amber-700">온톨로지 검색이 한 번도 성공하지 않아 SQL은 실행되지 않았습니다.</p>}
      </section>
      {answer.final_sql && (
        <section>
          <h3 className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted">최종 SQL</h3>
          <pre className="overflow-x-auto whitespace-pre-wrap break-words rounded-lg bg-slate-900 p-2.5 font-mono text-[11px] leading-snug text-slate-100">{answer.final_sql}</pre>
        </section>
      )}
      {answer.table ? (
        <section className="flex min-h-0 flex-1 flex-col">
          <h3 className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted">
            결과 표 · {answer.table.rows.length}행{answer.table.truncated ? ' (50행까지만 표시)' : ''}
          </h3>
          <div className="min-h-0 flex-1">
            <Table table={answer.table} />
          </div>
        </section>
      ) : (
        answer.final_sql && <p className="text-[11.5px] text-amber-700">마지막 SQL이 오류로 끝나 결과 표가 없습니다.</p>
      )}
    </div>
  )
}
