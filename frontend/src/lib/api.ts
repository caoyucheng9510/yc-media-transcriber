export class ApiError extends Error {
  status: number
  code?: string
  stage?: string

  constructor(status: number, message: string, code?: string, stage?: string) {
    super(message)
    this.name = "ApiError"
    this.status = status
    this.code = code
    this.stage = stage
  }
}

type RequestOptions = RequestInit & {
  token?: string
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers = new Headers(options.headers)

  if (options.token) {
    headers.set("Authorization", `Bearer ${options.token}`)
  }

  const response = await fetch(path, {
    ...options,
    headers,
  })

  if (!response.ok) {
    throw await apiErrorFromResponse(response)
  }

  if (response.status === 204) {
    return undefined as T
  }

  return response.json() as Promise<T>
}

export async function downloadFile(path: string, token?: string): Promise<void> {
  return downloadFileFromRequest(path, {}, token)
}

export async function downloadFileFromRequest(
  path: string,
  options: RequestInit = {},
  token?: string,
): Promise<void> {
  const headers = new Headers(options.headers)
  if (token) {
    headers.set("Authorization", `Bearer ${token}`)
  }

  const response = await fetch(path, { ...options, headers })
  if (!response.ok) {
    throw await apiErrorFromResponse(response)
  }

  const blob = await response.blob()
  const disposition = response.headers.get("content-disposition") || ""
  const match = disposition.match(/filename="?([^";]+)"?/)
  const filename = match?.[1] || path.split("/").pop() || "artifact.txt"
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement("a")
  anchor.href = url
  anchor.download = decodeURIComponent(filename)
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

async function apiErrorFromResponse(response: Response): Promise<ApiError> {
  let message = response.statusText || "Request failed"
  let code: string | undefined
  let stage: string | undefined

  try {
    const payload = await response.json()
    const detail = payload.detail
    if (typeof detail === "string") {
      message = detail
    } else if (detail && typeof detail === "object" && !Array.isArray(detail)) {
      message = String(detail.message || detail.msg || message)
      code = typeof detail.code === "string" ? detail.code : undefined
      stage = typeof detail.stage === "string" ? detail.stage : undefined
    }
  } catch {
    const text = await response.text().catch(() => "")
    if (text) {
      message = text
    }
  }

  return new ApiError(response.status, message, code, stage)
}
