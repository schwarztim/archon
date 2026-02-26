import { Input } from "@/components/ui/Input";

interface S3FormProps {
  config: Record<string, string>;
  onChange: (config: Record<string, string>) => void;
}

const REGIONS = [
  "us-east-1", "us-east-2", "us-west-1", "us-west-2",
  "eu-west-1", "eu-west-2", "eu-central-1",
  "ap-southeast-1", "ap-northeast-1",
];

export function S3Form({ config, onChange }: S3FormProps) {
  const set = (key: string, value: string) => onChange({ ...config, [key]: value });

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
      <div>
        <label className="mb-1 block text-xs font-medium text-gray-600 dark:text-gray-400">Region *</label>
        <select
          value={config.region ?? "us-east-1"}
          onChange={(e) => set("region", e.target.value)}
          className="h-9 w-full rounded-md border border-gray-200 bg-gray-50 px-3 text-sm text-gray-900 dark:border-surface-border dark:bg-surface-base dark:text-white"
        >
          {REGIONS.map((r) => (
            <option key={r} value={r}>{r}</option>
          ))}
        </select>
      </div>
      <div>
        <label className="mb-1 block text-xs font-medium text-gray-600 dark:text-gray-400">Bucket Name *</label>
        <Input placeholder="my-bucket" value={config.bucket ?? ""} onChange={(e) => set("bucket", e.target.value)} className="bg-gray-50 dark:bg-surface-base" />
      </div>
      <div>
        <label className="mb-1 block text-xs font-medium text-gray-600 dark:text-gray-400">Access Key ID *</label>
        <Input type="password" placeholder="AKIA..." value={config.access_key ?? ""} onChange={(e) => set("access_key", e.target.value)} className="bg-gray-50 dark:bg-surface-base" />
      </div>
      <div>
        <label className="mb-1 block text-xs font-medium text-gray-600 dark:text-gray-400">Secret Access Key *</label>
        <Input type="password" placeholder="••••••" value={config.secret_key ?? ""} onChange={(e) => set("secret_key", e.target.value)} className="bg-gray-50 dark:bg-surface-base" />
      </div>
    </div>
  );
}
