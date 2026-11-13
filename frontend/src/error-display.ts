export const NETWORK_INTERRUPTED = "网络连接中断，请检查网络或代理后重试";

// Presentation only: preserve the original exceptions, logs and recovery state.
export function displayError(message: string): string {
  const networkError = /SSLEOFError|UNEXPECTED_EOF_WHILE_READING|EOF occurred in violation of protocol|ConnectionResetError|ConnectionAbortedError|ConnectionRefusedError|ECONN(?:RESET|ABORTED|REFUSED)|connection (?:was )?(?:reset|aborted|refused)|all connection attempts failed|failed to establish a new connection|\b(?:Connect|Read|Write)Timeout\b|(?:read|write|connect) operation timed out|WinError (?:10053|10054|10060|10061)\b/i;
  return networkError.test(message) || message.trim() === "EOF" ? NETWORK_INTERRUPTED : message;
}
