import { Component } from 'react';

class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  render() {
    if (this.state.error) {
      return (
        <section className="m-6 rounded-3xl border border-risk-300/50 bg-risk-100/60 p-6 text-risk-700">
          <p className="metric-label text-risk-700">Frontend Error</p>
          <h1 className="mt-2 font-display text-2xl font-semibold">界面渲染失败</h1>
          <pre className="mt-4 overflow-auto rounded-2xl bg-white/70 p-4 font-mono text-xs">
            {String(this.state.error.message || this.state.error)}
          </pre>
        </section>
      );
    }

    return this.props.children;
  }
}

export default ErrorBoundary;
