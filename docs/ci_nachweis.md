# Mini-OS – CI-Nachweis (GitHub Actions)

- **Referenz:** PR #1 (Draft, nicht gemergt), Branch `vibe/personal-os-4e2dc9`
- **Getesteter PR-Head-Commit:** `221a15a1e1a36ebff3c159aba52057f200e345a9` (`221a15a`)
- **Datum:** 2026-11-15

## 1. Ursachenanalyse: warum zuvor keine Actions-Runs vorlagen

Unterscheidung Draft / Trigger / Repo-Einstellungen / Berechtigungen:

- **Draft-Status ist NICHT die Ursache.** `pull_request`-Events feuern auch für
  Draft-PRs: Run `43776178882` lief mit `event=pull_request` auf PR #1 im Draft-Zustand.
- **Vor Commit `1c361c2`:** API `actions/runs` lieferte `total_count = 0` — repo-weit
  keine sichtbaren Runs (weder main noch Branch). Ab dem Push von `1c361c2` erscheinen
  Runs für **push UND pull_request** auf dem Branch. Die frühere Leere ist damit nicht
  durch den Draft-Status erklärbar (mögliche Ursache: Sichtbarkeit/Rechte des
  App-Tokens zu diesem Zeitpunkt); seitdem ist sie empirisch widerlegt.
- **Trigger der Bestands-Workflows:** `ci.yml` feuert nur auf push→main bzw. PR→main
  (paths-ignore `**/*.md`) und führt **keine Python-Tests** aus (Explorer-npm-Build +
  Wheel-Build). `security.yml` nur bei Änderungen an pyproject/workflows.
  → Für Mini-OS gab es keinen Workflow, der die Testsuite zuverlässig ausführt.
- **Repo-Einstellungen/Berechtigungen:** `actions/permissions` und Branch-Protection
  sind mit dem verwendeten Token nicht lesbar (HTTP 403) — als Einschränkung
  dokumentiert; `actions/runs` ist lesbar und lieferte die Run-Daten.

## 2. Neuer dedizierter Workflow: `.github/workflows/personal-os.yml`

- **Trigger:** `pull_request` → main (paths: `personal_os/**`,
  `tests/test_personal_os*.py`, `examples/personal_os*.py`, `pyproject.toml`,
  `.pre-commit-config.yaml`, eigene Workflow-Datei), `push` (alle Branches, gleiche
  paths — sichert Runs auf dem Draft-PR-Head), `workflow_dispatch`.
- **Jobs:** Matrix Python 3.11 + 3.12 auf ubuntu-latest; Actions per SHA gepinnt
  (repoeigene Pin-Prüfung: `personal-os.yml` bestanden).
- **Schritte:** `pip install --no-deps -e .` (Paket-Installation; personal_os ist
  stdlib-only, Voll-Deps installiert die Repo-CI auf main) → `pip install starlette
  httpx requests uvicorn` (optionale Test-Deps der REST-/No-Network-Tests) →
  `pos --help` (CLI-Einstiegspunkt) → `python -m unittest discover -s tests -p
  "test_personal_os*.py"` (volle Mini-OS-Suite) → `pre-commit run --files …`
  (black/isort/flake8 + Repo-Hooks auf allen Mini-OS-Dateien).
- **Kein Daten-/Secret-/Modellbedarf:** `permissions: contents: read`; keine Secrets,
  keine produktiven Daten, keine externen Modellaufrufe (Netzwerk in Tests ist gepatcht
  und wird getestet; PyPI-Zugriff nur für Paketinstallation).

## 3. Tatsächlicher Run-Nachweis auf dem aktuellen PR-Stand

| Run-ID | Event | Head | Ergebnis |
|---|---|---|---|
| **43776178882** | pull_request (PR #1, Draft) | `221a15a` = PR-Head | **success** — [Run](https://github.com/jonnyinnacity/semantica/actions/runs/43776178882) |
| **43776173550** | push | `221a15a` | **success** — [Run](https://github.com/jonnyinnacity/semantica/actions/runs/43776173550) |

Job-Log von 43776178882 (beide Matrix-Jobs `Mini-OS Python 3.11` / `3.12` → success):
`Successfully installed semantica-0.6.5` (Paket-Installation), optionale Test-Deps
installiert, `pos --help` gelaufen, **`Ran 171 tests … OK`** auf 3.11 und 3.12,
pre-commit alle Hooks **Passed** (black/isort/flake8/yamllint/…).

Erstversuch auf `1c361c2` (Runs 43775978677 push / 43775978821 pull_request) war
**FEHLGESCHLAGEN** (18 Testfehler: `starlette`/`httpx`/`requests`/`uvicorn` fehlten
bei `--no-deps`); behoben in `221a15a` durch Installation der optionalen Test-Deps.
Zusätzlich lief die Repo-CI (`CI`, Run 43776178892) auf `221a15a` mit **success**.

## 4. Verbleibende Einschränkungen (dokumentiert)

- **Verify Action Pins** (Run 43776178871) schlägt repo-weit fehl: Upstream-Tags
  (v7/v5/v3/release-v1) haben sich seit den bestehenden Pins verschoben
  (`setup-node`, `deploy-pages`, `action-gh-release`, `gh-action-pypi-publish`,
  `upload-artifact`, altes `setup-python` in anderen Workflow-Dateien). **Nicht durch
  PR #1 verursacht**; `personal-os.yml` selbst besteht die Pin-Prüfung (OK in Log).
  Re-Pinning der übrigen Workflows liegt außerhalb des freigegebenen Umfangs.
- `actions/permissions` / Branch-Protection über das Token nicht lesbar (403).
- Lokale Runs ersetzen diesen Nachweis nicht — alle Angaben oben stammen aus der
  GitHub-Actions-API (`actions/runs`, `actions/runs/<id>/jobs`, Job-Logs).

## 5. Ergebnis

**BESTANDEN** — GitHub Actions hat die vollständige Mini-OS-Prüfung (Paket-Installation,
CLI-Smoke, volle Testsuite 171/171 auf Python 3.11 und 3.12, Formatierung/Linting via
pre-commit) auf dem aktuellen PR-Head `221a15a` erfolgreich ausgeführt (Run-IDs siehe
Abschnitt 3).

Technische Betriebsbereitschaft bleibt davon getrennt: Die produktive Nutzung wird durch
diesen Nachweis nicht automatisch freigegeben. PR #1 bleibt Draft (kein Merge ohne
Freigabe); keine weiteren Arbeitspakete; keine zusätzlichen Datenquellen; die
14-tägige Messphase startet nicht automatisch.
