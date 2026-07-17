import { useEffect, useState } from 'react'

// ugly on purpose. this page exists to prove the GET /agents/status contract works in a
// browser before phaser (step 12) builds the real dashboard on the exact same data.

type AgentStatusRow = {
  name: string
  role: string
  model: string
  status: string
  updated_at: string
}

const POLL_INTERVAL_MS = 2000 // single-user local tool, 2s feels live without hammering the api

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
    <div>
      <h1>Pantheon — agent status</h1>
      {error && <p>can't reach the backend: {error}</p>}
      <ul>
        {agents.map((agent) => (
          <li key={agent.name}>
            {agent.name} ({agent.role}) — {agent.status} — updated{' '}
            {new Date(agent.updated_at).toLocaleTimeString()}
          </li>
        ))}
      </ul>
    </div>
  )
}

export default AgentStatus
