import { useEffect, useState } from 'react'
import aizen from './assets/avatars/Aizen.png'
import asmoday from './assets/avatars/Asmoday.png'
import hermes from './assets/avatars/Hermes.png'
import khepri from './assets/avatars/Khepri.png'
import prometheus from './assets/avatars/Prometheus.png'
import './AgentStatus.css'

// still a thin client -- polls GET /agents/status and renders it, no logic of its own.
// the backend decides what a status means, this just picks a color for it.

// ===== TYPES =====

type AgentStatusRow = {
  name: string
  role: string
  model: string
  status: string
  updated_at: string
}

// ===== STATIC LOOKUPS =====

// imported rather than served from /public so vite bundles + hashes them.
// no ASSIST.png exists yet -- it falls through to the initial-letter placeholder below
const AVATARS: Record<string, string> = {
  Aizen: aizen,
  Asmoday: asmoday,
  Hermes: hermes,
  Khepri: khepri,
  Prometheus: prometheus,
}

// ASSIST first (it's the overseer, it dispatches everyone else), rest alphabetical.
// the api already sorts by name, this only lifts ASSIST out of the middle of the list
const ASSIST = 'ASSIST'

const POLL_INTERVAL_MS = 2000 // single-user local tool, 2s feels live without hammering the api

// ===== HELPERS =====

/** Orders the roster with ASSIST pinned to the top, leaving the API's alphabetical order intact below it. */
function withAssistFirst(agents: AgentStatusRow[]): AgentStatusRow[] {
  const assist = agents.filter((agent) => agent.name === ASSIST)
  const rest = agents.filter((agent) => agent.name !== ASSIST)
  return [...assist, ...rest]
}

// ===== COMPONENT =====

function AgentStatus() {
  const [agents, setAgents] = useState<AgentStatusRow[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    // one fetch now, then every 2s -- no react-query, no ws, nothing to justify yet
    const fetchStatus = async () => {
      try {
        const response = await fetch('/api/agents/status')
        if (!response.ok) throw new Error(`status ${response.status}`)
        setAgents(await response.json())
        setError(null)
      } catch (err) {
        // backend's probably just not running. keep the last list on screen and show the error
        // above it -- a stale list plus a visible warning beats going blank on one dropped poll
        setError(err instanceof Error ? err.message : 'something went wrong')
      }
    }

    fetchStatus()
    const timer = setInterval(fetchStatus, POLL_INTERVAL_MS)
    return () => clearInterval(timer) // stop polling when this unmounts
  }, [])

  return (
    <div className="status-page">
      <h1>Pantheon — agent status</h1>

      {error && <p className="status-error">can't reach the backend: {error}</p>}

      <table className="status-table">
        <thead>
          <tr>
            <th className="col-avatar"></th>
            <th>Agent</th>
            <th>Role</th>
            <th>Model</th>
            <th>Status</th>
            <th>Updated</th>
          </tr>
        </thead>
        <tbody>
          {withAssistFirst(agents).map((agent) => (
            <tr key={agent.name}>
              <td className="col-avatar">
                {AVATARS[agent.name] ? (
                  <img className="avatar" src={AVATARS[agent.name]} alt="" />
                ) : (
                  // stands in until an ASSIST.png shows up -- drop the file in and it takes over
                  <span className="avatar avatar-placeholder">{agent.name.charAt(0)}</span>
                )}
              </td>
              <td className="agent-name">{agent.name}</td>
              <td className="agent-role">{agent.role}</td>
              <td className="agent-model">{agent.model}</td>
              <td>
                {/* the color lives in css, keyed off the status string the api sends */}
                <span className={`badge badge-${agent.status}`}>{agent.status}</span>
              </td>
              <td className="agent-updated">{new Date(agent.updated_at).toLocaleTimeString()}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default AgentStatus
