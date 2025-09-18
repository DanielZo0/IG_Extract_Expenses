import os
import json
import logging
from typing import Dict, Any, Optional
from PyPDF2 import PdfReader
import re
from datetime import datetime

def load_config() -> Dict[str, Any]:
    """Load configuration from config.json file"""
    try:
        with open('config.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        logging.warning("config.json not found, using default configuration")
        return {
            "date_overrides": {},
            "supplier": "Attard & Co Food Ltd",
            "customer": "IG International Ltd",
            "nominal_ac": "5000",
            "default_type": "PI"
        }
    except json.JSONDecodeError as e:
        logging.error(f"Error parsing config.json: {str(e)}")
        raise

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,  # Changed to DEBUG level for more detailed output
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('pdf_extraction.log'),
        logging.StreamHandler()
    ]
)

class ValidationError(Exception):
    """Custom exception for data validation errors"""
    pass

def validate_data(data: Dict[str, Any]) -> None:
    """Validate extracted data for consistency and completeness"""
    required_fields = ["Invoice Number", "Date", "Net", "Total"]
    missing_fields = [field for field in required_fields if not data.get(field)]
    
    if missing_fields:
        raise ValidationError(f"Missing required fields: {', '.join(missing_fields)}")
    
    # Validate amounts
    try:
        net = float(data["Net"]) if data["Net"] else 0
        vat = float(data["VAT"]) if data["VAT"] else 0
        total = float(data["Total"]) if data["Total"] else 0
        
        # Check if total matches net + VAT (allowing for small rounding differences)
        if abs((net + vat) - total) > 0.02:  # 2 penny tolerance
            logging.warning(f"Amount mismatch: Net ({net}) + VAT ({vat}) != Total ({total})")
    except ValueError as e:
        raise ValidationError(f"Invalid amount format: {str(e)}")
    
    # Validate date format
    if data["Date"]:
        try:
            datetime.strptime(data["Date"], '%d/%m/%Y')
        except ValueError:
            raise ValidationError(f"Invalid date format: {data['Date']}")
            
def clean_text(text: str) -> str:
    """Clean and normalize extracted text"""
    # Remove multiple spaces and normalize line endings
    text = re.sub(r'\s+', ' ', text)
    # Remove common OCR artifacts
    text = re.sub(r'[^\x00-\x7F]+', '', text)  # Remove non-ASCII characters
    text = re.sub(r'[^\S\n]+', ' ', text)      # Normalize horizontal whitespace
    text = re.sub(r'\n{3,}', '\n\n', text)     # Normalize vertical whitespace
    return text.strip()

def extract_text_from_pdf(pdf_path):
    """Extract text from PDF file"""
    reader = PdfReader(pdf_path)
    text = ""
    for page in reader.pages:
        text += page.extract_text()
    return text

def parse_amount(text):
    """Extract and clean amount values"""
    if not text:
        return ""
    # Remove currency symbols and convert to float
    # Handle different currency symbols and formats
    amount = text.strip()
    amount = re.sub(r'[£$€¥]', '', amount)  # Remove currency symbols
    amount = re.sub(r'[,\s]', '', amount)    # Remove commas and spaces
    amount = re.sub(r'^-$', '0', amount)     # Convert lone dash to 0
    
    # Fix common OCR errors
    amount = amount.replace('i', '1')  # Replace 'i' with '1'
    amount = amount.replace('I', '1')  # Replace 'I' with '1'
    amount = amount.replace('l', '1')  # Replace 'l' with '1'
    amount = amount.replace('O', '0')  # Replace 'O' with '0'
    amount = amount.replace('o', '0')  # Replace 'o' with '0'
    
    try:
        # Handle negative amounts with parentheses
        if amount.startswith('(') and amount.endswith(')'):
            amount = '-' + amount[1:-1]
        
        # Convert to float and format with 2 decimal places
        parsed_amount = float(amount)
        
        # Handle large whole numbers that should have decimal places
        # If it's a whole number > 1000, it might be missing decimal point
        if parsed_amount >= 1000 and parsed_amount == int(parsed_amount):
            # Check if it should be divided by 100 (e.g., 57462 -> 574.62)
            if parsed_amount >= 10000:  # Only for very large numbers
                potential_decimal = parsed_amount / 100
                # If the result seems reasonable for an invoice amount
                if 10 <= potential_decimal <= 10000:
                    return f"{potential_decimal:.2f}"
        
        return f"{parsed_amount:.2f}"
    except ValueError:
        return ""

def parse_pdf_content(text, company_dir: str = ""):
    """Parse the extracted text and return structured data"""
    # Load configuration
    config = load_config()
    
    data = {
        "Type": config.get("default_type", "PI"),
        "Supplier": "",  # Will be set based on directory
        "Customer": config.get("customer", ""),
        "Nominal A/C": config.get("nominal_ac", "5000"),
        "Date": "",
        "Invoice Number": "",
        "Description": "",
        "Net": "",
        "Tax Code": "",
        "VAT": "",
        "Total": "",
        "Customer Country": ""
    }
    
    # Set supplier name based on directory
    if company_dir:
        data["Supplier"] = config.get("suppliers", {}).get(company_dir, company_dir)
    
    # Extract invoice number - prioritize exact "Invoice CBM" format
    if company_dir == "CamelBrand":
        # First, try to find the exact "Invoice CBM" format (highest priority)
        cbm_specific_patterns = [
            r'Invoice\s+CBM\s+(\d{8})',  # Exact format: "Invoice CBM 10228019"
            r'Invoice\s*CBM\s*(\d{8})',  # Without spaces: "Invoice CBM10228019"
            r'Invoice\s+CBM\s+(\d{7})',  # 7-digit format: "Invoice CBM 1022801"
            r'Invoice\s*CBM\s*(\d{7})',  # 7-digit without spaces
            r'Invoice\s+CBM\s+(\d+)',    # Any digits after "Invoice CBM"
            r'Invoice\s*CBM\s*(\d+)',    # Any digits after "Invoice CBM" (no spaces)
        ]
        
        for pattern in cbm_specific_patterns:
            invoice_match = re.search(pattern, text, re.IGNORECASE)
            if invoice_match:
                invoice_num = invoice_match.group(1)
                data["Invoice Number"] = f"CBM{invoice_num}"
                logging.info(f"Found CBM invoice number using pattern '{pattern}': CBM{invoice_num}")
                break
        
        # If no "Invoice CBM" found, try fallback patterns (lower priority)
        if not data["Invoice Number"]:
            fallback_patterns = [
                r'Our\s*Reference[.:\s]*(\d{5})/?',  # Reference number like "23025/"
                r'Our\s*Reference[.:\s]*(\d{5})\s*/',  # Reference number like "23025 /"  
                r'Reference[.:\s]*(\d{5})/?',  # Generic reference
                r'Our\s*Reference[.:\s]*(\d{7,8})/?',  # Longer reference numbers (7-8 digits)
                r'Reference[.:\s]*(\d{7,8})/?',
                r'Order\s*No[.:\s]*(\d{5,8})',  # Order number as fallback
            ]
            for pattern in fallback_patterns:
                ref_match = re.search(pattern, text, re.IGNORECASE)
                if ref_match:
                    ref_num = ref_match.group(1)
                    # Only use numbers that look like invoice numbers and exclude known phone numbers
                    if len(ref_num) >= 5 and ref_num not in ["21466292", "77886661"]:  # Exclude known phone/customer numbers
                        data["Invoice Number"] = f"CBM{ref_num}"
                        logging.info(f"Found CBM invoice number using fallback pattern '{pattern}': CBM{ref_num}")
                        break
    else:
        # For Attard & Co (FD prefix)
        fd_patterns = [
            r'Invoice\s*FD\s*(\d+)',  # Already has FD prefix
            r'Invoice\s*(?:No|Number|#)[.:]\s*FD\s*(\d+)',  # Has FD prefix
            r'Invoice\s*(?:No|Number|#)[.:]\s*(\d+)',  # Need to add prefix
            r'Invoice[.:]\s*(\d+)',  # Need to add prefix
            r'Reference[.:]\s*(\d+)',  # Need to add prefix
            r'Our\s*Reference[.:\s]*(\d+)/?',  # Reference number format
        ]
        
        for pattern in fd_patterns:
            invoice_match = re.search(pattern, text, re.IGNORECASE)
            if invoice_match:
                invoice_num = invoice_match.group(1)
                # Add FD prefix if not already present
                data["Invoice Number"] = f"FD{invoice_num}" if not invoice_num.startswith("FD") else invoice_num
                break
    
    
    # Extract date - handle various formats
    date_patterns = [
        (r'Date[.:]\s*(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})', ['%d/%m/%Y', '%d-%m-%Y', '%d/%m/%y', '%d-%m-%y']),
        (r'Date[.:]\s*(\d{1,2}-[A-Za-z]+-\d{4}\s+\d{2}:\d{2}:\d{2}(?:AM|PM)?)', ['%d-%b-%Y %H:%M:%S', '%d-%b-%Y %I:%M:%S%p']),
        (r'Date[.:]\s*(\d{1,2}-[A-Za-z]+-\d{4})', ['%d-%b-%Y']),
        (r'Date[.:\s]*(\d{1,2}-[A-Za-z]+-\d{4}\s+\d{2}:\d{2}:\d{2})', ['%d-%b-%Y %H:%M:%S']),
        (r'Date[.:\s]*(\d{1,2}-[A-Za-z]+-\d{4}\s+\d{2}\.\d{2}.\d{2}(?:AM|PM)?)', ['%d-%b-%Y %H.%M.%S', '%d-%b-%Y %I.%M.%S%p']),
        (r'Date[.:\s]+(\d{1,2}-[A-Za-z]+-\d{4}\s+\d{2}:\d{2}:\d{2})', ['%d-%b-%Y %H:%M:%S']),  # More flexible spacing
        # Handle date patterns that appear after other fields (like in CamelBrand_0006)
        (r'MT\s+\d+\s+(\d{1,2}-[A-Za-z]+-\d{4}\s+\d{2}:\d{2}:\d{2})', ['%d-%b-%Y %H:%M:%S']),
        (r'(?:Sales Rep|Our Reference|Order No|Delivery By).*?(\d{1,2}-[A-Za-z]+-\d{4}\s+\d{2}:\d{2}:\d{2})', ['%d-%b-%Y %H:%M:%S']),
        # Specific patterns for the failing cases
        (r'Date:\s*Sales Rep:.*?(\d{1,2}-[A-Za-z]{3}-\d{4}\s+\d{2}:\d{2}:\d{2})', ['%d-%b-%Y %H:%M:%S']),  # CamelBrand_0006 pattern
        (r'Date:\s*(\d{1,2}-[A-Za-z]{3}-\d{4}\s+\d{2}:\d{2}:\d{2})', ['%d-%b-%Y %H:%M:%S']),  # CamelBrand_0007 pattern
        # More flexible patterns to catch dates anywhere in the text
        (r'(\d{1,2}-[A-Za-z]{3}-\d{4}\s+\d{2}:\d{2}:\d{2})', ['%d-%b-%Y %H:%M:%S']),  # Generic date with time
        # Even more specific patterns for exact matches
        (r'MT\s+\d+\s+(\d{1,2}-[A-Za-z]{3}-\d{4}\s+\d{2}:\d{2}:\d{2})', ['%d-%b-%Y %H:%M:%S']),  # Pattern like "MT 21827731 4-Aug-2025 14:13:05"
        # Patterns for the failing PDFs with different time formats
        (r'(\d{1,2}-[A-Za-z]{3}-\d{4}\s+\d{2}\.\d{2}\d{2}(?:AM|PM))', ['%d-%b-%Y %H.%M%S%p']),  # Pattern like "25-Aug-2025 01.5418PM"
        (r'(\d{1,2}-[A-Za-z]{3}-\d{4}\s+\d{2}\s+\d{2}\s+\d{2}(?:AM|PM)?)', ['%d-%b-%Y %H %M %S', '%d-%b-%Y %H %M %S%p']),  # Pattern like "25-Aug-2025 01 54 18PM" or "28-Aug-2025 13 56 24"
        (r'Date Due:\s*(\d{1,2}/\d{1,2}/\d{4})', ['%d/%m/%Y']),
        (r'(\d{1,2}(?:st|nd|rd|th)?\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{2,4})', ['%d %B %Y', '%d %b %Y']),
        (r'(\d{4}[-/]\d{1,2}[-/]\d{1,2})', ['%Y-%m-%d', '%Y/%m/%d'])
    ]
    
    for pattern, formats in date_patterns:
        date_match = re.search(pattern, text, re.IGNORECASE)
        if date_match:
            date_str = date_match.group(1)
            # Remove ordinal indicators but keep original separators for proper format matching
            date_str = re.sub(r'(?:st|nd|rd|th)', '', date_str)
            
            for date_format in formats:
                try:
                    date_obj = datetime.strptime(date_str, date_format)
                    data["Date"] = date_obj.strftime('%d/%m/%Y')  # Changed to dd/mm/yyyy format
                    break
                except ValueError:
                    continue
            if data["Date"]:  # If we successfully parsed a date
                break
    
    # Check for date override in configuration
    if data["Invoice Number"] in config.get("date_overrides", {}):
        data["Date"] = config["date_overrides"][data["Invoice Number"]]
    
    # Extract amounts with more flexible patterns
    amount_patterns = {
        "Net": [
            r'Net\s*Amount\s*(?:in\s*EUR\s*)?(\d+\.[\d]+)',  # Handle decimals properly
            r'(?:Net|Subtotal|Sub-total)[:\s]*[£$€]?\s*(\(?[\d,]+\.?[\d]*\)?)',
            r'Amount[:\s]*[£$€]?\s*(\(?[\d,]+\.?[\d]*\)?)',
            r'NetAmount\s*(\d+\.[\d]+)',  # No space variation
            r'Net\s*Amount\s*(?:VAT\s*Amt)?[:\s]*(\d+\.[\d]+)',  # CamelBrand format
            r'Net\s*Amount\s+(\d+\.[\d]+)',  # With spaces
            r'NetAmount\s+(\d+\.[\d]+)',  # NetAmount with space
            r'NetAmount\s+(\d+)(?!\.\d)',  # NetAmount with whole number (no decimal)
            r'Net\s*Amount\s+(\d+)(?!\.\d)',  # Net Amount with whole number
            # Handle patterns like "NetAmount E - 0% 57462"
            r'NetAmount\s+(?:E\s*-\s*0%\s*)?(\d+)(?!\.\d)',
            r'Net\s*Amount\s+(?:E\s*-\s*0%\s*)?(\d+\.[\d]+)',
            # Additional patterns for CamelBrand_0001 type layouts
            r'Net\s*Amount\s*Retail\s*TC.*?(\d+\.?\d*)',  # Pattern with Retail TC
            r'Type[.\s]*Supply\s*by\s*Sale[^0-9]*?(\d+\.?\d*)',  # After "Supply by Sale"
            # More comprehensive patterns for complex layouts
            r'Supply\s*by\s*Sale\s*Net\s*Amount.*?(\d+\.?\d*)',  # After Supply by Sale Net Amount
            r'Net\s*Amount.*?(\d{2,4}\.?\d*)',  # Net Amount with at least 2 digits
            # Handle patterns after VAT summary
            r'E\s*-\s*0%\s*(\d+)(?!\.\d)',  # Pattern like "E - 0% 57462"
            r'0%\s*(\d+)(?!\.\d)'  # Pattern like "0% 57462"
        ],
        "VAT": [
            r'VAT\s*Amt\s*(\d+\.[\d]+)',
            r'VAT\s*Amount\s*(\d+\.[\d]+)',
            r'(?:VAT|Tax)[:\s]*[£$€]?\s*(\(?[\d,]+\.?[\d]*\)?)',
            r'V\.A\.T\.[:\s]*[£$€]?\s*(\(?[\d,]+\.?[\d]*\)?)',
            r'VATAmount\s*(\d+\.[\d]+)',  # No space variation
            r'VAT\s*Amount\s+(\d+\.[\d]+)',  # With spaces
            r'VATAmount\s+(\d+\.[\d]+)',  # VATAmount with space
            r'VAT\s*Amt\s+(\d+\.[\d]+)',  # VAT Amt with space
            r'VAT\s*Amt\s+(\d+\.[\d]+)'  # VAT Amt with space
        ],
        "Total": [
            r'Total\s*Amount\s*in\s*EUR\s*(\d+\.[\d]+)',
            r'(?:Total|Amount Due|Balance Due)[:\s]*[£$€]?\s*(\(?[\d,]+\.?[\d]*\)?)',
            r'Total\s+Amount[:\s]*[£$€]?\s*(\(?[\d,]+\.?[\d]*\)?)',
            r'Total\s*Amount\s*(?:in\s*EUR\s*)?(\d+\.[\d]+)',  # CamelBrand format
            r'Total\s*Amount\s+in\s+EUR\s+(\d+\.[\d]+)',  # With spaces
            r'TotalAmount\s*(\d+\.[\d]+)',  # No space variation
            r'Total\s+Amount\s+in\s+EUR\s+(\d+\.[\d]+)',  # More flexible spacing
            r'Total\s*Amount\s*in\s*EUR\s*(\d+)(?!\.\d)',  # Total with whole number
            # Handle patterns like "Total Amount in EUR Received goods in good order& condition by574.62"
            r'Total\s*Amount\s*in\s*EUR.*?by(\d+\.[\d]+)',
            # Additional patterns for edge cases like CamelBrand_0001
            r'Total\s*(?:Amount\s*)?[:\s]*(\d+\.?\d*)',  # Generic Total pattern
            r'Grand\s*Total[:\s]*(\d+\.?\d*)',  # Grand Total
            r'Balance[:\s]*(\d+\.?\d*)',  # Balance
            # Pattern to match after VAT summary
            r'VAT\s*Amount[^0-9]*?(\d+\.?\d*)',  # After VAT Amount
            r'Total\s*Amount\s*in\s*EUR.*?(\d+\.[\d]+)',  # More flexible
            # Handle patterns in VAT summary
            r'Total\s*Amount\s*in\s*EUR\s+(\d+\.[\d]+)',
            r'EUR\s+(\d+\.[\d]+)'  # Simple EUR pattern
        ]
    }
    
    # Process amounts and set VAT code based on VAT amount
    for field, patterns in amount_patterns.items():
        for pattern in patterns:
            amount_match = re.search(pattern, text, re.IGNORECASE)
            if amount_match:
                amount = parse_amount(amount_match.group(1))
                data[field] = amount
                if field == "VAT":
                    # Set Tax Code based on VAT amount
                    data["Tax Code"] = "T0" if amount == "0.00" else "T1"
                break
    
    # Fallback: Set Total = Net if Total is missing and VAT is 0 or empty
    if not data["Total"] and data["Net"]:
        vat_amount = float(data["VAT"]) if data["VAT"] else 0.0
        if vat_amount == 0.0:
            data["Total"] = data["Net"]
            logging.info(f"Set Total = Net ({data['Net']}) for zero VAT invoice")
    
    # Set fixed customer name as requested
    data["Customer"] = "IG International Ltd"
    
    # Try to extract country from address
    country_patterns = [
        r'(?:QORMI|ZABBAR|MALTA)',  # Common Malta locations
        r'\b(?:UK|USA|UNITED\s+KINGDOM|UNITED\s+STATES|CANADA|AUSTRALIA|MALTA)\b'
    ]
    
    for pattern in country_patterns:
        country_match = re.search(pattern, text, re.IGNORECASE)
        if country_match:
            data["Customer Country"] = "MALTA" if country_match.group().upper() in ["QORMI", "ZABBAR"] else country_match.group().upper()
            break
    
    # Extract description with improved pattern
    # Special handling for Attard & Co invoices with multiple line items
    if company_dir == "Attard&Co":
        # Look for descriptions section and extract all product lines
        desc_section_pattern = r'Description\s*(.*?)(?=Dual\s*Qty|Unit\s*Price|Qty\s*Unit\s*Price)'
        desc_section_match = re.search(desc_section_pattern, text, re.IGNORECASE | re.DOTALL)
        
        if desc_section_match:
            desc_section = desc_section_match.group(1)
            # Extract individual product lines that start with product names
            product_lines = re.findall(r'(Mortadella[^0-9\n]+|[A-Z][a-z]+[^0-9\n]*?)(?=\s*\d+|\n\d+|\s*Q\s*x|$)', desc_section, re.IGNORECASE)
            
            descriptions = []
            for line in product_lines:
                # Clean up the description
                cleaned_desc = line.strip()
                # Remove common patterns
                cleaned_desc = re.sub(r'\s+\d+\s*x\s*\d+.*$', '', cleaned_desc)  # Remove "1 x 2"
                cleaned_desc = re.sub(r'\s+SANT\s+DALMAI.*$', '', cleaned_desc, flags=re.IGNORECASE)
                cleaned_desc = re.sub(r'\s+Dual\s+Qty.*$', '', cleaned_desc, flags=re.IGNORECASE)
                cleaned_desc = re.sub(r'\s+\d+\s*(?:Kgs?|kg).*$', '', cleaned_desc, flags=re.IGNORECASE)
                cleaned_desc = re.sub(r'\s+\d{3,}.*$', '', cleaned_desc)  # Remove numbers like "355"
                cleaned_desc = re.sub(r'\s*\n.*$', '', cleaned_desc)  # Remove everything after newline
                
                if cleaned_desc and len(cleaned_desc) > 3:  # Only add meaningful descriptions
                    descriptions.append(cleaned_desc.strip())
            
            if descriptions:
                data["Description"] = "; ".join(descriptions)
                logging.info(f"Extracted multiple line items for Attard&Co: {data['Description']}")

    # If no description found yet, try general patterns
    if not data["Description"]:
        description_patterns = [
            r'Code\s+Description\s*\w+\s+(.*?)(?=\s*(?:Unit\s*Price|Disc%|Net\s*Amount|Retail|TC|\d+\s*(?:KG|PCS|EA)))',
            r'Description\s*(.*?)(?=\s*(?:Unit\s*Price|Disc%|Net\s*Amount|Retail|TC|\d+\s*(?:KG|PCS|EA)))',
            r'(?:Description|Items|Services)[.:]\s*(.*?)(?=\n\n|\n(?:Amount|Total|Net|VAT))',
            r'(?:Details|Work\s+Description)[.:]\s*(.*?)(?=\n\n|\n(?:Amount|Total|Net|VAT))',
            r'(?<=\n\n)(.*?)(?=\n\n|\n(?:Amount|Total|Net|VAT))'  # Fallback: try to find description between blank lines
        ]
        for pattern in description_patterns:
            desc_match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if desc_match:
                description = desc_match.group(1).strip()
                # Clean up the description
                description = re.sub(r'\s+', ' ', description)  # Normalize whitespace
                description = re.sub(r'^[-*•]\s*', '', description)  # Remove list markers
                # Remove any product codes that might be at the start
                description = re.sub(r'^[A-Z0-9]+\s+', '', description)
                # Remove any quantity information at the end
                description = re.sub(r'\s+\d+(?:\.\d+)?\s*(?:KG|PCS|EA).*$', '', description, flags=re.IGNORECASE)
                # Remove additional product details
                description = re.sub(r'\s+\d+x\d+\s+SANT\s+DALMAI.*$', '', description, flags=re.IGNORECASE)
                description = re.sub(r'\s+Dual\s+Qty\s+Qty.*$', '', description, flags=re.IGNORECASE)
                description = re.sub(r'\s+\d+\s*x\s*\d+.*$', '', description, flags=re.IGNORECASE)
                description = re.sub(r'\s+Q\s*x\s*\d+.*$', '', description, flags=re.IGNORECASE)
                data["Description"] = description.strip()
                break
            
    # If no description found but we have a product code and description in the line items
    if not data["Description"]:
        line_item_match = re.search(r'[A-Z0-9]+\s+(.*?)(?=\s+\d+(?:\.\d+)?\s*(?:KG|PCS|EA))', text, re.IGNORECASE)
        if line_item_match:
            data["Description"] = line_item_match.group(1).strip()
    
    return data

def process_pdfs():
    """Process all PDFs in the Resources directory"""
    resources_dir = "Resources"
    output_dir = "output"
    error_dir = os.path.join(output_dir, "errors")
    
    # Create output directories if they don't exist
    for directory in [output_dir, error_dir]:
        if not os.path.exists(directory):
            os.makedirs(directory)
    
    # Get all PDF files in Resources directory and its subdirectories
    pdf_files = []
    for root, _, files in os.walk(resources_dir):
        for f in files:
            if f.endswith('.pdf'):
                # Store full path relative to resources_dir
                rel_path = os.path.relpath(os.path.join(root, f), resources_dir)
                pdf_files.append(rel_path)
    
    if not pdf_files:
        logging.warning("No PDF files found in Resources directory")
        return
    
    logging.info(f"Found {len(pdf_files)} PDF files to process")
    
    success_count = 0
    error_count = 0
    
    for pdf_file in pdf_files:
        pdf_path = os.path.join(resources_dir, pdf_file)
        # Get the company name from the subdirectory
        company_dir = os.path.dirname(pdf_file)
        if company_dir:
            company_name = os.path.basename(company_dir).replace('&', ' & ')
        logging.info(f"Processing {pdf_file}")
        
        try:
            # Extract text from PDF
            text = extract_text_from_pdf(pdf_path)
            if not text.strip():
                raise ValueError("No text content extracted from PDF")
            
            # Log raw extracted text for debugging
            logging.debug(f"Raw extracted text from {pdf_file}:\n{text}")
            
            # Clean the extracted text
            text = clean_text(text)
            
            # Log cleaned text for debugging
            logging.debug(f"Cleaned text from {pdf_file}:\n{text}")
            
            # Parse the content
            data = parse_pdf_content(text, company_dir)
            
            # Validate the extracted data
            validate_data(data)
            
            # Prepare metadata separately
            metadata = {
                "source_file": pdf_file,
                "extraction_date": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                "version": "1.0",
                "invoice_number": data.get("Invoice Number", ""),
                "supplier": data.get("Supplier", ""),
                "processing_status": "success"
            }
            
            # Create output filenames based on invoice number or original filename
            invoice_number_clean = (data['Invoice Number'] or os.path.splitext(os.path.basename(pdf_file))[0]).replace("/", "_").replace("\\", "_")
            
            # Create company-specific output directories
            company_output_dir = os.path.join(output_dir, company_dir) if company_dir else output_dir
            company_metadata_dir = os.path.join(output_dir, "metadata", company_dir) if company_dir else os.path.join(output_dir, "metadata")
            
            if not os.path.exists(company_output_dir):
                os.makedirs(company_output_dir)
            if not os.path.exists(company_metadata_dir):
                os.makedirs(company_metadata_dir)
            
            # Handle potential duplicate invoice numbers by checking if file already exists
            base_name = invoice_number_clean
            invoice_filename = f"invoice_{base_name}.json"
            metadata_filename = f"metadata_{base_name}.json"
            invoice_path = os.path.join(company_output_dir, invoice_filename)
            metadata_path = os.path.join(company_metadata_dir, metadata_filename)
            
            counter = 1
            while os.path.exists(invoice_path) or os.path.exists(metadata_path):
                # Add counter suffix to make filename unique
                unique_name = f"{base_name}_{counter:02d}"
                invoice_filename = f"invoice_{unique_name}.json"
                metadata_filename = f"metadata_{unique_name}.json"
                invoice_path = os.path.join(company_output_dir, invoice_filename)
                metadata_path = os.path.join(company_metadata_dir, metadata_filename)
                counter += 1
                
                # Log the duplicate detection
                if counter == 2:  # Only log on first duplicate
                    logging.warning(f"Duplicate invoice number detected: {base_name}. Using unique suffix for {pdf_file}")
            
            # Save invoice JSON file (without metadata) - wrapped in array brackets
            with open(invoice_path, 'w', encoding='utf-8') as f:
                json.dump([data], f, indent=4, ensure_ascii=False)
            
            # Save metadata JSON file separately - wrapped in array brackets
            with open(metadata_path, 'w', encoding='utf-8') as f:
                json.dump([metadata], f, indent=4, ensure_ascii=False)
            
            logging.info(f"Successfully processed {pdf_file} -> {invoice_filename} + metadata/{company_dir}/{metadata_filename}")
            success_count += 1
            
        except ValidationError as ve:
            error_count += 1
            logging.error(f"Validation error in {pdf_file}: {str(ve)}")
            # Save detailed error information for review
            error_data = {
                "error_type": "Validation Error",
                "error_message": str(ve),
                "source_file": pdf_file,
                "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                "extracted_data": data,  # Include what was extracted
                "text_sample": text[:1000] if text else "No text extracted",  # First 1000 chars for debugging
                "company_directory": company_dir
            }
            # Save error metadata separately
            error_metadata = {
                "source_file": pdf_file,
                "extraction_date": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                "version": "1.0",
                "invoice_number": data.get("Invoice Number", "") if 'data' in locals() else "",
                "supplier": data.get("Supplier", "") if 'data' in locals() else "",
                "processing_status": "validation_error",
                "error_message": str(ve)
            }
            
            base_filename = os.path.splitext(os.path.basename(pdf_file))[0]
            error_file = os.path.join(error_dir, f"error_{base_filename}.json")
            error_metadata_file = os.path.join(error_dir, f"error_metadata_{base_filename}.json")
            
            with open(error_file, 'w', encoding='utf-8') as f:
                json.dump(error_data, f, indent=4)
            with open(error_metadata_file, 'w', encoding='utf-8') as f:
                json.dump(error_metadata, f, indent=4)
                
        except Exception as e:
            error_count += 1
            logging.error(f"Error processing {pdf_file}: {str(e)}", exc_info=True)
            # Save detailed error information for review
            error_data = {
                "error_type": type(e).__name__,
                "error_message": str(e),
                "source_file": pdf_file,
                "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                "extracted_data": data if 'data' in locals() else {},
                "text_sample": text[:1000] if 'text' in locals() and text else "No text extracted",
                "company_directory": company_dir,
                "traceback": str(e)
            }
            # Save error metadata separately
            error_metadata = {
                "source_file": pdf_file,
                "extraction_date": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                "version": "1.0",
                "invoice_number": data.get("Invoice Number", "") if 'data' in locals() and data else "",
                "supplier": data.get("Supplier", "") if 'data' in locals() and data else "",
                "processing_status": "processing_error",
                "error_message": str(e)
            }
            
            base_filename = os.path.splitext(os.path.basename(pdf_file))[0]
            error_file = os.path.join(error_dir, f"error_{base_filename}.json")
            error_metadata_file = os.path.join(error_dir, f"error_metadata_{base_filename}.json")
            
            with open(error_file, 'w', encoding='utf-8') as f:
                json.dump(error_data, f, indent=4)
            with open(error_metadata_file, 'w', encoding='utf-8') as f:
                json.dump(error_metadata, f, indent=4)
    
    # Log summary
    logging.info(f"Processing complete: {success_count} successful, {error_count} failed")
    if error_count > 0:
        logging.info(f"Check {error_dir} for error details")

if __name__ == "__main__":
    try:
        process_pdfs()
    except Exception as e:
        logging.critical(f"Critical error: {str(e)}", exc_info=True)
