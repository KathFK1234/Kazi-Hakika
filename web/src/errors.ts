import { ApiError } from './api'

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'Something went wrong. Please try again.'
}

/** What went wrong, and the field it's about when the server named one. */
export type Problem = { message: string; field?: string }

export function toProblem(error: unknown): Problem {
  return { message: errorMessage(error), field: error instanceof ApiError ? error.field : undefined }
}

/** The message to show under `field`, if the problem is about it. */
export function fieldError(problem: Problem | null, field: string): string | undefined {
  return problem && problem.field === field ? problem.message : undefined
}

/** The message for the form as a whole: anything not shown under one of `fields`. */
export function formError(problem: Problem | null, fields: readonly string[]): string | null {
  if (!problem) return null
  return problem.field && fields.includes(problem.field) ? null : problem.message
}
