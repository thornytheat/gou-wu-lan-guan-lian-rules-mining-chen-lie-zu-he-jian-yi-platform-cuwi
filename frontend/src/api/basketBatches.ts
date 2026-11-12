import http from './http'
import type { BasketBatch } from '../types/domain'

export interface ImportBatchPayload {
  batch_code: string
  note?: string
  imported_filename?: string
  baskets: Array<Record<string, unknown>>
}

export interface ImportBatchResult {
  batch: BasketBatch
  inserted: boolean
  message: string
}

export async function fetchBatches(): Promise<{ batches: BasketBatch[]; count: number }> {
  const { data } = await http.get('/basket-batches')
  return data
}

export async function importBatches(payload: ImportBatchPayload): Promise<ImportBatchResult> {
  const { data } = await http.post<ImportBatchResult>('/basket-batches', payload)
  return data
}
