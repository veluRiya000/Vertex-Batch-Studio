import { expect, it } from "vitest";
import { displayError, NETWORK_INTERRUPTED } from "./error-display";

it("网络传输错误统一显示中断提示，证书、权限与内容解析错误保持原信息", () => {
  for (const message of [
    "[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol (_ssl.c:1000)",
    "SSLEOFError(8, 'EOF occurred in violation of protocol')",
    "EOF", "Connection reset by peer", "All connection attempts failed",
    "ConnectTimeout", "The read operation timed out",
  ]) expect(displayError(message)).toBe(NETWORK_INTERRUPTED);
  for (const message of [
    "SSLError: CERTIFICATE_VERIFY_FAILED",
    "403 Permission denied", "429 Quota exceeded",
    "JSON decode error: unexpected EOF",
    "操作超时，请检查连接后重试",
  ]) expect(displayError(message)).toBe(message);
});
