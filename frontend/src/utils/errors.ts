import axios from "axios";

export function getErrorMessage(error: unknown, fallback = "Something went wrong.") {
  if (axios.isAxiosError(error)) {
    const detail: unknown = error.response?.data?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      const messages = detail
        .map((item: { msg?: unknown }) => item.msg)
        .filter((message): message is string => typeof message === "string");
      if (messages.length) return messages.join(". ");
    }
    if (!error.response) return "Unable to reach the server. Check your connection and try again.";
  }
  return fallback;
}
