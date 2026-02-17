import type { PortDataType } from "@/types";

/**
 * Check if a connection between two port data types is valid.
 * "any" is compatible with all types.
 */
export function isConnectionValid(
  sourceType: PortDataType,
  targetType: PortDataType,
): boolean {
  if (sourceType === "any" || targetType === "any") return true;
  return sourceType === targetType;
}
