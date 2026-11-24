import React from 'react';

/**
 * The last line of defence: if rendering throws (a response with a shape the page did not
 * expect, a bug), show what happened and the two ways out instead of a blank page.
 * "Start over" mounts the page again from nothing (the failed tree was unmounted when the message
 * replaced it); "Reload" fetches it again.
 */
export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
    this.reset = this.reset.bind(this);
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    console.error(error, info?.componentStack);
  }

  reset() {
    this.setState({ error: null });
  }

  render() {
    if (this.state.error) {
      return (
        <div className="min-h-screen bg-gray-50 flex items-start justify-center px-4 py-12">
          <div role="alert" className="max-w-lg w-full bg-white rounded-lg shadow-lg p-6">
            <h1 className="text-xl font-semibold text-gray-900">This page stopped working</h1>
            <p className="mt-3 text-gray-700">
              Something went wrong and the page could not carry on. If you were checking a
              document, you will need to upload it again.
            </p>
            <div className="mt-5 flex flex-wrap gap-3">
              <button
                type="button"
                onClick={() => window.location.reload()}
                className="min-h-[44px] px-5 rounded-lg bg-blue-600 text-white text-sm font-medium"
              >
                Reload the page
              </button>
              <button
                type="button"
                onClick={this.reset}
                className="min-h-[44px] px-5 rounded-lg border border-gray-300 bg-white text-sm font-medium text-gray-800"
              >
                Start over
              </button>
            </div>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
