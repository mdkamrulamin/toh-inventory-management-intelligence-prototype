# (TOH) Inventory Management & Intelligence Prototype

An academic inventory dashboard developed focusing on medication, for the University of Ottawa’s ELG 5902 Industry Project, Group 5.

The prototype demonstrates how medication inventory information can support clinical availability, inventory operations, and executive oversight.

## Prototype status

The current foundation includes:

- A modular Streamlit application.
- A synthetic medication dataset with six demonstration records.
- CSV loading, configurable field mapping, and basic validation.
- An interactive medication inventory table.
- Plotly stock charts grouped by stock unit.

Planned dashboard audiences:

- Clinical — Doctor + Nurse
- Procurement + Inventory/Ordering
- Warehouse
- Executive

Role-specific views are planned for the next implementation stage.

## Demonstration data

`data/sample_medications.csv` contains fictional stock quantities, costs, consumption values, expiry dates, and suppliers.

- `current_stock`: quantity in the row’s `stock_unit`.
- `unit_cost`: demonstration cost in CAD per stock unit.
- `average_monthly_consumption`: demonstration stock units consumed per month.
- `expiry_date`: illustrative expiry date for the sample record.
- `status`: illustrative stock availability label.

Stock charts separate tablets, capsules, and vials because their quantities use different units.

The dataset and field names are provisional and will be refined as the team confirms requirements.

This is an academic decision-support prototype. Demonstration data and representative metrics do not describe actual TOH inventory and must not be used for clinical or purchasing decisions.

## Requirements

- Python 3.12
- Git
- Python dependencies listed in `requirements.txt`

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

For later sessions, activate the existing environment and launch the app:

```bash
source .venv/bin/activate
python -m streamlit run app.py
```

## Project structure

| Location | Purpose |
| --- | --- |
| `app.py` | Streamlit entry point |
| `src/config.py` | Application labels and data paths |
| `src/data/schema.py` | Provisional required fields, numeric fields, and column mapping |
| `src/data/loader.py` | CSV loading and basic validation |
| `src/ui/components.py` | Reusable inventory table and stock charts |
| `src/services/` | Reserved for future inventory logic |
| `pages/` | Reserved for future dashboard pages |
| `data/sample_medications.csv` | Synthetic demonstration dataset |
| `tests/` | Reserved for future automated tests |
| `requirements.txt` | Python dependencies |
| `.gitignore` | Files excluded from version control |

## Verify data loading

From the project root, run:

```bash
python -c "from src.data.loader import load_medications; df = load_medications(); print('Rows:', len(df))"
```

Expected output:

```text
Rows: 6
```

In the running app, verify that:

- The inventory table displays six medications.
- Stock charts appear separately for tablets, capsules, and vials.
- Ibuprofen displays a stock quantity of zero.

## Next development stage

Add a demonstration role selector and separate dashboard views for the four planned audiences. Inventory rules and metrics will be introduced as research findings and project requirements are confirmed.

## Team and contributions

Developed by ELG 5902 Group 5:

- Md Kamrul Hasan Bin Amin
- Maria
- Maryam
- Mohtasim
- Sai Prasanna

The prototype incorporates the team’s research findings, process analysis,
inventory frameworks, and dashboard requirements, alongside software
implementation.