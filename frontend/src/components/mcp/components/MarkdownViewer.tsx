// ── Types ────────────────────────────────────────────────────────────

interface MarkdownViewerProps {
  content: string;
}

/**
 * Lightweight markdown renderer.
 * Converts common markdown patterns to styled HTML.
 */
export function MarkdownViewer({ content }: MarkdownViewerProps) {
  const html = renderMarkdown(content);

  return (
    <div
      className="prose prose-invert prose-sm max-w-none rounded-lg border border-surface-border bg-surface-base p-4 text-gray-300
        prose-headings:text-white prose-a:text-purple-400
        prose-code:rounded prose-code:bg-surface-raised prose-code:px-1.5 prose-code:py-0.5
        prose-pre:bg-surface-base prose-pre:border prose-pre:border-surface-border
        prose-strong:text-white prose-em:text-gray-300
        prose-ul:text-gray-300 prose-ol:text-gray-300
        prose-blockquote:border-purple-500 prose-blockquote:text-gray-400"
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}

/** Simple markdown-to-HTML converter */
function renderMarkdown(md: string): string {
  let html = escapeHtml(md);

  // Code blocks (``` ... ```)
  html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (_m, _lang, code) => {
    return `<pre><code>${code.trim()}</code></pre>`;
  });

  // Inline code
  html = html.replace(/`([^`]+)`/g, "<code>$1</code>");

  // Bold
  html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");

  // Italic
  html = html.replace(/\*(.+?)\*/g, "<em>$1</em>");

  // Headers
  html = html.replace(/^### (.+)$/gm, "<h3>$1</h3>");
  html = html.replace(/^## (.+)$/gm, "<h2>$1</h2>");
  html = html.replace(/^# (.+)$/gm, "<h1>$1</h1>");

  // Links
  html = html.replace(
    /\[([^\]]+)\]\(([^)]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>',
  );

  // Unordered lists
  html = html.replace(/^- (.+)$/gm, "<li>$1</li>");
  html = html.replace(/(<li>.*<\/li>\n?)+/g, (m) => `<ul>${m}</ul>`);

  // Blockquotes
  html = html.replace(/^> (.+)$/gm, "<blockquote>$1</blockquote>");

  // Horizontal rule
  html = html.replace(/^---$/gm, "<hr />");

  // Paragraphs (double newlines)
  html = html.replace(/\n\n/g, "</p><p>");
  html = `<p>${html}</p>`;

  // Clean up empty paragraphs
  html = html.replace(/<p>\s*<\/p>/g, "");

  return html;
}

function escapeHtml(str: string): string {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}
