// VITE_API_BASE_URL is set for the static GCS build. Locally, the relative
// path is proxied to the backend by Vite.
import type {
  AuditLogOut,
  BreakAnalysisOut,
  BreakOut,
  CassReconciliationOut,
  CheckerDecisionOut,
  ClientReconOut,
  ClientUploadOut,
  ConfigOut,
  EvidencePack,
  LoopAAggregateOut,
  LoopAProposeOutV2,
  LoopAWhatIfOut,
  MakerSubmitOut,
  PassStatOut,
  PendingActionOut,
  PositionProofOut,
  RegulatoryNotificationOut,
  ReproducibilityCheckOut,
  ResolutionMemoryOut,
  RunOut,
  RunSummaryOut,
  TokenResponse,
} from './types'

const BASE = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/$/, '')

let authToken: string | null = null
export function setAuthToken(token: string | null) {
  authToken = token
}
let onUnauthorized: (() => void) | null = null
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn
}

class ApiError extends Error {
  status: number
  detail: unknown
  constructor(status: number, detail: unknown) {
    super(typeof detail === 'string' ? detail : JSON.stringify(detail))
    this.status = status
    this.detail = detail
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {}
  if (!(options.body instanceof FormData)) headers['Content-Type'] = 'application/json'
  if (authToken) headers['Authorization'] = `Bearer ${authToken}`

  const resp = await fetch(`${BASE}${path}`, { ...options, headers })
  if (!resp.ok) {
    if (resp.status === 401 && onUnauthorized) onUnauthorized()
    let detail: unknown
    try {
      detail = await resp.json()
    } catch {
      detail = await resp.text()
    }
    throw new ApiError(resp.status, (detail as { detail?: unknown })?.detail ?? detail)
  }
  if (resp.status === 204) return undefined as T
  return resp.json() as Promise<T>
}

const get = <T>(path: string) => request<T>(path)
const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: 'POST', body: body !== undefined ? JSON.stringify(body) : undefined })

export const api = {
  health: () => get<{ status: string; llm_provider: string }>('/health'),

  // auth
  login: (email: string, password: string) => post<TokenResponse>('/auth/login', { email, password }),

  // configs
  authorConfig: (nl_description = '', recon_name_hint?: string) =>
    post<ConfigOut>('/configs/author', { nl_description, recon_name_hint }),
  submitConfig: (id: number) => post<ConfigOut>(`/configs/${id}/submit`),
  approveConfig: (id: number, approved = true, notes?: string) =>
    post<ConfigOut>(`/configs/${id}/approve`, { approved, notes }),
  getConfig: (id: number) => get<ConfigOut>(`/configs/${id}`),
  configVersions: (id: number) => get<ConfigOut[]>(`/configs/${id}/versions`),
  listConfigs: () => get<ConfigOut[]>('/configs'),

  // runs
  createRunFromSeed: (config_id: number) => {
    const form = new FormData()
    form.append('config_id', String(config_id))
    form.append('use_seed', 'true')
    return request<RunOut>('/runs', { method: 'POST', body: form })
  },
  createRunFromUpload: (config_id: number, ledger: File, statement: File) => {
    const form = new FormData()
    form.append('config_id', String(config_id))
    form.append('use_seed', 'false')
    form.append('ledger_file', ledger)
    form.append('statement_file', statement)
    return request<RunOut>('/runs', { method: 'POST', body: form })
  },
  getRun: (id: number) => get<RunOut>(`/runs/${id}`),
  listRuns: () => get<RunOut[]>('/runs'),
  reproduce: (id: number) => post<ReproducibilityCheckOut>(`/runs/${id}/reproduce`),
  positionProof: (id: number) => get<PositionProofOut[]>(`/runs/${id}/position-proof`),
  waterfall: (id: number) => get<PassStatOut[]>(`/runs/${id}/waterfall`),
  runSummary: (id: number) => get<RunSummaryOut>(`/runs/${id}/summary`),

  // breaks
  analyzeBreaks: (run_id: number) => post<BreakAnalysisOut[]>('/breaks/analyze', { run_id }),
  breaksByRun: (run_id: number, params: { status?: string; archetype?: string; regulatory_only?: boolean } = {}) => {
    const q = new URLSearchParams()
    if (params.status) q.set('status', params.status)
    if (params.archetype) q.set('archetype', params.archetype)
    if (params.regulatory_only) q.set('regulatory_only', 'true')
    const qs = q.toString()
    return get<BreakOut[]>(`/breaks/run/${run_id}${qs ? `?${qs}` : ''}`)
  },
  getBreak: (id: number) => get<BreakOut>(`/breaks/${id}`),
  regulatoryBreaks: () => get<BreakOut[]>('/breaks/regulatory'),

  // governance
  makerSubmit: (break_id: number, action_type: string, notes?: string) =>
    post<MakerSubmitOut>('/governance/maker-submit', { break_id, action_type, notes }),
  checkerApprove: (action_id: number, approved: boolean, notes?: string) =>
    post<CheckerDecisionOut>('/governance/checker-approve', { action_id, approved, notes }),
  pendingActions: () => get<PendingActionOut[]>('/governance/pending'),
  auditLog: (page = 1, page_size = 100) =>
    get<AuditLogOut[]>(`/governance/audit?page=${page}&page_size=${page_size}`),

  // regulatory
  emirNotifications: (status = 'DRAFT') => get<RegulatoryNotificationOut[]>(`/regulatory/emir?status=${status}`),
  approveEmir: (id: number) => post<RegulatoryNotificationOut>(`/regulatory/emir/${id}/approve`),
  cassDaily: (date: string) => get<CassReconciliationOut>(`/regulatory/cass/daily/${date}`),
  cassResolutionPack: (date: string) => get<Record<string, unknown>>(`/regulatory/cass/resolution-pack/${date}`),
  csdr: () => get<unknown[]>('/regulatory/csdr'),

  // loops
  loopAAggregate: (run_id: number) => get<LoopAAggregateOut>(`/runs/${run_id}/loop-a/aggregate`),
  loopAPropose: (run_id: number) => post<LoopAProposeOutV2>(`/runs/${run_id}/loop-a/propose`),
  loopAWhatIf: (run_id: number, candidate_config_id: number) =>
    post<LoopAWhatIfOut>(`/runs/${run_id}/loop-a/what-if`, { candidate_config_id }),
  resolutionMemory: () => get<ResolutionMemoryOut[]>('/resolution-memory'),

  // client portal
  clientUpload: (fund_id: string, recon_type: string, file: File) => {
    const form = new FormData()
    form.append('fund_id', fund_id)
    form.append('recon_type', recon_type)
    form.append('file', file)
    return request<ClientUploadOut>('/client/upload', { method: 'POST', body: form })
  },
  clientRecon: (run_id: number) => get<ClientReconOut>(`/client/recon/${run_id}`),
  clientEvidence: (run_id: number) => get<EvidencePack>(`/client/evidence/${run_id}`),
}

export { ApiError }
