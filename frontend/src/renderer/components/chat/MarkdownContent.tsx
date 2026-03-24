import React, { useState, useCallback } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import type { Components } from "react-markdown";
import { Check, Copy } from "lucide-react";

const warmSyntaxTheme: Record<string, React.CSSProperties> = {
  'code[class*="language-"]': {
    color: "#4D4538",
    background: "none",
    fontFamily: "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, monospace",
    fontSize: "0.8125rem",
    lineHeight: "1.625",
  },
  'pre[class*="language-"]': {
    color: "#4D4538",
    background: "#F5F1EA",
    padding: "1rem",
    borderRadius: "0.5rem",
    overflow: "auto",
  },
  comment: { color: "#918779" },
  prolog: { color: "#918779" },
  doctype: { color: "#918779" },
  cdata: { color: "#918779" },
  punctuation: { color: "#6E6456" },
  property: { color: "#C07639" },
  tag: { color: "#C07639" },
  boolean: { color: "#C07639" },
  number: { color: "#C07639" },
  constant: { color: "#C07639" },
  symbol: { color: "#C07639" },
  selector: { color: "#7B8C52" },
  "attr-name": { color: "#D4874D" },
  string: { color: "#7B8C52" },
  char: { color: "#7B8C52" },
  builtin: { color: "#D4874D" },
  operator: { color: "#6E6456" },
  entity: { color: "#D4874D" },
  url: { color: "#D4874D" },
  keyword: { color: "#C07639" },
  regex: { color: "#7B8C52" },
  important: { color: "#C07639", fontWeight: "bold" },
  atrule: { color: "#C07639" },
  "attr-value": { color: "#7B8C52" },
  function: { color: "#D4874D" },
  "class-name": { color: "#352F25" },
  variable: { color: "#4D4538" },
};

const CopyButton: React.FC<{ text: string }> = ({ text }) => {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(async () => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [text]);

  return (
    <button
      onClick={handleCopy}
      className="absolute top-2 right-2 p-1.5 rounded-md bg-warm-200/60 text-warm-500
                 hover:bg-warm-200 hover:text-warm-700 transition-all
                 opacity-0 group-hover:opacity-100"
      aria-label="Copy code"
    >
      {copied ? <Check size={14} /> : <Copy size={14} />}
    </button>
  );
};

const components: Components = {
  code({ children, className, ...rest }) {
    const match = /language-(\w+)/.exec(className || "");
    const codeString = String(children).replace(/\n$/, "");

    if (match) {
      return (
        <div className="relative group not-prose">
          <CopyButton text={codeString} />
          <SyntaxHighlighter
            style={warmSyntaxTheme}
            language={match[1]}
            PreTag="div"
          >
            {codeString}
          </SyntaxHighlighter>
        </div>
      );
    }

    return (
      <code
        className="bg-warm-150 text-accent-600 px-1.5 py-0.5 rounded text-[0.8125rem] font-mono"
        {...rest}
      >
        {children}
      </code>
    );
  },

  pre({ children }) {
    return <>{children}</>;
  },

  table({ children, ...rest }) {
    return (
      <div className="overflow-x-auto my-4">
        <table className="min-w-full" {...rest}>{children}</table>
      </div>
    );
  },
};

interface MarkdownContentProps {
  content: string;
}

const MarkdownContent: React.FC<MarkdownContentProps> = ({ content }) => {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
      {content}
    </ReactMarkdown>
  );
};

export default MarkdownContent;
