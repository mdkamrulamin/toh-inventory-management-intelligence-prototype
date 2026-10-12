# (TOH) Inventory Management & Intelligence Prototype

A literature-informed academic medication inventory dashboard developed for the University of Ottawa’s ELG 5902 Industry Project, Group 5.

The prototype demonstrates how medication inventory information can support clinical availability, procurement and ordering review, warehouse operations, and executive oversight.

All inventory values are synthetic. The application does not represent actual TOH operations or provide validated clinical or purchasing decisions.

## Current implementation

The application includes:

- Four audience tabs with dedicated view modules.
- Shared audience labels, process-context descriptions, and prototype notices.
- Original and extended synthetic medication datasets.
- CSV loading, configurable column mapping, and data validation.
- Reusable tables, stock charts, and clearly labelled feature placeholders.
- Clinical medication lookup and a nonpersisted request preview.
- Illustrative replenishment-review flags.
- Representative warehouse locations and historical count observations.
- Executive snapshot summaries and synthetic inventory valuation.
- Automated checks for loading, replenishment context, and executive summaries.

| Audience | Current content |
| --- | --- |
| Clinical — Doctor + Nurse | Medication lookup, recorded availability, stock units, and demo request preview; placeholders for clinical/pharmacy review, approved substitute information, and alerts |
| Procurement + Inventory/Ordering | Stock, consumption, expiry, unit costs, suppliers, optional thresholds and lead times, and illustrative ordering-review flags; ABC and replenishment-method placeholders |
| Warehouse | Recorded stock, representative locations and expiry dates, historical count dates and quantities, and stock charts; receiving, picking, expiry-monitoring, and reconciliation placeholders |
| Executive | Sample SKU count, zero-stock count and snapshot share, known suppliers, synthetic inventory value, and stock charts; inventory-turnover and further performance/risk placeholders |

The four audiences follow supervisor guidance. Detailed fields, widget choices, illustrative thresholds, and display behavior remain team design proposals informed by Sprint 2 research.

All four tabs are accessible during the demonstration. Tab navigation does not implement authentication or role-based authorization.

Patients may participate in the proposed process map but have no dashboard page. Finance information is included within Procurement and Executive rather than a separate fifth page.

## Demonstration datasets

### Original dataset

`data/sample_medications.csv` preserves the original six medication records and ten fields.

It remains available for backward-compatibility checks.

### Extended dataset

`data/sample_medications_extended.csv` contains the same six records and original ten fields, plus six optional demonstration fields.

The extended dataset is currently the default selected in `src/config.py`.

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

## Data validation

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

This availability classification does not establish clinical suitability, usable expiry, or availability elsewhere.

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

## Executive snapshot summaries

The current datasets produce:

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

The automated checks use explicit dataset paths and can check both files regardless of the selected application default.

## Project structure

| Location | Purpose |
| --- | --- |
| `app.py` | Streamlit entry point, shared loading, tab routing, and audience context |
| `src/config.py` | Application notices, role IDs/labels, process context, and default data path |
| `src/data/schema.py` | Required fields, optional extension fields, numeric/date fields, and column mapping |
| `src/data/loader.py` | CSV loading, parsing, validation, and basic availability checks |
| `src/services/replenishment.py` | Illustrative ordering-review context |
| `src/services/summary.py` | Executive snapshot counts, share, and synthetic valuation |
| `src/ui/components.py` | Reusable tables, stock charts, and feature placeholders |
| `src/ui/navigation.py` | Four-audience tab creation |
| `src/ui/views/__init__.py` | Mapping of role IDs to view functions |
| `src/ui/views/clinical.py` | Clinical lookup, availability, and request-preview view |
| `src/ui/views/procurement_inventory.py` | Procurement information and replenishment-context view |
| `src/ui/views/warehouse.py` | Representative locations, expiry, and historical-count view |
| `src/ui/views/executive.py` | Executive snapshot and KPI-placeholder view |
| `data/sample_medications.csv` | Original six-record, ten-field synthetic dataset |
| `data/sample_medications_extended.csv` | Extended six-record, sixteen-field synthetic dataset |
| `tests/test_loader.py` | Loader and dataset regression checks |
| `tests/test_replenishment.py` | Ordering-review boundary and missing-input checks |
| `tests/test_summary.py` | Executive calculations and missing-data checks |
| `requirements.txt` | Python dependencies |
| `.gitignore` | Files excluded from version control |
| `README.md` | Scope, setup, behavior, and verification instructions |

Python package initialization files are also included under `src/`.

An unused local `pages/` folder may remain from the initial setup. Current role views are organized under `src/ui/views/`.

## Run automated tests

Run commands from the project root with the virtual environment active:

```bash
source .venv/bin/activate
```

### Run all tests

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

Current expected result: **22 test methods**, followed by `OK`.

Some methods include several input subcases, so more than 22 individual scenarios are checked.

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

### Run executive summary tests only

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

For example, to check the reorder boundary:

```bash
python -m unittest discover -s tests -p "test_replenishment.py" -k "test_below_and_equal_threshold_require_review" -v
```

To check invalid numeric inputs:

```bash
python -m unittest discover -s tests -p "test_loader.py" -k "test_invalid_numbers_are_rejected" -v
```

To check missing-cost handling:

```bash
python -m unittest discover -s tests -p "test_summary.py" -k "test_missing_cost_prevents_partial_valuation" -v
```

Subcases within the selected method run together.

The current automated tests have passed locally. They check data and service behavior; they do not replace manual Streamlit interface checks.

## Manual dashboard verification

Use this checklist with both the original and extended datasets.

### Common checks

- Exactly four audience tabs are available.
- Each tab displays its audience heading and process context.
- The shared notice identifies the application as an educational prototype using synthetic data.
- Planned sections are clearly labelled as illustrative placeholders.
- No patient-facing route exists.
- Tabs open without errors when optional extension columns are absent.

### Clinical

- The initial availability table contains six medications.
- Selecting MED003 — Ibuprofen 200 mg shows zero stock.
- Selecting a medication displays its name, stock quantity, and stock unit.
- A request preview displays the selected medication and requested quantity.
- Previewing a request does not save or send it, change stock, or record approval.
- Costs and supplier commercial information are absent.
- No unvalidated substitute is recommended or approved.

### Procurement + Inventory/Ordering

- Stock, consumption, expiry, costs, and suppliers are visible.
- Extended inputs display the illustrative thresholds and lead times.
- MED003 has the distinct zero-stock review flag.
- With the extended dataset, MED006 has stock 80 and reorder point 90, so it is flagged for review.
- Missing optional thresholds display N/A.
- Dosage-form category is not presented as ABC class.
- No purchase order or order quantity is created.

### Warehouse

- Stock quantities retain their physical units.
- Extended inputs display representative storage locations.
- Expiry and count dates are readable as `YYYY-MM-DD`.
- MED001 retains current stock 1,200 alongside past counted stock 1,195.
- MED004 retains current stock 900 alongside past counted stock 895.
- Historical counts do not overwrite current stock.
- Missing location/count information displays N/A.
- No batch-level FEFO, stock-accuracy, loss, or shrinkage conclusion is claimed.

### Executive

- Cards show six SKUs, one zero-stock SKU, and a 16.7% zero-stock share.
- Synthetic inventory value is CAD 801.00 with either complete sample dataset.
- Known demo suppliers total three.
- Inventory turnover remains a labelled N/A placeholder.
- Stock charts keep different physical units separate.
- Snapshot results are not presented as actual TOH performance or historical trends.

## Scope and limitations

The application runs locally using CSV files, Python, Streamlit, Pandas, and Plotly.

Current limitations include:

- Synthetic inputs and illustrative thresholds.
- One record per medication/SKU.
- One representative location and expiry attribute per record.
- No transaction history, multiple-lot model, or multi-location inventory.
- Nonpersisted clinical request previews.
- No validated substitute relationships or clinical-criticality labels.
- Placeholder ABC classification, method selection, and additional executive KPIs.
- No actual turnover, longitudinal service-level, or stock-accuracy calculation.
- Demonstration tab navigation rather than authenticated role access.

Production authentication, live TOH/ERP integration, automatic dispensing or ordering, enterprise databases, forecasting engines, and AI assistants are outside the current implementation.

## Next development stage

Remaining refinement and integration work includes:

- Polish shared table display labels.
- Complete the final cross-dataset interface checklist for the refined views.
- Record verified requirement-to-code references and commit hashes in the project traceability workbook.
- Complete Task 25’s integration review and coherent MVP decision flow.
- Incorporate further approved field definitions, KPI definitions, and research refinements.

Future request/approval records, purchase orders, substitute relationships, stock movements, and multiple-lot/location data should use suitable supporting tables if confirmed in scope.

## Team and contributions

Developed by ELG 5902 Group 5:

- Md Kamrul Hasan Bin Amin
- Maria
- Maryam
- Mohtasim
- Sai Prasanna

The prototype incorporates the team’s literature findings, process analysis, inventory frameworks, and dashboard requirements alongside software implementation.

The implementation distinguishes supervisor guidance, literature-informed concepts, team design assumptions, synthetic inputs, derived demonstration values, and features deferred to later work.