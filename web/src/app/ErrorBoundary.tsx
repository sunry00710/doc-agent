import { Component, type ReactNode } from 'react'

type ErrorBoundaryProps = { children: ReactNode }
type ErrorBoundaryState = { failed: boolean }

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { failed: false }

  static getDerivedStateFromError(): ErrorBoundaryState { return { failed: true } }

  componentDidCatch() {}

  render() {
    if (this.state.failed) return <main className="error-boundary"><h1>Workspace unavailable</h1><p>Reload the page to restore the workspace.</p><button type="button" onClick={() => window.location.reload()}>Reload</button></main>
    return this.props.children
  }
}
