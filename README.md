# (TOH) Inventory Management & Intelligence Prototype

An academic medication inventory dashboard developed for the University of Ottawa’s ELG 5902 Industry Project, Group 5.

The prototype demonstrates how medication inventory information can support clinical availability review, procurement, warehouse operations, and executive oversight.

The application uses synthetic data. Where TOH-specific requirements have not been confirmed, data fields, thresholds, and workflow interpretations remain project assumptions and team design proposals.

This is an educational prototype, not a system for clinical or purchasing decisions.

## Current implementation

The application includes:

- Four audience tabs: Clinical, Procurement, Warehouse, and Executive.
- Illustrated role icons and audience-specific process descriptions.
- The Ottawa Hospital and uOttawa logos in the application header.
- Shared styling, readable typography, and responsive layouts.
- Original and extended synthetic medication datasets.
- CSV loading, configurable field mapping, and data validation.
- Readable table labels and date-only formatting.
- Medication lookup and stock-aware Clinical request previews.
- Shared stock-review indicators, badges, chart colors, and legends.
- Stock charts grouped by physical stock unit.
- Representative warehouse locations and historical count observations.
- Aggregate Executive summaries.
- Always-visible native table controls for column visibility, CSV download, search, and fullscreen.
- Clearly labelled placeholders for features requiring further requirements or supporting data.
- Automated tests for loading, request previews, inventory-review rules, navigation callbacks, and Executive summaries.

| View | Main information |
| --- | --- |
| Clinical | Medication lookup, recorded availability, stock units, inventory-review context, and unsaved request previews |
| Procurement | Stock, consumption, costs, suppliers, expiry dates, illustrative thresholds, lead times, and stock charts |
| Warehouse | Recorded stock, representative locations, expiry dates, historical count observations, inventory-review context, and stock charts |
| Executive | Aggregate inventory summaries, supplier information, and clearly labelled KPI placeholders |

All four views are available during the demonstration. Tabs do not provide authentication or role-based access restrictions.

Clinical previews do not submit requests, approve medication, or change inventory. Leaving Clinical clears its selected medication and previous preview.

## Demonstration datasets

The repository contains two synthetic datasets:

| Dataset | Records | Fields | Purpose |
| --- | ---: | ---: | --- |
| `data/sample_medications.csv` | 6 | 10 | Original demonstration dataset |
| `data/sample_medications_extended.csv` | 6 | 16 | Extended dataset with optional inventory fields |

The extended dataset is the application default. It preserves the original medication records and fields while adding six optional fields.

Each row represents one medication record with one representative location and expiry attribute. Multiple lots, simultaneous storage locations, and inventory transactions are not modeled.

Historical count observations are kept separate from current recorded stock.

### Field definitions

| Field | Description |
| --- | --- |
| `medication_id` | Unique sample medication identifier |
| `medication_name` | Medication name and strength |
| `category` | Dosage-form category, not ABC classification |
| `stock_unit` | Physical unit used for quantities, such as tablet, capsule, or vial |
| `current_stock` | Current recorded quantity in the row’s stock unit |
| `unit_cost` | Synthetic CAD cost per stock unit |
| `average_monthly_consumption` | Synthetic monthly consumption in stock units |
| `expiry_date` | Representative expiry date associated with the record |
| `supplier` | Fictional supplier |
| `status` | Basic recorded-stock availability label |
| `primary_location` | Optional representative storage location |
| `reorder_point` | Optional illustrative reorder threshold |
| `safety_stock_level` | Optional illustrative safety-stock quantity |
| `lead_time_days` | Optional synthetic replenishment lead time |
| `last_count_date` | Optional date of a historical synthetic count |
| `counted_stock` | Optional quantity observed during that count |

The field names and optional extension fields are provisional. They are not confirmed TOH operational fields or measurements.

## Data loading and validation

The loader:

- Preserves identifiers as strings, including leading zeros.
- Trims surrounding whitespace from headers and values.
- Applies configured source-field mappings.
- Rejects duplicate field names after normalization or mapping.
- Requires medication IDs, medication names, and recorded stock.
- Rejects empty datasets, missing identifiers, and duplicate medication IDs.
- Parses known numeric fields when present.
- Rejects nonnumeric, negative, and infinite numeric values.
- Requires a recorded-stock value for every medication.
- Parses date fields using `YYYY-MM-DD`.
- Rejects invalid date formats and invalid calendar dates.
- Preserves missing optional values rather than replacing them with zero.
- Checks supplied availability labels against recorded stock.
- Derives missing basic availability labels.
- Retains additional source columns for future use.

Tables use display copies of the loaded data. Internal field names receive readable labels, dates display without time components, and unavailable display information is labelled appropriately.

Presentation formatting does not modify source CSV files or bypass loader validation.

Recorded availability and illustrative stock-review indicators do not confirm physical stock, clinical suitability, or usable expiry.

## Requirements

- Python 3.12.
- Git.
- Python dependencies listed in `requirements.txt`.

Core application dependencies:

| Package | Pinned version |
| --- | --- |
| Streamlit | 1.65.0 |
| Pandas | 3.0.6 |
| Plotly | 7.1.0 |

Tests use Python’s built-in `unittest` framework.

Use the pinned dependencies when reproducing the application. Native table styling and navigation behavior should be checked before upgrading Streamlit.

## Local setup — macOS

Clone the repository:

```bash
git clone https://github.com/mdkamrulamin/toh-inventory-management-intelligence-prototype.git
cd toh-inventory-management-intelligence-prototype
```

Create and activate a virtual environment using Python 3.12:

```bash
python3.12 -m venv .venv
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

If your local project folder has a different name, use that folder as the project root.

## Select the demonstration dataset

The default dataset is configured in `src/config.py`.

To use the extended dataset:

```python
SAMPLE_MEDICATIONS_PATH = PROJECT_ROOT / "data" / "sample_medications_extended.csv"
```

To use the original dataset:

```python
SAMPLE_MEDICATIONS_PATH = PROJECT_ROOT / "data" / "sample_medications.csv"
```

After changing the path, save the file and stop/restart Streamlit so imported settings and loader defaults are refreshed.

Restore the extended dataset when finished checking the original dataset.

### Verify dataset shapes

From the project root, check the original dataset:

```bash
python -c "from src.data.loader import load_medications; print(load_medications('data/sample_medications.csv').shape)"
```

Expected output:

```text
(6, 10)
```

Check the extended dataset:

```bash
python -c "from src.data.loader import load_medications; print(load_medications('data/sample_medications_extended.csv').shape)"
```

Expected output:

```text
(6, 16)
```

## Project structure

| Location | Purpose |
| --- | --- |
| `app.py` | Application entry point, shared loading, and role-view rendering |
| `.streamlit/config.toml` | Theme, typography, and native data-export settings |
| `src/config.py` | Application notices, role labels, icon filenames, field labels, and data path |
| `src/data/schema.py` | Required fields, optional fields, numeric/date fields, and column mapping |
| `src/data/loader.py` | CSV loading, parsing, validation, and basic availability checks |
| `src/services/clinical.py` | Clinical request-stock comparison |
| `src/services/replenishment.py` | Illustrative inventory-review context |
| `src/services/summary.py` | Executive summary preparation |
| `src/ui/components.py` | Shared medication tables, stock charts, and placeholders |
| `src/ui/navigation.py` | Role tabs and Clinical selection-reset callback |
| `src/ui/stock_indicators.py` | Shared review styles, badges, and legends |
| `src/ui/styles.py` | Stylesheet loading, branded header, role headings, and chart styling |
| `src/ui/styles.css` | Shared dashboard and native table-toolbar presentation |
| `src/ui/icons.py` | Local role-icon loading |
| `src/ui/views/__init__.py` | Mapping of role IDs to view functions |
| `src/ui/views/clinical.py` | Clinical lookup, availability, and request-preview view |
| `src/ui/views/procurement_inventory.py` | Procurement inventory and replenishment-context view |
| `src/ui/views/warehouse.py` | Warehouse stock and historical-count view |
| `src/ui/views/executive.py` | Executive overview and KPI placeholders |
| `assets/icons/` | Illustrated role icons and source references |
| `assets/logos/` | Institutional header images |
| `data/sample_medications.csv` | Original synthetic dataset |
| `data/sample_medications_extended.csv` | Extended synthetic dataset |
| `tests/test_loader.py` | Loader and dataset checks |
| `tests/test_clinical.py` | Clinical request-preview checks |
| `tests/test_replenishment.py` | Inventory-review rule checks |
| `tests/test_navigation.py` | Navigation callback checks |
| `tests/test_summary.py` | Executive summary checks |
| `docs/` | Supporting technical documentation |
| `requirements.txt` | Pinned Python dependencies |
| `.gitignore` | Files excluded from version control |
| `README.md` | Project overview, setup, and test instructions |

Python package initialization files are included under `src/`.

Data loading, inventory services, shared presentation, and role-specific views are separated so requirements can be revised without placing all application logic in one file.

## Run automated tests

Run test commands from the project root with the virtual environment active:

```bash
source .venv/bin/activate
```

### Run the complete suite

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

The committed test suite contains:

| Test module | Test methods |
| --- | ---: |
| `test_loader.py` | 11 |
| `test_clinical.py` | 8 |
| `test_replenishment.py` | 12 |
| `test_navigation.py` | 3 |
| `test_summary.py` | 5 |
| Total | 39 |

A successful run ends with `OK`. Execution time varies.

Some methods include multiple subcases, so the number of checked scenarios exceeds the test-method count.

### Loader tests

```bash
python -m unittest discover -s tests -p "test_loader.py" -v
```

Expected: **11 tests**.

These cover:

- Compatibility between the original and extended datasets.
- Preservation of original field values.
- Optional numeric and date types.
- Missing optional values.
- Invalid numeric values and dates.
- Required stock values.
- Availability-label consistency.
- Leading-zero identifiers.
- Duplicate identifiers.
- Missing required columns.

### Clinical request-preview tests

```bash
python -m unittest discover -s tests -p "test_clinical.py" -v
```

Expected: **8 tests**.

These cover:

- Zero-stock, sufficient-stock, and insufficient-stock outcomes.
- Requests equal to recorded stock.
- Medication identity and stock-unit preservation.
- Invalid request quantities.
- Historical counts remaining separate from recorded stock.
- Source records remaining unchanged.

### Replenishment-review tests

```bash
python -m unittest discover -s tests -p "test_replenishment.py" -v
```

Expected: **12 tests**.

These cover:

- Zero-stock handling.
- Reorder-threshold boundaries.
- Missing and blank thresholds.
- Explicit zero thresholds.
- Missing and blank stock units.
- Supporting fields not overriding recorded-stock review.
- Expected behavior with both demonstration datasets.
- Source data remaining unchanged.

### Navigation callback tests

```bash
python -m unittest discover -s tests -p "test_navigation.py" -v
```

Expected: **3 tests**.

These cover:

- Clearing the Clinical lookup when another role is selected.
- Keeping the selection when the callback identifies Clinical as active.
- Preserving unrelated session-state values.

The tests use mocked session state. Real browser navigation and preview visibility still require manual checking.

### Executive summary tests

```bash
python -m unittest discover -s tests -p "test_summary.py" -v
```

Expected: **5 tests**.

These cover:

- Expected summaries with both demonstration datasets.
- Missing cost information.
- Unavailable supplier information.
- Empty datasets.
- Source data remaining unchanged.

### Run one test method

Use `-k` with a method name from the verbose test output.

For example, to check invalid loader numeric values:

```bash
python -m unittest discover -s tests -p "test_loader.py" -k "test_invalid_numbers_are_rejected" -v
```

To check a Clinical request exceeding recorded stock:

```bash
python -m unittest discover -s tests -p "test_clinical.py" -k "test_quantity_above_stock_requires_review" -v
```

All subcases within the selected method run together.

Automated tests complement manual checks for browser layout, navigation, table tools, downloads, chart readability, and displayed previews.

## Research and implementation traceability

The prototype draws on the team’s literature review, process analysis, inventory frameworks, and dashboard requirements.

Project documentation distinguishes research findings, supervisor guidance, team assumptions, synthetic inputs, implemented behavior, and deferred features.

Research informs the proposed approach. It does not establish that the demonstration’s fields, thresholds, or workflow choices have been validated for TOH.

Supporting technical documentation maintains the relationship between requirements, implementation, and verification.

A visible placeholder identifies a proposed feature; it does not indicate that the underlying workflow or analytics has been implemented.

## Deferred features and scope limitations

The current prototype does not implement:

- Persisted medication requests or clinical/pharmacy approvals.
- Validated substitute-product recommendations.
- Confirmed clinical availability alerts.
- ABC or clinical-criticality classification.
- Replenishment-method selection or calculated order quantities.
- Purchase-order processing.
- Batch-specific expiry monitoring or FEFO decisions.
- Receiving, picking, dispatch, transfers, or stock transactions.
- Inventory reconciliation or verified stock-accuracy assessment.
- Historical performance reporting or inventory-turnover analysis.
- Separate Pharmacist or Reporting views.
- Patient records or patient-facing workflows.
- Authentication or role-based authorization.
- Live TOH/ERP integration.
- Production databases, automated dispensing, forecasting engines, AI models, or advanced optimization.

The demonstration uses one record per medication, with one representative location and expiry attribute.

Historical count observations do not confirm current stock accuracy, loss, or shrinkage.

CSV downloads use Streamlit-generated timestamp filenames. They contain data values and headers, not the table’s visual styling.

Emergency workflows are outside the proposed prototype process.

No request is submitted or approved, no stock is deducted, and no purchasing action is executed.

The application must not be used for clinical or purchasing decisions.

## Assets and credits

Illustrated role icons are stored locally in `assets/icons/`.

Icon source references are recorded in [assets/icons/CREDITS.md](assets/icons/CREDITS.md).

Institutional header images are stored in `assets/logos/`.

The academic demonstration does not imply operational deployment or institutional endorsement.

## Team and contributions

Developed by ELG 5902 Group 5:

- Md Kamrul Hasan Bin Amin
- Maria
- Maryam
- Mohtasim
- Sai Prasanna

The prototype incorporates the team’s literature findings, process analysis, inventory frameworks, dashboard requirements, and software implementation.