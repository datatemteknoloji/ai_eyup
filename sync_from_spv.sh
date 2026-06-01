#!/bin/bash
set -e

echo "🔄 SPV worktree'den ana projeye dosya kopyalama..."

SPV="/root/.cursor/worktrees/ainew__SSH__root_192.168.1.166_/spv"
MAIN="/root/ainew"

# Backend - Critical files
echo "📦 Backend dosyaları..."

# Models
cp -f "$SPV/backend/app/models/credential.py" "$MAIN/backend/app/models/" 2>/dev/null || echo "credential.py yok, oluşturulacak"
cp -f "$SPV/backend/app/models/event.py" "$MAIN/backend/app/models/" 2>/dev/null || echo "event.py yok, oluşturulacak"
cp -f "$SPV/backend/app/models/__init__.py" "$MAIN/backend/app/models/"

# API
cp -f "$SPV/backend/app/api/settings.py" "$MAIN/backend/app/api/"
cp -f "$SPV/backend/app/api/events.py" "$MAIN/backend/app/api/" 2>/dev/null || echo "events.py yok"
cp -f "$SPV/backend/app/api/incidents.py" "$MAIN/backend/app/api/" 2>/dev/null || echo "incidents.py yok"
cp -f "$SPV/backend/app/api/hypervisors.py" "$MAIN/backend/app/api/"
cp -f "$SPV/backend/app/api/servers.py" "$MAIN/backend/app/api/"
cp -f "$SPV/backend/app/api/router.py" "$MAIN/backend/app/api/"

# Services - VMware/oVirt
mkdir -p "$MAIN/backend/app/services/vmware"
mkdir -p "$MAIN/backend/app/services/ovirt"
cp -rf "$SPV/backend/app/services/vmware/"* "$MAIN/backend/app/services/vmware/" 2>/dev/null || echo "vmware services yok"
cp -rf "$SPV/backend/app/services/ovirt/"* "$MAIN/backend/app/services/ovirt/" 2>/dev/null || echo "ovirt services yok"

# Frontend - Critical pages
echo "🎨 Frontend dosyaları..."
cp -f "$SPV/frontend/src/pages/Events.tsx" "$MAIN/frontend/src/pages/" 2>/dev/null || echo "Events.tsx yok"
cp -f "$SPV/frontend/src/pages/Incidents.tsx" "$MAIN/frontend/src/pages/" 2>/dev/null || echo "Incidents.tsx yok"
cp -f "$SPV/frontend/src/pages/Settings.tsx" "$MAIN/frontend/src/pages/"
cp -f "$SPV/frontend/src/App.tsx" "$MAIN/frontend/src/"
cp -f "$SPV/frontend/src/components/Layout.tsx" "$MAIN/frontend/src/components/"

echo "✅ Ana projeye kopyalama tamamlandı!"
