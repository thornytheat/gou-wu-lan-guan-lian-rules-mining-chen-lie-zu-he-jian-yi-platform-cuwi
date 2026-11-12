import { defineStore } from 'pinia'
import {
  createComparison,
  fetchBaselines,
  fetchComparisons,
  type ComparisonPayload,
} from '../api/comparisons'
import type { ComparisonRunSnapshot, RuleChangeType, RunComparison } from '../types/domain'

interface ComparisonState {
  baselines: ComparisonRunSnapshot[]
  history: RunComparison[]
  current: RunComparison | null
  loading: boolean
  error: string
  notice: string
}

export const useComparisonStore = defineStore('comparison', {
  state: (): ComparisonState => ({
    baselines: [],
    history: [],
    current: null,
    loading: false,
    error: '',
    notice: '',
  }),
  getters: {
    changeCounts: (state): Record<RuleChangeType, number> =>
      state.current?.counts ?? { new: 0, gone: 0, stronger: 0, weaker: 0, stable: 0 },
  },
  actions: {
    async loadBaselines() {
      try {
        const result = await fetchBaselines()
        this.baselines = result.baselines
      } catch (error) {
        this.error = (error as Error).message
      }
    },
    async loadHistory() {
      try {
        const result = await fetchComparisons()
        this.history = result.comparisons as RunComparison[]
      } catch (error) {
        this.error = (error as Error).message
      }
    },
    async compare(payload: ComparisonPayload) {
      this.loading = true
      this.error = ''
      this.notice = ''
      try {
        this.current = await createComparison(payload)
        this.notice = this.current.reused_snapshot
          ? '复用首次计算的对比快照（结果可复现）'
          : '已生成新的批次对比快照'
        await this.loadHistory()
        return this.current
      } catch (error) {
        this.error = (error as Error).message
        throw error
      } finally {
        this.loading = false
      }
    },
  },
})
