// Server-Sent Events as `ooat serve` writes them: `id:`, `event:`, `data:` lines, a blank line ends a message, a
// line starting with ":" is a comment (the keepalive).

/** @typedef {{id: string | null, event: string, data: string}} SseMessage */

/**
 * The whole messages in `buffer`, and the unfinished rest to prepend to the next chunk.
 * @param {string} buffer
 * @returns {{messages: SseMessage[], rest: string}}
 */
export function parseSse(buffer) {
  const blocks = buffer.split("\n\n");
  const rest = blocks.pop() ?? "";
  /** @type {SseMessage[]} */
  const messages = [];
  for (const block of blocks) {
    /** @type {SseMessage} */
    const message = {id: null, event: "message", data: ""};
    const data = [];
    for (const line of block.split("\n")) {
      if (line === "" || line.startsWith(":")) continue;
      const colon = line.indexOf(":");
      const field = colon < 0 ? line : line.slice(0, colon);
      const value = colon < 0 ? "" : line.slice(colon + 1).replace(/^ /, "");
      if (field === "id") message.id = value;
      else if (field === "event") message.event = value;
      else if (field === "data") data.push(value);
    }
    if (data.length) messages.push({...message, data: data.join("\n")});
  }
  return {messages, rest};
}
