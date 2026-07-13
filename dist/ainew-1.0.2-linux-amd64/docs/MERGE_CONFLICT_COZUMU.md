# Merge Conflict Çözümü

## "Merge Conflicts Detected" görüyorsanız

### 1. Conflict'lerin nerede olduğunu bulun

Proje kökünde çalıştırın:

```bash
bash scripts/find-merge-conflicts.sh .
```

Veya elle arayın:

```bash
grep -rln "^<<<<<<< " --include="*.py" --include="*.tsx" --include="*.ts" --include="*.yml" .
```

### 2. Bir dosyada conflict varsa

Dosyada şu bloklar görünür:

```
<<<<<<< HEAD
(sizin / mevcut branch'teki kod)
=======
(gelen branch'teki kod)
>>>>>>> branch-adı
```

**Ne yapmalı:**
- Ya **HEAD** tarafını tutun (üst blok), ya **gelen** tarafı (alt blok), ya da ikisini birleştirip mantıklı tek bir hâle getirin.
- `<<<<<<<`, `=======`, `>>>>>>>` satırlarını **tamamen silin**.

### 3. Merge durumunu kontrol edin

```bash
git status
cat .git/MERGE_HEAD   # Varsa merge devam ediyor
```

### 4. Conflict'leri çözdükten sonra

```bash
git add <çözülen dosyalar>
git commit -m "Merge conflict çözüldü"
```

### 5. Merge'ü iptal etmek isterseniz

```bash
git merge --abort
```

---

**Not:** Şu an bu repoda conflict marker'lı dosya bulunmuyor. Uyarıyı GitHub/GitLab PR ekranında veya `git pull`/`git merge` sonrası görüyorsanız, conflict'ler başka bir branch'te veya henüz merge denemediyseniz uzak branch'i birleştirip (`git fetch` + `git merge`) çıkan conflict'leri yukarıdaki adımlarla çözebilirsiniz.
