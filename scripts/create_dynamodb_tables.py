#!/usr/bin/env python3
"""
Create DynamoDB tables for Automated Day Trading Application
"""

import boto3
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Get AWS credentials from environment
aws_access_key = os.getenv("AWS_ACCESS_KEY_ID")
aws_secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")
aws_region = os.getenv("AWS_DEFAULT_REGION", "us-east-1")

# Initialize DynamoDB client
dynamodb = boto3.client(
    'dynamodb',
    aws_access_key_id=aws_access_key,
    aws_secret_access_key=aws_secret_key,
    region_name=aws_region
)

def create_table_if_not_exists(table_name, key_schema, attribute_definitions):
    """Create a DynamoDB table if it doesn't already exist"""
    try:
        # Check if table exists
        dynamodb.describe_table(TableName=table_name)
        print(f"✅ Table '{table_name}' already exists")
        return True
    except dynamodb.exceptions.ResourceNotFoundException:
        # Table doesn't exist, create it
        try:
            response = dynamodb.create_table(
                TableName=table_name,
                KeySchema=key_schema,
                AttributeDefinitions=attribute_definitions,
                BillingMode='PAY_PER_REQUEST'  # On-demand billing
            )
            print(f"✅ Created table '{table_name}'")
            return True
        except Exception as e:
            print(f"❌ Error creating table '{table_name}': {str(e)}")
            return False

def main():
    """Create all required DynamoDB tables"""
    print("🚀 Creating DynamoDB tables for Automated Day Trading Application...")
    print(f"📍 Region: {aws_region}\n")
    
    tables_created = 0
    tables_failed = 0
    
    # 1. ActiveTickersForAutomatedDayTrader
    if create_table_if_not_exists(
        table_name='ActiveTickersForAutomatedDayTrader',
        key_schema=[
            {'AttributeName': 'ticker', 'KeyType': 'HASH'}  # Partition key
        ],
        attribute_definitions=[
            {'AttributeName': 'ticker', 'AttributeType': 'S'}
        ]
    ):
        tables_created += 1
    else:
        tables_failed += 1
    
    # 2. CompletedTradesForMarketData
    if create_table_if_not_exists(
        table_name='CompletedTradesForMarketData',
        key_schema=[
            {'AttributeName': 'date', 'KeyType': 'HASH'},  # Partition key
            {'AttributeName': 'ticker_indicator', 'KeyType': 'RANGE'}  # Sort key
        ],
        attribute_definitions=[
            {'AttributeName': 'date', 'AttributeType': 'S'},
            {'AttributeName': 'ticker_indicator', 'AttributeType': 'S'}
        ]
    ):
        tables_created += 1
    else:
        tables_failed += 1
    
    # 3. InactiveTickersForDayTrading
    if create_table_if_not_exists(
        table_name='InactiveTickersForDayTrading',
        key_schema=[
            {'AttributeName': 'ticker', 'KeyType': 'HASH'},  # Partition key
            {'AttributeName': 'indicator', 'KeyType': 'RANGE'}  # Sort key
        ],
        attribute_definitions=[
            {'AttributeName': 'ticker', 'AttributeType': 'S'},
            {'AttributeName': 'indicator', 'AttributeType': 'S'}
        ]
    ):
        tables_created += 1
    else:
        tables_failed += 1
    
    # 4. DayTraderEvents
    if create_table_if_not_exists(
        table_name='DayTraderEvents',
        key_schema=[
            {'AttributeName': 'date', 'KeyType': 'HASH'},  # Partition key
            {'AttributeName': 'indicator', 'KeyType': 'RANGE'}  # Sort key
        ],
        attribute_definitions=[
            {'AttributeName': 'date', 'AttributeType': 'S'},
            {'AttributeName': 'indicator', 'AttributeType': 'S'}
        ]
    ):
        tables_created += 1
    else:
        tables_failed += 1
    
    # 5. MABStats
    if create_table_if_not_exists(
        table_name='MABStats',
        key_schema=[
            {'AttributeName': 'indicator_ticker', 'KeyType': 'HASH'}  # Partition key
        ],
        attribute_definitions=[
            {'AttributeName': 'indicator_ticker', 'AttributeType': 'S'}
        ]
    ):
        tables_created += 1
    else:
        tables_failed += 1
    
    print(f"\n{'='*60}")
    print(f"✅ Tables created/verified: {tables_created}")
    if tables_failed > 0:
        print(f"❌ Tables failed: {tables_failed}")
    print(f"{'='*60}")
    
    if tables_failed == 0:
        print("\n🎉 All DynamoDB tables are ready!")
        print("You can now run the trading application.")
    else:
        print("\n⚠️  Some tables failed to create. Check the errors above.")

if __name__ == "__main__":
    main()
