# (TOH) Inventory Management & Intelligence Prototype

A literature-informed academic medication inventory dashboard developed for the University of Ottawa’s ELG 5902 Industry Project, Group 5.

The prototype demonstrates how medication inventory information can support clinical availability review, procurement and ordering review, warehouse operations, and executive oversight.

All inventory values are synthetic. The application does not represent actual TOH operations or provide validated clinical or purchasing decisions.

## Current implementation

The application includes:

- Four audience tabs with dedicated view modules.
- Shared audience labels, process-context descriptions, and prototype notices.
- Original and extended synthetic medication datasets.
- CSV loading, configurable column mapping, and data validation.
- Centrally configured readable table labels, separate from internal field names.
- Date-only table formatting using `YYYY-MM-DD`.
- Compact stock charts separated by physical stock unit.
- Clinical medication lookup with selected recorded stock, unit, and availability status.
- Stock-aware, nonpersisted Clinical request previews.
- Illustrative replenishment-review flags.
- Representative warehouse locations and historical count observations.
- Aggregate-only Executive snapshot summaries and synthetic inventory valuation.
- Clearly labelled placeholders for features outside the implemented scope.
- Automated checks for loading, Clinical previews, replenishment context, and Executive summaries.

| Audience | Current content |
| --- | --- |
| Clinical — Doctor + Nurse | Medication lookup, selected recorded stock/unit/status, and stock-aware demo request previews for zero, sufficient, or insufficient recorded stock; placeholders for clinical/pharmacy review, approved substitute information, and alerts |
| Procurement + Inventory/Ordering | Stock, consumption, date-only expiry information, unit costs, suppliers, optional thresholds and lead times, illustrative ordering-review flags, and compact stock charts; ABC and replenishment-method placeholders |
| Warehouse | Recorded stock, representative locations and expiry dates, historical count dates and quantities, and compact stock charts; receiving, picking, expiry-monitoring, and reconciliation placeholders |
| Executive | Aggregate sample SKU count, zero-stock count and snapshot share, known suppliers, and synthetic inventory value; inventory-turnover and further performance/risk placeholders |

The four audiences follow supervisor guidance. Detailed fields, widget choices, illustrative thresholds, and display behavior remain team design proposals informed by research.

All four tabs are accessible during the demonstration. Tab navigation does not implement authentication or role-based authorization.

Patients may participate in the proposed process map but have no dashboard page. Finance information is included within Procurement and Executive rather than a separate fifth page.

## S3-05 polish and MVP freeze status

SCRUM-43 / S3-05 covers three final UI changes:

1. Make the Clinical medication lookup and request preview stock-aware.
2. Display Procurement expiry dates without a time component.
3. Reduce excess vertical whitespace in Procurement and Warehouse stock charts.

The baseline before these changes was commit `84d2a4e`, which keeps the Executive dashboard focused on aggregate summaries.

**S3-05 verification and MVP freeze review are pending.**

The expected automated test suite contains 30 test methods. An expected total is not a recorded passing result.

The prospective freeze baseline must be the new commit containing these changes. Record its hash, actual test results, both-dataset UI outcomes, screenshots, and any remaining blockers.

Do not mark SCRUM-43 frozen until the main project review has accepted the final evidence.

## Demonstration datasets

### Original dataset

`data/sample_medications.csv` contains the original six medication records and ten fields.

It remains available for backward-compatibility and regression checks.

### Extended dataset

`data/sample_medications_extended.csv` contains the same six records and original ten fields, plus six optional demonstration fields.

The extended dataset is the default selected in `src/config.py`.

### Field definitions

| Field | Meaning |
| --- | --- |
| `medication_id` | Unique sample medication identifier |
| `medication_name` | Medication name and strength |
| `category` | Dosage-form category, such as Tablet, Capsule, or Injection; not ABC classification |
| `stock_unit` | Physical unit used for quantities, such as tablet, capsule, or vial |
| `current_stock` | Recorded quantity in the row’s stock unit |
| `unit_cost` | Synthetic CAD cost per stock unit |
| `average_monthly_consumption` | Synthetic stock units consumed per month |
| `expiry_date` | Representative expiry date associated with the medication record |
| `supplier` | Fictional supplier |
| `status` | Basic recorded-stock availability label |
| `primary_location` | Optional single representative storage location |
| `reorder_point` | Optional illustrative replenishment threshold |
| `safety_stock_level` | Optional illustrative safety-stock quantity |
| `lead_time_days` | Optional synthetic replenishment lead time |
| `last_count_date` | Optional date of a historical synthetic count |
| `counted_stock` | Optional quantity observed during that historical count |

The optional extension fields are not confirmed TOH fields or measurements.

Each row represents one medication/SKU with one representative location and expiry attribute. Multiple lots, simultaneous locations, stock transactions, and historical inventory balances are not modeled.

MED001 and MED004 intentionally have historical counted quantities that differ from current recorded stock. Transactions since those counts are unknown, so these differences do not establish stock inaccuracy, loss, or shrinkage.

## Data validation and presentation

The loader:

- Reads identifiers as strings to preserve leading zeros.
- Normalizes surrounding whitespace and applies configured column mappings.
- Checks for duplicate fields after normalization/mapping.
- Requires `medication_id`, `medication_name`, and `current_stock`.
- Rejects empty datasets, missing identifiers, and duplicate medication IDs.
- Parses known numeric fields only when present.
- Rejects negative, nonnumeric, and infinite numeric values.
- Requires a stock quantity on every record.
- Parses present date fields using `YYYY-MM-DD`.
- Rejects invalid date formats and calendar dates.
- Preserves missing optional values rather than replacing them with zero.
- Checks supplied availability labels against recorded stock.

Basic availability uses:

- `In stock` when recorded stock is positive.
- `Out of stock` when recorded stock is zero.

Missing availability labels are derived from these rules. Conflicting supplied labels are rejected.

This availability classification does not establish physical availability, clinical suitability, usable expiry, or availability elsewhere.

The shared table component formats a display copy:

- Internal field names receive readable display labels.
- Present date fields display as `YYYY-MM-DD`.
- Missing or unparseable display dates appear as `N/A`.
- Loader datetime values and source CSV files are not modified.

Invalid dates in source CSVs remain subject to loader validation; presentation formatting does not bypass those checks.

## Clinical request previews

The Clinical view displays the selected medication’s name, ID, recorded stock, stock unit, and basic recorded availability.

A demo request uses a positive whole-number quantity and compares it with the selected record’s `current_stock`.

| Recorded condition | Preview outcome |
| --- | --- |
| Recorded stock equals zero | Unable to fulfill from recorded stock; pharmacy review is required |
| Positive recorded stock is greater than or equal to the requested quantity | Sufficient recorded stock for the requested quantity; proposed next step is pharmacist verification |
| Positive recorded stock is below the requested quantity | Requested quantity exceeds recorded stock; review is needed before fulfillment |

Every preview identifies the selected medication, medication ID, requested quantity, stock unit, and recorded-stock comparison.

The zero-stock message describes possible steps in the proposed process: internal redistribution, clinically authorized alternatives, or procurement escalation. It does not recommend a particular substitute or initiate any action.

The sufficient-stock message explicitly distinguishes the synthetic record from a physical stock confirmation.

Changing the selected medication or committing a quantity edit clears the previous preview. Clicking **Preview demo request** evaluates the current inputs.

Invalid or missing request quantities are rejected with a validation message.

Nothing is saved, sent, deducted, or approved. Historical `counted_stock` observations are never used to replace `current_stock`.

Clinical/pharmacy review, approved substitute information, and availability alerts remain clearly labelled placeholders.

## Illustrative replenishment context

The Procurement view displays optional reorder points, safety-stock levels, and lead times.

Ordering-review context follows these demonstration rules:

| Recorded condition | Displayed context |
| --- | --- |
| Stock equals zero | Recorded stock = 0 — availability/order review |
| Positive stock is at or below a supplied reorder point | At/below illustrative reorder threshold — review |
| Positive stock exceeds a supplied reorder point | Above illustrative reorder threshold |
| Positive stock has no supplied reorder point | N/A — reorder threshold unavailable |

Thresholds are synthetic, client-unvalidated examples. Safety stock and lead time are displayed as context; they are not used to calculate an order quantity.

The application does not create purchase orders, select a universal replenishment method, or automatically order medication.

## Stock charts

Procurement and Warehouse use the same reusable stock-chart component.

Charts:

- Keep tablet, capsule, and vial quantities separate.
- Adjust height according to the number of medication rows in each unit group.
- Preserve medication labels, axis labels, values, and hover information.
- Retain zero-stock medication categories, including MED003.
- Leave space for value labels and readable one-item groups.

Unlike physical stock units are never summed into one stock total.

The Executive view does not display item-level stock charts.

## Executive snapshot summaries

Both complete sample datasets produce:

| Summary | Expected value |
| --- | ---: |
| Sample SKUs | 6 |
| Recorded zero-stock SKUs | 1 |
| Zero-stock share — snapshot | 16.7% |
| Sample inventory value | CAD 801.00 |
| Known demo suppliers | 3 |
| Inventory turnover | N/A — placeholder |

Zero-stock share is calculated as:

`zero-stock SKU count / total SKU count × 100`

It describes the sample snapshot, not a stockout rate over time.

Synthetic inventory value is calculated as:

`sum(current_stock × unit_cost)`

Monetary values share the CAD unit and can be summed. Physical quantities in tablets, capsules, and vials are not combined into one stock total.

If any unit cost is missing, the total valuation remains unavailable rather than showing a partial total. Supplier information remains unavailable when the supplier column or all its values are missing.

Inventory turnover is a prominently labelled illustrative KPI slot. No turnover value is calculated because its reporting period, definition, and supporting historical records remain to be confirmed.

## Requirements

- Python 3.12
- Git
- Dependencies listed in `requirements.txt`

The application uses Streamlit, Pandas, and Plotly.

Tests use Python’s built-in `unittest` framework. No separate test-framework dependency is required.

## Local setup — macOS

Clone the repository:

```bash
git clone https://github.com/mdkamrulamin/toh-inventory-management-intelligence-prototype.git
cd toh-inventory-management-intelligence-prototype
```

Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

Run the application:

```bash
python -m streamlit run app.py
```

Open the local URL printed in the terminal.

Press `Ctrl+C` to stop the application.

For later sessions, run these commands from the project root:

```bash
source .venv/bin/activate
python -m streamlit run app.py
```

## Select the demonstration dataset

The default path is configured in `src/config.py`.

For the extended dataset:

```python
SAMPLE_MEDICATIONS_PATH = PROJECT_ROOT / "data" / "sample_medications_extended.csv"
```

For the original dataset:

```python
SAMPLE_MEDICATIONS_PATH = PROJECT_ROOT / "data" / "sample_medications.csv"
```

After changing this configuration, save the file and restart Streamlit so imported settings and loader defaults are refreshed.

Restore the extended dataset as the default after completing cross-dataset verification.

Loader and Executive summary regression tests use explicit dataset paths to check both files regardless of the selected application default.

### Verify dataset shapes

From the project root:

```bash
python -c "from src.data.loader import load_medications; print(load_medications('data/sample_medications.csv').shape)"
```

Expected:

```text
(6, 10)
```

For the extended dataset:

```bash
python -c "from src.data.loader import load_medications; print(load_medications('data/sample_medications_extended.csv').shape)"
```

Expected:

```text
(6, 16)
```

## Project structure

| Location | Purpose |
| --- | --- |
| `app.py` | Streamlit entry point, shared loading, tab routing, and audience context |
| `src/config.py` | Application notices, role IDs/labels, process context, table labels, and default data path |
| `src/data/schema.py` | Required fields, optional extension fields, numeric/date fields, and column mapping |
| `src/data/loader.py` | CSV loading, parsing, validation, and basic availability checks |
| `src/services/clinical.py` | Validated, nonmutating Clinical request-stock comparison |
| `src/services/replenishment.py` | Illustrative ordering-review context |
| `src/services/summary.py` | Executive snapshot counts, share, and synthetic valuation |
| `src/ui/components.py` | Reusable date-formatted tables, compact stock charts, and feature placeholders |
| `src/ui/navigation.py` | Four-audience tab creation |
| `src/ui/views/__init__.py` | Mapping of role IDs to view functions |
| `src/ui/views/clinical.py` | Clinical lookup, selected availability, and stock-aware request-preview view |
| `src/ui/views/procurement_inventory.py` | Procurement information and replenishment-context view |
| `src/ui/views/warehouse.py` | Representative locations, expiry, and historical-count view |
| `src/ui/views/executive.py` | Aggregate-only Executive snapshot and KPI-placeholder view |
| `data/sample_medications.csv` | Original six-record, ten-field synthetic dataset |
| `data/sample_medications_extended.csv` | Extended six-record, sixteen-field synthetic dataset |
| `tests/test_loader.py` | Loader and dataset regression checks |
| `tests/test_clinical.py` | Clinical preview outcomes, validation, identity/units, and nonmutation checks |
| `tests/test_replenishment.py` | Ordering-review boundary and missing-input checks |
| `tests/test_summary.py` | Executive calculations and missing-data checks |
| `requirements.txt` | Python dependencies |
| `.gitignore` | Files excluded from version control |
| `README.md` | Scope, setup, behavior, and verification instructions |

Python package initialization files are also included under `src/`.

Current role views are organized under `src/ui/views/`.

## Run automated tests

Run commands from the project root with the virtual environment active:

```bash
source .venv/bin/activate
```

### Run all tests

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

Expected result: **30 test methods**, followed by `OK`.

Some methods include several input subcases, so more than 30 individual scenarios are checked.

| Test file | Expected test methods |
| --- | ---: |
| `test_loader.py` | 11 |
| `test_clinical.py` | 8 |
| `test_replenishment.py` | 6 |
| `test_summary.py` | 5 |
| Total | 30 |

Record the actual passing total during S3-05 verification.

### Run loader tests only

```bash
python -m unittest discover -s tests -p "test_loader.py" -v
```

Expected: **11 tests**.

These check:

- Original and extended dataset shapes and preservation of original values.
- Optional numeric/date types.
- Missing optional values.
- Invalid numbers and dates.
- Missing required stock.
- Conflicting availability labels.
- Derivation of missing availability labels.
- Leading-zero identifiers.
- Duplicate identifiers.
- Missing required columns.

### Run Clinical request-preview tests only

```bash
python -m unittest discover -s tests -p "test_clinical.py" -v
```

Expected: **8 tests**.

These check:

- Zero recorded stock requires review.
- Sufficient recorded stock.
- Requested quantity equal to recorded stock.
- Requested quantity above recorded stock.
- Selected medication identity and stock unit.
- Invalid or missing request quantities.
- Historical counts do not replace recorded stock.
- Source inventory data is not modified.

These comparisons are educational UI decision support using synthetic recorded stock. They do not confirm physical availability, assess clinical suitability, approve treatment, or submit requests.

### Run replenishment tests only

```bash
python -m unittest discover -s tests -p "test_replenishment.py" -v
```

Expected: **6 tests**.

These check:

- Zero stock has its own flag.
- Stock below or equal to the reorder threshold requires review.
- Stock above the threshold has the correct label.
- Absent optional columns remain missing.
- Blank reorder thresholds remain unavailable.
- Source inventory data is not modified.

### Run Executive summary tests only

```bash
python -m unittest discover -s tests -p "test_summary.py" -v
```

Expected: **5 tests**.

These check:

- Both datasets produce the expected snapshot summaries.
- Missing costs prevent partial valuation.
- Missing supplier information remains unavailable.
- Empty snapshots avoid undefined rates or valuations.
- Source inventory data is not modified.

### Run one individual test method

Use `-k` with a test method name. Method names appear in the verbose output.

To check invalid loader numeric inputs:

```bash
python -m unittest discover -s tests -p "test_loader.py" -k "test_invalid_numbers_are_rejected" -v
```

To check a Clinical request exceeding recorded stock:

```bash
python -m unittest discover -s tests -p "test_clinical.py" -k "test_quantity_above_stock_requires_review" -v
```

To check the reorder boundary:

```bash
python -m unittest discover -s tests -p "test_replenishment.py" -k "test_below_and_equal_threshold_require_review" -v
```

To check missing-cost handling:

```bash
python -m unittest discover -s tests -p "test_summary.py" -k "test_missing_cost_prevents_partial_valuation" -v
```

Subcases within the selected method run together.

Automated tests check data and service behavior. They do not replace manual Streamlit checks for stale previews, date display, chart readability, or tab rendering.

## Manual dashboard verification

Complete this checklist with both the original and extended datasets.

### Common checks

- Exactly four audience tabs are available.
- Each tab displays its audience heading and process context.
- The shared notice identifies the application as an educational prototype using synthetic data.
- The demo notice states that tab navigation has no sign-in or access control.
- Planned sections are clearly labelled as illustrative placeholders.
- No patient-facing route exists.
- Tabs open without errors when optional extension columns are absent.

### Clinical

- The initial availability table contains six medications.
- Selecting a medication displays its name, ID, recorded stock, stock unit, and recorded availability.
- MED003 — Ibuprofen 200 mg, quantity 3: zero-stock pharmacy-review outcome.
- MED001 — Paracetamol 500 mg, quantity 3: sufficient-recorded-stock outcome with proposed pharmacist verification.
- MED001, quantity 1500: insufficient-recorded-stock outcome.
- Selecting capsule and vial medications displays the correct units in the preview.
- Every result includes the selected name, ID, requested quantity, unit, and recorded-stock comparison.
- Changing medication after a preview clears the old result.
- Committing a quantity edit after a preview clears the old result.
- Clicking Preview again evaluates the current medication and quantity.
- Repeated previews and refreshes do not change recorded stock or save requests.
- Review-status, approved-substitute, and availability-alert placeholders remain present.
- Costs and supplier commercial information are absent.
- No unvalidated substitute is recommended or approved.

### Procurement + Inventory/Ordering

- Stock, consumption, expiry, costs, and suppliers are visible.
- Expiry dates display as `YYYY-MM-DD`, without `00:00:00`.
- Missing display dates appear as `N/A`, not `NaT`.
- Extended inputs display illustrative thresholds and lead times.
- MED003 has the distinct zero-stock review flag.
- With the extended dataset, MED006 has stock 80 and reorder point 90, so it is flagged for review.
- With the original dataset, MED006 has positive stock but no reorder point, so its threshold context is unavailable.
- Missing optional thresholds and lead times display `N/A`.
- Dosage-form category is not presented as ABC class.
- No purchase order or order quantity is created.

### Warehouse

- Stock quantities retain their physical units.
- Extended inputs display representative storage locations.
- Expiry and count dates display as `YYYY-MM-DD`.
- MED001 retains current stock 1,200 alongside past counted stock 1,195.
- MED004 retains current stock 900 alongside past counted stock 895.
- Historical counts do not overwrite current stock.
- Missing location/count information displays `N/A`.
- Expiry monitoring, receiving/picking, and stock-movement/reconciliation placeholders remain present.
- No batch-level FEFO, stock-accuracy, loss, or shrinkage conclusion is claimed.

### Procurement and Warehouse charts

- Tablet, capsule, and vial charts remain separate.
- Chart heights are compact at normal browser width.
- Medication labels, axis labels, values, and hover information remain readable.
- MED003/Ibuprofen remains visible as a zero-stock category.
- The one-item vial chart remains comfortably readable.
- Labels do not overlap or clip.
- No medication rows or synthetic quantities are changed.

### Executive

- Cards show six SKUs, one recorded zero-stock SKU, and a 16.7% zero-stock snapshot share.
- Synthetic inventory value is CAD 801.00 with either complete sample dataset.
- Known demo suppliers total three.
- Inventory turnover remains a labelled `N/A` placeholder.
- Only aggregate summaries and broad placeholders are shown; no item-level stock chart is present.
- Snapshot results are not presented as actual TOH performance or historical trends.

After checking the original dataset, restore the extended dataset as the default and confirm it loads correctly.

## S3-05 release evidence

Capture the following screenshots:

1. Clinical MED003 with requested quantity 3 and its preview.
2. Clinical MED001 with requested quantity 3 and its preview.
3. Clinical MED001 with requested quantity 1500 and its preview.
4. Procurement date-only table and compact stock charts.
5. Warehouse compact stock charts.
6. Executive aggregate overview.

Use additional screenshots if needed to show all chart groups clearly.

After verification, record:

- Actual automated test command, passing total, and result.
- Manual outcomes for both datasets.
- Screenshot references.
- Exact changed-file list.
- Final commit hash and branch.
- Confirmation that the commit is pushed.
- Confirmation that the working tree is clean.
- Any unresolved defect or blocker.

Before committing, review:

```bash
git diff --check
git diff
git status --short
```

After committing and pushing, collect:

```bash
git branch --show-current
git status --short
git log -1 --oneline
git show --format= --name-only HEAD
```

An empty `git status --short` output indicates a clean working tree.

The intended S3-05 changed files are:

- `README.md`
- `src/services/clinical.py`
- `src/ui/components.py`
- `src/ui/views/clinical.py`
- `tests/test_clinical.py`

The temporary dataset switch should leave no change in `src/config.py` after the extended default is restored.

## Research and implementation traceability

The prototype distinguishes:

- Supervisor guidance.
- Paper evidence.
- Project design inference.
- Synthetic input assumptions.
- Derived demonstration results.
- Actual tested implementation.
- Deferred features and placeholders.

The S3-05 handover identifies Maria P020 as the basis for distinguishing recorded stock from verified physical availability. Maria’s proposed S1–S5 medication process and Sai P001/substitute framework inform the review and clinical-authorization boundaries.

The three-way request-stock comparison is a project UI interpretation using synthetic data, not a clinical decision rule validated by TOH.

Date formatting and chart sizing are presentation design choices. They should not be attributed to papers as prescribed implementation rules.

| S3-05 change | Implementation paths | Task 24 linkage |
| --- | --- | --- |
| Stock-aware Clinical preview | `src/services/clinical.py`, `src/ui/views/clinical.py`, `tests/test_clinical.py` | UI24-04, UI24-05, UI24-06 |
| Date-only table display | `src/ui/components.py` | UI24-07, UI24-12 |
| Compact unit-separated charts | `src/ui/components.py` | UI24-07, UI24-12, UI24-19 |
| Verification and handover | Tests, README, screenshots, and final commit | UI24-20 |

Update the project traceability workbook with the verified code paths, source IDs, actual test/manual results, and final S3-05 commit.

Verification of a placeholder means its label and scope boundary were checked. It does not mean the underlying analytics or workflow has been implemented.

## Scope and limitations

The application runs locally using CSV files, Python, Streamlit, Pandas, and Plotly.

Current limitations include:

- Synthetic inputs and illustrative thresholds.
- One record per medication/SKU.
- One representative location and expiry attribute per record.
- No transaction history, multiple-lot model, or multi-location inventory.
- Nonpersisted Clinical request previews.
- Recorded stock comparisons without physical-stock verification.
- No validated substitute relationships or clinical-criticality labels.
- Placeholder ABC classification, replenishment-method selection, and additional Executive KPIs.
- No actual turnover, longitudinal service-level, or stock-accuracy calculation.
- Demonstration tab navigation rather than authenticated role access.

No request is submitted or approved. No stock is deducted. No purchase order is created. No drug substitute is automatically recommended or authorized.

Production authentication, live TOH/ERP integration, automatic dispensing or ordering, enterprise databases, forecasting engines, and advanced optimization are outside the current implementation.

Emergency scenarios are outside the proposed prototype process.

This is an academic decision-support prototype. Its data, comparisons, and representative metrics must not be used for clinical or purchasing decisions.

## Next development stage

The immediate priority is to complete S3-05 verification, review the evidence, and agree on the MVP freeze baseline.

Further integration or implementation changes should follow the approved Sprint 3 plan and confirmed research requirements.

Future request/approval records, purchase orders, substitute relationships, stock movements, and multiple-lot/location data would require suitable supporting structures if confirmed in scope.

## Team and contributions

Developed by ELG 5902 Group 5:

- Md Kamrul Hasan Bin Amin
- Maria
- Maryam
- Mohtasim
- Sai Prasanna

The prototype incorporates the team’s literature findings, process analysis, inventory frameworks, and dashboard requirements alongside software implementation.

Detailed implementation choices remain team design proposals and assumptions where TOH-specific requirements or operational information have not been confirmed.