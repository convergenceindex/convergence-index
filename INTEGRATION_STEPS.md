# Integration Steps for convergence-index

Add automation to your existing repo with 3 simple steps.

---

## Step 1: Add Files to Your Repository

### 1A: Create Polling Directory and Add Collector

```bash
cd ~/convergence-index

# Create polling directory
mkdir -p polling/sources

# Copy the polling collector
# Copy polling_collector_for_repo.py → polling/collector.py
cp polling_collector_for_repo.py polling/collector.py

# Create init files
touch polling/__init__.py
touch polling/sources/__init__.py
```

### 1B: Add GitHub Actions Workflows

```bash
# Create workflows directory
mkdir -p .github/workflows

# Copy the three workflow files:
# polling-fetch.yml → .github/workflows/polling-fetch.yml
# deploy-on-update.yml → .github/workflows/deploy-on-artifact-update.yml
# generate-graphics.yml → .github/workflows/generate-graphics.yml

cp polling-fetch.yml .github/workflows/polling-fetch.yml
cp deploy-on-update.yml .github/workflows/deploy-on-artifact-update.yml
cp generate-graphics.yml .github/workflows/generate-graphics.yml
```

### 1C: Update .gitignore

```bash
# Add polling cache to gitignore
echo "polling/cache.json" >> .gitignore
```

---

## Step 2: Create Initial Polling Cache

```bash
# Create initial empty cache file
cat > polling/cache.json << 'EOF'
{
  "asOf": "2026-09-23T10:00:00Z",
  "house": {
    "genericBallot": {
      "margin": null,
      "dem_pct": null,
      "rep_pct": null,
      "date": null,
      "source": null
    }
  },
  "senate": {
    "races": {}
  },
  "governors": {
    "races": {}
  },
  "sources": {
    "success": [],
    "failed": [],
    "stale": []
  },
  "metadata": {
    "fetchedAt": "2026-09-23T10:00:00Z",
    "nextUpdate": "2026-09-23T16:00:00Z"
  }
}
EOF
```

---

## Step 3: Commit and Push

```bash
# Check what will be committed
git status

# Stage everything
git add polling/ .github/ .gitignore

# Commit
git commit -m "Add polling automation and GitHub Actions workflows

- Polling collector fetches from 6 sources (Wikipedia, Nate Silver, SurveyUSA, 270toWin, Cook Report, Ballotpedia)
- GitHub Actions workflows run polling every 6 hours
- Auto-deploy site after artifact updates
- Graphics generation at 7 AM daily"

# Push to GitHub
git push
```

---

## Step 4: Enable GitHub Actions

1. Go to: `https://github.com/yourusername/convergence-index/settings/actions`
2. Select: **Allow all actions and reusable workflows**
3. Click: **Save**

Workflows should now appear in the **Actions** tab.

---

## Step 5: Verify Setup

### Check Workflows Are Active

Go to: `https://github.com/yourusername/convergence-index/actions`

You should see:
- ✓ Fetch Polling Data
- ✓ Deploy on Artifact Update
- ✓ Generate Daily Graphics

### Manually Trigger First Run (Optional)

1. Click **Fetch Polling Data** workflow
2. Click **Run workflow** button
3. Watch it execute
4. Verify `polling/cache.json` was created and committed

---

## What Happens Now

### Automatic Timeline

```
2 AM ET  → Polling fetches (GitHub Actions)
6 AM ET  → Artifact updates (Claude scheduled task, as before)
6:10 AM  → Site deploys (GitHub Actions)
7 AM ET  → Graphics generate (GitHub Actions)

8 AM ET  → Polling fetches again
2 PM ET  → Polling fetches again
6 PM ET  → Artifact updates again (Claude scheduled task)
6:10 PM  → Site deploys again (GitHub Actions)
8 PM ET  → Polling fetches again
```

**No manual work. Everything runs itself.**

---

## File Structure After Integration

```
convergence-index/
├── .github/
│   └── workflows/
│       ├── polling-fetch.yml              ← NEW
│       ├── deploy-on-artifact-update.yml  ← NEW
│       └── generate-graphics.yml          ← NEW
├── polling/                               ← NEW
│   ├── __init__.py                        ← NEW
│   ├── collector.py                       ← NEW
│   ├── sources/                           ← NEW
│   │   └── __init__.py                    ← NEW
│   └── cache.json                         ← NEW (generated)
├── fonts/                                 (existing)
├── tools/                                 (existing)
│   ├── build_site.py                      (existing - no changes)
│   └── build_graphics.cjs                 (existing - no changes)
├── index.html                             (existing - updates auto)
├── build_graphics.cjs                     (existing)
├── build_site.py                          (existing)
├── CNAME                                  (existing)
├── README.md                              (existing - update below)
├── og-image.png                           (existing)
└── .gitignore                             (existing - updated)
```

---

## Verify It Works (Next 24 Hours)

### Morning Check (Tomorrow 6 AM ET)

```bash
# Check artifact was published (from Claude scheduled task)
# Visit: https://convergence-index.com

# Check polling was fetched
git log --oneline | grep -i polling | head -3

# Check site was deployed
git log --oneline | grep -i site | head -3
```

### Check GitHub Actions

Go to: `https://github.com/yourusername/convergence-index/actions`

Watch for:
- ✅ Polling fetches at 2 AM, 8 AM, 2 PM, 8 PM
- ✅ Deploy at 6:10 AM and 6:10 PM
- ✅ Graphics at 7 AM

All should show green checkmarks.

---

## Troubleshooting

### Workflows Not Running?

1. Check if Actions are enabled: Settings → Actions
2. Check if branch is `main` (workflows only run on default branch)
3. Manually trigger: Go to Actions → Fetch Polling → Run workflow

### Polling Cache Not Updating?

```bash
# Manual test
cd ~/convergence-index
python polling/collector.py
cat polling/cache.json | python -m json.tool | head -20
```

### Site Not Deploying?

1. Check if `tools/build_site.py` runs successfully locally
2. Check GitHub Actions logs for errors
3. Verify `index.html` can be committed

### Git Push Fails?

```bash
# Make sure you're on main branch
git branch

# If on different branch, switch to main
git checkout main
git pull origin main
git push
```

---

## Updates to README.md

Optionally, update your README to document the automation:

```markdown
## Automation

The forecast updates automatically:

- **Polling**: Fetched every 6 hours from Wikipedia, Nate Silver, SurveyUSA, 270toWin, Cook Report, Ballotpedia
- **Artifact**: Updated by Claude scheduled task at 6 AM & 6 PM ET
- **Website**: Deployed automatically after each artifact update
- **Graphics**: Generated daily at 7 AM ET

No manual intervention required. See `.github/workflows/` for automation setup.

### Local Testing

Test the polling collector:
```bash
python polling/collector.py
```

This will create/update `polling/cache.json` with latest polling data.
```

---

## Done! 🎉

Your repo now has:
✅ Automated polling collection (every 6 hours)
✅ GitHub Actions workflows (all automated)
✅ Auto-deployment (after artifact updates)
✅ Daily graphics generation (7 AM)
✅ Full git history of all updates

**Next step**: Monitor the GitHub Actions tab tomorrow to verify everything runs automatically.

Questions? Check the workflow logs:
→ `https://github.com/yourusername/convergence-index/actions`

