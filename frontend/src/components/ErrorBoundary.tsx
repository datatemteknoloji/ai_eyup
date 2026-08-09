import { Component, ErrorInfo, ReactNode } from 'react';

interface Props {
  children?: ReactNode;
  fallback?: ReactNode;
  /** Değişince hata durumu sıfırlanır (örn. location.pathname) */
  resetKey?: string | number;
}

interface State {
  hasError: boolean;
  error?: Error;
  errorInfo?: ErrorInfo;
}

class ErrorBoundary extends Component<Props, State> {
  public state: State = {
    hasError: false
  };

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  public componentDidUpdate(prevProps: Props) {
    if (this.state.hasError && prevProps.resetKey !== this.props.resetKey) {
      this.setState({ hasError: false, error: undefined, errorInfo: undefined })
    }
  }

  public componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('Uncaught error in React component:', error, errorInfo);
    this.setState({
      error,
      errorInfo
    });
  }

  public render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }
      
      return (
        <div className="flex h-full min-h-[50vh] flex-col items-center justify-center p-6 text-center">
          <div className="mb-4 rounded-full bg-red-100 p-4">
            <svg className="h-10 w-10 text-red-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
          </div>
          <h2 className="mb-2 text-2xl font-bold text-gray-800">Beklenmeyen Bir Hata Oluştu</h2>
          <p className="mb-4 max-w-md text-gray-600">
            Arayüzde bir sorun meydana geldi. Lütfen sayfayı yenilemeyi deneyin veya sistem yöneticisiyle iletişime geçin.
          </p>
          {this.state.error && (
            <pre className="mb-6 max-w-xl w-full overflow-auto rounded border border-red-200 bg-red-50 px-3 py-2 text-left text-xs text-red-700 font-mono">
              {this.state.error.message || String(this.state.error)}
            </pre>
          )}
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => this.setState({ hasError: false, error: undefined, errorInfo: undefined })}
              className="rounded border border-gray-300 bg-white px-4 py-2 font-semibold text-gray-700 hover:bg-gray-50"
            >
              Tekrar dene
            </button>
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="rounded bg-blue-600 px-4 py-2 font-semibold text-white hover:bg-blue-700"
            >
              Sayfayı Yenile
            </button>
          </div>
          
          {import.meta.env.DEV && this.state.errorInfo && (
            <div className="mt-8 max-w-4xl text-left">
              <pre className="overflow-auto rounded bg-gray-100 p-4 text-xs text-gray-800 border border-gray-300 max-h-64">
                {this.state.errorInfo.componentStack}
              </pre>
            </div>
          )}
        </div>
      );
    }

    return this.props.children;
  }
}

export default ErrorBoundary;
