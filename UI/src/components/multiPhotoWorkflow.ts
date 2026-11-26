export type CheckOutcome<T> = { status: 'success'; value: T } | { status: 'error'; message: string }

function message(error: unknown): string {
  return error instanceof Error ? error.message : '분석 중 오류가 발생했습니다.'
}

export async function runMultiPhotoChecks<C, P>(options: {
  count: number
  signal: AbortSignal
  compare: () => Promise<C>
  analyze: (index: number) => Promise<P>
  onPhase: (phase: 'comparison' | 'photo', index?: number) => void
  onComparison: (outcome: CheckOutcome<C>) => void
  onPhoto: (index: number, outcome: CheckOutcome<P>) => void
}): Promise<void> {
  const { signal } = options
  if (signal.aborted) return
  options.onPhase('comparison')
  try {
    const value = await options.compare()
    if (!signal.aborted) options.onComparison({ status: 'success', value })
  } catch (error) {
    if (!signal.aborted) options.onComparison({ status: 'error', message: message(error) })
  }
  for (let index = 0; index < options.count && !signal.aborted; index++) {
    options.onPhase('photo', index)
    try {
      const value = await options.analyze(index)
      if (!signal.aborted) options.onPhoto(index, { status: 'success', value })
    } catch (error) {
      if (!signal.aborted) options.onPhoto(index, { status: 'error', message: message(error) })
    }
  }
}
