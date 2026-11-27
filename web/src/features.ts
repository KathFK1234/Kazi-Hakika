import { createContext, useContext } from 'react'
import type { Features } from './api'

/** Which optional features the server has switched on (from /api/meta). */
export const FeaturesContext = createContext<Features>({ dira: false })

export const useFeatures = () => useContext(FeaturesContext)
