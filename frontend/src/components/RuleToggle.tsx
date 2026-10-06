// Adds/removes a location rule (country, region, city or venue) of the personal filter.
import type { MouseEvent } from "react";
import { Check, Plus } from "lucide-react";
import { errorMessage } from "../api/client";
import type { FilterProfile, LocationLevel } from "../api/types";
import { useFilter, useFilterMutations } from "../api/hooks";
import { useSession } from "../auth/session";
import { toast } from "../state/ui";
import { Button, IconButton } from "./ui";

export function ruleKeyFor(filter: FilterProfile | undefined, level: LocationLevel, id: number): string | null {
  return filter?.locations.find((r) => r.level === level && r.target_id === id)?.key ?? null;
}

interface RuleToggleProps {
  level: LocationLevel;
  id: number;
  label: string;
  compact?: boolean;
}

export function RuleToggle({ level, id, label, compact }: RuleToggleProps) {
  const { data: filter } = useFilter();
  const { add, remove } = useFilterMutations();
  const { readOnly } = useSession();
  const key = ruleKeyFor(filter, level, id);
  const pending = add.isPending || remove.isPending;
  const run = (e: MouseEvent) => {
    e.stopPropagation();
    const action = key ? remove.mutateAsync(key) : add.mutateAsync({ level, target_id: id });
    action
      .then(() => toast(key ? `${label} aus deinen Filtern entfernt` : `${label} zu deinen Filtern hinzugefügt`, "success"))
      .catch((err) => toast(errorMessage(err), "error"));
  };
  if (compact) {
    return (
      <IconButton
        size="sm"
        variant={key ? "accent" : "default"}
        disabled={readOnly || pending || !filter}
        label={key ? `${label} aus Filtern entfernen` : `${label} zu Filtern hinzufügen`}
        icon={key ? <Check size={14} /> : <Plus size={14} />}
        onClick={run}
      />
    );
  }
  return (
    <Button
      size="sm"
      variant={key ? "accent" : "default"}
      icon={key ? <Check size={14} /> : <Plus size={14} />}
      disabled={readOnly || pending || !filter}
      onClick={run}
      title={key ? "Klicken zum Entfernen" : undefined}
    >
      {key ? "Ausgewählt" : "Hinzufügen"}
    </Button>
  );
}
