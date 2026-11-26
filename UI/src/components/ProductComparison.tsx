import { useEffect, useRef, useState, type ReactNode } from 'react'
import { runMultiPhotoChecks } from './multiPhotoWorkflow'
import './ProductComparison.css'

type Photo = { file: File; url: string }
type Check = {
  feature: string; label: string; status: 'similar' | 'difference' | 'unobservable'
  observationA: string; observationB: string; explanation: string; nextPhoto: string
}
type Pair = {
  photoA: number; photoB: number; status: string; differenceCount: number
  unobservableCount: number; checks: Check[]
}
type Result = {
  pairs: Pair[]; duplicatePairs: number[][]; provider: string; model: string
  differenceCount: number; limitation: string
}
const statusLabels = { similar: '유사하게 보임', difference: '차이 확인 필요', unobservable: '비교 어려움' }

export type PhotoAnalysisOutcome = { content: ReactNode; fakePercent: number; verdictLabel: string }
type PhotoJob = { status: 'queued' | 'running' | 'success' | 'error'; result?: PhotoAnalysisOutcome; message?: string }

export default function ProductComparison({ combined = false, analyzePhoto, onBusyChange, analysisControls }: {
  combined?: boolean
  analyzePhoto?: (file: File, previewUrl: string, signal: AbortSignal) => Promise<PhotoAnalysisOutcome>
  onBusyChange?: (busy: boolean) => void
  analysisControls?: ReactNode
}) {
  const [photos, setPhotos] = useState<Photo[]>([])
  const [consent, setConsent] = useState(false)
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<Result | null>(null)
  const [error, setError] = useState('')
  const [photoJobs, setPhotoJobs] = useState<PhotoJob[]>([])
  const [phase, setPhase] = useState('')
  useEffect(() => { setConsent(false) }, [combined])
  const inputRef = useRef<HTMLInputElement>(null)
  const photosRef = useRef<Photo[]>([])
  const requestRef = useRef<AbortController | null>(null)
  useEffect(() => () => {
    requestRef.current?.abort()
    photosRef.current.forEach(p => URL.revokeObjectURL(p.url))
  }, [])

  const replacePhotos = (next: Photo[]) => {
    photosRef.current.filter(p => !next.includes(p)).forEach(p => URL.revokeObjectURL(p.url))
    photosRef.current = next
    setPhotos(next)
    setResult(null)
    setError('')
    setPhotoJobs([])
    setPhase('')
  }

  const addFiles = (files: FileList | null) => {
    if (!files || busy) return
    const selected = Array.from(files)
    if (photos.length + selected.length > 3) { setError('사진은 최대 3장까지 선택할 수 있습니다.'); return }
    if (selected.some(f => !['image/jpeg', 'image/png', 'image/webp'].includes(f.type) || f.size > 10 * 1024 * 1024 || f.size === 0)) {
      setError('JPG, PNG, WEBP 사진을 장당 10MB 이하로 선택해주세요.'); return
    }
    replacePhotos([...photos, ...selected.map(file => ({ file, url: URL.createObjectURL(file) }))])
  }

  const compare = async () => {
    if (photos.length < 2 || !consent || busy) return
    const controller = new AbortController()
    requestRef.current = controller
    setBusy(true); onBusyChange?.(true); setError(''); setResult(null)
    setPhotoJobs(combined ? photos.map(() => ({ status: 'queued' })) : [])
    let failures = 0
    const timeout = window.setTimeout(() => controller.abort(), combined ? 20 * 60 * 1000 : 115000)
    try {
      await runMultiPhotoChecks<Result, PhotoAnalysisOutcome>({
        count: combined ? photos.length : 0,
        signal: controller.signal,
        compare: async () => {
          const data = new FormData()
          photos.forEach(p => data.append('photos', p.file))
          data.append('consent', 'true')
          const response = await fetch('/api/compare-products', { method: 'POST', body: data, signal: controller.signal })
          const payload = await response.json()
          if (!response.ok || !payload.ok || !payload.comparison) throw new Error(payload.message || '상품 사진 비교에 실패했습니다.')
          return payload.comparison as Result
        },
        analyze: async index => {
          if (!analyzePhoto) throw new Error('사진 분석 기능이 연결되지 않았습니다.')
          return analyzePhoto(photos[index].file, photos[index].url, controller.signal)
        },
        onPhase: (kind, index) => {
          setPhase(kind === 'comparison' ? '상품 사진의 특징을 비교하고 있습니다.' : `사진 ${(index ?? 0) + 1}/${photos.length}의 AI 생성 가능성을 확인하고 있습니다.`)
          if (kind === 'photo') setPhotoJobs(rows => rows.map((row, i) => i === index ? { status: 'running' } : row))
        },
        onComparison: outcome => {
          if (outcome.status === 'success') setResult(outcome.value)
          else { failures++; setError('상품 사진 비교: ' + outcome.message) }
        },
        onPhoto: (index, outcome) => {
          if (outcome.status === 'error') failures++
          setPhotoJobs(rows => rows.map((row, i) => i === index
            ? outcome.status === 'success' ? { status: 'success', result: outcome.value } : { status: 'error', message: outcome.message }
            : row))
        },
      })
      setPhase(controller.signal.aborted ? '시간이 초과되었거나 요청이 중단되었습니다. 완료된 결과는 아래에 남아 있습니다.'
        : failures ? '일부 확인에 실패했습니다. 성공한 결과와 실패한 항목을 나눠 확인해주세요.' : '확인이 완료되었습니다.')
      if (controller.signal.aborted) setPhotoJobs(rows => rows.map(row => row.status === 'queued' || row.status === 'running' ? { status: 'error', message: '완료되지 않은 요청입니다. 다시 시도해주세요.' } : row))
    } catch (e) {
      setError(e instanceof Error ? e.message : '확인 중 오류가 발생했습니다.')
    } finally {
      window.clearTimeout(timeout)
      requestRef.current = null
      setBusy(false); onBusyChange?.(false)
    }
  }

  return <section className="product-comparison" aria-labelledby="product-comparison-title">
    <div className="comparison-heading">
      <div><span className="eyebrow">판매 사진 함께 확인하기</span><h2 id="product-comparison-title">사진 선택</h2></div>
      <span className="comparison-count">{photos.length} / 3장</span>
    </div>
    <p>{combined ? '사진 2~3장을 한 번 올리면 사진마다 AI 생성 가능성을 분석하고, 사진 사이 상품 특징도 비교합니다. 두 결과는 각각 표시합니다.' : '같은 판매글의 사진 2~3장을 올려 색상·형태·로고·구성품·흠집을 비교해보세요. 전체 사진과 같은 부위를 찍은 확대 사진을 함께 올리면 도움이 됩니다.'}</p>
    {combined && <fieldset className="combined-analysis-settings" disabled={busy}><legend>사진별 AI 분석 방식</legend>{analysisControls}</fieldset>}
    <input ref={inputRef} type="file" aria-label="비교할 상품 사진 선택" accept="image/jpeg,image/png,image/webp" multiple hidden disabled={busy}
      onChange={event => { addFiles(event.target.files); event.target.value = '' }} />
    <div className="comparison-photo-grid">
      {photos.map((photo, index) => <figure key={photo.url}>
        <img src={photo.url} alt={`비교 사진 ${index + 1}`} />
        <figcaption><strong>사진 {index + 1}</strong><span title={photo.file.name}>{photo.file.name}</span>
          <button type="button" disabled={busy} onClick={() => replacePhotos(photos.filter((_, i) => i !== index))} aria-label={`사진 ${index + 1} 삭제`}>삭제</button></figcaption>
      </figure>)}
      {photos.length < 3 && <button type="button" className="comparison-add" disabled={busy} onClick={() => inputRef.current?.click()}>
        <strong>+ 사진 추가</strong><span>JPG · PNG · WEBP / 장당 10MB</span>
      </button>}
    </div>
    <label className="comparison-consent"><input type="checkbox" checked={consent} disabled={busy} onChange={e => setConsent(e.target.checked)} />
      <span>사진 비교를 위해 선택한 사진을 Groq로 전송하는 데 동의합니다. 전송 전 위치 등 메타데이터를 제거합니다. {combined ? '함께 확인에서는 AI 생성 분석에 사용한 사진과 결과가 서버 분석 기록에 저장됩니다.' : '이 비교 기능은 사진과 결과를 서버에 별도로 저장하지 않습니다.'}</span>
    </label>
    <div className="comparison-actions">
      <button type="button" className="primary-cta" disabled={busy || photos.length < 2 || !consent} onClick={() => { void compare() }}>{busy ? '확인 중…' : combined ? '함께 확인 시작' : '사진 비교 시작'}</button>
      <button type="button" className="secondary-cta" disabled={busy || photos.length === 0} onClick={() => { replacePhotos([]); setConsent(false) }}>비교 초기화</button>
    </div>
    <p className="comparison-limit">{combined ? 'AI 분석 점수와 상품 사진 비교는 서로 다른 결과입니다. 두 결과를 합친 거래 안전 점수는 제공하지 않습니다. 사진별 AI 분석은 차례로 진행되어 시간이 더 걸릴 수 있습니다.' : '같은 물건이라는 인증이나 AI 생성 여부 판정이 아닙니다. 조명·각도에 따른 차이가 있을 수 있고, 작은 흠집은 확인되지 않을 수 있습니다.'}</p>
    {phase && <p role="status">{phase}</p>}
    {error && <p className="comparison-error" role="alert">{error}</p>}
    {photoJobs.length > 0 && <section className="combined-photo-results" aria-label="사진별 AI 생성 분석">
      <h3>사진별 AI 생성 분석</h3>
      <p>점수는 모델의 판별 점수이며 실제 정확도나 거래 안전 확률이 아닙니다.</p>
      {photoJobs.map((job, index) => <article className="combined-photo-job" key={photos[index].url}>
        <div className="combined-photo-job-heading"><img src={photos[index].url} alt={`AI 분석 사진 ${index + 1}`} />
          <div><h4>사진 {index + 1} · {photos[index].file.name}</h4>
            <p>{job.status === 'queued' ? '대기 중' : job.status === 'running' ? 'AI 분석 중…' : job.status === 'error' ? 'AI 분석 실패' : `AI 판별 점수 ${job.result?.fakePercent.toFixed(1)}%`}</p>
          </div>
        </div>
        {job.message && <p className="comparison-error" role="alert">{job.message}</p>}
        {job.result && <details><summary>사진 {index + 1} 분석 근거와 출처 기록 보기</summary>{job.result.content}</details>}
      </article>)}
    </section>}
    {result && <h3 className="combined-comparison-title">사진 간 상품 특징 비교</h3>}
    {result && <div className="comparison-results" aria-live="polite">
      <div className="comparison-summary"><h3>{result.differenceCount > 0 ? '추가로 확인할 차이가 있습니다' : '뚜렷한 차이로 표시된 항목은 없습니다'}</h3>
        <p>모델이 제안한 관찰 결과입니다. 비교 어려움 항목과 실제 사진을 함께 확인하세요. 차이가 표시되지 않아도 같은 물건이라는 뜻은 아닙니다.</p>
      </div>
      {result.duplicatePairs.map(pair => <p className="comparison-duplicate" key={pair.join('-')}>사진 {pair[0]}·{pair[1]}은 동일한 이미지입니다. 다른 각도의 사진을 추가해야 비교에 도움이 됩니다.</p>)}
      {result.pairs.map(pair => <section className="comparison-pair" key={`${pair.photoA}-${pair.photoB}`}>
        <h3>사진 {pair.photoA} ↔ 사진 {pair.photoB}</h3>
        <div className="comparison-pair-photos">{[pair.photoA, pair.photoB].map(id => <figure key={id}><img src={photos[id - 1]?.url} alt={`사진 ${id} 비교 원본`} /><figcaption>사진 {id}</figcaption></figure>)}</div>
        <div className="comparison-checks">{pair.checks.map(check => <article key={check.feature} className={`comparison-check is-${check.status}`}>
          <div className="comparison-check-heading"><h4>{check.label}</h4><span>{statusLabels[check.status]}</span></div>
          <dl><div><dt>사진 {pair.photoA}</dt><dd>{check.observationA}</dd></div><div><dt>사진 {pair.photoB}</dt><dd>{check.observationB}</dd></div></dl>
          <p>{check.explanation}</p>
          {check.nextPhoto !== '추가 요청 없음' && <p className="comparison-request"><strong>추가 촬영 제안</strong> {check.nextPhoto}</p>}
        </article>)}</div>
      </section>)}
      <p className="comparison-limit">{result.limitation}</p>
      <small>사진 이해 모델: {result.provider} / {result.model}</small>
    </div>}
  </section>
}
