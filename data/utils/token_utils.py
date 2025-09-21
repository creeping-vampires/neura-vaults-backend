import logging
import os
import csv
from django.conf import settings

logger = logging.getLogger(__name__)

def get_token_info():
    """Read token information from tokens.csv file.
    
    Returns:
        dict: Dictionary mapping token symbols to their information (address, decimals)
    """
    token_info = {}
    try:
        tokens_csv_path = os.path.join(settings.BASE_DIR, 'tokens.csv')
        
        if not os.path.exists(tokens_csv_path):
            logger.error(f"tokens.csv file not found at {tokens_csv_path}")
            return token_info
            
        with open(tokens_csv_path, 'r') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                token_symbol = row.get('Token')
                if token_symbol:
                    token_info[token_symbol] = {
                        'address': row.get('Contract Address'),
                        'decimals': int(row.get('decimals', 18))
                    }
    except Exception as e:
        logger.error(f"Error reading tokens.csv: {str(e)}")
        
    return token_info
