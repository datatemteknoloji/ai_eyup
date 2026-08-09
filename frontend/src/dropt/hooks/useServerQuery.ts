import { useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import { useOpsWizard } from "@dropt/hooks/useOpsWizard";

/** Read serverId / serverIds from wizard query string or embedded console context. */
export function useServerQuery(defaultId = "") {
  const [params] = useSearchParams();
  const ctx = useOpsWizard();
  return useMemo(() => {
    if (ctx?.embedded) {
      const ids =
        ctx.serverIds.length > 0 ? ctx.serverIds : ctx.serverId ? [ctx.serverId] : [];
      return { serverId: ids[0] || defaultId, serverIds: ids, embedded: true as const };
    }
    const single = params.get("serverId") || defaultId;
    const multi = (params.get("serverIds") || "")
      .split(",")
      .map((x) => x.trim())
      .filter(Boolean);
    const ids = multi.length ? multi : single ? [single] : [];
    return { serverId: ids[0] || "", serverIds: ids, embedded: false as const };
  }, [params, defaultId, ctx]);
}
