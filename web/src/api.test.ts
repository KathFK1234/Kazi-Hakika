import { vi } from 'vitest'
import { ApiError, request } from './api'

function respond(body: string, status: number, type = 'text/html') {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(body, { status, headers: { 'Content-Type': type } })))
}

describe('request', () => {
  it('turns an HTML success body into a friendly ApiError', async () => {
    respond('<html>waking up</html>', 200)
    await expect(request('GET', '/api/x')).rejects.toThrow('unexpected reply')
  })

  it('turns an HTML error page into a friendly ApiError', async () => {
    respond('<html>502</html>', 502)
    const error = await request('GET', '/api/x').catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).status).toBe(502)
    expect((error as ApiError).message).toBe('Something went wrong. Please try again.')
  })

  it('shows the first validation message with its field', async () => {
    respond(JSON.stringify({ detail: [{ loc: ['body', 'role_title'], msg: 'String should have at least 1 character' }] }), 422, 'application/json')
    await expect(request('POST', '/api/x', {})).rejects.toMatchObject({
      message: 'Role title: String should have at least 1 character',
      field: 'role_title',
      status: 422,
    })
  })

  it('shows our own validation sentences as written, without the field key', async () => {
    respond(
      JSON.stringify({ detail: [{ loc: ['body', 'handle'], msg: 'Value error, Handle: 3 to 30 letters, numbers, - or _.' }] }),
      422,
      'application/json',
    )
    await expect(request('POST', '/api/x', {})).rejects.toMatchObject({
      message: 'Handle: 3 to 30 letters, numbers, - or _.',
      field: 'handle',
    })
  })
})
