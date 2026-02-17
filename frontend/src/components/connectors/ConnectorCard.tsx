import { Button } from "@/components/ui/Button";
import {
  Database, Cloud, MessageSquare, Globe, Bot, Cpu, Server, Webhook,
  Github, Mail, Search, GitBranch, Book, Notebook, Headphones,
  Target, Briefcase, Code, Brain, Ticket, Users, Plug,
} from "lucide-react";

interface ConnectorCardProps {
  name: string;
  label: string;
  category: string;
  icon: string;
  description: string;
  supportsOauth: boolean;
  onConnect: () => void;
}

const iconMap: Record<string, typeof Database> = {
  database: Database,
  server: Server,
  cloud: Cloud,
  "message-square": MessageSquare,
  "message-circle": MessageSquare,
  globe: Globe,
  bot: Bot,
  cpu: Cpu,
  webhook: Webhook,
  github: Github,
  mail: Mail,
  search: Search,
  "git-branch": GitBranch,
  book: Book,
  notebook: Notebook,
  headphones: Headphones,
  target: Target,
  briefcase: Briefcase,
  code: Code,
  brain: Brain,
  ticket: Ticket,
  users: Users,
  plug: Plug,
  snowflake: Database,
  chart: Database,
};

const categoryColors: Record<string, string> = {
  Database: "bg-blue-500/20 text-blue-400 dark:bg-blue-500/20 dark:text-blue-400",
  SaaS: "bg-purple-500/20 text-purple-400 dark:bg-purple-500/20 dark:text-purple-400",
  Communication: "bg-pink-500/20 text-pink-400 dark:bg-pink-500/20 dark:text-pink-400",
  Cloud: "bg-cyan-500/20 text-cyan-400 dark:bg-cyan-500/20 dark:text-cyan-400",
  AI: "bg-amber-500/20 text-amber-400 dark:bg-amber-500/20 dark:text-amber-400",
  Custom: "bg-gray-500/20 text-gray-400 dark:bg-gray-500/20 dark:text-gray-400",
};

export function ConnectorCard({
  label,
  category,
  icon,
  description,
  supportsOauth,
  onConnect,
}: ConnectorCardProps) {
  const Icon = iconMap[icon] ?? Plug;
  const catColor = categoryColors[category] ?? categoryColors.Custom;

  return (
    <div className="group rounded-lg border border-gray-200 bg-white p-4 transition-colors hover:border-purple-500/50 dark:border-[#2a2d37] dark:bg-[#1a1d27]">
      <div className="mb-3 flex items-start justify-between">
        <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-purple-500/20">
          <Icon size={20} className="text-purple-400" />
        </div>
        <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${catColor}`}>
          {category}
        </span>
      </div>
      <h3 className="mb-1 text-sm font-semibold text-gray-900 dark:text-white">{label}</h3>
      <p className="mb-3 text-xs text-gray-500 dark:text-gray-500 line-clamp-2">{description}</p>
      <Button
        size="sm"
        variant="outline"
        className="w-full border-purple-500/30 text-purple-600 opacity-80 group-hover:opacity-100 dark:text-purple-400"
        onClick={onConnect}
      >
        {supportsOauth ? "Connect" : "Configure"}
      </Button>
    </div>
  );
}
