# (TOH) Inventory Management & Intelligence Prototype

An academic medication inventory dashboard developed for the University of Ottawa’s ELG 5902 Industry Project, Group 5.

The prototype demonstrates how medication inventory information can support clinical availability, inventory operations, and executive oversight.

## Prototype status

The current prototype includes:

- A modular Streamlit application.
- Six synthetic medication records.
- CSV loading, configurable field mapping, and basic validation.
- Four audience tabs with dedicated view modules.
- Reusable inventory tables, stock charts, and feature placeholders.
- Executive summary cards calculated from the sample dataset.

| Audience | Implemented shell content |
| --- | --- |
| Clinical — Doctor + Nurse | Medication availability table; placeholders for substitute-product information and availability alerts |
| Procurement + Inventory/Ordering | Stock, consumption, costs, and suppliers; stock charts; placeholders for ABC classification and replenishment |
| Warehouse | Stock and expiry information; stock charts; placeholders for expiry monitoring, storage locations, and stock movements |
| Executive | Sample record, zero-stock record, and supplier counts; stock charts; placeholders for performance KPIs, risks, and costs |

Tabs provide demonstration audience navigation. They do not implement authentication or access restrictions.

Planned-feature sections are placeholders. Their detailed requirements, data fields, and calculation rules remain subject to team research and client confirmation.

## Demonstration data

`data/sample_medications.csv` contains six fictional medication inventory records. Stock quantities, costs, consumption values, expiry dates, and suppliers are synthetic.

| Field | Meaning |
| --- | --- |
| `medication_id` | Unique identifier for the sample medication record |
| `medication_name` | Medication name and strength |
| `category` | Illustrative dosage-form category |
| `stock_unit` | Unit used for stock quantities, such as tablet, capsule, or vial |
| `current_stock` | Quantity in the row’s stock unit |
| `unit_cost` | Demonstration cost in CAD per stock unit |
| `average_monthly_consumption` | Demonstration stock units consumed per month |
| `expiry_date` | Illustrative batch expiry date |
| `supplier` | Fictional supplier |
| `status` | Illustrative stock availability label stored in the CSV |

Each sample record represents one illustrative medication batch. The current dataset does not support multiple batches per medication, storage locations, or historical stock movements.

Stock charts separate tablets, capsules, and vials because their quantities use different units.

Executive cards display descriptive counts from the sample dataset:

- Six sample medication records.
- One record with zero stock.
- Three distinct demo suppliers.

The zero-stock count describes the current sample snapshot. It is not a stockout rate over time.

The dataset, field names, and dashboard sections are provisional and will be refined as the team confirms requirements.

This is an academic decision-support prototype. Demonstration data and representative metrics do not describe actual TOH inventory and must not be used for clinical or purchasing decisions.

## Requirements

- Python 3.12
- Git
- Python dependencies listed in `requirements.txt`

The application uses Streamlit, Pandas, and Plotly.

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

Press `Ctrl+C` in the terminal to stop the application.

For later sessions, run these commands from the project root:

```bash
source .venv/bin/activate
python -m streamlit run app.py
```

## Project structure

| Location | Purpose |
| --- | --- |
| `app.py` | Streamlit entry point, shared data loading, and routing of tabs to role views |
| `src/config.py` | Application labels, stable role IDs, and data paths |
| `src/data/schema.py` | Provisional required fields, numeric fields, and column mapping |
| `src/data/loader.py` | CSV loading and basic validation |
| `src/ui/components.py` | Reusable medication table, stock charts, and feature placeholders |
| `src/ui/navigation.py` | Audience tab creation using centrally configured role labels |
| `src/ui/views/__init__.py` | Mapping of stable role IDs to view functions |
| `src/ui/views/clinical.py` | Clinical availability shell |
| `src/ui/views/procurement_inventory.py` | Procurement and inventory/ordering shell |
| `src/ui/views/warehouse.py` | Warehouse operations shell |
| `src/ui/views/executive.py` | Executive summary shell |
| `src/services/` | Reserved for future inventory logic |
| `pages/` | Reserved folder; current role views use `src/ui/views/` |
| `data/sample_medications.csv` | Synthetic demonstration dataset |
| `tests/` | Reserved for future automated tests |
| `requirements.txt` | Python dependencies |
| `.gitignore` | Files excluded from version control |
| `README.md` | Project scope, setup instructions, and verification guidance |

Empty reserved folders may not appear in a fresh clone because Git tracks files rather than empty directories.

## Application organization

Application labels, role IDs, and data paths are maintained in `src/config.py`.

The data loader reads the sample CSV, applies the column mapping defined in `src/data/schema.py`, checks basic validity, and returns a Pandas DataFrame.

The application loads the dataset once per Streamlit execution and passes it to the role views. Each view selects its relevant columns and uses shared display components.

Each role has a dedicated view module so its content can be refined independently as research requirements change.

## Current infrastructure scope

The current prototype runs locally using CSV files, Python, Streamlit, Pandas, and Plotly.

A database, separate backend/API, production authentication, cloud hosting, live hospital integrations, and ML infrastructure are outside the current foundation and dashboard-shell scope.

Additional infrastructure will be considered only if confirmed project requirements justify it.

## Verification

From the project root, verify data loading:

```bash
python -c "from src.data.loader import load_medications; df = load_medications(); print('Rows:', len(df))"
```

Expected output:

```text
Rows: 6
```

In the running app, verify that:

- All four audience tabs open successfully.
- The Clinical table displays six records with four availability columns.
- The Procurement table displays six records with seven inventory and ordering columns.
- The Warehouse table displays six records with six stock and expiry columns.
- Procurement, Warehouse, and Executive stock charts separate tablets, capsules, and vials.
- Ibuprofen displays zero stock.
- Executive cards display six sample medication records, one record with zero stock, and three demo suppliers.
- Planned-feature sections are clearly labelled.

These are manual verification checks. Automated tests have not yet been added.

## Next development stage

Refine the provisional dashboard sections using confirmed research and client requirements.

Agree on data fields, display labels, KPI definitions, and inventory rules before implementing:

- ABC classification.
- Safety-stock and replenishment calculations.
- Expiry and availability alerts.
- Substitute-product intelligence.
- Executive performance, risk, and cost indicators.

Multiple batches, storage locations, stock movements, and historical reporting will require additional data structures if confirmed in scope.

## Team and contributions

Developed by ELG 5902 Group 5:

- Md Kamrul Hasan Bin Amin
- Maria
- Maryam
- Mohtasim
- Sai Prasanna

The prototype incorporates the team’s research findings, process analysis, inventory frameworks, and dashboard requirements, alongside software implementation.