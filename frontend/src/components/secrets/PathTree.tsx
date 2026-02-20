import { useState, useMemo } from "react";
import type { SecretMetadata } from "@/api/secrets";

interface PathNode {
  name: string;
  path: string;
  children: PathNode[];
  secrets: SecretMetadata[];
}

interface PathTreeProps {
  secrets: SecretMetadata[];
  onSelectPath?: (path: string) => void;
  onSelectSecret?: (path: string) => void;
}

function buildTree(secrets: SecretMetadata[]): PathNode {
  const root: PathNode = { name: "archon", path: "", children: [], secrets: [] };

  for (const s of secrets) {
    const parts = s.path.split("/").filter(Boolean);
    let current = root;

    for (let i = 0; i < parts.length - 1; i++) {
      const segment = parts[i];
      let child = current.children.find((c) => c.name === segment);
      if (!child) {
        child = {
          name: segment!,
          path: parts.slice(0, i + 1).join("/"),
          children: [],
          secrets: [],
        };
        current.children.push(child);
      }
      current = child;
    }

    current.secrets.push(s);
  }

  return root;
}

function TreeNode({
  node,
  depth,
  onSelectPath,
  onSelectSecret,
}: {
  node: PathNode;
  depth: number;
  onSelectPath?: (path: string) => void;
  onSelectSecret?: (path: string) => void;
}) {
  const [expanded, setExpanded] = useState(depth < 2);
  const hasChildren = node.children.length > 0 || node.secrets.length > 0;

  return (
    <div className="select-none">
      <button
        className="flex w-full items-center gap-1.5 rounded px-2 py-1 text-sm hover:bg-muted/40 transition-colors text-left"
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
        onClick={() => {
          setExpanded(!expanded);
          onSelectPath?.(node.path);
        }}
        aria-expanded={expanded}
        aria-label={`${node.name} folder`}
      >
        <span className="text-muted-foreground text-xs">
          {hasChildren ? (expanded ? "▾" : "▸") : "·"}
        </span>
        <span className="font-medium">📁 {node.name}</span>
        {node.secrets.length > 0 && (
          <span className="ml-auto text-xs text-muted-foreground">
            {node.secrets.length} secret{node.secrets.length !== 1 ? "s" : ""}
          </span>
        )}
      </button>
      {expanded && (
        <>
          {node.children.map((child) => (
            <TreeNode
              key={child.path}
              node={child}
              depth={depth + 1}
              onSelectPath={onSelectPath}
              onSelectSecret={onSelectSecret}
            />
          ))}
          {node.secrets.map((s) => {
            const name = s.path.split("/").pop() || s.path;
            return (
              <button
                key={s.path}
                className="flex w-full items-center gap-1.5 rounded px-2 py-1 text-sm hover:bg-primary/10 transition-colors text-left"
                style={{ paddingLeft: `${(depth + 1) * 16 + 8}px` }}
                onClick={() => onSelectSecret?.(s.path)}
                aria-label={`Secret ${name}`}
              >
                <span className="text-muted-foreground text-xs">🔑</span>
                <span className="font-mono text-xs">{name}</span>
              </button>
            );
          })}
        </>
      )}
    </div>
  );
}

export default function PathTree({ secrets, onSelectPath, onSelectSecret }: PathTreeProps) {
  const tree = useMemo(() => buildTree(secrets), [secrets]);

  if (secrets.length === 0) {
    return (
      <div className="rounded-lg border border-dashed p-6 text-center text-muted-foreground">
        No secrets to display in the path tree.
      </div>
    );
  }

  return (
    <div className="rounded-lg border p-2">
      <h3 className="px-2 py-1 text-sm font-semibold text-muted-foreground">
        Vault Path Structure
      </h3>
      <TreeNode
        node={tree}
        depth={0}
        onSelectPath={onSelectPath}
        onSelectSecret={onSelectSecret}
      />
    </div>
  );
}
