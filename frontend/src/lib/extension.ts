export function sendTokenToExtension(token: string): void {
  if (typeof chrome === "undefined" || !chrome.runtime) return;

  const extensionId = process.env.NEXT_PUBLIC_EXTENSION_ID;
  if (!extensionId) return;

  chrome.runtime.sendMessage(
    extensionId,
    { type: "SET_AUTH_TOKEN", token },
    () => {
      // Ignore errors — extension may not be installed
      if (chrome.runtime.lastError) {
        // Swallow — expected when extension is not present
      }
    }
  );
}
