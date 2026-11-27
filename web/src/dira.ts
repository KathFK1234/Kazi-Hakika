import type { ConfidenceKey } from './api'

// Career adaptability: four ways people steer their careers. Plain words, no scores shown back.
export const CONFIDENCE_LABELS: Record<ConfidenceKey, { label: string; question: string }> = {
  planning: { label: 'Planning', question: 'Planning what comes next in my career' },
  control: { label: 'Ownership', question: 'Making my own career decisions' },
  curiosity: { label: 'Exploring', question: 'Exploring options I have not tried yet' },
  action: { label: 'Doing', question: 'Taking steps, even small ones, towards my goals' },
}
