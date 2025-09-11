# IG Extract Expenses

A Python-based tool for extracting expense information from PDF invoices and converting them to structured JSON format.

## Features

- Extracts data from PDF invoices
- Generates standardized JSON output
- Supports batch processing of multiple PDFs
- Handles various invoice fields including:
  - Invoice numbers
  - Dates
  - Customer information
  - Amount details (Net, VAT, Total)
  - Tax codes
  - Descriptions

## Project Structure

```
IG_Extract_Expenses/
├── Resources/           # PDF invoice files
├── output/             # Generated JSON files
├── pdf_to_json_extractor.py
├── requirements.txt
└── README.md
```

## Setup

1. Create and activate a virtual environment:
```bash
# Windows
python -m venv venv
venv\Scripts\activate

# Linux/Mac
python -m venv venv
source venv/bin/activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

## Usage

1. Place your PDF invoices in the `Resources` directory
2. Run the extraction script:
```bash
python pdf_to_json_extractor.py
```
3. Find the generated JSON files in the `output` directory

## JSON Template Structure

```json
{
    "Type": "PI",
    "Supplier": "",
    "Customer": "",
    "Nominal A/C": "5000",
    "Date": "",
    "Invoice Number": "",
    "Description": "",
    "Net": "",
    "Tax Code": "",
    "VAT": "",
    "Total": "",
    "Customer Country": ""
}
```

## Requirements

- Python 3.6+
- PyPDF2>=3.0.0

## License

MIT
