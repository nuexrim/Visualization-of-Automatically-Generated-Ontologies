import { useRef } from 'react'
import { useStore } from '../store'
import { DB_FILE_ACCEPT } from './TopBar'

/** 아직 DB를 불러오지 않았을 때의 캔버스. DB 파일을 고르거나 끌어다 놓으면 ERD가 만들어진다. */
export function EmptyState() {
  const importing = useStore((s) => s.importing)
  const importDb = useStore((s) => s.importDb)
  const input = useRef<HTMLInputElement>(null)

  return (
    <div className="flex h-full items-center justify-center p-8">
      <div className="w-[520px] max-w-full rounded-2xl border-2 border-dashed border-line bg-white px-8 py-10 text-center">
        {importing ? (
          <>
            <span className="spinner text-accent" style={{ width: 22, height: 22, borderWidth: 3 }} />
            <h2 className="mt-4 text-[15px] font-semibold">DB를 읽는 중입니다</h2>
            <p className="mt-1 break-all font-mono text-[12px] text-muted">{importing}</p>
            <p className="mt-3 text-[12px] text-muted">파일을 PostgreSQL에 올리고 테이블·컬럼·외래 키를 읽어 ERD를 만듭니다.</p>
          </>
        ) : (
          <>
            <h2 className="text-[16px] font-semibold">DB 파일을 불러오세요</h2>
            <p className="mt-2 text-[12.5px] leading-relaxed text-slate-600">
              파일을 읽어 테이블, 컬럼, 기본 키, 외래 키를 파악하고 ERD를 그립니다.
              <br />
              그다음 이 DB의 온톨로지를 생성해 그래프로 볼 수 있습니다.
            </p>
            <input
              ref={input}
              type="file"
              accept={DB_FILE_ACCEPT}
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0]
                if (file) void importDb(file)
                e.target.value = ''
              }}
            />
            <button className="mt-5 rounded-lg bg-accent px-5 py-2 text-[13px] font-semibold text-white hover:brightness-110" onClick={() => input.current?.click()}>
              DB 파일 선택
            </button>
            <p className="mt-3 text-[12px] text-muted">또는 파일을 이 화면에 끌어다 놓으세요</p>
            <dl className="mx-auto mt-6 grid w-fit grid-cols-[auto_auto] gap-x-4 gap-y-1 text-left text-[11.5px] text-slate-600">
              <dt className="font-mono">.dump</dt>
              <dd>PostgreSQL 덤프 (pg_dump 사용자 지정 형식)</dd>
              <dt className="font-mono">.sql</dt>
              <dd>PostgreSQL SQL 스크립트</dd>
              <dt className="font-mono">.sqlite / .db</dt>
              <dd>SQLite 파일 (PostgreSQL로 옮겨서 읽음)</dd>
            </dl>
          </>
        )}
      </div>
    </div>
  )
}
