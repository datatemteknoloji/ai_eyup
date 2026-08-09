import { createContext, useContext } from "react";
import { useNavigate } from "react-router-dom";
import type { JobPublic } from "@dropt/api";

export type OpsWizardContextValue = {
  embedded: boolean;
  serverId: string;
  serverIds: string[];
  onAfterPreview: (job: JobPublic) => void;
  /** Son önizlenen / aktif job — wizard formu draft doldurabilir */
  draftJob?: JobPublic | null;
};

export const OpsWizardContext = createContext<OpsWizardContextValue | null>(null);

export function useOpsWizard() {
  return useContext(OpsWizardContext);
}

/** After preview: stay on console when embedded, else open job detail. */
export function useAfterPreview() {
  const ctx = useOpsWizard();
  const navigate = useNavigate();
  return (job: JobPublic) => {
    if (ctx?.embedded) {
      ctx.onAfterPreview(job);
      return;
    }
    navigate(`/level1/jobs/${job.id}`);
  };
}
