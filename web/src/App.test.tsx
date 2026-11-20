import { render, screen } from '@testing-library/react'
import { vi } from 'vitest'
import App from './App'

describe('App', () => {
  it('shows the name and tagline from /api/meta', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ name: 'Test Name', tagline: 'test tagline' }), {
          status: 200,
        }),
      ),
    )
    render(<App />)
    expect(await screen.findByText('Test Name')).toBeInTheDocument()
    expect(screen.getByText('test tagline')).toBeInTheDocument()
  })

  it('keeps the fallback name when the API fails', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')))
    render(<App />)
    expect(await screen.findByText('Kazi Hakika')).toBeInTheDocument()
  })
})
