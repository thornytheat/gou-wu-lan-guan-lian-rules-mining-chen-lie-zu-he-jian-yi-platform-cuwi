import http from './http'
import type { ComparisonRunSnapshot, RunComparison } from '../types/domain'

export interface ComparisonPayload {
  baseline_run_id: string
  current_run_id: string
  force_refresh?: boolean
}

export async function fetchBaselines(): Promise<{ baselines: ComparisonRunSnapshot[]; count: number }> {
  const { data } = await http.get('/comparisons/baselines')
  return data
}

export async function createComparison(payload: ComparisonPayload): Promise<RunComparison> {
  const { data } = await http.post<RunComparison>('/comparisons', payload)
  return data
}

export async function fetchComparisons(): Promise<{
  comparisons: Array<Pick<RunComparison, 'comparison_key' | 'counts' | 'baseline' | 'current' | 'snapshot_at'>>
  count: number
}> {
  const { data } = await http.get('/comparisons')
  return data
}
