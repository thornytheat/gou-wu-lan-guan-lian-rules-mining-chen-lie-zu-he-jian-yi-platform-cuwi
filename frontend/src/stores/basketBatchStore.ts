import { defineStore } from 'pinia'
import { fetchBatches, importBatches, type ImportBatchPayload } from '../api/basketBatches'
import type { BasketBatch } from '../types/domain'

interface BasketBatchState {
  batches: BasketBatch[]
  loading: boolean
  error: string
  notice: string
}

export const useBasketBatchStore = defineStore('basket-batches', {
  state: (): BasketBatchState => ({
    batches: [],
    loading: false,
    error: '',
    notice: '',
  }),
  actions: {
    async load() {
      this.loading = true
      this.error = ''
      try {
        const result = await fetchBatches()
        this.batches = result.batches
      } catch (error) {
        this.error = (error as Error).message
      } finally {
        this.loading = false
      }
    },
    async importBatch(payload: ImportBatchPayload) {
      this.error = ''
      this.notice = ''
      try {
        const result = await importBatches(payload)
        this.notice = result.message
        await this.load()
        return result
      } catch (error) {
        this.error = (error as Error).message
        throw error
      }
    },
  },
})
