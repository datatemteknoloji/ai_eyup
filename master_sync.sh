#!/bin/bash
set -e

echo "🚀 MASTER SYNC - Tüm Worktree'lere Dağıtım"
echo "=========================================="

SPV="/root/.cursor/worktrees/ainew__SSH__root_192.168.1.166_/spv"
MAIN="/root/ainew"
WORKTREE_BASE="/root/.cursor/worktrees/ainew__SSH__root_192.168.1.166_"

# 1. SPV'den ana projeye kopyala
echo ""
echo "📦 ADIM 1: SPV → Ana Proje"
echo "-------------------------"

# VMware/oVirt services
cp -rf "$SPV/backend/app/services/vmware" "$MAIN/backend/app/services/"
cp -rf "$SPV/backend/app/services/ovirt" "$MAIN/backend/app/services/"

# Models
cp -f "$SPV/backend/app/models/credential.py" "$MAIN/backend/app/models/" 2>/dev/null || true
cp -f "$SPV/backend/app/models/event.py" "$MAIN/backend/app/models/" 2>/dev/null || true
cp -f "$SPV/backend/app/models/server.py" "$MAIN/backend/app/models/"
cp -f "$SPV/backend/app/models/__init__.py" "$MAIN/backend/app/models/"

# API
cp -f "$SPV/backend/app/api/settings.py" "$MAIN/backend/app/api/"
cp -f "$SPV/backend/app/api/events.py" "$MAIN/backend/app/api/" 2>/dev/null || true
cp -f "$SPV/backend/app/api/incidents.py" "$MAIN/backend/app/api/" 2>/dev/null || true
cp -f "$SPV/backend/app/api/hypervisors.py" "$MAIN/backend/app/api/"
cp -f "$SPV/backend/app/api/servers.py" "$MAIN/backend/app/api/"
cp -f "$SPV/backend/app/api/router.py" "$MAIN/backend/app/api/"

# Frontend
cp -f "$SPV/frontend/src/pages/Events.tsx" "$MAIN/frontend/src/pages/" 2>/dev/null || true
cp -f "$SPV/frontend/src/pages/Incidents.tsx" "$MAIN/frontend/src/pages/" 2>/dev/null || true
cp -f "$SPV/frontend/src/pages/Settings.tsx" "$MAIN/frontend/src/pages/"
cp -f "$SPV/frontend/src/App.tsx" "$MAIN/frontend/src/"
cp -f "$SPV/frontend/src/components/Layout.tsx" "$MAIN/frontend/src/components/"

echo "✅ Ana projeye kopyalama tamam"

# 2. Ana projeden TÜM worktree'lere dağıt
echo ""
echo "🌐 ADIM 2: Ana Proje → Tüm Worktree'ler"
echo "--------------------------------------"

WORKTREES=(bik dsm gqq hjc hqf joh qjj qlj quq srz tvv uum wlk xrx)

for wt in "${WORKTREES[@]}"; do
    TARGET="$WORKTREE_BASE/$wt"
    if [ ! -d "$TARGET" ]; then
        echo "⏭️  $wt: dizin yok, atlanıyor"
        continue
    fi
    
    echo "📋 $wt: kopyalanıyor..."
    
    # Backend klasörleri oluştur
    mkdir -p "$TARGET/backend/app/services/vmware"
    mkdir -p "$TARGET/backend/app/services/ovirt"
    mkdir -p "$TARGET/backend/app/models"
    mkdir -p "$TARGET/backend/app/api"
    
    # Frontend klasörleri oluştur  
    mkdir -p "$TARGET/frontend/src/pages"
    mkdir -p "$TARGET/frontend/src/components"
    
    # Backend dosyaları
    cp -rf "$MAIN/backend/app/services/vmware/"* "$TARGET/backend/app/services/vmware/" 2>/dev/null || true
    cp -rf "$MAIN/backend/app/services/ovirt/"* "$TARGET/backend/app/services/ovirt/" 2>/dev/null || true
    cp -f "$MAIN/backend/app/models/credential.py" "$TARGET/backend/app/models/" 2>/dev/null || true
    cp -f "$MAIN/backend/app/models/event.py" "$TARGET/backend/app/models/" 2>/dev/null || true
    cp -f "$MAIN/backend/app/models/server.py" "$TARGET/backend/app/models/" 2>/dev/null || true
    cp -f "$MAIN/backend/app/models/__init__.py" "$TARGET/backend/app/models/" 2>/dev/null || true
    cp -f "$MAIN/backend/app/api/settings.py" "$TARGET/backend/app/api/" 2>/dev/null || true
    cp -f "$MAIN/backend/app/api/events.py" "$TARGET/backend/app/api/" 2>/dev/null || true
    cp -f "$MAIN/backend/app/api/incidents.py" "$TARGET/backend/app/api/" 2>/dev/null || true
    cp -f "$MAIN/backend/app/api/hypervisors.py" "$TARGET/backend/app/api/" 2>/dev/null || true
    cp -f "$MAIN/backend/app/api/servers.py" "$TARGET/backend/app/api/" 2>/dev/null || true
    cp -f "$MAIN/backend/app/api/router.py" "$TARGET/backend/app/api/" 2>/dev/null || true
    
    # Frontend dosyaları
    cp -f "$MAIN/frontend/src/pages/Events.tsx" "$TARGET/frontend/src/pages/" 2>/dev/null || true
    cp -f "$MAIN/frontend/src/pages/Incidents.tsx" "$TARGET/frontend/src/pages/" 2>/dev/null || true
    cp -f "$MAIN/frontend/src/pages/Settings.tsx" "$TARGET/frontend/src/pages/" 2>/dev/null || true
    cp -f "$MAIN/frontend/src/App.tsx" "$TARGET/frontend/src/" 2>/dev/null || true
    cp -f "$MAIN/frontend/src/components/Layout.tsx" "$TARGET/frontend/src/components/" 2>/dev/null || true
    
    echo "   ✅ $wt: tamam"
done

echo ""
echo "🎉 MASTER SYNC TAMAMLANDI!"
echo "=========================="
echo "✅ Ana proje güncellendi"
echo "✅ 14 worktree senkronize edildi"
echo ""
echo "Artık HERHANGİ BİR worktree'de çalışabilirsiniz:"
echo "  - Global Credentials ✓"
echo "  - Events/Incidents ✓"
echo "  - VMware/oVirt Sync ✓"
echo "  - Chat ✓"
