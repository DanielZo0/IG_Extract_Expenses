import os
import json
from PyPDF2 import PdfReader
import re
from datetime import datetime

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
    amount = text.replace("£", "").replace(",", "").strip()
    try:
        return f"{float(amount):.2f}"
    except ValueError:
        return ""

def parse_pdf_content(text):
    """Parse the extracted text and return structured data"""
    data = {
        "Type": "PI",  # Default value from template
        "Supplier": "AttardCo",  # Based on filename pattern
        "Customer": "",
        "Nominal A/C": "5000",  # Default value from template
        "Date": "",
        "Invoice Number": "",
        "Description": "",
        "Net": "",
        "Tax Code": "",
        "VAT": "",
        "Total": "",
        "Customer Country": ""
    }
    
    # Extract invoice number (assuming format like "Invoice No: XXXX")
    invoice_match = re.search(r'Invoice\s*No[.:]\s*(\w+)', text, re.IGNORECASE)
    if invoice_match:
        data["Invoice Number"] = invoice_match.group(1)
    
    # Extract date (assuming format like "Date: DD/MM/YYYY")
    date_match = re.search(r'Date[.:]\s*(\d{1,2}/\d{1,2}/\d{4})', text, re.IGNORECASE)
    if date_match:
        # Convert date to standard format
        try:
            date_obj = datetime.strptime(date_match.group(1), '%d/%m/%Y')
            data["Date"] = date_obj.strftime('%Y-%m-%d')
        except ValueError:
            data["Date"] = date_match.group(1)
    
    # Extract amounts
    # Net amount
    net_match = re.search(r'Net[:\s]*[£]?(\d+[.,]\d+)', text, re.IGNORECASE)
    if net_match:
        data["Net"] = parse_amount(net_match.group(1))
    
    # VAT amount
    vat_match = re.search(r'VAT[:\s]*[£]?(\d+[.,]\d+)', text, re.IGNORECASE)
    if vat_match:
        data["VAT"] = parse_amount(vat_match.group(1))
        data["Tax Code"] = "T1"  # Standard VAT code
    
    # Total amount
    total_match = re.search(r'Total[:\s]*[£]?(\d+[.,]\d+)', text, re.IGNORECASE)
    if total_match:
        data["Total"] = parse_amount(total_match.group(1))
    
    # Extract customer info (assuming it's between "Bill To:" and the next section)
    customer_match = re.search(r'Bill\s*To:(.*?)(?=Invoice|Date)', text, re.IGNORECASE | re.DOTALL)
    if customer_match:
        customer_info = customer_match.group(1).strip()
        data["Customer"] = customer_info.split('\n')[0].strip()
        # Try to extract country from address
        address_lines = customer_info.split('\n')
        if len(address_lines) > 1:
            data["Customer Country"] = address_lines[-1].strip()
    
    # Extract description (assuming it's the first line item or main text)
    desc_match = re.search(r'Description:(.*?)(?=Amount|Total|Net|VAT)', text, re.IGNORECASE | re.DOTALL)
    if desc_match:
        data["Description"] = desc_match.group(1).strip()
    
    return data

def process_pdfs():
    """Process all PDFs in the Resources directory"""
    resources_dir = "Resources"
    output_dir = "output"
    
    # Create output directory if it doesn't exist
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    # Get all PDF files in Resources directory
    pdf_files = [f for f in os.listdir(resources_dir) if f.endswith('.pdf')]
    
    for pdf_file in pdf_files:
        pdf_path = os.path.join(resources_dir, pdf_file)
        
        try:
            # Extract text from PDF
            text = extract_text_from_pdf(pdf_path)
            
            # Parse the content
            data = parse_pdf_content(text)
            
            # Create output filename based on invoice number or original filename
            output_filename = f"invoice_{data['Invoice Number'] or os.path.splitext(pdf_file)[0]}.json"
            output_path = os.path.join(output_dir, output_filename)
            
            # Save to JSON file
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)
                
            print(f"Successfully processed {pdf_file} -> {output_filename}")
            
        except Exception as e:
            print(f"Error processing {pdf_file}: {str(e)}")

if __name__ == "__main__":
    process_pdfs()
