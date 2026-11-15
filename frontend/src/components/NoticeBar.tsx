import { useStore } from '../store'

/** 생성·업로드 결과와 오류를 캔버스 위에 띄운다. 생성한 파일은 여기서 바로 불러올 수 있다. */
export function NoticeBar() {
  const notice = useStore((s) => s.notice)
  const setNotice = useStore((s) => s.setNotice)
  const loadFile = useStore((s) => s.loadFile)
  if (!notice) return null
  const error = notice.kind === 'error'
  return (
    <div className="pointer-events-none absolute inset-x-0 top-3 z-20 flex justify-center px-4">
      <div role="status" className={`pointer-events-auto flex max-w-full items-center gap-3 rounded-lg border px-3.5 py-2 text-[12px] shadow-lg ${error ? 'border-red-300 bg-red-50 text-red-800' : 'border-onto/40 bg-white'}`}>
        <span className="min-w-0 break-words">{notice.text}</span>
        {notice.file && !error && (
          <button className="shrink-0 rounded-md bg-onto px-2.5 py-1 font-medium text-white hover:brightness-110" onClick={() => void loadFile(notice.file!)}>
            이 파일 불러오기
          </button>
        )}
        <button className="shrink-0 rounded px-1.5 text-muted hover:bg-slate-100" aria-label="닫기" onClick={() => setNotice(null)}>
          ✕
        </button>
      </div>
    </div>
  )
}
